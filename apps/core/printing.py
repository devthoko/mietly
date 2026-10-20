"""Drucken über das lokale CUPS.

mietly richtet genau eine Druckerwarteschlange („mietly“) ein. Der Drucker wird
per IP-Adresse angegeben; der passende Treiber wird automatisch gewählt:

1. Treiberlos (IPP Everywhere / AirPrint) – fast alle Netzwerkdrucker ab ca. 2013
2. Modell per SNMP erkennen und den passenden installierten Treiber wählen
   (HPLIP, Gutenprint, brlaser), Druck über Port 9100

Der Dienstbenutzer ``mietly`` ist Mitglied der Gruppe ``lpadmin`` und darf die
Warteschlange deshalb selbst anlegen. CUPS lauscht nur lokal.
"""

import os
import re
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass

from django.utils import timezone

QUEUE = "mietly"
HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$")
IPP_PATHS = ["/ipp/print", "/ipp", "/"]
SNMP_BACKEND = "/usr/lib/cups/backend/snmp"


class PrinterError(Exception):
    pass


@dataclass
class Probe:
    host: str
    port: int | None
    ipp_uri: str = ""
    everywhere: bool = False
    make_model: str = ""
    raw_port_open: bool = False


def _env():
    env = dict(os.environ)
    env.update({"LC_ALL": "C", "LANG": "C"})
    return env


def _run(args, timeout=30, check=True):
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env())
    except FileNotFoundError:
        raise PrinterError("Das Drucksystem (CUPS) ist auf dem Server nicht installiert. Bitte das mietly-Update erneut ausführen.")
    except subprocess.TimeoutExpired:
        raise PrinterError("Der Drucker hat nicht rechtzeitig geantwortet.")
    if check and res.returncode != 0:
        msg = (res.stderr or res.stdout).strip().splitlines()
        raise PrinterError(msg[-1] if msg else f"{args[0]} ist fehlgeschlagen.")
    return res


def parse_host(value):
    value = (value or "").strip()
    for prefix in ("http://", "https://", "ipp://", "ipps://", "socket://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/", 1)[0]
    if not HOST_RE.match(value):
        raise PrinterError("Bitte eine gültige IP-Adresse oder einen Hostnamen angeben, z. B. 192.168.1.50.")
    host, _, port = value.partition(":")
    return host, int(port) if port else None


def _port_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe(value) -> Probe:
    """Fragt den Drucker ab: IPP-Fähigkeiten, Modell, offene Druckports."""
    host, port = parse_host(value)
    p = Probe(host=host, port=port)
    ipp_port = port or 631
    if _port_open(host, ipp_port):
        for path in IPP_PATHS:
            uri = f"ipp://{host}:{ipp_port}{path}"
            res = _run(["ipptool", "-tv", "-T", "8", uri, "get-printer-attributes.test"], timeout=20, check=False)
            if res.returncode != 0 and "printer-make-and-model" not in res.stdout:
                continue
            p.ipp_uri = uri
            m = re.search(r"printer-make-and-model \([^)]*\) = (.+)", res.stdout)
            if m:
                p.make_model = m.group(1).strip()
            formats = re.search(r"document-format-supported \([^)]*\) = (.+)", res.stdout)
            fmt = formats.group(1) if formats else ""
            # IPP Everywhere / AirPrint: Rasterformate, die CUPS ohne Herstellertreiber erzeugen kann
            p.everywhere = any(f in fmt for f in ("image/pwg-raster", "image/urf", "application/pdf"))
            break
    if port is None:
        p.raw_port_open = _port_open(host, 9100)
        if not p.make_model and os.path.exists(SNMP_BACKEND):
            res = _run([SNMP_BACKEND, host], timeout=20, check=False)
            m = re.search(r'^\S+ \S+ "[^"]*" "([^"]+)"', res.stdout, re.M)
            if m:
                p.make_model = m.group(1).strip()
    return p


def find_driver(make_model):
    """Passenden installierten Treiber (PPD) zum Modell suchen."""
    if not make_model:
        return None
    candidates = []
    words = make_model.split()
    # Mit dem vollständigen Namen beginnen und schrittweise allgemeiner suchen
    for n in range(len(words), 1, -1):
        res = _run(["lpinfo", "--make-and-model", " ".join(words[:n]), "-m"], timeout=60, check=False)
        candidates = [line.split(" ", 1) for line in res.stdout.splitlines() if " " in line]
        candidates = [c for c in candidates if not c[0].startswith(("everywhere", "driverless")) and "Generic" not in c[1]]
        if candidates:
            break
    if not candidates:
        return None

    def rank(c):
        name, desc = c
        score = 0
        if "recommended" in desc.lower():
            score -= 10
        if "hpcups" in desc.lower() or "hpcups" in name:
            score -= 5
        return score

    name, desc = sorted(candidates, key=rank)[0]
    return name, desc


def setup(value):
    """Richtet die Warteschlange ein. Gibt (uri, treiberbeschreibung) zurück."""
    p = probe(value)
    if p.ipp_uri and p.everywhere:
        uri, model, driver = p.ipp_uri, "everywhere", "Treiberlos (IPP Everywhere)"
    else:
        found = find_driver(p.make_model)
        if found and (p.raw_port_open or p.ipp_uri):
            model, driver = found
            uri = f"socket://{p.host}:9100" if p.raw_port_open else p.ipp_uri
        elif p.ipp_uri or p.raw_port_open:
            what = f"„{p.make_model}“" if p.make_model else "ein Drucker"
            raise PrinterError(f"Unter dieser Adresse antwortet {what}, aber es wurde kein passender Treiber gefunden. "
                               "Bitte prüfen, ob der Drucker AirPrint bzw. IPP Everywhere unterstützt und dies im Drucker-Menü aktiviert ist.")
        else:
            raise PrinterError(f"Unter {value} wurde kein Drucker gefunden. Ist der Drucker eingeschaltet und im selben Netzwerk?")
    _run(["lpadmin", "-p", QUEUE, "-E", "-v", uri, "-m", model,
          "-D", "mietly", "-o", "printer-error-policy=abort-job", "-o", "media-default=iso_a4_210x297mm",
          "-o", "printer-is-shared=false"], timeout=90)
    _run(["cupsenable", QUEUE], check=False)
    _run(["cupsaccept", QUEUE], check=False)
    return uri, driver, p.make_model


def remove():
    _run(["lpadmin", "-x", QUEUE], check=False)


def queue_exists():
    res = _run(["lpstat", "-p", QUEUE], timeout=10, check=False)
    return res.returncode == 0


def print_file(path, title, copies=1):
    """Druckauftrag abschicken (kehrt sofort zurück). Gibt die Auftragsnummer zurück."""
    if not queue_exists():
        raise PrinterError("Es ist kein Drucker eingerichtet (Einstellungen → Drucker).")
    _run(["cupsenable", QUEUE], check=False)  # nach einem Fehler wieder freigeben
    res = _run(["lp", "-d", QUEUE, "-n", str(max(1, min(int(copies), 20))), "-t", title[:120], "--", str(path)], timeout=30)
    m = re.search(r"request id is (\S+)", res.stdout)
    return m.group(1) if m else ""


def job_state(job_id):
    """completed, aborted, canceled, pending, processing …"""
    num = job_id.rsplit("-", 1)[-1]
    res = _run(["ipptool", "-tv", "-T", "5", f"ipp://localhost/jobs/{num}", "get-job-attributes.test"], timeout=10, check=False)
    m = re.search(r"job-state \(enum\) = (\S+)", res.stdout)
    reasons = re.search(r"job-printer-state-message \([^)]*\) = (.+)", res.stdout)
    return (m.group(1) if m else "unknown"), (reasons.group(1).strip() if reasons else "")


def printer_message():
    res = _run(["lpstat", "-l", "-p", QUEUE], timeout=10, check=False)
    lines = [l.strip() for l in res.stdout.splitlines()[1:] if l.strip() and not l.strip().startswith(("Description", "Alerts", "Location", "Connection", "Interface", "On fault", "After fault", "Users", "Forms", "Banner", "Charset", "Printer types"))]
    return " ".join(lines)


def test_page(company_name, wait=25):
    """Testseite drucken und auf das Ergebnis warten. Gibt (ok, text) zurück."""
    from weasyprint import HTML

    now = timezone.localtime().strftime("%d.%m.%Y, %H:%M Uhr")
    html = f"""<html><head><meta charset="utf-8"><style>
      @page {{ size: A4; margin: 25mm }} body {{ font-family: 'Source Sans 3', sans-serif; color: #2e2823 }}
      h1 {{ font-family: 'EB Garamond', serif; font-weight: 500; font-size: 30pt; margin: 0 0 6mm }}
      .box {{ border: 1px solid #c9bfb3; border-radius: 4mm; padding: 8mm; margin-top: 10mm }}
    </style></head><body><h1>Testseite</h1>
    <p>Dieser Drucker ist in <strong>mietly</strong> für {company_name} eingerichtet.</p>
    <p>Gedruckt am {now}.</p>
    <div class="box">Angebote, Verträge, Rechnungen und Protokolle können jetzt direkt aus mietly gedruckt werden.</div>
    </body></html>"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(HTML(string=html).write_pdf())
        path = tmp.name
    try:
        job = print_file(path, "mietly Testseite")
        deadline = time.monotonic() + wait
        state, msg = "pending", ""
        while time.monotonic() < deadline:
            state, msg = job_state(job)
            if state in ("completed", "aborted", "canceled"):
                break
            time.sleep(1)
    finally:
        os.unlink(path)
    if state == "completed":
        return True, "Die Testseite wurde an den Drucker übertragen."
    if state in ("aborted", "canceled"):
        return False, "Die Testseite konnte nicht gedruckt werden" + (f": {msg}" if msg else ".")
    detail = msg or printer_message()
    _run(["cancel", job], check=False)  # nicht später unerwartet ausdrucken
    return False, "Die Testseite wurde nicht gedruckt" + (f" ({detail})" if detail else "") + ". Ist der Drucker eingeschaltet und erreichbar?"
