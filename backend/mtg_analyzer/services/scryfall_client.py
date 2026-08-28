"""Scryfall API client: fetch card data and convert it into `Card` objects.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/implementation-state/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "ScryfallIntegration").
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import httpx2 as httpx

from mtg_analyzer.config import SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS, USER_AGENT
from mtg_analyzer.models.card import VALID_COLORS, Card
from mtg_analyzer.parser.oracle.normalize import strip_reminder_text

_BASE_URL = "https://api.scryfall.com"
#: Scryfall asks integrations to identify themselves and to stay under
#: ~10 requests/second; a small delay between requests is the simplest
#: way to honor that without a background rate limiter. Overridable via
#: MTG_USER_AGENT / MTG_SCRYFALL_MIN_REQUEST_INTERVAL — see
#: mtg_analyzer/config.py.
_USER_AGENT = USER_AGENT
_MIN_REQUEST_INTERVAL_SECONDS = SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS
#: Batch size cap for POST /cards/collection (Scryfall's own limit).
_COLLECTION_BATCH_SIZE = 75

_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


class ScryfallNotFoundError(Exception):
    """Raised when Scryfall has no card matching the given name."""


class ScryfallIntegration:
    """Thin wrapper around the Scryfall HTTP API used for lazy card loading."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(
            base_url=_BASE_URL,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=10.0,
        )
        self._last_request_at: Optional[float] = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ScryfallIntegration":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_card(self, name: str) -> dict[str, Any]:
        """Fetch a single card by exact name. Raises ScryfallNotFoundError if unknown."""
        response = self._request("GET", "/cards/named", params={"exact": name})
        if response.status_code == 404:
            raise ScryfallNotFoundError(f'No Scryfall card found for "{name}"')
        response.raise_for_status()
        return response.json()

    def fetch_multiple(self, names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Fetch several cards by name in as few requests as possible.

        Returns (found_card_data, names_not_found). Uses Scryfall's bulk
        `/cards/collection` endpoint (up to 75 identifiers per request)
        rather than one request per card.
        """
        found: list[dict[str, Any]] = []
        not_found: list[str] = []

        for start in range(0, len(names), _COLLECTION_BATCH_SIZE):
            batch = names[start : start + _COLLECTION_BATCH_SIZE]
            identifiers = [{"name": name} for name in batch]
            response = self._request(
                "POST", "/cards/collection", json={"identifiers": identifiers}
            )
            response.raise_for_status()
            body = response.json()
            found.extend(body.get("data", []))
            not_found.extend(entry.get("name", "") for entry in body.get("not_found", []))

        return found, not_found

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._throttle()
        return self._client.request(method, path, **kwargs)

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = _MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


#: Scryfall layouts that print two *separate* face images the player can
#: flip between — a transform card (Delver), a modal DFC (Valki //
#: Tibalt), a double-faced token, and Scryfall's own reversible reprints.
#: Everything else with a `card_faces` array ("flip", "split", "adventure",
#: "meld") shows a single shared image, so no back image is captured for
#: those. See Card.has_back_face.
_TWO_IMAGE_LAYOUTS = frozenset(
    {"transform", "modal_dfc", "double_faced_token", "reversible_card"}
)

#: Layouts whose `card_faces[1]` is a real, independently nameable/castable
#: second face worth capturing into `back_*`, even when (unlike
#: `_TWO_IMAGE_LAYOUTS`) it shares the front's single printed image — a
#: split card's other half (RULE 709), an Adventure's instant/sorcery half
#: (RULE 715), or a preparation card's inset "prepare spell" (RULE 722).
#: `back_image_uri_*` stays empty for these since their face entries carry
#: no `image_uris` of their own, so `Card.has_back_face` is unaffected.
_SECOND_FACE_LAYOUTS = _TWO_IMAGE_LAYOUTS | {"split", "adventure", "prepare"}


def card_from_scryfall_data(data: dict[str, Any]) -> Card:
    """Convert a Scryfall card object into a `Card` domain model.

    Double-faced cards keep face-specific fields (oracle text, image
    URIs, power/toughness, type line) under `card_faces` rather than at
    the top level. The `Card` model is front-face-first: its primary
    fields describe the front, and derived type flags (`is_creature`,
    `is_land`, …) come from the *front* face's type line — not the
    combined "Front // Back" line, which would e.g. flag an
    "Instant // Land" modal DFC as a land. The back face is preserved in
    the `back_*` fields for layouts that print a separate back image
    (see `_TWO_IMAGE_LAYOUTS`); how it is reached — cast from hand vs.
    transformed in play — is distinguished by `layout` (Card.is_modal_dfc
    / Card.is_transforming).
    """
    layout = data.get("layout", "")
    faces = data.get("card_faces") or []
    front = data
    if faces and ("oracle_text" not in data or not data.get("image_uris")):
        front = {**faces[0], **{k: v for k, v in data.items() if k not in faces[0]}}

    # Type flags describe the front face. `front["type_line"]` is the
    # front-only line for a true DFC (merged from card_faces[0] above) and
    # the top-level line otherwise — which for split/adventure/flip is
    # already the single printed line we want.
    type_line = front.get("type_line") or data.get("type_line", "")

    image_uris = front.get("image_uris") or data.get("image_uris") or {}

    power = _parse_int(front.get("power"))
    toughness = _parse_int(front.get("toughness"))
    is_creature = "Creature" in type_line
    # RULE 208.1/MEC-29: a Vehicle (or any other noncreature permanent
    # Scryfall still prints P/T on) keeps its printed power/toughness in
    # `vehicle_power`/`vehicle_toughness` rather than discarding it the way
    # `power`/`toughness` do below — Crew (RULE 702.122a) needs it the
    # instant such a permanent actually becomes a creature. Scoped to the
    # subtype rather than "any noncreature with printed P/T" so a stray
    # future Scryfall data quirk can't leak a P/T pair onto an unrelated
    # card type this was never meant to cover.
    #
    # RULE 702.184/721 Station (Edge of Eternities) reprints exactly this
    # same shape for a Spacecraft artifact: no "Creature" in its own type
    # line, but a real top-level Scryfall `power`/`toughness` pair for the
    # P/T it gets once its own "N+ |" bracket makes it "an artifact
    # creature at N+" — confirmed against the cached data (Entropic
    # Battlecruiser prints `"power": "3", "toughness": "10"` despite
    # `type_line: "Artifact — Spacecraft"`). A Station *land* (subtype
    # Planet) never carries a printed P/T at all (it never becomes a
    # creature), so widening this check costs nothing there — same latent-
    # bug shape MEC-29 fixed for Vehicle/Crew, caught before it ever
    # shipped this time.
    is_vehicle_or_spacecraft = not is_creature and (
        "Vehicle" in type_line or "Spacecraft" in type_line
    )
    vehicle_power = power if is_vehicle_or_spacecraft else None
    vehicle_toughness = toughness if is_vehicle_or_spacecraft else None

    back = faces[1] if layout in _SECOND_FACE_LAYOUTS and len(faces) >= 2 else {}
    back_image_uris = back.get("image_uris") or {}
    back_type_line = back.get("type_line", "")
    back_is_creature = "Creature" in back_type_line

    return Card(
        id=data["id"],
        name=data["name"],
        type_line=type_line,
        mana_cost=_parse_mana_cost(front.get("mana_cost", "")),
        mana_cost_string=front.get("mana_cost", "") or "",
        converted_mana_cost=int(data.get("cmc") or 0),
        color_identity=set(data.get("color_identity") or []),
        is_creature=is_creature,
        is_instant="Instant" in type_line,
        is_sorcery="Sorcery" in type_line,
        is_land="Land" in type_line,
        power=power if is_creature else None,
        toughness=toughness if is_creature else None,
        vehicle_power=vehicle_power,
        vehicle_toughness=vehicle_toughness,
        loyalty=_parse_int(front.get("loyalty")),
        # RULE 310.4a: a battle's printed defense. Face-specific like
        # loyalty/power — every real battle is a transforming DFC whose
        # front face carries it, so it rides the same merged `front`.
        defense=_parse_int(front.get("defense")),
        oracle_text=front.get("oracle_text", ""),
        keywords=list(data.get("keywords") or []),
        image_uri_small=image_uris.get("small", ""),
        image_uri_normal=image_uris.get("normal", ""),
        image_uri_large=image_uris.get("large", ""),
        image_uri_png=image_uris.get("png", ""),
        set_code=data.get("set", ""),
        rarity=data.get("rarity", ""),
        # Some promo printings (Secret Lair "Godzilla" series, Universes
        # Beyond crossovers) carry an alternate printed name here instead of
        # on the (always-Oracle) top-level `name` — see Card.flavor_name.
        # Rare double-faced cards put it per-face rather than top-level.
        flavor_name=data.get("flavor_name") or front.get("flavor_name") or "",
        is_legendary="Legendary" in type_line,
        has_partner=_has_partner(front.get("oracle_text", "")),
        partner_with=_partner_with(front.get("oracle_text", "")),
        layout=layout,
        # RULE 709.4: Fuse is a top-level keyword on a split card, not
        # per-face oracle text.
        has_fuse="Fuse" in (data.get("keywords") or []),
        back_name=back.get("name", ""),
        back_type_line=back_type_line,
        back_oracle_text=back.get("oracle_text", ""),
        back_mana_cost_string=back.get("mana_cost", "") or "",
        back_power=_parse_int(back.get("power")) if back_is_creature else None,
        back_toughness=_parse_int(back.get("toughness")) if back_is_creature else None,
        back_image_uri_small=back_image_uris.get("small", ""),
        back_image_uri_normal=back_image_uris.get("normal", ""),
        back_image_uri_large=back_image_uris.get("large", ""),
        back_image_uri_png=back_image_uris.get("png", ""),
    )


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        # "*" and "X" show up as power/toughness on some cards.
        return None


def _parse_mana_cost(mana_cost: str) -> dict[str, int]:
    """Tally colored/colorless mana symbols, ignoring generic numeric pips.

    The `Card` model only tracks a per-symbol pip count (no generic
    amount field), so "{2}{R}" becomes {"R": 1} with the "2" dropped;
    `converted_mana_cost` remains the source of truth for total cost.

    Hybrid ("{W/U}") and Phyrexian ("{W/P}") symbols are also
    flattened: each is split on "/" and only the half matching a known
    color/colorless letter is kept, so "{W/U}" and "{W/P}" both count
    as a single "W" pip, indistinguishable from a plain "{W}". That
    loses real information (a hybrid symbol can be paid in either
    color; a Phyrexian one can be paid with 2 life instead) — see
    docs/implementation-state/Done_Backend.md "Mana cost model" for the backlog on representing
    these properly.
    """
    counts = {color: 0 for color in sorted(VALID_COLORS) + ["C"]}
    for symbol in _MANA_SYMBOL_RE.findall(mana_cost):
        for letter in symbol.split("/"):
            if letter in counts:
                counts[letter] += 1
    return counts


def _has_partner(oracle_text: str) -> bool:
    return bool(re.search(r"^Partner\b", oracle_text, re.MULTILINE))


def _partner_with(oracle_text: str) -> Optional[str]:
    """The exact name after "Partner with " on a "Partner with X" card, or
    None. Scryfall prints this line with its RULE 207.2 reminder text
    inline ("Partner with Sam, Loyal Attendant (When this creature
    enters, ...)"), so the raw regex capture must have that reminder text
    stripped before use — otherwise it never exactly matches the named
    card's `Card.name`, breaking the pairing check in
    services/commander_legality.py for every "Partner with X" card.
    """
    match = re.search(r"^Partner with (.+)$", oracle_text, re.MULTILINE)
    if match is None:
        return None
    return strip_reminder_text(match.group(1)).strip()
