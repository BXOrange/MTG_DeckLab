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
rule (RULE 614.1): they read the printed text (delegating the actual clause
recognition to `parser.oracle.catalogue.lands`, the coverage gate's own
source of truth for these shapes), so every plain tap-land — and the shock/
check/fast/slow/Battlebond-land conditional shapes `GameEngine.play_land`
resolves via `RulesEngine.enter_land_tapped` — works without being registered.
`entry_counters(card)` is the same split for a RULE 614.1-style "enters with
N counters" clause (`parser.oracle.catalogue.counters`), resolved by
`RulesEngine`'s battlefield-entry paths.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..models.events import EventType
from ..parser.oracle.catalogue.counters import entry_counters as _entry_counters
from ..parser.oracle.catalogue.keywords import parse_keywords
from ..parser.oracle.catalogue.lands import land_tap_condition as _land_tap_condition
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
    - ``{"kind": "unless_count", "cmp": "le" | "ge", "count": N, "basic": bool}``
      — a fast land (``"le"``) or slow land (``"ge"``): untapped iff the
      count of *other* lands (or, when ``basic`` is set, *basic* lands) the
      controller controls compares as stated.
    - ``{"kind": "unless_opponents", "count": N}`` — a Commander
      "Battlebond" land: untapped iff the game has at least ``N`` opponents.
    - ``{"kind": "unless_opponents_count", "cmp": "le" | "ge", "count": N}``
      — the "Turbulent" land cycle: untapped iff the *total* count of lands
      across all opponents compares as stated.

    The conditional shapes are deterministic on game/board state at entry —
    no player decision, unlike the shock land's payment. Delegates to the
    oracle-text front-end's `parser.oracle.catalogue.lands.land_tap_condition`
    (the coverage gate's single source of truth for these clause shapes, so
    the engine can never resolve a shape the gate doesn't also claim, or
    vice versa) — see that module for the full clause-recognition logic.
    """
    return _land_tap_condition(card)


def enters_tapped(card: Any) -> bool:
    """Whether ``card`` unconditionally enters the battlefield tapped
    (RULE 614.1) — a plain tap-land. Conditional tap-lands (shock/check/
    fast/slow lands, see `land_tap_condition`) are *not* "always" and so
    read as ``False`` here; `GameEngine.play_land` resolves those properly."""
    return land_tap_condition(card)["kind"] == "always"


def entry_counters(card: Any) -> Optional[dict[str, Any]]:
    """``card``'s RULE 614.1-style "enters with N counters" clause, or
    ``None`` if it has none. One of:

    - ``{"is_x": True, "counter_type": "+1/+1"}`` — the amount is the
      object's actual paid X (RULE 107.3c: 0 outside a cast-for-X).
    - ``{"is_x": False, "count": N, "counter_type": "ice"}`` — a fixed
      amount.

    Delegates to `parser.oracle.catalogue.counters.entry_counters` (the
    coverage gate's single source of truth for this clause shape), the same
    split `land_tap_condition` uses for tapped-entry.
    """
    return _entry_counters(card)


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

    — Clever Impersonator (RULE 706/707 "become a copy" / RULE 614.1c/614.12
    "as ~ enters" replacement timing, `enter_as_copy` /
    `RulesEngine._offer_enter_as_copy`). The choice — copy target X, or
    decline — is offered and resolved *before* this object is ever added to
    the battlefield/fires ENTERS_BATTLEFIELD, so (unlike the old ENTERS_
    BATTLEFIELD-trigger modeling this replaces) it's never observably
    "itself" first. ``target_kind="permanent"`` is broader than "any
    nonland permanent" — the target-kind vocabulary (docs/11 §10) has no
    land-exclusion; picking a land here is simply never correct oracle-
    text-wise but not currently prevented.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Nichtland-"
                      "bleibenden Karte ins Spiel kommen lassen.",
        )
    ]


register("Clever Impersonator", _clever_impersonator)


def _phantasmal_image() -> list[AbilitySpec]:
    """You may have this creature enter the battlefield as a copy of any
    creature on the battlefield, except it's an Illusion in addition to its
    other types.

    — Phantasmal Image. Same `enter_as_copy` mechanism as `Clever
    Impersonator` (see its docstring); ``add_subtypes`` carries the "except
    it's an Illusion" clause (`Card.as_copy`).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "creature", "add_subtypes": ["Illusion"]})],
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

    — Copy Artifact. Same `enter_as_copy` mechanism; ``add_types`` carries
    the "except it's an enchantment" clause.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent", "add_types": ["Enchantment"]})],
            raw_text="Du kannst dieses Verzauberung als Kopie eines beliebigen Artefakts "
                      "ins Spiel kommen lassen, außer dass sie zusätzlich zu ihren anderen "
                      "Typen eine Verzauberung ist.",
        )
    ]


register("Copy Artifact", _copy_artifact)


def _vesuvan_shapeshifter() -> list[AbilitySpec]:
    """You may have this creature enter the battlefield as a copy of any
    creature on the battlefield, except it's a Shapeshifter in addition to
    its other types.
    As long as ~ is untapped, you may have it be a copy of another target
    creature, except it's a Shapeshifter in addition to its other types.

    — Vesuvan Shapeshifter: the driving real-card example for the layer-1
    *conditional/continuous* copy mechanism (`game/continuous.py`'s
    `_apply_copy_layer`), unlike the three ETB-only cards above (Clever
    Impersonator/Phantasmal Image/Copy Artifact), which copy once and never
    revert. Three specs: the same RULE 614.1c/614.12 `enter_as_copy`
    replacement those use for its own ETB half; a `static` `conditional_copy`
    spec driving the continuous layer-1 pass (reverts the instant it's
    tapped, per the real card's "as long as untapped" wording); and an
    `activated` spec exposing "choose a new target" — RULE 707.9's "special
    action" isn't modeled as its own timing category, so this is simplified
    to a costless, sorcery-speed-only activated ability instead (same
    simplification tier as other documented ones in this file). Per the real
    Vesuvan Shapeshifter ruling, copying a creature with no similar ability
    *locks in* — the copied creature's own abilities replace this one's
    `conditional_copy`/`set_copy_target` entirely (RULE 706.2), so there's
    nothing left to revert or re-target with until something else grants an
    equivalent ability.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "creature", "add_subtypes": ["Shapeshifter"]})],
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Kreatur ins "
                      "Spiel kommen lassen, außer dass sie zusätzlich zu ihren anderen "
                      "Typen ein Gestaltwandler ist.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("conditional_copy", {"requires_untapped": True, "add_subtypes": ["Shapeshifter"]})],
            raw_text="Solange ~ ungetappt ist, kannst du es zu einer Kopie einer anderen "
                      "Kreatur deiner Wahl machen, außer dass es zusätzlich zu seinen "
                      "anderen Typen ein Gestaltwandler ist.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("set_copy_target", {"target_kind": "creature"})],
            cost={"sorcery_speed_only": True},
            raw_text="(Wähle eine andere Zielkreatur für die vorstehende Fähigkeit.)",
        ),
    ]


register("Vesuvan Shapeshifter", _vesuvan_shapeshifter)


def _cursed_mirror() -> list[AbilitySpec]:
    """{T}: ~ becomes a copy of target creature until end of turn.

    — Cursed Mirror: the driving real-card example for the temporary
    "becomes a copy … until end of turn" mechanism (`RulesEngine.
    become_copy_until_end_of_turn`), reverted by `GameEngine._step_cleanup`
    (RULE 514.2) — a third, distinct copy mechanism alongside the permanent
    ETB copy (Clever Impersonator) and the conditional continuous copy
    (Vesuvan Shapeshifter above), all sharing `game/copy_mechanics.py`'s
    mutate/snapshot/restore primitives.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "creature"})],
            cost={"taps_self": True},
            raw_text="{T}: ~ wird bis zum Ende des Zuges zu einer Kopie einer Zielkreatur.",
        )
    ]


register("Cursed Mirror", _cursed_mirror)


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


def _doubling_season() -> list[AbilitySpec]:
    """If an effect would create one or more tokens under your control, it
    creates twice that many of those tokens instead. If an effect would put
    one or more counters on a permanent or player, it puts twice that many
    of those counters on that permanent or player instead.

    — Doubling Season. Two independent RULE 616.1 replacement effects
    (`double_tokens`/`double_counters`) sharing one permanent — a real card
    with *two* simultaneously-registered replacement clauses, exercising
    `build_replacements`'s one-`ReplacementEffect`-per-`EffectSpec` path.
    The counter clause is deliberately unscoped (any permanent/player, not
    just ones its controller controls — the real card's own well-known
    "doubles an opponent's poison counters too" behaviour); the token
    clause is controller-scoped, matching the printed "under your control".
    Together with Parallel Lives (`_parallel_lives`) this is the textbook
    RULE 616.1e "which order?" prompt — the final token count is the same
    either way (doubling commutes), but the choice is still required.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_tokens", {}), EffectSpec("double_counters", {})],
            raw_text="Falls ein Effekt einen oder mehrere Marker-Spielsteine unter "
                     "deiner Kontrolle erzeugen würde, erzeugt er stattdessen doppelt "
                     "so viele. Falls ein Effekt einen oder mehrere Marker auf eine "
                     "bleibende Karte oder einen Spieler legen würde, legt er "
                     "stattdessen doppelt so viele.",
        )
    ]


register("Doubling Season", _doubling_season)


def _parallel_lives() -> list[AbilitySpec]:
    """If an effect would create one or more tokens under your control, it
    creates twice that many of those tokens instead.

    — Parallel Lives. The same `double_tokens` replacement as Doubling
    Season's token clause (see its docstring above for the RULE 616.1e
    "two doubling effects, which order?" example this pairing exists for).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_tokens", {})],
            raw_text="Falls ein Effekt einen oder mehrere Marker-Spielsteine unter "
                     "deiner Kontrolle erzeugen würde, erzeugt er stattdessen doppelt "
                     "so viele.",
        )
    ]


register("Parallel Lives", _parallel_lives)


def _furnace_of_rath() -> list[AbilitySpec]:
    """If a source would deal damage to a permanent or player, it deals
    double that damage to that permanent or player instead.

    — Furnace of Rath. Unscoped `double_damage` (every source, not just its
    controller's) — the classic damage-doubling enchantment, and — paired
    with Torbran, Thane of Red Fell (`_torbran_thane_of_red_fell`) — the
    RULE 616.1 example where the *order* genuinely changes the outcome:
    double-then-add-2 vs. add-2-then-double differ, unlike the
    order-invariant token-doubling pair above.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {})],
            raw_text="Falls eine Quelle einer bleibenden Karte oder einem Spieler "
                     "Schaden zufügen würde, fügt sie stattdessen doppelt so viel "
                     "Schaden zu.",
        )
    ]


register("Furnace of Rath", _furnace_of_rath)


def _gratuitous_violence() -> list[AbilitySpec]:
    """If a source you control would deal combat damage to a permanent or
    player, it deals double that damage to that permanent or player
    instead.

    — Gratuitous Violence. `double_damage` scoped to ``combat_only`` +
    ``your_sources_only`` — narrower than Furnace of Rath's unscoped
    version (noncombat burn spells, and an opponent's combat damage, are
    both untouched).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"combat_only": True, "your_sources_only": True})],
            raw_text="Falls eine Quelle, die du kontrollierst, einer bleibenden Karte "
                     "oder einem Spieler Kampfschaden zufügen würde, fügt sie "
                     "stattdessen doppelt so viel Schaden zu.",
        )
    ]


register("Gratuitous Violence", _gratuitous_violence)


def _torbran_thane_of_red_fell() -> list[AbilitySpec]:
    """If a red source you control would deal damage to an opponent or a
    permanent an opponent controls, it deals that much damage plus 2
    instead.

    — Torbran, Thane of Red Fell. `additional_damage` scoped by
    ``your_sources_only``/``color: "R"``/``to_opponent_only`` — an additive
    replacement rather than `double_damage`'s multiplicative one, which is
    exactly why pairing it with Furnace of Rath (`_furnace_of_rath`) makes
    RULE 616.1's ordering choice observably matter: (X+2)×2 ≠ (X×2)+2.
    """
    return [
        AbilitySpec(
            "replacement",
            [
                EffectSpec(
                    "additional_damage",
                    {
                        "amount": 2,
                        "your_sources_only": True,
                        "to_opponent_only": True,
                        "color": "R",
                    },
                )
            ],
            raw_text="Falls eine rote Quelle, die du kontrollierst, einem Gegner oder "
                     "einer bleibenden Karte, die ein Gegner kontrolliert, Schaden "
                     "zufügen würde, fügt sie stattdessen so viel Schaden plus 2 zu.",
        )
    ]


register("Torbran, Thane of Red Fell", _torbran_thane_of_red_fell)
