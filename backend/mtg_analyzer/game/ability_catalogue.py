"""Card → `AbilitySpec` catalogue: the bind-on-load source of card behaviour.

The engine turns a card's abilities into behaviour by binding `AbilitySpec`s
(the IR, `parser/oracle/spec.py`) onto its `GameObject`. Until the oracle-text
NLP parser (docs/09) exists, those specs come from the **hand-authored,
name-keyed registry here**. `specs_for(card)` is the single entry point the
binder (`effect_binder.bind_from_catalogue`) consults when a game is built.

This is deliberately the seam the future parser plugs into: when it lands,
`specs_for` can fall back to it for any card not in the registry, and nothing
else in the engine has to change. Register a card with `register(name, factory)`
where ``factory`` returns fresh specs each call (specs are mutated when bound —
their effects get a source — so each object must get its own copies).

`enters_tapped(card)` is a separate, *oracle-derived* rule (RULE 614.1): it
reads the printed text, so every plain tap-land works without being registered.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..parser.oracle.catalogue.keywords import parse_keywords
from ..parser.oracle.spec import AbilitySpec, EffectSpec

#: name (lowercased) → factory producing that card's specs, fresh each call.
_REGISTRY: dict[str, Callable[[], list[AbilitySpec]]] = {}


def register(name: str, factory: Callable[[], list[AbilitySpec]]) -> None:
    """Register a card's ability specs under its (case-insensitive) name."""
    _REGISTRY[name.strip().lower()] = factory


def is_registered(name: str) -> bool:
    return name.strip().lower() in _REGISTRY


def specs_for(card: Any) -> list[AbilitySpec]:
    """The `AbilitySpec`s a card contributes, or ``[]`` if none are known.

    Two sources, unioned: the hand-authored registry (by card name) and the
    RULE 702 **keyword catalogue** parsed off the card's own text/keywords.
    Flag keywords from the latter dock onto combat via the binder; any keyword
    the registry already authored wins, so it isn't duplicated. (Future: fall
    back to the full oracle parser for unregistered effect clauses too.)
    """
    name = (getattr(card, "name", "") or "").strip().lower()
    factory = _REGISTRY.get(name)
    specs: list[AbilitySpec] = list(factory()) if factory is not None else []

    authored = {
        s.keyword.get("name")
        for s in specs
        if s.ability_kind == "keyword" and s.keyword
    }
    for kw_spec in parse_keywords(card):
        if kw_spec.keyword and kw_spec.keyword.get("name") in authored:
            continue
        specs.append(kw_spec)
    return specs


#: A land that enters tapped (RULE 614.1) — a plain tap-land whose text says so.
_ENTERS_TAPPED_RE = re.compile(r"enters (?:the battlefield )?tapped", re.IGNORECASE)
#: …but not one whose tapped-entry is *conditional* (shock/check/pay-life
#: lands), since that choice isn't modeled yet — those stay untapped for now.
_CONDITIONAL_TAP_RE = re.compile(
    r"unless|you may pay|if you don't|reveal", re.IGNORECASE
)


def enters_tapped(card: Any) -> bool:
    """Whether ``card`` enters the battlefield tapped (RULE 614.1).

    Read straight off the oracle text, so any plain tap-land works. Conditional
    tap-lands (shock lands' "you may pay 2 life", check lands' "unless you
    control …") are treated as entering untapped — the payment/condition choice
    is a known gap, so we don't force them tapped.
    """
    text = getattr(card, "oracle_text", "") or ""
    if not _ENTERS_TAPPED_RE.search(text):
        return False
    return not _CONDITIONAL_TAP_RE.search(text)


# ---------------------------------------------------------------------------
# Seed catalogue — a representative starter set proving the pipeline. Extend
# freely; each entry is one card's abilities as pure specs.
# ---------------------------------------------------------------------------


def _fetch_basic_to_battlefield_tapped() -> list[AbilitySpec]:
    """"{T}, Sacrifice ~: Search your library for a basic land, put it onto the
    battlefield tapped, then shuffle." — Evolving Wilds / Terramorphic Expanse."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"basic": True},
                        "destination": "battlefield_tapped",
                        "count": 1,
                        "optional": True,
                    },
                )
            ],
            cost={"text": "{T}, Sacrifice ~"},
            raw_text="{T}, Opfere ~: Suche eine Standardland-Karte, lege sie getappt ins Spiel, mische dann.",
        )
    ]


register("Evolving Wilds", _fetch_basic_to_battlefield_tapped)
register("Terramorphic Expanse", _fetch_basic_to_battlefield_tapped)
