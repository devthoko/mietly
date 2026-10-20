"""E-Mail-Versand über den in den Einstellungen hinterlegten SMTP-Server.

Dokumente werden im Hintergrund versendet: Die Seite wartet nicht auf den
Mailserver, und bei einer Störung (z. B. Zeitüberschreitung) wird der Versand
automatisch wiederholt – zunächst im laufenden Prozess, danach über den
systemd-Timer ``mietly-mail.timer`` (``manage.py mail_retry``).
"""

import logging
import mimetypes
import threading
import time
from datetime import timedelta
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend
from django.db import connection, transaction
from django.utils import timezone

from .models import CompanySettings, EmailLog

logger = logging.getLogger(__name__)

# Wartezeit vor dem 2., 3., 4. … Versuch
RETRY_DELAYS = [timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30), timedelta(hours=2)]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# So lange wartet der Hintergrund-Thread selbst auf die nächste Wiederholung
THREAD_RETRY_WINDOW = timedelta(minutes=3)


class MailError(Exception):
    pass


def _backend(company):
    return EmailBackend(
        host=company.smtp_host,
        port=company.smtp_port,
        username=company.smtp_user or None,
        password=company.smtp_password or None,
        use_tls=company.smtp_security == CompanySettings.SmtpSecurity.STARTTLS,
        use_ssl=company.smtp_security == CompanySettings.SmtpSecurity.SSL,
        timeout=20,
        fail_silently=False,
    )


def _message(company, *, to, subject, body):
    sender = formataddr((company.mail_from_name or company.name, company.mail_from_email))
    return EmailMessage(
        subject=subject,
        body=body,
        from_email=sender,
        to=[to],
        bcc=[company.mail_bcc] if company.mail_bcc else None,
        reply_to=[company.email] if company.email else None,
        connection=_backend(company),
    )


def _attach(msg, documents):
    names = []
    for doc in documents:
        f = doc.final_file
        name = doc.final_filename
        f.open("rb")
        try:
            msg.attach(name, f.read(), mimetypes.guess_type(name)[0] or "application/octet-stream")
        finally:
            f.close()
        names.append(name)
    return names


def _check_configured(company):
    if not company.mail_configured:
        raise MailError("Der E-Mail-Versand ist noch nicht eingerichtet (Einstellungen → E-Mail).")


def send_mail(*, to, subject, body, documents=(), user=None, order=None):
    """Sendet sofort und protokolliert das Ergebnis (für die Testmail). Wirft MailError bei Fehlern."""
    company = CompanySettings.get()
    _check_configured(company)
    msg = _message(company, to=to, subject=subject, body=body)
    names = _attach(msg, documents)
    error = ""
    try:
        msg.send()
    except Exception as exc:  # noqa: BLE001 – jede SMTP-Störung soll protokolliert werden
        logger.warning("E-Mail an %s fehlgeschlagen: %s", to, exc)
        error = str(exc) or exc.__class__.__name__
    with transaction.atomic():
        EmailLog.objects.create(
            user=user if user and user.is_authenticated else None, order=order, to=to, subject=subject, body=body,
            attachments=names, status=EmailLog.Status.FAILED if error else EmailLog.Status.SENT, error=error,
            attempts=1, sent_at=None if error else timezone.now(),
        )
    if error:
        raise MailError(f"Die E-Mail konnte nicht gesendet werden: {error}")


# --------------------------------------------------------------------------
# Versand im Hintergrund
# --------------------------------------------------------------------------

def queue_mail(*, to, subject, body, documents=(), user=None, order=None):
    """Legt die E-Mail zum Versand an und startet ihn nach dem Speichern im Hintergrund."""
    company = CompanySettings.get()
    _check_configured(company)
    log = EmailLog.objects.create(
        user=user if user and user.is_authenticated else None, order=order, to=to, subject=subject, body=body,
        attachments=[d.final_filename for d in documents], document_ids=[d.pk for d in documents],
        status=EmailLog.Status.QUEUED, next_attempt_at=timezone.now(),
    )
    if getattr(settings, "MAIL_ASYNC", True):
        transaction.on_commit(lambda: _start_worker(log.pk))
    return log


def _start_worker(log_id):
    threading.Thread(target=_worker, args=(log_id,), name=f"mail-{log_id}", daemon=True).start()


def _worker(log_id):
    from .models import _settings_cache

    _settings_cache.set(None)  # im Hintergrund immer frisch lesen, nie den Speicher der Anfrage
    try:
        deadline = timezone.now() + THREAD_RETRY_WINDOW
        while True:
            log = deliver(log_id)
            if log is None or log.status != EmailLog.Status.QUEUED or log.next_attempt_at > deadline:
                return
            time.sleep(max(1.0, (log.next_attempt_at - timezone.now()).total_seconds()))
    except Exception:  # noqa: BLE001
        logger.exception("Hintergrundversand der E-Mail %s abgebrochen", log_id)
    finally:
        connection.close()


def deliver(log_id):
    """Ein Zustellversuch. Gibt den aktualisierten Protokolleintrag zurück
    (oder None, wenn gerade ein anderer Prozess diese E-Mail versendet)."""
    from apps.documents.models import Document

    now = timezone.now()
    # Eintrag für diesen Versuch reservieren, damit Thread und Timer nicht doppelt senden
    claimed = EmailLog.objects.filter(pk=log_id, status=EmailLog.Status.QUEUED, next_attempt_at__lte=now).update(
        next_attempt_at=now + timedelta(minutes=5)
    )
    if not claimed:
        return None
    log = EmailLog.objects.get(pk=log_id)
    company = CompanySettings.get()
    error = ""
    documents = []
    try:
        _check_configured(company)
        by_id = Document.objects.in_bulk(log.document_ids)
        documents = [by_id[i] for i in log.document_ids if i in by_id]
        msg = _message(company, to=log.to, subject=log.subject, body=log.body)
        _attach(msg, documents)
        msg.send()
    except Exception as exc:  # noqa: BLE001
        error = str(exc) or exc.__class__.__name__
        logger.warning("E-Mail %s an %s: Versuch %s fehlgeschlagen: %s", log.pk, log.to, log.attempts + 1, error)

    log.attempts += 1
    if not error:
        log.status = EmailLog.Status.SENT
        log.sent_at = timezone.now()
        log.error = ""
        log.next_attempt_at = None
    elif log.attempts >= MAX_ATTEMPTS:
        log.status = EmailLog.Status.FAILED
        log.error = error
        log.next_attempt_at = None
    else:
        log.error = error
        log.next_attempt_at = timezone.now() + RETRY_DELAYS[log.attempts - 1]
    log.save(update_fields=["status", "sent_at", "error", "next_attempt_at", "attempts"])

    if not error:
        from . import audit

        Document.objects.filter(pk__in=[d.pk for d in documents]).update(last_emailed_at=log.sent_at)
        names = ", ".join(d.display_name for d in documents) or log.subject
        audit.log(log.user, "email", f"{names} per E-Mail an {log.to} gesendet", order=log.order)
    elif log.status == EmailLog.Status.FAILED:
        from . import audit

        audit.log(log.user, "email", f"E-Mail an {log.to} konnte nach {log.attempts} Versuchen nicht zugestellt werden: {error[:200]}",
                  order=log.order)
    return log


def retry_due():
    """Fällige Wiederholungen versenden (aufgerufen vom systemd-Timer)."""
    count = 0
    for pk in EmailLog.objects.filter(status=EmailLog.Status.QUEUED, next_attempt_at__lte=timezone.now()).values_list("pk", flat=True):
        if deliver(pk) is not None:
            count += 1
    return count


def requeue(log):
    """Fehlgeschlagene E-Mail erneut in den Versand geben (Schaltfläche „Erneut senden“)."""
    EmailLog.objects.filter(pk=log.pk).update(status=EmailLog.Status.QUEUED, attempts=0, next_attempt_at=timezone.now(), error="")
    if getattr(settings, "MAIL_ASYNC", True):
        transaction.on_commit(lambda: _start_worker(log.pk))
