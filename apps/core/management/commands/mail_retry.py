from django.core.management.base import BaseCommand

from apps.core.mail import retry_due


class Command(BaseCommand):
    help = "Versendet E-Mails, deren Zustellung wiederholt werden soll."

    def handle(self, *args, **options):
        count = retry_due()
        if count:
            self.stdout.write(f"{count} E-Mail(s) versucht.")
