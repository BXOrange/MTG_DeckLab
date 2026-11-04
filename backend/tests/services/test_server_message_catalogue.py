"""VIS-24: the server message catalogue is complete in both languages and covers every code in use."""

from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from mtg_analyzer.i18n import (
    LocalizedError,
    has_message,
    lang_from_connection,
    localize_detail,
    message,
    resolve_lang,
)
from mtg_analyzer.i18n.catalogue import CATALOGUE, DEFAULT_LANG, SUPPORTED_LANGS

PACKAGE = Path(__file__).resolve().parents[2] / "mtg_analyzer"
#: Source files whose string codes must exist in the catalogue.
CODE_SOURCES = [*sorted((PACKAGE / "api").glob("*.py")), *sorted((PACKAGE / "services").glob("*.py"))]
#: Quoted snake_case token that is a message code at a raising site.
_CODE_SITES = [
    re.compile(r"""\bapi_error\(\s*[^,]+,\s*(?:"|')([a-z_]+)(?:"|')"""),
    re.compile(r"""\b(?:LobbyError|AssetQuotaError|ArchidektFetchError|LocalizedError)\(\s*(?:"|')([a-z_]+)(?:"|')"""),
    re.compile(r"""\bdeny\(\s*[^,]+,\s*(?:"|')([a-z_]+)(?:"|')"""),
    re.compile(r"""HTTPException\([^{]*\{\s*"code":\s*"([a-z_]+)\""""),
]


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_code_exists_in_every_language():
    reference = set(CATALOGUE[DEFAULT_LANG])
    for lang in SUPPORTED_LANGS:
        assert set(CATALOGUE[lang]) == reference, f"{lang} drifts from {DEFAULT_LANG}"


def test_placeholders_match_across_languages_and_nothing_is_empty():
    for code, german in CATALOGUE["de"].items():
        english = CATALOGUE["en"][code]
        assert german.strip() and english.strip(), code
        assert _placeholders(german) == _placeholders(english), code


def test_every_code_raised_in_the_server_is_in_the_catalogue():
    seen: set[str] = set()
    for path in CODE_SOURCES:
        text = path.read_text(encoding="utf-8")
        for pattern in _CODE_SITES:
            seen.update(pattern.findall(text))
    assert len(seen) > 40  # the scan itself found the sites
    assert {code for code in seen if not has_message(code)} == set()


def test_queue_refusal_and_dynamic_codes_come_from_the_runner_constants():
    from mtg_analyzer.services.job_runner import REFUSAL_OWNER_LIMIT, REFUSAL_QUEUE_FULL

    assert has_message(REFUSAL_OWNER_LIMIT) and has_message(REFUSAL_QUEUE_FULL)


def test_password_and_name_codes_the_routes_build_dynamically_are_covered():
    for code in ("password_too_short", "password_too_long", "password_blocklisted", "password_reused_initial", "invalid_name"):
        assert has_message(code)


@pytest.mark.parametrize(
    ("cookie", "accept", "expected"),
    [
        ("en", "de", "en"),
        ("de", "en", "de"),
        (None, None, "de"),
        (None, "", "de"),
        (None, "en", "en"),
        (None, "en-US,en;q=0.9,de;q=0.8", "en"),
        (None, "de-DE,de;q=0.9,en;q=0.8", "de"),
        (None, "fr, en;q=0.5", "en"),
        (None, "en;q=0.4, de;q=0.9", "de"),
        (None, "en;q=0, de;q=0", "de"),
        (None, "*", "de"),
        (None, "xx;q=abc, en", "en"),
        ("klingon", "en", "en"),
        ("klingon", "fr", "de"),
    ],
)
def test_language_selection(cookie, accept, expected):
    assert resolve_lang(cookie, accept) == expected


def test_lang_from_connection_reads_cookie_then_header():
    class Connection:
        def __init__(self, cookies, headers):
            self.cookies, self.headers = cookies, headers

    assert lang_from_connection(Connection({"mtg_lang": "en"}, {"accept-language": "de"})) == "en"
    assert lang_from_connection(Connection({}, {"accept-language": "en;q=0.9"})) == "en"
    assert lang_from_connection(Connection({}, {})) == "de"
    assert lang_from_connection(object()) == DEFAULT_LANG  # no cookies/headers: default, never a crash


def test_message_never_raises_and_falls_back():
    assert message("deck_not_found", "en", deck_id="d") == 'No saved deck with id "d".'
    assert message("deck_not_found", "de", deck_id="d").startswith("Kein gespeichertes Deck")
    assert message("deck_not_found", "fr", deck_id="d").startswith("Kein gespeichertes Deck")  # unknown language
    assert message("deck_not_found", "en") == 'No saved deck with id "".'  # missing parameter renders empty
    assert message("no_such_code", "en") == "no_such_code"  # last resort: the code itself


def test_localize_detail_keeps_unknown_codes_and_existing_messages():
    assert localize_detail({"code": "mystery"}, "en") == {"code": "mystery"}
    assert localize_detail({"code": "csrf", "message": "mine"}, "en") == {"code": "csrf", "message": "mine"}
    assert localize_detail("plain", "en") == "plain"
    assert localize_detail([{"loc": []}], "en") == [{"loc": []}]


def test_localized_error_str_is_english_and_renders_per_language():
    error = LocalizedError("lobby_unknown_game", game_id="g1")
    assert str(error) == 'Unknown game "g1".'
    assert error.render("de") == 'Unbekanntes Spiel "g1".'
    assert error.code == "lobby_unknown_game" and error.params == {"game_id": "g1"}
