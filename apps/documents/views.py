import re

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.files import protected_file_response
from apps.core.mail import MailError, queue_mail, requeue
from apps.core.models import TextTemplate
from apps.core.permissions import client_ip
from apps.core.textrender import render_placeholders
from apps.orders.forms import EmailForm, SignForm, UploadSignedForm
from apps.orders.workflow import WorkflowError

from . import services
from .context import mail_context, mail_template_key
from .models import Document

STEP_FOR_KIND = {
    "offer": "offer", "contract": "contract", "invoice": "invoice", "packing_list": "packing",
    "handover": "handover", "return": "return", "deposit": "close",
}


def _back(doc):
    return f"{doc.order.get_absolute_url()}?schritt={STEP_FOR_KIND.get(doc.kind, '')}"


def document_list(request):
    qs = Document.objects.select_related("order", "order__customer", "created_by")
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("art", "")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(order__number__icontains=q) | Q(order__event_name__icontains=q)
                       | Q(order__customer__last_name__icontains=q) | Q(signer_name__icontains=q))
    if kind in Document.Kind.values:
        qs = qs.filter(kind=kind)
    page = Paginator(qs, 40).get_page(request.GET.get("seite"))
    return render(request, "documents/list.html", {"page": page, "q": q, "kind": kind, "kinds": Document.Kind.choices})


def download(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    variant = request.GET.get("fassung")
    if variant == "original" or not doc.signed_file:
        f, name = doc.file, doc.filename
    else:
        f, name = doc.signed_file, doc.final_filename
    inline = request.GET.get("download") is None
    return protected_file_response(f.path, name, inline=inline)


def sign(request, pk):
    doc = get_object_or_404(Document.objects.select_related("order", "order__customer"), pk=pk)
    if doc.is_signed:
        messages.info(request, "Dieses Dokument ist bereits unterschrieben.")
        return redirect(_back(doc))
    if doc.status != Document.Status.ISSUED or not doc.requires_signature:
        messages.error(request, "Dieses Dokument ist nicht mehr aktuell oder benötigt keine Unterschrift.")
        return redirect(_back(doc))
    initial_name = doc.order.customer.full_name if doc.order.customer else ""
    if doc.kind == "handover" and hasattr(doc.order, "handover"):
        initial_name = doc.order.handover.recipient_name or initial_name
    form = SignForm(request.POST or None, initial={"signer_name": initial_name})
    upload_form = UploadSignedForm(initial={"signer_name": initial_name})
    if request.method == "POST" and form.is_valid():
        try:
            services.sign_document(
                doc, signer_name=form.cleaned_data["signer_name"], signature_data_url=form.cleaned_data["signature"],
                user=request.user, ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except (WorkflowError, ValidationError) as e:
            messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else str(e))
            return redirect("documents:sign", doc.pk)
        messages.success(request, f"{doc.get_kind_display()} wurde unterschrieben.")
        return redirect(_back(doc))
    return render(request, "documents/sign.html", {"doc": doc, "form": form, "upload_form": upload_form})


@require_POST
def upload_signed(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    form = UploadSignedForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Bitte Namen und Datei angeben.")
        return redirect(request.POST.get("back") or _back(doc))
    try:
        services.upload_signed(doc, upload=form.cleaned_data["file"], signer_name=form.cleaned_data["signer_name"], user=request.user)
        messages.success(request, f"Unterschriebenes Dokument für {doc.display_name} gespeichert.")
    except (WorkflowError, ValidationError) as e:
        messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else str(e))
    return redirect(_back(doc))


def email(request, pk):
    doc = get_object_or_404(Document.objects.select_related("order", "order__customer"), pk=pk)
    order = doc.order
    key = mail_template_key(doc)
    if key is None:
        messages.error(request, "Für diese Dokumentart ist kein E-Mail-Versand vorgesehen.")
        return redirect(_back(doc))
    if request.method == "POST":
        form = EmailForm(request.POST)
        if form.is_valid():
            try:
                queue_mail(to=form.cleaned_data["to"], subject=form.cleaned_data["subject"], body=form.cleaned_data["body"],
                           documents=[doc], user=request.user, order=order)
                messages.success(request, f"{doc.display_name} wird an {form.cleaned_data['to']} gesendet.")
                return redirect(_back(doc))
            except MailError as e:
                messages.error(request, str(e))
    else:
        tpl = TextTemplate.current(key)
        ctx = mail_context(doc)
        body = re.sub(r"\n{3,}", "\n\n", render_placeholders(tpl.body, ctx)).strip() + "\n"
        form = EmailForm(initial={
            "to": order.customer.email if order.customer else "",
            "subject": render_placeholders(tpl.subject, ctx),
            "body": body,
        })
    return render(request, "documents/email.html", {"doc": doc, "form": form, "template_key": key})


@require_POST
def email_retry(request, log_pk):
    from apps.core.models import EmailLog

    log = get_object_or_404(EmailLog, pk=log_pk)
    if log.status != EmailLog.Status.FAILED:
        messages.info(request, "Diese E-Mail wurde bereits zugestellt oder wird gerade gesendet.")
        return redirect(log.order.get_absolute_url() if log.order else "/")
    requeue(log)
    messages.success(request, f"Die E-Mail an {log.to} wird erneut gesendet.")
    back = log.order.get_absolute_url() if log.order else "/"
    return redirect(back)


@require_POST
def print_document(request, pk):
    from apps.core import audit, printing
    from apps.core.models import CompanySettings

    doc = get_object_or_404(Document.objects.select_related("order"), pk=pk)
    from django.utils.http import url_has_allowed_host_and_scheme

    back = request.POST.get("next") or ""
    if not back.startswith("/") or not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        back = _back(doc)
    if not CompanySettings.get().printer_ready:
        messages.error(request, "Es ist noch kein Drucker eingerichtet (Einstellungen → Drucker).")
        return redirect(back)
    copies = request.POST.get("copies", "1")
    copies = int(copies) if copies.isdigit() else 1
    try:
        job = printing.print_file(doc.final_file.path, doc.display_name, copies=copies)
    except printing.PrinterError as e:
        messages.error(request, f"{doc.display_name} konnte nicht gedruckt werden: {e}")
        return redirect(back)
    audit.log(request.user, "print", f"{doc.display_name} gedruckt" + (f" ({copies}×)" if copies > 1 else ""), obj=doc, order=doc.order, job=job)
    messages.success(request, f"{doc.display_name} wird gedruckt" + (f" ({copies}×)." if copies > 1 else "."))
    return redirect(back)
