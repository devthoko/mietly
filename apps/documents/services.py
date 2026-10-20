"""Erstellen, Versionieren und Unterschreiben von Dokumenten."""

import base64
import binascii
import hashlib
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image

from apps.core import audit
from apps.orders.workflow import WorkflowError

from . import snapshots
from .models import Document
from .pdf import render_pdf

# Alle Auftragsdokumente tragen die Nummer des Auftrags (AU-2026-0007 → AN-2026-0007, MV-2026-0007 …).
# Nur Rechnungen haben aus steuerlichen Gründen einen eigenen, lückenlosen Nummernkreis.
SUFFIX = {"offer": "AN", "contract": "MV", "packing_list": "PL", "handover": "UP", "return": "RP", "deposit": "KA"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _order_suffix(order):
    # AU-2026-0001 → 2026-0001
    return order.number.split("-", 1)[1]


def _doc_number(order, kind):
    number = f"{SUFFIX[kind]}-{_order_suffix(order)}"
    # Vor 1.0.4 wurden Angebote und Verträge fortlaufend gezählt – eine solche Nummer kann
    # bereits bei einem anderen Auftrag vergeben sein. Dann einen Zusatz anhängen.
    candidate, n = number, 1
    while Document.objects.filter(kind=kind, number=candidate).exclude(order=order).exists():
        n += 1
        candidate = f"{number}-{n}"
    return candidate


def _next_version(order, kind):
    prev = order.documents.filter(kind=kind).order_by("-version").first()
    return prev, (prev.version + 1 if prev else 1)


def _supersede(order, kind):
    order.documents.filter(kind=kind, status__in=[Document.Status.ISSUED, Document.Status.SIGNED]).update(status=Document.Status.SUPERSEDED)


def _store(order, kind, number, version, data, versions, user):
    pdf = render_pdf(kind, data)
    doc = Document(
        order=order, kind=kind, number=number, version=version, title=data["title"],
        sha256=_sha(pdf), data=data, template_versions=versions, created_by=user,
    )
    doc.file.save(doc.filename, ContentFile(pdf), save=False)
    doc.save()
    return doc


@transaction.atomic
def create_offer(order, user):
    from apps.orders.workflow import assert_can_create_offer, refresh_stage

    assert_can_create_offer(order)
    prev, version = _next_version(order, "offer")
    number = prev.number if prev else _doc_number(order, "offer")
    _supersede(order, "offer")
    _supersede(order, "contract")  # ein neues Angebot erfordert auch einen neuen Vertrag
    data, versions = snapshots.offer(order, number, version)
    doc = _store(order, "offer", number, version, data, versions, user)
    audit.log(user, "document", f"{doc.display_name} erstellt", obj=doc, order=order)
    refresh_stage(order)
    return doc


@transaction.atomic
def create_contract(order, user):
    from apps.orders.workflow import assert_can_create_contract, refresh_stage

    assert_can_create_contract(order)
    prev, version = _next_version(order, "contract")
    number = prev.number if prev else _doc_number(order, "contract")
    _supersede(order, "contract")
    data, versions = snapshots.contract(order, number, version)
    doc = _store(order, "contract", number, version, data, versions, user)
    audit.log(user, "document", f"{doc.display_name} erstellt", obj=doc, order=order)
    refresh_stage(order)
    return doc


@transaction.atomic
def create_simple(order, kind, user, builder):
    """Packliste, Übergabe-/Rücknahmeprotokoll, Kautionsabrechnung."""
    from apps.orders.workflow import refresh_stage

    prev, version = _next_version(order, kind)
    number = _doc_number(order, kind)
    _supersede(order, kind)
    data, versions = builder(order, number, version)
    doc = _store(order, kind, number, version, data, versions, user)
    audit.log(user, "document", f"{doc.display_name} erstellt", obj=doc, order=order)
    refresh_stage(order)
    return doc


def create_invoice_document(invoice, user):
    data, versions = snapshots.invoice(invoice)
    doc = _store(invoice.order, "invoice", invoice.number, 1, data, versions, user)
    invoice.document = doc
    invoice.save(update_fields=["document"])
    return doc


# --------------------------------------------------------------------------
# Unterschriften
# --------------------------------------------------------------------------

def _check_signable(doc):
    if not doc.requires_signature:
        raise WorkflowError("Dieses Dokument benötigt keine Unterschrift.")
    if doc.status == Document.Status.SIGNED:
        raise WorkflowError("Das Dokument ist bereits unterschrieben.")
    if doc.status != Document.Status.ISSUED:
        raise WorkflowError("Dieses Dokument ist nicht mehr aktuell und kann nicht unterschrieben werden.")
    if doc.order.status != doc.order.Status.ACTIVE:
        raise WorkflowError("Der Auftrag ist nicht mehr aktiv.")
    if doc.kind == "handover":
        from apps.orders.workflow import assert_handover_allowed

        assert_handover_allowed(doc.order)


def _decode_signature(data_url):
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        raise ValidationError("Bitte unterschreiben Sie im Unterschriftenfeld.")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("Die Unterschrift konnte nicht gelesen werden.")
    if len(raw) > 2 * 1024 * 1024:
        raise ValidationError("Die Unterschrift ist zu groß.")
    try:
        img = Image.open(BytesIO(raw))
        img.verify()
        img = Image.open(BytesIO(raw)).convert("RGBA")
    except Exception:
        raise ValidationError("Die Unterschrift ist kein gültiges Bild.")
    bbox = img.getchannel("A").getbbox()
    if bbox is None or (bbox[2] - bbox[0]) < 40:
        raise ValidationError("Die Unterschrift ist zu kurz. Bitte vollständig unterschreiben.")
    # Auf den gezeichneten Bereich zuschneiden
    pad = 12
    img = img.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad)))
    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


@transaction.atomic
def sign_document(doc, *, signer_name, signature_data_url, user, ip=None, user_agent=""):
    from apps.orders.workflow import refresh_stage

    doc = Document.objects.select_for_update().get(pk=doc.pk)
    _check_signable(doc)
    signer_name = (signer_name or "").strip()
    if len(signer_name) < 3:
        raise ValidationError("Bitte den vollständigen Namen der unterzeichnenden Person angeben.")
    png = _decode_signature(signature_data_url)
    now = timezone.now()
    doc.signature_image.save(f"{doc.kind}_{doc.number}_v{doc.version}.png", ContentFile(png), save=False)
    signature = {
        "name": signer_name,
        "date": timezone.localtime(now).strftime("%d.%m.%Y, %H:%M Uhr"),
        "image": doc.signature_image.path,
        "original_sha256": doc.sha256,
        "recorded_by": user.display_name if user else "",
        "method": "drawn",
    }
    pdf = render_pdf(doc.kind, doc.data, signature)
    doc.signed_file.save(doc.filename[:-4] + "_unterschrieben.pdf", ContentFile(pdf), save=False)
    doc.signed_sha256 = _sha(pdf)
    doc.signature_method = Document.SignatureMethod.DRAWN
    doc.signer_name = signer_name
    doc.signed_at = now
    doc.signed_ip = ip
    doc.signed_user_agent = (user_agent or "")[:300]
    doc.signed_recorded_by = user
    doc.status = Document.Status.SIGNED
    doc.save()
    audit.log(user, "signature", f"{doc.display_name} digital unterschrieben von {signer_name}", obj=doc, order=doc.order,
              sha256=doc.sha256, signed_sha256=doc.signed_sha256)
    refresh_stage(doc.order)
    return doc


PDF_MAGIC = b"%PDF-"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@transaction.atomic
def upload_signed(doc, *, upload, signer_name, user):
    from apps.orders.workflow import refresh_stage

    doc = Document.objects.select_for_update().get(pk=doc.pk)
    _check_signable(doc)
    signer_name = (signer_name or "").strip()
    if len(signer_name) < 3:
        raise ValidationError("Bitte den Namen der unterzeichnenden Person angeben.")
    if upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(f"Die Datei ist zu groß (maximal {settings.MAX_UPLOAD_MB} MB).")
    head = upload.read(8)
    upload.seek(0)
    if head.startswith(PDF_MAGIC):
        ext = ".pdf"
    elif head.startswith(JPEG_MAGIC):
        ext = ".jpg"
    elif head.startswith(PNG_MAGIC):
        ext = ".png"
    else:
        raise ValidationError("Bitte ein PDF oder ein Foto (JPG/PNG) des unterschriebenen Dokuments hochladen.")
    content = upload.read()
    doc.signed_file.save(doc.filename[:-4] + "_unterschrieben" + ext, ContentFile(content), save=False)
    doc.signed_sha256 = _sha(content)
    doc.signature_method = Document.SignatureMethod.UPLOAD
    doc.signer_name = signer_name
    doc.signed_at = timezone.now()
    doc.signed_recorded_by = user
    doc.status = Document.Status.SIGNED
    doc.save()
    audit.log(user, "signature", f"Unterschriebenes Dokument hochgeladen: {doc.display_name} ({signer_name})", obj=doc, order=doc.order)
    refresh_stage(doc.order)
    return doc
