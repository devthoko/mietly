from decimal import Decimal, InvalidOperation

from django import template
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def icon(name, size=18, cls=""):
    return format_html(
        '<svg class="icon {}" width="{}" height="{}" aria-hidden="true"><use href="{}#{}"></use></svg>',
        cls, size, size, static("icons.svg"), name,
    )


def format_euro(value, sign=False):
    if value is None or value == "":
        return ""
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError):
        return value
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    prefix = "−" if value < 0 else ("+" if sign and value > 0 else "")
    return f"{prefix}{text} €"


@register.filter
def euro(value):
    return format_euro(value)


@register.filter
def euro_signed(value):
    return format_euro(value, sign=True)


@register.filter
def percent(value):
    if value is None:
        return ""
    value = Decimal(value).normalize()
    text = f"{value:f}".replace(".", ",")
    return f"{text} %"


@register.filter
def qty(value):
    """Mengen ohne unnötige Nachkommastellen."""
    if value is None:
        return ""
    value = Decimal(value)
    if value == value.to_integral():
        return f"{int(value)}"
    return f"{value.normalize():f}".replace(".", ",")


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _local(value):
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        return timezone.localtime(value)
    return value


@register.filter
def d(value):
    """Datum: 24.10.2026"""
    if not value:
        return ""
    return f"{_local(value):%d.%m.%Y}"


@register.filter
def dt(value):
    """Datum mit Uhrzeit: 24.10.2026, 14:00"""
    if not value:
        return ""
    return f"{_local(value):%d.%m.%Y, %H:%M}"


@register.filter
def dlong(value):
    """Wochentag und Datum: Sa, 24.10.2026"""
    if not value:
        return ""
    value = _local(value)
    return f"{WEEKDAYS[value.weekday()]}, {value:%d.%m.%Y}"


@register.filter
def dtlong(value):
    if not value:
        return ""
    value = _local(value)
    return f"{WEEKDAYS[value.weekday()]}, {value:%d.%m.%Y}, {value:%H:%M} Uhr"


@register.filter
def month_name(value):
    return MONTHS[value - 1]


@register.filter
def relday(value):
    """heute / morgen / in 3 Tagen / vor 2 Tagen"""
    if not value:
        return ""
    value = _local(value)
    day = value.date() if hasattr(value, "date") and callable(value.date) else value
    delta = (day - timezone.localdate()).days
    if delta == 0:
        return "heute"
    if delta == 1:
        return "morgen"
    if delta == -1:
        return "gestern"
    if delta > 1:
        return f"in {delta} Tagen"
    return f"vor {-delta} Tagen"


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    path = context["request"].path
    for prefix in prefixes:
        if prefix == "/" and path == "/":
            return "active"
        if prefix != "/" and path.startswith(prefix):
            return "active"
    return ""


@register.simple_tag(takes_context=True)
def query(context, **kwargs):
    """Aktuelle Query-Parameter mit Änderungen, z. B. für Paginierung."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.filter
def initials(name):
    parts = [p for p in str(name).split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.inclusion_tag("components/field.html")
def field(bound_field, cls="", hint=None):
    return {"f": bound_field, "cls": cls, "hint": hint}


@register.simple_tag
def status_badge(text, tone="neutral"):
    return format_html('<span class="badge badge-{}">{}</span>', tone, text)


@register.filter
def fileuri(path):
    from pathlib import Path

    return Path(path).as_uri() if path else ""


@register.filter
def nl2br_safe(value):
    from django.utils.html import escape

    text = escape(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return mark_safe(text.replace("\n", "<br>"))
