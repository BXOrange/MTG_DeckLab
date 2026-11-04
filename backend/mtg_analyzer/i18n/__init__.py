"""Server-side message catalogue: stable ``code`` + a ``message`` in the caller's language (VIS-24).

User-facing refusals (HTTP error details, lobby / WebSocket reasons, queue refusals) carry a stable
machine-readable ``code`` and a human ``message`` rendered here from ``catalogue.py``. The language is
the ``mtg_lang`` cookie the frontend already sets, then ``Accept-Language``, then German.

Internal / log-only text stays English and is not routed through this module. Raising sites that have
no request (services) raise `LocalizedError` with a code and parameters; the API boundary translates.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from fastapi import HTTPException, Request

from mtg_analyzer.i18n.catalogue import CATALOGUE, DEFAULT_LANG, SUPPORTED_LANGS

__all__ = [
    "DEFAULT_LANG",
    "LANG_COOKIE",
    "CodedText",
    "LocalizedError",
    "SUPPORTED_LANGS",
    "api_error",
    "has_message",
    "lang_from_connection",
    "localize_detail",
    "localize_parsed_deck",
    "localize_texts",
    "localize_validation",
    "request_lang",
    "message",
    "resolve_lang",
]

#: The cookie the frontend persists the UI language in (`frontend/src/js/i18n.js`).
LANG_COOKIE = "mtg_lang"

#: `q` weight of an `Accept-Language` entry that names none (RFC 9110 section 12.4.2).
_DEFAULT_QUALITY = 1.0

_ACCEPT_ENTRY = re.compile(r"^\s*([A-Za-z*]{1,8})(?:-[A-Za-z0-9-]*)?\s*(?:;\s*q\s*=\s*([0-9.]+))?\s*$")


def has_message(code: str) -> bool:
    """Whether the catalogue knows `code` (in any language)."""
    return any(code in CATALOGUE[lang] for lang in SUPPORTED_LANGS)


def message(code: str, lang: Optional[str] = None, **params: Any) -> str:
    """Render `code` in `lang`; falls back to the other language, then to the code itself.

    Never raises: a missing key or placeholder must not turn a refusal into a 500 (the parity test
    keeps the catalogues complete). Unknown placeholders render empty."""
    order = [lang] if lang in SUPPORTED_LANGS else []
    order += [DEFAULT_LANG] + [other for other in SUPPORTED_LANGS if other != DEFAULT_LANG]
    for candidate in order:
        template = CATALOGUE[candidate].get(code)
        if template is None:
            continue
        try:
            return template.format_map(_Params(params))
        except (ValueError, IndexError, AttributeError):
            return template
    return code


class _Params(dict):
    def __missing__(self, key: str) -> str:
        return ""


def resolve_lang(cookie: Optional[str] = None, accept_language: Optional[str] = None) -> str:
    """`mtg_lang` cookie, else the best supported `Accept-Language` entry (q-values), else German."""
    if cookie in SUPPORTED_LANGS:
        return cookie  # type: ignore[return-value]
    best: Optional[tuple[float, int, str]] = None
    for position, entry in enumerate((accept_language or "").split(",")):
        match = _ACCEPT_ENTRY.match(entry)
        if not match:
            continue
        tag = match.group(1).lower()
        try:
            quality = float(match.group(2)) if match.group(2) is not None else _DEFAULT_QUALITY
        except ValueError:
            continue
        if tag not in SUPPORTED_LANGS or quality <= 0:
            continue
        key = (quality, -position, tag)
        if best is None or key > best:
            best = key
    return best[2] if best else DEFAULT_LANG


def lang_from_connection(connection: Any) -> str:
    """Language of a Starlette `Request` / `WebSocket` (anything with ``cookies`` and ``headers``)."""
    try:
        cookie = connection.cookies.get(LANG_COOKIE)
        accept = connection.headers.get("accept-language")
    except (AttributeError, RuntimeError):
        return DEFAULT_LANG
    return resolve_lang(cookie, accept)


class LocalizedError(Exception):
    """A refusal raised without a request: a stable `code` plus placeholder `params`.

    ``str()`` is the English text (logs, tests); the API boundary renders it in the caller's language."""

    def __init__(self, code: str, **params: Any) -> None:
        self.code = code
        self.params = params
        super().__init__(message(code, "en", **params))

    def render(self, lang: Optional[str]) -> str:
        return message(self.code, lang, **self.params)


class CodedText(str):
    """A refusal text that still knows its `code` and `params` (deck validation lists, VIS-24).

    It *is* the English string, so every consumer that joins, compares or logs the list keeps working;
    the API boundary re-renders it in the caller's language (`localize_texts` and friends), and
    ``issue()`` is the language-neutral form persisted in cached validation results."""

    code: str
    params: dict[str, Any]

    def __new__(cls, code: str, **params: Any) -> "CodedText":
        obj = super().__new__(cls, message(code, "en", **params))
        obj.code = code
        obj.params = params
        return obj

    def issue(self) -> dict[str, Any]:
        return {"code": self.code, "params": self.params}

    def render(self, lang: Optional[str]) -> str:
        return message(self.code, lang, **self.params)


def localize_texts(texts: Any, lang: Optional[str]) -> Any:
    """Render every `CodedText` of a list in `lang`; plain strings stay as they are."""
    if not isinstance(texts, list):
        return texts
    return [item.render(lang) if isinstance(item, CodedText) else item for item in texts]


def _render_issues(issues: Any, fallback: Any, lang: Optional[str]) -> Any:
    """Texts for a list of ``{"code", "params"}`` issues; `fallback` when the list is absent (an old cached result)."""
    if not isinstance(issues, list):
        return fallback
    return [message(issue["code"], lang, **(issue.get("params") or {})) for issue in issues]


def localize_validation(validation: Any, lang: Optional[str]) -> Any:
    """A `DeckValidationResult.to_dict()` with ``errors`` / ``warnings`` in `lang` (from the issue lists)."""
    if not isinstance(validation, dict):
        return validation
    return {
        **validation,
        "errors": _render_issues(validation.get("errorIssues"), validation.get("errors"), lang),
        "warnings": _render_issues(validation.get("warningIssues"), validation.get("warnings"), lang),
    }


def localize_parsed_deck(parsed: dict[str, Any], lang: Optional[str]) -> dict[str, Any]:
    """A `ParsedDeck.to_dict()` with its parse errors and validation texts in `lang`."""
    return {
        **parsed,
        "parseErrors": _render_issues(parsed.get("parseErrorIssues"), parsed.get("parseErrors"), lang),
        "validation": localize_validation(parsed.get("validation"), lang),
    }


def request_lang(request: Request) -> str:
    """FastAPI dependency: the calling request's language."""
    return lang_from_connection(request)


def api_error(
    status: int,
    code: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    **params: Any,
) -> HTTPException:
    """An `HTTPException` whose detail is ``{"code", **params}``; the app's exception handler adds the
    localized ``message`` for the request's language (`api/errors.py`)."""
    return HTTPException(status, {"code": code, **params}, headers=dict(headers) if headers else None)


def error_from(exc: Exception, status: int, *, headers: Optional[Mapping[str, str]] = None) -> HTTPException:
    """Boundary translation of a service exception. A `LocalizedError` keeps its code and params; any
    other (engine / rules) refusal passes its own text through under the code ``action_rejected``."""
    if isinstance(exc, LocalizedError):
        return api_error(status, exc.code, headers=headers, **exc.params)
    return HTTPException(
        status, {"code": "action_rejected", "message": str(exc)}, headers=dict(headers) if headers else None
    )


def localize_detail(detail: Any, lang: Optional[str]) -> Any:
    """Add the localized ``message`` to a ``{"code": ...}`` detail that has none.

    A detail that already carries a message (engine passthrough, or a body that composes its own) is
    left alone; a plain string or list (framework validation) is returned unchanged."""
    if not isinstance(detail, dict) or "code" not in detail:
        return detail
    # Coded deck-validation texts nested in the body ("errors", "validation") follow the language too.
    detail = {
        **detail,
        **({"errors": localize_texts(detail["errors"], lang)} if "errors" in detail else {}),
        **({"validation": localize_validation(detail["validation"], lang)} if "validation" in detail else {}),
    }
    code = detail["code"]
    if "message" in detail or not isinstance(code, str) or not has_message(code):
        return detail
    params = {key: value for key, value in detail.items() if key != "code"}
    return {**detail, "message": message(code, lang, **params)}
