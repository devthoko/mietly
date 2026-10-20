from django.shortcuts import render


def forbidden(request, exception=None):
    return render(request, "errors/error.html", {
        "code": 403, "title": "Keine Berechtigung",
        "text": str(exception) if exception and str(exception) else "Für diese Seite fehlen Ihnen die nötigen Rechte.",
    }, status=403)


def not_found(request, exception=None):
    return render(request, "errors/error.html", {
        "code": 404, "title": "Seite nicht gefunden",
        "text": "Die angeforderte Seite existiert nicht oder wurde entfernt.",
    }, status=404)


def bad_request(request, exception=None):
    """Meist eine Adresse, die nicht in MIETLY_ALLOWED_HOSTS steht."""
    from django.core.exceptions import DisallowedHost
    from django.http import HttpResponseBadRequest
    from django.utils.html import escape

    if isinstance(exception, DisallowedHost):
        host = escape(request.META.get("HTTP_HOST", ""))
        text = (
            f"Die Adresse <strong>{host}</strong> ist für mietly noch nicht freigegeben. "
            f"Bitte auf dem Server in <code>/etc/mietly/mietly.env</code> bei <code>MIETLY_ALLOWED_HOSTS</code> "
            f"<code>{host}</code> und bei <code>MIETLY_CSRF_TRUSTED_ORIGINS</code> <code>https://{host}</code> ergänzen "
            f"und anschließend <code>sudo mietly restart</code> ausführen."
        )
    else:
        text = "Die Anfrage war ungültig. Bitte die Seite neu laden."
    html = (
        "<!doctype html><html lang=de><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Ungültige Anfrage · mietly</title><style>body{font-family:system-ui,sans-serif;background:#f6f1e9;color:#2e2823;"
        "display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}div{max-width:520px;padding:28px;background:#fffdf9;"
        "border:1px solid #e6e3de;border-radius:14px;line-height:1.5}code{background:#f0eeeb;padding:1px 5px;border-radius:4px}</style>"
        f"</head><body><div><h1 style='font-size:20px'>Ungültige Anfrage (400)</h1><p>{text}</p></div></body></html>"
    )
    return HttpResponseBadRequest(html)


def server_error(request):
    return render(request, "errors/error_plain.html", status=500)
