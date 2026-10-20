"""Auslieferung geschützter Dateien.

Hochgeladene Dateien und Dokumente liegen außerhalb des Web-Roots und werden
nur nach einer Berechtigungsprüfung ausgeliefert. Im Betrieb übernimmt nginx
die eigentliche Übertragung (X-Accel-Redirect), in Entwicklung/Tests Django.
"""

import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse


def protected_file_response(path, download_name, *, internal_prefix="/_protected/", root=None, inline=False, accel=True):
    path = Path(path).resolve()
    root = Path(root or settings.MEDIA_ROOT).resolve()
    if root not in path.parents or not path.is_file():
        raise Http404
    content_type = mimetypes.guess_type(download_name)[0] or "application/octet-stream"
    disposition = "inline" if inline else "attachment"
    header = f"{disposition}; filename*=UTF-8''{quote(download_name)}"
    if settings.USE_X_ACCEL and accel:
        rel = path.relative_to(root).as_posix()
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = internal_prefix + quote(rel)
    else:
        response = FileResponse(open(path, "rb"), content_type=content_type)
    response["Content-Disposition"] = header
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def media_response(field_file, download_name=None, inline=False):
    if not field_file:
        raise Http404
    name = download_name or Path(field_file.name).name
    return protected_file_response(field_file.path, name, inline=inline)
