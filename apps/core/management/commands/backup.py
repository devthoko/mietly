from django.core.management.base import BaseCommand, CommandError

from apps.core import backup


class Command(BaseCommand):
    help = "Erstellt ein vollständiges Backup (Datenbank, Dateien, Konfiguration)."

    def add_arguments(self, parser):
        parser.add_argument("--reason", default="", help="Anlass, z. B. vor-update")
        parser.add_argument("--prune", action="store_true", help="Danach alte Backups gemäß Aufbewahrungsregel entfernen")

    def handle(self, *args, reason="", prune=False, **opts):
        try:
            path = backup.create_backup(reason)
        except backup.BackupError as e:
            raise CommandError(str(e))
        self.stdout.write(str(path))
        if prune:
            removed = backup.prune()
            if removed:
                self.stdout.write(f"{len(removed)} alte Backups entfernt.")
