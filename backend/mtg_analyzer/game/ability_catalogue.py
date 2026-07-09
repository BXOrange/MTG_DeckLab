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

`enters_tapped(card)`/`land_tap_condition(card)` are a separate, *oracle-derived*
rule (RULE 614.1): they read the printed text, so every plain tap-land — and
the shock/check/fast/slow-land conditional shapes `GameEngine.play_land`
resolves via `RulesEngine.enter_land_tapped` — works without being registered.
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
#: …but not one whose tapped-entry is *conditional* (shock/check/fast/slow
#: lands) — `land_tap_condition` classifies those precisely; this is only the
#: fallback for a conditional shape it doesn't recognize (fails safe: enters
#: untapped rather than wrongly forcing it down).
_CONDITIONAL_TAP_RE = re.compile(
    r"unless|you may pay|if you don't|reveal", re.IGNORECASE
)
#: Shock lands: "you may pay N life. If you don't, ~ enters the battlefield
#: tapped." (an optional-cost replacement, RULE 614.1 — a genuine choice).
_PAY_LIFE_RE = re.compile(r"you may pay (\d+) life", re.IGNORECASE)
#: Fast/slow lands: "unless you control <count> or fewer/more other lands" —
#: deterministic on the board the controller already has, not a choice.
_UNLESS_COUNT_RE = re.compile(
    r"unless you control (\w+) or (fewer|more) other lands", re.IGNORECASE
)
#: Check lands: "unless you control a/an <Type> [or a/an <Type> …]" —
#: deterministic on the land *types* the controller already has.
_UNLESS_TYPES_RE = re.compile(r"unless you control an? (.+?)\.", re.IGNORECASE)
#: Small number words the count-based clauses spell out.
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


def _split_types_clause(clause: str) -> list[str]:
    """"Mountain or a Forest" → ``["mountain", "forest"]`` (each subsequent
    item repeats its own "a"/"an" per official templating)."""
    types: list[str] = []
    for part in re.split(r"\s+or\s+", clause):
        part = re.sub(r"^an?\s+", "", part.strip(), flags=re.IGNORECASE).strip()
        if part:
            types.append(part.lower())
    return types


def land_tap_condition(card: Any) -> dict[str, Any]:
    """How ``card``'s RULE 614.1 tapped-entry resolves, read off its text.

    One of:

    - ``{"kind": "never"}`` — no tapped-entry clause (a normal land), or an
      unrecognized conditional shape (fails safe: untapped rather than wrong).
    - ``{"kind": "always"}`` — a plain tap-land, unconditionally tapped.
    - ``{"kind": "pay_life", "amount": N}`` — a shock land: the controller may
      pay ``N`` life to keep it untapped, a genuine choice the caller must
      offer interactively.
    - ``{"kind": "unless_types", "types": [...]}`` — a check land: untapped
      iff the controller already controls a land of one of these types.
    - ``{"kind": "unless_count", "cmp": "le" | "ge", "count": N}`` — a
      fast land (``"le"``) or slow land (``"ge"``): untapped iff the count of
      *other* lands the controller controls compares as stated.

    The last three are deterministic on the board state at entry — no player
    decision, unlike the shock land's payment.
    """
    text = getattr(card, "oracle_text", "") or ""
    if not _ENTERS_TAPPED_RE.search(text):
        return {"kind": "never"}
    pay_match = _PAY_LIFE_RE.search(text)
    if pay_match and "if you don't" in text.lower():
        return {"kind": "pay_life", "amount": int(pay_match.group(1))}
    count_match = _UNLESS_COUNT_RE.search(text)
    if count_match:
        count = _NUMBER_WORDS.get(count_match.group(1).lower())
        if count is None:
            try:
                count = int(count_match.group(1))
            except ValueError:
                count = None
        if count is not None:
            cmp_op = "le" if count_match.group(2).lower() == "fewer" else "ge"
            return {"kind": "unless_count", "cmp": cmp_op, "count": count}
    types_match = _UNLESS_TYPES_RE.search(text)
    if types_match:
        types = _split_types_clause(types_match.group(1))
        if types:
            return {"kind": "unless_types", "types": types}
    if _CONDITIONAL_TAP_RE.search(text):
        return {"kind": "never"}
    return {"kind": "always"}


def enters_tapped(card: Any) -> bool:
    """Whether ``card`` unconditionally enters the battlefield tapped
    (RULE 614.1) — a plain tap-land. Conditional tap-lands (shock/check/
    fast/slow lands, see `land_tap_condition`) are *not* "always" and so
    read as ``False`` here; `GameEngine.play_land` resolves those properly."""
    return land_tap_condition(card)["kind"] == "always"


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


def _tyvar_kell() -> list[AbilitySpec]:
    """Elves you control have "{T}: Add {B}."
    [loyalty abilities not modeled — planeswalkers/loyalty costs are, but
    this catalogue entry only demonstrates the static clause]

    — Tyvar Kell. A layer-6 ability-adding grant (RULE 613.7f) of a mana
    ability rather than a keyword — despite CR 612.1's mention of text
    "granted … by other effects", this is *not* layer 3/RULE 612 (see
    `game/continuous.py`'s module docstring); it's the same layer as
    `grant_keyword`, just granting `{"B": 1}` mana production instead of a
    keyword slug. `mana_abilities.mana_options_for` folds it onto whatever
    the Elf already taps for."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_mana_ability",
                    {"affects": "creatures_you_control", "subtype": "Elf", "mana": [{"B": 1}]},
                )
            ],
            raw_text='Elfen, die du kontrollierst, haben "{T}: Erzeuge {B}."',
        )
    ]


register("Tyvar Kell", _tyvar_kell)


def _dionus_elvish_archdruid() -> list[AbilitySpec]:
    """Elves you control have "Whenever this creature becomes tapped during
    your turn, untap it and put a +1/+1 counter on it. This ability
    triggers only once each turn."

    — Dionus, Elvish Archdruid. A layer-6 ability-adding grant (RULE
    613.7f) of a full triggered ability, not just a keyword or a mana
    ability (see `_tyvar_kell` above for the same distinction from layer
    3/RULE 612). Each Elf gets its *own* granted `TriggeredAbility`
    instance, scoped to itself (`continuous._granted_trigger_condition`) and
    cached across recomputes (`GameState._granted_ability_cache`) so its
    "once each turn" state survives — and stops being granted the instant
    the Elf (or Dionus) leaves, with no separate removal code. The nested
    "untap it"/"put a +1/+1 counter on it" effects use the self-acting
    (``target_kind: None``) mode of `tap`/`add_counters` — "it" is always
    the specific Elf the ability was granted to, never a player choice."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_triggered_ability",
                    {
                        "affects": "creatures_you_control",
                        "subtype": "Elf",
                        "trigger_event": EventType.TAPPED,
                        "controllers_turn_only": True,
                        "once_per_turn": True,
                        "grant_effects": [
                            {"type": "tap", "params": {"target_kind": None, "untap": True}},
                            {"type": "add_counters", "params": {"amount": 1}},
                        ],
                    },
                )
            ],
            raw_text='Elfen, die du kontrollierst, haben "Wenn diese Kreatur während '
                     'deines Zuges tappt wird, enttappe sie und lege einen +1/+1-Marker '
                     'auf sie. Diese Fähigkeit wird nur einmal pro Zug ausgelöst."',
        )
    ]


register("Dionus, Elvish Archdruid", _dionus_elvish_archdruid)
