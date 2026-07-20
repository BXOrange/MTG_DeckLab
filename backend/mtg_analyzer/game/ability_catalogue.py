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
    # A DFC/MDFC/split card's ``name`` is the combined "Front // Back"; a
    # registration keyed on the (castable) front face's own name should still
    # match (e.g. Shatterskull Smashing, whose back is a land). Fall back to
    # the pre-"//" front name — the same slice `Card.fuse_face` reads.
    if factory is None and "//" in name:
        factory = _REGISTRY.get(name.split("//")[0].strip())
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

    — Robe of Stars. Astral Projection is now real (RULE 702.26 phasing,
    `game/effects.py`'s `PhaseOutEffect`, scoped to the single-permanent
    case this card needs — no "phase out together" attachment chain).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 0, "toughness": 3})],
            raw_text="Ausgerüstete Kreatur erhält +0/+3.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {})],
            cost={"mana": "{1}{W}"},
            raw_text="Astralprojektion — {1}{W}: Ausgerüstete Kreatur phast heraus.",
        ),
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
    scaling yet). Cycling's own mass "destroy all artifacts and
    enchantments" is now real (RULE 702.28/702.29's "Discard this card"
    activation cost, `game/costs.py`'s ``discard_self``) — a hand-zone
    `AbilitySpec("activated", ...)` alongside the spell-effect one below,
    reusing the already-existing mass-destroy selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "permanent", "optional": True})],
            raw_text="Zerstöre bis zu eine Zielartefakt- oder -verzauberungskarte, "
                     "die ein Gegner kontrolliert.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("destroy", {"selector": "all_artifacts"}),
                EffectSpec("destroy", {"selector": "all_enchantments"}),
            ],
            cost={"text": "{6}{W}{W}, Discard this card"},
            raw_text="Verausgabung {6}{W}{W}. Wenn du diese Karte verausgabst, "
                     "zerstöre alle Artefakte und Verzauberungen.",
        ),
    ]


register("Dismantling Wave", _dismantling_wave)


def _renewed_faith() -> list[AbilitySpec]:
    """You gain 3 life.
    Cycling {2}{W}

    — Renewed Faith. A simple two-mode card (cast for the life gain, or
    cycle it away for a card) exercising the same hand-zone Cycling
    activated-ability shape as Dismantling Wave with a much smaller cost,
    and no mass-destroy selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_life", {"amount": 3})],
            raw_text="Du erhältst 3 Lebenspunkte hinzu.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{2}{W}, Discard this card"},
            raw_text="Verausgabung {2}{W}.",
        ),
    ]


register("Renewed Faith", _renewed_faith)


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
    loyalty abilities at instant speed" clause is now real too
    (`conditional_flash={"entered_this_turn": True}`, `game/
    condition_query.py`/`GameEngine._can_activate_loyalty`) — carried on
    the first loyalty ability below; `effect_binder.attach_to_object` scans
    every spec for it regardless of which one carries it, same as
    `additional_cost`. −2 drops the "tapped" restriction on its target (no
    such target filter exists yet).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counter_first_strike", {"target_kind": "creature", "optional": True})],
            cost={"loyalty": 1},
            conditional_flash={"entered_this_turn": True},
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


def _mana_drain() -> list[AbilitySpec]:
    """Counter target spell. At the beginning of your next main phase, add
    an amount of {C} equal to that spell's mana value.

    — Mana Drain. Now fully modeled (batch 22 built the delayed-trigger
    primitive): `counter` the target spell, then `create_delayed_trigger`
    arms an "at the beginning of your next main phase" ability (``step``
    ``"main"`` matches whichever of main1/main2 begins first, ``scope``
    ``"controller"``). The countered spell is gone by the time the delayed
    ability fires, so its mana value is captured *now* via
    ``capture="target_mana_value"`` and substituted into the delayed
    `add_mana`'s ``"x"`` amount (RULE 603.7's "that spell's mana value").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "main",
                    "scope": "controller",
                    "capture": "target_mana_value",
                    "effects": [
                        {"type": "add_mana", "params": {"color": "C", "amount": "x"}},
                    ],
                }),
            ],
            raw_text="Annulliere einen Zielzauberspruch. Zu Beginn deiner nächsten "
                     "Hauptphase erzeuge eine Menge {C} in Höhe der Manakosten "
                     "jenes Zauberspruchs.",
        )
    ]


register("Mana Drain", _mana_drain)


def _corpse_dance() -> list[AbilitySpec]:
    """Buyback {2} (You may pay an additional {2} as you cast this spell.
    If you do, put this card into your hand as it resolves.)
    Return the top creature card of your graveyard to the battlefield.
    That creature gains haste until end of turn. Exile it at the beginning
    of the next end step.

    — Corpse Dance. Buyback comes from the RULE 702.27 keyword catalogue
    (independent of this registry). The return-and-haste half is modeled
    (`return_top_graveyard_creature_with_haste`, a positional "top of
    graveyard" pick, not a RULE 115 target); the trailing "Exile it at the
    beginning of the next end step." is dropped — the same missing
    one-shot delayed-trigger primitive Mana Drain's entry above needs, see
    docs/implementation-state/ToDo_Backend.md.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_top_graveyard_creature_with_haste", {})],
            raw_text="Bringe die oberste Kreaturenkarte deines Friedhofs ins Spiel "
                     "zurück. Diese Kreatur erhält Eile bis zum Ende des Zuges.",
        )
    ]


register("Corpse Dance", _corpse_dance)


def _feed_the_swarm() -> list[AbilitySpec]:
    """Destroy target creature or enchantment an opponent controls. You
    lose life equal to that permanent's mana value.

    — Feed the Swarm. ``target_kind="permanent"`` is broader than "creature
    or enchantment an opponent controls" (no target kind unions two card
    types *and* restricts to opponents at once) — the same simplification
    tier `parser.oracle.catalogue.subgrammars`'s "target artifact or
    enchantment" → ``"permanent"`` row already uses generically; the life
    loss always hits the caster, matching the printed "you lose life".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_lose_life_equal_mana_value", {"target_kind": "permanent"})],
            raw_text="Zerstöre eine Zielkreatur oder eine Zielverzauberung, die ein "
                     "Gegner kontrolliert. Du verlierst Lebenspunkte in Höhe des "
                     "Manawerts dieser bleibenden Karte.",
        )
    ]


register("Feed the Swarm", _feed_the_swarm)


def _resculpt() -> list[AbilitySpec]:
    """Exile target artifact or creature. Its controller creates a 4/4 blue
    and red Elemental creature token.

    — Resculpt. ``target_kind="permanent"`` is the same documented
    simplification Feed the Swarm's entry above uses (drops the artifact/
    creature type union — no target kind names exactly that pair).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_create_token", {
                "target_kind": "permanent",
                "power": 4, "toughness": 4, "colors": ["U", "R"], "subtypes": ["Elemental"],
            })],
            raw_text="Exiliere eine Zielartefakt- oder Zielkreaturenkarte. Ihr "
                     "Beherrscher erzeugt einen blau-roten 4/4 Elementar-"
                     "Kreaturenspielstein.",
        )
    ]


register("Resculpt", _resculpt)


def _mirage_mirror() -> list[AbilitySpec]:
    """{2}: This artifact becomes a copy of target artifact, creature,
    enchantment, or land until end of turn.

    — Mirage Mirror. ``target_kind="permanent"`` is broader than the
    printed four-type union (no target kind names exactly "artifact,
    creature, enchantment, or land" — it only additionally admits a
    planeswalker), the same simplification tier Clever Impersonator's own
    `enter_as_copy` entry already documents for "any nonland permanent".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "permanent"})],
            cost={"mana": "{2}"},
            raw_text="{2}: Dieses Artefakt wird bis zum Ende des Zuges zu einer "
                     "Kopie einer Zielartefakt-, Zielkreaturen-, "
                     "Zielverzauberungs- oder Ziellandkarte.",
        )
    ]


register("Mirage Mirror", _mirage_mirror)


def _phyrexian_metamorph() -> list[AbilitySpec]:
    """({U/P} can be paid with either {U} or 2 life.)
    You may have this creature enter as a copy of any artifact or creature
    on the battlefield, except it's an artifact in addition to its other
    types.

    — Phyrexian Metamorph. The Phyrexian-mana reminder-text line is inert
    (parsed elsewhere, independent of this registry). Same `enter_as_copy`
    mechanism as Clever Impersonator (see its docstring); ``target_kind=
    "permanent"`` is the same "no type-union target kind" simplification
    (drops the artifact/creature restriction, permitting an enchantment/
    land/planeswalker pick too — never correct oracle-text-wise but not
    currently prevented, exactly Clever Impersonator's own documented gap).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent", "add_types": ["Artifact"]})],
            raw_text="Du kannst diese Kreatur als Kopie eines beliebigen Artefakts "
                     "oder einer beliebigen Kreatur ins Spiel kommen lassen, außer "
                     "dass sie zusätzlich zu ihren anderen Typen ein Artefakt ist.",
        )
    ]


register("Phyrexian Metamorph", _phyrexian_metamorph)


def _steal_enchantment() -> list[AbilitySpec]:
    """Enchant enchantment
    You control enchanted enchantment.

    — Steal Enchantment. "Enchant enchantment" is the RULE 702.5 attach
    keyword, folded in automatically from the printed text (see
    `specs_for`'s precedence note) — not authored here. This entry only
    supplies the control-change static (RULE 613.2, layer 2), scoped
    ``affects="attached_permanent"`` — the same "enchanted/equipped X"
    idiom every Sword/Aura entry in this file already uses, just for
    `control_change` instead of `anthem`/`grant_keyword`. Omitting
    ``controller`` defaults it to the Aura's own controller (`continuous.
    recompute`'s layer-2 pass), exactly "you control".
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("control_change", {"affects": "attached_permanent"})],
            raw_text="Du kontrollierst die verzauberte Verzauberung.",
        )
    ]


register("Steal Enchantment", _steal_enchantment)


def _grinding_station() -> list[AbilitySpec]:
    """{T}, Sacrifice an artifact: Target player mills three cards.
    Whenever an artifact enters, you may untap this artifact.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {"count": 3, "target_kind": "player"})],
            cost={"text": "{T}, Sacrifice an artifact"},
            raw_text="{T}, Opfere ein Artefakt: Ein Zielspieler mischt drei Karten "
                     "seiner Bibliothek in seinen Friedhof.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": None, "untap": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "group", "type": "artifact"}},
            optional=True,
            raw_text="Wenn ein Artefakt ins Spiel kommt, kannst du dieses Artefakt "
                     "untappen.",
        ),
    ]


register("Grinding Station", _grinding_station)


def _goblin_engineer() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an
    artifact card, put it into your graveyard, then shuffle.
    {R}, {T}, Sacrifice an artifact: Return target artifact card with mana
    value 3 or less from your graveyard to the battlefield.

    — Goblin Engineer. The reanimation ability's "mana value 3 or less"
    restriction isn't modeled (no graveyard target kind carries a
    mana-value filter yet — the same documented simplification Sun Titan's
    own catalogue entry already uses, any artifact card in the graveyard is
    a legal target here).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Artifact"}, "destination": "graveyard"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du in deiner "
                     "Bibliothek nach einer Artefaktkarte suchen, sie in deinen "
                     "Friedhof legen, dann mischen.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_artifact", "destination": "battlefield"})],
            cost={"text": "{R}, {T}, Sacrifice an artifact"},
            raw_text="{R}, {T}, Opfere ein Artefakt: Bringe eine Zielartefaktkarte "
                     "aus deinem Friedhof ins Spiel zurück.",
        ),
    ]


register("Goblin Engineer", _goblin_engineer)


def _winds_of_abandon() -> list[AbilitySpec]:
    """Exile target creature you don't control. For each creature exiled
    this way, its controller searches their library for a basic land card.
    Those players put those cards onto the battlefield tapped, then
    shuffle.
    Overload {4}{W}{W} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Winds of Abandon. Models the ordinary single-target cast; Overload
    (RULE 702.96, already recognized as a keyword so it doesn't block this
    entry) has no behavioral effect yet — casting via Overload still only
    exiles one target rather than rewriting "target" to "each" (see
    docs/implementation-state/ToDo_Backend.md). ``target_kind="creature"``
    drops the "you don't control" restriction — a documented simplification,
    no target kind carries an ownership exclusion yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_controller_searches_basic_land", {"target_kind": "creature"})],
            raw_text="Exiliere eine Zielkreatur, die du nicht kontrollierst. Für "
                     "jede auf diese Weise exilierte Kreatur sucht ihr Beherrscher "
                     "in seiner Bibliothek nach einer Standardlandkarte. Diese "
                     "Spieler legen diese Karten getappt ins Spiel, dann mischen sie.",
        )
    ]


register("Winds of Abandon", _winds_of_abandon)


def _eiganjo_seat_of_the_empire() -> list[AbilitySpec]:
    """{T}: Add {W}.
    Channel — {2}{W}, Discard this card: It deals 4 damage to target
    attacking or blocking creature. This ability costs {1} less to
    activate for each legendary creature you control.

    — Eiganjo, Seat of the Empire. The mana ability is covered by the
    engine's mana model directly (no spec needed). Channel (RULE 702.29,
    `costs.ActivationCost.discard_self`) is modeled at its full, flat cost;
    "target attacking or blocking creature" collapses to a plain creature
    target (the same simplification `parser.oracle.catalogue.subgrammars`'s
    own "target attacking or blocking creature" row already uses
    elsewhere). The trailing "This ability costs {1} less to activate for
    each legendary creature you control." is dropped — there is no
    activated-ability cost-reduction primitive yet (`continuous.
    cost_reduction_for`/`self_cost_reduction_for` only ever discount a
    *spell's* cast cost, RULE 601.2f, never an activated ability's own
    cost) — logged in docs/implementation-state/ToDo_Backend.md rather
    than guessed at.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 4, "target_kind": "creature"})],
            cost={"text": "{2}{W}, Discard this card"},
            raw_text="Kanalisieren — {2}{W}, Wirf diese Karte ab: Sie fügt einer "
                     "angreifenden oder blockenden Zielkreatur 4 Schaden zu.",
        )
    ]


register("Eiganjo, Seat of the Empire", _eiganjo_seat_of_the_empire)


def _winter_orb() -> list[AbilitySpec]:
    """As long as this artifact is untapped, players can't untap more than
    one land during their untap steps.

    — Winter Orb. A new static family (`continuous.untap_cap_for_lands`,
    `GameEngine._step_untap`), distinct from `no_untap` (which restricts
    one specific *permanent*, not a global per-player cap) and from
    `enters_tapped_static`'s opponent-scoped board-wide family (this is
    unscoped by ownership and gates on the source's own tapped state, not
    a permanent's controller). Auto-picks which land(s) stay tapped (the
    same non-interactive MVP simplification `_sacrifice_candidate`'s
    callers already make elsewhere).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("untap_cap", {"count": 1})],
            raw_text="Solange dieses Artefakt ungetappt ist, können Spieler "
                     "während ihres Enttapp-Schritts nicht mehr als ein Land "
                     "enttappen.",
        )
    ]


register("Winter Orb", _winter_orb)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch B2
# ---------------------------------------------------------------------------


def _temur_sabertooth() -> list[AbilitySpec]:
    """{1}{G}: You may return another creature you control to its owner's
    hand. If you do, this creature gains indestructible until end of turn.

    — Temur Sabertooth. A bespoke effect (`return_creature_grant_
    indestructible`, `game/effects.py`'s `ReturnCreatureGrantIndestructibleEffect`
    — the same "if you do" shape `UnattachTapIndestructibleEffect` (Akiri,
    Fearless Voyager) already uses) since the indestructible grant is
    conditioned on whether the optional return actually happened — an
    "if you do" gate `ConditionalEffect` doesn't cover (only RULE 702.33b's
    "if this spell was kicked" today). ``creature_you_control`` already
    excludes the ability's own source (`targeting.legal_targets`), so it
    reads as "another creature you control" with no extra plumbing.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_creature_grant_indestructible", {})],
            cost={"mana": "{1}{G}"},
            raw_text="{1}{G}: Du kannst eine andere Kreatur, die du "
                     "kontrollierst, auf die Hand ihres Besitzers "
                     "zurückbringen. Falls du dies tust, erhält diese "
                     "Kreatur Unzerstörbarkeit bis zum Ende des Zuges.",
        )
    ]


register("Temur Sabertooth", _temur_sabertooth)


def _helm_of_awakening() -> list[AbilitySpec]:
    """Spells cost {1} less to cast.

    — Helm of Awakening. Unscoped (``affects="all_spells"``, not the
    default ``"your_spells"``) — `continuous.cost_reduction_for` never
    gates ``"all_spells"`` by controller at all (the same shape Thalia,
    Guardian of Thraben's tax uses in reverse), so every player's spells
    get the discount, this permanent's own controller included.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"affects": "all_spells", "generic": 1})],
            raw_text="Zaubersprüche kosten {1} weniger, um gewirkt zu werden.",
        )
    ]


register("Helm of Awakening", _helm_of_awakening)


def _brainstorm() -> list[AbilitySpec]:
    """Draw three cards, then put two cards from your hand on top of your
    library in any order.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 3}),
                EffectSpec("put_hand_cards_on_top", {"count": 2}),
            ],
            raw_text="Ziehe drei Karten, dann lege zwei Karten von deiner "
                     "Hand in beliebiger Reihenfolge oben auf deine "
                     "Bibliothek.",
        )
    ]


register("Brainstorm", _brainstorm)


def _timetwister() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards.

    — Timetwister. `wheel` (`game/effects.py`'s `WheelEffect`) is written
    generically (not Timetwister-specific) since Time Reversal/Echo of
    Eons print the identical line.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("wheel", {"draw_count": 7})],
            raw_text="Jeder Spieler mischt seine Hand und seinen Friedhof "
                     "in seine Bibliothek, dann zieht er sieben Karten.",
        )
    ]


register("Timetwister", _timetwister)


def _damn() -> list[AbilitySpec]:
    """Destroy target creature. A creature destroyed this way can't be
    regenerated.
    Overload {2}{W}{W} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Damn. Overload (RULE 702.96) isn't modeled — no alternative-cost
    mechanism stamps "was this spell cast via its overload cost" anywhere a
    resolving effect can read it back (unlike kicker's `kicker_count`), so
    there's nothing to key a target→each rewrite off of; only the ordinary
    single-target cast is modeled, matching the Sword of Forge and
    Frontier partial-model precedent. ``can_be_regenerated=False`` covers
    "can't be regenerated" exactly.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "creature", "can_be_regenerated": False})],
            raw_text="Zerstöre eine Zielkreatur. Eine auf diese Weise "
                     "zerstörte Kreatur kann nicht regeneriert werden.",
        )
    ]


register("Damn", _damn)


def _power_artifact() -> list[AbilitySpec]:
    """Enchant artifact
    Enchanted artifact's activated abilities cost {2} less to activate.
    This effect can't reduce the mana in that cost to less than one mana.

    — Power Artifact. A new activation-cost-reduction primitive
    (`continuous.activation_cost_reduction_for`/`GameEngine.
    _reduced_activation_mana`) — unlike a spell's cast cost
    (`cost_reduction_for`), nothing in the ordinary activation-cost path
    consulted a reduction before this. ``scope="activation"`` distinguishes
    it from the ordinary spell-cost `cost_reduction` shape sharing the same
    "cost" layer; ``min_total=1`` is the printed floor.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "attached_permanent", "generic": 2,
                "scope": "activation", "min_total": 1,
            })],
            raw_text="Verzaubere ein Artefakt\nAktivierte Fähigkeiten des "
                     "verzauberten Artefakts kosten {2} weniger, um "
                     "aktiviert zu werden. Dieser Effekt kann die Kosten "
                     "nicht auf weniger als ein Mana reduzieren.",
        )
    ]


register("Power Artifact", _power_artifact)


def _seedborn_muse() -> list[AbilitySpec]:
    """Untap all permanents you control during each other player's untap
    step.

    — Seedborn Muse. A new ``"not_you"`` group-trigger controller scope
    (`effect_binder._group_ok`, the mirror image of the existing ``"you"``
    scope) plus a new `TapEffect` ``"permanents_you_control"`` selector
    (`continuous.group_selector_objects` already supported the selector
    itself; only `effects._TAP_SELECTORS`'s whitelist was missing it).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"untap": True, "selector": "permanents_you_control"})],
            trigger={
                "event": EventType.UNTAP,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Enttappe alle Permanente, die du kontrollierst, "
                     "während des Enttapp-Schritts jedes anderen Spielers.",
        )
    ]


register("Seedborn Muse", _seedborn_muse)


def _nether_void() -> list[AbilitySpec]:
    """Whenever a player casts a spell, counter it unless that player pays
    {3}.

    — Nether Void. A plain "group" trigger subject with no ``"controller"``
    filter already matches *any* player's `SPELL_CAST` (the vocabulary's
    unrestricted default); `CounterSpellEffect`'s own ``target_spec``
    (``kind="spell"``) is gathered interactively same as any other
    triggered ability's target — since the triggering spell is pushed onto
    `state.stack` before `SPELL_CAST` fires, it's already a legal option by
    the time the ability asks.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"unless_pays": "{3}"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
            raw_text="Immer wenn ein Spieler einen Zauberspruch wirkt, "
                     "wird dieser gecountert, außer dieser Spieler bezahlt "
                     "{3}.",
        )
    ]


register("Nether Void", _nether_void)


def _spellseeker() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an
    instant or sorcery card with mana value 2 or less, reveal it, put it
    into your hand, then shuffle.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": ["Instant", "Sorcery"], "max_mana_value": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du in "
                     "deiner Bibliothek nach einer Spontanzauber- oder "
                     "Hexereikarte mit Manawert 2 oder weniger suchen, sie "
                     "zeigen, auf deine Hand legen und dann mischen.",
        )
    ]


register("Spellseeker", _spellseeker)


def _windfall() -> list[AbilitySpec]:
    """Each player discards their hand, then draws cards equal to the
    greatest number of cards a player discarded this way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("windfall", {})],
            raw_text="Jeder Spieler wirft seine Hand ab, dann zieht er so "
                     "viele Karten, wie die größte Anzahl an Karten "
                     "beträgt, die ein Spieler auf diese Weise abgeworfen "
                     "hat.",
        )
    ]


register("Windfall", _windfall)


def _ephemerate() -> list[AbilitySpec]:
    """Exile target creature you control, then return it to the
    battlefield under its owner's control.
    Rebound (If you cast this spell from your hand, exile it as it
    resolves. At the beginning of your next upkeep, you may cast this
    card from exile without paying its mana cost.)

    — Ephemerate. Rebound (RULE 702.88b) isn't modeled — every triggered
    ability today is bound once at `GameObject` creation and reused for the
    object's whole lifetime; nothing creates a fresh, one-shot trigger tied
    to one specific future upkeep (RULE 603.7, the same delayed-trigger gap
    Mana Drain/Corpse Dance/Summoner's Pact are already logged as blocked
    on). The blink half is modeled in full (`game/effects.py`'s
    `BlinkEffect`/`RulesEngine.blink`, a new RULE 400.7 "exile then
    immediately return" primitive).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("blink", {"target_kind": "creature_you_control"})],
            raw_text="Exiliere eine Zielkreatur, die du kontrollierst, und "
                     "bringe sie dann unter der Kontrolle ihres Besitzers "
                     "auf das Schlachtfeld zurück.",
        )
    ]


register("Ephemerate", _ephemerate)


def _city_of_traitors() -> list[AbilitySpec]:
    """When you play another land, sacrifice this land.
    {T}: Add {C}{C}.

    — City of Traitors. The mana ability is covered by the engine's mana
    model directly off the printed text (no spec needed, same as Eiganjo,
    Seat of the Empire's own `{T}: Add {W}.`). The sacrifice trigger needed
    a new ``"LAND_PLAYED"`` entry in `effect_binder._GROUP_CONTROLLER_
    EVENT_KEYS` (that event only ever carried ``player_id``) plus a stamped
    ``instance_id`` on the event itself (`GameEngine.play_land`) so the
    ``"other"`` subject-condition flag can exclude this land's own play —
    otherwise a land with no other lands yet in play would immediately
    sacrifice itself the moment it was played.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={
                "event": EventType.LAND_PLAYED,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": True},
            },
            raw_text="Wenn du ein anderes Land spielst, opfere dieses Land.",
        )
    ]


register("City of Traitors", _city_of_traitors)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch B3
# ---------------------------------------------------------------------------


def _elesh_norn_grand_cenobite() -> list[AbilitySpec]:
    """Vigilance. Other creatures you control get +2/+2. Creatures your
    opponents control get -2/-2.

    — Elesh Norn, Grand Cenobite. Vigilance is a keyword, already covered
    by the parser's keyword catalogue. The two-sided anthem is two
    independent ``anthem`` static effects on one card — one scoped
    ``"other_creatures_you_control"`` (the existing lord vocabulary), the
    other reusing `group_selector_objects`'s ``"opponents_permanents"``
    selector (built for Manglehorn's "Artifacts your opponents control
    enter tapped.") narrowed to creatures via the shared ``card_type``
    selector param — no new engine surface needed for either half.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_creatures_you_control", "power": 2, "toughness": 2,
                }),
                EffectSpec("anthem", {
                    "affects": "opponents_permanents", "card_type": "creature",
                    "power": -2, "toughness": -2,
                }),
            ],
            raw_text="Wachsamkeit. Andere Kreaturen, die du kontrollierst, "
                     "erhalten +2/+2. Kreaturen, die deine Gegner kontrollieren, "
                     "erhalten -2/-2.",
        )
    ]


register("Elesh Norn, Grand Cenobite", _elesh_norn_grand_cenobite)


def _beast_within() -> list[AbilitySpec]:
    """Destroy target permanent. Its controller creates a 3/3 green Beast
    creature token.

    — Beast Within. A new `destroy_create_token` effect this batch —
    `ExileCreateTokenEffect`'s destroy-instead-of-exile sibling.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_create_token", {
                "target_kind": "permanent",
                "power": 3, "toughness": 3, "colors": ["G"], "subtypes": ["Beast"],
            })],
            raw_text="Zerstöre eine Zielkarte eines bleibenden Kartentyps. Ihr "
                     "Beherrscher erschafft einen grünen 3/3-Bestien-"
                     "Kreaturenspielstein.",
        )
    ]


register("Beast Within", _beast_within)


def _natures_claim() -> list[AbilitySpec]:
    """Destroy target artifact or enchantment. Its controller gains 4 life.

    — Nature's Claim. A new `destroy_gain_life_to_controller` effect this
    batch — a fixed-amount sibling of `ExileGainLifeToControllerEffect`
    (Swords to Plowshares' "equal to its power" life total doesn't apply
    here). ``target_kind="permanent"`` (broader than "artifact or
    enchantment") mirrors `DestroyLoseLifeEqualManaValueEffect`'s own
    documented simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_gain_life_to_controller", {
                "target_kind": "permanent", "amount": 4,
            })],
            raw_text="Zerstöre eine Zielartefakt- oder Zielverzauberungskarte. "
                     "Ihr Beherrscher gewinnt 4 Lebenspunkte hinzu.",
        )
    ]


register("Nature's Claim", _natures_claim)


def _toxic_deluge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, pay X life.
    All creatures get -X/-X until end of turn.

    — Toxic Deluge. X here comes entirely from the announced additional-
    cost life payment (RULE 601.2b), not a mana ``{X}`` — `RulesEngine.
    cast_spell`/`GameEngine._pay_additional_cast_cost` already thread a
    caller-supplied ``x`` through ``additional_cost={"pay_life": "x"}``
    regardless of whether the printed mana cost itself has a variable
    symbol. `RulesEngine._substitute_x` was extended this batch to also
    rewrite a `pump` effect's own ``power``/``toughness`` fields (not just
    ``amount``/``count``), including a new ``"-x"`` sentinel for an
    X-scaled *debuff* whose X isn't itself negative.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pump", {"power": "-x", "toughness": "-x", "selector": "all_creatures"})],
            additional_cost={"pay_life": "x"},
            raw_text="Bezahle als zusätzliche Kosten für diesen Zauberspruch X "
                     "Lebenspunkte. Alle Kreaturen erhalten bis zum Ende des "
                     "Zuges -X/-X.",
        )
    ]


register("Toxic Deluge", _toxic_deluge)


def _goblin_recruiter() -> list[AbilitySpec]:
    """When this creature enters, search your library for any number of
    Goblin cards, reveal them, then shuffle and put those cards on top in
    any order.

    — Goblin Recruiter. The generic search grammar's "up to N" choice loop
    already lets a player decline at any point, and `RulesEngine._finish_
    search` already shuffles first and then places each chosen card at the
    library's top one at a time (the *last* one chosen ends up on top —
    full order control, just reversed-order picking, matching "in any
    order"). "Any number" is modeled as a generous fixed cap (99, far above
    any real deck's Goblin count) rather than a genuinely open-ended count —
    the same "big enough constant" idiom no real deck can actually reach
    the edge of.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Goblin"}, "destination": "library_top", "count": 99,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, suche in deiner "
                     "Bibliothek nach einer beliebigen Anzahl Goblinkarten, "
                     "zeige sie offen vor, mische danach und lege diese Karten "
                     "in beliebiger Reihenfolge oben auf deine Bibliothek.",
        )
    ]


register("Goblin Recruiter", _goblin_recruiter)


def _archivist_of_oghma() -> list[AbilitySpec]:
    """Flash. Whenever an opponent searches their library, you gain 1 life
    and draw a card.

    — Archivist of Oghma. Flash is a keyword, already covered by the
    parser's keyword catalogue. `RulesEngine.request_search` already fires
    ``EventType.LIBRARY_SEARCHED`` (``player_id``-keyed) for every search,
    real or fizzled (no eligible cards) — this batch added it to
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` so the existing "group" +
    ``controller: "not_you"`` trigger-subject scope (built for Seedborn
    Muse) applies here too.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.LIBRARY_SEARCHED,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Blitzschlag. Immer wenn ein Gegner seine Bibliothek "
                     "durchsucht, gewinnst du 1 Lebenspunkt hinzu und ziehst "
                     "eine Karte.",
        )
    ]


register("Archivist of Oghma", _archivist_of_oghma)


def _leonin_relic_warder() -> list[AbilitySpec]:
    """When this creature enters, you may exile target artifact or
    enchantment. When this creature leaves the battlefield, return the
    exiled card to the battlefield under its owner's control.

    — Leonin Relic-Warder. A new O-Ring-shaped linkage primitive this
    batch: `ExileEffect(remember=True)` stamps the exiled card's own
    ``instance_id`` onto this creature's `GameObject.linked_exile_id`
    (survives however long it stays exiled, arbitrarily many turns);
    `ReturnLinkedExileEffect`, on this creature's own leaves-battlefield
    trigger, reads it back and returns that exact card, clearing the link.
    ``target_kind="permanent"`` (broader than "artifact or enchantment" —
    no target kind unions two card types) is the same documented
    `_TARGET_ROWS` simplification several other catalogue entries use.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "permanent", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du eine "
                     "Zielartefakt- oder Zielverzauberungskarte exilieren.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, bringe die "
                     "exilierte Karte unter der Kontrolle ihres Besitzers auf "
                     "das Schlachtfeld zurück.",
        ),
    ]


register("Leonin Relic-Warder", _leonin_relic_warder)


def _dockside_extortionist() -> list[AbilitySpec]:
    """When this creature enters, create X Treasure tokens, where X is the
    number of artifacts and enchantments your opponents control.

    — Dockside Extortionist. A new opponents-scoped `continuous.
    count_selector` entry this batch (``artifacts_and_or_enchantments_
    opponents_control``, the mirror image of the existing "you control"
    one) plus a new `CreateTokenEffect.count_selector` param reading it
    live at resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure",
                "count_selector": "artifacts_and_or_enchantments_opponents_control",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, erschaffe X Schatz-"
                     "Spielsteine, wobei X die Anzahl der Artefakte und "
                     "Verzauberungen ist, die deine Gegner kontrollieren.",
        )
    ]


register("Dockside Extortionist", _dockside_extortionist)


def _zealous_conscripts() -> list[AbilitySpec]:
    """Haste. When this creature enters, gain control of target permanent
    until end of turn. Untap that permanent. It gains haste until end of
    turn.

    — Zealous Conscripts. Haste is a keyword, already covered by the
    parser's keyword catalogue. The ETB is a new atomic
    `GainControlUntilEndOfTurnEffect` this batch — control change, untap,
    and the target's own "gains haste" all bundled into one effect over one
    shared target (no existing "gain control until end of turn" primitive
    existed before this batch; confirmed via `game/effects.py` before
    building it — a temporary control change is a materially different,
    simpler shape than Gilded Drake's still-missing *permanent exchange*).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Hast. Wenn diese Kreatur ins Spiel kommt, erlange bis "
                     "zum Ende des Zuges die Kontrolle über eine Zielkarte "
                     "eines bleibenden Kartentyps. Enttappe diese Karte. Sie "
                     "erhält bis zum Ende des Zuges Hast.",
        ),
    ]


register("Zealous Conscripts", _zealous_conscripts)


def _coercive_recruiter() -> list[AbilitySpec]:
    """Whenever this creature or another Pirate you control enters, gain
    control of target creature until end of turn. Untap that creature.
    Until end of turn, it gains haste and becomes a Pirate in addition to
    its other types.

    — Coercive Recruiter. Simplified in two ways, documented rather than
    guessed at: the trigger only fires on this creature's *own* entry
    (dropping "or another Pirate you control enters" — `GameObject.
    type_words`, the only vocabulary a "group" trigger subject's ``type``
    filter reads, is main card types only, never subtypes, so "Pirate"
    can't be recognized there without a new subtype-aware ENTERS_
    BATTLEFIELD trigger scope, out of this batch's size); and the granted
    "...becomes a Pirate in addition to its other types" tail is dropped
    (no layer-6 temporary-type-grant-on-a-temporarily-controlled-permanent
    primitive exists). Both per the Sword of Forge and Frontier precedent
    (a genuinely partial model, documented, rather than skipping the whole
    card) — the control-change/untap/haste half is the same
    `GainControlUntilEndOfTurnEffect` Zealous Conscripts uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {"target_kind": "creature"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, erlange bis zum Ende "
                     "des Zuges die Kontrolle über eine Zielkreatur. Enttappe "
                     "diese Kreatur. Sie erhält bis zum Ende des Zuges Hast.",
        ),
    ]


register("Coercive Recruiter", _coercive_recruiter)


def _spirit_of_the_labyrinth() -> list[AbilitySpec]:
    """Each player can't draw more than one card each turn.

    — Spirit of the Labyrinth. A new `draw_limit` static layer this batch,
    the draw-side mirror of the existing `cast_limit` family (Eidolon of
    Rhetoric/Rule of Law/Archon of Emeria) — `RulesEngine._single_draw`
    consults `continuous.max_draws_per_turn` against a new per-player
    `GameState.cards_drawn_this_turn` counter before each individual draw,
    the same "flat global cap, most restrictive wins" shape.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 1})],
            raw_text="Jeder Spieler kann nicht mehr als eine Karte pro Zug "
                     "ziehen.",
        )
    ]


register("Spirit of the Labyrinth", _spirit_of_the_labyrinth)


def _snap() -> list[AbilitySpec]:
    """Return target creature to its owner's hand. Untap up to two lands.

    — Snap. Two independent targeting effects on one spell (RULE 115.1a) —
    the bounce and the "up to two" land untap — resolved via `StackItem.
    target_groups` (2026-07-16's generalization, previously only exercised
    for a triggered ability's own auto-gathered per-effect target; a caller
    must supply ``target_groups`` explicitly for a spell). `TapEffect`
    gained a ``count`` param this batch (RULE 115.1a's N>=2 generalization,
    mirroring `DestroyEffect.count`) for the "up to two" half.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "creature"}),
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "untap": True,
                    "optional": True, "count": 2,
                }),
            ],
            raw_text="Bringe eine Zielkreatur auf die Hand ihres Besitzers "
                     "zurück. Enttappe bis zu zwei Länder.",
        )
    ]


register("Snap", _snap)


def _ponder() -> list[AbilitySpec]:
    """Look at the top three cards of your library, then put them back in
    any order. You may shuffle. Draw a card.

    — Ponder. Reuses the existing non-interactive `scry` resolution exactly
    as `RulesEngine.scry` already documents it (a goldfish/solo session has
    no chooser, so it deterministically keeps every looked-at card on top
    in its existing order) — "put them back in any order" and "you may
    shuffle" both have "leave everything exactly as it is" among their
    legal outcomes, so ``scry(3)`` already resolves Ponder correctly at
    this engine's fidelity; a literal "always shuffle" would be a
    *different*, wrong resolution (shuffling is optional, not automatic).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scry", {"count": 3}), EffectSpec("draw", {"count": 1})],
            raw_text="Schau dir die obersten drei Karten deiner Bibliothek "
                     "an, lege sie dann in beliebiger Reihenfolge zurück. Du "
                     "kannst mischen. Ziehe eine Karte.",
        )
    ]


register("Ponder", _ponder)


def _mirrormade() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any artifact or
    enchantment on the battlefield.

    — Mirrormade. The same `enter_as_copy` replacement mechanism Phyrexian
    Metamorph/Clever Impersonator use; ``target_kind="permanent"`` is the
    same documented "no type-union target kind" simplification those
    entries already use (admits a creature/land/planeswalker pick too,
    never correct oracle-text-wise but not currently prevented).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
            raw_text="Du kannst diese Verzauberung als Kopie eines beliebigen "
                     "Artefakts oder einer beliebigen Verzauberung auf dem "
                     "Schlachtfeld ins Spiel kommen lassen.",
        )
    ]


register("Mirrormade", _mirrormade)


def _geistwave() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card.

    — Geistwave. A new atomic `ReturnToHandDrawIfControlledEffect` this
    batch — the target's controller has to be read *before*
    `ReturnToHandEffect` would move it, the same reason
    `ExileGainLifeToControllerEffect` is one atomic effect rather than two
    composed ones.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand_draw_if_controlled", {"target_kind": "nonland_permanent"})],
            raw_text="Bringe eine nichtländliche Zielkarte eines bleibenden "
                     "Kartentyps auf die Hand ihres Besitzers zurück. Falls du "
                     "diese Karte kontrolliert hast, ziehe eine Karte.",
        )
    ]


register("Geistwave", _geistwave)


def _paradigm_shift() -> list[AbilitySpec]:
    """Exile all cards from your library. Then shuffle your graveyard into
    your library.

    — Paradigm Shift. Two new, generically reusable effects this batch:
    `ExileLibraryEffect` (an untargeted hidden-zone-to-exile mass move,
    distinct from `ExileEffect.selector`'s battlefield-only board-wipe
    vocabulary) and `ShuffleGraveyardIntoLibraryEffect` (the graveyard-only
    sibling of `RulesEngine.shuffle_hand_and_graveyard_into_library`'s
    "hand AND graveyard" wheel template).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_library", {}), EffectSpec("shuffle_graveyard_into_library", {})],
            raw_text="Exiliere alle Karten aus deiner Bibliothek. Mische dann "
                     "deinen Friedhof in deine Bibliothek.",
        )
    ]


register("Paradigm Shift", _paradigm_shift)


def _endurance() -> list[AbilitySpec]:
    """Flash. Reach. When this creature enters, up to one target player
    puts all the cards from their graveyard on the bottom of their library
    in a random order. Evoke—Exile a green card from your hand.

    — Endurance. Flash/Reach are keywords, already covered by the parser's
    keyword catalogue. A new `GraveyardToLibraryBottomRandomEffect` this
    batch (RULE 701.20-adjacent — randomizes only the moved batch's own
    relative order, leaving the rest of the library's order alone). Evoke
    isn't modeled — no alternative-cast-cost mechanism exists for it,
    unlike Kicker/Buyback which `GameEngine.cast_spell` already threads —
    dropped per the Sword of Forge and Frontier precedent; the card is only
    hard-castable for its full mana cost, but its ETB fully functions
    either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("graveyard_to_library_bottom_random", {
                "target_kind": "player", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Blitzschlag. Reichweite. Wenn diese Kreatur ins Spiel "
                     "kommt, legt bis zu ein Zielspieler alle Karten aus "
                     "seinem Friedhof in zufälliger Reihenfolge unter seine "
                     "Bibliothek.",
        )
    ]


register("Endurance", _endurance)


def _borne_upon_a_wind() -> list[AbilitySpec]:
    """You may cast spells this turn as though they had flash. Draw a card.

    — Borne Upon a Wind. A new `GrantFlashUntilEndOfTurnEffect` this batch:
    stamps `GameState.temp_flash_until_turn` for the caster, consulted by
    `GameEngine.can_cast`'s existing RULE 702.8b Flash timing gate
    alongside the printed-keyword/`conditional_flash` checks it already
    made.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_flash_until_eot", {}), EffectSpec("draw", {"count": 1})],
            raw_text="Du kannst in diesem Zug Zaubersprüche wirken, als "
                     "hätten sie Blitzschlag. Ziehe eine Karte.",
        )
    ]


register("Borne Upon a Wind", _borne_upon_a_wind)


# ---------------------------------------------------------------------------
# Batch 14 — "destroy/counter target X; its controller creates a token"
# cluster and further cube singles whose effect primitives already exist.
# ---------------------------------------------------------------------------


def _pongify() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    creates a 3/3 green Ape creature token.

    — Pongify. Reuses `destroy_create_token` (Beast Within), with
    ``can_be_regenerated=False`` for the "can't be regenerated" clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_create_token", {
                "target_kind": "creature",
                "power": 3, "toughness": 3, "colors": ["G"], "subtypes": ["Ape"],
                "can_be_regenerated": False,
            })],
            raw_text="Zerstöre eine Zielkreatur. Sie kann nicht regeneriert "
                     "werden. Ihr Beherrscher erschafft einen grünen 3/3-Affen-"
                     "Kreaturenspielstein.",
        )
    ]


register("Pongify", _pongify)


def _rapid_hybridization() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. That creature's
    controller creates a 3/3 green Frog Lizard creature token.

    — Rapid Hybridization. Pongify's blue sibling (`destroy_create_token`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_create_token", {
                "target_kind": "creature",
                "power": 3, "toughness": 3, "colors": ["G"],
                "subtypes": ["Frog", "Lizard"], "token_name": "Frog Lizard",
                "can_be_regenerated": False,
            })],
            raw_text="Zerstöre eine Zielkreatur. Sie kann nicht regeneriert "
                     "werden. Der Beherrscher jener Kreatur erschafft einen "
                     "grünen 3/3-Frosch-Echsen-Kreaturenspielstein.",
        )
    ]


register("Rapid Hybridization", _rapid_hybridization)


def _swan_song() -> list[AbilitySpec]:
    """Counter target enchantment, instant, or sorcery spell. Its controller
    creates a 2/2 blue Bird creature token with flying.

    — Swan Song. A new `counter_create_token` effect this batch — the
    stack-side sibling of `destroy_create_token`: the token goes to the
    countered spell's own controller.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "card_types": ["enchantment", "instant", "sorcery"],
                "power": 2, "toughness": 2, "colors": ["U"],
                "subtypes": ["Bird"], "keywords": ["flying"],
            })],
            raw_text="Neutralisiere eine Zielverzauberung, einen Zielspontan- "
                     "oder Zielhexereizauber. Ihr Beherrscher erschafft einen "
                     "blauen 2/2-Vogel-Kreaturenspielstein mit Fliegend.",
        )
    ]


register("Swan Song", _swan_song)


def _strix_serenade() -> list[AbilitySpec]:
    """Counter target artifact, creature, or planeswalker spell. Its
    controller creates a 2/2 blue Bird creature token with flying.

    — Strix Serenade. Swan Song's mirror over the other card-type triplet
    (`counter_create_token`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "card_types": ["artifact", "creature", "planeswalker"],
                "power": 2, "toughness": 2, "colors": ["U"],
                "subtypes": ["Bird"], "keywords": ["flying"],
            })],
            raw_text="Neutralisiere einen Zielartefakt-, Zielkreatur- oder "
                     "Zielplaneswalker-Zauber. Sein Beherrscher erschafft einen "
                     "blauen 2/2-Vogel-Kreaturenspielstein mit Fliegend.",
        )
    ]


register("Strix Serenade", _strix_serenade)


def _an_offer_you_cant_refuse() -> list[AbilitySpec]:
    """Counter target noncreature spell. Its controller creates two Treasure
    tokens.

    — An Offer You Can't Refuse (`counter_create_token`, ``noncreature`` +
    ``count=2``). The Treasure tokens are created as artifact tokens named
    "Treasure"; their own "sacrifice for mana" ability isn't bound (no
    generic Treasure-behaviour primitive yet) — the token exists on the
    board but can't yet be cracked for mana.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_create_token", {
                "noncreature": True, "count": 2,
                "subtypes": ["Treasure"], "token_name": "Treasure",
            })],
            raw_text="Neutralisiere einen Ziel-Nichtkreaturenzauber. Sein "
                     "Beherrscher erschafft zwei Schatz-Spielsteine.",
        )
    ]


register("An Offer You Can't Refuse", _an_offer_you_cant_refuse)


def _path_to_exile() -> list[AbilitySpec]:
    """Exile target creature. Its controller may search their library for a
    basic land card, put that card onto the battlefield tapped, then shuffle.

    — Path to Exile. Reuses `exile_controller_searches_basic_land` (the same
    "exile + the target's controller ramps a tapped basic" primitive Swords
    to Plowshares' sibling family established).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_controller_searches_basic_land", {
                "target_kind": "creature",
            })],
            raw_text="Schicke eine Zielkreatur ins Exil. Ihr Beherrscher kann "
                     "seine Bibliothek nach einer Standardlandkarte durchsuchen, "
                     "sie getappt ins Spiel bringen und dann mischen.",
        )
    ]


register("Path to Exile", _path_to_exile)


def _cyclonic_rift() -> list[AbilitySpec]:
    """Return target nonland permanent you don't control to its owner's hand.
    (Overload {6}{U} — not modeled.)

    — Cyclonic Rift. The base (non-overload) mode via `return_to_hand` with
    the new ``nonland_permanent_you_dont_control`` target kind. Overload
    (RULE 702.96 — an alternative cost that rewrites "target" to "each") has
    no parser/engine support yet, so only the single-target mode is offered;
    documented drop per the Sword-of-Forge-and-Frontier partial precedent.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_dont_control",
            })],
            raw_text="Bringe eine bleibende Nichtland-Zielkarte, die du nicht "
                     "kontrollierst, auf die Hand ihres Besitzers zurück.",
        )
    ]


register("Cyclonic Rift", _cyclonic_rift)


def _alchemists_retrieval() -> list[AbilitySpec]:
    """Return target nonland permanent [you control] to its owner's hand.
    (Cleave {1}{U} — not modeled.)

    — Alchemist's Retrieval. The base (non-cleave) mode via `return_to_hand`
    with ``nonland_permanent_you_control``. Cleave (RULE 702.150 — an
    alternative cost that removes the bracketed words, here broadening the
    target to any nonland permanent) has no parser/engine support yet;
    documented drop.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_control",
            })],
            raw_text="Bringe eine bleibende Nichtland-Zielkarte, die du "
                     "kontrollierst, auf die Hand ihres Besitzers zurück.",
        )
    ]


register("Alchemist's Retrieval", _alchemists_retrieval)


def _copy_enchantment() -> list[AbilitySpec]:
    """You may have this enchantment enter as a copy of any enchantment on the
    battlefield.

    — Copy Enchantment. Same `enter_as_copy` mechanism as Clever Impersonator
    (see its docstring), narrowed to ``target_kind="enchantment"`` (the new
    single-type target kind).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "enchantment"})],
            raw_text="Du kannst diese Verzauberung als Kopie einer beliebigen "
                     "Verzauberung im Spiel ins Spiel kommen lassen.",
        )
    ]


register("Copy Enchantment", _copy_enchantment)


def _gitaxian_probe() -> list[AbilitySpec]:
    """Look at target player's hand. Draw a card.

    — Gitaxian Probe. The "look at target player's hand" clause is pure
    information (no game-state change) and, in a full-information goldfish/
    replay session, a no-op — so only the "draw a card" cantrip half is
    bound; documented drop of the reveal clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {"count": 1})],
            raw_text="Sieh dir die Hand eines Zielspielers an. Ziehe eine Karte.",
        )
    ]


register("Gitaxian Probe", _gitaxian_probe)


def _reanimate() -> list[AbilitySpec]:
    """Put target creature card from a graveyard onto the battlefield under
    your control. You lose life equal to that creature's mana value.

    — Reanimate. `return_from_graveyard` with ``under_your_control`` (the
    Reanimate shape) plus the new ``lose_life_equal_mv`` rider, which reads
    the returned creature's mana value and makes the caster lose that much
    life.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_creature",
                "destination": "battlefield",
                "under_your_control": True,
                "lose_life_equal_mv": True,
            })],
            raw_text="Bringe eine Zielkreaturenkarte aus einem Friedhof unter "
                     "deiner Kontrolle ins Spiel. Du verlierst so viele "
                     "Lebenspunkte, wie ihr Manawert beträgt.",
        )
    ]


register("Reanimate", _reanimate)


def _noxious_revival() -> list[AbilitySpec]:
    """Put target card from a graveyard on top of its owner's library.

    — Noxious Revival. `return_from_graveyard` with the new ``library_top``
    destination (the card goes to its *owner's* library top, the engine
    default when no controller override is given).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_card",
                "destination": "library_top",
            })],
            raw_text="Lege eine Zielkarte aus einem Friedhof oben auf die "
                     "Bibliothek ihres Besitzers.",
        )
    ]


register("Noxious Revival", _noxious_revival)


def _dramatic_reversal() -> list[AbilitySpec]:
    """Untap all nonland permanents you control.

    — Dramatic Reversal. `TapEffect` in its untargeted mass-untap mode via
    the new ``nonland_permanents_you_control`` group selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("tap", {
                "untap": True, "selector": "nonland_permanents_you_control",
            })],
            raw_text="Enttappe alle bleibenden Nichtland-Karten, die du "
                     "kontrollierst.",
        )
    ]


register("Dramatic Reversal", _dramatic_reversal)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 15 (new core primitive: EventType.SACRIFICE)
# ---------------------------------------------------------------------------


def _mayhem_devil() -> list[AbilitySpec]:
    """Whenever a player sacrifices a permanent, Mayhem Devil deals 1 damage
    to any target.

    — Mayhem Devil. First consumer of the new `EventType.SACRIFICE`
    occurrence (RULE 701.17), fired by `RulesEngine._move_to_graveyard` for
    every `put_into_graveyard` sacrifice in addition to DIES/LEAVES. The
    trigger carries no subject condition — "a player" means *any* player's
    sacrifice, and SACRIFICE only ever fires for a permanent being
    sacrificed, so a bare trigger matches exactly the intended events. The
    1-damage effect targets "any target" (RULE 115.4), gathered
    interactively at resolution like any other targeted trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
            trigger={"event": EventType.SACRIFICE},
            raw_text="Immer wenn ein Spieler eine bleibende Karte opfert, fügt "
                     "Mayhem Devil einem beliebigen Ziel 1 Schadenspunkt zu.",
        )
    ]


register("Mayhem Devil", _mayhem_devil)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 17 (new core primitive: spell-copy, RULE 707.10)
# ---------------------------------------------------------------------------


def _dualcaster_mage() -> list[AbilitySpec]:
    """Flash. When Dualcaster Mage enters, copy target instant or sorcery
    spell. You may choose new targets for the copy.

    — Dualcaster Mage. Flash is a keyword (folded in by `specs_for`'s RULE
    702 keyword catalogue, so it isn't authored here). The ETB trigger is
    the first consumer of the new `copy_spell` effect (`RulesEngine.
    copy_spell`, RULE 707.10): it targets an instant/sorcery spell on the
    stack and puts a copy above it. "You may choose new targets" is the
    effect's documented MVP simplification (keeps the original's targets —
    always legal, RULE 707.10c).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Dualcaster Mage ins Spiel kommt, kopiere einen "
                     "Ziel-Spontanzauber oder eine Ziel-Hexerei.",
        )
    ]


register("Dualcaster Mage", _dualcaster_mage)


def _flare_of_duplication() -> list[AbilitySpec]:
    """You may sacrifice a nontoken red creature rather than pay this spell's
    mana cost. Copy target instant or sorcery spell. You may choose new
    targets for the copy.

    — Flare of Duplication. The copy effect is the `copy_spell` primitive.
    **Deliberately dropped**: the optional "sacrifice a nontoken red creature
    rather than pay this spell's mana cost" *alternative* casting cost (RULE
    118.9 — an alt-cost, the Force-of-Will/pitch family the engine doesn't
    model yet). Dropping it leaves the card fully playable at its normal mana
    cost, only without the optional discount — the same
    partial-model-with-explicit-drop precedent as Batch 14's Cyclonic Rift
    (Overload) and Gitaxian Probe (reveal).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            raw_text="Kopiere einen Ziel-Spontanzauber oder eine Ziel-Hexerei.",
        )
    ]


register("Flare of Duplication", _flare_of_duplication)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 20 (new core primitive: the "tapped for mana"
# event, RULE 605.1 — `EventType.TAPPED_FOR_MANA`)
# ---------------------------------------------------------------------------


def _price_of_glory() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, if it's not that player's
    turn, destroy that land.

    — Price of Glory. First consumer of the new `EventType.TAPPED_FOR_MANA`
    occurrence (`GameEngine.tap_for_mana`, RULE 605.1). Three primitives
    compose here, no bespoke code: the ``"group"`` subject scopes it to a
    *land* being tapped (`condition.type == "land"`, any player — no
    ``controller`` scoping); ``not_controllers_turn`` is the RULE 603.4
    intervening-if ("if it's not that player's turn", checked against the
    live active player, `effect_binder._trigger_condition`); and
    ``reflexive`` bakes in *that* land as the destroy target from the
    event's ``instance_id`` (RULE 603.3d, batch 16) — no target choice, and
    the trigger drops if the land somehow already left. Destroying a land is
    an ordinary stack trigger (not a mana ability), so normal resolution is
    correct.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": "land"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
                "not_controllers_turn": True,
                "reflexive": True,
            },
            raw_text="Immer wenn ein Spieler ein Land für Mana tappt und es nicht "
                     "der Zug dieses Spielers ist, zerstöre jenes Land.",
        )
    ]


register("Price of Glory", _price_of_glory)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 19 (new core primitive: divided damage,
# RULE 601.2d — `DealDamageEffect(divided=True)`)
# ---------------------------------------------------------------------------


def _shatterskull_smashing() -> list[AbilitySpec]:
    """Shatterskull Smashing deals X damage divided as you choose among up to
    two target creatures and/or planeswalkers. If X is 6 or more, it deals
    twice X divided among them instead.

    — Shatterskull Smashing (the sorcery *front* face of the MDFC; its back is
    the land Shatterskull, the Hammer Pass, so the spell casts as an ordinary
    {X}{R}{R} sorcery — no modal-DFC machinery needed for this face). First
    consumer of the `divided` damage primitive: the announced {X} pool is
    split across the chosen targets (``divided`` + ``count`` 2 ``optional``),
    doubling at ``double_at=6`` (RULE 107.3). **Documented simplifications**:
    the "and/or planeswalkers" half of the target set is dropped (``creature``
    only — planeswalker damage targeting), and the "as you choose" split
    defaults to an even distribution (`DealDamageEffect._apply_divided`) — the
    total dealt and which creatures take it are exact; only the freedom to
    lump it unevenly is auto-made.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature", "count": 2,
                "optional": True, "divided": True, "double_at": 6,
            })],
            raw_text="Shatterskull Smashing fügt X Schadenspunkte zu, nach Wahl "
                     "des Spielers aufgeteilt auf bis zu zwei Ziel-Kreaturen. Ist "
                     "X gleich 6 oder mehr, fügt es stattdessen zweimal X zu.",
        )
    ]


register("Shatterskull Smashing", _shatterskull_smashing)


def _fire_covenant() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, pay X life. Fire Covenant
    deals X damage divided as you choose among any number of target creatures.

    — Fire Covenant. Combines the `divided` damage primitive with the same
    ``additional_cost={"pay_life": "x"}`` X-from-life shape as Toxic Deluge
    (RULE 601.2b — X is defined by the announced life payment, not a mana
    {X}, and threaded into the ``"x"`` amount by `RulesEngine._substitute_x`).
    "Any number of target creatures" is capped at ``count`` 10 for target
    offering (a UI cap — a real board never has X-1's worth of relevant
    creatures beyond that); the even-split "as you choose" simplification is
    the same as Shatterskull's.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature", "count": 10,
                "optional": True, "divided": True,
            })],
            additional_cost={"pay_life": "x"},
            raw_text="Bezahle als zusätzliche Kosten für diesen Zauberspruch X "
                     "Lebenspunkte. Fire Covenant fügt X Schadenspunkte zu, nach "
                     "Wahl aufgeteilt auf eine beliebige Anzahl Ziel-Kreaturen.",
        )
    ]


register("Fire Covenant", _fire_covenant)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 18 (new core primitive: extra turns,
# RULE 500.7 — `GameState.extra_turns` + `take_extra_turn` effect,
# consumed by `GameEngine.begin_turn`)
# ---------------------------------------------------------------------------


def _final_fortune() -> list[AbilitySpec]:
    """Take an extra turn after this one. At the beginning of that turn's end
    step, you lose the game.

    — Final Fortune. First consumer of the extra-turn primitive (`take_extra_
    turn` → `GameState.extra_turns`, RULE 500.7). The downside reuses the
    batch-22 delayed-trigger primitive: a `lose_game` armed for the
    controller's *end* step, with ``min_turn_offset`` 1 so it fires at *that*
    (extra) turn's end step — not the current turn's, which would otherwise be
    the very next end step to begin. The extra turn is queued first, then the
    delayed loss armed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("take_extra_turn", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "min_turn_offset": 1,
                    "effects": [{"type": "lose_game", "params": {"reason": "final_fortune"}}],
                }),
            ],
            raw_text="Mache einen zusätzlichen Zug nach diesem. Zu Beginn des "
                     "Endsegments jenes Zuges verlierst du das Spiel.",
        )
    ]


register("Final Fortune", _final_fortune)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 23 (new core primitive: granted protection,
# RULE 702.16 — `GameObject.temp_protections` read by `combat.is_protected_
# from`, granted via the interactive `grant_protection` effect)
# ---------------------------------------------------------------------------


def _mother_of_runes() -> list[AbilitySpec]:
    """{T}: Target creature you control gains protection from the color of
    your choice until end of turn.

    — Mother of Runes. First consumer of the granted-protection primitive: the
    `grant_protection` effect opens an interactive colour pick
    (`RulesEngine.grant_protection_choice`) and stashes the chosen quality in
    the target's ``temp_protections``, which `combat.is_protected_from` now
    reads alongside printed text (cleared at cleanup, RULE 514.2).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_protection", {"target_kind": "creature_you_control"})],
            cost={"taps_self": True},
            raw_text="{T}: Eine Zielkreatur, die du kontrollierst, erhält bis zum "
                     "Ende des Zuges Schutz vor der Farbe deiner Wahl.",
        )
    ]


register("Mother of Runes", _mother_of_runes)


def _giver_of_runes() -> list[AbilitySpec]:
    """{T}: Another target creature you control gains protection from
    colorless or from the color of your choice until end of turn.

    — Giver of Runes. Same primitive as Mother of Runes, with Giver's extra
    "colorless" option (``allow_colorless``). **Documented simplification**:
    the "*another*" restriction (Giver can't target itself) is dropped — no
    "other creature you control" target kind exists yet, so it's modeled as
    the plain "creature you control" Mother uses; the only lost fidelity is
    that Giver could illegally target itself, which a real player never wants.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_protection", {
                "target_kind": "creature_you_control", "allow_colorless": True,
            })],
            cost={"taps_self": True},
            raw_text="{T}: Eine andere Zielkreatur, die du kontrollierst, erhält "
                     "bis zum Ende des Zuges Schutz vor Farblos oder vor der Farbe "
                     "deiner Wahl.",
        )
    ]


register("Giver of Runes", _giver_of_runes)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 24 (new core primitive: board-wide ability strip,
# layer 6 — `remove_all_abilities` static → `GameObject.loses_all_abilities`)
# ---------------------------------------------------------------------------


def _humility() -> list[AbilitySpec]:
    """All creatures lose all abilities and have base power and toughness 1/1.

    — Humility. First consumer of the ability-strip primitive: a layer-6
    `remove_all_abilities` static (RULE 613.7f — every creature's keywords via
    `combat._obj_keywords`, its triggered/activated abilities gated at
    fire/activate time) plus a layer-7b `pt_set` to base 1/1. Two static
    abilities on one card, both scoped to ``all_creatures`` (Humility is itself
    a non-creature enchantment, so it isn't self-affected).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("remove_all_abilities", {"affects": "all_creatures"})],
            raw_text="Alle Kreaturen verlieren alle Fähigkeiten.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("pt_set", {"power": 1, "toughness": 1, "affects": "all_creatures"})],
            raw_text="Alle Kreaturen haben Grundstärke und -widerstandskraft 1/1.",
        ),
    ]


register("Humility", _humility)
