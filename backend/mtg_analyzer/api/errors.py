"""One error shape for every `HTTPException` (VIS-24): ``{"detail": {"code", "message", ...params}}``.

Raising sites give a stable ``code`` (`mtg_analyzer.i18n.api_error`); this handler adds the
``message`` in the caller's language (``mtg_lang`` cookie, `Accept-Language`, German). A detail that
already carries a ``message``, a plain string (framework 404/405) or a list (validation) is untouched.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mtg_analyzer.i18n import lang_from_connection, localize_detail

#: Statuses whose responses must not carry a body (RFC 9110).
_BODYLESS_STATUSES = frozenset({204, 304})


async def _localized_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    headers = getattr(exc, "headers", None)
    if exc.status_code in _BODYLESS_STATUSES:
        return JSONResponse(status_code=exc.status_code, content=None, headers=headers)
    detail = localize_detail(exc.detail, lang_from_connection(request))
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _localized_http_exception)
