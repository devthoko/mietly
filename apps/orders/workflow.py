"""Der Auftragsworkflow: Zustand, Fortschritt und verbindliche Sperren.

Alle geschäftlichen Sperren werden hier zentral geprüft. Views, Dienste und
Modelle rufen diese Prüfungen auf – es gibt bewusst keinen Parameter, mit dem
sich eine Sperre umgehen ließe, auch nicht für Administratoren.

Verbindliche Sperren:
  * Mietvertrag nur mit unterschriebenem Angebot
  * Rechnung nur mit unterschriebenem Mietvertrag
  * Übergabe nur bei vollständig bezahlter Rechnung
  * Abschluss der Übergabe nur mit unterschriebenem Übergabeprotokoll
"""

from dataclasses import dataclass, field
from decimal import Decimal
from functools import wraps

from django.db.models import Sum

from apps.core.templatetags.ui import d as _d  # Datum in Ortszeit (Europe/Berlin)

ZERO = Decimal("0.00")


def _fmt(amount):
    return f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


class WorkflowError(Exception):
    """Ein Vorgang ist aufgrund einer geschäftlichen Sperre nicht zulässig."""


# --------------------------------------------------------------------------
# Abfragen
# --------------------------------------------------------------------------

def _memo(fn):
    """Zwischenspeicher für eine Seitenanfrage: Ist am Auftrag `_wf_memo` gesetzt
    (nur beim Anzeigen der Auftragsakte), werden wiederholte Abfragen nur einmal
    ausgeführt. Bei Änderungen (POST) ist der Speicher nicht aktiv."""

    @wraps(fn)
    def wrapper(order, *args):
        cache = getattr(order, "_wf_memo", None)
        if cache is None:
            return fn(order, *args)
        key = (fn.__name__,) + args
        if key not in cache:
            cache[key] = fn(order, *args)
        return cache[key]

    return wrapper


def enable_memo(order):
    order._wf_memo = {}
    return order


@_memo
def current_document(order, kind):
    from apps.documents.models import Document

    cache = getattr(order, "_wf_memo", None)
    if cache is not None:
        # Alle aktuellen Dokumente des Auftrags mit einer Abfrage laden
        if "_current_docs" not in cache:
            docs = {}
            for d in order.documents.filter(status__in=[Document.Status.ISSUED, Document.Status.SIGNED]).order_by("-version", "-created_at"):
                docs.setdefault(d.kind, d)
            cache["_current_docs"] = docs
        return cache["_current_docs"].get(kind)
    return (
        order.documents.filter(kind=kind, status__in=[Document.Status.ISSUED, Document.Status.SIGNED])
        .order_by("-version", "-created_at")
        .first()
    )


def is_signed(order, kind):
    doc = current_document(order, kind)
    return doc is not None and doc.is_signed


@_memo
def main_invoice(order):
    from apps.billing.models import Invoice

    for inv in order.invoices.filter(kind=Invoice.Kind.INVOICE).select_related("cancelled_by").order_by("-id"):
        if inv.is_active:
            return inv
    return None


@_memo
def active_invoices(order):
    return [inv for inv in order.invoices.select_related("cancelled_by") if inv.is_active]


@_memo
def paid_total(order):
    return order.payments.aggregate(s=Sum("amount"))["s"] or ZERO


def invoiced_total(order):
    return sum((inv.total_gross for inv in active_invoices(order)), ZERO)


def open_balance(order):
    """Positiv = Kunde schuldet noch, negativ = Guthaben/Erstattung fällig."""
    return invoiced_total(order) - paid_total(order)


def invoice_fully_paid(order):
    inv = main_invoice(order)
    if inv is None:
        return False
    return paid_total(order) >= inv.total_gross


@dataclass
class DepositState:
    agreed: Decimal
    received: Decimal
    refunded: Decimal
    retained: Decimal

    @property
    def held(self):
        return self.received - self.refunded - self.retained

    @property
    def outstanding(self):
        return max(ZERO, self.agreed - self.received)

    @property
    def required(self):
        return self.agreed > 0

    @property
    def settled(self):
        return self.held == 0


@_memo
def deposit_state(order):
    sums = {k: ZERO for k in ("received", "refunded", "retained")}
    for row in order.deposit_transactions.values("kind").annotate(s=Sum("amount")):
        sums[row["kind"]] = row["s"] or ZERO
    return DepositState(agreed=order.deposit_amount, **sums)


def handover_completed(order):
    h = getattr(order, "handover", None)
    return h is not None and h.is_completed


def return_completed(order):
    r = getattr(order, "return_record", None)
    return r is not None and r.is_completed


def event_complete(order):
    if not (order.event_name and order.event_date and order.handover_at and order.return_at):
        return False
    if order.return_at <= order.handover_at:
        return False
    if order.fulfillment == order.Fulfillment.DELIVERY and not order.delivery_address.strip():
        return False
    return True


def deposit_blocks_handover(order):
    from apps.core.models import CompanySettings

    if not CompanySettings.get().deposit_required_before_handover:
        return False
    return deposit_state(order).outstanding > 0


# --------------------------------------------------------------------------
# Sperren (werfen WorkflowError)
# --------------------------------------------------------------------------

def assert_active(order):
    if order.status != order.Status.ACTIVE:
        raise WorkflowError(f"Der Auftrag ist {order.get_status_display().lower()} und kann nicht mehr bearbeitet werden.")


def assert_can_edit_items(order):
    assert_active(order)
    if main_invoice(order) is not None:
        raise WorkflowError("Es gibt bereits eine Rechnung. Positionen können erst nach einer Stornierung der Rechnung geändert werden.")
    if is_signed(order, "offer"):
        raise WorkflowError("Das Angebot ist bereits unterschrieben. Erstellen Sie eine neue Angebotsversion, um Positionen zu ändern.")


def assert_can_create_offer(order):
    assert_active(order)
    if order.customer is None:
        raise WorkflowError("Bitte zuerst einen Kunden auswählen.")
    if not event_complete(order):
        raise WorkflowError("Bitte zuerst die Eventdaten vollständig erfassen (Name, Datum, Übergabe- und Rückgabetermin).")
    if not order.has_rental_items():
        raise WorkflowError("Das Angebot enthält noch keine Mietgegenstände.")
    if main_invoice(order) is not None:
        raise WorkflowError("Es gibt bereits eine Rechnung. Ein neues Angebot ist erst nach Stornierung der Rechnung möglich.")
    from .availability import shortages

    missing = shortages(order)
    if missing:
        names = ", ".join(f"{s.article.name} (fehlen {s.missing})" for s in missing)
        raise WorkflowError(f"Nicht genügend Bestand im Mietzeitraum: {names}.")


def assert_can_create_contract(order):
    assert_active(order)
    if not is_signed(order, "offer"):
        raise WorkflowError("Der Mietvertrag kann erst erstellt werden, wenn das Angebot unterschrieben ist.")
    if main_invoice(order) is not None:
        raise WorkflowError("Es gibt bereits eine Rechnung zu diesem Vertrag.")


def assert_can_issue_invoice(order):
    assert_active(order)
    if not is_signed(order, "contract"):
        raise WorkflowError("Die Rechnung kann erst erstellt werden, wenn der Mietvertrag unterschrieben ist.")
    if main_invoice(order) is not None:
        raise WorkflowError("Für diesen Auftrag gibt es bereits eine gültige Rechnung.")
    assert_invoice_data_complete(order)


def missing_invoice_data(order):
    """Fehlende Pflichtangaben nach § 14 UStG für die spätere Rechnung."""
    from apps.core.models import CompanySettings

    company = CompanySettings.get()
    missing = []
    if not (company.name and company.street and company.zip_code and company.city):
        missing.append("vollständige Anschrift des Betriebs (Einstellungen → Geschäftsdaten)")
    if not (company.tax_number or company.vat_id):
        missing.append("Steuernummer oder USt-IdNr. (Einstellungen → Steuer & Bank)")
    c = order.customer
    if c is None or not (c.street and c.zip_code and c.city):
        missing.append("vollständige Anschrift des Kunden")
    return missing


def assert_invoice_data_complete(order):
    """Eine ausgestellte Rechnung ist unveränderlich, deshalb wird vorher geprüft,
    ob alle Pflichtangaben vorhanden sind."""
    missing = missing_invoice_data(order)
    if missing:
        raise WorkflowError("Für die Rechnung fehlen noch Pflichtangaben: " + "; ".join(missing) + ".")


def assert_handover_allowed(order):
    assert_active(order)
    if main_invoice(order) is None:
        raise WorkflowError("Die Übergabe ist erst möglich, wenn eine Rechnung erstellt und vollständig bezahlt wurde.")
    if not invoice_fully_paid(order):
        missing = main_invoice(order).total_gross - paid_total(order)
        raise WorkflowError(f"Die Übergabe ist gesperrt: Die Rechnung ist noch nicht vollständig bezahlt (offen: {_fmt(missing)}).")
    if deposit_blocks_handover(order):
        raise WorkflowError(f"Die Übergabe ist gesperrt: Die vereinbarte Kaution ist noch nicht vollständig eingegangen (offen: {_fmt(deposit_state(order).outstanding)}).")


def assert_handover_completable(order, handover=None):
    assert_handover_allowed(order)
    if not is_signed(order, "handover"):
        raise WorkflowError("Die Übergabe kann erst abgeschlossen werden, wenn das Übergabeprotokoll unterschrieben ist.")


def assert_can_start_return(order):
    assert_active(order)
    if not handover_completed(order):
        raise WorkflowError("Die Rücknahme ist erst nach abgeschlossener Übergabe möglich.")


def close_blockers(order):
    blockers = []
    if not return_completed(order):
        blockers.append("Die Rücknahme ist noch nicht abgeschlossen.")
    if order.damages.filter(settlement="open").exists():
        blockers.append("Es gibt Schäden oder Fehlmengen, deren Abrechnung noch offen ist.")
    dep = deposit_state(order)
    if dep.held != 0:
        blockers.append(f"Die Kaution ist noch nicht abgerechnet (verwahrt: {_fmt(dep.held)}).")
    balance = open_balance(order)
    if balance > 0:
        blockers.append(f"Es sind noch Rechnungsbeträge offen ({_fmt(balance)}).")
    elif balance < 0:
        blockers.append(f"Es besteht ein Guthaben des Kunden ({_fmt(-balance)}), das erstattet werden muss.")
    return blockers


def assert_can_close(order):
    assert_active(order)
    blockers = close_blockers(order)
    if blockers:
        raise WorkflowError(" ".join(blockers))


# --------------------------------------------------------------------------
# Fortschrittsanzeige
# --------------------------------------------------------------------------

STEPS = [
    (1, "customer", "Kunde"),
    (2, "event", "Event"),
    (3, "offer", "Angebot"),
    (4, "contract", "Mietvertrag"),
    (5, "invoice", "Rechnung"),
    (6, "packing", "Packliste"),
    (7, "handover", "Übergabe"),
    (8, "return", "Rücknahme"),
    (9, "close", "Kaution & Abschluss"),
]


@dataclass
class Step:
    number: int
    key: str
    title: str
    done: bool = False
    locked: bool = False
    current: bool = False
    summary: str = ""
    blockers: list = field(default_factory=list)

    @property
    def state(self):
        if self.done:
            return "done"
        if self.current:
            return "current"
        if self.locked:
            return "locked"
        return "open"


@dataclass
class WorkflowState:
    steps: list
    current: Step
    next_action: str
    next_hint: str


def compute(order) -> WorkflowState:
    from apps.core.models import CompanySettings

    company = CompanySettings.get()
    offer = current_document(order, "offer")
    contract = current_document(order, "contract")
    packing = current_document(order, "packing_list")
    handover_doc = current_document(order, "handover")
    inv = main_invoice(order)
    paid = paid_total(order)
    dep = deposit_state(order)
    has_items = order.has_rental_items()  # nur die Lieferpauschale zählt nicht

    s = {key: Step(n, key, title) for n, key, title in STEPS}

    # 1 Kunde
    s["customer"].done = order.customer_id is not None
    s["customer"].summary = order.customer.full_name if order.customer_id else "Noch kein Kunde gewählt"

    # 2 Event
    s["event"].done = event_complete(order)
    if order.event_name:
        s["event"].summary = order.event_name
    if not s["event"].done:
        s["event"].blockers.append("Name, Datum, Übergabe- und Rückgabetermin erfassen")

    # 3 Angebot
    s["offer"].done = offer is not None and offer.is_signed
    if offer is None:
        s["offer"].summary = "Noch kein Angebot erstellt"
        if not has_items:
            s["offer"].blockers.append("Artikel oder Pakete hinzufügen")
    elif offer.is_signed:
        s["offer"].summary = f"{offer.number} unterschrieben"
    else:
        s["offer"].summary = f"{offer.number} wartet auf Unterschrift"
        s["offer"].blockers.append("Angebot unterschreiben lassen oder unterschriebenes PDF hochladen")

    # 4 Vertrag
    s["contract"].locked = not s["offer"].done
    s["contract"].done = contract is not None and contract.is_signed
    if s["contract"].locked:
        s["contract"].blockers.append("Angebot muss unterschrieben sein")
    elif contract is None:
        s["contract"].summary = "Vertrag erstellen"
    elif contract.is_signed:
        s["contract"].summary = f"{contract.number} unterschrieben"
    else:
        s["contract"].summary = f"{contract.number} wartet auf Unterschrift"
        s["contract"].blockers.append("Vertrag unterschreiben lassen oder unterschriebenes PDF hochladen")

    # 5 Rechnung
    s["invoice"].locked = not s["contract"].done
    s["invoice"].done = inv is not None and paid >= inv.total_gross
    if s["invoice"].locked:
        s["invoice"].blockers.append("Mietvertrag muss unterschrieben sein")
    elif inv is None:
        s["invoice"].summary = "Rechnung erstellen"
    elif s["invoice"].done:
        s["invoice"].summary = f"{inv.number} bezahlt"
    else:
        s["invoice"].summary = f"{inv.number}: offen {_fmt(inv.total_gross - paid)}"
        s["invoice"].blockers.append(f"Zahlungseingang erfassen (offen {_fmt(inv.total_gross - paid)})")

    # 6 Packliste (darf auch vor Bezahlung erstellt werden)
    s["packing"].done = packing is not None
    s["packing"].locked = not has_items
    s["packing"].summary = f"erstellt am {_d(packing.created_at)}" if packing else "Packliste erstellen"

    # 7 Übergabe
    handover_done = handover_completed(order)
    s["handover"].done = handover_done
    if not handover_done:
        if not s["invoice"].done:
            s["handover"].locked = True
            s["handover"].blockers.append("Rechnung muss vollständig bezahlt sein")
        if company.deposit_required_before_handover and dep.outstanding > 0:
            s["handover"].locked = True
            s["handover"].blockers.append(f"Kaution muss eingegangen sein (offen {_fmt(dep.outstanding)})")
        if not s["handover"].locked:
            if handover_doc is None:
                s["handover"].blockers.append("Übergabe erfassen und Protokoll erstellen")
            elif not handover_doc.is_signed:
                s["handover"].blockers.append("Übergabeprotokoll unterschreiben lassen")
    else:
        s["handover"].summary = f"am {_d(order.handover.completed_at)}"

    # 8 Rücknahme
    s["return"].locked = not handover_done
    s["return"].done = return_completed(order)
    if s["return"].locked:
        s["return"].blockers.append("Übergabe muss abgeschlossen sein")
    elif s["return"].done:
        s["return"].summary = f"am {_d(order.return_record.completed_at)}"

    # 9 Abschluss
    s["close"].done = order.status == order.Status.COMPLETED
    s["close"].locked = not s["return"].done
    if not s["close"].done and not s["close"].locked:
        s["close"].blockers = close_blockers(order)
    if dep.required:
        s["close"].summary = f"Kaution {_fmt(dep.agreed)}"

    # Packliste gilt als erledigt, sobald die Übergabe abgeschlossen ist
    if handover_done and not s["packing"].done:
        s["packing"].done = True

    steps = [s[key] for _, key, _ in STEPS]
    if order.status == order.Status.CANCELLED:
        current = steps[0]
        return WorkflowState(steps, current, "Auftrag storniert", order.cancel_reason or "")
    current = next((st for st in steps if not st.done), steps[-1])
    current.current = not current.done

    next_action, hint = _next_action(order, current, offer, contract, inv, handover_doc)
    return WorkflowState(steps, current, next_action, hint)


def _next_action(order, step, offer, contract, inv, handover_doc):
    if order.status == order.Status.COMPLETED:
        return "Auftrag abgeschlossen", "Alle Vorgänge sind erledigt."
    key = step.key
    if key == "customer":
        return "Kunden auswählen", "Bestehenden Kunden suchen oder neu anlegen."
    if key == "event":
        return "Eventdaten erfassen", "Veranstaltung, Datum sowie Übergabe- und Rückgabetermin eintragen."
    if key == "offer":
        if not order.has_rental_items():
            return "Artikel hinzufügen", "Artikel, Pakete oder individuelle Positionen zum Angebot hinzufügen."
        if offer is None:
            return "Angebot erstellen", "Positionen prüfen und das Angebot als PDF erzeugen."
        return "Angebot unterschreiben lassen", "Digital unterschreiben lassen oder das unterschriebene PDF hochladen."
    if key == "contract":
        if contract is None:
            return "Mietvertrag erstellen", "Der Vertrag wird aus den Auftragsdaten und der Vertragsvorlage erzeugt."
        return "Mietvertrag unterschreiben lassen", "Digital unterschreiben lassen oder das unterschriebene PDF hochladen."
    if key == "invoice":
        if inv is None:
            return "Rechnung erstellen", "Die Rechnung wird fortlaufend nummeriert und ist danach unveränderlich."
        return "Zahlungseingang erfassen", "Erst nach vollständiger Bezahlung ist die Übergabe möglich."
    if key == "packing":
        return "Packliste erstellen", "Die Packliste fasst alle Artikel inklusive Paketinhalten zusammen."
    if key == "handover":
        if step.locked:
            return "Übergabe noch gesperrt", " · ".join(step.blockers)
        if handover_doc is None:
            return "Übergabe durchführen", "Mengen und Zustand erfassen, Fotos aufnehmen und Protokoll erstellen."
        if not handover_doc.is_signed:
            return "Übergabeprotokoll unterschreiben lassen", "Ohne Unterschrift kann die Übergabe nicht abgeschlossen werden."
        return "Übergabe abschließen", "Das Protokoll ist unterschrieben."
    if key == "return":
        return "Rücknahme erfassen", "Zurückgegebene Mengen, Schäden und Fehlmengen dokumentieren."
    if key == "close":
        return close_action(order, step.blockers)
    return "", ""


def list_status(order, state):
    """Kurzer Status für Listen: worauf wartet der Auftrag? (Text, Ton)"""
    if order.status != order.Status.ACTIVE:
        return "", ""
    action = state.next_action
    if action.endswith("unterschreiben lassen"):
        return "Wartet auf Unterschrift", "warning"
    if action in ("Zahlungseingang erfassen", "Zahlung abwarten"):
        return "Wartet auf Zahlung", "warning"
    if action == "Übergabe noch gesperrt":
        return ("Wartet auf Kaution" if "Kaution" in state.next_hint and "Rechnung" not in state.next_hint else "Wartet auf Zahlung"), "warning"
    if action in ("Übergabe durchführen", "Übergabe abschließen"):
        return "Bereit zur Übergabe", "info"
    if action == "Rücknahme erfassen":
        return "Beim Kunden", "info"
    if action in ("Kaution abrechnen", "Guthaben erstatten", "Auftrag abschließen"):
        return action, "success"
    return action, "neutral"


def refresh_stage(order):
    state = compute(order)
    stage = state.current.number if order.status == order.Status.ACTIVE else 9
    text, tone = list_status(order, state)
    if (order.stage, order.next_action, order.next_tone) != (stage, text, tone):
        order.stage, order.next_action, order.next_tone = stage, text, tone
        type(order).objects.filter(pk=order.pk).update(stage=stage, next_action=text, next_tone=tone)
    return state


def close_action(order, blockers=None):
    """Bezeichnung des letzten Schritts – je nachdem, was tatsächlich noch fehlt."""
    if blockers is None:
        blockers = close_blockers(order)
    if not blockers:
        return "Auftrag abschließen", "Alle Voraussetzungen sind erfüllt."
    dep = deposit_state(order)
    if dep.held != 0 or order.damages.filter(settlement="open").exists():
        return "Kaution abrechnen", " · ".join(blockers)
    balance = open_balance(order)
    if balance > 0:
        open_invoices = [inv for inv in active_invoices(order) if inv.kind != "invoice"]
        names = ", ".join(f"{inv.get_kind_display()} {inv.number}" for inv in open_invoices)
        hint = f"Offen: {_fmt(balance)}" + (f" ({names})" if names else "") + ". Danach kann der Auftrag abgeschlossen werden."
        return "Zahlung abwarten", hint
    if balance < 0:
        return "Guthaben erstatten", f"Der Kunde erhält noch {_fmt(-balance)} zurück. Danach kann der Auftrag abgeschlossen werden."
    return "Auftrag abschließen", " · ".join(blockers)


def money_issue(order, balance=None, held=None):
    """Offener Betrag oder Guthaben bei stornierten/abgeschlossenen Aufträgen (für die Übersicht)."""
    if balance is None:
        balance = open_balance(order)
    if held is None:
        held = deposit_state(order).held
    if balance == 0 and held == 0:
        return None
    if balance > 0:
        return {"kind": "receivable", "amount": balance, "title": f"Zahlung offen: {_fmt(balance)}"}
    if balance < 0:
        return {"kind": "refund", "amount": -balance, "title": f"Erstattung fällig: {_fmt(-balance)}"}
    return {"kind": "deposit", "amount": held, "title": f"Kaution zurückzahlen: {_fmt(held)}"}


def is_empty_draft(order):
    """Ein Auftrag ohne Dokumente, Rechnungen und Zahlungen darf gelöscht werden."""
    return (
        order.status == order.Status.ACTIVE
        and not order.documents.exists()
        and not order.invoices.exists()
        and not order.payments.exists()
        and not order.deposit_transactions.exists()
        and getattr(order, "handover", None) is None
    )


def awaiting_signature(order, state=None):
    """Das Dokument, auf dessen Unterschrift der Auftrag gerade wartet (für die Aktionsknöpfe)."""
    state = state or compute(order)
    if order.status != order.Status.ACTIVE:
        return None
    key = state.current.key
    kind = {"offer": "offer", "contract": "contract", "handover": "handover"}.get(key)
    if not kind:
        return None
    doc = current_document(order, kind)
    if doc is not None and not doc.is_signed:
        if kind == "handover" and state.current.locked:
            return None
        return doc
    return None


# --------------------------------------------------------------------------
# Summen für Listen und Übersicht – direkt in der Datenbank statt je Auftrag
# --------------------------------------------------------------------------

def with_money(qs):
    """Ergänzt Aufträge um _invoiced, _paid, _dep_received, _dep_refunded, _dep_retained
    (je eine Unterabfrage statt mehrerer Abfragen pro Auftrag)."""
    from django.db.models import DecimalField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    from apps.billing.models import Invoice, Payment

    from .models import DepositTransaction

    def total(model, field, **filters):
        sub = (model.objects.filter(order=OuterRef("pk"), **filters).order_by().values("order")
               .annotate(s=Sum(field)).values("s"))
        return Coalesce(Subquery(sub, output_field=DecimalField(max_digits=12, decimal_places=2)), Value(ZERO))

    active = Invoice.objects.filter(cancelled_by__isnull=True).exclude(kind=Invoice.Kind.CANCELLATION)
    invoiced = (active.filter(order=OuterRef("pk")).order_by().values("order").annotate(s=Sum("total_gross")).values("s"))
    return qs.annotate(
        _invoiced=Coalesce(Subquery(invoiced, output_field=DecimalField(max_digits=12, decimal_places=2)), Value(ZERO)),
        _paid=total(Payment, "amount"),
        _dep_received=total(DepositTransaction, "amount", kind="received"),
        _dep_refunded=total(DepositTransaction, "amount", kind="refunded"),
        _dep_retained=total(DepositTransaction, "amount", kind="retained"),
    )


def money_of(order):
    """(offener Saldo, verwahrte Kaution) eines mit with_money geladenen Auftrags."""
    balance = order._invoiced - order._paid
    held = order._dep_received - order._dep_refunded - order._dep_retained
    return balance, held
