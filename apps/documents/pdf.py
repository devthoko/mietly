"""PDF-Erzeugung mit WeasyPrint (HTML/CSS → PDF).

Externe Ressourcen werden nicht geladen: Der URL-Fetcher erlaubt nur lokale
Dateien aus den Verzeichnissen von mietly.
"""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from weasyprint import HTML, URLFetcher

TEMPLATES = {
    "offer": "pdf/offer.html",
    "contract": "pdf/contract.html",
    "invoice": "pdf/invoice.html",
    "packing_list": "pdf/packing_list.html",
    "handover": "pdf/handover.html",
    "return": "pdf/return.html",
    "deposit": "pdf/deposit.html",
}


def _allowed_roots():
    roots = [Path(settings.MEDIA_ROOT), Path(settings.BASE_DIR) / "static", Path("/usr/share/fonts")]
    return [r.resolve() for r in roots]


class LocalFetcher(URLFetcher):
    def __init__(self):
        # Fehlende Bilder (z. B. gelöschtes Foto) sollen das Dokument nicht verhindern
        super().__init__(allowed_protocols={"file"}, fail_on_errors=False)

    def fetch(self, url, headers=None):
        from urllib.parse import unquote, urlparse

        if not url.startswith("file://"):
            raise ValueError(f"Externe Ressource blockiert: {url}")
        path = Path(unquote(urlparse(url).path)).resolve()
        if not any(root == path or root in path.parents for root in _allowed_roots()):
            raise ValueError(f"Datei außerhalb der erlaubten Verzeichnisse: {path}")
        return super().fetch(url, headers)


def render_pdf(kind, data, signature=None) -> bytes:
    html = render_to_string(TEMPLATES[kind], {
        "d": data,
        "sig": signature,
        "css_path": (Path(settings.BASE_DIR) / "static" / "pdf" / "pdf.css").as_uri(),
    })
    # Das typografische Minuszeichen (U+2212) fehlt in EB Garamond und wird
    # sonst als fremdes Zeichen dargestellt – im PDF den Halbgeviertstrich nutzen.
    html = html.replace("−", "–")
    base = (Path(settings.BASE_DIR) / "static").as_uri() + "/"
    return HTML(string=html, base_url=base, url_fetcher=LocalFetcher()).write_pdf()
