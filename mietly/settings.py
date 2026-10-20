"""
Django-Einstellungen für mietly.

Alle betriebsspezifischen Werte kommen aus Umgebungsvariablen, die im Betrieb
aus /etc/mietly/mietly.env geladen werden (systemd EnvironmentFile bzw. das
Verwaltungsskript `mietly`). Quellcode, Konfiguration und Daten bleiben so
sauber getrennt.
"""

import os
from pathlib import Path

from .version import VERSION

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(f"MIETLY_{name}", default)


def env_bool(name, default=False):
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


DEBUG = env_bool("DEBUG", False)
TESTING = env_bool("TESTING", False)

SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise RuntimeError("MIETLY_SECRET_KEY ist nicht gesetzt (siehe /etc/mietly/mietly.env).")

# Schlüssel für verschlüsselt gespeicherte Zugangsdaten (SMTP, WebDAV).
ENCRYPTION_KEY = env("ENCRYPTION_KEY", "")

ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

DATA_DIR = Path(env("DATA_DIR", str(BASE_DIR / "var")))
BACKUP_DIR = Path(env("BACKUP_DIR", "/var/backups/mietly"))
MEDIA_ROOT = DATA_DIR / "media"
MEDIA_URL = "/medien/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Im Betrieb erhalten statische Dateien einen Inhalts-Hash im Namen (sicheres Caching nach Updates).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if (DEBUG or TESTING) else "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
    },
}

# Geschützte Dateien werden nach der Berechtigungsprüfung per X-Accel-Redirect
# von nginx ausgeliefert. Ohne nginx (Entwicklung/Tests) liefert Django selbst.
USE_X_ACCEL = env_bool("USE_X_ACCEL", False)

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_htmx",
    "apps.core",
    "apps.customers",
    "apps.catalog",
    "apps.orders",
    "apps.documents",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestCacheMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.SessionRefreshMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.LoginRequiredMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "mietly.urls"
WSGI_APPLICATION = "mietly.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.mietly",
            ],
            "builtins": ["apps.core.templatetags.ui"],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "mietly"),
        "USER": env("DB_USER", ""),
        "PASSWORD": env("DB_PASSWORD", ""),
        # Leer = Unix-Socket mit Peer-Authentifizierung (kein Passwort nötig).
        "HOST": env("DB_HOST", ""),
        "PORT": env("DB_PORT", ""),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "ATOMIC_REQUESTS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "core.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:login"

# Anmeldeschutz: nach 5 Fehlversuchen 15 Minuten Sperre je Benutzername/IP.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15

SESSION_COOKIE_AGE = 60 * 60 * 10  # 10 Stunden (ein Arbeitstag)
# Sitzung gleitend verlängern, aber höchstens alle 5 Minuten speichern (SessionRefreshMiddleware)
SESSION_SAVE_EVERY_REQUEST = False
SESSION_REFRESH_SECONDS = 300
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE = env_bool("SECURE", not DEBUG)
SESSION_COOKIE_SECURE = SECURE
CSRF_COOKIE_SECURE = SECURE
if SECURE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# SAMEORIGIN, damit PDFs auf der Unterschriftsseite eingebettet angezeigt werden können.
X_FRAME_OPTIONS = "SAMEORIGIN"
SILENCED_SYSTEM_CHECKS = [
    "security.W004",  # HSTS: bei selbstsignierten Zertifikaten im LAN bewusst nicht gesetzt
    "security.W008",  # HTTP→HTTPS-Weiterleitung übernimmt nginx
    "security.W019",  # X-Frame-Options SAMEORIGIN (siehe oben)
]

LANGUAGE_CODE = "de"
LANGUAGES = [("de", "Deutsch")]
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True
# Aus: sonst würden auch IDs in Formularen als „1.000“ ausgegeben. Beträge formatiert der Filter |euro selbst.
USE_THOUSAND_SEPARATOR = False

DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750
MAX_UPLOAD_MB = 20

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

MIETLY_VERSION = VERSION

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
}
