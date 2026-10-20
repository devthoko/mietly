from functools import wraps

from django.core.exceptions import PermissionDenied


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_admin):
            raise PermissionDenied("Nur für Administratoren.")
        return view(request, *args, **kwargs)

    return wrapper


def client_ip(request):
    # nginx setzt X-Real-IP; direkter Zugriff fällt auf REMOTE_ADDR zurück.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR")
