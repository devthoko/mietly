from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

PUBLIC_PREFIXES = ("/anmelden", "/static/", "/favicon.ico", "/healthz", "/speculation-rules.json")


class LoginRequiredMiddleware:
    """Alle Seiten außer der Anmeldung erfordern einen angemeldeten Benutzer."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(PUBLIC_PREFIXES):
            login_url = reverse(settings.LOGIN_URL)
            if request.headers.get("HX-Request"):
                resp = HttpResponse(status=204)
                resp["HX-Redirect"] = login_url
                return resp
            return redirect(f"{login_url}?next={request.get_full_path()}")
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Zusätzliche Sicherheits-Header. Alle Ressourcen werden lokal ausgeliefert."""

    CSP = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; frame-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if request.user.is_authenticated:
            # Nicht zwischenspeichern ohne Rückfrage beim Server (immer aktuelle Daten), aber
            # Vorab-Laden und den Zurück-Cache des Browsers erlauben – das macht die Bedienung schnell.
            response.setdefault("Cache-Control", "private, no-cache")
            if request.method == "GET" and response.get("Content-Type", "").startswith("text/html") and not request.headers.get("HX-Request"):
                response.setdefault("Speculation-Rules", '"/speculation-rules.json"')
        return response


class RequestCacheMiddleware:
    """Zwischenspeicher, der genau eine Anfrage lang lebt (z. B. Betriebseinstellungen).
    Hintergrund-Threads und Befehle laufen ohne ihn und lesen immer frisch."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .models import _settings_cache

        token = _settings_cache.set({})
        try:
            return self.get_response(request)
        finally:
            _settings_cache.reset(token)


class SessionRefreshMiddleware:
    """Gleitender Ablauf der Anmeldung ohne Schreibzugriff bei jedem Seitenaufruf:
    Die Sitzung wird nur gespeichert (und damit verlängert), wenn die letzte
    Verlängerung länger als SESSION_REFRESH_SECONDS zurückliegt."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        import time

        from django.conf import settings

        response = self.get_response(request)
        session = getattr(request, "session", None)
        if session is not None and not session.is_empty() and session.session_key:
            now = int(time.time())
            if now - int(session.get("_refreshed", 0)) >= getattr(settings, "SESSION_REFRESH_SECONDS", 300):
                session["_refreshed"] = now
        return response
