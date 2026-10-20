import calendar as pycal
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import audit
from .forms import (
    CompanyForm, LoginForm, MailForm, PasswordChangeForm, ProfileForm, RulesForm, TaxBankForm,
    TestMailForm, TextTemplateForm, UserForm, WebdavForm,
)
from .mail import MailError, send_mail
from .models import AuditLog, CompanySettings, EmailLog, LoginAttempt, TextTemplate, User
from .permissions import admin_required, client_ip
from .textrender import PLACEHOLDERS, render_html

# --------------------------------------------------------------------------
# Anmeldung
# --------------------------------------------------------------------------


def _locked(username, ip):
    since = timezone.now() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
    q = LoginAttempt.objects.filter(created_at__gte=since)
    return (
        q.filter(username__iexact=username).count() >= settings.LOGIN_MAX_ATTEMPTS
        or (ip and q.filter(ip=ip).count() >= settings.LOGIN_MAX_ATTEMPTS * 3)
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        ip = client_ip(request)
        if _locked(username, ip):
            error = f"Zu viele Fehlversuche. Bitte warten Sie {settings.LOGIN_LOCK_MINUTES} Minuten."
        else:
            user = authenticate(request, username=username, password=form.cleaned_data["password"])
            if user is not None:
                LoginAttempt.objects.filter(username__iexact=username).delete()
                login(request, user)
                audit.log(user, "login", "Angemeldet")
                nxt = request.GET.get("next") or ""
                if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(nxt)
                return redirect("core:dashboard")
            LoginAttempt.objects.create(username=username, ip=ip)
            LoginAttempt.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
            error = "Benutzername oder Passwort ist nicht korrekt."
    return render(request, "auth/login.html", {"form": form, "error": error})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "Sie wurden abgemeldet.")
    return redirect("core:login")


def media(request, path):
    """Hochgeladene Dateien nur für angemeldete Benutzer (Prüfung durch Middleware)."""
    from pathlib import Path

    from .files import protected_file_response

    return protected_file_response(Path(settings.MEDIA_ROOT) / path, Path(path).name, inline=True)


def healthz(request):
    from django.db import connection

    with connection.cursor() as c:
        c.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


# --------------------------------------------------------------------------
# Übersicht
# --------------------------------------------------------------------------


# Je Aufgabengruppe nur die ersten Einträge zeigen – der Rest ist über die Auftragsliste erreichbar
ATTENTION_LIMIT = 8


def dashboard(request):
    from django.db.models import Prefetch

    from apps.documents.models import Document
    from apps.orders.models import Order
    from apps.orders import workflow

    today = timezone.localdate()
    company = CompanySettings.get()
    # Alle Kennzahlen mit wenigen Abfragen: Summen per Unterabfrage, Status aus dem
    # gespeicherten Kurzstatus (workflow.refresh_stage), offene Dokumente vorab geladen.
    open_docs = Prefetch(
        "documents",
        queryset=Document.objects.filter(kind__in=["offer", "contract"], status=Document.Status.ISSUED).order_by("-version"),
        to_attr="open_docs",
    )
    active = list(
        workflow.with_money(Order.objects.filter(status=Order.Status.ACTIVE))
        .select_related("customer", "handover", "return_record")
        .prefetch_related(open_docs)
        .order_by("event_date", "created_at")
    )

    receivables = Decimal("0")
    deposits_held = Decimal("0")
    attention = {"sign": [], "unpaid": [], "handover": [], "overdue": [], "close": [], "money": []}
    for o in active:
        bal, held = workflow.money_of(o)
        if bal > 0:
            receivables += bal
        deposits_held += held
        stage = o.stage
        if stage in (3, 4):
            kind = "offer" if stage == 3 else "contract"
            doc = next((d for d in o.open_docs if d.kind == kind), None)
            if doc is not None:
                attention["sign"].append((o, doc))
        if stage == 5 and o._invoiced > 0:
            attention["unpaid"].append((o, bal))
        deposit_blocked = company.deposit_required_before_handover and o.deposit_amount > o._dep_received
        if stage in (6, 7) and not deposit_blocked and o.next_action not in ("Wartet auf Zahlung", "Wartet auf Kaution"):
            attention["handover"].append(o)
        if stage == 8 and o.return_at and timezone.localtime(o.return_at).date() < today:
            attention["overdue"].append(o)
        if stage == 9:
            label = "Zahlung abwarten" if o.next_action == "Wartet auf Zahlung" else (o.next_action or "Auftrag abschließen")
            attention["close"].append((o, label))

    # Stornierte oder abgeschlossene Aufträge, bei denen noch Geld fließen muss
    # (z. B. Erstattung nach Stornierung oder offene Stornogebühr)
    inactive = workflow.with_money(
        Order.objects.exclude(status=Order.Status.ACTIVE).filter(created_at__gte=timezone.now() - timedelta(days=730))
    ).select_related("customer")
    for o in inactive:
        bal, held = workflow.money_of(o)
        issue = workflow.money_issue(o, bal, held)
        if issue is None:
            continue
        attention["money"].append((o, issue))
        if issue["kind"] == "receivable":
            receivables += issue["amount"]
        elif issue["kind"] == "deposit":
            deposits_held += issue["amount"]

    horizon = today + timedelta(days=7)
    agenda = []
    for o in active:
        if o.handover_at and not workflow.handover_completed(o):
            d = timezone.localtime(o.handover_at).date()
            if d <= horizon:
                agenda.append({"when": o.handover_at, "kind": "out", "order": o, "overdue": d < today})
        if o.return_at and workflow.handover_completed(o) and not workflow.return_completed(o):
            d = timezone.localtime(o.return_at).date()
            if d <= horizon:
                agenda.append({"when": o.return_at, "kind": "in", "order": o, "overdue": d < today})
    agenda.sort(key=lambda x: x["when"])

    upcoming = [o for o in active if o.event_date and today <= o.event_date <= today + timedelta(days=30)]

    context = {
        "today": today,
        "kpi_active": len(active),
        "kpi_upcoming": len(upcoming),
        "kpi_receivables": receivables,
        "kpi_deposits": deposits_held,
        "attention": {k: v[:ATTENTION_LIMIT] for k, v in attention.items()},
        "attention_count": sum(len(v) for v in attention.values()),
        "attention_hidden": sum(max(0, len(v) - ATTENTION_LIMIT) for v in attention.values()),
        "agenda": agenda,
        "upcoming": upcoming[:6],
        "activity": AuditLog.objects.select_related("user", "order").exclude(action="login")[:8],
        "setup_missing": _setup_missing(),
    }
    return render(request, "core/dashboard.html", context)


def _setup_missing():
    c = CompanySettings.get()
    missing = []
    if not (c.street and c.city):
        missing.append(("Anschrift des Betriebs", reverse("core:settings")))
    if not (c.tax_number or c.vat_id):
        missing.append(("Steuernummer oder USt-IdNr.", reverse("core:settings_tax")))
    if not c.iban:
        missing.append(("Bankverbindung", reverse("core:settings_tax")))
    if not c.mail_configured:
        missing.append(("E-Mail-Versand", reverse("core:settings_mail")))
    return missing


# --------------------------------------------------------------------------
# Kalender
# --------------------------------------------------------------------------


def calendar_view(request):
    from apps.orders.models import Order

    today = timezone.localdate()
    try:
        year = int(request.GET.get("jahr", today.year))
        month = int(request.GET.get("monat", today.month))
        first = date(year, month, 1)
    except (TypeError, ValueError):
        first = today.replace(day=1)
    cal = pycal.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1]

    orders = (
        Order.objects.exclude(status=Order.Status.CANCELLED)
        .filter(
            Q(event_date__range=(start, end))
            | Q(handover_at__date__range=(start, end))
            | Q(return_at__date__range=(start, end))
        )
        .select_related("customer")
    )
    events = {}
    for o in orders:
        label = o.event_name or o.number
        if o.handover_at:
            d = timezone.localtime(o.handover_at).date()
            events.setdefault(d, []).append({"order": o, "kind": "out", "label": f"{timezone.localtime(o.handover_at):%H:%M} Übergabe · {label}"})
        if o.event_date:
            events.setdefault(o.event_date, []).append({"order": o, "kind": "event", "label": label})
        if o.return_at:
            d = timezone.localtime(o.return_at).date()
            events.setdefault(d, []).append({"order": o, "kind": "in", "label": f"{timezone.localtime(o.return_at):%H:%M} Rückgabe · {label}"})

    order_kind = {"out": 0, "event": 1, "in": 2}
    grid = [
        [{"date": d, "other": d.month != first.month, "today": d == today, "events": sorted(events.get(d, []), key=lambda e: order_kind[e["kind"]])} for d in week]
        for week in weeks
    ]
    # Agenda-Ansicht (Smartphone): nur Tage des Monats mit Terminen
    agenda = [
        {"date": cell["date"], "today": cell["today"], "events": cell["events"]}
        for week in grid for cell in week
        if not cell["other"] and cell["events"]
    ]
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return render(request, "core/calendar.html", {
        "first": first, "grid": grid, "agenda": agenda, "prev": prev_month, "next": next_month, "today": today,
        "weekdays": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    })


# --------------------------------------------------------------------------
# Suche
# --------------------------------------------------------------------------


def search(request):
    from apps.billing.models import Invoice
    from apps.catalog.models import Article, Package
    from apps.customers.models import Customer
    from apps.documents.models import Document
    from apps.orders.models import Order

    q = (request.GET.get("q") or "").strip()
    groups = []
    if not q:
        groups.append(("Schnellzugriff", [
            {"url": reverse("orders:create"), "icon": "plus", "title": "Neuen Auftrag anlegen", "sub": ""},
            {"url": reverse("customers:create"), "icon": "user-plus", "title": "Neuen Kunden anlegen", "sub": ""},
            {"url": reverse("catalog:article_create"), "icon": "flower-2", "title": "Neuen Artikel anlegen", "sub": ""},
            {"url": reverse("core:calendar"), "icon": "calendar-days", "title": "Kalender öffnen", "sub": ""},
        ]))
        recent = Order.objects.select_related("customer").order_by("-updated_at")[:5]
        groups.append(("Zuletzt bearbeitet", [
            {"url": o.get_absolute_url(), "icon": "clipboard-list", "title": o.title, "sub": f"{o.number} · {o.customer or ''}"} for o in recent
        ]))
    else:
        terms = q.split()
        cq = Q()
        for t in terms:
            cq &= Q(first_name__icontains=t) | Q(last_name__icontains=t) | Q(email__icontains=t) | Q(phone__icontains=t) | Q(number__icontains=t) | Q(city__icontains=t)
        customers = Customer.objects.filter(cq)[:6]
        oq = Q()
        for t in terms:
            oq &= Q(number__icontains=t) | Q(event_name__icontains=t) | Q(customer__first_name__icontains=t) | Q(customer__last_name__icontains=t) | Q(event_location__icontains=t)
        orders = Order.objects.filter(oq).select_related("customer")[:6]
        articles = Article.objects.filter(Q(name__icontains=q) | Q(number__icontains=q) | Q(storage_location__icontains=q))[:6]
        packages = Package.objects.filter(name__icontains=q)[:4]
        docs = Document.objects.filter(number__icontains=q).select_related("order")[:5]
        invoices = Invoice.objects.filter(number__icontains=q).select_related("order")[:5]
        if orders:
            groups.append(("Aufträge", [{"url": o.get_absolute_url(), "icon": "clipboard-list", "title": o.title, "sub": f"{o.number} · {o.customer or ''}"} for o in orders]))
        if customers:
            groups.append(("Kunden", [{"url": c.get_absolute_url(), "icon": "user", "title": c.full_name, "sub": f"{c.number} · {c.city}"} for c in customers]))
        if articles:
            groups.append(("Artikel", [{"url": a.get_absolute_url(), "icon": "flower-2", "title": a.name, "sub": a.number} for a in articles]))
        if packages:
            groups.append(("Pakete", [{"url": p.get_absolute_url(), "icon": "package", "title": p.name, "sub": ""} for p in packages]))
        if invoices:
            groups.append(("Rechnungen", [{"url": i.order.get_absolute_url() + "?schritt=invoice", "icon": "receipt-text", "title": i.number, "sub": i.order.title} for i in invoices]))
        if docs:
            groups.append(("Dokumente", [{"url": d.get_absolute_url(), "icon": "file-text", "title": d.display_name, "sub": d.order.title} for d in docs]))
    return render(request, "core/search_results.html", {"groups": groups, "q": q})


# --------------------------------------------------------------------------
# Profil
# --------------------------------------------------------------------------


def profile(request):
    # Jedes Formular wird nur ausgewertet, wenn sein eigener Knopf gedrückt wurde.
    saving_profile = request.method == "POST" and "save_profile" in request.POST
    changing_password = request.method == "POST" and "change_password" in request.POST
    form = ProfileForm(request.POST if saving_profile else None, instance=request.user, prefix="p")
    pw_form = PasswordChangeForm(request.user, request.POST if changing_password else None, prefix="pw")
    if saving_profile and form.is_valid():
        form.save()
        messages.success(request, "Profil gespeichert.")
        return redirect("core:profile")
    if changing_password and pw_form.is_valid():
        request.user.set_password(pw_form.cleaned_data["new_password1"])
        request.user.save()
        update_session_auth_hash(request, request.user)
        audit.log(request.user, "password", "Eigenes Passwort geändert")
        messages.success(request, "Passwort geändert.")
        return redirect("core:profile")
    return render(request, "core/profile.html", {"form": form, "pw_form": pw_form})


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------


def _settings_page(request, form_class, template, section, success_msg, files=False):
    company = CompanySettings.get()
    if not request.user.is_admin:
        return render(request, template, {"form": None, "section": section, "readonly": True, "company": company})
    form = form_class(request.POST or None, request.FILES or None if files else None, instance=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request.user, "settings", f"Einstellungen geändert: {success_msg}")
        messages.success(request, f"{success_msg} gespeichert.")
        return redirect(request.path)
    return render(request, template, {"form": form, "section": section, "company": company})


def settings_company(request):
    return _settings_page(request, CompanyForm, "core/settings/company.html", "company", "Geschäftsdaten", files=True)


def settings_tax(request):
    return _settings_page(request, TaxBankForm, "core/settings/tax.html", "tax", "Steuer und Bank")


def settings_rules(request):
    return _settings_page(request, RulesForm, "core/settings/rules.html", "rules", "Geschäftsregeln")


@admin_required
def settings_mail(request):
    company = CompanySettings.get()
    form = MailForm(request.POST or None, instance=company, prefix="m")
    test_form = TestMailForm(request.POST if "send_test" in request.POST else None, prefix="t", initial={"to": request.user.email})
    if request.method == "POST":
        if "send_test" in request.POST:
            form = MailForm(instance=company, prefix="m")
            if test_form.is_valid():
                try:
                    send_mail(
                        to=test_form.cleaned_data["to"],
                        subject=f"Test-E-Mail von mietly ({company.name})",
                        body="Diese Test-E-Mail bestätigt, dass der E-Mail-Versand von mietly funktioniert.",
                        user=request.user,
                    )
                    messages.success(request, "Test-E-Mail wurde gesendet.")
                except MailError as e:
                    messages.error(request, str(e))
                return redirect("core:settings_mail")
        elif form.is_valid():
            form.save()
            audit.log(request.user, "settings", "E-Mail-Einstellungen geändert")
            messages.success(request, "E-Mail-Einstellungen gespeichert.")
            return redirect("core:settings_mail")
    log = EmailLog.objects.select_related("order")[:15]
    return render(request, "core/settings/mail.html", {"form": form, "test_form": test_form, "section": "mail", "log": log, "company": company})




@admin_required
def settings_printer(request):
    from . import printing

    company = CompanySettings.get()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "setup":
            host = request.POST.get("printer_host", "").strip()
            try:
                uri, driver, model = printing.setup(host)
            except printing.PrinterError as e:
                messages.error(request, f"Der Drucker konnte nicht eingerichtet werden: {e}")
                return render(request, "core/settings/printer.html", {"section": "printer", "company": company, "host": host})
            company.printer_host, company.printer_uri, company.printer_driver, company.printer_model = host, uri, driver, model[:200]
            company.printer_ready = True
            company.save()
            audit.log(request.user, "settings", f"Drucker eingerichtet: {host} ({model or driver})")
            action = "test"
        if action == "test":
            try:
                ok, text = printing.test_page(company.name)
            except printing.PrinterError as e:
                ok, text = False, str(e)
            company.printer_last_test = timezone.now()
            company.printer_last_result = text
            company.save(update_fields=["printer_last_test", "printer_last_result", "updated_at"])
            (messages.success if ok else messages.warning)(request, text)
        elif action == "remove":
            printing.remove()
            company.printer_host = company.printer_uri = company.printer_driver = company.printer_model = ""
            company.printer_ready = False
            company.printer_last_result = ""
            company.printer_last_test = None
            company.save()
            audit.log(request.user, "settings", "Drucker entfernt")
            messages.success(request, "Der Drucker wurde entfernt.")
        return redirect("core:settings_printer")
    return render(request, "core/settings/printer.html", {"section": "printer", "company": company, "host": company.printer_host})


@admin_required
def settings_webdav(request):
    from .webdav import WebdavError, sync_now, test_connection

    company = CompanySettings.get()
    form = WebdavForm(request.POST or None, instance=company)
    if request.method == "POST":
        if ("test" in request.POST or "sync" in request.POST) and form.has_changed():
            # Geänderte Eingaben zuerst übernehmen, damit mit ihnen getestet wird.
            if not form.is_valid():
                return render(request, "core/settings/webdav.html", {"form": form, "section": "webdav", "company": company})
            company = form.save()
        if "test" in request.POST:
            try:
                test_connection(company)
                messages.success(request, "Verbindung zum WebDAV-Server erfolgreich.")
            except WebdavError as e:
                messages.error(request, str(e))
            return redirect("core:settings_webdav")
        if "sync" in request.POST:
            try:
                result = sync_now(company)
                messages.success(request, f"Synchronisierung abgeschlossen: {result}")
            except WebdavError as e:
                messages.error(request, str(e))
            return redirect("core:settings_webdav")
        if form.is_valid():
            form.save()
            audit.log(request.user, "settings", "WebDAV-Einstellungen geändert")
            messages.success(request, "WebDAV-Einstellungen gespeichert.")
            return redirect("core:settings_webdav")
    return render(request, "core/settings/webdav.html", {"form": form, "section": "webdav", "company": company})


def settings_templates(request):
    keys = TextTemplate.Key.choices
    current = {}
    for key, label in keys:
        current[key] = TextTemplate.current(key)
    groups = [
        ("Verträge & rechtliche Texte", ["contract", "terms", "withdrawal", "privacy"]),
        ("Dokumenttexte", ["offer_intro", "offer_outro", "invoice_outro", "invoice_outro_followup", "handover_confirm"]),
        ("E-Mail-Vorlagen", ["mail_offer", "mail_offer_signed", "mail_contract", "mail_contract_signed", "mail_invoice",
                             "mail_handover", "mail_return", "mail_deposit", "mail_additional", "mail_fee", "mail_cancellation"]),
    ]
    return render(request, "core/settings/templates.html", {
        "section": "templates",
        "groups": [(title, [current[k] for k in ks]) for title, ks in groups],
    })


def settings_template_edit(request, key):
    if key not in TextTemplate.Key.values:
        raise Http404
    tpl = TextTemplate.current(key)
    history = TextTemplate.objects.filter(key=key).select_related("created_by")
    form = TextTemplateForm(request.POST or None, key=key, initial={"subject": tpl.subject, "body": tpl.body})
    preview = None
    if request.method == "POST":
        if not request.user.is_admin:
            messages.error(request, "Nur Administratoren können Vorlagen ändern.")
            return redirect(request.path)
        if form.is_valid():
            subject = form.cleaned_data.get("subject", tpl.subject) or ""
            body = form.cleaned_data["body"].replace("\r\n", "\n")
            if "preview" in request.POST:
                preview = render_html(body, _sample_context())
            elif subject == tpl.subject and body == tpl.body:
                messages.info(request, "Keine Änderungen.")
                return redirect(request.path)
            else:
                new = TextTemplate.objects.create(key=key, version=tpl.version + 1, subject=subject, body=body, created_by=request.user)
                audit.log(request.user, "template", f"Vorlage „{new.get_key_display()}“ geändert (Version {new.version})", obj=new)
                messages.success(request, f"Vorlage gespeichert (Version {new.version}). Bereits erstellte Dokumente bleiben unverändert.")
                return redirect(request.path)
    restore = request.GET.get("version")
    if restore and request.method == "GET":
        old = history.filter(version=restore).first()
        if old:
            form = TextTemplateForm(key=key, initial={"subject": old.subject, "body": old.body})
            messages.info(request, f"Version {old.version} geladen. Speichern, um sie als neue Version zu übernehmen.")
    return render(request, "core/settings/template_edit.html", {
        "section": "templates", "tpl": tpl, "form": form, "history": history[:20],
        "placeholders": PLACEHOLDERS, "preview": preview, "is_mail": key.startswith("mail_"),
    })


def _sample_context():
    from apps.documents.context import placeholder_context

    return placeholder_context(None)


@admin_required
def users_list(request):
    users = User.objects.all().order_by("-is_active", "first_name", "username")
    return render(request, "core/settings/users.html", {"section": "users", "users": users})


@admin_required
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else User()
    form = UserForm(request.POST or None, instance=user, acting_user=request.user)
    if request.method == "POST" and form.is_valid():
        created = user.pk is None
        form.save()
        audit.log(request.user, "user", f"Benutzer {'angelegt' if created else 'geändert'}: {user.username}", obj=user)
        messages.success(request, "Benutzer gespeichert.")
        return redirect("core:users")
    return render(request, "core/settings/user_form.html", {"section": "users", "form": form, "obj": user})


@admin_required
def activity_log(request):
    qs = AuditLog.objects.select_related("user", "order")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(message__icontains=q) | Q(order__number__icontains=q) | Q(user__username__icontains=q))
    page = Paginator(qs, 50).get_page(request.GET.get("seite"))
    return render(request, "core/settings/activity.html", {"section": "activity", "page": page, "q": q})


@admin_required
def backups(request):
    from . import backup

    if request.method == "POST":
        try:
            backup.start_backup_async()
            audit.log(request.user, "backup", "Backup manuell gestartet")
            messages.success(request, "Das Backup wurde gestartet. Es erscheint in wenigen Sekunden in der Liste.")
        except backup.BackupError as e:
            messages.error(request, str(e))
        return redirect("core:backups")
    return render(request, "core/settings/backups.html", {
        "section": "backups",
        "backups": backup.list_backups(),
        "running": backup.is_running(),
        "last_error": backup.last_error(),
        "backup_dir": settings.BACKUP_DIR,
    })


@admin_required
def backup_download(request, name):
    from . import backup
    from .files import protected_file_response

    path = backup.backup_path(name)
    if path is None:
        raise Http404
    audit.log(request.user, "backup", f"Backup heruntergeladen: {name}")
    # Backups enthalten Schlüssel und sind nur für den Dienstbenutzer lesbar,
    # daher liefert Django sie selbst aus (nicht nginx).
    return protected_file_response(path, name, root=settings.BACKUP_DIR, accel=False)


def settings_about(request):
    import platform

    from django import get_version

    return render(request, "core/settings/about.html", {
        "section": "about",
        "python": platform.python_version(),
        "django": get_version(),
        "data_dir": settings.DATA_DIR,
    })


# Seiten vorab laden, sobald der Mauszeiger auf einem Link ruht oder er angetippt wird
# (Speculation Rules, Chrome/Edge). Nur lesende Seiten – Downloads, Sicherungen und
# Abmelden sind ausgenommen; Formulare werden ohnehin nie vorab abgeschickt.
SPECULATION_RULES = {
    "prefetch": [{
        "where": {"and": [
            {"href_matches": "/*"},
            {"not": {"href_matches": "/dokumente/*"}},
            {"not": {"href_matches": "/einstellungen/backups/*"}},
            {"not": {"href_matches": "/abmelden*"}},
            {"not": {"href_matches": "/*\\?*export=*"}},
            {"not": {"selector_matches": "[download], [target=_blank], [data-no-prefetch]"}},
        ]},
        "eagerness": "moderate",
    }]
}


def speculation_rules(request):
    import json

    resp = HttpResponse(json.dumps(SPECULATION_RULES), content_type="application/speculationrules+json")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp
