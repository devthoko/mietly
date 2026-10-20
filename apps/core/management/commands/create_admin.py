import getpass
import os

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.core.models import User


class Command(BaseCommand):
    help = "Legt ein Administrator-Konto an (interaktiv oder per --username/--password-env)."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--first-name", default="")
        parser.add_argument("--password-env", help="Name einer Umgebungsvariable mit dem Passwort (für automatische Installation)")

    def handle(self, *args, username=None, first_name="", password_env=None, **opts):
        username = username or input("Benutzername: ").strip()
        if not username:
            raise CommandError("Kein Benutzername angegeben.")
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"Der Benutzer „{username}“ existiert bereits.")
        if password_env:
            password = os.environ.get(password_env, "")
        else:
            password = getpass.getpass("Passwort (mind. 10 Zeichen): ")
            if password != getpass.getpass("Passwort wiederholen: "):
                raise CommandError("Die Passwörter stimmen nicht überein.")
        user = User(username=username, first_name=first_name, role=User.Role.ADMIN)
        try:
            password_validation.validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Administrator „{username}“ wurde angelegt."))
