import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mietly.settings")
application = get_wsgi_application()

# Aufwärmen beim Start: gunicorn lädt die Anwendung mit --preload einmal im
# Hauptprozess. Damit nicht jeder Arbeitsprozess seine erste Anfrage mit dem
# Laden der Seitenlogik und der PDF-Bibliothek (≈0,5 s) verbringt, geschieht
# das hier – die Prozesse übernehmen alles fertig geladen.
from django.urls import get_resolver  # noqa: E402

get_resolver().url_patterns
import apps.documents.pdf  # noqa: E402,F401
