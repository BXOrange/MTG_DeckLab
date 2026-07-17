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


def _oracle_of_mul_daya() -> list[AbilitySpec]:
    """You may play an additional land on each of your turns.
    Play with the top card of your library revealed.
    You may play lands from the top of your library.

    — Oracle of Mul Daya. Only the reveal/play-lands-from-top lines are
    modeled here (`top_library_permission`, `game/top_library.py`); the
    "additional land drop" line is a separate, still-unmodeled player-level
    permission (`backend/ToDo_Backend.md`'s processing-list tail — "you may
    play an additional land on each of your turns") — deliberately left
    off rather than guessed at, not silently dropped by oversight.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True, "play_lands": True})],
            raw_text="Spiele mit der obersten Karte deiner Bibliothek aufgedeckt. Du "
                     "darfst Länder von der Oberseite deiner Bibliothek spielen.",
        )
    ]


register("Oracle of Mul Daya", _oracle_of_mul_daya)


def _glarb_calamitys_augur() -> list[AbilitySpec]:
    """Deathtouch
    You may look at the top card of your library any time.
    You may play lands and cast spells with mana value 4 or greater from
    the top of your library.
    {T}: Surveil 2.

    — Glarb, Calamity's Augur. Deathtouch comes from the RULE 702 keyword
    catalogue (Scryfall's own ``keywords`` array, folded in automatically
    regardless of registration — see `specs_for`), so only the top-library
    permission (`top_library_permission`, mana-value-gated via
    ``min_mana_value``) and the surveil activated ability need
    hand-authoring here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "play_lands": True, "cast_spells": True, "min_mana_value": 4,
            })],
            raw_text="Du darfst dir jederzeit die oberste Karte deiner Bibliothek "
                     "ansehen. Du darfst Länder spielen und Sprüche mit Manawert 4 "
                     "oder größer von der Oberseite deiner Bibliothek wirken.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("surveil", {"count": 2})],
            cost={"text": "{T}"},
            raw_text="{T}: Surveile 2.",
        ),
    ]


register("Glarb, Calamity's Augur", _glarb_calamitys_augur)


# ---------------------------------------------------------------------------
# "Wyleth Equip" — Boros equipment/voltron commander deck. Every entry below
# hand-authors the *whole* card (not just its unclaimed clause): registering
# a name skips the oracle-text parser fallback entirely (`specs_for`'s
# precedence order), so any already-parser-claimable clause (e.g. a plain
# attached-permanent anthem) has to be repeated here too, not just the part
# the parser couldn't reach. Several clauses are deliberately simplified or
# dropped — each says so inline — where the engine has no primitive for the
# real shape yet (X-spells scaling an effect, phasing, per-object dynamic
# "that creature" references, a genuine two-independent-target activated
# ability); see `backend/ToDo_Backend.md` for the running list.
# ---------------------------------------------------------------------------


def _wyleth_soul_of_steel() -> list[AbilitySpec]:
    """Trample
    Whenever Wyleth attacks, draw a card for each Aura and Equipment
    attached to it.

    — Trample comes from the RULE 702 keyword catalogue automatically. The
    draw uses `DrawCardEffect.count_selector` (a per-object dynamic count).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count_selector": "auras_and_equipment_attached_to_self"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Wenn Wyleth angreift, ziehe eine Karte für jede Aura und "
                     "jede Ausrüstung, die an ihm befestigt ist.",
        )
    ]


register("Wyleth, Soul of Steel", _wyleth_soul_of_steel)


def _akiri_fearless_voyager() -> list[AbilitySpec]:
    """Whenever you attack a player with one or more equipped creatures,
    draw a card.
    {W}: You may unattach an Equipment from a creature you control. If you
    do, tap that creature and it gains indestructible until end of turn.

    — Akiri, Fearless Voyager. Simplified: the engine fires RULE 508.1a's
    ATTACKS event once *per attacking creature*, not once per combat, so
    this is authored as "whenever an equipped creature you control attacks
    a player, draw a card" — a per-attacker trigger rather than a true
    once-per-combat one (attacking with 2+ equipped creatures in the same
    combat draws more than the printed one card; see `effect_binder.
    _trigger_condition`'s ``requires_equipped`` for the equipped check).
    The second ability is `UnattachTapIndestructibleEffect`
    (`targeting.py`'s ``attached_equipment_you_control`` only offers an
    Equipment that's actually attached, so there's always a host to act on).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"},
                     "requires_equipped": True},
            raw_text="Wenn eine ausgerüstete Kreatur, die du kontrollierst, einen "
                     "Spieler angreift, ziehe eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("unattach_tap_indestructible", {})],
            cost={"mana": "{W}"},
            raw_text="{W}: Du kannst eine Ausrüstung von einer Kreatur, die du "
                     "kontrollierst, lösen. Wenn du dies tust, tappe die Kreatur "
                     "und sie erhält Unzerstörbarkeit bis zum Ende des Zuges.",
        ),
    ]


register("Akiri, Fearless Voyager", _akiri_fearless_voyager)


def _argentum_armor() -> list[AbilitySpec]:
    """Equipped creature gets +6/+6.
    Whenever equipped creature attacks, destroy target permanent.
    Equip {6}

    — Argentum Armor. Equip is synthesized by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 6, "toughness": 6})],
            raw_text="Ausgerüstete Kreatur erhält +6/+6.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": "permanent"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Wenn die ausgerüstete Kreatur angreift, zerstöre eine Zielspielsteinkarte.",
        ),
    ]


register("Argentum Armor", _argentum_armor)


def _blackblade_reforged() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each land you control.
    Equip legendary creature {3}
    Equip {7}

    — Blackblade Reforged. Both Equip costs collapse to the keyword
    catalogue's single synthesized Equip ability (the cheaper "equip
    legendary creature" alternative cost isn't modeled separately — a
    documented simplification, always the {7} cost here).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "lands_you_control", "toughness_count": "lands_you_control",
            })],
            raw_text="Ausgerüstete Kreatur erhält +1/+1 für jedes Land, das du kontrollierst.",
        )
    ]


register("Blackblade Reforged", _blackblade_reforged)


def _bloodforged_battle_axe() -> list[AbilitySpec]:
    """Equipped creature gets +2/+0.
    Whenever equipped creature deals combat damage to a player, create a
    token that's a copy of this Equipment.
    Equip {2}
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 0})],
            raw_text="Ausgerüstete Kreatur erhält +2/+0.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {"target_kind": None})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden zufügt, "
                     "erzeuge einen Spielstein, der eine Kopie dieser Ausrüstung ist.",
        ),
    ]


register("Bloodforged Battle-Axe", _bloodforged_battle_axe)


def _bruenor_battlehammer() -> list[AbilitySpec]:
    """Each creature you control gets +2/+0 for each Equipment attached to it.
    You may pay {0} rather than pay the equip cost of the first equip
    ability you activate each turn.

    — Bruenor Battlehammer. The cost-reduction clause isn't modeled (the
    engine's cost-reduction static only scopes to spells being cast, not
    activated-ability costs) — a documented gap.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 2, "toughness": 0,
                "power_count": "equipment_attached_to_self",
            })],
            raw_text="Jede Kreatur, die du kontrollierst, erhält +2/+0 für jede "
                     "Ausrüstung, die an ihr befestigt ist.",
        )
    ]


register("Bruenor Battlehammer", _bruenor_battlehammer)


def _colossus_hammer() -> list[AbilitySpec]:
    """Equipped creature gets +10/+10 and loses flying.
    Equip {8}
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 10, "toughness": 10}),
                EffectSpec("remove_keyword", {"affects": "attached_permanent", "keywords": ["flying"]}),
            ],
            raw_text="Ausgerüstete Kreatur erhält +10/+10 und verliert Flugfähigkeit.",
        )
    ]


register("Colossus Hammer", _colossus_hammer)


def _austere_command() -> list[AbilitySpec]:
    """Choose two —
    • Destroy all artifacts.
    • Destroy all enchantments.
    • Destroy all creatures with mana value 3 or less.
    • Destroy all creatures with mana value 4 or greater.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [EffectSpec("destroy", {"selector": "all_artifacts"})],
                    [EffectSpec("destroy", {"selector": "all_enchantments"})],
                    [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"max_mana_value": 3}})],
                    [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_mana_value": 4}})],
                ],
                "descriptions": [
                    "Zerstöre alle Artefakte.",
                    "Zerstöre alle Verzauberungen.",
                    "Zerstöre alle Kreaturen mit Manawert 3 oder weniger.",
                    "Zerstöre alle Kreaturen mit Manawert 4 oder mehr.",
                ],
            },
            raw_text="Wähle zwei —",
        )
    ]


register("Austere Command", _austere_command)


def _boros_charm() -> list[AbilitySpec]:
    """Choose one —
    • Boros Charm deals 4 damage to target player or planeswalker.
    • Permanents you control gain indestructible until end of turn.
    • Target creature gains double strike until end of turn.

    — Boros Charm. The first mode drops "or planeswalker" (the project's
    existing convention for this exact phrase, see `parser/oracle/catalogue/
    subgrammars.py`'s ``"target player or planeswalker"`` row, which maps to
    plain ``"player"`` too).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 4, "target_kind": "player"})],
                    [EffectSpec("pump", {"selector": "permanents_you_control", "keywords": ["indestructible"]})],
                    [EffectSpec("pump", {"target_kind": "creature", "keywords": ["double_strike"]})],
                ],
                "descriptions": [
                    "Fügt einem Zielspieler 4 Schaden zu.",
                    "Bleibende Karten, die du kontrollierst, erhalten Unzerstörbarkeit bis zum Ende des Zuges.",
                    "Eine Zielkreatur erhält Doppelschlag bis zum Ende des Zuges.",
                ],
            },
            raw_text="Wähle eins —",
        )
    ]


register("Boros Charm", _boros_charm)


def _citywide_bust() -> list[AbilitySpec]:
    """Destroy all creatures with toughness 4 or greater."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_toughness": 4}})],
            raw_text="Zerstöre alle Kreaturen mit Widerstandskraft 4 oder mehr.",
        )
    ]


register("Citywide Bust", _citywide_bust)


def _embercleave() -> list[AbilitySpec]:
    """Flash
    This spell costs {1} less to cast for each attacking creature you control.
    When Embercleave enters, attach it to target creature you control.
    Equipped creature gets +1/+1 and has double strike and trample.
    Equip {3}

    — Embercleave. Flash comes from the RULE 702 keyword catalogue (and is
    now honoured for casting timing, `GameEngine.can_cast`). The attacker-
    count cost reduction isn't modeled (no per-cast, board-state-dependent
    discount mechanism exists yet for a card still in hand) — a documented
    gap; it always costs its full {3}{R}{W}.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach", {"target_kind": "creature_you_control"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Sturmpanzerklinge ins Spiel kommt, befestige sie an einer "
                     "Zielkreatur, die du kontrollierst.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent",
                                              "keywords": ["double_strike", "trample"]}),
            ],
            raw_text="Ausgerüstete Kreatur erhält +1/+1 und hat Doppelschlag und Trampelschaden.",
        ),
    ]


register("Embercleave", _embercleave)


def _encroaching_wastes() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {4}, {T}, Sacrifice this land: Destroy target nonbasic land.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "nonbasic_land"})],
            cost={"mana": "{4}", "taps_self": True, "sacrifice": "self"},
            raw_text="{4}, {T}, Opfere dieses Land: Zerstöre ein nichtgrundlegendes Zielland.",
        )
    ]


register("Encroaching Wastes", _encroaching_wastes)


def _explorers_scope() -> list[AbilitySpec]:
    """Whenever equipped creature attacks, look at the top card of your
    library. If it's a land card, you may put it onto the battlefield tapped.
    Equip {1}
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("peek_top_land_battlefield_tapped", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Wenn die ausgerüstete Kreatur angreift, sieh dir die oberste "
                     "Karte deiner Bibliothek an. Falls es eine Landkarte ist, "
                     "kannst du sie getappt ins Spiel legen.",
        )
    ]


register("Explorer's Scope", _explorers_scope)


def _farewell() -> list[AbilitySpec]:
    """Choose one or more —
    • Exile all artifacts.
    • Exile all creatures.
    • Exile all enchantments.
    • Exile all graveyards.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "options": [
                    [EffectSpec("exile", {"selector": "all_artifacts"})],
                    [EffectSpec("exile", {"selector": "all_creatures"})],
                    [EffectSpec("exile", {"selector": "all_enchantments"})],
                    [EffectSpec("exile_all_graveyards", {})],
                ],
                "descriptions": [
                    "Exiliere alle Artefakte.",
                    "Exiliere alle Kreaturen.",
                    "Exiliere alle Verzauberungen.",
                    "Exiliere alle Friedhöfe.",
                ],
            },
            raw_text="Wähle eins oder mehr —",
        )
    ]


register("Farewell", _farewell)


def _fighter_class() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    When this Class enters, search your library for an Equipment card,
    reveal it, put it into your hand, then shuffle.
    {1}{R}{W}: Level 2
    Equip abilities you activate cost {2} less to activate.
    {3}{R}{W}: Level 3
    Whenever a creature you control attacks, up to one target creature
    blocks it this combat if able.

    — Fighter Class. Only the level-1 ETB tutor is modeled; the level 2/3
    upgrades (an equip-cost reduction and a forced-block effect) aren't —
    the Class simply never gains a "level up" button, a documented gap
    rather than a wrongly-behaving one.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Equipment"}, "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Klasse ins Spiel kommt, suche in deiner Bibliothek "
                     "nach einer Ausrüstungskarte, zeige sie offen, nimm sie auf "
                     "deine Hand, dann mische.",
        )
    ]


register("Fighter Class", _fighter_class)


def _forging_the_tyrite_sword() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter.
    Sacrifice after III.)
    I, II — Create a Treasure token.
    III — Search your library for a card named Halvar, God of Battle or an
    Equipment card, reveal it, put it into your hand, then shuffle.

    — Forging the Tyrite Sword. Chapter III drops the "named Halvar, God of
    Battle" alternative (a name-*or*-type search the ``search`` effect's
    criteria can't express — it can only AND conditions, not OR two
    different shapes) and always searches for an Equipment card instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1, 2]},
            raw_text="I, II — Erzeuge einen Schatz-Spielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Equipment"}, "destination": "hand"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
            raw_text="III — Suche in deiner Bibliothek nach einer Ausrüstungskarte, "
                     "zeige sie offen, nimm sie auf deine Hand, dann mische.",
        ),
    ]


register("Forging the Tyrite Sword", _forging_the_tyrite_sword)


def _halvar_god_of_battle() -> list[AbilitySpec]:
    """Creatures you control that are enchanted or equipped have double strike.
    At the beginning of each combat, you may attach target Aura or Equipment
    attached to a creature you control to target creature you control.

    — Halvar, God of Battle. The move-attachment trigger needs two
    independent targets on one ability (the Aura/Equipment *and* its new
    host), which isn't supported yet (`docs/Reference/11_CARD_CATALOGUE_
    AUTHORING_GUIDE.md` §5's "at most one targeting effect per ability") —
    a documented gap; only the static double-strike grant is modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "enchanted_or_equipped_creatures_you_control", "keywords": ["double_strike"],
            })],
            raw_text="Kreaturen, die du kontrollierst und die verzaubert oder "
                     "ausgerüstet sind, haben Doppelschlag.",
        )
    ]


register("Halvar, God of Battle", _halvar_god_of_battle)


def _indomitable_archangel() -> list[AbilitySpec]:
    """Flying
    Metalcraft — Artifacts you control have shroud as long as you control
    three or more artifacts.

    — Flying comes from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "artifacts_you_control", "keywords": ["shroud"],
                "min_count_selector": "artifacts_you_control", "min_count": 3,
            })],
            raw_text="Metallgespür — Artefakte, die du kontrollierst, haben Schutzhülle, "
                     "solange du drei oder mehr Artefakte kontrollierst.",
        )
    ]


register("Indomitable Archangel", _indomitable_archangel)


def _kaldra_compleat() -> list[AbilitySpec]:
    """Living weapon
    Indestructible
    Equipped creature gets +5/+5 and has first strike, trample,
    indestructible, haste, and "Whenever this creature deals combat damage
    to a creature, exile that creature."
    Equip {7}

    — Kaldra Compleat. Living weapon and Indestructible come from the RULE
    702 keyword catalogue (Living Weapon's germ-token creation is now
    synthesized behaviourally too, see `effect_binder._keyword_triggered_
    abilities`). The granted "exile that creature" ability isn't modeled —
    it needs a per-firing dynamic reference to *whichever* creature was
    just damaged, which no generic `TriggeredAbility` (one fixed `effects`
    list) can carry (the same class of gap `RulesEngine.check_rampage`
    solves by going around `TriggeredAbility` entirely) — a documented gap.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 5, "toughness": 5}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent",
                    "keywords": ["first_strike", "trample", "indestructible", "haste"],
                }),
            ],
            raw_text="Ausgerüstete Kreatur erhält +5/+5 und hat Erstschlag, "
                     "Trampelschaden, Unzerstörbarkeit und Eile.",
        )
    ]


register("Kaldra Compleat", _kaldra_compleat)


def _lion_sash() -> list[AbilitySpec]:
    """{W}: Exile target card from a graveyard. If it was a permanent card,
    put a +1/+1 counter on this permanent.
    Equipped creature gets +1/+1 for each +1/+1 counter on this Equipment.
    Reconfigure {2}

    — Reconfigure's attach/unattach activated ability is synthesized by the
    keyword catalogue.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_graveyard_card_counter_if_permanent", {})],
            cost={"mana": "{W}"},
            raw_text="{W}: Exiliere eine Zielkarte aus einem Friedhof. Falls es "
                     "eine Karte eines bleibenden Kartentyps war, lege einen "
                     "+1/+1-Marker auf diese bleibende Karte.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "plus_one_counters_on_self", "toughness_count": "plus_one_counters_on_self",
            })],
            raw_text="Ausgerüstete Kreatur erhält +1/+1 für jeden +1/+1-Marker auf "
                     "dieser Ausrüstung.",
        ),
    ]


register("Lion Sash", _lion_sash)


def _nahiri_heir_of_the_ancients() -> list[AbilitySpec]:
    """+1: Create a 1/1 white Kor Warrior creature token. You may attach an
    Equipment you control to it.
    −2: Look at the top six cards of your library. You may reveal a Warrior
    or Equipment card from among them and put it into your hand. Put the
    rest on the bottom of your library in a random order.
    −3: Nahiri deals damage to target creature or planeswalker equal to
    twice the number of Equipment you control.

    — Nahiri, Heir of the Ancients. Only +1 is modeled: −2 needs a "look at
    top N, take a matching one, bottom the rest" mechanic distinct from a
    whole-library `search` (not implemented); −3 needs a dynamic damage
    amount computed at resolution (no `DealDamageEffect` "amount equals a
    count" mode exists yet). Both are documented gaps rather than guessed
    approximations.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token_may_attach_equipment", {
                "token_name": "Kor Warrior", "power": 1, "toughness": 1,
                "colors": ["W"], "subtypes": ["Kor", "Warrior"],
            })],
            cost={"loyalty": 1},
            raw_text="+1: Erzeuge einen weißen 1/1 Kor-Krieger-Kreaturenspielstein. "
                     "Du kannst eine Ausrüstung, die du kontrollierst, an ihm befestigen.",
        )
    ]


register("Nahiri, Heir of the Ancients", _nahiri_heir_of_the_ancients)


def _nahiri_storm_of_stone() -> list[AbilitySpec]:
    """During your turn, creatures you control have first strike and equip
    abilities you activate cost {1} less to activate.
    −X: Nahiri deals X damage to target tapped creature.

    — Nahiri, Storm of Stone. Only the first-strike half of the static is
    modeled (the equip-cost reduction isn't — same gap as Bruenor
    Battlehammer/Nahiri, Heir); the −X ability needs a variable-loyalty-cost
    + dynamic-damage-amount mechanism this engine doesn't have, so it's
    left off entirely rather than guessed at.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["first_strike"],
                "active_player_only": True,
            })],
            raw_text="Während deines Zuges haben Kreaturen, die du kontrollierst, Erstschlag.",
        )
    ]


register("Nahiri, Storm of Stone", _nahiri_storm_of_stone)


def _nettlecyst() -> list[AbilitySpec]:
    """Living weapon
    Equipped creature gets +1/+1 for each artifact and/or enchantment you
    control.
    Equip {2}

    — Living Weapon's germ-token creation is synthesized behaviourally by
    `effect_binder._keyword_triggered_abilities`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "artifacts_and_or_enchantments_you_control",
                "toughness_count": "artifacts_and_or_enchantments_you_control",
            })],
            raw_text="Ausgerüstete Kreatur erhält +1/+1 für jedes Artefakt und/oder "
                     "jede Verzauberung, die du kontrollierst.",
        )
    ]


register("Nettlecyst", _nettlecyst)


def _open_the_armory() -> list[AbilitySpec]:
    """Search your library for an Aura or Equipment card, reveal it, put it
    into your hand, then shuffle.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {"criteria": {"type": ["Aura", "Equipment"]}, "destination": "hand"})],
            raw_text="Suche in deiner Bibliothek nach einer Aura- oder Ausrüstungskarte, "
                     "zeige sie offen, nimm sie auf deine Hand, dann mische.",
        )
    ]


register("Open the Armory", _open_the_armory)


def _relic_seeker() -> list[AbilitySpec]:
    """Renown 1
    When this creature becomes renowned, you may search your library for
    an Equipment card, reveal it, put it into your hand, then shuffle.

    — Renown 1 comes from the RULE 702 keyword catalogue, whose counter-
    placing behaviour is now synthesized (`effect_binder._keyword_
    triggered_abilities`, firing `EventType.RENOWNED`); this entry only
    adds Relic Seeker's own *separate* "becomes renowned" search trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Equipment"}, "destination": "hand"})],
            trigger={"event": "RENOWNED", "condition": {"subject": "self"}},
            optional=True,
            raw_text="Wenn diese Kreatur berühmt wird, kannst du in deiner Bibliothek "
                     "nach einer Ausrüstungskarte suchen, sie offen zeigen, auf deine "
                     "Hand nehmen, dann mische.",
        )
    ]


register("Relic Seeker", _relic_seeker)


def _robe_of_stars() -> list[AbilitySpec]:
    """Equipped creature gets +0/+3.
    Astral Projection — {1}{W}: Equipped creature phases out.
    Equip {1}

    — Robe of Stars. Astral Projection isn't modeled (this engine has no
    phasing subsystem, RULE 702.26) — a documented gap; only the static
    pump is modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 0, "toughness": 3})],
            raw_text="Ausgerüstete Kreatur erhält +0/+3.",
        )
    ]


register("Robe of Stars", _robe_of_stars)


def _rogues_gloves() -> list[AbilitySpec]:
    """Whenever equipped creature deals combat damage to a player, you may
    draw a card.
    Equip {2}
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            optional=True,
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden "
                     "zufügt, kannst du eine Karte ziehen.",
        )
    ]


register("Rogue's Gloves", _rogues_gloves)


def _rogues_passage() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {4}, {T}: Target creature can't be blocked this turn.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"target_kind": "creature"})],
            cost={"mana": "{4}", "taps_self": True},
            raw_text="{4}, {T}: Eine Zielkreatur kann in diesem Zug nicht geblockt werden.",
        )
    ]


register("Rogue's Passage", _rogues_passage)


def _simian_sling() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1.
    Whenever this creature or equipped creature becomes blocked, it deals
    1 damage to defending player.
    Reconfigure {2}

    — Simian Sling. The trigger's "defending player" resolves off the
    ability's own source (Simian Sling) via `_defending_player_of`, which
    reads *its own* combat-defender stamp — correct when Simian Sling
    itself is the attacking creature, but it won't have one when it's
    reconfigured onto a *different* attacking creature instead (a documented
    simplification: the trigger still fires, but finds no defending player
    to hit in that case).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
            raw_text="Ausgerüstete Kreatur erhält +1/+1.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "defending_player"})],
            trigger={"event": EventType.BECOMES_BLOCKED, "condition": {"subject": "self_or_attached_permanent"}},
            raw_text="Wenn diese Kreatur oder die ausgerüstete Kreatur geblockt "
                     "wird, fügt sie dem verteidigenden Spieler 1 Schaden zu.",
        ),
    ]


register("Simian Sling", _simian_sling)


def _spirit_mantle() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1 and has protection from creatures.

    — Spirit Mantle. Protection reads the printed oracle text directly
    (`game/combat.py`'s `protections_of`, independent of this registry), so
    only the +1/+1 anthem needs authoring here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
            raw_text="Verzauberte Kreatur erhält +1/+1.",
        )
    ]


register("Spirit Mantle", _spirit_mantle)


def _sram_senior_edificer() -> list[AbilitySpec]:
    """Whenever you cast an Aura, Equipment, or Vehicle spell, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "you"},
                "spell_subtype_any": ["Aura", "Equipment", "Vehicle"],
            },
            raw_text="Wenn du einen Aura-, Ausrüstungs- oder Fahrzeugzauber wirkst, ziehe eine Karte.",
        )
    ]


register("Sram, Senior Edificer", _sram_senior_edificer)


def _sun_titan() -> list[AbilitySpec]:
    """Vigilance
    Whenever this creature enters or attacks, you may return target
    permanent card with mana value 3 or less from your graveyard to the
    battlefield.

    — Vigilance comes from the RULE 702 keyword catalogue. The "mana value
    3 or less" restriction on the graveyard target isn't modeled (no
    graveyard target kind carries a mana-value filter yet) — any permanent
    card in the graveyard is a legal target, a documented simplification.
    """
    effect = EffectSpec(
        "return_from_graveyard",
        {"target_kind": "graveyard_permanent", "destination": "battlefield", "optional": True},
    )
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(effect.type, dict(effect.params))],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du eine "
                     "Zielkarte eines bleibenden Kartentyps aus deinem Friedhof "
                     "ins Spiel zurückbringen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec(effect.type, dict(effect.params))],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur angreift, kannst du eine Zielkarte "
                     "eines bleibenden Kartentyps aus deinem Friedhof ins Spiel "
                     "zurückbringen.",
        ),
    ]


register("Sun Titan", _sun_titan)


def _sunforger() -> list[AbilitySpec]:
    """Equipped creature gets +4/+0.
    {R}{W}, Unattach this Equipment: Search your library for a red or
    white instant card with mana value 4 or less and cast that card
    without paying its mana cost. Then shuffle.
    Equip {3}
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 4, "toughness": 0})],
            raw_text="Ausgerüstete Kreatur erhält +4/+0.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Instant", "color": ["R", "W"], "max_mana_value": 4},
                "destination": "cast_free",
            })],
            cost={"mana": "{R}{W}", "unattach_self": True},
            raw_text="{R}{W}, Löse diese Ausrüstung: Suche in deiner Bibliothek nach "
                     "einer roten oder weißen Spontanzauberkarte mit Manawert 4 oder "
                     "weniger und wirke diese Karte, ohne ihre Manakosten zu bezahlen. "
                     "Mische danach.",
        ),
    ]


register("Sunforger", _sunforger)


def _sword_of_forge_and_frontier() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from red and from green.
    Whenever equipped creature deals combat damage to a player, exile the
    top two cards of your library. You may play those cards this turn. You
    may play an additional land this turn.
    Equip {2}

    — Sword of Forge and Frontier. Protection reads the printed oracle text
    directly (independent of this registry); the "impulsive draw + extra
    land drop" trigger isn't modeled (no "exile and may play until end of
    turn" mechanism exists yet) — a documented gap, only the static pump
    is modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
            raw_text="Ausgerüstete Kreatur erhält +2/+2.",
        )
    ]


register("Sword of Forge and Frontier", _sword_of_forge_and_frontier)


def _sword_of_hearth_and_home() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from green and from white.
    Whenever equipped creature deals combat damage to a player, exile up to
    one target creature you own, then search your library for a basic land
    card. Put both cards onto the battlefield under your control, then
    shuffle.
    Equip {2}

    — Sword of Hearth and Home. Simplified: only the ramp half ("search
    your library for a basic land card, put it onto the battlefield") is
    modeled — the "exile up to one target creature you own, then reunite it
    with the land" blink half needs a two-part simultaneous re-entry this
    engine's `search` effect can't express, so it's dropped rather than
    guessed at.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
            raw_text="Ausgerüstete Kreatur erhält +2/+2.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield"})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden "
                     "zufügt, suche in deiner Bibliothek nach einer Standardlandkarte "
                     "und lege sie ins Spiel, dann mische.",
        ),
    ]


register("Sword of Hearth and Home", _sword_of_hearth_and_home)


def _sword_of_light_and_shadow() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from white and from black.
    Whenever equipped creature deals combat damage to a player, you gain 3
    life and you may return up to one target creature card from your
    graveyard to your hand.
    Equip {2}
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
            raw_text="Ausgerüstete Kreatur erhält +2/+2.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"amount": 3}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "hand", "optional": True,
                }),
            ],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden "
                     "zufügt, gewinnst du 3 Lebenspunkte hinzu und kannst eine "
                     "Zielkreaturenkarte aus deinem Friedhof auf deine Hand "
                     "zurückbringen.",
        ),
    ]


register("Sword of Light and Shadow", _sword_of_light_and_shadow)


def _sword_of_the_animist() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1.
    Whenever equipped creature attacks, you may search your library for a
    basic land card, put it onto the battlefield tapped, then shuffle.
    Equip {2}
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
            raw_text="Ausgerüstete Kreatur erhält +1/+1.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield_tapped"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Wenn die ausgerüstete Kreatur angreift, kannst du in deiner "
                     "Bibliothek nach einer Standardlandkarte suchen, sie getappt "
                     "ins Spiel legen, dann mische.",
        ),
    ]


register("Sword of the Animist", _sword_of_the_animist)


def _sword_of_truth_and_justice() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from white and from blue.
    Whenever equipped creature deals combat damage to a player, put a
    +1/+1 counter on a creature you control, then proliferate.
    Equip {2}

    — Sword of Truth and Justice. "put a +1/+1 counter on a creature you
    control" is authored as a real target (``creature_you_control``) rather
    than RULE 701.19's untargeted choice — a small, deliberate simplification
    (functionally equivalent at this engine's fidelity).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2})],
            raw_text="Ausgerüstete Kreatur erhält +2/+2.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "target_kind": "creature_you_control"}),
                EffectSpec("proliferate", {}),
            ],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden "
                     "zufügt, lege einen +1/+1-Marker auf eine Kreatur, die du "
                     "kontrollierst, und proliferiere dann.",
        ),
    ]


register("Sword of Truth and Justice", _sword_of_truth_and_justice)


def _swords_to_plowshares() -> list[AbilitySpec]:
    """Exile target creature. Its controller gains life equal to its power."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_gain_life_equal_power", {"target_kind": "creature"})],
            raw_text="Exiliere eine Zielkreatur. Ihr Beherrscher gewinnt Lebenspunkte "
                     "in Höhe ihrer Stärke hinzu.",
        )
    ]


register("Swords to Plowshares", _swords_to_plowshares)


def _timely_ward() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash if it targets a commander.
    Enchant creature
    Enchanted creature has indestructible.

    — Timely Ward. The conditional-flash clause isn't modeled (no
    "flash if X" casting-permission mechanism exists) — a documented gap;
    only the static indestructible grant is modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["indestructible"]})],
            raw_text="Verzauberte Kreatur hat Unzerstörbarkeit.",
        )
    ]


register("Timely Ward", _timely_ward)


def _unquestioned_authority() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card.
    Enchanted creature has protection from creatures.

    — Unquestioned Authority. Protection reads the printed oracle text
    directly (independent of this registry), so only the ETB draw needs
    authoring here.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura ins Spiel kommt, ziehe eine Karte.",
        )
    ]


register("Unquestioned Authority", _unquestioned_authority)


def _volcanic_fallout() -> list[AbilitySpec]:
    """This spell can't be countered.
    Volcanic Fallout deals 2 damage to each creature and each player.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("damage", {"amount": 2, "selector": "each_creature_and_player"}),
            ],
            raw_text="Dieser Zauberspruch kann nicht annulliert werden. Vulkanischer "
                     "Niederschlag fügt jeder Kreatur und jedem Spieler 2 Schaden zu.",
        )
    ]


register("Volcanic Fallout", _volcanic_fallout)


def _wrath_of_god() -> list[AbilitySpec]:
    """Destroy all creatures. They can't be regenerated."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "can_be_regenerated": False})],
            raw_text="Zerstöre alle Kreaturen. Sie können nicht regenerieren.",
        )
    ]


register("Wrath of God", _wrath_of_god)


def _crypt_incursion() -> list[AbilitySpec]:
    """Exile all creature cards from target player's graveyard. You gain 3
    life for each card exiled this way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_graveyard_creatures_gain_life", {"target_kind": "player", "life_per_card": 3})],
            raw_text="Exiliere alle Kreaturenkarten aus dem Friedhof eines Zielspielers. "
                     "Du gewinnst 3 Lebenspunkte für jede auf diese Weise exilierte Karte.",
        )
    ]


register("Crypt Incursion", _crypt_incursion)


def _sign_in_blood() -> list[AbilitySpec]:
    """Target player draws two cards and loses 2 life."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("target_player_draw_lose_life", {"draw_count": 2, "life_loss": 2})],
            raw_text="Zielspieler zieht zwei Karten und verliert 2 Lebenspunkte.",
        )
    ]


register("Sign in Blood", _sign_in_blood)


def _dismantling_wave() -> list[AbilitySpec]:
    """For each opponent, destroy up to one target artifact or enchantment
    that player controls.
    Cycling {6}{W}{W}
    When you cycle this card, destroy all artifacts and enchantments.

    — Dismantling Wave. Simplified to a single "destroy up to one target
    artifact or enchantment" (dropping the "for each opponent" multiplayer
    scaling — no card in this pool needs per-opponent multi-target
    scaling yet). Cycling isn't modeled (no hand-zone discard-cost cycling
    mechanism exists) — a documented gap.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "permanent", "optional": True})],
            raw_text="Zerstöre bis zu eine Zielartefakt- oder -verzauberungskarte, "
                     "die ein Gegner kontrolliert.",
        )
    ]


register("Dismantling Wave", _dismantling_wave)


def _the_wandering_emperor() -> list[AbilitySpec]:
    """Flash
    As long as The Wandering Emperor entered this turn, you may activate
    her loyalty abilities any time you could cast an instant.
    +1: Put a +1/+1 counter on up to one target creature. It gains first
    strike until end of turn.
    −1: Create a 2/2 white Samurai creature token with vigilance.
    −2: Exile target tapped creature. You gain 2 life.

    — The Wandering Emperor. Flash comes from the RULE 702 keyword
    catalogue (and is now honoured for casting timing). The "activate
    loyalty abilities at instant speed" clause isn't modeled — every
    loyalty ability in this engine is sorcery-speed-only
    (`GameEngine._can_activate_loyalty`), same as any other planeswalker —
    a documented gap. −2 drops the "tapped" restriction on its target
    (no such target filter exists yet).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counter_first_strike", {"target_kind": "creature", "optional": True})],
            cost={"loyalty": 1},
            raw_text="+1: Lege einen +1/+1-Marker auf bis zu eine Zielkreatur. Sie "
                     "erhält Erstschlag bis zum Ende des Zuges.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "token_name": "Samurai", "power": 2, "toughness": 2, "count": 1,
                "colors": ["W"], "subtypes": ["Samurai"], "keywords": ["vigilance"],
            })],
            cost={"loyalty": -1},
            raw_text="−1: Erzeuge einen weißen 2/2 Samurai-Kreaturenspielstein mit Wachsamkeit.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "creature"}),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            cost={"loyalty": -2},
            raw_text="−2: Exiliere eine Zielkreatur. Du gewinnst 2 Lebenspunkte hinzu.",
        ),
    ]


register("The Wandering Emperor", _the_wandering_emperor)
