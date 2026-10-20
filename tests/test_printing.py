"""Drucker einbinden und Dokumente drucken (CUPS wird in den Tests ersetzt)."""

import pytest

from apps.core import printing
from apps.core.models import AuditLog, CompanySettings
from apps.documents import services as docs


def test_parse_host_accepts_ip_hostname_and_port():
    assert printing.parse_host("192.168.1.50") == ("192.168.1.50", None)
    assert printing.parse_host(" http://drucker.lan/ ") == ("drucker.lan", None)
    assert printing.parse_host("10.0.0.7:631") == ("10.0.0.7", 631)
    for bad in ["", "192.168.1.50; rm -rf /", "-v", "a b"]:
        with pytest.raises(printing.PrinterError):
            printing.parse_host(bad)


def test_setup_prefers_driverless(monkeypatch):
    calls = []
    monkeypatch.setattr(printing, "probe", lambda v: printing.Probe(host="10.0.0.7", port=None, ipp_uri="ipp://10.0.0.7:631/ipp/print",
                                                                     everywhere=True, make_model="Brother HL-L2350DW"))
    monkeypatch.setattr(printing, "_run", lambda args, **kw: calls.append(args))
    uri, driver, model = printing.setup("10.0.0.7")
    assert driver.startswith("Treiberlos") and model == "Brother HL-L2350DW"
    lpadmin = calls[0]
    assert lpadmin[:2] == ["lpadmin", "-p"] and "everywhere" in lpadmin and uri in lpadmin


def test_setup_uses_model_driver_when_not_driverless(monkeypatch):
    calls = []
    monkeypatch.setattr(printing, "probe", lambda v: printing.Probe(host="10.0.0.8", port=None, make_model="HP LaserJet 1022", raw_port_open=True))
    monkeypatch.setattr(printing, "find_driver", lambda m: ("drv:///hpcups.drv/hp-laserjet_1022.ppd", "HP LaserJet 1022, hpcups"))
    monkeypatch.setattr(printing, "_run", lambda args, **kw: calls.append(args))
    uri, driver, _ = printing.setup("10.0.0.8")
    assert uri == "socket://10.0.0.8:9100" and "hpcups" in driver


def test_setup_reports_missing_printer(monkeypatch):
    monkeypatch.setattr(printing, "probe", lambda v: printing.Probe(host="10.0.0.9", port=None))
    with pytest.raises(printing.PrinterError, match="kein Drucker gefunden"):
        printing.setup("10.0.0.9")


def test_settings_page_sets_up_printer_and_prints_test_page(client, admin, company, monkeypatch):
    monkeypatch.setattr(printing, "setup", lambda host: ("ipp://10.0.0.7:631/ipp/print", "Treiberlos (IPP Everywhere)", "Brother HL"))
    monkeypatch.setattr(printing, "test_page", lambda name: (True, "Die Testseite wurde an den Drucker übertragen."))
    client.force_login(admin)
    r = client.post("/einstellungen/drucker/", {"action": "setup", "printer_host": "10.0.0.7"})
    assert r.status_code == 302
    c = CompanySettings.get()
    assert c.printer_ready and c.printer_host == "10.0.0.7" and c.printer_model == "Brother HL"
    assert c.printer_last_test is not None and "übertragen" in c.printer_last_result


def test_settings_page_shows_error(client, admin, company, monkeypatch):
    def fail(host):
        raise printing.PrinterError("Unter 10.0.0.9 wurde kein Drucker gefunden.")

    monkeypatch.setattr(printing, "setup", fail)
    client.force_login(admin)
    r = client.post("/einstellungen/drucker/", {"action": "setup", "printer_host": "10.0.0.9"})
    assert r.status_code == 200 and "kein Drucker gefunden" in r.content.decode()
    assert not CompanySettings.get().printer_ready


def test_printer_settings_admin_only(client, staff):
    client.force_login(staff)
    assert client.get("/einstellungen/drucker/").status_code in (302, 403)


def test_print_button_and_print(client, order, admin, monkeypatch):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    page = client.get(order.get_absolute_url() + "?schritt=offer").content.decode()
    assert f"/dokumente/{offer.pk}/drucken/" not in page  # noch kein Drucker

    c = CompanySettings.get()
    c.printer_ready = True
    c.printer_host = "10.0.0.7"
    c.save()
    page = client.get(order.get_absolute_url() + "?schritt=offer").content.decode()
    assert f"/dokumente/{offer.pk}/drucken/" in page

    sent = {}
    monkeypatch.setattr(printing, "print_file", lambda path, title, copies=1: sent.update(path=path, title=title) or "mietly-7")
    r = client.post(f"/dokumente/{offer.pk}/drucken/", {"next": order.get_absolute_url()})
    assert r.status_code == 302 and r.url == order.get_absolute_url()
    assert sent["path"] == offer.file.path and sent["title"] == offer.display_name
    assert AuditLog.objects.filter(action="print", order=order).exists()


def test_print_without_printer_shows_error(client, order, admin):
    offer = docs.create_offer(order, admin)
    client.force_login(admin)
    r = client.post(f"/dokumente/{offer.pk}/drucken/", follow=True)
    assert "noch kein Drucker eingerichtet" in r.content.decode()


def test_print_rejects_external_redirect(client, order, admin, monkeypatch):
    offer = docs.create_offer(order, admin)
    c = CompanySettings.get()
    c.printer_ready = True
    c.save()
    monkeypatch.setattr(printing, "print_file", lambda *a, **k: "mietly-8")
    client.force_login(admin)
    r = client.post(f"/dokumente/{offer.pk}/drucken/", {"next": "https://evil.example/"})
    assert r.url.startswith("/auftraege/")
