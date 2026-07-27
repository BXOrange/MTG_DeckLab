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
    - ``{"kind": "optional_bonus_rad", "amount": N}`` — the mirror image
      (Mariposa Military Base): untapped by default, with the controller
      able to choose tapped instead for ``N`` rad counters.
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
    """If a creature you control would deal damage to a permanent or
    player, it deals double that damage to that permanent or player
    instead.

    — Gratuitous Violence. `double_damage` scoped to ``creature_only`` +
    ``your_sources_only`` — narrower than Furnace of Rath's unscoped
    version (a non-creature source you control, e.g. a burn spell or an
    artifact, is untouched), but *not* combat-restricted despite the name —
    the real printed text has no "combat" qualifier at all, unlike what an
    earlier version of this entry assumed.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"creature_only": True, "your_sources_only": True})],
            raw_text="Falls eine Kreatur, die du kontrollierst, einer bleibenden Karte "
                     "oder einem Spieler Schaden zufügen würde, fügt sie stattdessen "
                     "doppelt so viel Schaden zu.",
        )
    ]


register("Gratuitous Violence", _gratuitous_violence)


def _fiery_emancipation() -> list[AbilitySpec]:
    """If a source you control would deal damage to a permanent or player,
    it deals triple that damage to that permanent or player instead.

    — Fiery Emancipation. `double_damage` with ``multiplier=3`` +
    ``your_sources_only`` — the RULE 616.1 "triple" sibling of Furnace of
    Rath's unscoped "double" and Torbran's flat "+2"; stacking multiple
    multiplicative/additive damage replacements is exactly the ordering
    case `_furnace_of_rath`'s own docstring calls out.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})],
            raw_text="Falls eine Quelle, die du kontrollierst, einer bleibenden Karte "
                     "oder einem Spieler Schaden zufügen würde, fügt sie stattdessen "
                     "dreifach so viel Schaden zu.",
        )
    ]


register("Fiery Emancipation", _fiery_emancipation)


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
    permission (`docs/implementation-state/BACKLOG.md`'s processing-list tail — "you may
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


def _lurrus_of_the_dream_den() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast a permanent spell with
    mana value 2 or less from your graveyard.
    Companion — Each permanent card in your starting deck has mana value 2
    or less. (You may begin the game with this card in your sideboard.)

    — Lurrus of the Dream-Den. The graveyard-cast permission
    (`graveyard_cast_permission`, `game/graveyard_cast.py`) is the
    open-ended sibling of `top_library_permission` above (a standing grant
    from a permanent, not a closed alt-cost keyword like Flashback/Escape);
    ``once_per_turn``/``permanent_only`` both default True, so only the
    ``max_mana_value`` gate needs stating. Companion (RULE 702.139, a
    deck-construction legality rule checked at deckbuilding time, not a
    runtime game effect) isn't modeled — out of the game engine's scope,
    same as every other Companion card. "If a spell cast this way would be
    put into a graveyard this turn, exile it instead" *is* now modeled via
    ``exile_if_would_be_put_into_graveyard`` — see
    `GraveyardCastPermissionEffect`'s own docstring for the mechanism
    (`GameObject.cast_via_graveyard_cast_permission_until_turn` +
    `RulesEngine._move_to_graveyard`'s redirect).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "max_mana_value": 2, "exile_if_would_be_put_into_graveyard": True,
            })],
            raw_text="Einmal während jedes deiner Züge darfst du einen "
                     "permanenten Zauberspruch mit Manawert 2 oder weniger "
                     "aus deinem Friedhof wirken. Falls ein auf diese Weise "
                     "gewirkter Zauberspruch in diesem Zug auf einen "
                     "Friedhof gelegt werden würde, exiliere ihn stattdessen.",
        )
    ]


register("Lurrus of the Dream-Den", _lurrus_of_the_dream_den)


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
# ability); see `docs/implementation-state/BACKLOG.md` for the running list.
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
                    "description": "Mana Drain: {C} in Höhe der Manakosten des annullierten Zauberspruchs hinzufügen",
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
    (independent of this registry). The return-and-haste half is
    `return_top_graveyard_creature_with_haste` (a positional "top of
    graveyard" pick, not a RULE 115 target).

    The trailing "Exile it at the beginning of the next end step." is now
    modeled too, and stays *inside* that same effect rather than becoming a
    second spec entry: `CreateDelayedTriggerEffect` bakes its targets in at
    arm time, and only the effect that did the returning knows which object
    "it" is — the same "act on what I just did" reason the return and the
    haste grant are one effect. ``scope="any"`` matches "the **next** end
    step", whoever's turn that is.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_top_graveyard_creature_with_haste", {
                "delayed_exile_step": "end",
            })],
            raw_text="Bringe die oberste Kreaturenkarte deines Friedhofs ins Spiel "
                     "zurück. Diese Kreatur erhält Eile bis zum Ende des Zuges. "
                     "Exiliere sie zu Beginn des nächsten Endsegments.",
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
    docs/implementation-state/BACKLOG.md). ``target_kind="creature"``
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
    elsewhere).

    "This ability costs {1} less to activate for each legendary creature you
    control." is a `costs.ActivationCost.dynamic_reduction` — the same field
    Mariposa Military Base's own per-rad-counter discount already used, now
    also accepting a **board**-reading ``count_selector`` (`continuous.
    count_selector`'s ``legendary_creatures_you_control``) instead of only a
    player-counter ``kind``. Re-evaluated live on every activation
    (`GameEngine._reduced_activation_mana`), so playing a legendary creature
    mid-turn immediately cheapens it, and `ManaCost.reduce_generic`'s own
    floor keeps the coloured {W} pip intact no matter how many legends are
    out. This is distinct from `continuous.cost_reduction_for`'s RULE 601.2f
    *spell*-cast discount, which never applied to an activated ability.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 4, "target_kind": "creature"})],
            cost={
                "text": "{2}{W}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
            raw_text="Kanalisieren — {2}{W}, Wirf diese Karte ab: Sie fügt einer "
                     "angreifenden oder blockenden Zielkreatur 4 Schaden zu. Diese "
                     "Fähigkeit kostet {1} weniger für jede legendäre Kreatur, die "
                     "du kontrollierst.",
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

    — Ephemerate. Rebound (RULE 702.88b) is now modeled, reusing the
    `create_delayed_trigger`/`GameState.delayed_triggers` primitive Mana
    Drain's own batch built (this docstring previously deferred it as
    blocked on exactly that primitive, citing Mana Drain among others —
    stale the moment that batch shipped; see `AbilitySpec.rebound`'s
    docstring for the "standing free-cast window instead of a forced
    yes/no choice" simplification). The `rebound` marker rides on its own
    empty-effects spec, the same "scan every spec" shape `impulsive_draw_
    on_combat_damage` uses; the blink half is unchanged (`game/effects.py`'s
    `BlinkEffect`/`RulesEngine.blink`, RULE 400.7's "exile then immediately
    return").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("blink", {"target_kind": "creature_you_control"})],
            raw_text="Exiliere eine Zielkreatur, die du kontrollierst, und "
                     "bringe sie dann unter der Kontrolle ihres Besitzers "
                     "auf das Schlachtfeld zurück.",
        ),
        AbilitySpec(
            "static",
            [],
            rebound=True,
            raw_text="Wiedergänger (Falls du diesen Zauberspruch von deiner Hand "
                     "gewirkt hast, verbanne ihn, während er verrechnet wird. Zu "
                     "Beginn deiner nächsten Versorgung darfst du diese Karte aus "
                     "dem Exil wirken, ohne ihre Manakosten zu bezahlen.)",
        ),
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
                    "description": "Final Fortune: du verlierst das Spiel",
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


# ---------------------------------------------------------------------------
# Impulsive draw's dual-player extension — Ragavan, Nimble Pilferer's
# damaged-player-library exile + Mnemonic Betrayal's whole-graveyard, "any
# type" mana-wildcard exile. See `game/effects.py`'s `ImpulsiveDrawEffect`/
# `GraveyardImpulsiveCastEffect`/`ReturnRemainingExiledEffect`,
# `RulesEngine._collect_impulsive_draw_triggers`/`exile_with_play_permission`/
# `exile_graveyard_with_cast_permission`, and `ManaPool`'s ``wildcard`` param.
# ---------------------------------------------------------------------------


def _ragavan_nimble_pilferer() -> list[AbilitySpec]:
    """Whenever Ragavan deals combat damage to a player, create a Treasure
    token and exile the top card of that player's library. Until end of
    turn, you may cast that card.
    Dash {1}{R}

    — Ragavan, Nimble Pilferer. Splits into two triggered abilities sharing
    the same "self deals combat damage to a player" condition: the Treasure
    token has no per-firing variance, so it's an ordinary bound
    `TriggeredAbility` below; the exile-and-cast-permission half needs the
    *damaged* player baked in fresh per firing (a bind-on-load ability's one
    fixed effects list can't carry that), so it's a marker
    (`impulsive_draw_on_combat_damage`) `RulesEngine.
    _collect_impulsive_draw_triggers` reads off the event's own source
    instead — see that method's docstring. Dash is a plain RULE 702 keyword,
    covered by the keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn Ragavan einer Spielerin oder einem Spieler Kampfschaden zufügt, "
                     "erschaffe einen Schatz-Spielstein.",
        ),
        AbilitySpec(
            "static",
            [],
            impulsive_draw_on_combat_damage={"count": 1},
            raw_text="Wenn Ragavan einer Spielerin oder einem Spieler Kampfschaden zufügt, "
                     "verbanne die oberste Karte der Bibliothek dieser Spielerin oder dieses "
                     "Spielers. Bis zum Ende des Zuges darfst du diese Karte wirken.",
        ),
    ]


register("Ragavan, Nimble Pilferer", _ragavan_nimble_pilferer)


def _mnemonic_betrayal() -> list[AbilitySpec]:
    """Exile all opponents' graveyards. You may cast spells from among
    those cards this turn, and mana of any type can be spent to cast them.
    At the beginning of the next end step, if any of those cards remain
    exiled, return them to their owners' graveyards.
    Exile Mnemonic Betrayal.

    — Mnemonic Betrayal. The trailing "Exile ~." is the ordinary
    `ExileEffect` ``target_kind=None`` self mode (already claimed by the
    oracle-text parser — see `backend/tests/test_cube_batch_a1.py`'s
    ``test_mnemonic_betrayal_and_teferis_protection_self_exile_claimed``);
    only the graveyard-impulsive-cast body needed hand authoring, via
    `GraveyardImpulsiveCastEffect`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile_opponents_graveyards_impulsive_cast", {"mana_wildcard": "type"}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            raw_text="Verbanne die Friedhöfe aller deiner Gegner. Du darfst in diesem Zug "
                     "Zaubersprüche unter diesen Karten wirken, und Mana jeglichen Typs kann "
                     "verwendet werden, um sie zu wirken. Zu Beginn des nächsten Endsegments "
                     "gib alle Karten, die auf diese Weise noch immer verbannt sind, in den "
                     "Friedhof ihres Besitzers zurück.\n"
                     "Verbanne Mnemonic Betrayal.",
        )
    ]


register("Mnemonic Betrayal", _mnemonic_betrayal)


def _marchesa_the_black_rose() -> list[AbilitySpec]:
    """Dethrone (Whenever this creature attacks the player with the most
    life or tied for most life, put a +1/+1 counter on it.)
    Other creatures you control have dethrone.
    Whenever a creature you control with a +1/+1 counter on it dies,
    return that card to the battlefield under your control at the
    beginning of the next end step.

    — Marchesa, the Black Rose. Her own printed Dethrone needs no
    hand-authoring — it's a plain Scryfall keyword flag `combat.has` already
    recognizes (`RulesEngine.check_dethrone`, called from `GameEngine.
    declare_attackers` since Dethrone's amount is fixed per-firing rather
    than bind-on-load, the same "per-firing dynamic" reason `check_rampage`
    isn't a bind-time `TriggeredAbility` either). The "Other creatures you
    control have dethrone" static *is* hand-authored here, below, as an
    ordinary layer-6 `grant_keyword` — `check_dethrone` reads `combat.has`
    fresh at attack-declaration time, so a creature holding the granted
    keyword dethrones exactly like one with it printed. The third clause
    (the RULE 603.7 delayed-return trigger) is modeled via
    `AbilitySpec.counter_death_return`/`RulesEngine._collect_counter_
    death_return_triggers` — a good showcase card for the "planned"
    delayed-trigger UI panel, same reason Ephemerate/Sneak Attack/Meek
    Attack were picked.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "keywords": ["dethrone"],
            })],
            raw_text="Andere Kreaturen, die du kontrollierst, haben Thronraub.",
        ),
        AbilitySpec(
            "static",
            [],
            counter_death_return={"counter_kind": "+1/+1"},
            raw_text="Wann immer eine Kreatur, die du kontrollierst und die einen "
                     "+1/+1-Zählmarke auf sich hat, stirbt, bringe diese Karte zu "
                     "Beginn des nächsten Endsegments unter deiner Kontrolle auf "
                     "das Schlachtfeld zurück.",
        )
    ]


register("Marchesa, the Black Rose", _marchesa_the_black_rose)


def _sneak_attack() -> list[AbilitySpec]:
    """{R}: You may put a creature card from your hand onto the
    battlefield. That creature gains haste. Sacrifice the creature at the
    beginning of the next end step.

    — Sneak Attack. `CheatCreatureFromHandEffect` (`game/effects.py`)
    covers the whole line in one atomic effect: the RULE 701 "cheat into
    play", the haste grant, and arming the RULE 603.7 delayed sacrifice.
    The hand-card pick is auto-chosen — no chooser in this MVP,
    `RulesEngine.discard`'s established precedent for an un-targeted
    hand-card pick — rather than an interactive choice among several
    eligible creatures.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("cheat_creature_from_hand", {})],
            cost={"text": "{R}"},
            raw_text="{R}: Du darfst eine Kreaturenkarte aus deiner Hand ins Spiel "
                     "bringen. Diese Kreatur erhält Eile. Opfere die Kreatur zu "
                     "Beginn des nächsten Endsegments.",
        )
    ]


register("Sneak Attack", _sneak_attack)


def _meek_attack() -> list[AbilitySpec]:
    """{1}{R}: You may put a creature card with total power and toughness
    5 or less from your hand onto the battlefield. That creature gains
    haste. At the beginning of the next end step, sacrifice that creature.

    — Meek Attack (Sneak Attack's Unhinged sibling): the same
    `CheatCreatureFromHandEffect`, just with its ``max_total_pt`` filter
    set to 5 instead of unrestricted.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("cheat_creature_from_hand", {"max_total_pt": 5})],
            cost={"text": "{1}{R}"},
            raw_text="{1}{R}: Du darfst eine Kreaturenkarte mit einer Gesamt-Stärke "
                     "und -Widerstandskraft von 5 oder weniger aus deiner Hand ins "
                     "Spiel bringen. Diese Kreatur erhält Eile. Opfere diese Kreatur "
                     "zu Beginn des nächsten Endsegments.",
        )
    ]


register("Meek Attack", _meek_attack)


# ---------------------------------------------------------------------------
# RULE 728 Rad counters — "whenever ~ deals combat damage to a player, they
# get N rad counters" cards whose *damaged player* varies per firing (the
# oracle-text parser has no such per-firing grammar; see
# `AbilitySpec.rad_counters_on_combat_damage`, `RulesEngine._collect_rad_
# counter_damage_triggers`, `game/effects.py`'s `AddPlayerCountersEffect`).
# Each card's *other*, unrelated ability is a "whenever a player/an opponent
# mills a nonland card, ..."/"whenever one or more nonland cards are milled,
# ..." trigger (RULE 701.13) — now modeled too, off `EventType.MILL_CARD`
# (`RulesEngine.mill`, fired once per nonland card, never for a land) and its
# `effect_binder`-level "group" subject scoping, the same generic machinery
# `LIBRARY_SEARCHED`'s "an opponent searches" trigger already uses. Both
# clauses are hand-authored per card below — a 3-card family, same "narrow,
# real-card-driven" bar the oracle-text parser front-end itself uses before
# it's worth generalizing a whole new segmenter grammar for one, rather than
# building genuine parser recognition — so printed RULE 702 keywords
# (Deathtouch/Flying) are still picked up automatically regardless of
# registration (`specs_for`'s unconditional keyword fold-in), but nothing
# else on these cards falls through to the oracle-text parser.
# ---------------------------------------------------------------------------


def _glowing_one() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature deals combat damage to a player, they get four
    rad counters.
    Whenever a player mills a nonland card, you gain 1 life.

    — Glowing One. The mill trigger is an ordinary bind-once
    `TriggeredAbility` off `EventType.MILL_CARD` with an unscoped ``"group"``
    subject (no ``controller`` key — any player's mill counts, including
    your own).
    """
    return [
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": 4},
            raw_text="Wenn diese Kreatur einer Spielerin oder einem Spieler Kampfschaden "
                     "zufügt, erhält sie/er vier Rad-Marken.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group"}},
            raw_text="Wenn eine Spielerin oder ein Spieler eine Nichtland-Karte mahlt, "
                     "gewinnst du 1 Leben.",
        ),
    ]


register("Glowing One", _glowing_one)


def _infesting_radroach() -> list[AbilitySpec]:
    """Flying
    This creature can't block.
    Whenever this creature deals combat damage to a player, they get that
    many rad counters.
    Whenever an opponent mills a nonland card, if this creature is in your
    graveyard, you may return it to your hand.

    — Infesting Radroach. "That many" ties the rad-counter amount to the
    combat damage just dealt (`rad_counters_on_combat_damage`'s
    ``"damage_amount"`` sentinel, `RulesEngine._collect_rad_counter_damage_
    triggers`). The graveyard-return-on-opponent-mill ability is RULE
    112.6a's own family — a triggered ability that must keep functioning
    while its source sits in the graveyard, not a bind-once
    `TriggeredAbility` at all — see `AbilitySpec.mill_return_from_graveyard`/
    `RulesEngine._collect_mill_return_from_graveyard_triggers`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})],
            raw_text="Diese Kreatur kann nicht blocken.",
        ),
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": "damage_amount"},
            raw_text="Wenn diese Kreatur einer Spielerin oder einem Spieler Kampfschaden "
                     "zufügt, erhält sie/er so viele Rad-Marken.",
        ),
        AbilitySpec(
            "static",
            [],
            mill_return_from_graveyard=True,
            raw_text="Wenn ein Gegner eine Nichtland-Karte mahlt, darfst du diese Karte, "
                     "falls sie sich in deinem Friedhof befindet, auf deine Hand "
                     "zurücknehmen.",
        ),
    ]


register("Infesting Radroach", _infesting_radroach)


def _the_wise_mothman() -> list[AbilitySpec]:
    """Flying
    Whenever The Wise Mothman enters or attacks, each player gets a rad
    counter.
    Whenever one or more nonland cards are milled, put a +1/+1 counter on
    each of up to X target creatures, where X is the number of nonland
    cards milled this way.

    — The Wise Mothman. The first ability is otherwise fully covered by the
    oracle-text parser's own "~ enters or attacks" grammar and its
    ``add_player_counters``/``each_player`` selector (confirmed by direct
    `parse_oracle` output — see `docs/implementation-state/Done_Backend.md`
    "Library-top ... closeout" batch), but registering this card at all
    (needed for the second ability, below) makes `specs_for` skip the
    parser entirely for it (registry wins wholesale), so it's reproduced
    here verbatim rather than left to fall through.

    The second ability is *simplified*: rather than a genuinely dynamic
    "up to X target creatures where X is milled this way" (X varying per
    firing the way Rampage's block-count bonus does — this catalogue's
    sanctioned answer for that shape is building a fresh `TriggeredAbility`
    directly at the firing call site, `RulesEngine.check_rampage`), this
    reuses the same per-nonland-card `EventType.MILL_CARD` Glowing One/
    Infesting Radroach's mill triggers use: "put a +1/+1 counter on up to
    one target creature" fires once *per* nonland card milled (any player's
    mill, unscoped ``"group"`` subject, same as Glowing One). Across N
    simultaneous nonland mills this reaches the identical set of possible
    end states as the real card's single "up to X targets" choice — for
    each of N independent chances you may put a counter on some creature or
    decline — just as N separate optional triggers instead of one modal
    "choose up to X targets" ability; only trigger *count* (irrelevant to
    every card in this engine's corpus today) differs. The same "for each,
    optionally act" broadcast simplification `_dismantling_wave`-shaped
    entries elsewhere in this catalogue already use for a fixed-count
    "for each opponent" case, just driven by a per-firing count instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 1, "kind": "rad", "selector": "each_player"})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {"subject": "self"}},
            raw_text="Wenn The Wise Mothman ins Spiel kommt oder angreift, erhält "
                     "jede Spielerin und jeder Spieler eine Rad-Marke.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": "creature", "optional": True})],
            trigger={"event": EventType.MILL_CARD, "condition": {"subject": "group"}},
            # RULE 115.1a's "up to one target" — this codebase's trigger-
            # placement UI (`RulesEngine._trigger_target_choice`) only offers
            # a skip/decline option when the *ability* itself is marked
            # ``optional`` (RULE 603.5), so this also needs setting here even
            # though "up to one" isn't literally a "you may": without it a
            # player with a legal creature on board couldn't decline putting
            # the counter at all, contradicting "up to".
            optional=True,
            raw_text="Wenn eine oder mehrere Nichtland-Karten gemahlen werden, lege "
                     "einen +1/+1-Marker auf bis zu je eine Zielkreatur, für jede so "
                     "gemahlene Nichtland-Karte.",
        ),
    ]


register("The Wise Mothman", _the_wise_mothman)


def _bloatfly_swarm() -> list[AbilitySpec]:
    """Flying
    This creature enters with five +1/+1 counters on it.
    If damage would be dealt to this creature while it has a +1/+1 counter
    on it, prevent that damage, remove that many +1/+1 counters from it,
    then give each player a rad counter for each +1/+1 counter removed this
    way.

    — Bloatfly Swarm. Flying and the entry counters are picked up
    unconditionally (RULE 702 keyword fold-in / `entry_counters`, neither
    routed through the catalogue registry at all) — only the compound
    damage-prevention replacement needs hand-authoring here: "that many"
    ties both the counters removed *and* the rad counters granted to the
    damage amount that would have been dealt, known only inside the
    replacement itself at resolution time (`effects.
    _prevent_damage_convert_counters_replacement`), not a shape the oracle
    parser's plain `prevent_damage`/one-shot grammar can express.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage_convert_counters", {
                "to": "self", "remove_kind": "+1/+1", "grant_kind": "rad",
                "grant_selector": "each_player",
            })],
            raw_text="Falls diese Kreatur Schaden zugefügt bekommen würde, während "
                     "sie sich mindestens eine +1/+1-Marke auf ihr befindet, "
                     "verhindere diesen Schaden, entferne so viele +1/+1-Marken von "
                     "ihr, dann erhält jede Spielerin und jeder Spieler für jede so "
                     "entfernte +1/+1-Marke eine Rad-Marke.",
        ),
    ]


register("Bloatfly Swarm", _bloatfly_swarm)


def _vexing_radgull() -> list[AbilitySpec]:
    """Flying
    Whenever this creature deals combat damage to a player, that player
    gets two rad counters if they don't have any rad counters. Otherwise,
    proliferate.

    — Vexing Radgull. Flying picked up unconditionally (RULE 702 keyword
    fold-in). The branch is the same per-firing marker mechanism Glowing
    One/Infesting Radroach use (`rad_counters_on_combat_damage`, the
    damaged player varies per firing — no oracle-text grammar for that at
    all), extended with its own ``else`` key
    (`RulesEngine._collect_rad_counter_damage_triggers`): the damaged
    player gets 2 rad counters if they currently have none, otherwise a
    real RULE 701.30 proliferate happens instead (`game/effects.py`'s
    `ProliferateEffect`, which now also proliferates player-level counters
    — a documented gap this card is the first to actually need closed).
    """
    return [
        AbilitySpec(
            "static",
            [],
            rad_counters_on_combat_damage={"count": 2, "kind": "rad", "else": "proliferate"},
            raw_text="Wenn diese Kreatur einer Spielerin oder einem Spieler Kampfschaden "
                     "zufügt, erhält sie/er zwei Rad-Marken, falls sie/er keine "
                     "Rad-Marken hat. Andernfalls, vermehre dich.",
        ),
    ]


register("Vexing Radgull", _vexing_radgull)


def _vault_12_the_necropolis() -> list[AbilitySpec]:
    """I — Each player gets three rad counters.
    II — Create X 2/2 black Zombie Mutant creature tokens, where X is the
    total number of rad counters among players.
    III — Put two +1/+1 counters on each creature you control that's a
    Zombie or Mutant.

    — Vault 12: The Necropolis. Chapter I parses fine on its own (it's
    registered here only because chapters II/III need hand-authoring, and a
    registered card's other specs no longer fall back to the parser —
    `ability_catalogue.specs_for`), so it's just carried over verbatim.
    Chapter II needs two things no card in this pool needed before: a
    cross-player aggregate count (`continuous.count_selector`'s new
    ``"total_rad_counters_among_players"``, unlike every other entry there,
    which scopes to a single controller) and a "create X tokens, where X is
    ..." dynamic count (`CreateTokenEffect.count_selector` — the same
    primitive Dockside Extortionist already uses, just with this new
    selector). Chapter III needs a tribal mass-counter filter
    (`AddCountersEffect`'s new ``subtypes`` param).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 3, "kind": "rad", "selector": "each_player"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
            raw_text="I — Jede Spielerin und jeder Spieler erhält drei Rad-Marken.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "total_rad_counters_among_players",
                "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie", "Mutant"], "token_name": "Zombie Mutant",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
            raw_text="II — Erzeuge X 2/2 schwarze Zombie-Mutant-Kreaturenspielsteine, wobei "
                     "X der Gesamtzahl der Rad-Marken unter den Spielerinnen und Spielern "
                     "entspricht.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": 2, "kind": "+1/+1", "selector": "each_creature_you_control",
                "subtypes": ["Zombie", "Mutant"],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
            raw_text="III — Lege zwei +1/+1-Marken auf jede Kreatur, die du kontrollierst "
                     "und die ein Zombie oder Mutant ist.",
        ),
    ]


register("Vault 12: The Necropolis", _vault_12_the_necropolis)


def _struggle_for_project_purity() -> list[AbilitySpec]:
    """As this enchantment enters, choose Brotherhood or Enclave.
    • Brotherhood — At the beginning of your upkeep, each opponent draws a
    card. You draw a card for each card drawn this way.
    • Enclave — Whenever a player attacks you with one or more creatures,
    that player gets twice that many rad counters.

    — Struggle for Project Purity. A "choose a named mode as this enters,
    persisting for the rest of the game" shape (RULE 601.2b-adjacent, but
    choosing between two flavour-named ability sets rather than a creature
    type/colour) — a new third `enter_choice_effects` sibling
    (`ChooseNamedModeReplacement`, alongside `ChooseCreatureTypeReplacement`/
    `ChooseColorReplacement`), stamping `GameObject.chosen_mode`. Brotherhood
    is an ordinary `TriggeredAbility`, just gated by `effect_binder._trigger_
    condition`'s new ``"named_mode"`` predicate so it only fires once
    "brotherhood" was actually chosen; its "you draw a card for each card
    drawn this way" is `DrawCardEffect`'s new ``"opponents_you_have"``
    count_selector. Enclave needs a genuinely new aggregate event
    (`EventType.PLAYER_ATTACKED`, fired once per combat rather than once per
    attacking creature — see its own docstring) plus the same per-firing
    marker mechanism the other rad-counter cards use
    (`rad_counters_on_attacked`, gated the same way via its own
    ``requires_mode`` key, since it's resolved by a dedicated collector
    rather than the ordinary `TriggeredAbility` condition machinery).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {"options": ["Brotherhood", "Enclave"]})],
            raw_text="Während dieses Verzauberung ins Spiel kommt, wähle Bruderschaft "
                     "oder Enklave.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1, "selector": "each_opponent"}),
                EffectSpec("draw", {"count_selector": "opponents_you_have"}),
            ],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                "phase_relation": "you", "named_mode": "brotherhood",
            },
            raw_text="Bruderschaft — Zu Beginn deines Versorgungssegments zieht jede "
                     "Gegnerin und jeder Gegner eine Karte. Du ziehst für jede auf diese "
                     "Weise gezogene Karte eine Karte.",
        ),
        AbilitySpec(
            "static",
            [],
            rad_counters_on_attacked={"multiplier": 2, "requires_mode": "enclave"},
            raw_text="Enklave — Wann immer eine Spielerin oder ein Spieler dich mit "
                     "einer oder mehreren Kreaturen angreift, erhält sie/er doppelt so "
                     "viele Rad-Marken.",
        ),
    ]


register("Struggle for Project Purity", _struggle_for_project_purity)


def _mariposa_military_base() -> list[AbilitySpec]:
    """You may have this land enter tapped. If you do, you get two rad
    counters.
    {T}: Add {C}.
    {5}, {T}: Draw a card. This ability costs {1} less to activate for
    each rad counter you have.

    — Mariposa Military Base. The tapped-entry choice is picked up
    unconditionally, no registration needed at all
    (`parser.oracle.catalogue.lands.tap_clause_condition`'s new
    ``"optional_bonus_rad"`` shape, resolved by `RulesEngine.
    enter_land_tapped`/`resolve_land_tapped_bonus_choice` — the mirror
    image of a shock land's pay-life choice). The plain "{T}: Add {C}."
    mana ability is likewise picked up unconditionally
    (`game/mana_abilities.py` reads oracle text directly, regardless of
    catalogue registration). Only the draw ability's own "costs {1} less
    ... for each rad counter you have" needs hand-authoring here — a
    dynamically-scaled activation-cost reduction no oracle-text grammar
    exists for yet (`costs.ActivationCost.dynamic_reduction`, consulted by
    `GameEngine._reduced_activation_mana`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{5}, {T}", "dynamic_reduction": {"kind": "rad", "generic_per": 1}},
            raw_text="{5}, {T}: Ziehe eine Karte. Diese Fähigkeit kostet {1} weniger, "
                     "um sie zu aktivieren, für jede Rad-Marke, die du hast.",
        ),
    ]


register("Mariposa Military Base", _mariposa_military_base)


def _nuka_nuke_launcher() -> list[AbilitySpec]:
    """Equipped creature gets +3/+0 and has intimidate.
    Whenever equipped creature attacks, until the end of defending
    player's next turn, that player gets two rad counters whenever they
    cast a spell.
    Equip {3}

    — Nuka-Nuke Launcher. The +3/+0-and-intimidate anthem grant and Equip
    cost both parse generically (an ordinary attached-permanent static +
    the standard Equip keyword ability). Only the triggered ability
    needs hand-authoring: a *recurring*, bounded-duration player-scoped
    trigger (`InstallTemporaryPlayerTriggerEffect`/`GameState.temporary_
    player_triggers`) — no oracle-text grammar exists for "until the end
    of X's next turn, <recurring effect>" (a genuinely different shape
    from RULE 603.7's existing one-shot `CreateDelayedTriggerEffect`).
    The "whenever equipped creature attacks" trigger subject itself does
    parse generically now (`_ATTACHED_SUBJECT_RE`), so this AbilitySpec's
    ``trigger`` is written the same way the parser would emit it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("install_temporary_player_trigger", {
                "event_type": "SPELL_CAST",
                "effects": [{"type": "add_player_counters", "params": {"amount": 2, "kind": "rad"}}],
                "description": "Nuka-Nuke Launcher: Rad-Marken bei Zauberspruch",
            })],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
            raw_text="Wann immer die ausgerüstete Kreatur angreift, erhält die "
                     "verteidigende Spielerin oder der verteidigende Spieler bis zum "
                     "Ende ihres/seines nächsten Zuges zwei Rad-Marken, wann immer "
                     "sie/er einen Zauberspruch wirkt.",
        ),
    ]


register("Nuka-Nuke Launcher", _nuka_nuke_launcher)


def _harold_and_bob() -> list[AbilitySpec]:
    """Vigilance, reach
    When Harold and Bob dies, if it was a creature, return it to the
    battlefield. It's an Aura enchantment with enchant Forest you control
    and "{T}: Add three mana of any one color. You get two rad counters."
    Harold and Bob loses all other abilities.

    — Harold and Bob, First Numens. Vigilance/reach are picked up
    unconditionally (RULE 702 keyword fold-in). "If it was a creature" is a
    no-op condition given how this engine already only ever fires DIES for
    an object that was a creature (`RulesEngine._move_to_graveyard`'s own
    ``was_creature`` gate) — always true in practice, so no separate check
    is needed. The return itself is a wholly new compound shape, well
    beyond RULE 712.8's ordinary "return transformed" (which needs a real
    printed back face this card doesn't have):
    `ReturnDiesAsNewPermanentEffect`/`RulesEngine.return_dies_as_new_
    permanent` swaps the returned object's own `Card` for a synthetic Aura
    built from the quoted text right here, attached to a real RULE 115
    target ("enchant Forest you control", `targeting.py`'s new
    ``forest_you_control`` kind) — "loses all other abilities" is made
    literal by simply never re-binding the original creature's catalogue
    specs onto the new permanent. The granted "{T}: Add three mana of any
    one color. You get two rad counters." is a genuine compound mana
    ability (`game/mana_abilities.py`'s ``self_rad_counters`` rider,
    alongside fixing a latent "any one color" amount bug — the parser
    always produced 1 mana regardless of a printed fixed count > 1, since
    no card before this one printed one) — read live off the synthetic
    card's own oracle text, no further hand-authoring needed for it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_dies_as_new_permanent", {
                "new_type_line": "Enchantment — Aura",
                "new_oracle_text": "Enchant Forest you control\n{T}: Add three mana of any "
                                   "one color. You get two rad counters.",
                "target_kind": "forest_you_control",
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="Wenn Harold und Bob stirbt, falls es eine Kreatur war, bringe es "
                     "ins Spiel zurück. Es ist eine Verzauberung des Typs Aura mit "
                     "Verzaubert Wald unter deiner Kontrolle und '{T}: Füge drei Mana "
                     "einer Farbe deiner Wahl hinzu. Du erhältst zwei Rad-Marken.' "
                     "Harold und Bob verliert alle anderen Fähigkeiten.",
        ),
    ]


register("Harold and Bob, First Numens", _harold_and_bob)


def _riot_control() -> list[AbilitySpec]:
    """You gain 1 life for each creature your opponents control. Prevent
    all damage that would be dealt to you this turn.

    — Riot Control. The lifegain half is an ordinary `GainLifeEffect` with
    the new `count_selector="creatures_opponents_control"` (mirroring the
    existing "you control"/"opponents control" selector pairs in
    `continuous.count_selector`). The prevention half is the new one-shot
    `prevent_damage_shield` family (`PreventDamageEffect`/`RulesEngine.
    prevent_damage_to_player`) this card and Thought Lash's own activated
    ability motivated — a turn-scoped shield living on `Player.
    player_effects`, distinct from `regenerate`'s permanent-scoped one and
    from `ReplacementRegistry`'s unrelated standing-permanent `"prevent_
    damage"` factory (still uncarded). ``amount="all"`` here since Riot
    Control prevents everything, not a capped amount.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"count_selector": "creatures_opponents_control"}),
                EffectSpec("prevent_damage_shield", {"amount": "all"}),
            ],
            raw_text="Du gewinnst 1 Lebenspunkt für jede Kreatur, die deine Gegner "
                     "kontrollieren. Verhindere jeglichen Schaden, der dir in diesem "
                     "Zug zugefügt werden würde.",
        )
    ]


register("Riot Control", _riot_control)


def _thought_lash() -> list[AbilitySpec]:
    """Exile the top card of your library: Prevent the next 1 damage that
    would be dealt to you this turn.

    — Thought Lash. Only this repeatable activated ability is hand-authored
    here; the card's Cumulative upkeep ("At the beginning of your upkeep,
    put an age counter on this permanent, then sacrifice it unless you pay
    its upkeep cost for each age counter on it") and its own "when a player
    doesn't pay this enchantment's cumulative upkeep, that player exiles
    all cards from their library" trigger are a wholly separate, entirely
    unmodeled mechanic (Cumulative upkeep isn't built at all yet — no card
    needs it otherwise) and are deliberately left unclaimed; this entry
    only supplies the activated ability so the shared `prevent_damage_
    shield` primitive has its second real, amount-capped/repeatable-use
    exercising card (Riot Control's own use is the single uncapped "all"
    case). The cost is a plain "Exile the top card of your library" cost
    (`costs.py`'s existing library-exile cost grammar); the effect passes
    ``amount=1`` — a fresh `RulesEngine.prevent_damage_to_player` shield is
    opened on each activation, so repeated activations in a turn stack
    independent 1-point shields exactly like `regenerate`'s own multiple-
    activations-stack behaviour.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1})],
            cost={"text": "Exile the top card of your library"},
            raw_text="Exiliere die oberste Karte deiner Bibliothek: Verhindere den "
                     "nächsten 1 Schadenspunkt, der dir in diesem Zug zugefügt werden "
                     "würde.",
        )
    ]


register("Thought Lash", _thought_lash)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 1: state-tracking primitives
#
# Six cards whose only real blocker was that the engine kept no *record* of
# something that had already happened: how much mana a spell was paid with,
# who a creature connected with in combat, what was sacrificed to an
# additional cost, how many symbols of a colour are on the board. Each is now
# a first-class piece of state (`GameObject.mana_spent_to_cast`/
# `sacrificed_cost_mana_value`, `GameState.combat_damage_to_players_this_turn`,
# `continuous.count_selector`'s devotion/legendary/named-card entries) rather
# than something re-derived — none of it *can* be re-derived after the fact.
# ---------------------------------------------------------------------------


def _lavinia_azorius_renegade() -> list[AbilitySpec]:
    """Each opponent can't cast noncreature spells with mana value greater
    than the number of lands that player controls.
    Whenever an opponent casts a spell, if no mana was spent to cast it,
    counter that spell.

    — Lavinia, Azorius Renegade. Both halves needed a new primitive:

    * the prohibition is the first ``cast_prohibition`` static (RULE 601.3a)
      — a *conditional* veto on one specific spell, unlike the pre-existing
      ``cast_limit``'s flat per-turn count. Its ``max_mana_value_selector``
      is evaluated for the **casting** player ("*that player*'s lands"), not
      the static's own controller, which is why it can't be a plain layer-
      engine value (`continuous.cast_prohibited`).
    * the counter-trigger reads the `SPELL_CAST` event's new ``mana_spent``
      key (RULE 202.1/601.2h). Deliberately *not* the pre-existing ``free``
      flag: a spell cast for an alternative cost of {0}, or one whose cost
      was reduced to {0}, spends no mana while still being a paid cast —
      Lavinia catches those too, which is most of why she is played.
      "Counter that spell" is the already-built RULE 603.3d ``reflexive``
      trigger shape (`TriggeredAbility.reflexive`), whose docstring named
      this card as its motivating example before it had one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents",
                "noncreature": True,
                "max_mana_value_selector": "lands_you_control",
            })],
            raw_text="Jeder Gegner kann keine Nichtkreaturenzauber mit Manawert "
                     "größer als die Anzahl der Länder wirken, die er kontrolliert.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"mana_spent": 0},
                "reflexive": True,
            },
            raw_text="Immer wenn ein Gegner einen Zauberspruch wirkt und dafür kein "
                     "Mana ausgegeben wurde, annulliere jenen Zauberspruch.",
        ),
    ]


register("Lavinia, Azorius Renegade", _lavinia_azorius_renegade)


def _boromir_warden_of_the_tower() -> list[AbilitySpec]:
    """Vigilance
    Whenever an opponent casts a spell, if no mana was spent to cast it,
    counter that spell.
    Sacrifice Boromir: Creatures you control gain indestructible until end
    of turn. The Ring tempts you.

    — Boromir, Warden of the Tower. Shares Lavinia's ``mana_spent`` trigger
    verbatim (see her entry). Vigilance comes from the RULE 702 keyword
    catalogue, independent of this registry.

    "The Ring tempts you." (RULE 701.51a) is now real: `RulesEngine.
    the_ring_tempts_you` levels the tempting player's Ring emblem up (0–4,
    `Player.ring_level`) and re-chooses their Ring-bearer (`Player.
    ring_bearer_id`, an interactive ``ring_bearer`` `pending_choice` when
    there's more than one creature to pick). The emblem's four abilities are
    all source-less like the monarch's and the initiative's — ability 1 is a
    static split between `continuous._apply_ring_bearer_static` (legendary)
    and `GameEngine.can_block` (the greater-power blocking restriction),
    abilities 2–4 are built fresh per firing by `RulesEngine.
    _collect_ring_triggers`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"mana_spent": 0},
                "reflexive": True,
            },
            raw_text="Immer wenn ein Gegner einen Zauberspruch wirkt und dafür kein "
                     "Mana ausgegeben wurde, annulliere jenen Zauberspruch.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["indestructible"],
                "selector": "creatures_you_control",
            }), EffectSpec("the_ring_tempts_you", {})],
            cost={"sacrifice": "self"},
            raw_text="Opfere Boromir: Kreaturen, die du kontrollierst, erhalten bis "
                     "zum Ende des Zuges Unzerstörbarkeit. Der Ring verlockt dich.",
        ),
    ]


register("Boromir, Warden of the Tower", _boromir_warden_of_the_tower)


def _hope_of_ghirapur() -> list[AbilitySpec]:
    """Flying
    Sacrifice Hope of Ghirapur: Until your next turn, target player who was
    dealt combat damage by Hope of Ghirapur this turn can't cast noncreature
    spells.

    — Hope of Ghirapur. Two firsts here, both forced by the card:

    * a **history-filtered target kind** (`targeting.py`'s
      ``player_dealt_combat_damage_by_source``). By the time the sacrifice
      ability is activated the combat damage step is long over and nothing
      on the board records who got hit, so `GameState.
      combat_damage_to_players_this_turn` keeps the tally (keyed by source,
      so two copies each track their own victims). With no one hit this
      turn the ability simply has no legal target and RULE 601.2c makes it
      unactivatable — exactly right, and fail-closed.
    * a **player-scoped cast prohibition with no permanent behind it**
      (`PlayerCastRestrictionEffect`). Hope has sacrificed *itself* to pay
      for this, so there is nothing for `continuous.recompute` to read a
      static off; it lives on `Player.player_effects` for the same reason
      the RULE 615 damage shield does, and lapses when the *controller's*
      next turn begins (RULE 611.2b, swept in `GameEngine.begin_turn`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("player_cast_restriction", {"noncreature": True})],
            cost={"sacrifice": "self"},
            raw_text="Opfere Hoffnung von Ghirapur: Bis zu deinem nächsten Zug kann "
                     "ein Zielspieler, dem Hoffnung von Ghirapur in diesem Zug "
                     "Kampfschaden zugefügt hat, keine Nichtkreaturenzauber wirken.",
        ),
    ]


register("Hope of Ghirapur", _hope_of_ghirapur)


def _thassas_oracle() -> list[AbilitySpec]:
    """When this creature enters, look at the top X cards of your library,
    where X is your devotion to blue. Put up to one of them on top of your
    library and the rest on the bottom of your library in a random order.
    If X is greater than or equal to the number of cards in your library,
    you win the game.

    — Thassa's Oracle. Needed the **devotion** count selector (RULE 202.2f):
    `Card.mana_cost` already tallies symbols per colour *and* already counts
    a hybrid pip toward both of its colours, which is precisely devotion's
    definition, so `continuous.count_selector`'s ``devotion_to_<colour>``
    entries read it directly with no cost re-parse.

    The win check (RULE 104.2a) is evaluated *before* anything moves and
    routes through `RulesEngine.player_wins`, the same choke point Jace,
    Wielder of Mysteries uses — so a "you can't win the game" effect would
    stop both in one place. Note X >= 0 wins on an empty library even with
    devotion 0, which is correct and is the actual cEDH line (Oracle after
    Demonic Consultation).

    **Documented simplification**: the dig itself is non-interactive —
    the top card stays on top, the rest go to the bottom. In every real line
    the card is cast to *win*, not to filter, so the choice is a formality;
    this matches the non-interactive auto-pick the engine already makes for
    sacrifice/discard costs.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("look_top_keep_one_on_top", {
                "count_selector": "devotion_to_blue",
                "win_if_count_at_least_library": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            raw_text="Wenn diese Kreatur ins Spiel kommt, schaue dir die obersten X "
                     "Karten deiner Bibliothek an, wobei X deine Hingabe zu Blau ist. "
                     "Falls X größer oder gleich der Anzahl Karten in deiner "
                     "Bibliothek ist, gewinnst du das Spiel.",
        ),
    ]


register("Thassa's Oracle", _thassas_oracle)


def _eldritch_evolution() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value X or less, where
    X is 2 plus the sacrificed creature's mana value. Put that card onto the
    battlefield, then shuffle. Exile Eldritch Evolution.

    — Eldritch Evolution. The additional cost (RULE 601.2b) was already
    modeled; what was missing is that nothing *remembered what was
    sacrificed*. `StackItem.x` only ever threads a spell's announced {X},
    so the sacrificed permanent's mana value now gets its own channel
    (`GameObject.sacrificed_cost_mana_value`, stamped by `GameEngine.
    _pay_additional_cast_cost` right before the victim leaves) and
    `SearchLibraryEffect.mana_value_from` binds it into the search criteria
    at resolution time. With no cost paid it fails closed to "nothing
    matches" rather than searching unrestricted.

    "Exile Eldritch Evolution." is its own replacement of the normal
    graveyard destination — the shipped `ExileEffect` self mode
    (``target_kind=None``, no target), which `RulesEngine.resolve_top_of_
    stack` already honours by *not* also routing the card to the graveyard.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature"},
                    "destination": "battlefield",
                    "mana_value_from": {"source": "sacrificed_cost", "plus": 2, "cmp": "le"},
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
            additional_cost={"sacrifice": "creature"},
            raw_text="Als zusätzliche Kosten opfere eine Kreatur. Durchsuche deine "
                     "Bibliothek nach einer Kreaturenkarte mit Manawert X oder "
                     "weniger, wobei X gleich 2 plus dem Manawert der geopferten "
                     "Kreatur ist, und bringe sie ins Spiel. Mische danach. "
                     "Exiliere Eldritch Evolution.",
        ),
    ]


register("Eldritch Evolution", _eldritch_evolution)


def _neoform() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Search your library for a creature card with mana value equal to 1 plus
    the sacrificed creature's mana value, put that card onto the battlefield
    with an additional +1/+1 counter on it, then shuffle.

    — Neoform. Eldritch Evolution's sibling (see that entry for the
    ``mana_value_from`` channel), with two differences: the bound is
    *exact* rather than "or less" (``"cmp": "eq"``, emitted as a two-sided
    min/max since `models.card_query` has no single "exactly N" key), and
    the found card arrives with a counter already on it
    (``extra_counters``, applied by `RulesEngine._finish_search` the moment
    it reaches the battlefield — RULE 614.1c-adjacent, but applied here
    rather than as an entry replacement because the counter comes from the
    *searching effect*, not the card's own printed text).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
                "extra_counters": {"kind": "+1/+1", "count": 1},
            })],
            additional_cost={"sacrifice": "creature"},
            raw_text="Als zusätzliche Kosten opfere eine Kreatur. Durchsuche deine "
                     "Bibliothek nach einer Kreaturenkarte mit Manawert gleich 1 plus "
                     "dem Manawert der geopferten Kreatur und bringe sie mit einer "
                     "zusätzlichen +1/+1-Marke ins Spiel. Mische danach.",
        ),
    ]


register("Neoform", _neoform)


def _rite_of_flame() -> list[AbilitySpec]:
    """Add {R}{R}, then add {R} for each card named Rite of Flame in each
    graveyard.

    — Rite of Flame. Two halves of one `AddManaEffect`: the flat ``{R}{R}``
    as printed symbols, plus the board-reading bonus via the new
    ``amount_selector`` (`continuous.count_selector`'s
    ``cards_named_source_in_all_graveyards`` — a cross-player aggregate like
    the existing ``total_rad_counters_among_players``, but name-keyed).

    The name comes from the effect's **own source object**, never from a
    free-text literal in the spec — putting an arbitrary card name through
    the spec boundary would buy nothing and widen it. The resolving copy is
    on the stack rather than in a graveyard, so it never counts itself.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["R", "R"],
                "color": "R",
                "amount_selector": "cards_named_source_in_all_graveyards",
            })],
            raw_text="Erzeuge {R}{R} und danach {R} für jede Karte namens Rite of "
                     "Flame in einem Friedhof.",
        ),
    ]


register("Rite of Flame", _rite_of_flame)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 2: mana primitives
#
# The headline new mechanism is the **triggered mana ability** (RULE
# 605.1b/605.4, `TriggeredAbility.mana_ability`): an ability that triggers
# off a mana ability and only produces mana never uses the stack at all — it
# resolves on the spot, so its mana is in the pool in time for the very
# payment that triggered it. Queueing it like an ordinary trigger would put
# the extra mana one full stack resolution too late to spend, which is the
# entire reason both Wild Growth and Kinnan are played.
#
# Alongside it: `GameContext.trigger_event` (RULE 603.1 — the firing event,
# exposed for exactly the resolution window, so an effect can depend on
# *which* firing without every `apply()` growing an event parameter) and the
# generalized `pay_cost_then` optional payment (RULE 118.3).
# ---------------------------------------------------------------------------


def _wild_growth() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G}.

    — Wild Growth. A **triggered mana ability** (RULE 605.1b): it triggers
    off a mana ability and produces only mana, so RULE 605.4 keeps it off
    the stack entirely and `RulesEngine._collect_triggers` resolves it
    immediately. That timing is the card — an extra {G} that arrived after a
    stack resolution would be useless for the spell you tapped the land to
    cast.

    The recipient is ``event_controller``, not the Aura's own controller:
    the text says "**its** controller", and RULE 110.2 lets those diverge
    under a control-change effect.

    Enchant land comes from the RULE 702 keyword catalogue; the trigger's
    subject is the shipped ``attached_permanent`` scoping (RULE 603.1), so
    it stops firing the instant the Aura is unattached, with no teardown.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["G"], "recipient": "event_controller"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
            raw_text="Immer wenn das verzauberte Land für Mana getappt wird, erzeugt "
                     "sein Beherrscher zusätzlich {G}.",
        ),
    ]


register("Wild Growth", _wild_growth)


def _kinnan_bonder_prodigy() -> list[AbilitySpec]:
    """Whenever you tap a nonland permanent for mana, add one mana of any
    type that permanent produced.
    {5}{G}{U}: Look at the top five cards of your library. You may put a
    non-Human creature card from among them onto the battlefield. Put the
    rest on the bottom of your library in a random order.

    — Kinnan, Bonder Prodigy. Wild Growth's sibling — the same RULE 605.4
    triggered mana ability — but the *type* isn't printed: "any type that
    permanent produced" is only knowable from the firing, so
    `MirrorProducedManaEffect` reads the `TAPPED_FOR_MANA` event's
    ``produced`` payload off `GameContext.trigger_event`. That is narrower
    than `AddManaEffect`'s ``"ANY"`` sentinel (which offers every colour):
    Basalt Monolith copies {C}, and a Bloom Tender copies only what it
    actually made.

    The trigger's group subject is ``{"controller": "you"}`` with a
    nonland type filter, so an opponent's taps and your own lands are both
    correctly ignored.

    **Documented simplification**: with 2+ distinct types produced in a
    single tap (only possible for an "any combination of colours" ability)
    the first is copied rather than opening a choice — see
    `MirrorProducedManaEffect`. The activated ability's "non-Human" filter
    likewise collapses to a plain creature filter, the same simplification
    the shipped `impulsive_look` grammar already makes for subtype-negated
    filters elsewhere.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mirror_produced_mana", {"count": 1})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "you", "type": "nonland"},
                "mana_ability": True,
            },
            raw_text="Immer wenn du eine bleibende Nichtland-Karte für Mana tappst, "
                     "erzeuge ein Mana eines beliebigen Typs, den jene bleibende "
                     "Karte erzeugt hat.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 5,
                "criteria": "Creature",
                "hit_destination": "battlefield",
                "miss_destination": "library_bottom",
                "optional": True,
            })],
            cost={"text": "{5}{G}{U}"},
            raw_text="{5}{G}{U}: Schaue dir die obersten fünf Karten deiner Bibliothek "
                     "an. Du kannst eine Nicht-Mensch-Kreaturenkarte davon ins Spiel "
                     "bringen. Lege den Rest in zufälliger Reihenfolge unter deine "
                     "Bibliothek.",
        ),
    ]


register("Kinnan, Bonder Prodigy", _kinnan_bonder_prodigy)


def _mana_web() -> list[AbilitySpec]:
    """Whenever a land an opponent controls is tapped for mana, tap all
    lands that player controls that could produce any type of mana that land
    could produce.

    — Mana Web. *Not* a mana ability (it produces none), so unlike Wild
    Growth/Kinnan above it uses the stack like any ordinary trigger.

    Both halves of "that player" / "that land" come from the firing event
    (`GameContext.trigger_event`). The reference land's production is
    re-derived from `game/mana_abilities.py` rather than read off the
    event's ``produced`` payload, because RULE 605.1a's wording is about
    what a land *could* produce: a dual land tapped for {U} still locks
    down every land making {U} **or** its other colour, which is the
    difference between Mana Web being a real prison piece and a rounding
    error.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_matching_lands", {})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "not_you", "type": "land"},
            },
            raw_text="Immer wenn ein Land, das ein Gegner kontrolliert, für Mana "
                     "getappt wird, tappe alle Länder, die jener Spieler kontrolliert "
                     "und die einen Manatyp erzeugen könnten, den jenes Land erzeugen "
                     "könnte.",
        ),
    ]


register("Mana Web", _mana_web)


def _mana_vault() -> list[AbilitySpec]:
    """This artifact doesn't untap during your untap step.
    At the beginning of your upkeep, you may pay {4}. If you do, untap this
    artifact.
    At the beginning of your draw step, if this artifact is tapped, it deals
    1 damage to you.
    {T}: Add {C}{C}{C}.

    — Mana Vault. Three of the four lines were already expressible; the two
    that weren't are now general primitives rather than one-offs:

    * "you may pay {4}. If you do, untap ~." is the new ``pay_cost_then``
      (RULE 118.3) — the general form of the shipped, energy-only
      `PayEnergyThenEffect`, reusing the very same `_can_pay_player_cost`/
      `_pay_player_cost` machinery ward and "sacrifice ~ unless you pay"
      share, so an arbitrary `ActivationCost` works without a fourth
      parallel payment path. `UntapSelfEffect` deliberately bypasses the
      untap-step restriction the card's own first line imposes — that
      restriction is about RULE 502.4, not about this ability.
    * "if this artifact is tapped" is a RULE 603.4 intervening-if about the
      ability's **own source's** state (`effect_binder`'s new
      ``source_state`` trigger key), rather than about the event or whose
      turn it is — the two intervening-if flavours that already existed.

    The mana ability and the untap restriction both come from the engine
    directly (the printed mana ability needs no spec; the restriction is the
    shipped ``no_untap`` static).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("no_untap", {})],
            raw_text="Dieses Artefakt enttappt nicht während deines Enttappsegments.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{4}",
                "effects": [{"type": "untap_self", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
            raw_text="Zu Beginn deines Versorgungssegments kannst du {4} bezahlen. "
                     "Falls du dies tust, enttappe dieses Artefakt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": None, "selector": "controller"})],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "draw"},
                "phase_relation": "you",
                "source_state": "tapped",
            },
            raw_text="Zu Beginn deines Ziehsegments fügt dieses Artefakt dir 1 Schaden "
                     "zu, falls es getappt ist.",
        ),
    ]


register("Mana Vault", _mana_vault)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 3: control & zone effects
#
# Five shapes the engine had no way to express, each now a whitelisted
# primitive: a two-way control **exchange** (RULE 701.10, distinct from both
# shipped control shapes), **mass phasing** plus a player-scoped life lock
# (RULE 702.26b/119.6), pulling a **spell** off the stack into hand (RULE
# 400.1, distinct from bouncing a permanent), a bounce whose legal set
# depends on the *entering* permanent, and putting cards onto the
# battlefield from **hand**.
# ---------------------------------------------------------------------------


def _gilded_drake() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exchange control of this creature and up to
    one target creature an opponent controls. If you don't or can't make an
    exchange, sacrifice this creature. This ability still resolves if its
    target becomes illegal.

    — Gilded Drake. Needed a genuine **control-exchange** primitive (RULE
    701.10): the shipped layer-2 ``control_change`` static reassigns one
    permanent for as long as its source sticks around, and
    `GainControlUntilEndOfTurnEffect` is a one-way, end-of-turn grab.
    Exchange is two-way, permanent, and survives its source leaving — the
    drake dying afterwards must *not* hand the creature back, which is
    exactly why the card sees play. So it's modeled as a straight
    `controller_id` swap (RULE 701.10c's one-shot change of control), not as
    a pair of continuous effects.

    "If you don't or can't make an exchange, sacrifice this creature" is
    RULE 701.10d — an exchange with only one exchangeable permanent doesn't
    happen at all — and falls out naturally: ``optional=True`` on the target
    makes "no target" a legal choice, so the ability resolves, the exchange
    doesn't, and the sacrifice does (RULE 701.16c: sacrifice, never
    destruction, so nothing can regenerate out of it).

    Flying comes from the RULE 702 keyword catalogue.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control", {
                "target_kind": "creature",
                "sacrifice_self_if_no_exchange": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            raw_text="Wenn diese Kreatur ins Spiel kommt, tausche die Kontrolle über "
                     "sie und über bis zu eine Zielkreatur, die ein Gegner "
                     "kontrolliert. Falls du keinen Tausch vornimmst oder kannst, "
                     "opfere diese Kreatur.",
        ),
    ]


register("Gilded Drake", _gilded_drake)


def _teferis_protection() -> list[AbilitySpec]:
    """Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out.
    Exile Teferi's Protection.

    — Teferi's Protection. Three simultaneous effects sharing one duration,
    so they're one primitive:

    * **mass phasing** (RULE 702.26b) — the shipped `PhaseOutEffect` only
      ever phased a single permanent, and deliberately unattached any Aura/
      Equipment on it. Here host and attachment phase out *together*, so the
      attachment stays valid throughout (RULE 702.26e) — which is the whole
      point of the card as a board-preserving answer. The duration needs no
      bookkeeping of its own: `GameEngine._step_untap`'s existing RULE
      702.26a sweep phases everything back in at your next untap step.
    * **"your life total can't change"** (RULE 119.6) — a *prohibition*, not
      a replacement that rewrites an amount, so `RulesEngine.gain_life`/
      `lose_life` check it at their choke points rather than routing it
      through `apply_replacements`.
    * **protection from everything** for a *player* (RULE 702.16e), which
      reduces to "is dealt no damage" — the only half a player can be
      subject to. Checked in `deal_damage` alongside the permanent-side
      `is_protected_from`, which can't answer it (players carry no printed
      protection).

    The latter two live on `Player.player_effects` (`PlayerShieldEffect`)
    for the same reason Hope of Ghirapur's lock does: the spell is already
    in the graveyard, so there is no permanent to derive a static from. Both
    lapse together in `GameEngine.begin_turn` (RULE 611.2b).

    "Exile Teferi's Protection." is the shipped `ExileEffect` self mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("phase_out_all_you_control", {}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            raw_text="Bis zu deinem nächsten Zug kann sich dein Lebenspunktestand "
                     "nicht ändern und du erhältst Schutz vor allem. Alle bleibenden "
                     "Karten, die du kontrollierst, werden phasenverschoben. "
                     "Exiliere Teferis Schutz.",
        ),
    ]


register("Teferi's Protection", _teferis_protection)


def _narsets_reversal() -> list[AbilitySpec]:
    """Copy target instant or sorcery spell, then return it to its owner's
    hand. You may choose new targets for the copy.

    — Narset's Reversal. The copy half was already shipped
    (`CopySpellEffect`); the *bounce* half needed a new engine primitive:
    every existing "return to hand" moves a battlefield permanent, and this
    one pulls a `StackItem` off the stack entirely (`RulesEngine.
    return_spell_to_hand`, RULE 400.1). Practically that's a counter that
    leaves the card in hand instead of the graveyard — which is why it beats
    "can't be countered".

    Kept as one atomic effect rather than two composed ones for the same
    reason `GainControlUntilEndOfTurnEffect` is: both clauses act on the
    *same* chosen spell, and two separate targeting effects would prompt for
    it twice. Order matters and is the card's whole trick — the copy is made
    **first**, so it survives the original being picked up.

    **Documented simplification**: "You may choose new targets for the copy"
    keeps the original's targets, the same MVP choice `CopySpellEffect`'s
    own docstring already documents for every card in this family.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell_and_bounce", {"card_types": ["instant", "sorcery"]})],
            raw_text="Kopiere einen Zielspontanzauber oder eine Zielhexerei und bringe "
                     "sie danach auf die Hand ihres Besitzers zurück.",
        ),
    ]


register("Narset's Reversal", _narsets_reversal)


def _reiterate() -> list[AbilitySpec]:
    """Buyback {3}
    Copy target instant or sorcery spell. You may choose new targets for the
    copy.

    — Reiterate. Needed nothing new at all: Buyback (RULE 702.27) has been a
    real, payable additional cost since the keyword catalogue landed
    (`GameEngine._buyback_cost`/`GameObject.buyback_paid`, with
    `RulesEngine.resolve_top_of_stack` returning the card to hand instead of
    the graveyard), and `CopySpellEffect` was already built — its own
    docstring names Reiterate. It was simply never registered, so the
    fail-closed coverage gate left the card `UNMODELED` on the strength of
    the unparsed body. Registering it is the whole fix.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            raw_text="Kopiere einen Zielspontanzauber oder eine Zielhexerei.",
        ),
    ]


register("Reiterate", _reiterate)


def _cloudstone_curio() -> list[AbilitySpec]:
    """Whenever a nonartifact permanent you control enters, you may return
    another permanent you control that shares a permanent type with it to
    its owner's hand.

    — Cloudstone Curio. "Shares a permanent type **with it**" is why this
    can't be an ordinary bounce with a target kind: the legal set depends on
    the *entering* permanent, which is only known per firing. It reads
    `GameContext.trigger_event` (the RULE 603.1 firing event, exposed for
    exactly the resolution window) and narrows to permanents sharing one of
    its RULE 205.2a main types.

    The trigger's group subject uses the negated type filter added for
    Kinnan (``"type": "nonartifact"``), so the artifact half of the printed
    restriction is real rather than dropped.

    **Documented simplification**: the "you may … return" *pick* is
    non-interactive (most recently added matching permanent). The trigger
    itself is already ``optional``, so the machinery does ask whether to
    bounce at all — and Cloudstone Curio's real use is a deliberate two-card
    loop where the intended permanent is unambiguous.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_shared_type_permanent", {})],
            optional=True,
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "controller": "you", "type": "nonartifact",
                },
            },
            raw_text="Immer wenn eine bleibende Nichtartefaktkarte, die du "
                     "kontrollierst, ins Spiel kommt, kannst du eine andere bleibende "
                     "Karte, die du kontrollierst und die einen bleibenden Kartentyp "
                     "mit ihr gemeinsam hat, auf die Hand ihres Besitzers "
                     "zurückbringen.",
        ),
    ]


register("Cloudstone Curio", _cloudstone_curio)


def _tooth_and_nail() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for up to two creature cards, reveal them, put
      them into your hand, then shuffle.
    • Put up to two creature cards from your hand onto the battlefield.
    Entwine {2}

    — Tooth and Nail. The second mode needed the one genuinely new shape:
    every "put onto the battlefield" in the engine moves a card out of a
    *library* (a search) or a *graveyard* (reanimation), never an open pick
    from hand. `PutFromHandOntoBattlefieldEffect` reuses `RulesEngine.
    request_search`'s interactive one-at-a-time choice against a new
    ``"hand"`` search zone, so the prompt, the undo snapshots and the "up to
    N" semantics match every other pick rather than needing a parallel
    choice kind wired through the session and frontend. `request_search`
    already keys its shuffle and its `LIBRARY_SEARCHED` event to
    ``"library"``, so a hand pick correctly does neither.

    **Entwine (RULE 702.42a)** is now a real additional cost rather than the
    free RULE 700.2e ``or_both`` flag it used to borrow: the ``entwine`` key
    on the modes block prices the combined offer, so "choose all" costs
    {2} more and is *locked* when that {2} isn't available — which matters,
    because the both-modes line (tutor two creatures, then put them onto the
    battlefield) is the entire reason the card is played, and getting it for
    free made the spell strictly better than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "entwine": "{2}",
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": "Creature"},
                        "destination": "hand",
                        "count": 2,
                    })],
                    [EffectSpec("put_from_hand_onto_battlefield", {
                        "criteria": {"type": "Creature"},
                        "count": 2,
                    })],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach bis zu zwei Kreaturenkarten "
                    "und nimm sie auf die Hand.",
                    "Bringe bis zu zwei Kreaturenkarten aus deiner Hand ins Spiel.",
                ],
            },
            raw_text="Wähle eins — Durchsuche deine Bibliothek nach bis zu zwei "
                     "Kreaturenkarten und nimm sie auf die Hand; oder bringe bis zu "
                     "zwei Kreaturenkarten aus deiner Hand ins Spiel. Verflechten {2}",
        ),
    ]


register("Tooth and Nail", _tooth_and_nail)


def _wandering_archaic() -> list[AbilitySpec]:
    """Whenever an opponent casts an instant or sorcery spell, they may pay
    {2}. If they don't, you may copy that spell. You may choose new targets
    for the copy.

    — Wandering Archaic // Explore the Vastlands. The tax is the new
    ``pay_cost_then`` (RULE 118.3), with two features this card is what
    forced: the **payer** is the player named by the triggering event (the
    opponent who cast the spell), not the effect's own controller; and the
    "**If they don't**, …" branch is where all the action is — the
    else-branch is what copies the spell.

    "That spell" is the RULE 603.3d ``reflexive`` trigger shape, so the copy
    acts on the exact spell that fired the trigger rather than a freshly
    chosen target — the same mechanism Lavinia's "counter that spell" uses.
    An opponent who can't afford {2} is never asked (the shortcut ward and
    `counter_unless_pays` already take), and the else-branch fires straight
    away.

    **Documented simplification**: "you *may* copy" is taken (the copy is
    the only reason the trigger exists), and new targets aren't chosen — the
    same `CopySpellEffect` MVP the whole copy family shares. The back face
    "Explore the Vastlands" is a modal-DFC land half, covered by the shipped
    MDFC machinery independently of this registration.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "payer": "event_player",
                "effects": [],
                "else_effects": [
                    {"type": "copy_spell", "params": {"card_types": ["instant", "sorcery"]}},
                ],
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_card_types": ["instant", "sorcery"],
                "reflexive": True,
            },
            raw_text="Immer wenn ein Gegner einen Spontanzauber oder eine Hexerei "
                     "wirkt, kann er {2} bezahlen. Falls er dies nicht tut, kannst du "
                     "jenen Zauberspruch kopieren.",
        ),
    ]


register("Wandering Archaic", _wandering_archaic)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 4: naming a card, and the three loops
#
# Four genuinely new engine shapes, each previously listed as its own
# blocker:
#
# * **naming a card** (`request_name_card`) — the only choice in the engine
#   whose answer space isn't enumerable from game state.
# * **dig-until-a-predicate** (`RulesEngine.dig_until`) — the cascade dig
#   generalized so both the predicate and both destinations are parameters.
# * **repeat-until-a-predicate** (`MillUntilCreatureEffect`) — every other
#   repetition here had its count fixed before it started.
# * **an open-ended loop** (`request_look_top_pay_life_loop`) — bounded by
#   its own life payment rather than by any counter.
# ---------------------------------------------------------------------------


def _demonic_consultation() -> list[AbilitySpec]:
    """Choose a card name. Exile the top six cards of your library, then
    reveal cards from the top of your library until you reveal a card with
    the chosen name. Put that card into your hand and exile all other cards
    revealed this way.

    — Demonic Consultation. Two firsts, composed:

    * **Naming a card** (`NameCardThenEffect`). Every other `pending_choice`
      picks from a set the engine can enumerate; a player may name any card
      in Magic. So the choice offers the names the player can actually see
      (their own hand/library/graveyard) as *suggestions* and accepts an
      arbitrary string, which is then only ever compared against card names
      — never interpreted — keeping docs/09's security boundary intact.
    * **Dig-until-a-predicate** (`RulesEngine.dig_until`), the cascade dig
      with the predicate and both destinations made parameters. The chosen
      name reaches it through the ``"named_card"`` criteria sentinel,
      substituted at answer time exactly like `_substitute_x` handles an
      announced {X}.

    Naming a card that *isn't* in the library exiles the whole library
    rather than erroring — which is not a degenerate case but the actual
    cEDH line: Consultation into an empty library, then Thassa's Oracle.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("name_card_then", {
                "effects": [{
                    "type": "dig_until",
                    "params": {
                        "criteria": {"name": "named_card"},
                        "pre_exile": 6,
                        "hit_destination": "hand",
                        "rest_destination": "exile",
                    },
                }],
            })],
            raw_text="Wähle einen Kartennamen. Exiliere die obersten sechs Karten "
                     "deiner Bibliothek und decke danach so lange Karten von oben "
                     "auf, bis du eine Karte mit dem gewählten Namen aufdeckst. Nimm "
                     "jene Karte auf die Hand und exiliere alle anderen so "
                     "aufgedeckten Karten.",
        ),
    ]


register("Demonic Consultation", _demonic_consultation)


def _helm_of_obedience() -> list[AbilitySpec]:
    """{X}, {T}: Target opponent mills a card, then repeats this process
    until a creature card or X cards have been put into their graveyard this
    way, whichever comes first. If one or more creature cards were put into
    that graveyard this way, sacrifice this artifact and put one of them
    onto the battlefield under your control. X can't be 0.

    — Helm of Obedience. The engine's first **repeat-until-a-predicate**
    loop: every other repetition primitive (mill N, draw N, proliferate) has
    its count fixed before it starts. Here X is only a *cap* and the real
    stopping condition is what the mill turned up, so the loop has to
    re-check after every iteration.

    Bounded on both sides by construction — X caps the iterations, an empty
    library ends it early — which is the property that makes having a
    "repeat until" primitive safe at all. "X can't be 0" falls out of the
    same guard.

    Note the reanimated creature arrives under **your** control (RULE
    110.2), not its owner's, and the Helm sacrifices itself only when a
    creature was actually hit (RULE 701.16c: sacrifice, so nothing can
    regenerate out of it).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill_until_creature", {"amount": "x", "target_kind": "player"})],
            cost={"text": "{X}", "taps_self": True},
            raw_text="{X}, {T}: Ein Zielgegner legt eine Karte von seiner Bibliothek "
                     "auf seinen Friedhof und wiederholt diesen Vorgang, bis eine "
                     "Kreaturenkarte oder X Karten auf diese Weise auf seinen "
                     "Friedhof gelegt wurden. Falls eine Kreaturenkarte dabei war, "
                     "opfere dieses Artefakt und bringe sie unter deiner Kontrolle "
                     "ins Spiel.",
        ),
    ]


register("Helm of Obedience", _helm_of_obedience)


def _lim_duls_vault() -> list[AbilitySpec]:
    """Look at the top five cards of your library. As many times as you
    choose, you may pay 1 life, put those cards on the bottom of your
    library in any order, then look at the top five cards of your library.
    Then shuffle and put the last cards you looked at this way on top in any
    order.

    — Lim-Dûl's Vault. The engine's only **open-ended** loop: every other
    repetition has a fixed count or a hard cap, whereas here the player
    decides after each iteration whether to go again. Driven by a
    `pending_choice` that re-opens itself (the same self-re-opening shape a
    multi-card search already uses) with no counter running down.

    It is still bounded, by the card's own payment rather than a safety
    valve bolted on: each iteration costs 1 life and the choice simply isn't
    offered once the player couldn't survive another (RULE 118.4).

    Stopping shuffles **first** and puts the last batch back on top
    afterwards — RULE 701.19e's ordering, the same one `_finish_search`
    already uses for a library destination; the other order would scatter
    the very cards the card promises to leave on top.

    **Documented simplification**: "in any order" isn't an interactive
    five-card reorder — the batch keeps its relative order. The card is
    played to *find* something, and the top card is what the next draw takes
    either way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("look_top_pay_life_loop", {"count": 5, "life_cost": 1})],
            raw_text="Schaue dir die obersten fünf Karten deiner Bibliothek an. So "
                     "oft du möchtest, kannst du 1 Lebenspunkt bezahlen, jene Karten "
                     "unter deine Bibliothek legen und dir danach die obersten fünf "
                     "Karten ansehen. Mische danach und lege die zuletzt angesehenen "
                     "Karten oben auf deine Bibliothek.",
        ),
    ]


register("Lim-Dûl's Vault", _lim_duls_vault)


def _tibalts_trickery() -> list[AbilitySpec]:
    """Counter target spell. Choose 1, 2, or 3 at random. Its controller
    mills that many cards, then exiles cards from the top of their library
    until they exile a nonland card with a different name than that spell.
    They may cast that card without paying its mana cost. Then they put the
    exiled cards on the bottom of their library in a random order.

    — Tibalt's Trickery. One atomic `ScrambleSpellEffect`, shared with
    Possibility Storm below: both answer a spell and then dig **its
    controller's** library for a replacement they may cast free, differing
    only in how the spell is answered and what the dig looks for. A
    composition of separate counter/mill/dig effects couldn't work — every
    clause is about the same spell and the same (not-the-caster) player, and
    the dig's predicate is derived from that spell's own name via the new
    ``not_name`` criteria key (`models.card_query`), the negated form of an
    exact name match, kept as its own key rather than a magic value inside
    ``name`` so a criteria dict stays literal data.

    **Documented simplifications**, both about hidden information the
    goldfish/replay model has no place for yet: "choose 1, 2, or 3 at
    random" is resolved by the engine rather than by a secret simultaneous
    number choice (there is no hidden-information channel between players),
    and "they may cast that card" is taken automatically — the free cast is
    the only reason anyone resolves this. Tracked in
    `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("scramble_spell", {
                "answer": "counter",
                "match": "different_name",
                "mill_random_max": 3,
            })],
            raw_text="Annulliere einen Zielzauberspruch. Wähle zufällig 1, 2 oder 3. "
                     "Sein Beherrscher legt so viele Karten von seiner Bibliothek auf "
                     "seinen Friedhof und exiliert danach Karten von oben, bis er "
                     "eine Nichtlandkarte mit einem anderen Namen als jener "
                     "Zauberspruch exiliert. Er kann jene Karte wirken, ohne ihre "
                     "Manakosten zu bezahlen.",
        ),
    ]


register("Tibalt's Trickery", _tibalts_trickery)


def _possibility_storm() -> list[AbilitySpec]:
    """Whenever a player casts a spell from their hand, that player exiles
    it, then exiles cards from the top of their library until they exile a
    card that shares a card type with it. That player may cast that card
    without paying its mana cost. Then they put all cards exiled with this
    enchantment on the bottom of their library in a random order.

    — Possibility Storm. Three things had to exist for this:

    * "casts a spell **from their hand**" — the `SPELL_CAST` event now
      carries ``from_hand``, snapshotted before the card leaves its zone
      (by the time the event fires it already sits on the stack).
    * "**that** spell" is the RULE 603.3d ``reflexive`` trigger shape, so
      the exile acts on the exact spell that fired the trigger.
    * "shares a card type **with it**" (RULE 205.2) is read off the
      answered spell's own types, snapshotted before it leaves the stack.

    Note "that player **exiles** it" is a zone change, not a counter
    (`RulesEngine.move_spell_off_stack`) — which is why Possibility Storm
    also gets around "can't be countered". The whole tail runs against the
    *casting* player, who may be an opponent: Possibility Storm scrambles
    everyone's spells, which is the point.

    **Documented simplification**: "they may cast that card" is taken
    automatically, the same MVP choice the cascade family's own free cast
    documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scramble_spell", {
                "answer": "exile",
                "match": "shares_card_type",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "filter": {"from_hand": True},
                "reflexive": True,
            },
            raw_text="Immer wenn ein Spieler einen Zauberspruch aus seiner Hand "
                     "wirkt, exiliert er ihn und exiliert danach Karten von oben "
                     "seiner Bibliothek, bis er eine Karte exiliert, die einen "
                     "Kartentyp mit ihm gemeinsam hat. Jener Spieler kann jene Karte "
                     "wirken, ohne ihre Manakosten zu bezahlen.",
        ),
    ]


register("Possibility Storm", _possibility_storm)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 5: keyword mechanics
#
# Four RULE 702 keywords that were bare `FLAG`/parametric recognition with no
# behaviour behind them — Fading (702.32), Soulbond (702.94), Mutate
# (702.140) and Bargain — plus a *granted* Escape (702.138 from Underworld
# Breach rather than printed on the card), and the Pacts, which needed
# nothing new at all beyond the `pay_cost_then` primitive wave 2 built.
# ---------------------------------------------------------------------------


def _tangle_wire() -> list[AbilitySpec]:
    """Fading 4
    At the beginning of each player's upkeep, that player taps an untapped
    artifact, creature, or land they control for each fade counter on this
    artifact.

    — Tangle Wire. **Fading (RULE 702.32)** is now a real keyword rather
    than a recognized-but-inert one, and both halves live with the keyword
    (not with this card), so every Fading/Vanishing card gets them:

    * 702.32a's entry counters are placed by `RulesEngine.
      _apply_entry_counters`, read off the **parsed keyword** rather than
      the reminder sentence — the keyword *is* the rule, and the reminder
      text isn't guaranteed to be printed.
    * 702.32b's "At the beginning of your upkeep, remove a fade counter. If
      you can't, sacrifice it." is synthesized in
      `effect_binder._keyword_triggered_abilities`, alongside annihilator/
      afflict/bushido. Note "if you can't" means *no counter left*, not a
      choice — which is why Fading N lasts N+1 of your upkeeps, not N.

    The card's own ability then reads the counter count **live** each
    upkeep, so the tax shrinks as Fading counts down — which is the entire
    design of the card.

    **Documented simplification**: which permanents get tapped is an
    auto-pick, the same non-interactive choice the engine already makes for
    every other "that player chooses" cost.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_permanents_per_counter", {
                "kind": "fade",
                "types": ["artifact", "creature", "land"],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text="Zu Beginn des Versorgungssegments jedes Spielers tappt jener "
                     "Spieler ein ungetapptes Artefakt, eine Kreatur oder ein Land, "
                     "das er kontrolliert, für jede Schwundmarke auf diesem Artefakt.",
        ),
    ]


register("Tangle Wire", _tangle_wire)


def _deadeye_navigator() -> list[AbilitySpec]:
    """Soulbond
    As long as Deadeye Navigator is paired with another creature, each of
    those creatures has "{1}{U}: Exile this creature, then return it to the
    battlefield under your control."

    — Deadeye Navigator. **Soulbond (RULE 702.94)** is now real pairing
    rather than a bare flag keyword. The pair itself is genuine game state
    (`GameObject.paired_with`, held on both objects) rather than a
    continuous effect, because RULE 702.94c breaks it on *events* — either
    creature leaving the battlefield, stopping being a creature, or the two
    ceasing to share a controller — which `RulesEngine.
    break_illegal_soulbond_pairs` sweeps as a state-based action so no
    individual site has to remember to tear it down.

    The pairing trigger is synthesized from the keyword itself
    (`effect_binder`), as *two* abilities: "when **either** enters" means it
    must fire both when Deadeye arrives and when a later unpaired creature
    joins it.

    The grant is then an ordinary layer-6 `grant_activated_ability` static
    over the new ``soulbond_pair`` selector, which resolves to the source
    plus its partner *and only while paired* — so an unpaired Navigator
    grants nothing, with no separate teardown. The granted ability is the
    shipped `blink` effect (RULE 400.7's genuine zone change, which is why
    it re-triggers enters-the-battlefield abilities — the whole point).

    **Documented simplification**: the partner is an auto-pick (the first
    other unpaired creature you control). The trigger is already
    ``optional``, so a player who wants a different partner declines.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "soulbond_pair",
                "cost": {"text": "{1}{U}"},
                "grant_effects": [{"type": "blink", "params": {}}],
            })],
            raw_text="Solange Deadeye Navigator mit einer anderen Kreatur gepaart "
                     "ist, hat jede dieser Kreaturen „{1}{U}: Exiliere diese Kreatur "
                     "und bringe sie danach unter deiner Kontrolle ins Spiel "
                     "zurück.“",
        ),
    ]


register("Deadeye Navigator", _deadeye_navigator)


def _lore_drakkis() -> list[AbilitySpec]:
    """Mutate {U/R}{U/R}
    Whenever this creature mutates, return target instant or sorcery card
    from your graveyard to your hand.

    — Lore Drakkis. **Mutate (RULE 702.140)** is now a real cast mode rather
    than a recognized-but-inert keyword:

    * the Mutate cost is an *alternative* cast cost (`GameEngine.
      _mutate_cost`), substituted the same way Flashback/Escape already
      substitute theirs;
    * a mutate cast targets a creature you own and, on resolution, merges
      onto it instead of entering the battlefield
      (`RulesEngine.mutate_onto`). The **host** stays the surviving
      `GameObject`, which is what RULE 702.140c requires — the merged
      permanent is the *same* permanent, so counters, damage, Auras and
      summoning sickness all carry over, and no enters-the-battlefield
      trigger fires;
    * "the creature on top plus all abilities from under it" is modeled by
      banking whichever card ends up *underneath* on `GameObject.
      merged_oracle_text` and re-deriving abilities through the ordinary
      bind path — so the pile keeps accumulating abilities as further
      creatures mutate onto it, and mutate needs no ability-construction
      code of its own. Both directions of "over **or** under" work: which
      one applies is chosen as the spell is cast (RULE 702.140a,
      `GameObject.mutate_under`), and only which card supplies the printed
      face changes.
    * `EventType.MUTATES` then gives "whenever this creature mutates"
      something to trigger on — deliberately distinct from
      ENTERS_BATTLEFIELD, which mutate specifically does not fire.

    * the host is validated against a real ``non_human_creature_you_own``
      target kind (RULE 702.140a) — ownership rather than control (RULE
      108.3), and Humans genuinely excluded. Checked by `GameEngine.
      can_cast`/`_cast_current_face` directly, since a mutate creature
      spell carries no targeting *effect* for the ordinary RULE 115
      machinery to read.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_instant_or_sorcery",
                "destination": "hand",
            })],
            trigger={
                "event": EventType.MUTATES,
                "condition": {"subject": "self"},
            },
            raw_text="Immer wenn diese Kreatur mutiert, bringe eine Zielspontanzauber- "
                     "oder Zielhexereikarte aus deinem Friedhof auf deine Hand zurück.",
        ),
    ]


register("Lore Drakkis", _lore_drakkis)


def _beseech_the_mirror() -> list[AbilitySpec]:
    """Bargain
    Search your library for a card, exile it face down, then shuffle. If
    this spell was bargained, you may cast the exiled card without paying
    its mana cost if that spell's mana value is 4 or less. Put the exiled
    card into your hand if it wasn't cast this way.

    — Beseech the Mirror. **Bargain** is the optional additional cost
    "sacrifice an artifact, enchantment, or token as you cast this spell",
    now genuinely payable (`GameEngine.cast_spell(..., bargained=True)`,
    charged alongside every other additional cost) and recorded on
    `GameObject.bargained`.

    "If this spell was bargained, …" is then the existing
    `EffectSpec.condition` gate with a new ``"bargained"`` key — the exact
    shape Kicker's own ``"kicked"`` gate already had, reading a flag instead
    of a counter, so `ConditionalEffect` needed one branch rather than a new
    mechanism.

    The exile round trip is now genuinely modeled rather than collapsed to
    "tutor to hand, then cheat something into play": the search's
    ``"exile_face_down"`` destination sets `GameObject.face_down_in_exile`
    (RULE 701.20a — hidden from everyone but its owner), and
    `CastExiledFaceDownEffect` then hands out Rebound's own free-cast window
    (`RulesEngine.grant_free_cast_window_from_exile`) so the card is cast
    from exile through the ordinary action loop, with its full targeting and
    modal choices. The "put the exiled card into your hand if it wasn't cast
    this way" half is a `DelayedTrigger` at the next end step, and applies
    immediately instead when the card was never eligible to be cast (the
    spell wasn't bargained, or the card costs more than {4}).

    Note the two halves have *different* conditions, which is why this isn't
    a `ConditionalEffect` around a single cast: only the cast is gated on
    ``bargained``, while the return-to-hand always happens.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "exile_face_down",
                    "count": 1,
                }),
                EffectSpec(
                    "cast_exiled_face_down",
                    {"max_mana_value": 4, "require_bargained": True},
                ),
            ],
            raw_text="Durchsuche deine Bibliothek nach einer Karte und exiliere sie "
                     "verdeckt. Falls dieser Zauberspruch gefeilscht wurde, kannst du "
                     "die exilierte Karte wirken, ohne ihre Manakosten zu bezahlen, "
                     "falls ihr Manawert höchstens 4 beträgt. Nimm die exilierte Karte "
                     "auf die Hand, falls sie nicht auf diese Weise gewirkt wurde.",
        ),
    ]


register("Beseech the Mirror", _beseech_the_mirror)


def _underworld_breach() -> list[AbilitySpec]:
    """Each nonland card in your graveyard has escape. The escape cost is
    equal to the card's mana cost plus exile three other cards from your
    graveyard.
    At the beginning of the end step, sacrifice this enchantment.

    — Underworld Breach. A **granted** Escape (RULE 702.138), which is a
    different thing from the printed keyword the engine already supported:
    it applies to cards in a *graveyard*, so no battlefield selector and no
    printed-keyword scan could ever reach them, and its cost has to be
    assembled per-card (each card's own mana cost plus the exile clause)
    rather than read from a fixed printed string.

    Modeled as a ``grant_escape`` static consulted by `GameEngine.
    _graveyard_cast_keyword`/`_escape_cost` (`continuous.
    granted_escape_for`), which is why the rest of the escape machinery —
    the zone gate, the alternative cost, `_pay_escape_graveyard_cost` —
    needed no changes at all. Kept out of `recompute` proper for the same
    reason the other permission statics are: nothing about the affected
    card's *characteristics* changes, so there is no layer to write it into.

    The self-sacrifice is the shipped `sacrifice_self` effect on an end-step
    trigger.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_escape", {
                "nonland_only": True,
                "exile_from_graveyard": 3,
            })],
            raw_text="Jede Nichtlandkarte in deinem Friedhof hat Entfliehen. Die "
                     "Entfliehen-Kosten entsprechen den Manakosten der Karte plus "
                     "exiliere drei andere Karten aus deinem Friedhof.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
            raw_text="Zu Beginn des Endsegments opfere diese Verzauberung.",
        ),
    ]


register("Underworld Breach", _underworld_breach)


def _summoners_pact() -> list[AbilitySpec]:
    """Search your library for a green creature card, reveal it, put it into
    your hand, then shuffle.
    At the beginning of your next upkeep, pay {2}{G}{G}. If you don't, you
    lose the game.

    — Summoner's Pact. Needed **nothing new**: `CreateDelayedTriggerEffect`
    (RULE 603.7) has named "the Pacts" in its docstring since it was built,
    and wave 2's `pay_cost_then` supplies the missing half — the *mandatory*
    payment with a consequence. The Pact is simply `pay_cost_then` with an
    empty "if you do" branch and `lose_game` as the "if you don't" one,
    which is exactly how the card reads.

    A player who *can't* afford the payment is never asked and loses
    immediately — the same "don't stall on a choice nobody can act on"
    shortcut ward and "sacrifice ~ unless you pay" already take, and here it
    is also the correct outcome.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "color": "G"},
                    "destination": "hand",
                    "count": 1,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Summoner's Pact: {2}{G}{G} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{2}{G}{G}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
            raw_text="Durchsuche deine Bibliothek nach einer grünen Kreaturenkarte "
                     "und nimm sie auf die Hand. Mische danach. Zu Beginn deines "
                     "nächsten Versorgungssegments bezahle {2}{G}{G}. Falls du dies "
                     "nicht tust, verlierst du das Spiel.",
        ),
    ]


register("Summoner's Pact", _summoners_pact)


def _pact_of_negation() -> list[AbilitySpec]:
    """Counter target spell.
    At the beginning of your next upkeep, pay {3}{U}{U}. If you don't, you
    lose the game.

    — Pact of Negation. Summoner's Pact's sibling; see that entry for why
    the delayed "pay or lose" needed no new primitive. Note the counter half
    was already parsed — only the Pact clause left the card `UNMODELED`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Pact of Negation: {3}{U}{U} bezahlen oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{3}{U}{U}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
            raw_text="Annulliere einen Zielzauberspruch. Zu Beginn deines nächsten "
                     "Versorgungssegments bezahle {3}{U}{U}. Falls du dies nicht "
                     "tust, verlierst du das Spiel.",
        ),
    ]


register("Pact of Negation", _pact_of_negation)


# ---------------------------------------------------------------------------
# cEDH staples cube — batch 25, wave 6: the bespoke tail
#
# The new shared primitive here is **two independently-chosen targets of
# different kinds in one clause** (`GameEffect.extra_target_specs`): the
# gathering paths (`RulesEngine._trigger_target_specs`,
# `targeting.spell_target_specs`) now read `target_specs` (plural), and
# `_apply_effects_partitioned` hands such an effect all of its groups
# flattened. That single change unblocks Brass Squire, Halvar and Archdruid's
# Charm, which were the whole "two independent targeting effects on one
# ability" entry on the blocker list.
# ---------------------------------------------------------------------------


def _brass_squire() -> list[AbilitySpec]:
    """{T}: Attach target Equipment you control to target creature you
    control.

    — Brass Squire. The seed card for `extra_target_specs`: the thing being
    attached is *itself* a target, which the shipped `AttachEffect` can't
    express (it always attaches its own source). Both requirements are
    gathered one at a time through the ordinary RULE 115.1 machinery and
    arrive at the effect flattened in printed order.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("attach_chosen", {
                "what_kind": "equipment_you_control",
                "to_kind": "creature_you_control",
            })],
            cost={"taps_self": True},
            raw_text="{T}: Lege eine Ziel-Ausrüstung, die du kontrollierst, an eine "
                     "Zielkreatur an, die du kontrollierst.",
        ),
    ]


register("Brass Squire", _brass_squire)


def _halvar_god_of_battle() -> list[AbilitySpec]:
    """Creatures you control that are enchanted or equipped have double
    strike.
    At the beginning of each combat, you may attach target Aura or Equipment
    attached to a creature you control to target creature you control.

    — Halvar, God of Battle. Brass Squire's clause widened to Auras, via the
    new ``attached_aura_or_equipment_you_control`` target kind — narrower
    than a bare "Equipment you control" in both directions: the attachment
    must already be on something, and that host must be yours.

    The static half uses the shipped layer-6 `grant_keyword` with the
    existing "enchanted or equipped" group selector, so it needed nothing
    new. The card is a DFC (// Sword of the Realms); registering the front
    face's own name is enough — `specs_for` falls back to the pre-"//" name.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "enchanted_or_equipped_creatures_you_control",
                "keywords": ["double strike"],
            })],
            raw_text="Kreaturen, die du kontrollierst und die verzaubert oder "
                     "ausgerüstet sind, haben Doppelschlag.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control",
                "to_kind": "creature_you_control",
            })],
            optional=True,
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}},
            raw_text="Zu Beginn jedes Kampfes kannst du eine Ziel-Aura oder "
                     "Ziel-Ausrüstung, die an einer Kreatur unter deiner Kontrolle "
                     "angelegt ist, an eine Zielkreatur anlegen, die du "
                     "kontrollierst.",
        ),
    ]


register("Halvar, God of Battle", _halvar_god_of_battle)


def _archdruids_charm() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for a creature or land card and reveal it. Put it
      onto the battlefield tapped if it's a land card. Otherwise, put it
      into your hand. Then shuffle.
    • Put a +1/+1 counter on target creature you control. It deals damage
      equal to its power to target creature you don't control.
    • Exile target artifact or enchantment.

    — Archdruid's Charm. The second mode is the third user of
    `extra_target_specs`, and has to be one atomic effect for a reason the
    other two don't: the damage is read off the *first* target **after** the
    counter lands (RULE 613's layer pass runs in between — putting the
    counter on first is the entire point), so no separate `DealDamageEffect`
    could ever see the boosted power.

    The first mode's *conditional* destination is `SearchLibraryEffect`'s
    ``destination_if``: unlike the positional ``destinations`` list (which
    is fixed when the search opens — Cultivate's "one tapped, one to hand"),
    this branches on the card the player actually found, which is the only
    way to express "onto the battlefield tapped **if it's a land card**.
    Otherwise, put it into your hand."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": ["Creature", "Land"]},
                        "destination": "hand",
                        "destination_if": [
                            {"criteria": {"type": "Land"},
                             "destination": "battlefield_tapped"},
                        ],
                        "count": 1,
                    })],
                    [EffectSpec("counter_then_fightlike_damage", {"counters": 1})],
                    [EffectSpec("exile", {"target_kind": "artifact_or_enchantment"})],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach einer Kreaturen- oder Landkarte.",
                    "Lege eine +1/+1-Marke auf eine Zielkreatur, die du kontrollierst. "
                    "Sie fügt einer Zielkreatur, die du nicht kontrollierst, Schaden "
                    "in Höhe ihrer Stärke zu.",
                    "Exiliere ein Zielartefakt oder eine Zielverzauberung.",
                ],
            },
            raw_text="Wähle eins — Durchsuche deine Bibliothek nach einer Kreaturen- "
                     "oder Landkarte; oder lege eine +1/+1-Marke auf eine Zielkreatur, "
                     "die du kontrollierst, und sie fügt einer Zielkreatur, die du "
                     "nicht kontrollierst, Schaden in Höhe ihrer Stärke zu; oder "
                     "exiliere ein Zielartefakt oder eine Zielverzauberung.",
        ),
    ]


register("Archdruid's Charm", _archdruids_charm)


def _dauntless_dismantler() -> list[AbilitySpec]:
    """Artifacts your opponents control enter tapped.
    {X}{X}{W}, Sacrifice this creature: Destroy each artifact with mana
    value X.

    — Dauntless Dismantler. The static half was *already* covered by the
    shipped board-wide ``enters_tapped`` static (`continuous.
    enters_tapped_from_static`) — only the activated ability left the card
    unmodeled.

    That ability needed a mass destroy whose **filter** is the ability's own
    announced X rather than a printed constant: the shipped
    `DestroyEffect`'s ``max_mana_value`` is a printed cap, while this is an
    exact match on a value known only at activation. Threaded through the
    same ``"x"`` sentinel `RulesEngine._substitute_x` rewrites for every
    other X-scaled magnitude — including the ``{X}{X}`` cost, which the mana
    model already doubles correctly.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("enters_tapped_static", {
                "affects": "opponents_permanents",
                "card_type": "artifact",
            })],
            raw_text="Artefakte, die deine Gegner kontrollieren, kommen getappt ins "
                     "Spiel.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy_each_with_mana_value", {
                "amount": "x", "card_type": "artifact",
            })],
            cost={"text": "{X}{X}{W}", "sacrifice": "self"},
            raw_text="{X}{X}{W}, Opfere diese Kreatur: Zerstöre jedes Artefakt mit "
                     "Manawert X.",
        ),
    ]


register("Dauntless Dismantler", _dauntless_dismantler)


def _pemmins_aura() -> list[AbilitySpec]:
    """Enchant creature
    {U}: Untap enchanted creature.
    {U}: Enchanted creature gains flying until end of turn.
    {U}: Enchanted creature gains shroud until end of turn.
    {1}: Enchanted creature gets +1/-1 or -1/+1 until end of turn.

    — Pemmin's Aura. The first three lines already parse; the fourth was the
    "inline two-way modal with no bulleted header" the blocker list named —
    "A or B" in a single sentence, which the RULE 700.2 modal grammar (built
    for the bulleted block) doesn't recognize.

    Modeled as **two separate activated abilities**, one per half, rather
    than one ability with a RULE 700.2 mode choice: `modes` is only
    supported on spell/triggered abilities (an *activated* ability has no
    mode-choice window in this engine), and splitting is a faithful model
    anyway — the player's choice of which ability to activate *is* the
    printed choice, made at the same moment, with the same result. That
    keeps the card fully playable without inventing an activation-time mode
    prompt no other card needs.

    The oracle-text front-end now recognizes that shape itself
    (`segmenter._inline_pt_modal_bodies`, which rebuilds "gets A or B" as
    two complete clauses and emits one activated ability each), so this
    entry is no longer load-bearing — it's left registered rather than
    deleted, the same "no harm in both existing side by side" call the
    `top_library_permission` entries document, since the hand-authored
    registry always wins for a registered card and the two agree.
    """
    def pump(power: int, toughness: int) -> EffectSpec:
        """One half of the printed "+1/-1 or -1/+1", acting on whatever the
        Aura is currently attached to (RULE 303.4)."""
        return EffectSpec("pump", {
            "power": power, "toughness": toughness,
            "target_kind": "attached_permanent",
        })

    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "attached_permanent"})],
            cost={"text": "{U}"},
            raw_text="{U}: Enttappe die verzauberte Kreatur.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["flying"],
                "target_kind": "attached_permanent",
            })],
            cost={"text": "{U}"},
            raw_text="{U}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "Fliegend.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["shroud"],
                "target_kind": "attached_permanent",
            })],
            cost={"text": "{U}"},
            raw_text="{U}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "Schutzlosigkeit.",
        ),
        AbilitySpec(
            "activated",
            [pump(1, -1)],
            cost={"text": "{1}"},
            raw_text="{1}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "+1/-1.",
        ),
        AbilitySpec(
            "activated",
            [pump(-1, 1)],
            cost={"text": "{1}"},
            raw_text="{1}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "-1/+1.",
        ),
    ]


register("Pemmin's Aura", _pemmins_aura)


def _dress_down() -> list[AbilitySpec]:
    """Flash
    When this enchantment enters, draw a card.
    Creatures lose all abilities.
    At the beginning of the end step, sacrifice this enchantment.

    — Dress Down. All three abilities were individually expressible — the
    board-wide ability strip is the shipped ``remove_all_abilities`` layer-6
    static (RULE 613.7f) — but the card was left unregistered, so the
    fail-closed coverage gate gave it nothing. Flash comes from the RULE 702
    keyword catalogue.

    Note the ordering that makes the card work: the ETB draw is a triggered
    ability that goes on the stack *before* the strip is ever consulted, and
    the strip doesn't remove the enchantment's own abilities (it names
    creatures), so the end-step sacrifice still fires.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            raw_text="Wenn diese Verzauberung ins Spiel kommt, ziehe eine Karte.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("remove_all_abilities", {"affects": "all_creatures"})],
            raw_text="Kreaturen verlieren alle Fähigkeiten.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
            raw_text="Zu Beginn des Endsegments opfere diese Verzauberung.",
        ),
    ]


register("Dress Down", _dress_down)


def _professor_onyx() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    each opponent loses 2 life and you gain 2 life.
    +1: You lose 1 life. Look at the top three cards of your library. Put
    one of them into your hand and the rest into your graveyard.
    −3: Each opponent sacrifices a creature with the greatest power among
    creatures that player controls.
    −8: Each opponent may discard a card. If they don't, they lose 3 life.
    Repeat this process six more times.

    — Professor Onyx. Magecraft already parsed; the three loyalty abilities
    are hand-authored here.

    The −3 needed one narrow extension: `SacrificeEffect` gained
    ``greatest_power``, because this is the one place the engine's
    non-interactive "first matching permanent" auto-pick would be actively
    *wrong* rather than merely uninteresting — the card's whole effect is
    that the sacrificing player can't dodge with a spare token. It also
    gained an ``each_opponent`` selector and a registry entry (it had only
    ever been reachable from the annihilator keyword).

    **Documented simplification**: the −8's "each opponent may discard a
    card. If they don't, they lose 3 life. Repeat six more times." is
    modeled as seven rounds of a straight discard-or-lose-3, resolved
    non-interactively (discard if able, else lose the life) rather than as
    seven interactive `pay_cost_then` prompts per opponent — the outcome is
    identical for any opponent with cards, and an empty-handed one loses the
    life either way. Tracked in `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("lose_life", {"amount": 1, "player": "controller"}),
                EffectSpec("impulsive_look", {
                    "count": 3, "criteria": "", "hit_destination": "hand",
                    "miss_destination": "graveyard", "optional": False,
                }),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Du verlierst 1 Lebenspunkt. Schaue dir die obersten drei "
                     "Karten deiner Bibliothek an. Nimm eine davon auf die Hand und "
                     "lege den Rest auf deinen Friedhof.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {
                "count": 1, "what": "creature",
                "selector": "each_opponent", "greatest_power": True,
            })],
            cost={"loyalty": -3},
            raw_text="−3: Jeder Gegner opfert eine Kreatur mit der höchsten Stärke "
                     "unter den Kreaturen, die er kontrolliert.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("discard_or_lose_life", {
                "count": 1, "amount": 3, "times": 7, "selector": "each_opponent",
            })],
            cost={"loyalty": -8},
            raw_text="−8: Jeder Gegner kann eine Karte abwerfen. Falls er dies nicht "
                     "tut, verliert er 3 Lebenspunkte. Wiederhole diesen Vorgang "
                     "sechsmal.",
        ),
    ]


register("Professor Onyx", _professor_onyx)


def _tevesh_szat_doom_of_fools() -> list[AbilitySpec]:
    """+2: Create two 0/1 black Thrull creature tokens.
    +1: You may sacrifice another creature or planeswalker. If you do, draw
    two cards, then draw another card if the sacrificed permanent was a
    commander.
    −10: Gain control of all commanders. Put all commanders from the command
    zone onto the battlefield under your control.

    — Tevesh Szat, Doom of Fools. The token and draw halves are shipped
    primitives; only the −10 needed a new one (`gain_control_of_all_
    commanders`), which is a genuinely Commander-specific effect with no
    near-miss anywhere in the engine: RULE 903.3's command-zone-to-
    battlefield move under someone *else's* control, across every player.

    The +1 is the first user of the general `ChooseObjectsEffect`: "you
    **may** sacrifice another creature or planeswalker" is a real choice
    now, and both of its conditional tails ride the chooser's own
    ``then``/``then_if_commander`` follow-ups — the draw only happens "if
    you do", and RULE 903's extra card only when the thing sacrificed was a
    commander, neither of which can be known before the pick is made.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 2, "name": "Thrull", "power": 0, "toughness": 1,
                "colors": ["B"], "subtypes": ["Thrull"],
            })],
            cost={"loyalty": 2},
            raw_text="+2: Erzeuge zwei 0/1 schwarze Thrull-Kreaturenspielsteine.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("choose_objects", {
                    "action": "sacrifice",
                    "what": "creature_or_planeswalker",
                    "count": 1,
                    "optional": True,
                    "exclude_self": True,
                    "prompt": "Tevesh Szat: Wähle eine Kreatur oder einen Planeswalker "
                              "zum Opfern",
                    "then": [{"type": "draw", "params": {"count": 2}}],
                    "then_if_commander": [{"type": "draw", "params": {"count": 1}}],
                }),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Du kannst eine andere Kreatur oder einen anderen Planeswalker "
                     "opfern. Falls du dies tust, ziehe zwei Karten. Falls ein "
                     "Kommandeur auf diese Weise geopfert wurde, ziehe eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_control_of_all_commanders", {})],
            cost={"loyalty": -10},
            raw_text="−10: Erlange die Kontrolle über alle Kommandeure. Bringe alle "
                     "Kommandeure aus der Kommandozone unter deiner Kontrolle ins "
                     "Spiel.",
        ),
    ]


register("Tevesh Szat, Doom of Fools", _tevesh_szat_doom_of_fools)


def _jeska_thrice_reborn() -> list[AbilitySpec]:
    """Jeska enters with a loyalty counter on her for each time you've cast a
    commander from the command zone this game.
    0: Choose target creature. Until your next turn, if that creature would
    deal combat damage to one of your opponents, it deals triple that damage
    to that player instead.
    −X: Jeska deals X damage to each of up to three targets.

    — Jeska, Thrice Reborn. Two of the three lines ride shipped primitives:
    the entry counters read `Player.commander_casts` (already tracked for
    RULE 903.8's commander tax — no new state), and the −X is the shipped
    divided-damage shape with ``count=3``/``optional=True``.

    The 0 is the interesting one: it's a **targeted, duration-bounded damage
    multiplier**, which the shipped RULE 616.1 ``double_damage`` replacement
    family (Furnace of Rath/Fiery Emancipation — standing, board-wide,
    permanent-sourced) could *almost* express. Rather than a new mechanism
    it reuses that family's `multiplier` param with two new scopes the
    family already wanted: a specific source instance, and "combat damage to
    an opponent of the effect's controller" — installed as a turn-scoped
    `ReplacementEffect` on the targeted creature, the same
    `RegenerateEffect`-shaped per-object shield the engine already uses.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("multiply_damage_from_target", {
                "multiplier": 3, "combat_only": True, "to": "opponents",
            })],
            cost={"loyalty": 0},
            raw_text="0: Wähle eine Zielkreatur. Bis zu deinem nächsten Zug fügt sie "
                     "einem deiner Gegner dreifachen Kampfschaden zu.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "any", "count": 3,
                "optional": True, "divided": False,
            })],
            cost={"loyalty": "-x"},
            raw_text="−X: Jeska fügt bis zu drei Zielen jeweils X Schaden zu.",
        ),
    ]


register("Jeska, Thrice Reborn", _jeska_thrice_reborn)


def _delver_of_secrets() -> list[AbilitySpec]:
    """At the beginning of each upkeep, look at the top card of your
    library. You may reveal that card. If an instant or sorcery card is
    revealed this way, transform Delver of Secrets.

    — Delver of Secrets. RULE 712's one still-open template
    (`docs/implementation-state/BACKLOG.md` called it out by name): a *conditional*
    transform gated on a library-peek rather than RULE 731's day/night
    spells-cast count. `RevealTopThenTransformEffect` (`game/effects.py`)
    is the new general-purpose primitive — it takes a `models.card_query`
    criteria dict, so any future card sharing this exact template ("look at
    the top card…, if it's a[n] X card, transform ~") reuses it instead of
    a bespoke class. The "reveal" and "may" in the printed text don't
    change any actual decision here (the check is unconditional on what's
    really on top, and there's no consequence to *not* revealing it since
    nothing else looks at it), so both are simplifications with no
    observable difference to a solo player. Fires on every player's
    upkeep, not just its controller's, and reads *its own controller's*
    library regardless of whose upkeep triggered it, exactly like Tangle
    Wire's "each player's upkeep" trigger reads "that player" for its own
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_transform", {
                "criteria": {"type": ["instant", "sorcery"]},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text="Zu Beginn eines jeden Versorgungssegments schau dir die oberste "
                     "Karte deiner Bibliothek an. Du kannst diese Karte offenlegen. "
                     "Falls auf diese Weise eine Spontanzauber- oder Hexereikarte "
                     "offengelegt wird, wandle Delver of Secrets um.",
        ),
    ]


register("Delver of Secrets", _delver_of_secrets)
