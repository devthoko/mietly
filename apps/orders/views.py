from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing import services as billing
from apps.billing.models import Payment
from apps.catalog.models import Article, Package
from apps.core.images import process_image
from apps.core.models import CompanySettings
from apps.customers.forms import CustomerForm
from apps.customers.models import Customer
from apps.core.numbering import next_number
from apps.core import audit

from . import availability, services, workflow
from .forms import (
    CancelForm, CustomItemForm, DamageForm, DepositAmountForm, DepositForm, EventForm, HandoverForm, PaymentForm, ReturnForm,
)
from .models import Damage, Order, OrderItem, Photo
from .workflow import WorkflowError


def _pk(value):
    """Kennung aus einem Formularfeld – ungültige Werte führen zu „nicht gefunden“ statt zu einem Serverfehler."""
    value = str(value or "").strip()
    if not value.isdigit():
        raise Http404("Ungültige Auswahl.")
    return int(value)


def step_url(order, step):
    return f"{reverse('orders:detail', args=[order.pk])}?schritt={step}"


def action(step):
    """POST-Aktion: Sperren und Validierungsfehler werden als Meldung angezeigt."""

    def decorator(view):
        @wraps(view)
        @require_POST
        def wrapper(request, pk, *args, **kwargs):
            order = get_object_or_404(Order, pk=pk)
            try:
                result = view(request, order, *args, **kwargs)
            except WorkflowError as e:
                messages.error(request, str(e))
                return redirect(step_url(order, step))
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
                return redirect(step_url(order, step))
            return result or redirect(step_url(order, step))

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Liste & Anlage
# --------------------------------------------------------------------------

STATUS_TABS = [
    ("aktiv", "In Bearbeitung", Q(status=Order.Status.ACTIVE)),
    ("abgeschlossen", "Abgeschlossen", Q(status=Order.Status.COMPLETED)),
    ("storniert", "Storniert", Q(status=Order.Status.CANCELLED)),
    ("alle", "Alle", Q()),
]


def order_list(request):
    tab = request.GET.get("status", "aktiv")
    tabs = []
    current_filter = Q(status=Order.Status.ACTIVE)
    for key, label, f in STATUS_TABS:
        tabs.append({"key": key, "label": label, "count": Order.objects.filter(f).count()})
        if key == tab:
            current_filter = f
    qs = Order.objects.filter(current_filter).select_related("customer")
    q = request.GET.get("q", "").strip()
    if q:
        for t in q.split():
            qs = qs.filter(Q(number__icontains=t) | Q(event_name__icontains=t) | Q(customer__first_name__icontains=t)
                           | Q(customer__last_name__icontains=t) | Q(event_location__icontains=t))
    stage = request.GET.get("schritt")
    if stage and stage.isdigit():
        qs = qs.filter(stage=int(stage))
    sort = request.GET.get("sortierung", "event")
    if sort == "event":
        qs = qs.order_by("event_date", "-created_at") if tab == "aktiv" else qs.order_by("-event_date", "-created_at")
    else:
        qs = qs.order_by("-created_at")
    page = Paginator(qs.prefetch_related("items"), 30).get_page(request.GET.get("seite"))
    return render(request, "orders/list.html", {
        "page": page, "tabs": tabs, "tab": tab, "q": q, "stage": stage, "sort": sort,
        "steps": workflow.STEPS,
    })


def order_create(request):
    customer_pk = request.POST.get("kunde") if request.method == "POST" else None
    if customer_pk:
        customer = get_object_or_404(Customer, pk=_pk(customer_pk), anonymized_at__isnull=True)
        order = services.create_order(request.user, customer)
        return redirect(step_url(order, "event"))
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and "new_customer" in request.POST:
        if form.is_valid():
            customer = form.save(commit=False)
            customer.number = next_number("customer")
            customer.save()
            audit.log(request.user, "customer", f"Kunde angelegt: {customer.full_name}", obj=customer)
            order = services.create_order(request.user, customer)
            messages.success(request, f"Kunde {customer.full_name} angelegt.")
            return redirect(step_url(order, "event"))
    q = request.GET.get("q", "").strip()
    customers = Customer.objects.filter(anonymized_at__isnull=True)
    if q:
        for t in q.split():
            customers = customers.filter(Q(first_name__icontains=t) | Q(last_name__icontains=t) | Q(email__icontains=t) | Q(phone__icontains=t) | Q(city__icontains=t))
    else:
        customers = customers.order_by("-updated_at")
    template = "orders/_customer_results.html" if request.htmx else "orders/create.html"
    return render(request, template, {"form": form, "customers": customers[:12], "q": q, "show_new": request.method == "POST"})


# --------------------------------------------------------------------------
# Auftragsakte
# --------------------------------------------------------------------------

def _items_prefetch():
    from django.db.models import Prefetch

    return Prefetch("items", queryset=OrderItem.objects.select_related("article", "package").prefetch_related("package__items__article"))


def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("customer", "created_by").prefetch_related(_items_prefetch()), pk=pk)
    workflow.enable_memo(order)  # Ablaufabfragen nur einmal je Seitenaufruf
    keys = [k for _, k, _ in workflow.STEPS]
    selected = request.GET.get("schritt")
    state = workflow.refresh_stage(order)
    if selected not in keys:
        selected = state.current.key if order.is_active else "close"
    ctx = _detail_context(request, order, selected, state)
    return render(request, "orders/detail.html", ctx)


def _mail_issues(order):
    """Laufende oder gescheiterte E-Mails, die noch nicht durch einen späteren Versand erledigt sind."""
    from apps.core.models import EmailLog

    recent = list(order.emails.order_by("-created_at")[:20])
    issues = []
    for i, m in enumerate(recent):
        if m.status == EmailLog.Status.SENT:
            continue
        later_sent = any(o.status == EmailLog.Status.SENT and o.to == m.to and o.subject == m.subject for o in recent[:i])
        if not later_sent:
            issues.append(m)
    return issues[:3]


def _detail_context(request, order, selected, state):
    step = next(s for s in state.steps if s.key == selected)
    ctx = {
        "order": order, "state": state, "step": step, "selected": selected,
        "documents": order.documents.select_related("created_by").order_by("kind", "-version"),
        "activities": order.activities.select_related("user")[:12],
        "deposit": workflow.deposit_state(order),
        "paid_total": workflow.paid_total(order),
        "invoiced_total": workflow.invoiced_total(order),
        "open_balance": workflow.open_balance(order),
        "main_invoice": workflow.main_invoice(order),
        "next_doc": workflow.awaiting_signature(order, state),
        "mail_issues": _mail_issues(order),
        "is_empty_draft": workflow.is_empty_draft(order),
    }
    ctx.update(_step_context(request, order, selected))
    return ctx


def _step_context(request, order, key):
    ctx = {}
    if key == "customer":
        ctx["customer_locked"] = workflow.current_document(order, "offer") is not None
    elif key == "event":
        data = request.session.pop(f"event_form_{order.pk}", None)
        if data:
            form = EventForm(data, instance=Order.objects.get(pk=order.pk))
            form.is_valid()
        else:
            form = EventForm(instance=order)
        ctx["event_form"] = form
        ctx["delivery_fee"] = CompanySettings.get().delivery_fee
    elif key == "offer":
        ctx.update(_items_context(order))
        ctx["offer"] = workflow.current_document(order, "offer")
        ctx["custom_form"] = CustomItemForm()
        ctx["deposit_form"] = DepositAmountForm(initial={"amount": order.deposit_amount})
        ctx["offer_history"] = order.documents.filter(kind="offer").order_by("-version")
        ctx["invoice_data_missing"] = workflow.missing_invoice_data(order) if order.is_active and not workflow.main_invoice(order) else []
    elif key == "contract":
        ctx["contract"] = workflow.current_document(order, "contract")
        ctx["contract_history"] = order.documents.filter(kind="contract").order_by("-version")
    elif key == "invoice":
        ctx["invoices"] = order.invoices.select_related("document", "cancels").order_by("id")
        ctx["payments"] = order.payments.select_related("created_by", "invoice")
        ctx["payment_form"] = PaymentForm(initial={"paid_on": timezone.localdate(), "amount": max(workflow.open_balance(order), Decimal("0"))})
        ctx["deposit_form"] = DepositForm(initial={"date": timezone.localdate(), "amount": workflow.deposit_state(order).outstanding})
        ctx["deposit_transactions"] = order.deposit_transactions.select_related("created_by")
        ctx["cancel_form"] = CancelForm()
    elif key == "packing":
        ctx["packing"] = workflow.current_document(order, "packing_list")
        ctx["quantities"] = sorted(order.article_quantities().items(), key=lambda x: (x[0].category.name if x[0].category else "~", x[0].name))
    elif key == "handover":
        h = getattr(order, "handover", None)
        ctx["handover"] = h
        ctx["handover_doc"] = workflow.current_document(order, "handover")
        ctx["handover_signed_doc"] = order.documents.filter(kind="handover", status="signed").first()
        if h:
            ctx["handover_form"] = HandoverForm(initial={"performed_at": timezone.localtime(h.performed_at), "recipient_name": h.recipient_name, "notes": h.notes})
            ctx["handover_items"] = h.items.select_related("article")
        ctx["photos"] = order.photos.filter(stage="handover")
        ctx["deposit_form"] = DepositForm(initial={"date": timezone.localdate(), "amount": workflow.deposit_state(order).outstanding})
        try:
            workflow.assert_handover_allowed(order)
            ctx["handover_allowed"] = True
        except WorkflowError as e:
            ctx["handover_allowed"] = False
            ctx["handover_block"] = str(e)
    elif key == "return":
        r = getattr(order, "return_record", None)
        ctx["record"] = r
        if r:
            ctx["return_form"] = ReturnForm(initial={"performed_at": timezone.localtime(r.performed_at), "returned_by_name": r.returned_by_name, "notes": r.notes})
            ctx["return_items"] = r.items.select_related("article")
        ctx["damages"] = order.damages.select_related("article")
        ctx["damage_form"] = DamageForm(order=order)
        ctx["photos"] = order.photos.filter(stage="return")
        ctx["return_doc"] = workflow.current_document(order, "return")
        ctx["damages_locked"] = services.return_locked(order)
    elif key == "close":
        ctx["damages"] = order.damages.select_related("article")
        ctx["open_damages"] = order.damages.filter(settlement="open").select_related("article")
        ctx["deposit_transactions"] = order.deposit_transactions.select_related("created_by")
        ctx["blockers"] = workflow.close_blockers(order) if order.is_active else []
        ctx["payment_form"] = PaymentForm(initial={"paid_on": timezone.localdate(), "amount": max(workflow.open_balance(order), Decimal("0"))})
        ctx["refund_form"] = PaymentForm(initial={"paid_on": timezone.localdate(), "amount": max(-workflow.open_balance(order), Decimal("0")), "method": "transfer"})
        ctx["deposit_doc"] = workflow.current_document(order, "deposit")
        ctx["invoices"] = order.invoices.select_related("document", "cancels").order_by("id")
        ctx["payments"] = order.payments.select_related("created_by")
        ctx["refund_methods"] = Payment.Method.choices
        ctx["damage_form"] = DamageForm(order=order)
    return ctx


def _items_context(order):
    try:
        workflow.assert_can_edit_items(order)
        editable, lock_reason = True, ""
    except WorkflowError as e:
        editable, lock_reason = False, str(e)
    avail = {a.article.pk: a for a in availability.check_order(order)}
    return {
        "items": order._item_rows(),
        "items_editable": editable,
        "items_lock_reason": lock_reason,
        "availability": avail,
        "shortages": [a for a in avail.values() if not a.ok],
        "order_total": order.total,
    }


def _items_partial(request, order):
    """Positionsliste plus Schrittleiste, „Als Nächstes“ und Angebotskarte (htmx out-of-band),
    damit nach jeder Änderung alles auf dem aktuellen Stand ist."""
    order.refresh_from_db()
    state = workflow.refresh_stage(order)
    ctx = _detail_context(request, order, "offer", state)
    ctx["oob"] = True
    return render(request, "orders/_items_response.html", ctx)


# --------------------------------------------------------------------------
# Schritt 1 & 2
# --------------------------------------------------------------------------

@action("customer")
def set_customer(request, order):
    customer = get_object_or_404(Customer, pk=_pk(request.POST.get("customer")))
    services.set_customer(order, customer, request.user)
    messages.success(request, f"Kunde {customer.full_name} übernommen.")
    return redirect(step_url(order, "event"))


def customer_picker(request, pk):
    order = get_object_or_404(Order, pk=pk)
    q = request.GET.get("q", "").strip()
    customers = Customer.objects.filter(anonymized_at__isnull=True)
    for t in q.split():
        customers = customers.filter(Q(first_name__icontains=t) | Q(last_name__icontains=t) | Q(email__icontains=t) | Q(phone__icontains=t))
    return render(request, "orders/_customer_results.html", {"customers": customers[:12], "order": order, "q": q})


@require_POST
def save_event(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = EventForm(request.POST, instance=order)
    if form.is_valid():
        try:
            services.save_event(order, form, request.user)
        except WorkflowError as e:
            messages.error(request, str(e))
            return redirect(step_url(order, "event"))
        messages.success(request, "Eventdaten gespeichert.")
        nxt = "offer" if workflow.event_complete(order) else "event"
        return redirect(step_url(order, nxt))
    # Eingaben merken und auf die normale Adresse umleiten – so führt Neuladen nicht zu einem Fehler.
    request.session[f"event_form_{order.pk}"] = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
    messages.error(request, "Bitte die markierten Angaben prüfen.")
    return redirect(step_url(order, "event"))


# --------------------------------------------------------------------------
# Schritt 3: Positionen & Angebot
# --------------------------------------------------------------------------

def item_search(request, pk):
    order = get_object_or_404(Order, pk=pk)
    q = request.GET.get("q", "").strip()
    articles = Article.objects.filter(active=True).select_related("category")
    packages = Package.objects.filter(active=True).prefetch_related("items__article")
    if q:
        articles = articles.filter(Q(name__icontains=q) | Q(number__icontains=q) | Q(category__name__icontains=q))
        packages = packages.filter(name__icontains=q)
    packages = list(packages[:5])
    articles = list(articles[:15])
    # Verfügbarkeit aller Treffer (inkl. Paketinhalte) in einem Durchgang berechnen
    ids = [a.pk for a in articles] + [pi.article_id for p in packages for pi in p.items.all()]
    free = availability.available_map(ids, order)
    extra_days = services._extra_days(order)
    results = []
    for p in packages:
        results.append({"kind": "package", "obj": p, "price": services.package_price(order, p, extra_days),
                        "available": availability.package_available_from(p, free)})
    for a in articles:
        results.append({"kind": "article", "obj": a, "price": services.article_price(order, a, extra_days),
                        "available": free.get(a.pk, 0)})
    return render(request, "orders/_item_results.html", {"results": results, "order": order, "q": q})


def _htmx_or_redirect(request, order, step="offer"):
    if request.htmx:
        return _items_partial(request, order)
    return redirect(step_url(order, step))


def _htmx_error(request, order, error):
    if request.htmx:
        resp = _items_partial(request, order)
        resp.content = (
            f'<div class="alert alert-danger mb-sm" role="alert">{_esc(error)}</div>'.encode() + resp.content
        )
        return resp
    messages.error(request, error)
    return redirect(step_url(order, "offer"))


def _esc(text):
    from django.utils.html import escape

    return escape(text)


# Grenzen für Formularwerte: verhindert Datenbankfehler bei unsinnig großen Eingaben
INT_LIMIT = 1_000_000
DEC_LIMIT = Decimal("99999999")


def _int(value, default=1):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(-INT_LIMIT, min(INT_LIMIT, number))


def _dec(value, default=None):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return default
    if not number.is_finite() or abs(number) > DEC_LIMIT:
        return default
    return number


@require_POST
def item_add(request, pk):
    order = get_object_or_404(Order, pk=pk)
    qty = max(1, _int(request.POST.get("quantity"), 1))
    try:
        if request.POST.get("article"):
            services.add_article(order, get_object_or_404(Article, pk=_pk(request.POST["article"]), active=True), qty, request.user)
        elif request.POST.get("package"):
            services.add_package(order, get_object_or_404(Package, pk=_pk(request.POST["package"]), active=True), qty, request.user)
        else:
            return HttpResponseBadRequest()
    except WorkflowError as e:
        return _htmx_error(request, order, str(e))
    return _htmx_or_redirect(request, order)


@require_POST
def item_custom(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = CustomItemForm(request.POST)
    if not form.is_valid():
        return _htmx_error(request, order, "Bitte Bezeichnung, Menge und Preis der Position angeben.")
    try:
        services.add_custom(order, user=request.user, **form.cleaned_data)
    except WorkflowError as e:
        return _htmx_error(request, order, str(e))
    return _htmx_or_redirect(request, order)


@require_POST
def item_update(request, pk, item_pk):
    order = get_object_or_404(Order, pk=pk)
    item = get_object_or_404(OrderItem, pk=item_pk, order=order)
    qty = _int(request.POST.get("quantity"), item.quantity)
    price = _dec(request.POST.get("unit_price"), item.unit_price)
    discount = _dec(request.POST.get("discount_percent"), item.discount_percent) or Decimal("0")
    try:
        services.update_item(item, quantity=qty, unit_price=price, discount_percent=discount,
                             description=request.POST.get("description", "").strip() or None, user=request.user)
    except WorkflowError as e:
        return _htmx_error(request, order, str(e))
    return _htmx_or_redirect(request, order)


@require_POST
def item_remove(request, pk, item_pk):
    order = get_object_or_404(Order, pk=pk)
    item = get_object_or_404(OrderItem, pk=item_pk, order=order)
    try:
        services.remove_item(item, request.user)
    except WorkflowError as e:
        return _htmx_error(request, order, str(e))
    return _htmx_or_redirect(request, order)


@require_POST
def deposit_amount(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = DepositAmountForm(request.POST)
    if not form.is_valid():
        return _htmx_error(request, order, "Bitte einen gültigen Kautionsbetrag angeben.")
    try:
        services.set_deposit(order, form.cleaned_data["amount"], request.user)
    except WorkflowError as e:
        return _htmx_error(request, order, str(e))
    return _htmx_or_redirect(request, order)


@action("offer")
def reprice(request, order):
    services.reprice(order, request.user)
    messages.success(request, "Preise wurden anhand der Mietdauer neu berechnet.")


@action("offer")
def create_offer(request, order):
    from apps.documents.services import create_offer as make

    doc = make(order, request.user)
    messages.success(request, f"{doc.display_name} wurde erstellt. Jetzt unterschreiben lassen oder per E-Mail senden.")
    missing = workflow.missing_invoice_data(order)
    if missing:
        messages.warning(request, "Bitte schon jetzt ergänzen – sonst kann später keine Rechnung erstellt werden: " + "; ".join(missing) + ".")
    return redirect(step_url(order, "offer") + "#angebot")


# --------------------------------------------------------------------------
# Schritt 4 & 5
# --------------------------------------------------------------------------

@action("contract")
def create_contract(request, order):
    from apps.documents.services import create_contract as make

    doc = make(order, request.user)
    messages.success(request, f"{doc.display_name} wurde erstellt. Jetzt unterschreiben lassen oder per E-Mail senden.")
    return redirect(step_url(order, "contract") + "#vertrag")


@action("invoice")
def issue_invoice(request, order):
    inv = billing.issue_invoice(order, request.user)
    messages.success(request, f"Rechnung {inv.number} wurde erstellt.")


@action("invoice")
def cancel_invoice(request, order, invoice_pk):
    inv = get_object_or_404(order.invoices, pk=invoice_pk)
    storno = billing.cancel_invoice(inv, request.user, request.POST.get("reason", ""))
    messages.success(request, f"Rechnung {inv.number} wurde durch {storno.number} storniert.")


@action("invoice")
def add_payment(request, order):
    form = PaymentForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte Betrag, Datum und Zahlungsart prüfen.")
    billing.record_payment(order, user=request.user, amount=form.cleaned_data["amount"], paid_on=form.cleaned_data["paid_on"],
                           method=form.cleaned_data["method"], reference=form.cleaned_data["reference"], note=form.cleaned_data["note"])
    messages.success(request, "Zahlungseingang erfasst.")
    if request.POST.get("next") == "close":
        return redirect(step_url(order, "close"))
    if workflow.invoice_fully_paid(order) and not workflow.handover_completed(order):
        messages.info(request, "Die Rechnung ist vollständig bezahlt – die Übergabe ist freigegeben.")


@action("close")
def add_refund(request, order):
    form = PaymentForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte Betrag, Datum und Zahlungsart prüfen.")
    billing.record_refund(order, user=request.user, amount=form.cleaned_data["amount"], paid_on=form.cleaned_data["paid_on"],
                          method=form.cleaned_data["method"], reference=form.cleaned_data["reference"], note=form.cleaned_data["note"])
    messages.success(request, "Erstattung erfasst.")


@action("invoice")
def delete_payment(request, order, payment_pk):
    payment = get_object_or_404(order.payments, pk=payment_pk)
    billing.delete_payment(payment, request.user, request.POST.get("reason", ""))
    messages.success(request, "Zahlung gelöscht.")


@action("invoice")
def add_deposit(request, order):
    form = DepositForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte Betrag, Datum und Zahlungsart der Kaution prüfen.")
    services.record_deposit(order, user=request.user, **form.cleaned_data)
    messages.success(request, "Kautionseingang erfasst.")
    if request.POST.get("next") == "handover":
        return redirect(step_url(order, "handover"))


# --------------------------------------------------------------------------
# Schritt 6 & 7
# --------------------------------------------------------------------------

@action("packing")
def create_packing_list(request, order):
    doc = services.create_packing_list(order, request.user)
    messages.success(request, f"{doc.display_name} wurde erstellt.")


@action("handover")
def start_handover(request, order):
    services.start_handover(order, request.user)


@action("handover")
def save_handover(request, order):
    form = HandoverForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte Zeitpunkt und Empfänger angeben.")
    items = {}
    for item in order.handover.items.all():
        p = f"item-{item.pk}-"
        items[item.pk] = {
            "quantity": max(0, _int(request.POST.get(p + "quantity"), item.quantity)),
            "condition": request.POST.get(p + "condition", item.condition) if request.POST.get(p + "condition") in ("good", "used", "damaged") else item.condition,
            "existing_damage": request.POST.get(p + "existing_damage", "")[:300],
            "note": request.POST.get(p + "note", "")[:300],
        }
    services.save_handover(order, {**form.cleaned_data, "items": items}, request.user)
    if "protocol" in request.POST:
        doc = services.create_handover_protocol(order, request.user)
        messages.success(request, f"{doc.display_name} wurde erstellt. Bitte jetzt unterschreiben lassen.")
        return redirect("documents:sign", doc.pk)
    messages.success(request, "Übergabe gespeichert.")


@action("handover")
def complete_handover(request, order):
    services.complete_handover(order, request.user)
    messages.success(request, "Übergabe abgeschlossen. Viel Erfolg bei der Veranstaltung!")
    return redirect(step_url(order, "return"))


@action("handover")
def upload_photos(request, order, stage):
    if stage not in ("handover", "return"):
        return HttpResponseBadRequest()
    workflow.assert_active(order)
    files = request.FILES.getlist("images")
    if not files:
        raise ValidationError("Bitte mindestens ein Foto auswählen.")
    article = Article.objects.filter(pk=_pk(request.POST["article"])).first() if request.POST.get("article") else None
    for f in files[:20]:
        processed = process_image(f)
        Photo.objects.create(order=order, stage=stage, article=article, image=processed, caption=request.POST.get("caption", "")[:200], created_by=request.user)
    messages.success(request, f"{len(files[:20])} Foto(s) gespeichert.")
    return redirect(step_url(order, stage))


@action("handover")
def delete_photo(request, order, photo_pk):
    photo = get_object_or_404(order.photos, pk=photo_pk)
    if photo.stage == "handover" and workflow.handover_completed(order):
        raise WorkflowError("Fotos einer abgeschlossenen Übergabe bleiben als Nachweis erhalten.")
    if photo.stage == "return" and workflow.return_completed(order):
        raise WorkflowError("Fotos einer abgeschlossenen Rücknahme bleiben als Nachweis erhalten.")
    stage = photo.stage
    photo.image.delete(save=False)
    photo.delete()
    return redirect(step_url(order, stage))


# --------------------------------------------------------------------------
# Schritt 8 & 9
# --------------------------------------------------------------------------

@action("return")
def start_return(request, order):
    services.start_return(order, request.user)


@action("return")
def save_return(request, order):
    form = ReturnForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte den Zeitpunkt der Rücknahme angeben.")
    items = {}
    for item in order.return_record.items.all():
        p = f"item-{item.pk}-"
        items[item.pk] = {
            "returned_qty": max(0, _int(request.POST.get(p + "returned_qty"), item.returned_qty)),
            "damaged_qty": max(0, _int(request.POST.get(p + "damaged_qty"), item.damaged_qty)),
            "condition": request.POST.get(p + "condition") if request.POST.get(p + "condition") in ("good", "used", "damaged") else item.condition,
            "note": request.POST.get(p + "note", "")[:300],
        }
    services.save_return(order, {**form.cleaned_data, "items": items}, request.user)
    if "complete" in request.POST:
        services.complete_return(order, request.user)
        messages.success(request, "Rücknahme abgeschlossen, Rücknahmeprotokoll erstellt.")
        return redirect(step_url(order, "close"))
    messages.success(request, "Rücknahme gespeichert. Schäden und Fehlmengen wurden übernommen.")


@action("return")
def add_damage(request, order):
    form = DamageForm(request.POST, order=order)
    if not form.is_valid():
        raise ValidationError("Bitte Art, Beschreibung und Betrag angeben.")
    services.add_damage(order, user=request.user, **form.cleaned_data)
    messages.success(request, "Posten erfasst.")
    if request.POST.get("next") == "close":
        return redirect(step_url(order, "close"))


@action("return")
def update_damage(request, order, damage_pk):
    dmg = get_object_or_404(order.damages, pk=damage_pk)
    amount = _dec(request.POST.get("amount"), dmg.amount)
    if amount is None or amount < 0:
        raise ValidationError("Bitte einen gültigen Betrag angeben.")
    services.update_damage(dmg, amount=amount, description=request.POST.get("description", dmg.description)[:300] or dmg.description,
                           write_off=bool(request.POST.get("write_off")), user=request.user)
    if request.POST.get("next") == "close":
        return redirect(step_url(order, "close"))


@action("return")
def delete_damage(request, order, damage_pk):
    dmg = get_object_or_404(order.damages, pk=damage_pk)
    services.delete_damage(dmg, request.user)
    if request.POST.get("next") == "close":
        return redirect(step_url(order, "close"))


@action("close")
def settle(request, order):
    decisions = {}
    for dmg in order.damages.filter(settlement=Damage.Settlement.OPEN):
        decisions[dmg.pk] = request.POST.get(f"damage-{dmg.pk}")
    method = request.POST.get("refund_method", "transfer")
    services.settle(order, decisions=decisions, refund_method=method, user=request.user)
    messages.success(request, "Abrechnung erstellt.")


@action("close")
def close_order(request, order):
    services.close_order(order, request.user)
    messages.success(request, f"Auftrag {order.number} ist abgeschlossen. 🎉")


@action("close")
def cancel_order(request, order):
    form = CancelForm(request.POST)
    if not form.is_valid():
        raise ValidationError("Bitte einen Stornogrund angeben.")
    services.cancel_order(order, reason=form.cleaned_data["reason"], fee=form.cleaned_data.get("fee") or Decimal("0"), user=request.user)
    messages.success(request, f"Auftrag {order.number} wurde storniert.")


@action("close")
def refund_deposit_cancelled(request, order):
    services.refund_deposit_after_cancellation(order, method=request.POST.get("method", "transfer"), user=request.user)
    messages.success(request, "Kautionsrückzahlung erfasst.")


@require_POST
def duplicate(request, pk):
    """Neuen Auftrag mit gleichem Kunden und gleichen Positionen anlegen (z. B. für jährliche Events)."""
    source = get_object_or_404(Order, pk=pk)
    order = services.create_order(request.user, source.customer if source.customer and not source.customer.is_anonymized else None)
    order.event_name = source.event_name
    order.event_location = source.event_location
    order.fulfillment = source.fulfillment
    order.delivery_address = source.delivery_address
    order.deposit_amount = source.deposit_amount
    order.deposit_manual = source.deposit_manual
    order.customer_note = source.customer_note
    order.save()
    for item in source.items.all():
        OrderItem.objects.create(order=order, kind=item.kind, article=item.article, package=item.package, description=item.description,
                                 detail=item.detail, quantity=item.quantity, unit_price=item.unit_price,
                                 discount_percent=item.discount_percent, vat_rate=item.vat_rate, sort=item.sort)
    audit.log(request.user, "order", f"Auftrag aus {source.number} kopiert", obj=order, order=order)
    messages.success(request, f"Auftrag {order.number} wurde als Kopie angelegt. Bitte die Termine eintragen.")
    return redirect(step_url(order, "event"))


@require_POST
def delete_draft(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        number = services.delete_draft(order, request.user)
    except WorkflowError as e:
        messages.error(request, str(e))
        return redirect(order.get_absolute_url())
    messages.success(request, f"Der leere Auftrag {number} wurde gelöscht.")
    return redirect("orders:list")
