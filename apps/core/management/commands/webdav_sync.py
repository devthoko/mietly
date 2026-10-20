from django.core.management.base import BaseCommand, CommandError

from apps.core.models import CompanySettings
from apps.core.webdav import WebdavError, sync_now


class Command(BaseCommand):
    help = "Überträgt neue Dokumente und das neueste Backup zum WebDAV-Server (falls aktiviert)."

    def handle(self, *args, **opts):
        company = CompanySettings.get()
        if not company.webdav_enabled:
            self.stdout.write("WebDAV-Synchronisierung ist nicht aktiviert.")
            return
        try:
            self.stdout.write(sync_now(company))
        except WebdavError as e:
            raise CommandError(str(e))
