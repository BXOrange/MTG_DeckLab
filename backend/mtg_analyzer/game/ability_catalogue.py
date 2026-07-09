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

from ..models.events import EventType
from ..parser.oracle.catalogue.keywords import parse_keywords
from ..parser.oracle.gate import parse_oracle
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

    Three sources, in precedence order:

    1. the hand-authored registry (by card name) — trusted wholesale when a
       card is registered;
    2. the RULE 702 **keyword catalogue** parsed off the card's own
       text/keywords (always folded in, since each keyword is safe on its own);
    3. the **oracle-effect parser** (docs/09) for the effect/triggered clauses
       of an *unregistered* card — but only when the parser marks the whole
       card `MODELED` (fail-closed: a half-parsed card contributes no effects).

    Any keyword the registry already authored wins, so it isn't duplicated.
    """
    name = (getattr(card, "name", "") or "").strip().lower()
    factory = _REGISTRY.get(name)
    registered = factory is not None
    specs: list[AbilitySpec] = list(factory()) if registered else []

    authored = {
        s.keyword.get("name")
        for s in specs
        if s.ability_kind == "keyword" and s.keyword
    }
    for kw_spec in parse_keywords(card):
        if kw_spec.keyword and kw_spec.keyword.get("name") in authored:
            continue
        specs.append(kw_spec)

    # For an unregistered card, add parser-derived effect abilities — but only
    # from a fully MODELED card, so we never resolve half of what a card says.
    if not registered:
        result = parse_oracle(card)
        if result.modeled:
            specs.extend(result.effect_specs)
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


def _armadillo_cloak() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +2/+2 and has trample and lifelink.

    — Armadillo Cloak (kept as two lines, matching Scryfall's own line break
    between the "Enchant creature" clause and the static buff — see docs/11
    §3 on quoting oracle text). The "Enchant creature" keyword itself (and
    the ETB attach-to-target it drives, RULE 303.4f) comes from the RULE 702
    keyword catalogue reading the card's own oracle text/keywords — only the
    static buff needs hand-authoring here, scoped to whatever the Aura is
    attached to (docs/11 §6 "attached_permanent")."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent",
                                              "keywords": ["trample", "lifelink"]}),
            ],
            raw_text="Verzauberte Kreatur erhält +2/+2 und hat Trampelschaden und Lebensverknüpfung.",
        )
    ]


register("Armadillo Cloak", _armadillo_cloak)


def _clever_impersonator() -> list[AbilitySpec]:
    """You may have this creature enter the battlefield as a copy of any
    nonland permanent on the battlefield, except it's an artifact in
    addition to its other types.

    — Clever Impersonator (RULE 706/707 "become a copy", `become_copy`
    effect / `RulesEngine.become_copy`). Modeled as an ordinary
    ENTERS_BATTLEFIELD trigger rather than the true "as ~ enters"
    replacement timing (RULE 614.1c/614.12 aren't wired yet — see
    ToDo_Backend.md, the same simplification as the conditional-tapland
    gap) and as unconditional rather than a real "you may" choice
    (`AbilitySpec.optional`/`TriggeredAbility.optional` are carried but not
    yet consulted for a player decision). ``target_kind="permanent"`` is
    broader than "any nonland permanent" — the target-kind vocabulary
    (docs/11 §10) has no land-exclusion; picking a land here is simply never
    correct oracle-text-wise but not currently prevented.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_copy", {"target_kind": "permanent"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
            optional=True,
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Nichtland-"
                      "bleibenden Karte ins Spiel kommen lassen.",
        )
    ]


register("Clever Impersonator", _clever_impersonator)


def _phantasmal_image() -> list[AbilitySpec]:
    """You may have this creature enter the battlefield as a copy of any
    creature on the battlefield, except it's an Illusion in addition to its
    other types.

    — Phantasmal Image. Same `become_copy` mechanism as `Clever Impersonator`
    (see its docstring for the modeling caveats); ``add_subtypes`` carries
    the "except it's an Illusion" clause (`Card.as_copy`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_copy", {"target_kind": "creature", "add_subtypes": ["Illusion"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
            optional=True,
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Kreatur ins "
                      "Spiel kommen lassen, außer dass sie zusätzlich zu ihren anderen "
                      "Typen eine Illusion ist.",
        )
    ]


register("Phantasmal Image", _phantasmal_image)


def _copy_artifact() -> list[AbilitySpec]:
    """You may have this enchantment enter the battlefield as a copy of any
    artifact on the battlefield, except it's an enchantment in addition to
    its other types.

    — Copy Artifact. Same `become_copy` mechanism; ``add_types`` carries the
    "except it's an enchantment" clause.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_copy", {"target_kind": "permanent", "add_types": ["Enchantment"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
            optional=True,
            raw_text="Du kannst dieses Verzauberung als Kopie eines beliebigen Artefakts "
                      "ins Spiel kommen lassen, außer dass sie zusätzlich zu ihren anderen "
                      "Typen eine Verzauberung ist.",
        )
    ]


register("Copy Artifact", _copy_artifact)
