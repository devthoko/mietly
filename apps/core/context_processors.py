import time

from django.conf import settings

from .models import CompanySettings


def mietly(request):
    # In der Entwicklung bei jeder Anfrage neu laden, im Betrieb sorgt der Datei-Hash für frische Dateien.
    asset_version = str(int(time.time())) if settings.DEBUG else settings.MIETLY_VERSION
    ctx = {"MIETLY_VERSION": settings.MIETLY_VERSION, "ASSET_VERSION": asset_version}
    if request.user.is_authenticated:
        ctx["company"] = CompanySettings.get()
    return ctx
