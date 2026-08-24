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
`RulesEngine`'s battlefield-entry paths. `kicker_x_mana_restriction(card)`
is the same split again, for Kicker's own ``{X}`` payment restriction
(`parser.oracle.catalogue.kicker_mana`, PAR-7), resolved by
`GameEngine.can_cast`/`cast_spell`. `opening_hand_battlefield_permission
(card)` is the same split for RULE 103.6a's "you may begin the game with
it on the battlefield" pregame permission (`parser.oracle.catalogue.
opening_hand`, PLR-11), resolved by `services/game_session.py`'s
opening-hand handling; `pregame_setup_permission(card)` generalizes it to
that module's conditional/graveyard shapes (Gemstone Caverns/Buried Ogre).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..models.events import EventType
from ..parser.oracle.catalogue.counters import entry_counters as _entry_counters
from ..parser.oracle.catalogue.keywords import parse_keywords
from ..parser.oracle.catalogue.kicker_mana import kicker_x_mana_restriction as _kicker_x_mana_restriction
from ..parser.oracle.catalogue.lands import land_tap_condition as _land_tap_condition
from ..parser.oracle.catalogue.opening_hand import (
    opening_hand_battlefield_permission as _opening_hand_battlefield_permission,
    PregameSetupPermission,
    pregame_setup_permission as _pregame_setup_permission,
)
from ..parser.oracle.gate import parse_oracle
from ..parser.oracle.spec import AbilitySpec, EffectSpec

#: name (lowercased) → factory producing that card's specs, fresh each call.
_REGISTRY: dict[str, Callable[[], list[AbilitySpec]]] = {}


def register(name: str, factory: Callable[[], list[AbilitySpec]]) -> None:
    """Register a card's ability specs under its (case-insensitive) name."""
    _REGISTRY[name.strip().lower()] = factory


def is_registered(name: str) -> bool:
    """Whether ``name`` (a card's own ``.name``) has a catalogue entry.

    Mirrors `specs_for`'s own DFC/MDFC/split "//" front-face fallback — a
    card registered under its front face's name alone (Halvar, God of
    Battle // Sword of the Realms is registered as just "Halvar, God of
    Battle") must still report registered when looked up by its full
    combined name, or a caller that only checks this (e.g. `api/cards.py`'s
    coverage badge) wrongly reports a fully-bound card as unmodeled.
    """
    lowered = name.strip().lower()
    if lowered in _REGISTRY:
        return True
    return "//" in lowered and lowered.split("//")[0].strip() in _REGISTRY


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


def opening_hand_battlefield_permission(card: Any) -> bool:
    """Whether ``card`` may begin the game on the battlefield straight from
    a kept opening hand (RULE 103.6a — "If this card is in your opening
    hand, you may begin the game with it on the battlefield.", the Leyline
    cycle). A pregame setup permission, not a static or resolve-time
    effect, so it doesn't go through the `EffectRegistry`/binder pipeline
    at all — `services/game_session.py`'s opening-hand handling in
    `_keep_hand` reads this directly once every seat has kept.

    Delegates to `parser.oracle.catalogue.opening_hand` (the coverage
    gate's single source of truth for this clause shape), the same split
    `land_tap_condition`/`entry_counters` use.
    """
    return _opening_hand_battlefield_permission(card)


def pregame_setup_permission(card: Any) -> Optional[PregameSetupPermission]:
    """``card``'s RULE 103.6 pregame setup permission, generalizing
    `opening_hand_battlefield_permission` above to the two conditional/
    costed shapes it deliberately left unclaimed: Gemstone Caverns'
    "...and you're not the starting player...with a luck counter on it. If
    you do, exile a card from your hand." and Buried Ogre's "...in your
    graveyard. If you do, you lose N life." — or ``None`` if ``card`` has
    no pregame setup permission at all.

    Delegates to `parser.oracle.catalogue.opening_hand` (the coverage
    gate's single source of truth for these clause shapes), the same split
    `land_tap_condition`/`entry_counters` use. `services/game_session.py`'s
    opening-hand handling reads this instead of the plain boolean above so
    it can check a permission's own `PregameSetupPermission.condition`
    against who the starting player is before ever queuing the choice.
    """
    return _pregame_setup_permission(card)


def kicker_x_mana_restriction(card: Any) -> Optional[str]:
    """``card``'s Kicker-own-``{X}`` payment restriction (RULE 605.3a-style,
    PAR-7 — Emblazoned Golem's "Spend only colored mana on X. No more than
    one mana of each color may be spent this way."), or ``None`` for an
    ordinary/no-``{X}`` Kicker cost. ``"distinct_colors"`` is the one
    recognized value today, consulted by `GameEngine.can_cast`/`cast_spell`
    via `models.mana_pool.ManaPool.can_pay_distinct_colors`/
    `pay_distinct_colors`.

    Delegates to `parser.oracle.catalogue.kicker_mana` (the coverage gate's
    single source of truth for this clause shape), the same split
    `entry_counters` above uses.
    """
    return _kicker_x_mana_restriction(card)


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


def _sakashima_of_a_thousand_faces() -> list[AbilitySpec]:
    """You may have Sakashima enter as a copy of another creature you
    control, except it has Sakashima's other abilities.
    The "legend rule" doesn't apply to permanents you control.

    — MEC-12 (cEDH staples 2). Two specs: the ordinary `enter_as_copy`
    replacement (``target_kind="creature_you_control"``,
    ``keep_own_abilities=True`` — RULE 706.2 would otherwise erase
    Sakashima's own printed abilities entirely, but the "except" clause adds
    them back onto the copy, snapshotted before the copy runs and reattached
    after in `resolve_enter_as_copy_choice`); and a standing
    `ignore_legend_rule` static (RULE 704.5j) so two same-named legendary
    permanents — Sakashima-as-a-copy and the original it copied, or any
    other pair — can coexist under its controller. Partner is already
    parser-claimed for free.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_control", "keep_own_abilities": True,
            })],
            raw_text="Du kannst Sakashima als Kopie einer anderen Kreatur unter deiner "
                      "Kontrolle ins Spiel kommen lassen, außer dass es Sakashimas "
                      "andere Fähigkeiten besitzt.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("ignore_legend_rule", {"affects": "you"})],
            raw_text='Die "Legendenregel" gilt nicht für Bleibende Karten unter deiner '
                      "Kontrolle.",
        ),
    ]


register("Sakashima of a Thousand Faces", _sakashima_of_a_thousand_faces)


def _mockingbird() -> list[AbilitySpec]:
    """Flying
    You may have this creature enter as a copy of any creature on the
    battlefield with mana value less than or equal to the amount of mana
    spent to cast this creature, except it's a Bird in addition to its
    other types and it has flying.

    — MEC-12 (cEDH staples 2). Flying is already parser-claimed for free;
    the `enter_as_copy` replacement carries the rest —
    ``max_mana_value_from_mana_spent`` reads `GameObject.mana_spent_to_cast`
    live when the choice is offered (an {X} creature spell, so the real cap
    is whatever {X} the caster chose), ``add_subtypes``/``add_keywords`` the
    "except" clause.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "max_mana_value_from_mana_spent": True,
                "add_subtypes": ["Bird"], "add_keywords": ["Flying"],
            })],
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Kreatur mit "
                      "einem Manawert kleiner oder gleich der Menge an Mana, die für "
                      "diese Kreatur bezahlt wurde, ins Spiel kommen lassen, außer dass "
                      "sie zusätzlich zu ihren anderen Typen ein Vogel ist und Flugfähigkeit hat.",
        ),
    ]


register("Mockingbird", _mockingbird)


def _flesh_duplicate() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of any creature on the
    battlefield, except it has vanishing 3 if that creature doesn't have
    vanishing.

    — MEC-12 (cEDH staples 2). ``add_keywords_if_target_lacks`` is checked
    against the *target*'s own printed keywords in `resolve_enter_as_copy_
    choice` before the copy runs, so a creature that already has Vanishing
    (of any N) isn't granted a second, conflicting instance.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature",
                "add_keywords_if_target_lacks": ["Vanishing 3"],
            })],
            raw_text="Du kannst diese Kreatur als Kopie einer beliebigen Kreatur ins "
                      "Spiel kommen lassen, außer dass sie Verblassen 3 besitzt, falls "
                      "diese Kreatur nicht bereits Verblassen besitzt.",
        ),
    ]


register("Flesh Duplicate", _flesh_duplicate)


def _imposter_mech() -> list[AbilitySpec]:
    """You may have this Vehicle enter as a copy of a creature an opponent
    controls, except it's a Vehicle artifact with crew 3 and it loses all
    other card types.
    Crew 3

    — MEC-12 (cEDH staples 2). The printed "Crew 3" (own copy, before any
    "enters as a copy" choice) is already parser-claimed for free; the
    "except" clause needs `only_types` (RULE 706.2's copiable card types
    replaced wholesale, not appended — `Card.as_copy` moves the copied
    creature's power/toughness to the vehicle-style slot since a
    non-creature can't carry plain `power`/`toughness`) plus `add_subtypes`
    for the Vehicle subtype and `add_keywords` to re-grant "Crew 3" itself,
    since RULE 707.2 would otherwise replace it with the copied creature's
    text (which has no Crew line of its own).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_dont_control",
                "only_types": ["Artifact"], "add_subtypes": ["Vehicle"],
                "add_keywords": ["Crew 3"],
            })],
            raw_text="Du kannst dieses Fahrzeug als Kopie einer Kreatur, die ein Gegner "
                      "kontrolliert, ins Spiel kommen lassen, außer dass es ein Fahrzeug-"
                      "Artefakt mit Mannschaft 3 ist und alle anderen Kartentypen verliert.",
        ),
    ]


register("Imposter Mech", _imposter_mech)


def _emiel_the_blessed() -> list[AbilitySpec]:
    """{3}: Exile another target creature you control, then return it to
    the battlefield under its owner's control.
    Whenever another creature you control enters, you may pay {G/W}. If
    you do, put a +1/+1 counter on it. If it's a Unicorn, put two +1/+1
    counters on it instead.

    — MEC-12 (cEDH staples). The activated ability is the plain
    `"blink"` `EffectSpec` (`BlinkEffect`, the same primitive Ephemerate/
    Restoration Angel use) with an explicit {3} cost, scoped to
    ``other_creature_you_control`` (targeting already excludes the source
    regardless — "another" needs no separate kind). The trigger is
    `pay_cost_then` wrapping `add_counters`'s ``trigger_subject_key``
    (targets whichever creature just entered — "it"), with the new
    ``amount_if_trigger_subject_subtype``/``_value`` override for "if it's
    a Unicorn, `<bigger effect>` instead" — a genuinely new, narrowly-
    scoped param, not the general "if X, A instead of B" primitive
    (`BACKLOG.md`'s kicker "instead" note is still open).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("blink", {"target_kind": "other_creature_you_control"})],
            cost={"mana": "{3}"},
            raw_text="{3}: Exiliere eine andere Zielkreatur, die du kontrollierst, und "
                     "bringe sie dann unter der Kontrolle ihres Besitzers auf das "
                     "Schlachtfeld zurück.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{G/W}",
                "remember_trigger_subject": True,
                "effects": [{
                    "type": "add_counters",
                    "params": {
                        "amount": 1, "kind": "+1/+1", "trigger_subject_key": "remembered",
                        "amount_if_trigger_subject_subtype": ["unicorn"],
                        "amount_if_trigger_subject_subtype_value": 2,
                    },
                }],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": True},
            },
            raw_text="Immer wenn eine andere Kreatur, die du kontrollierst, ins Spiel "
                     "kommt, darfst du {G/W} bezahlen. Falls du dies tust, lege einen "
                     "+1/+1-Zählmarke auf sie. Falls es sich um ein Einhorn handelt, "
                     "lege stattdessen zwei +1/+1-Zählmarken auf sie.",
        ),
    ]


register("Emiel the Blessed", _emiel_the_blessed)


def _aven_mindcensor() -> list[AbilitySpec]:
    """Flying
    If an opponent would search a library, that player searches the top
    four cards of that library instead.

    — MEC-12 (cEDH Rocco/staples/staples 2). Flying is already
    parser-claimed for free; the static half is the new
    `grant_search_limited_to_top_n` (RULE 701.19a-adjacent narrowing, not
    `grant_search_prohibited`'s outright block) — `RulesEngine.
    _search_zone_objects` scans for it exactly where `request_search`
    already scans for the prohibition.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_search_limited_to_top_n", {"n": 4})],
            raw_text="Falls ein Gegner eine Bibliothek durchsuchen würde, "
                     "durchsucht dieser Spieler stattdessen die obersten vier "
                     "Karten dieser Bibliothek.",
        ),
    ]


register("Aven Mindcensor", _aven_mindcensor)


def _phyrexian_revoker() -> list[AbilitySpec]:
    """As this creature enters, choose a nonland card name.
    Activated abilities of sources with the chosen name can't be activated.

    — MEC-12 (cEDH staples/staples 2). The new free-text `ChooseCardName
    Replacement` (a fourth RULE 601.2b `enter_choice_effects` sibling of
    the creature-type/colour/named-mode pickers — naming any card isn't an
    enumerable option list) feeds `activation_prohibition`'s new
    `card_name_from_source` selector, the naming-choice sibling of that
    static's existing `subtype_from_source`/`color_from_source`. Unlike
    Pithing Needle below, this one is unconditional — no mana-ability
    carve-out at all, so naming a mana dork silences its mana ability too.
    The printed "nonland" restriction on the *choice itself* isn't
    enforced (this engine's naming choices are never validated against
    real card data — `RulesEngine.request_name_card` accepts any string
    the same way); naming a land simply matches nothing, same as any other
    name that happens not to be on the board.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_card_name_on_enter", {})],
            raw_text="Wähle beim Ins-Spiel-Kommen dieser Kreatur einen "
                     "Namen einer nichtländischen Karte.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "all_permanents",
                "card_name_from_source": True,
            })],
            raw_text="Aktivierte Fähigkeiten von Quellen mit dem gewählten Namen "
                     "können nicht aktiviert werden.",
        ),
    ]


register("Phyrexian Revoker", _phyrexian_revoker)


def _pithing_needle() -> list[AbilitySpec]:
    """As this artifact enters, choose a card name.
    Activated abilities of sources with the chosen name can't be activated
    unless they're mana abilities.

    — MEC-12 (cEDH staples/staples 2), Phyrexian Revoker's own artifact
    sibling — same naming-choice mechanism, but unrestricted (any card, not
    just nonland) and with the mana-ability carve-out `activation_
    prohibition`'s ``except_mana_abilities`` rider already provides
    (Kasmina's Transmutation/Imprisoned in the Moon's own shape).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_card_name_on_enter", {})],
            raw_text="Wähle beim Ins-Spiel-Kommen von Pfählende Nadel einen "
                     "Kartennamen.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "all_permanents",
                "card_name_from_source": True,
                "except_mana_abilities": True,
            })],
            raw_text="Aktivierte Fähigkeiten von Quellen mit dem gewählten Namen "
                     "können nicht aktiviert werden, außer es handelt sich um "
                     "Manafähigkeiten.",
        ),
    ]


register("Pithing Needle", _pithing_needle)


def _defense_grid() -> list[AbilitySpec]:
    """Each spell costs {3} more to cast except during its controller's turn.

    — MEC-12 (cEDH staples/staples 2). A genuinely new `cost_reduction`
    rider, `except_caster_own_turn` — "its controller" means the *taxed
    spell's own caster*, not Defense Grid's controller, so it can't reuse
    the ordinary ability-source-relative `active_if`/`your_turn` gate the
    way Tithe Taker's own "during your turn" clause does; `continuous.
    cost_reduction_for` checks it directly against its own ``player``
    argument instead.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells", "generic": 3, "increase": True,
                "except_caster_own_turn": True,
            })],
            raw_text="Jeder Zauberspruch kostet {3} mehr, außer während der "
                     "Runde seines Kontrolleurs.",
        ),
    ]


register("Defense Grid", _defense_grid)


def _suppression_field() -> list[AbilitySpec]:
    """Activated abilities cost {2} more to activate unless they're mana
    abilities.

    — MEC-12 (cEDH staples 2). `activation_cost_reduction_for` previously
    only ever supported a *reduction*, scoped to one of three named
    selectors (attached/subtype/card_type) — this needed all three widened
    at once: a signed net that can tax as well as discount
    (`GameEngine._reduced_activation_mana`'s new `increase_generic` branch,
    mirroring `CastingMixin._adjust_cost`'s existing spell-side handling), a
    genuinely unscoped ``affects="all_permanents"`` selector, and
    `activation_prohibition`'s own ``except_mana_abilities``/
    ``is_mana_ability`` rider threaded through the whole activation-cost
    call chain (`_can_pay_activation_cost`/`_pay_activation_cost`/
    `tap_for_mana`) so a mana ability is actually exempt rather than taxed
    twice over (once here, and it would have been wrong either way).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "affects": "all_permanents",
                "generic": 2, "increase": True, "except_mana_abilities": True,
            })],
            raw_text="Aktivierte Fähigkeiten kosten {2} mehr, außer es handelt "
                     "sich um Manafähigkeiten.",
        ),
    ]


register("Suppression Field", _suppression_field)


def _tithe_taker() -> list[AbilitySpec]:
    """During your turn, spells your opponents cast cost {1} more to cast
    and abilities your opponents activate cost {1} more to activate unless
    they're mana abilities.
    Afterlife 1 (When this creature dies, create a 1/1 white and black
    Spirit creature token with flying.)

    — MEC-12 (cEDH staples 2). Combines Defense Grid's tax shape (spells)
    and Suppression Field's (activations) with the *ordinary*,
    ability-source-relative "during your turn" gate (`active_if={"kind":
    "your_turn"}`, unlike Defense Grid's own caster-relative rider) and the
    opponents-only scope both `cost_reduction_for`/`activation_cost_
    reduction_for` already had for a reduction (Grand Arbiter Augustin IV/
    Training Grounds-shaped) but had never combined with a tax before.
    Afterlife is a plain already-bound keyword — hand-authoring this card's
    other two clauses doesn't drop it (keyword binding runs independently
    of `specs_for`'s registry precedence).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "opponents_spells", "generic": 1, "increase": True,
                "active_if": {"kind": "your_turn"},
            })],
            raw_text="Während deiner Runde kosten Zaubersprüche, die deine "
                     "Gegner wirken, {1} mehr.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "affects": "opponents_permanents",
                "generic": 1, "increase": True, "except_mana_abilities": True,
                "active_if": {"kind": "your_turn"},
            })],
            raw_text="Während deiner Runde kosten Fähigkeiten, die deine "
                     "Gegner aktivieren, {1} mehr, außer es handelt sich um "
                     "Manafähigkeiten.",
        ),
    ]


register("Tithe Taker", _tithe_taker)


def _solitude() -> list[AbilitySpec]:
    """Flash
    Lifelink
    When this creature enters, exile up to one other target creature. That
    creature's controller gains life equal to its power.
    Evoke — Exile a white card from your hand.

    — MEC-12 (cEDH staples 2). Flash/Lifelink are already-bound printed
    keywords. The new `GainLifeEffect.recipient="target_controller"` reads
    the same shared exile target `amount_from_target_power` already reads
    (RULE 608.2 — one target requirement gathered once, both effects in
    this trigger share it) — for *who* receives the life, not just how
    much; without it an untargeted `gain_life` falls back to this
    creature's own controller, not the exiled creature's. Evoke isn't
    modeled — same documented simplification as Endurance's own entry (no
    alternative-cast-cost mechanism for it, unlike Kicker/Buyback which
    `cast_spell` already threads): Solitude is only hard-castable at its
    full {3}{W}{W}, but its ETB fully functions either way. "Target
    creature" (unqualified by "you control"/"you don't control") already
    excludes the source itself in this engine's `targeting.py` (RULE
    115's own "another" reading, not a new exclusion), matching "up to one
    **other** target creature" for free.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": "creature", "optional": True}),
                EffectSpec("gain_life", {
                    "amount_from_target_power": True, "recipient": "target_controller",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, exiliere bis zu eine "
                     "andere Zielkreatur. Deren Kontrolleur erhält Leben in "
                     "Höhe ihrer Stärke.",
        ),
    ]


register("Solitude", _solitude)


def _parallax_wave() -> list[AbilitySpec]:
    """Fading 5 (This enchantment enters with five fade counters on it. At
    the beginning of your upkeep, remove a fade counter from it. If you
    can't, sacrifice it.)
    Remove a fade counter from this enchantment: Exile target creature.
    When this enchantment leaves the battlefield, each player returns to
    the battlefield all cards they own exiled with it.

    — MEC-12 (cEDH staples 2). Fading is an already-bound keyword. The new
    `ReturnAllExiledWithEffect`/`"return_all_exiled_with"` is the mass
    sibling of the O-Ring family's `ReturnLinkedExileEffect` — reading
    `GameObject.exiled_with_ids` (MEC-21's accumulating tracker) instead of
    the single-slot `linked_exile_id`, since this activated ability can
    exile a different creature every time a fade counter is spent (up to
    five times), each potentially owned by a different player, all
    returning together the moment Parallax Wave itself leaves.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "creature", "track_exiled_with": True})],
            cost={"remove_counters": ["fade", 1]},
            raw_text="Entferne eine Marke des Verblassens von dieser "
                     "Verzauberung: Exiliere eine Zielkreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung das Schlachtfeld verlässt, bringt "
                     "jeder Spieler alle Karten, die ihm gehören und mit ihr "
                     "exiliert wurden, auf das Schlachtfeld zurück.",
        ),
    ]


register("Parallax Wave", _parallax_wave)


def _skyclave_apparition() -> list[AbilitySpec]:
    """When this creature enters, exile up to one target nonland, nontoken
    permanent you don't control with mana value 4 or less.
    When this creature leaves the battlefield, the exiled card's owner
    creates an X/X blue Illusion creature token, where X is the mana value
    of the exiled card.

    — MEC-12 (cEDH staples 2). Both clauses ride the O-Ring family's
    linkage — `ExileEffect(remember=True)` and the new
    `CreateTokenForLinkedExileEffect` (`ReturnLinkedExileEffect`'s
    token-creating sibling: same `linked_exile_id` read, but hands off to
    `GameContext.create_token` under the linked card's owner instead of
    returning it) — rather than ever returning the exiled card at all.
    `ExileEffect` gained its own `max_mana_value` this batch, the same
    target-offer-time cap `DestroyEffect` already had (`targeting.
    TargetSpec.max_mana_value`). `target_kind="nonland_permanent_you_dont_
    control"` doesn't itself exclude tokens (no ``exclude_tokens`` selector
    exists yet) — a narrow, documented simplification, the same shape as
    Leonin Relic-Warder's own `target_kind="permanent"` type-union
    simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent_you_dont_control",
                "optional": True, "remember": True, "max_mana_value": 4,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, exiliere bis zu eine "
                     "Ziel-nichtland-Permanente, die du nicht kontrollierst, "
                     "mit Manawert 4 oder weniger.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token_for_linked_exile", {
                "colors": ["U"], "subtypes": ["Illusion"],
            })],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, erschafft "
                     "der Besitzer der exilierten Karte eine X/X blaue "
                     "Illusion-Kreaturenspielmarke, wobei X der Manawert der "
                     "exilierten Karte ist.",
        ),
    ]


register("Skyclave Apparition", _skyclave_apparition)


def _soul_partition() -> list[AbilitySpec]:
    """Exile target nonland permanent. For as long as that card remains
    exiled, its owner may play it. A spell cast by an opponent this way
    costs {2} more to cast.

    — MEC-12 (cEDH staples 2). `ExileEffect`'s new `grant_owner_play_
    permission`/`owner_play_permission_tax` params: the standing sibling
    of Lukka, Coppercoat Outcast's own board-gated `GameState.exile_cast_
    condition` grant (an empty condition dict always holds, per
    `static_conditions.condition_holds`'s own "no condition = always
    true") — keyed to the exiled card's *owner* rather than this spell's
    caster — plus a per-instance cost tax stamped directly onto that one
    card at exile time (`continuous.self_cost_reduction_for`'s new
    `caster_id` param, `except_same_controller_as` naming the exiler so
    only they're ever exempt from their own tax). Surfaced and fixed a
    real latent bug along the way: `legal_actions`'s own exile-zone offer
    list never checked `_has_conditional_exile_permission` at all — Lukka's
    permission worked when driven directly through `can_cast`/`cast_spell`
    in a test, but nothing had ever actually offered it as a real action,
    the same "parse-only masks real bugs" shape this project's own testing
    lesson warns about.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent",
                "grant_owner_play_permission": True,
                "owner_play_permission_tax": 2,
            })],
            raw_text="Exiliere eine Zielpermanente eines nichtländlichen "
                     "Typs. Solange diese Karte exiliert bleibt, darf ihr "
                     "Besitzer sie spielen. Ein von einem Gegner auf diese "
                     "Weise gewirkter Zauberspruch kostet {2} mehr.",
        ),
    ]


register("Soul Partition", _soul_partition)


def _abdel_adrian_gorions_ward() -> list[AbilitySpec]:
    """When Abdel Adrian enters, exile any number of other nonland
    permanents you control until Abdel Adrian leaves the battlefield.
    Create a 1/1 white Soldier creature token for each permanent exiled
    this way.
    Choose a Background (You can have a Background as a second commander.)

    — MEC-12 (cEDH staples 2), the O-Ring/exile family's last remaining
    member. The new `ExileAnyNumberYouControlEffect` is a *selection*
    among the controller's own permanents, not a RULE 115 target at all —
    `RulesEngine.request_choose_objects`'s chooser, with its own new
    `track_exiled_with=True` accumulating every pick onto `GameObject.
    exiled_with_ids`, the same field `ExileEffect(track_exiled_with=True)`
    uses. The token count is the new `exiled_with_count` count_selector
    (`continuous.count_selector`, threaded a `source` param `CreateTokenEffect`
    never passed before), freshly reading that list's length rather than a
    fixed number — "a token for each permanent exiled **this way**". The
    leaves-battlefield half reuses `ReturnAllExiledWithEffect` verbatim, no
    new code at all — built for Parallax Wave in this same batch, and
    exactly the same shape here (several permanents, each returning to
    *their own* owner, which for Abdel Adrian is always its own controller
    since it only ever exiles its own stuff). Background deckbuilding
    (choosing a second commander, RULE 903-adjacent) isn't a board-state
    mechanic and needs no engine support.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_any_number_you_control", {}),
                EffectSpec("create_token", {
                    "count_selector": "exiled_with_count",
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Abdel Adrian ins Spiel kommt, exiliere eine "
                     "beliebige Anzahl anderer nichtländischer Permanenten, "
                     "die du kontrollierst, bis Abdel Adrian das Schlachtfeld "
                     "verlässt. Erschaffe für jede auf diese Weise exilierte "
                     "Permanente eine 1/1 weiße Soldat-Kreaturenspielmarke.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Abdel Adrian das Schlachtfeld verlässt, bringt "
                     "jeder Spieler alle Karten, die ihm gehören und mit ihm "
                     "exiliert wurden, auf das Schlachtfeld zurück.",
        ),
    ]


register("Abdel Adrian, Gorion's Ward", _abdel_adrian_gorions_ward)


def _dark_confidant() -> list[AbilitySpec]:
    """At the beginning of your upkeep, reveal the top card of your
    library and put that card into your hand. You lose life equal to its
    mana value.

    — MEC-12 (cEDH staples 2). New `RevealTopThenTakeAndLoseLifeEffect` —
    deliberately not routed through `DrawCardEffect`/`RulesEngine.draw` at
    all (RULE 121.4: a card entering hand without the printed word "draw"
    isn't a draw, so it must never trip a draw-replacement/"whenever you
    draw" trigger, or count toward cards drawn this turn — load-bearing
    for this exact cluster, since Alms Collector/Notion Thief/Chains of
    Mephistopheles all key off "would draw a card").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_take_and_lose_life", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments, decke die oberste "
                     "Karte deiner Bibliothek auf und nimm diese Karte auf "
                     "deine Hand. Du verlierst Leben in Höhe ihres Manawerts.",
        ),
    ]


register("Dark Confidant", _dark_confidant)


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
    +1: Put a +1/+1 counter on up to one target Elf. Untap it. It gains
    deathtouch until end of turn.
    0: Create a 1/1 green Elf Warrior creature token.
    −6: You get an emblem with "Whenever you cast an Elf spell, it gains
    haste until end of turn and you draw two cards."

    — Tyvar Kell. The static mana grant is a layer-6 ability-adding grant
    (RULE 613.7f) — despite CR 612.1's mention of text "granted … by other
    effects", this is *not* layer 3/RULE 612 (see `game/continuous.py`'s
    module docstring); it's the same layer as `grant_keyword`, just
    granting `{"B": 1}` mana production instead of a keyword slug.
    `mana_abilities.mana_options_for` folds it onto whatever the Elf
    already taps for.

    Eliferate deck batch (all three loyalty abilities were previously
    unmodeled — hand-authoring a card wholesale-replaces the parser's own
    output, `specs_for`'s registry-wins precedence, so a static-only entry
    silently dropped them even where the parser alone could already model
    the "0:" ability). "+1:"'s combo body is
    `effects.CounterUntapGrantKeywordEffect` (put a counter, untap, grant a
    keyword — one atomic effect over one shared target, `CounterAndFirst
    StrikeEffect`'s established "avoid a second target prompt" shape,
    generalized with an untap step and a caller-chosen keyword), targeting
    `creature_filter={"subtype": "Elf"}` (any Elf, not just yours — RAW has
    no "you control" on this one). "−6:"'s emblem quotes a genuine nested
    `AbilitySpec` (RULE 114.2, the same shape the oracle-text parser's own
    `_emblem_ability_spec` builds, just constructed directly here since
    there's no card text to recursively parse) combining a new
    `effects.GrantKeywordToTriggerSubjectEffect` ("it gains haste" — RULE
    603.1's "it" pronoun resolves to whatever `SPELL_CAST` event fired the
    trigger) with a plain draw.
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [
            EffectSpec("grant_keyword_to_trigger_subject", {"keyword": "haste"}),
            EffectSpec("draw", {"count": 2}),
        ],
        trigger={
            "event": EventType.SPELL_CAST,
            "condition": {"subject": "group", "subtypes": ["elf"], "controller": "you"},
        },
        raw_text="Immer wenn du einen Elfenzauberspruch wirkst, erhält er Eile bis "
                 "zum Ende des Zuges und du ziehst zwei Karten.",
    )
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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("counter_untap_grant_keyword", {
                "creature_filter": {"subtype": "Elf"}, "keyword": "deathtouch",
            })],
            cost={"loyalty": 1},
            raw_text="+1: Lege einen +1/+1-Marke auf bis zu einen Zielelfen. Enttappe "
                     "ihn. Er erhält Todesberührung bis zum Ende des Zuges.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            cost={"loyalty": 0},
            raw_text="0: Erzeuge einen 1/1 grünen Elfen-Krieger-Kreaturenspielstein.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -6},
            raw_text='−6: Du erhältst einen Emblem-Spielstein mit "Immer wenn du einen '
                     'Elfenzauberspruch wirkst, erhält er Eile bis zum Ende des Zuges '
                     'und du ziehst zwei Karten."',
        ),
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
    honoured for casting timing, `GameEngine.can_cast`). The attacker-count
    cost reduction (MEC-6) is `cost_reduction` with `affects="self"` and
    `per="attacking_creatures_you_control"` — the same self-scoped discount
    shape Delve/Affinity already exercise via `continuous.
    self_cost_reduction_for`, read live at cast time (`GameObject.attacking`,
    RULE 508.1) so a cast after declare attackers sees the real count.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"affects": "self", "generic": 1,
                                            "per": "attacking_creatures_you_control"})],
            raw_text="Dieser Zauberspruch kostet {1} weniger, wie du für jede angreifende "
                     "Kreatur, die du kontrollierst.",
        ),
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
    abilities`). The granted "exile that creature" ability is a layer-6
    (RULE 613.7f) `grant_triggered_ability` onto the equipped creature —
    ``filter: {"combat": True, "is_player": False}`` narrows `DAMAGE` to
    combat damage dealt to a creature (not a player), and the per-firing
    "that creature" pronoun (ENG-13 — *which* creature was hit, a different
    `DAMAGE` field from the ``source_id`` that scopes *which grantee*
    reacts) is `ExileTriggerDamagedCreatureEffect`, reading the resolving
    event's own ``target_id`` off `GameContext.trigger_event` rather than a
    chosen target.
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
                EffectSpec("grant_triggered_ability", {
                    "affects": "attached_permanent",
                    "trigger_event": EventType.DAMAGE,
                    "filter": {"combat": True, "is_player": False},
                    "grant_effects": [{"type": "exile_trigger_damaged_creature", "params": {}}],
                }),
            ],
            raw_text="Ausgerüstete Kreatur erhält +5/+5 und hat Erstschlag, "
                     "Trampelschaden, Unzerstörbarkeit und Eile. \"Wenn diese Kreatur "
                     "einer Kreatur Kampfschaden zufügt, exiliere jene Kreatur.\"",
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

    — Simian Sling. The trigger's "defending player" resolves via
    `_defending_player_of`, which reads the ability's own source's
    combat-defender stamp — correct when Simian Sling itself is the
    attacking creature — and, since ENG-14, falls back to the permanent
    it's reconfigured onto when that's the one actually attacking instead
    (RULE 702.151), matching this trigger's own "this creature **or
    equipped creature**" subject scoping.
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


def _sigardas_aid() -> list[AbilitySpec]:
    """You may cast Aura and Equipment spells as though they had flash.
    Whenever an Equipment you control enters, you may attach it to target
    creature you control.

    — Sigarda's Aid. Only the second ability is modeled. RULE 603.3d's "it"
    is the Equipment that just entered — not the ability's own source
    (Sigarda's Aid itself), and not a choice — which is exactly ENG-13's
    general per-firing dynamic reference: `AttachTriggeringPermanentEffect`
    reads it off `GameContext.trigger_event`'s own ``instance_id``, the
    same field `ReturnSharedTypePermanentEffect` reads for Cloudstone
    Curio's "it". Only the destination ("target creature you control") is a
    real choice, and it's what makes the whole ability optional — declining
    the target is declining the attach, matching `CreateTokenMayAttach
    EquipmentEffect`'s own "target_spec.optional" idiom rather than a
    separate `AbilitySpec.optional` flag.

    The first ability — a *standing* cast-as-flash permission scoped to two
    card types — isn't modeled: it needs a static permission distinct from
    the existing `grant_flash_until_eot` (a one-shot "this turn" grant,
    Borne Upon a Wind-shaped), a documented gap unrelated to ENG-13.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_triggering_permanent", {
                "target_kind": "creature_you_control", "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "artifact",
                    "subtypes": ["equipment"], "controller": "you",
                },
            },
            raw_text="Wenn eine Ausrüstung, die du kontrollierst, ins Spiel kommt, "
                     "darfst du sie an eine Zielkreatur, die du kontrollierst, anlegen.",
        )
    ]


register("Sigarda's Aid", _sigardas_aid)


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

    — Timely Ward. The conditional-flash clause (MEC-7) is
    `conditional_flash={"targets_a_commander": True}`, checked live at cast
    time against the caster's actual chosen target
    (`game/condition_query.py`'s `conditional_flash_holds`); the segmenter
    recognizes this exact template too (`_CONDITIONAL_FLASH_IF_TARGETS_
    COMMANDER_RE`), but only on the instant/sorcery `allow_spell_effect`
    path — an Aura like this one still needs the hand-authored entry. Rides
    on this same spec regardless of which one carries the real (attach-
    target) effects, same "may ride on any spec" idiom `additional_cost`
    uses.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["indestructible"]})],
            conditional_flash={"targets_a_commander": True},
            raw_text="Du kannst diesen Zauberspruch wirken, als hätte er Blitzschlag, falls er einen Anführer als Ziel hat.\n"
                     "Verzauberte Kreatur hat Unzerstörbarkeit.",
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

    — Winter Orb. A static family (`continuous.active_untap_caps`,
    `GameEngine._step_untap`), distinct from `no_untap` (which restricts
    one specific *permanent*, not a global per-player cap) and from
    `enters_tapped_static`'s opponent-scoped board-wide family (this is
    unscoped by ownership). The tapped-state gate is the ordinary RULE
    613.6 ``active_if`` wrapper every other conditional static uses, not a
    hardcoded check — Static Orb/Winter Moon (`parser/oracle/catalogue/
    static_handlers.py`'s ``_UNTAP_CAP_RE``) reuse the same family,
    ``card_type``/``nonbasic`` widening it past lands-only. Auto-picks
    which land(s) stay tapped (the same non-interactive MVP simplification
    `_sacrifice_candidate`'s callers already make elsewhere).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("untap_cap", {"count": 1, "active_if": {"kind": "source_untapped"}})],
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


def _liliana_dreadhorde_general() -> list[AbilitySpec]:
    """Whenever a creature you control dies, draw a card.
    +1: Create a 2/2 black Zombie creature token.
    −4: Each player sacrifices two creatures of their choice.
    −9: Each opponent chooses a permanent they control of each permanent
    type and sacrifices the rest.

    — Liliana, Dreadhorde General. The first three abilities are exactly
    what the oracle-text parser already claims (`author_card.py reuse`) —
    pasted as-is. Only the -9 needed a hand-written spec: reframed as
    "sacrifice all but one of each type, one type at a time" —
    `EffectSpec("sacrifice", {"selector": "each_opponent", "what": <type>,
    "count": "all_but_one"})`, `effects.SacrificeEffect`'s dynamic
    ``"all_but_one"`` count sentinel (`RulesEngine.sacrifice`) — six
    separate top-level effects, one per RULE 300-ish permanent type,
    relying on `_apply_effects_partitioned`'s existing "suspend the rest
    when one effect opens a pending_choice" sequencing (RULE 608.2) to run
    them one at a time rather than a bespoke chaining structure.

    Documented simplification: real Liliana lets the *same* multi-typed
    permanent (an artifact creature, say) count as the kept pick for two
    different types in one settling; processing types independently in
    sequence here means a permanent spared by an earlier type's cut can
    still be swept by a later type's own cut if a *different* permanent is
    kept for that type instead. Unobservable for the overwhelming majority
    of real boards (single-typed permanents), and still strictly a choice
    each affected player makes themselves, never an auto-pick.
    """
    types = ["battle", "planeswalker", "creature", "land", "artifact", "enchantment"]
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
            },
            raw_text="whenever a creature you control dies, draw a card.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie"], "keywords": [], "token_name": "Zombie",
            })],
            cost={"loyalty": 1},
            raw_text="+1: create a 2/2 black zombie creature token.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature", "count": 2})],
            cost={"loyalty": -4},
            raw_text="−4: each player sacrifices 2 creatures of their choice.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("sacrifice", {"selector": "each_opponent", "what": t, "count": "all_but_one"})
                for t in types
            ],
            cost={"loyalty": -9},
            raw_text=(
                "−9: each opponent chooses a permanent they control of each "
                "permanent type and sacrifices the rest."
            ),
        ),
    ]


register("Liliana, Dreadhorde General", _liliana_dreadhorde_general)


def _mutiny() -> list[AbilitySpec]:
    """Target creature an opponent controls deals damage equal to its power
    to another target creature that player controls.

    — Mutiny. The one-sided "fight" shape `effects.DamageEqualToPowerEffect`
    already implements for Rabid Bite ("target creature you control deals
    damage equal to its power to target creature you don't control") — only
    the *dealer* here is also an opponent's creature (RULE 115.1a two
    independent `creature_you_dont_control` targets, `extra_target_specs`),
    not the caster's own.

    Documented simplification: RAW's "**that player**" ties the second
    target to the specific opponent who controls the first (only matters at
    3+ players); both targets are modeled as plain "an opponent controls"
    independently rather than tracking which specific opponent the first
    pick named — the two coincide by construction in any 2-player game, and
    no card in scope needs the distinction (no "same specific opponent"
    targeting constraint exists in this engine yet).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_equal_to_power", {
                "dealer_kind": "creature_you_dont_control",
                "target_kind": "creature_you_dont_control",
            })],
            raw_text=(
                "target creature an opponent controls deals damage equal to "
                "its power to another target creature that player controls."
            ),
        ),
    ]


register("Mutiny", _mutiny)


def _anger() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Mountain, creatures you control have haste.

    — Anger. RULE 112.7a's own printed exception: a static ability that
    explicitly functions from the graveyard rather than the battlefield
    (the "Timeshifted enemy-color cycle" — Brawn/Filth/Valor/Wonder are
    the same shape onto trample/swampwalk/first strike/flying, not in
    scope here). ``"from_graveyard": True`` is what `continuous.
    _battlefield_static_abilities` reads to scan each player's graveyard
    for this one marked ability instead of the battlefield — everything
    downstream (the layer-6 keyword grant, the "you control a Mountain"
    `active_if` gate) is the same machinery an ordinary battlefield anthem
    already uses; only the *source's own zone* is unusual. Re-evaluated
    fresh every `continuous.recompute` pass, so this stops granting haste
    the instant either half of the condition stops holding — Anger leaves
    the graveyard, or the last Mountain does.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["haste"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_mountain",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
            raw_text=(
                "as long as this card is in your graveyard and you control "
                "a mountain, creatures you control have haste."
            ),
        ),
    ]


register("Anger", _anger)


def _brawn() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Forest, creatures you control have trample.

    — Brawn, `_anger`'s green sibling (MEC-22): identical
    ``"from_graveyard": True`` shape, just trample/Forest in place of
    haste/Mountain. Brawn's own printed Trample (its first oracle-text
    line) needs no `AbilitySpec` of its own — that's the creature's plain
    printed keyword, read directly off `Card.keywords` by
    `combat.py`/`continuous.py` like any other, independent of this
    catalogue entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["trample"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_forest",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
            raw_text=(
                "as long as this card is in your graveyard and you control "
                "a forest, creatures you control have trample."
            ),
        ),
    ]


register("Brawn", _brawn)


def _filth() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Swamp, creatures you control have swampwalk.

    — Filth, `_anger`'s black sibling (MEC-22). ``"swampwalk"`` is a
    landwalk slug, not a FLAG keyword, but `grant_keyword`'s
    `keywords` list already accepts either shape identically
    (`combat._landwalk_slugs` matches any granted keyword ending
    "walk"), so no different EffectSpec params are needed here than
    Anger's/Brawn's.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["swampwalk"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_swamp",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
            raw_text=(
                "as long as this card is in your graveyard and you control "
                "a swamp, creatures you control have swampwalk."
            ),
        ),
    ]


register("Filth", _filth)


def _valor() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control a
    Plains, creatures you control have first strike.

    — Valor, `_anger`'s white sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["first strike"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_plains",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
            raw_text=(
                "as long as this card is in your graveyard and you control "
                "a plains, creatures you control have first strike."
            ),
        ),
    ]


register("Valor", _valor)


def _wonder() -> list[AbilitySpec]:
    """As long as this card is in your graveyard and you control an
    Island, creatures you control have flying.

    — Wonder, `_anger`'s blue sibling (MEC-22).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["flying"],
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_island",
                    "min": 1,
                },
                "from_graveyard": True,
            })],
            raw_text=(
                "as long as this card is in your graveyard and you control "
                "an island, creatures you control have flying."
            ),
        ),
    ]


register("Wonder", _wonder)


def _riftstone_portal() -> list[AbilitySpec]:
    """{T}: Add {C}.
    As long as this card is in your graveyard, lands you control have
    "{T}: Add {G} or {W}."

    — MEC-22's fifth "from the graveyard" card, and unlike Anger/Brawn/
    Filth/Valor/Wonder it grants a mana ability rather than a keyword
    (`grant_mana_ability` in place of `grant_keyword`, same
    ``"from_graveyard": True`` gate) onto lands rather than creatures
    (``affects="lands_you_control"``), and with no board-state gate of
    its own — unconditional once the card is in the graveyard. Its own
    printed "{T}: Add {C}." mana ability needs no `AbilitySpec` either,
    same reasoning as Brawn's own printed Trample: an ordinary printed
    mana ability is read directly by `mana_abilities.py`, not through
    this catalogue.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "lands_you_control",
                "mana": [{"G": 1}, {"W": 1}],
                "from_graveyard": True,
            })],
            raw_text=(
                'as long as this card is in your graveyard, lands you '
                'control have "{t}: add {g} or {w}."'
            ),
        ),
    ]


register("Riftstone Portal", _riftstone_portal)


def _arcane_denial() -> list[AbilitySpec]:
    """Counter target spell. Its controller may draw up to two cards at
    the beginning of the next turn's upkeep.
    You draw a card at the beginning of the next turn's upkeep.

    — Arcane Denial. The second sentence is exactly what the oracle-text
    parser already claims on its own (`author_card.py reuse`) — a plain
    "you draw a card next upkeep" `create_delayed_trigger`, pasted as-is.
    Only the first sentence needed a hand-written spec: the delayed draw
    belongs to the *countered spell's controller*, not this ability's own
    caster — `effects.CreateDelayedTriggerEffect`'s new
    ``capture="target_controller"`` (built for this card), which both
    arms the delayed trigger for *that* player's next upkeep and hands
    the drawn cards to them, reading the countered spell's own
    `GameObject.controller_id` at resolution (the countered spell is long
    gone by the time the delayed half actually fires).

    Documented simplification: "may draw **up to** two" is modeled as an
    unconditional draw of 2 — declining is a real but exceedingly rare
    choice (avoiding a self-mill/deck-out effect), and a delayed trigger
    has no interactive pending_choice machinery to offer it yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    # "**the** next turn's upkeep" — the very next one,
                    # whoever's turn that turns out to be, not specifically
                    # the countered spell's controller's own next turn
                    # (same reading the parser already gave the second
                    # sentence's identical phrasing, `scope: "any"` below).
                    "scope": "any",
                    "capture": "target_controller",
                    "effects": [{"type": "draw", "params": {"count": 2}}],
                    "description": "Arcane Denial: 2 Karten ziehen",
                }),
            ],
            raw_text=(
                "counter target spell. its controller may draw up to two "
                "cards at the beginning of the next turn's upkeep."
            ),
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_delayed_trigger", {
                "step": "upkeep",
                "scope": "any",
                "effects": [{"type": "draw", "params": {"count": 1}}],
                "description": "Arcane Denial: 1 Karte ziehen",
            })],
            raw_text="you draw a card at the beginning of the next turn's upkeep.",
        ),
    ]


register("Arcane Denial", _arcane_denial)


def _goldspan_dragon() -> list[AbilitySpec]:
    """Flying, haste
    Whenever this creature attacks or becomes the target of a spell,
    create a Treasure token.
    Treasures you control have "{T}, Sacrifice this artifact: Add two
    mana of any one color."

    — Goldspan Dragon. Flying/haste are keywords, already covered by the
    parser's keyword catalogue. The compound "attacks or becomes the
    target of a spell" trigger is two `AbilitySpec`s (MEC-19's
    `EventType.BECOMES_TARGET` added the second — same "one AbilitySpec
    per event" idiom `_SELF_MULTI_EVENT_RE`/Matoya, Archon Elder's "you
    scry or surveil" use for a compound RULE 603.1 condition), not a
    generalized "attacks or becomes the target of a spell [an opponent
    controls]" parser grammar — only Goldspan Dragon and Tectonic Giant
    print this exact compound (Giggling Skitterspike's own 3-way "attacks,
    blocks, or becomes the target of a spell" is a third, still wider
    shape), too narrow a family to be worth a general regex over two
    hand-authored entries.

    MEC-25 closed this card's own documented simplification: the granted
    ability now upgrades Treasure's printed one-mana version to the real
    printed two — `effects.grant_mana_ability`'s new ``cost`` param
    (`continuous._apply_layer_6_ability`'s ``mana_ability_cost`` handling)
    lets a grant carry a non-``{T}``-only cost and *replace* a matching
    printed ability instead of adding an independent second one (see
    `mana_abilities.mana_abilities_for`'s replace-matching). ``mana`` is
    the same 5-option "any one colour" menu shape `mana_abilities.
    _parse_clause` builds for Treasure's own printed text, just at amount 2.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="whenever ~ attacks, create a treasure token.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
            },
            raw_text="whenever ~ becomes the target of a spell, create a treasure token.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "permanents_you_control",
                "subtype": "Treasure",
                "cost": {"text": "{T}, Sacrifice this artifact"},
                "mana": [{color: 2} for color in ("W", "U", "B", "R", "G")],
            })],
            raw_text='treasures you control have "{t}, sacrifice this artifact: '
                     'add two mana of any one color."',
        ),
    ]


register("Goldspan Dragon", _goldspan_dragon)


def _tectonic_giant() -> list[AbilitySpec]:
    """Whenever this creature attacks or becomes the target of a spell an
    opponent controls, choose one —
    • This creature deals 3 damage to each opponent.
    • Exile the top two cards of your library. Choose one of them. Until
    the end of your next turn, you may play that card.

    — Tectonic Giant, MEC-19's second named card. Same "one AbilitySpec per
    compound-triggered event" idiom as Goldspan Dragon's own entry (this
    trigger only needs the ``caster_relation: "opponent"`` filter Goldspan
    Dragon's plain "of a spell" doesn't).

    Documented simplification on the second mode: "exile the top two
    cards, **choose one of them**, until the end of your next turn you may
    play *that* card" is a distinct RULE 601.3b shape from the already-
    shipped `ImpulsiveDrawEffect` ("exile N, *all* of them stay playable")
    — a filtered choice-and-route dig, not a plain reveal-and-window one.
    No shipped primitive covers "exile N, pick 1 to keep playable, discard
    the rest" (7 real cache cards total, `parser_probe.py cards` — its own
    small, real gap, orthogonal to MEC-19's `BECOMES_TARGET` work and not
    built here). Modeled instead with the closest existing effect,
    `impulsive_draw` at ``count=2``: strictly more generous than print
    (both exiled cards stay playable, not just one chosen), same
    "until the end of your next turn" window (``same_turn_only=False``).
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="whenever ~ attacks, choose one —",
        ),
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
                "caster_relation": "opponent",
            },
            raw_text="whenever ~ becomes the target of a spell an opponent controls, choose one —",
        ),
    ]


register("Tectonic Giant", _tectonic_giant)


def _kiki_jiki_mirror_breaker() -> list[AbilitySpec]:
    """Haste
    {T}: Create a token that's a copy of target nonlegendary creature you
    control, except it has haste. Sacrifice it at the beginning of the
    next end step.

    — Kiki-Jiki, Mirror Breaker. Haste is a keyword, already covered by
    the parser's keyword catalogue. The activated ability needed a hand
    spec for its "except it has haste" + "sacrifice it at the beginning
    of the next end step" pair — `effects.CopyPermanentEffect`'s new
    ``haste`` param (grants the copy temp haste directly, rather than a
    second untargeted keyword-grant effect that couldn't tell *which*
    creature just got made), then `create_delayed_trigger`'s new
    ``capture="created_objects"`` to arm a RULE 603.7 delayed
    ``sacrifice_specific`` naming that exact token (`GameContext.
    created_objects`, the same "the tokens…" referent Fabricate/Martial
    Coup already read) — this batch's general primitive for the whole
    "create/return X, it gains haste, [sacrifice/exile] it at the
    beginning of the next end step" template family (~40 real cards
    total between this shape and Puppeteer Clique's reanimate-and-exile
    sibling), not a one-off for this card alone.

    Documented simplification: the real printed restriction is "target
    **nonlegendary** creature you control" — this engine's targeting
    vocabulary has no "nonlegendary" creature kind yet (only the positive
    "legendary permanent"), so it's modeled as a plain "creature you
    control" target; illegally copying a legendary creature just runs
    into the ordinary RULE 704.5j legend-rule SBA like any other route to
    a second legendary permanent, rather than being refused as an illegal
    target the way real Kiki-Jiki refuses it outright.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "count": 1, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Kiki-Jiki: Kopie opfern",
                }),
            ],
            cost={"taps_self": True},
            raw_text=(
                "{t}: create a token that's a copy of target nonlegendary "
                "creature you control, except it has haste. sacrifice it "
                "at the beginning of the next end step."
            ),
        ),
    ]


register("Kiki-Jiki, Mirror Breaker", _kiki_jiki_mirror_breaker)


def _puppeteer_clique() -> list[AbilitySpec]:
    """When this creature enters, put target creature card from an
    opponent's graveyard onto the battlefield under your control. It
    gains haste. At the beginning of your next end step, exile it.

    — Puppeteer Clique. The reanimate-and-exile sibling of Kiki-Jiki's
    copy-and-sacrifice template (same batch, same primitives):
    `effects.ReturnFromGraveyardEffect`'s new ``haste`` param plus
    `create_delayed_trigger`'s ``capture="created_objects"`` to arm a
    RULE 603.7 delayed ``exile`` naming the exact permanent this
    resolution just reanimated (`GameContext.created_objects`) — see
    `_kiki_jiki_mirror_breaker`'s docstring for the shared design.
    ``target_kind="opponent_graveyard_creature"`` already exists in
    `targeting.py` for exactly this card (its own docstring names
    Puppeteer Clique as the motivating example).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "opponent_graveyard_creature",
                    "destination": "battlefield",
                    "under_your_control": True,
                    "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [{"type": "exile", "params": {"target_kind": None}}],
                    "description": "Puppeteer Clique: Kreatur verbannen",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text=(
                "when ~ enters, put target creature card from an "
                "opponent's graveyard onto the battlefield under your "
                "control. it gains haste. at the beginning of your next "
                "end step, exile it."
            ),
        ),
    ]


register("Puppeteer Clique", _puppeteer_clique)


def _mikaeus_the_unhallowed() -> list[AbilitySpec]:
    """Whenever a Human deals damage to you, destroy it.
    Other non-Human creatures you control get +1/+1 and have undying.

    — Mikaeus, the Unhallowed. The anthem is `other_nonhuman_creatures_
    you_control` (`continuous.group_selector_objects`'s new branch — the
    negated-subtype sibling of the existing `other_creatures_you_control`/
    `nonlegendary_creatures_you_control`), carrying both the +1/+1 anthem
    and the undying keyword grant.

    The first clause needed two small additions of its own: a group-
    subject DAMAGE trigger scoped to the *player* recipient specifically
    (`effect_binder`'s new ``condition["recipient_is_you"]`` — the
    existing ``condition["recipient"]`` only ever matches a *permanent*
    recipient's controller, since `RulesEngine.deal_damage` stamps
    ``target_controller_id`` as ``None`` for a player target), and
    `effects.DestroyEffect`'s new ``target_from_trigger_event="source_id"``
    to destroy the Human that actually dealt the damage — a group-subject
    trigger has no single chosen creature the way a self-subject "when ~
    enters" trigger's implicit "it" would, so "it" here has to be read
    back off the firing DAMAGE event itself.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {"target_kind": None, "target_from_trigger_event": "source_id"})],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "subtypes": ["human"], "recipient_is_you": True},
            },
            raw_text="whenever a human deals damage to you, destroy it.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "other_nonhuman_creatures_you_control", "power": 1, "toughness": 1,
                }),
                EffectSpec("grant_keyword", {
                    "affects": "other_nonhuman_creatures_you_control", "keywords": ["undying"],
                }),
            ],
            raw_text="other non-human creatures you control get +1/+1 and have undying.",
        ),
    ]


register("Mikaeus, the Unhallowed", _mikaeus_the_unhallowed)


def _spark_double() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of a creature or
    planeswalker you control, except it enters with an additional +1/+1
    counter on it if it's a creature, it enters with an additional
    loyalty counter on it if it's a planeswalker, and it isn't legendary.

    — Spark Double. `effects.EnterAsCopyReplacement` (RULE 614.1c/614.12,
    Clever Impersonator's own mechanism), with two additions this batch
    needed: ``target_kind="creature_or_planeswalker_you_control"``
    (`targeting.py`'s new controller-scoped sibling of the existing bare
    "creature or planeswalker" union kind), and the new
    ``extra_counter_if_creature``/``extra_counter_if_planeswalker`` pair
    (`RulesEngine.add_counters`, applied once the copy is made and the
    resulting permanent's real type is known).

    Documented simplification: "**and it isn't legendary**" is not
    modeled — this engine's copy mechanism (`copy_mechanics.become_copy`)
    has no "strip a supertype" primitive (only `add_types`/`add_subtypes`
    exist), so a Spark Double copying a legendary permanent comes in as a
    second copy of that same legendary permanent and runs into the
    ordinary RULE 704.5j legend-rule SBA like any other route to one,
    rather than being exempted from it the way the real card is.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_or_planeswalker_you_control",
                "extra_counter_if_creature": "+1/+1",
                "extra_counter_if_planeswalker": "loyalty",
            })],
            raw_text=(
                "you may have ~ enter as a copy of a creature or "
                "planeswalker you control, except it enters with an "
                "additional +1/+1 counter on it if it's a creature, it "
                "enters with an additional loyalty counter on it if it's "
                "a planeswalker, and it isn't legendary."
            ),
        ),
    ]


register("Spark Double", _spark_double)


def _kari_zevs_expertise() -> list[AbilitySpec]:
    """Gain control of target creature or Vehicle until end of turn.
    Untap it. It gains haste until end of turn.
    You may cast a spell with mana value 2 or less from your hand without
    paying its mana cost.

    — Kari Zev's Expertise. The threaten half reuses `effects.
    GainControlUntilEndOfTurnEffect` (built for Zealous Conscripts,
    already bundling the control change/untap/haste grant) with
    ``target_kind="permanent"`` rather than a creature-only kind, so a
    Vehicle target (an artifact, not a creature until crewed) is reachable
    the same way — narrower than the printed "creature or Vehicle" (any
    artifact is technically eligible here, not just Vehicles), a one-word
    substitution rather than a dedicated Vehicle target kind for this one
    card.

    MEC-20 closed the second sentence — RULE 601.2f's "Expertise" cycle
    template ("you may cast a spell with mana value N or less from your
    hand without paying its mana cost", also on Sram's/Yahenni's/Baral's/
    Rishkar's Expertise), via the new `effects.FreeCastFromHandEffect` and
    the oracle-text handler that now claims the other four automatically
    (`parser/oracle/catalogue/handlers.py`'s ``free_cast_from_hand`` row) —
    this card stays hand-authored only for its first, threaten sentence.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_until_eot", {"target_kind": "permanent"})],
            raw_text=(
                "gain control of target creature or vehicle until end of "
                "turn. untap it. it gains haste until end of turn."
            ),
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": 2})],
            raw_text=(
                "you may cast a spell with mana value 2 or less from your "
                "hand without paying its mana cost."
            ),
        ),
    ]


register("Kari Zev's Expertise", _kari_zevs_expertise)


def _electrodominance() -> list[AbilitySpec]:
    """Electrodominance deals X damage to any target. You may cast a spell
    with mana value X or less from your hand without paying its mana cost.

    — Electrodominance (MEC-20's own X-scaled "Expertise" cousin — RULE
    601.2f, same template as the Expertise cycle just with an announced
    {X} instead of a literal N, `effects.FreeCastFromHandEffect`'s
    ``criteria={"max_mana_value": "x"}``). Hand-authored rather than
    reached through the oracle-text parser's own ``damage`` handler:
    that handler's regex is digit-only (``NUMBER``, not ``COUNT_X``) and
    widening it to accept the "x" sentinel is a separate, real gap of its
    own (X-cost burn spells generally — Fireball/Rolling Thunder/Banefire-
    shaped, a family this ticket didn't size) rather than a one-line
    change safe to fold into this batch unreviewed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any"})],
            raw_text="~ deals x damage to any target.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("free_cast_from_hand", {"max_mana_value": "x"})],
            raw_text=(
                "you may cast a spell with mana value x or less from your "
                "hand without paying its mana cost."
            ),
        ),
    ]


register("Electrodominance", _electrodominance)


def _danny_pink() -> list[AbilitySpec]:
    """Creatures you control have "Whenever one or more counters are put
    on this creature for the first time each turn, draw a card."

    — Danny Pink. `grant_triggered_ability` (layer 6, the same quoted-
    ability-grant mechanism the hand-authored Dionus, Elvish Archdruid
    uses for its own per-creature "once each turn" grant): each creature
    you control gets its own `TriggeredAbility` watching its own
    `EventType.COUNTER` firing, capped by ``once_per_turn`` — RULE 603.2's
    "for the first time each turn" phrasing exactly.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_triggered_ability",
                    {
                        "affects": "creatures_you_control",
                        "trigger_event": EventType.COUNTER,
                        "once_per_turn": True,
                        "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                    },
                )
            ],
            raw_text=(
                'creatures you control have "whenever 1 or more counters '
                'are put on ~ for the first time each turn, draw a card."'
            ),
        ),
    ]


register("Danny Pink", _danny_pink)


def _black_market_connections() -> list[AbilitySpec]:
    """At the beginning of your first main phase, choose one or more —
    • Sell Contraband — Create a Treasure token. You lose 1 life.
    • Buy Information — Draw a card. You lose 2 life.
    • Hire a Mercenary — Create a 3/2 colorless Shapeshifter creature
    token with changeling. You lose 3 life.

    — Black Market Connections. The modal shape (RULE 700.2's "choose one
    or more") reuses Farewell's own ``modes={"choose": 1, "at_least":
    True, "options": [...]}`` structure verbatim — the only difference is
    the wrapper: a `STEP_BEGIN` main-phase trigger (``filter: {"step":
    "main1"}``, ``phase_relation: "you"``, the same shape Trystan/Wall of
    Vipers-esque "at the beginning of your first main phase" grants
    already use) instead of a plain spell.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "options": [
                    [
                        EffectSpec("create_token", {"count": 1, "token_name": "Treasure"}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 2}),
                    ],
                    [
                        EffectSpec("create_token", {
                            "count": 1, "power": 3, "toughness": 2, "colors": [],
                            "subtypes": ["Shapeshifter"], "keywords": ["changeling"],
                            "token_name": "Shapeshifter",
                        }),
                        EffectSpec("lose_life", {"amount": 3}),
                    ],
                ],
                "descriptions": [
                    "Sell Contraband: Erzeuge einen Schatz. Verliere 1 Leben.",
                    "Buy Information: Ziehe eine Karte. Verliere 2 Leben.",
                    "Hire a Mercenary: Erzeuge einen 3/2 farblosen Gestaltwandler "
                    "mit Wandelbar. Verliere 3 Leben.",
                ],
            },
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
            raw_text=(
                "at the beginning of your first main phase, choose one or "
                "more — sell contraband — create a treasure token. you "
                "lose 1 life. buy information — draw a card. you lose 2 "
                "life. hire a mercenary — create a 3/2 colorless "
                "shapeshifter creature token with changeling. you lose 3 "
                "life."
            ),
        ),
    ]


register("Black Market Connections", _black_market_connections)


def _agathas_soul_cauldron() -> list[AbilitySpec]:
    """You may spend mana as though it were mana of any color to activate
    abilities of creatures you control.
    Creatures you control with +1/+1 counters on them have all activated
    abilities of all creature cards exiled with this artifact.
    {T}: Exile target card from a graveyard. When a creature card is
    exiled this way, put a +1/+1 counter on target creature you control.

    — Agatha's Soul Cauldron. MEC-21 closed both of this card's previously
    unmodeled clauses:

    - The mana-spend permission is `effects.grant_any_color_for_activation`
      (a standing RULE 605.1a wildcard over activation-cost mana, distinct
      from the shipped RULE 605.3a `restriction_predicate_for_cast`/
      `_for_activation` machinery, which restricts *what* a lot of mana can
      pay for rather than *what color* it counts as) — `continuous.
      any_color_for_activation`, consulted by every activation-cost payment
      site in `game/engine/activation_mixin.py`.
    - The dynamic ability grant is `effects.grant_borrowed_activated_
      ability`, reading live off `GameObject.exiled_with_ids` — the
      generalized, *accumulating* "cards exiled with ~" list this card's
      own activated ability below now stamps via `ExileEffect`'s new
      ``track_exiled_with`` param (MEC-21's other named primitive,
      reusable by any future "exile with ~" card; ~185 cached cards print
      that shape). `continuous._apply_borrowed_activated_abilities` builds
      one fresh `ActivatedAbility` per (grantee, exiled creature, ability
      index), reusing the exiled card's own cost/effects (bound once at
      bind-on-load, same as any other permanent's) with each nested
      effect's `.source` redirected to the grantee (RULE 113.7c).

    Documented simplification on the activated ability: the counter
    placement is unconditional rather than gated on "if a **creature** card
    was exiled this way" — this engine's ``exile`` effect has no
    "conditional on the exiled card's own type" follow-up yet (RULE 608.2's
    "when you do" sub-trigger machinery this would need is the same one
    Maestros Theater's cycle uses for its own mandatory "sacrifice it, then
    search" shape, not directly reusable for an optional target's *type*
    instead of a fixed antecedent) — so a noncreature exile still grows a
    counter, strictly more generous than print.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "track_exiled_with": True}),
                EffectSpec("add_counters", {"amount": 1, "target_kind": "creature"}),
            ],
            cost={"taps_self": True},
            raw_text=(
                "{t}: exile target card from a graveyard. when a creature "
                "card is exiled this way, put a +1/+1 counter on target "
                "creature you control."
            ),
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {"creature_abilities_only": True})],
            raw_text="you may spend mana as though it were mana of any color to "
                     "activate abilities of creatures you control.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "creatures_you_control",
                "has_counter_kind": "+1/+1",
                "creature_only": True,
            })],
            raw_text="creatures you control with +1/+1 counters on them have all "
                     "activated abilities of all creature cards exiled with this "
                     "artifact.",
        ),
    ]


register("Agatha's Soul Cauldron", _agathas_soul_cauldron)


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
    damage"` factory (the Sphere/Absorb/Shield of the Realm family, MEC-30).
    ``amount="all"`` here since Riot Control prevents everything, not a
    capped amount.
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
    here; the card's own Cumulative Upkeep (RULE 702.24) now binds for free
    regardless (MEC-16 — `game/effect_binder.py`'s keyword dispatch reads
    `Card.keywords`/oracle text independently of whatever a hand-authored
    entry supplies), so it no longer needs claiming here. Its own trailing
    "when a player doesn't pay this enchantment's cumulative upkeep, that
    player exiles all cards from their library" rider is still unclaimed
    though — the base mechanic never fires a paid-vs-not-paid event a
    second trigger could hook, only a real but narrower residual gap now.
    This entry only supplies the activated ability so the shared
    `prevent_damage_shield` primitive has its second real, amount-capped/
    repeatable-use exercising card (Riot Control's own use is the single
    uncapped "all" case). The cost is a plain "Exile the top card of your
    library" cost (`costs.py`'s existing library-exile cost grammar); the
    effect passes ``amount=1`` — a fresh `RulesEngine.
    prevent_damage_to_player` shield is opened on each activation, so
    repeated activations in a turn stack independent 1-point shields
    exactly like `regenerate`'s own multiple-activations-stack behaviour.
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


def _chrome_mox() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, you may exile a nonartifact,
    nonland card from your hand.
    {T}: Add one mana of any of the exiled card's colors.

    — Chrome Mox (ENG-27's own sibling primitive, MEC-17 — RULE 702.45-
    adjacent Imprint's solo real card). The mana ability parses on its own
    (`game/mana_abilities.py`'s new ``_IMPRINTED_COLOR_ADD_RE`` →
    `ManaAbility.color_selector`'s ``"imprinted_card_colors"``, read fresh
    off `GameObject.linked_exile_id` every tap, unconditionally — mana
    abilities are parsed straight from the printed card, not gated on
    hand-authoring, the same reason ENG-27's Bloom Tender/Carpet of
    Flowers primitives needed no catalogue entry either); only the ETB
    exile-and-remember half is hand-authored here, via `ImprintEffect`
    (``exclude_card_types=["artifact", "land"]`` — Chrome Mox's own
    "nonartifact, nonland" filter) with ``remember=True`` threaded through
    `RulesEngine.request_choose_objects`'s general chooser.
    """
    # `optional` deliberately stays off the *spec* — the trigger itself is
    # unconditionally put on the stack (there's no separate RULE 603.5 "you
    # may" gating the trigger header, unlike a plain "you may draw a card"
    # body); `ImprintEffect`'s own `optional=True` default is what asks the
    # real "you may exile…" question at resolution, one prompt not two.
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {"exclude_card_types": ["artifact", "land"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Prägung — Wenn dieses Artefakt ins Spiel kommt, kannst "
                     "du eine Nichtartefakt-, Nichtland-Karte aus deiner "
                     "Hand exilieren.",
        )
    ]


register("Chrome Mox", _chrome_mox)


def _carpet_of_flowers() -> list[AbilitySpec]:
    """At the beginning of each of your main phases, if you haven't added
    mana with this ability this turn, you may add X mana of any one
    color, where X is the number of Islands target opponent controls.

    — Carpet of Flowers (ENG-27). Unlike Wild Growth/Kinnan just above,
    this one genuinely **targets** ("target opponent"), which RULE 605.5a
    disqualifies from ever being a mana ability at all regardless of what
    it produces — so it's an ordinary triggered ability that goes on the
    stack, not the RULE 605.4 off-stack shape. Two standing entries, one
    per main phase: the engine fires a real ``step="main1"``/``"main2"``
    event, never a generic ``"main"`` one (that spelling is `Mana Drain`'s
    own delayed-trigger-only sentinel, a different mechanism entirely).

    Both ride the same new primitives: `AddManaEffect.
    amount_from_target_count_selector` (X evaluated against the *resolved
    target*, not this permanent's own controller — `continuous.
    count_selector`'s pre-existing ``lands_you_control_of_type_island``,
    scoped to whichever opponent got picked) and `once_per_turn_ability`
    (`GameObject.added_mana_with_ability_this_turn`, reset each untap
    step). ``optional=True`` is RULE 603.5's "you may" — declining never
    puts the trigger on the stack at all, so a decline never touches the
    once-per-turn flag either, exactly matching a real "no, thanks" at the
    table. **Documented simplification**: the "if you haven't added mana…"
    gate is a resolve-time no-op rather than a full RULE 603.4
    intervening-if, so the "you may" prompt can still appear on a turn
    it would do nothing (see `AddManaEffect`'s own docstring) — no
    observable difference once resolved, since it just adds no mana either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "colors": ["ANY"],
                "target_kind": "opponent",
                "amount_from_target_count_selector": "lands_you_control_of_type_island",
                "once_per_turn_ability": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": step},
                "phase_relation": "you",
            },
            optional=True,
            raw_text="Zu Beginn jeder deiner Hauptphasen erzeuge, falls du in diesem "
                     "Zug noch kein Mana mit dieser Fähigkeit erzeugt hast, wahlweise "
                     "X Mana einer beliebigen Farbe, wobei X der Anzahl der Inseln "
                     "entspricht, die ein Zielgegner kontrolliert.",
        )
        for step in ("main1", "main2")
    ]


register("Carpet of Flowers", _carpet_of_flowers)


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


# ---------------------------------------------------------------------------
# MEC-11 — the Enrage stragglers: real cards left UNMODELED after the
# parser's own general "whenever ~ is dealt damage" recognition
# (`parser/oracle/segmenter.py`'s `_DAMAGE_RECIPIENT_TRIGGER_RE`) closed the
# trigger side. Each of these fails on its *effect body*, not the Enrage
# trigger itself — a second, narrower gap per card. Several needed a small
# new primitive (`damage_equal_to_counters`, `AddManaEffect.
# amount_from_trigger_event`, `AddCountersEffect`/`DealDamageEffect`'s
# widened selector vocabulary, the `opponent`/`opponent_or_planeswalker`
# target kinds) rather than being purely bespoke — each documented at its
# own definition in `game/effects.py`/`game/targeting.py`. Every entry below
# also documents its own simplifications inline; none silently drops a
# clause without saying so.
# ---------------------------------------------------------------------------


def _bellowing_aegisaur() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, put a +1/+1 counter
    on each other creature you control.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"selector": "each_other_creature_you_control"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, lege "
                     "eine +1/+1-Marke auf jede andere Kreatur unter deiner Kontrolle.",
        ),
    ]


register("Bellowing Aegisaur", _bellowing_aegisaur)


def _frilled_deathspitter() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 2 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, fügt sie "
                     "einem Zielgegner oder einem Ziel-Planeswalker 2 Schadenspunkte zu.",
        ),
    ]


register("Frilled Deathspitter", _frilled_deathspitter)


def _sun_crowned_hunters() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 3 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 3, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, fügt sie "
                     "einem Zielgegner oder einem Ziel-Planeswalker 3 Schadenspunkte zu.",
        ),
    ]


register("Sun-Crowned Hunters", _sun_crowned_hunters)


def _indoraptor_the_perfect_hybrid() -> list[AbilitySpec]:
    """Bloodthirst X
    Menace
    Enrage — Whenever Indoraptor is dealt damage, choose an opponent at
    random. Indoraptor deals damage equal to its power to that player
    unless they sacrifice a nontoken creature of their choice.

    Simplified: "at random" becomes an ordinary target choice — a real
    choice instead of randomness has no rules-relevant difference here and
    is never worse for the chosen opponent — and the "unless they
    sacrifice a nontoken creature" escape clause isn't modeled (that would
    need a genuinely new opponent-side interactive "unless" primitive; the
    existing `sacrifice_unless_pay`/`request_pay_cost_then` family is
    always about *this ability's own controller* paying, not an
    opponent). The damage simply always happens. Bloodthirst is bind-on-
    load from the RULE 702 keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage_equal_to_power", {"target_kind": "opponent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Indoraptor Schaden zugefügt bekommt, fügt es "
                     "einem Zielgegner Schaden in Höhe seiner Stärke zu.",
        ),
    ]


register("Indoraptor, the Perfect Hybrid", _indoraptor_the_perfect_hybrid)


def _polyraptor() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, create a token
    that's a copy of this creature.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {"target_kind": None})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, erzeuge "
                     "einen Kartenspielstein, der eine Kopie von ihr ist.",
        ),
    ]


register("Polyraptor", _polyraptor)


def _raphael_ninja_destroyer() -> list[AbilitySpec]:
    """Raphael must be blocked if able.
    Enrage — Whenever Raphael is dealt damage, add that much {R}. Until
    end of turn, you don't lose this mana as steps and phases end.

    Simplified: the "you don't lose this mana as steps and phases end"
    persistence isn't modeled — `ManaPool` has no survives-a-step
    mechanism yet, so this mana empties at the current step's end (RULE
    500.4) like any other, rather than lasting the rest of the turn.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["must_be_blocked"], "affects": "self"})],
            raw_text="Raphael muss blocken, falls möglich.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"color": "R", "amount_from_trigger_event": "amount"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Raphael Schaden zugefügt bekommt, erzeuge "
                     "entsprechend viel {R}.",
        ),
    ]


register("Raphael, Ninja Destroyer", _raphael_ninja_destroyer)


def _red_hulk() -> list[AbilitySpec]:
    """Reach, trample
    Enrage — Whenever Red Hulk is dealt damage, put a +1/+1 counter on
    him. When you do, he deals damage equal to the number of +1/+1
    counters on him to any other target.

    Simplified: RULE 603.10's "when you do" is really a second, reflexive
    triggered ability off the counter-placement — this engine has no such
    primitive yet, so both halves run as one triggered ability's effect
    list instead (RULE 608.2a resolves a list in printed order, and
    nothing has a window to intervene between them either way in an
    automated engine), which is behaviourally indistinguishable from the
    two-trigger original. Reach/trample are bind-on-load from the RULE 702
    keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {}),
                EffectSpec("damage_equal_to_counters", {"target_kind": "any"}),
            ],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Red Hulk Schaden zugefügt bekommt, lege eine "
                     "+1/+1-Marke auf ihn. Danach fügt er einem beliebigen anderen Ziel "
                     "Schaden in Höhe der +1/+1-Marken auf ihm zu.",
        ),
    ]


register("Red Hulk", _red_hulk)


def _silverclad_ferocidons() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, each opponent
    sacrifices a permanent of their choice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "each_opponent", "what": "permanent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, opfert "
                     "jeder Gegner eine bleibende Karte seiner Wahl.",
        ),
    ]


register("Silverclad Ferocidons", _silverclad_ferocidons)


def _stalwart_speartail() -> list[AbilitySpec]:
    """Enrage — Whenever Stalwart Speartail is dealt damage, other
    Dinosaurs you control and Dinosaur cards in your hand and library
    perpetually get +1/+1.
    Whenever Stalwart Speartail attacks, Stalwart Speartail deals 1 damage
    to each creature and each planeswalker.

    Simplified: only the second (attacks-trigger) ability is modeled. The
    first is RULE 121's *perpetual* effect shape (a one-time, permanent
    grant that outlives its source and reaches into hand/library, unlike
    an ordinary "as long as ~ is on the battlefield" static) — genuinely
    unsupported by this engine (`GrantUntilEffect`'s duration vocabulary,
    `game/durations.py`, is turn/game-window-scoped, not "forever,
    independent of the source"), so it's left out rather than
    approximated as an always-on static, which would be a meaningfully
    different, strictly *more* powerful card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_planeswalker"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Stalwart Speartail angreift, fügt es jeder Kreatur und "
                     "jedem Planeswalker 1 Schadenspunkt zu.",
        ),
    ]


register("Stalwart Speartail", _stalwart_speartail)


def _trapjaw_tyrant() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, exile target
    creature an opponent controls until this creature leaves the
    battlefield.

    The O-Ring-shaped linked-exile pair (`ExileEffect(remember=True)` +
    `ReturnLinkedExileEffect` on the leaves-battlefield trigger, exactly
    `Leonin Relic-Warder`'s pattern) — the modern one-sentence "exile …
    until ~ leaves the battlefield" templating is the same RULE 610.3-style
    linked duration as Leonin's older two-sentence phrasing, just terser.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, exiliere "
                     "eine Zielkreatur, die ein Gegner kontrolliert, bis diese Kreatur das "
                     "Schlachtfeld verlässt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, bringe die exilierte "
                     "Karte unter der Kontrolle ihres Besitzers auf das Schlachtfeld zurück.",
        ),
    ]


register("Trapjaw Tyrant", _trapjaw_tyrant)


def _vrondiss_rage_of_ancients() -> list[AbilitySpec]:
    """Enrage — Whenever Vrondiss is dealt damage, you may create a 5/4
    red and green Dragon Spirit creature token with "When this token
    deals damage, sacrifice it."
    Whenever you roll one or more dice, you may have Vrondiss deal 1
    damage to itself.

    Simplified: the created token's own "sacrifice it after it deals
    damage" downside isn't modeled (no quoted-ability-grant support for a
    created token yet — every other quoted-grant primitive in this engine
    targets an *existing* permanent, not a token being created in the same
    breath), so the token created here is strictly a 5/4 vanilla. The
    dice-roll clause is skipped entirely — this engine has no dice-rolling
    subsystem at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Dragon Spirit", "power": 5, "toughness": 4,
                "colors": ["R", "G"], "subtypes": ["Dragon", "Spirit"],
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            optional=True,
            raw_text="Enrage — Immer wenn Vrondiss Schaden zugefügt bekommt, kannst du "
                     "einen 5/4 roten und grünen Drachengeist-Kreaturenspielstein erzeugen.",
        ),
    ]


register("Vrondiss, Rage of Ancients", _vrondiss_rage_of_ancients)


# ---------------------------------------------------------------------------
# "Hobbits" / "Wyleth Equip" saved-deck-priority batch — closing the
# remaining group-attack/group-ETB/conditional-trigger cluster the parser's
# generic grammar doesn't reach yet (RULE 603.3b's "any number of X" is a
# genuine aggregate-once trigger shape, distinct from the per-object group
# condition `effect_binder._build_group_ok` already models; a printed
# "historic"/exact-power-filtered ETB gate; a multi-object sacrifice cost).
# Each entry documents its own specific simplification.
# ---------------------------------------------------------------------------


def _meriadoc_brandybuck() -> list[AbilitySpec]:
    """Whenever one or more Halflings you control attack a player, create
    a Food token.

    Simplified: modeled as "attacks" (any defender), not "attacks a
    player" specifically — the ATTACKS event carries no defender-kind
    payload to filter on. RULE 603.3b's "one or more X" is a genuine
    aggregate-once-per-batch trigger; this engine's group condition instead
    fires once per *qualifying object* (once per attacking Halfling), so
    it's capped at once per turn (`trigger["limit"]`) as the closest
    available approximation — under-fires on a rare second combat the same
    turn, never over-fires on a simultaneous multi-Halfling attack.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {
                    "subject": "group", "subtypes": ["halfling"],
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
            raw_text="Immer wenn ein oder mehr Halblinge unter deiner Kontrolle einen "
                     "Spieler angreifen, erzeuge einen Nahrungsspielstein.",
        ),
    ]


register("Meriadoc Brandybuck", _meriadoc_brandybuck)


def _merry_warden_of_isengard() -> list[AbilitySpec]:
    """Partner with Pippin, Warden of Isengard.
    Whenever one or more artifacts you control enter, create a 1/1 white
    Soldier creature token with lifelink. This ability triggers only once
    each turn.

    ("Partner with" is bound by the RULE 702 keyword catalogue directly
    off Scryfall's own keyword array — no hand-authoring needed for it.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Soldier"], "keywords": ["lifelink"], "token_name": "Soldier",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "artifact",
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
            raw_text="Immer wenn ein oder mehr Artefakte unter deiner Kontrolle ins Spiel "
                     "kommen, erzeuge einen 1/1 weißen Soldat-Kreaturenspielstein mit "
                     "Lebensverknüpfung. Diese Fähigkeit wird nur einmal pro Zug ausgelöst.",
        ),
    ]


register("Merry, Warden of Isengard", _merry_warden_of_isengard)


def _rosie_cotton_of_south_lane() -> list[AbilitySpec]:
    """When Rosie Cotton enters, create a Food token.
    Whenever you create a token, put a +1/+1 counter on target creature
    you control other than Rosie Cotton.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Rosie Cotton ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"target_kind": "other_creature_you_control"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein erzeugst, lege einen +1/+1-Marker auf "
                     "eine andere Zielkreatur unter deiner Kontrolle.",
        ),
    ]


register("Rosie Cotton of South Lane", _rosie_cotton_of_south_lane)


def _saradoc_master_of_buckland() -> list[AbilitySpec]:
    """Whenever Saradoc or another nontoken creature you control with
    power 2 or less enters, create a 1/1 white Halfling creature token.
    Tap two other untapped Halflings you control: Saradoc gets +2/+0 and
    gains lifelink until end of turn.

    Simplified: the power-2-or-less filter isn't checked (a live per-
    firing power qualifier on a group-ETB condition isn't modeled yet) —
    widened to any nontoken creature entering; the tap cost's pool isn't
    narrowed to exclude Saradoc herself (`costs.ActivationCost.tap_others`
    has no self-exclusion flag), so she could in principle pay her own
    cost. Both are documented over-generosities, not a functional break.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Halfling"], "token_name": "Halfling",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "type": "creature", "controller": "you", "other": True},
            },
            raw_text="Immer wenn Saradoc oder eine andere nicht-Spielstein-Kreatur unter "
                     "deiner Kontrolle mit Stärke 2 oder weniger ins Spiel kommt, erzeuge "
                     "einen 1/1 weißen Halblinge-Kreaturenspielstein.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0, "keywords": ["lifelink"]})],
            cost={"tap_others": (2, "halfling")},
            raw_text="Tappe zwei andere ungetappte Halblinge unter deiner Kontrolle: "
                     "Saradoc erhält +2/+0 und Lebensverknüpfung bis zum Ende des Zuges.",
        ),
    ]


register("Saradoc, Master of Buckland", _saradoc_master_of_buckland)


def _experimental_confectioner() -> list[AbilitySpec]:
    """When this creature enters, create a Food token.
    Whenever you sacrifice a Food, create a 1/1 black Rat creature token
    with "This token can't block."

    Simplified: the created Rat token doesn't carry its own "can't block"
    text — `create_token`'s params have no combat-restriction hook for a
    token being created this same breath (every other combat-restriction
    consumer targets an *existing* permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["B"],
                "subtypes": ["Rat"], "token_name": "Rat",
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
            raw_text="Immer wenn du eine Nahrung opferst, erzeuge einen 1/1 schwarzen "
                     "Ratte-Kreaturenspielstein (kann nicht blocken).",
        ),
    ]


register("Experimental Confectioner", _experimental_confectioner)


def _rapacious_guest() -> list[AbilitySpec]:
    """Menace
    Whenever one or more creatures you control deal combat damage to a
    player, create a Food token.
    Whenever you sacrifice a Food, put a +1/+1 counter on this creature.
    When this creature leaves the battlefield, target opponent loses life
    equal to its power.

    Simplified: the first trigger is capped at once per turn
    (`trigger["limit"]`) — see Meriadoc Brandybuck's own note on RULE
    603.3b's "any number of X" aggregate-once shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": False,
                },
                "filter": {"combat": True, "is_player": True},
                "limit": True,
            },
            raw_text="Immer wenn eine oder mehr Kreaturen unter deiner Kontrolle einem "
                     "Spieler Kampfschaden zufügen, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
            raw_text="Immer wenn du eine Nahrung opferst, lege einen +1/+1-Marker auf "
                     "diese Kreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "power"})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, verliert ein Gegner "
                     "deiner Wahl so viel Leben, wie ihre Stärke betrug.",
        ),
    ]


register("Rapacious Guest", _rapacious_guest)


def _mirkwood_bats() -> list[AbilitySpec]:
    """Flying
    Whenever you create or sacrifice a token, each opponent loses 1 life.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein erzeugst, verliert jeder Gegner 1 Leben.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein opferst, verliert jeder Gegner 1 Leben.",
        ),
    ]


register("Mirkwood Bats", _mirkwood_bats)


def _farmer_cotton() -> list[AbilitySpec]:
    """When Farmer Cotton enters the battlefield, create X 1/1 white
    Halfling creature tokens and X Food tokens, where X is the number of
    Halflings you control.

    The cached oracle text is missing its trailing "where X is …" clause
    (a Scryfall data gap in the local cache) — X is filled in here from
    the card's real printed rules text.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                    "token_name": "Halfling",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
                EffectSpec("create_token", {
                    "token_name": "Food",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Farmer Cotton ins Spiel kommt, erzeuge X 1/1 weiße "
                     "Halblinge-Kreaturenspielsteine und X Nahrungsspielsteine, wobei X "
                     "die Anzahl der Halblinge ist, die du kontrollierst.",
        ),
    ]


register("Farmer Cotton", _farmer_cotton)


def _samwise_gamgee() -> list[AbilitySpec]:
    """Whenever another nontoken creature you control enters, create a
    Food token.
    Sacrifice three Foods: Return target historic card from your
    graveyard to your hand. (Artifacts, legendaries, and Sagas are
    historic.)

    Simplified: "historic" isn't a modeled target filter — widened to
    "target card in your graveyard" (`graveyard_card`), the closest
    already-supported graveyard-target shape; likewise "nontoken" isn't
    enforced on a bare main-type group condition (only on a subtype-
    filtered one), so this also fires for a token creature entering.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": True,
                },
            },
            raw_text="Immer wenn eine andere nicht-Spielstein-Kreatur unter deiner "
                     "Kontrolle ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_card", "destination": "hand"})],
            cost={"sacrifice_count": (3, "food")},
            raw_text="Opfere drei Nahrungen: Bringe eine Zielkarte aus deinem Friedhof auf "
                     "deine Hand zurück.",
        ),
    ]


register("Samwise Gamgee", _samwise_gamgee)


def _sam_loyal_attendant() -> list[AbilitySpec]:
    """Partner with Frodo, Adventurous Hobbit.
    At the beginning of combat on your turn, create a Food token.
    Activated abilities of Foods you control cost {1} less to activate.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "combat"}, "phase_relation": "you"},
            raw_text="Zu Beginn des Kampfes in deinem Zug erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "scope": "activation", "subtype": "food"})],
            raw_text="Aktivierte Fähigkeiten von Nahrungen unter deiner Kontrolle kosten "
                     "{1} weniger zum Aktivieren.",
        ),
    ]


register("Sam, Loyal Attendant", _sam_loyal_attendant)


def _academy_manufactor() -> list[AbilitySpec]:
    """If you would create a Clue, Food, or Treasure token, instead create
    one of each.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("create_one_of_each_named_token", {})],
            raw_text="Falls du einen Hinweis-, Nahrungs- oder Schatzspielstein erzeugen "
                     "würdest, erzeuge stattdessen jeweils einen davon.",
        ),
    ]


register("Academy Manufactor", _academy_manufactor)


def _access_tunnel() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {3}, {T}: Target creature with power 3 or less can't be blocked this
    turn.

    (The mana ability is bound automatically off the printed "{T}: Add
    {C}." text — `game/mana_abilities.py` — so only the second ability
    needs authoring here.)
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"max_power": 3}})],
            cost={"mana": "{3}", "taps_self": True},
            raw_text="{3}, {T}: Eine Zielkreatur mit Stärke 3 oder weniger kann in diesem "
                     "Zug nicht geblockt werden.",
        ),
    ]


register("Access Tunnel", _access_tunnel)


def _anduril_flame_of_the_west() -> list[AbilitySpec]:
    """Equipped creature gets +3/+1.
    Whenever equipped creature attacks, create two tapped 1/1 white Spirit
    creature tokens with flying. If that creature is legendary, instead
    create two of those tokens that are tapped and attacking.

    Simplified: the "instead tapped and attacking" branch for a legendary
    equipped creature isn't modeled — the tokens always enter merely
    tapped, never already attacking (no primitive yet for a token entering
    mid-combat as an attacker).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 3, "toughness": 1})],
            raw_text="Verzauberte Kreatur erhält +3/+1.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Spirit"], "keywords": ["flying"], "token_name": "Spirit", "tapped": True,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Immer wenn die verzauberte Kreatur angreift, erzeuge zwei getappte "
                     "1/1 weiße Geist-Kreaturenspielsteine mit Fliegen.",
        ),
    ]


register("Andúril, Flame of the West", _anduril_flame_of_the_west)


def _banquet_guests() -> list[AbilitySpec]:
    """Affinity for Foods
    Trample
    This creature enters with twice X +1/+1 counters on it.
    {2}, Sacrifice a Food: This creature gains indestructible until end of
    turn.

    (Affinity/Trample/the sacrifice-a-Food ability already parse on their
    own — only the X-scaled entry counters, which RULE 614.1's oracle-
    derived path can't express, needed hand-authoring.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"x_multiplier": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Diese Kreatur kommt mit doppelt X +1/+1-Marken ins Spiel.",
        ),
    ]


register("Banquet Guests", _banquet_guests)


def _bilbo_birthday_celebrant() -> list[AbilitySpec]:
    """If you would gain life, you gain that much life plus 1 instead.
    {2}{W}{B}{G}, {T}, Exile Bilbo: Search your library for any number of
    creature cards, put them onto the battlefield, then shuffle. Activate
    only if you have 111 or more life.

    Simplified: the lifegain-plus-1 replacement and the "111 or more
    life" activation gate aren't modeled (no lifegain-amount replacement/
    activation-condition primitive reaches this exact shape yet); the
    exile-self cost is approximated as sacrifice-self (no battlefield
    "exile this permanent as a cost" primitive exists — only a hand-zone
    one). The tutor-and-mass-reanimate itself is fully modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True,
            })],
            cost={"mana": "{2}{W}{B}{G}", "taps_self": True, "sacrifice": "self"},
            raw_text="{2}{W}{B}{G}, {T}, Exiliere Bilbo: Durchsuche deine Bibliothek nach "
                     "einer beliebigen Anzahl Kreaturenkarten, lege sie ins Spiel und "
                     "mische danach.",
        ),
    ]


register("Bilbo, Birthday Celebrant", _bilbo_birthday_celebrant)


def _call_for_unity() -> list[AbilitySpec]:
    """Revolt — At the beginning of your end step, if a permanent left the
    battlefield under your control this turn, put a unity counter on this
    enchantment.
    Creatures you control get +1/+1 for each unity counter on this
    enchantment.

    Simplified: Revolt's own condition ("a permanent left the battlefield
    under your control this turn") isn't modeled — the counter is added
    every end step unconditionally (no "permanent left the battlefield
    this turn" tracker exists yet, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "unity"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Revolte — Zu Beginn deines Endsegments lege eine Einheits-Marke auf "
                     "diese Verzauberung.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 1, "toughness": 1,
                "power_count": "counters_on_self", "toughness_count": "counters_on_self",
                "counter_kind": "unity",
            })],
            raw_text="Kreaturen unter deiner Kontrolle erhalten +1/+1 für jede "
                     "Einheits-Marke auf dieser Verzauberung.",
        ),
    ]


register("Call for Unity", _call_for_unity)


def _call_of_the_ring() -> list[AbilitySpec]:
    """At the beginning of your upkeep, the Ring tempts you.
    Whenever you choose a creature as your Ring-bearer, you may pay 2
    life. If you do, draw a card.

    Simplified: the second ability isn't modeled — no event fires for
    "you choose a creature as your Ring-bearer" yet (RULE 701.52a's
    choice is a `pending_choice`, not a broadcast `GameEvent`), so there's
    nothing to trigger off. The upkeep Ring-tempts-you line (this card's
    real recurring value) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("the_ring_tempts_you", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments verlockt dich der Ring.",
        ),
    ]


register("Call of the Ring", _call_of_the_ring)


def _fell_the_mighty() -> list[AbilitySpec]:
    """Destroy all creatures with power greater than target creature's
    power.

    Simplified: the dynamic threshold (the target creature's own power,
    read fresh at resolution) isn't modeled — widened to a fixed "power 4
    or greater" mass destroy (`min_power`, the same filter Dusk // Dawn
    uses), a reasonable typical-target approximation without a real
    "compare to the resolved target's own characteristic" mass-selector
    primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 4}})],
            raw_text="Zerstöre alle Kreaturen mit einer größeren Stärke als eine "
                     "Zielkreatur.",
        ),
    ]


register("Fell the Mighty", _fell_the_mighty)


def _flowering_of_the_white_tree() -> list[AbilitySpec]:
    """Legendary creatures you control get +2/+1 and have ward {1}.
    Nonlegendary creatures you control get +1/+1.

    Simplified: the granted "have ward {1}" isn't modeled — the layer-6
    keyword-grant mechanism only carries flag keywords today (ward is
    parametric, a real pre-existing gap: `parser/oracle/catalogue/
    static_handlers._flag_keywords` fails closed on any granted parametric
    keyword). Both anthems (+2/+1 legendary / +1/+1 nonlegendary) are fully
    modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "legendary_creatures_you_control", "power": 2, "toughness": 1})],
            raw_text="Legendäre Kreaturen unter deiner Kontrolle erhalten +2/+1.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "nonlegendary_creatures_you_control", "power": 1, "toughness": 1})],
            raw_text="Nicht-legendäre Kreaturen unter deiner Kontrolle erhalten +1/+1.",
        ),
    ]


register("Flowering of the White Tree", _flowering_of_the_white_tree)


def _ghost_quarter() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice this land: Destroy target land. Its controller may
    search their library for a basic land card, put it onto the
    battlefield, then shuffle.

    Simplified: the destroyed land's controller getting a compensating
    basic-land fetch isn't modeled (`SearchLibraryEffect` always searches
    *this* ability's own controller's library, not the target's
    controller) — narrowed to the land destruction alone, the card's own
    primary use.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "permanent"})],
            cost={"taps_self": True, "sacrifice": "self"},
            raw_text="{T}, Opfere dieses Land: Zerstöre ein Zielland.",
        ),
    ]


register("Ghost Quarter", _ghost_quarter)


def _go_for_the_throat() -> list[AbilitySpec]:
    """Destroy target nonartifact creature."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"without_card_type": "artifact"}})],
            raw_text="Zerstöre eine Ziel-Nichtartefaktkreatur.",
        ),
    ]


register("Go for the Throat", _go_for_the_throat)


def _gollum_obsessed_stalker() -> list[AbilitySpec]:
    """Skulk (This creature can't be blocked by creatures with greater
    power.)
    At the beginning of your end step, each opponent dealt combat damage
    this game by a creature named Gollum, Obsessed Stalker loses life
    equal to the amount of life you gained this turn.

    Simplified: narrowed to "each opponent loses life equal to the amount
    of life you gained this turn" every end step — the "only an opponent
    this specific creature has ever connected with" scoping isn't tracked
    (no "dealt combat damage by a creature named X, ever" history exists);
    in practice this only differs when Gollum himself hasn't dealt combat
    damage to anyone yet, a narrow early-game window.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount_from_life_gained_this_turn": True,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments verliert jeder Gegner so viel Leben, "
                     "wie du in diesem Zug an Leben gewonnen hast.",
        ),
    ]


register("Gollum, Obsessed Stalker", _gollum_obsessed_stalker)


def _lembas() -> list[AbilitySpec]:
    """When this artifact enters, scry 1, then draw a card.
    {2}, {T}, Sacrifice this artifact: You gain 3 life.
    When this artifact is put into a graveyard from the battlefield, its
    owner shuffles it into their library.

    Simplified: the dies-trigger self-shuffle isn't modeled (no "return
    self from graveyard" primitive exists for `ReturnFromGraveyardEffect`,
    only a real RULE 115 target pick) — Lembas simply stays in the
    graveyard once it dies, same as an ordinary permanent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scry", {"count": 1}), EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Artefakt ins Spiel kommt, prophezeie 1, dann ziehe "
                     "eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_life", {"amount": 3})],
            cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"},
            raw_text="{2}, {T}, Opfere dieses Artefakt: Du gewinnst 3 Leben.",
        ),
    ]


register("Lembas", _lembas)


def _lobelia_defender_of_bag_end() -> list[AbilitySpec]:
    """When Lobelia enters, look at the top card of each opponent's
    library and exile those cards face down.
    {T}, Sacrifice an artifact: Choose one — Until end of turn, you may
    play a card exiled with Lobelia without paying its mana cost. / Each
    opponent loses 2 life and you gain 2 life.

    Simplified: narrowed to the second mode only (each opponent loses 2
    life, you gain 2 life) — the ETB peek-and-exile plus "play what was
    exiled with ~" free-cast window needs a linked-exile-with-a-play-
    window primitive this engine doesn't have yet (`ExileEffect(remember=
    True)` links to *one* object, not a per-opponent set with its own
    later play permission).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}), EffectSpec("gain_life", {"amount": 2})],
            cost={"taps_self": True, "sacrifice": "artifact"},
            raw_text="{T}, Opfere ein Artefakt: Jeder Gegner verliert 2 Leben und du "
                     "gewinnst 2 Leben.",
        ),
    ]


register("Lobelia, Defender of Bag End", _lobelia_defender_of_bag_end)


def _motivated_pony() -> list[AbilitySpec]:
    """Trample, haste
    Whenever this creature attacks, attacking creatures get +1/+1 until
    end of turn. If a Food entered under your control this turn, untap
    those creatures and they get an additional +2/+2 until end of turn.

    Simplified: narrowed to the unconditional first half (attacking
    creatures get +1/+1) — the "if a Food entered this turn" bonus/untap
    branch isn't modeled (no "permanent of type X entered this turn"
    tracker exists, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "selector": "attacking_creatures"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, erhalten angreifende Kreaturen "
                     "+1/+1 bis zum Ende des Zuges.",
        ),
    ]


register("Motivated Pony", _motivated_pony)


def _of_herbs_and_stewed_rabbit() -> list[AbilitySpec]:
    """I — Put a +1/+1 counter on up to one target creature. Create a Food
    token.
    II — Draw a card. Create a Food token.
    III — Create a 1/1 white Halfling creature token for each Food you
    control.

    Chapters I/II are carried over verbatim from what the parser already
    resolves on its own; only chapter III (a "for each Food you control"
    dynamic count no `create_token` handler recognizes yet) needed
    hand-authoring — same shape as Vault 12: The Necropolis's own chapter
    II, just with the new ``foods_you_control`` count selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"target_kind": "creature", "optional": True}),
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
            ],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
            raw_text="I — Lege eine +1/+1-Marke auf bis zu eine Zielkreatur. Erzeuge "
                     "einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
            raw_text="II — Ziehe eine Karte. Erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                "token_name": "Halfling", "count_selector": "foods_you_control",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
            raw_text="III — Erzeuge einen 1/1 weißen Halbling-Kreaturenspielstein für "
                     "jede Nahrung, die du kontrollierst.",
        ),
    ]


register("Of Herbs and Stewed Rabbit", _of_herbs_and_stewed_rabbit)


def _peregrin_took() -> list[AbilitySpec]:
    """If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead.
    Sacrifice three Foods: Draw a card.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_named_token", {"token_name": "Food"})],
            raw_text="Falls ein oder mehr Spielsteine unter deiner Kontrolle erzeugt "
                     "würden, werden diese Spielsteine plus ein zusätzlicher "
                     "Nahrungsspielstein stattdessen erzeugt.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"sacrifice_count": (3, "food")},
            raw_text="Opfere drei Nahrungen: Ziehe eine Karte.",
        ),
    ]


register("Peregrin Took", _peregrin_took)


def _prize_pig() -> list[AbilitySpec]:
    """Whenever you gain life, put that many ribbon counters on this
    creature. Then if there are three or more ribbon counters on this
    creature, remove those counters and untap it.
    {T}: Add one mana of any color.

    Simplified: narrowed to the counter accumulation — the "at 3+, remove
    and untap" follow-up isn't modeled (no "then if this permanent's own
    counter count reaches N, do X" primitive exists yet). The counters
    still visibly accumulate, so the card isn't a no-op, just missing its
    payoff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "ribbon", "amount_from_trigger_event": "amount"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
            raw_text="Immer wenn du Leben gewinnst, lege so viele Band-Marken auf diese "
                     "Kreatur.",
        ),
    ]


register("Prize Pig", _prize_pig)


def _shire_shirriff() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, you may sacrifice a token. When you do,
    exile target creature an opponent controls until this creature leaves
    the battlefield.

    Simplified: the "you may sacrifice a token" cost gate on the exile
    isn't modeled as an interactive optional choice — the exile always
    happens (still linked, still returned when Shire Shirriff leaves), a
    strictly *more* generous approximation than requiring a token
    sacrifice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, exiliere eine Zielkreatur, die "
                     "ein Gegner kontrolliert, bis diese Kreatur das Schlachtfeld "
                     "verlässt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, bringe die exilierte "
                     "Karte zurück.",
        ),
    ]


register("Shire Shirriff", _shire_shirriff)


def _tireless_provisioner() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, create a Food token
    or a Treasure token.

    Simplified: narrowed to always creating a Food token — the "or a
    Treasure" choice isn't modeled (no interactive "choose one of two
    token types" primitive for a plain trigger body exists yet).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": False},
            },
            raw_text="Landfall — Immer wenn ein Land unter deiner Kontrolle ins Spiel "
                     "kommt, erzeuge einen Nahrungsspielstein oder einen Schatzspielstein.",
        ),
    ]


register("Tireless Provisioner", _tireless_provisioner)


def _treebeard_gracious_host() -> list[AbilitySpec]:
    """Trample, ward {2}
    When Treebeard enters, create two Food tokens.
    Whenever you gain life, put that many +1/+1 counters on target
    Halfling or Treefolk.

    Simplified: the target is widened to "target creature you control"
    (no subtype-filtered RULE 115 target kind exists yet — every real
    target_kind is either broad main-type or a fixed single subtype, not
    an ad-hoc "Halfling or Treefolk" OR-list).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Baumbart ins Spiel kommt, erzeuge zwei Nahrungsspielsteine.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "target_kind": "creature_you_control", "amount_from_trigger_event": "amount",
            })],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
            raw_text="Immer wenn du Leben gewinnst, lege so viele +1/+1-Marken auf eine "
                     "Zielkreatur unter deiner Kontrolle.",
        ),
    ]


register("Treebeard, Gracious Host", _treebeard_gracious_host)


def _smeagol_helpful_guide() -> list[AbilitySpec]:
    """At the beginning of your end step, if a creature died under your
    control this turn, the Ring tempts you.
    Whenever the Ring tempts you, target opponent reveals cards from the
    top of their library until they reveal a land card. Put that card
    onto the battlefield tapped under your control and the rest into
    their graveyard.

    Simplified: the ring-tempted payoff is narrowed to *your own* library
    instead of a chosen opponent's (`RulesEngine.dig_until` always digs
    the ability's own controller — no "dig a chosen player's library"
    variant exists), the found land enters untapped (`dig_until`'s
    "battlefield" hit destination doesn't apply RULE 614.1 tapped-entry),
    and the rest goes to exile rather than graveyard (`dig_until`'s own
    "exile" default `rest_destination`, the only one it supports besides
    a random bottom-of-library shuffle).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "the_ring_tempts_you", {},
                condition={"creatures_died_this_turn_at_least": 1},
            )],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments, falls eine Kreatur unter deiner "
                     "Kontrolle in diesem Zug gestorben ist, verlockt dich der Ring.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Land"}, "hit_destination": "battlefield", "rest_destination": "exile",
            })],
            trigger={"event": EventType.RING_TEMPTED, "condition": {"subject": "you"}},
            raw_text="Immer wenn dich der Ring verlockt, deckt ein Gegner deiner Wahl "
                     "Karten vom oberen Rand seiner Bibliothek auf, bis er eine "
                     "Landkarte aufdeckt.",
        ),
    ]


register("Sméagol, Helpful Guide", _smeagol_helpful_guide)


def _the_battle_of_bywater() -> list[AbilitySpec]:
    """Destroy all creatures with power 3 or greater. Then create a Food
    token for each creature you control.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 3}}),
                EffectSpec("create_token", {"token_name": "Food", "count_selector": "creatures_you_control"}),
            ],
            raw_text="Zerstöre alle Kreaturen mit Stärke 3 oder größer. Erzeuge danach "
                     "einen Nahrungsspielstein für jede Kreatur, die du kontrollierst.",
        ),
    ]


register("The Battle of Bywater", _the_battle_of_bywater)


def _the_one_ring() -> list[AbilitySpec]:
    """Indestructible
    When The One Ring enters, if you cast it, you gain protection from
    everything until your next turn.
    At the beginning of your upkeep, you lose 1 life for each burden
    counter on The One Ring.
    {T}: Put a burden counter on The One Ring, then draw a card for each
    burden counter on The One Ring.

    Simplified: the ETB "if you cast it" protection-from-everything grant
    isn't modeled (no "if this was cast, not put onto the battlefield
    another way" condition exists, and no generic "protection from
    everything" grant primitive) — the burden-counter draw engine/life-
    loss loop (this card's real ongoing engine) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount_from_burden_counters_on_self": True})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments verlierst du 1 Leben für "
                     "jede Bürde-Marke auf Der Eine Ring.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "burden", "amount": 1}),
                EffectSpec("draw", {"count_selector": "burden_counters_on_self"}),
            ],
            cost={"taps_self": True},
            raw_text="{T}: Lege eine Bürde-Marke auf Der Eine Ring, dann ziehe eine "
                     "Karte für jede Bürde-Marke auf Der Eine Ring.",
        ),
    ]


register("The One Ring", _the_one_ring)


def _frodo_saurons_bane() -> list[AbilitySpec]:
    """{W/B}{W/B}: If Frodo is a Citizen, it becomes a Halfling Scout with
    base power and toughness 2/3 and lifelink.
    {B}{B}{B}: If Frodo is a Scout, it becomes a Halfling Rogue with
    "Whenever this creature deals combat damage to a player, that player
    loses the game if the Ring has tempted you four or more times this
    game. Otherwise, the Ring tempts you."

    — RULE 205.1b's "becomes a copy-independent creature with a new type
    line", turned out to need no new engine primitive after all despite the
    BACKLOG's earlier read: it's a two-step RULE 613.6 standing conditional
    static, gated on the permanent's own progress, driven by a plain custom
    counter (``frodo_stage``, no whitelist restricts `AddCountersEffect`'s
    ``kind`` — a "level"/"class_level" counter in spirit, just not literally
    either mechanic).

    Each activated ability's own legality ("if Frodo is a Citizen/Scout")
    is `ActivationCost.activation_condition` (PAR-10) reading the same
    `source_counters` gate a static's `active_if` does, so activating out
    of order is simply illegal rather than a no-op. Its own effect is
    nothing but bumping the counter — the actual transformation lives in
    the two `static` specs below, each gated ``active_if: source_counters``
    with a **``min`` and no ``max``**, deliberately: both stay active once
    unlocked (not mutually-exclusive bands like a Leveler's tiers), so the
    Rogue-stage static — which never restates a P/T — doesn't need to; RULE
    613.7 timestamp layering keeps the still-active Scout static's own
    ``pt_set``/type-change-with-P/T (RULE 613.4's "becomes an X/Y creature"
    shape, ``type_change``'s own ``power``/``toughness`` params) under the
    Rogue static's later ``set_subtypes`` override, exactly matching the
    printed card.

    The granted Rogue-stage trigger's "that player loses the game … .
    Otherwise, the Ring tempts you." is a genuine if/else the engine had no
    shape for: `ConditionalEffect` only ever gated a single existing
    effect, with no "otherwise" branch, and `grant_triggered_ability`'s own
    ``grant_effects`` list was built via a bare `EffectRegistry.create`
    with no way to condition an entry at all. Closed generally rather than
    with a one-off: `continuous._build_grant_effect` now honours an
    optional per-entry ``condition`` key the same shape `EffectSpec.
    condition` already has, and `ConditionalEffect` gained the symmetric
    ``ring_tempted_at_most`` key alongside the existing ``ring_tempted_at_
    least`` — two independently-gated conditionals with complementary
    bounds standing in for one if/else, the same pattern the front face's
    own compound clause already established for AND rather than OR. "That
    player" (not "you") is `LoseGameTriggerDamagedPlayerEffect`, the
    player-flavoured mirror of `ExileTriggerDamagedCreatureEffect`'s
    "that creature" pronoun off the granted ability's own firing `DAMAGE`
    event, since Frodo's controller and the player he just hit are usually
    different people.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "frodo_stage", "amount": 1})],
            cost={
                "mana": "{W/B}{W/B}",
                "activation_condition": {"kind": "source_counters", "counter": "frodo_stage", "max": 0},
            },
            raw_text='{W/B}{W/B}: Falls Frodo ein Bürger ist, wird er ein '
                     'Halbling-Kundschafter mit der Basisstärke/-widerstandskraft '
                     '2/3 und Lebensverknüpfung.',
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "frodo_stage", "amount": 1})],
            cost={
                "mana": "{B}{B}{B}",
                "activation_condition": {"kind": "source_counters", "counter": "frodo_stage", "min": 1, "max": 1},
            },
            raw_text='{B}{B}{B}: Falls Frodo ein Kundschafter ist, wird er ein '
                     'Halbling-Schurke mit "Wenn diese Kreatur einem Spieler '
                     'Kampfschaden zufügt, verliert jener Spieler die Partie, '
                     'falls der Ring dich in diesem Spiel viermal oder öfter '
                     'verlockt hat. Andernfalls verlockt dich der Ring."',
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "set_subtypes": ["Halfling", "Scout"], "power": 2, "toughness": 3,
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 1},
                }),
                EffectSpec("grant_keyword", {
                    "affects": "self",
                    "keywords": ["lifelink"],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 1},
                }),
            ],
            raw_text="(Halbling-Kundschafter-Stufe)",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "set_subtypes": ["Halfling", "Rogue"],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 2},
                }),
                EffectSpec("grant_triggered_ability", {
                    "affects": "self",
                    "trigger_event": EventType.DAMAGE,
                    "filter": {"combat": True, "is_player": True},
                    "grant_effects": [
                        {
                            "type": "lose_game_trigger_damaged_player",
                            "params": {},
                            "condition": {"ring_tempted_at_least": 4},
                        },
                        {
                            "type": "the_ring_tempts_you",
                            "params": {},
                            "condition": {"ring_tempted_at_most": 3},
                        },
                    ],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 2},
                }),
            ],
            raw_text="(Halbling-Schurke-Stufe)",
        ),
    ]


register("Frodo, Sauron's Bane", _frodo_saurons_bane)


# ---------------------------------------------------------------------------
# "Wyleth Equip" saved-deck-priority batch (continued)
# ---------------------------------------------------------------------------


def _ardenn_intrepid_archaeologist() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may attach any number
    of Auras and Equipment you control to target permanent or player.
    Partner (You can have two commanders if both have partner.)

    Simplified: narrowed to attaching *one* Aura/Equipment already
    attached to something you control, to another target creature you
    control — the "any number, freely among permanents or players" mass
    rearrange has no primitive (`AttachChosenEffect`, built for Halvar's
    own single-object clause, is the closest shape this engine has).
    (Partner is bound by the keyword catalogue automatically.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control", "to_kind": "creature_you_control",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "combat"}, "phase_relation": "you"},
            optional=True,
            raw_text="Zu Beginn des Kampfes in deinem Zug kannst du eine Verzauberung "
                     "oder Ausrüstung unter deiner Kontrolle an eine andere Zielkreatur "
                     "unter deiner Kontrolle anlegen.",
        ),
    ]


register("Ardenn, Intrepid Archaeologist", _ardenn_intrepid_archaeologist)


def _armored_skyhunter() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, look at the top six cards of your
    library. You may put an Aura or Equipment card from among them onto
    the battlefield. If an Equipment is put onto the battlefield this
    way, you may attach it to a creature you control. Put the rest of
    those cards on the bottom of your library in a random order.

    Simplified: the found Aura/Equipment enters unattached — the "you may
    attach it to a creature you control" follow-up isn't modeled (no
    "dig hit, then optionally attach what was just found" primitive), and
    the rest go to exile instead of a random spot on the bottom of the
    library (`dig_until`'s own supported rest destinations).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": ["Aura", "Equipment"]}, "hit_destination": "battlefield",
                "rest_destination": "exile",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, sieh dir die obersten sechs "
                     "Karten deiner Bibliothek an. Du kannst eine Verzauberungs- oder "
                     "Ausrüstungskarte aus ihnen ins Spiel bringen.",
        ),
    ]


register("Armored Skyhunter", _armored_skyhunter)


def _martial_coup() -> list[AbilitySpec]:
    """Create X 1/1 white Soldier creature tokens. If X is 5 or more,
    destroy all other creatures.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "count": "x", "power": 1, "toughness": 1, "colors": ["W"],
                    "subtypes": ["Soldier"], "token_name": "Soldier",
                }),
                EffectSpec(
                    "destroy", {"selector": "all_creatures", "exclude_created": True},
                    condition={"source_x_paid_at_least": 5},
                ),
            ],
            raw_text="Erzeuge X 1/1 weiße Soldat-Kreaturenspielsteine. Falls X 5 oder "
                     "größer ist, zerstöre alle anderen Kreaturen.",
        ),
    ]


register("Martial Coup", _martial_coup)


def _masterwork_of_ingenuity() -> list[AbilitySpec]:
    """You may have this Equipment enter as a copy of any Equipment on the
    battlefield.

    Simplified: widened to "any permanent" — the target-kind vocabulary
    (docs/11 §10) has no Equipment-only restriction, matching the same
    documented looseness `Clever Impersonator`'s own catalogue entry
    already accepts for "any nonland permanent".
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {"target_kind": "permanent"})],
            raw_text="Du kannst dieses Ausrüstungsstück als Kopie eines beliebigen "
                     "Ausrüstungsstücks ins Spiel kommen lassen.",
        ),
    ]


register("Masterwork of Ingenuity", _masterwork_of_ingenuity)


def _raph_and_leo_sibling_rivals() -> list[AbilitySpec]:
    """Whenever Raph & Leo attack, if it's the first combat phase of the
    turn, untap one or two target attacking creatures. After this phase,
    there is an additional combat phase.

    MEC-28: the same RULE 603.4 intervening-if extra-combat template as
    Finest Hour/Karlach, Fury of Avernus/Raiyuu, Storm's Edge (all four now
    parser-`MODELED`) — hand-authored here only because of its own
    remaining gap, a genuine RULE 601.2c "N or M target X" range. ENG-30
    built that primitive (`targeting.TargetSpec.count_max`) — this entry now
    uses the real "one or two" range (``count=1, count_max=2``) instead of
    the single-mandatory-target simplification it shipped with.

    Still hand-authored, not deleted in favor of the oracle-text parser: the
    parser's shared multi-target grammar (`catalogue.handlers.
    _MULTI_TARGET_ROWS`) has no row for a *targeted* "attacking creatures"
    phrase — only the untargeted mass-selector "untap all attacking
    creatures" form ENG-29 built. Adding one is real, separate scope (a new
    row plus threading a `creature_filter` through `_multi_target_params`,
    which has no such param today) that only this one card would exercise;
    left for whenever a second real card needs it rather than built
    speculatively here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {
                        "target_kind": "creature", "creature_filter": {"attacking": True}, "untap": True,
                        "count": 1, "count_max": 2,
                    },
                    condition={"is_first_combat_phase": True},
                ),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
            raw_text="Whenever Raph & Leo attack, if it's the first combat phase of the turn, "
                     "untap one or two target attacking creatures. After this phase, there is "
                     "an additional combat phase.",
        ),
    ]


register("Raph & Leo, Sibling Rivals", _raph_and_leo_sibling_rivals)


def _balthier_and_fran() -> list[AbilitySpec]:
    """Reach
    Vehicles you control get +1/+1 and have vigilance and reach.
    Whenever a Vehicle crewed by Balthier and Fran this turn attacks, if
    it's the first combat phase of the turn, you may pay {1}{R}{G}. If you
    do, after this phase, there is an additional combat phase.

    MEC-29: the last of MEC-28's own five-card list, closed by building the
    two primitives its own diagnosis named. RULE 702.122 **Crew** as real
    engine state (`ActivationCost.crew_power`, `GameEngine._resolve_crew_
    cost`/`_crew_pool`, `GameObject.crewed_by_ids`, `effect_binder._crew_
    activated_ability`) — "Crew N" had been parser-*recognized* the whole
    time (the coverage gate's own keyword catalogue), just never bound to
    behaviour anywhere in `game/`/`models/` (`grep -rn "crewed_by"` found
    nothing before this), the same "recognized but inert" gap Cycling had
    before PAR-9 — and a new `"crewed_by_self"` RULE 603.1 group-subject
    trigger-condition key (`effect_binder._build_group_ok`) reading it live
    off the board. Hand-authored here rather than left to the oracle-text
    parser: "a Vehicle crewed by ~ this turn attacks" is a genuinely
    singleton phrasing (`parser_probe.py cards 'crewed by'` finds exactly
    one other cached card, Mighty Servant of Leuk-o, printing a completely
    different "crewed by exactly N creatures" template) not worth a
    dedicated grammar row for.

    The anthem clause is duplicated here rather than left to the parser for
    a narrower reason: it already parses correctly on its own (a real fix
    below), but registering this card for its trigger clause means
    `ability_catalogue.specs_for` takes *all* of this card's non-keyword
    abilities from the registry instead — "Reach" alone still auto-attaches
    from `parse_keywords`, which runs regardless of registration.

    Building Crew surfaced two real, previously-invisible bugs, both fixed
    at the root rather than worked around for this one card:

    1. `_ANTHEM_RE`'s `_scope` (`parser/oracle/catalogue/static_handlers.
       py`) had no non-creature-**subtype** guard the way `_NONCREATURE_
       TYPES` already gives it for non-creature main *types* ("Artifacts
       you control…"), so a bare "Vehicles" scope silently fell through to
       the ordinary creature-subtype reading and produced ``affects:
       creatures_you_control`` — wrong, since a Vehicle isn't a creature
       until crewed, so the anthem would have excluded every uncrewed
       Vehicle it's printed to buff. No real card had ever reached this
       shape's *whole* card fully-MODELED before, so it silently shipped
       wrong without ever showing up as a coverage regression. Fixed with
       `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params`, reused by
       `_GRANT_RE`/`_QUOTED_GRANT_RE`'s existing PAR-3 fallback chain too —
       any other "Vehicles [you control] get/have …" card benefits for
       free, not just this one.
    2. A freshly crewed Vehicle had no power/toughness at all —
       `Card.__init__`'s own invariant refuses P/T on a noncreature, so a
       Vehicle's *printed* P/T (RULE 208.1: some noncreature permanents,
       Vehicles chief among them, print P/T that matters once something
       else makes them a creature) had never been captured anywhere in
       this engine's `Card` model. Without it, `type_change`'s "becomes an
       artifact creature" grant left the crewed Vehicle at 0/0, dying to
       RULE 704.5f the instant the next state-based action check ran —
       Crew would have bound correctly while being unusable in any real
       game. Fixed with `Card.vehicle_power`/`vehicle_toughness`
       (deliberately separate fields, not a relaxation of the existing
       invariant, so every reader that treats "power is not None" as a
       creature check stays correct), populated by `scryfall_client.
       card_from_scryfall_data` for any noncreature Vehicle and read by
       `effect_binder._crew_activated_ability` when building the grant.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "power": 1, "toughness": 1,
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
                EffectSpec("grant_keyword", {
                    "keywords": ["vigilance", "reach"],
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
            ],
            raw_text="Vehicles you control get +1/+1 and have vigilance and reach.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "pay_cost_then",
                    {
                        "cost": "{1}{R}{G}",
                        "effects": [{"type": "extra_combat_phase", "params": {}}],
                    },
                    condition={"is_first_combat_phase": True},
                ),
            ],
            trigger={
                "event": "ATTACKS",
                "condition": {"subject": "group", "subtypes": ["vehicle"], "crewed_by_self": True},
            },
            raw_text="Whenever a Vehicle crewed by ~ this turn attacks, if it's the first "
                     "combat phase of the turn, you may pay {1}{R}{G}. If you do, after this "
                     "phase, there is an additional combat phase.",
        ),
    ]


register("Balthier and Fran", _balthier_and_fran)


def _tifa_martial_artist() -> list[AbilitySpec]:
    """Melee (Whenever this creature attacks, it gets +1/+1 until end of
    turn for each opponent you attacked this combat.)
    Whenever one or more creatures you control with power 7 or greater deal
    combat damage to a player, untap all creatures you control. If it's the
    first combat phase of your turn, there is an additional combat phase
    after this phase.

    MEC-29: the other half of MEC-28's own five-card list, closed by
    building the two primitives its own diagnosis named — though the
    diagnosis itself needed correcting first (this repo's standing rule:
    verify a "needs a new primitive" claim against current code before
    trusting it, even when the claim is this ticket's own). RULE 603.1's
    DAMAGE-subject group scoping for "you control" already existed
    (`_GROUP_CONTROLLER_EVENT_KEYS["DAMAGE"]`, built for Bident of Thassa/
    Deepfathom Skulker's own "a creature you control deals combat damage to
    a player") — the real, still-open gap was the **"one or more"**
    quantifier: RULE 603.1's ordinary group subject fires once *per
    creature*, but "one or more creatures … deal combat damage" describes a
    single condition about the whole combat damage step. This engine
    already has the identical shape solved once, for a different verb: RULE
    506.4's "a player attacks you **with one or more creatures**" is
    exactly why `EventType.PLAYER_ATTACKED` exists instead of reusing the
    per-declaration `ATTACKS` event (see that event's own docstring) — two
    creatures qualifying simultaneously must trigger this ability *once*,
    not twice (this card's own payoff, an extra combat phase, would
    otherwise double up per RULE 508.6/509.5's simultaneous combat damage).
    Built the combat-damage sibling the same way:
    `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
    (`GameEngine._apply_combat_damage`), fired once per (contributing
    creatures' controller, player hit) pair after a damage step, carrying
    ``max_power`` — the highest power among that pair's contributors — for
    a new `"contributor_power_at_least"` trigger-condition threshold
    (`effect_binder._trigger_condition`, mirroring the existing
    ``spell_mana_value_at_most`` idiom) to check: the aggregate event names
    no single acting object a `"group"` condition's own per-object
    ``min_power`` filter could read off the board.

    Hand-authored rather than left to the oracle-text parser: this
    "one or more `<type>` you control with power `<n>` or greater deal
    combat damage to a player" template is, per `parser_probe.py cards
    'deal combat damage to a player'`, printed on exactly this one cached
    card — not worth a dedicated grammar row for a single user. "If it's
    the first combat phase of **your** turn" (not "…of **the** turn",
    `_FIRST_COMBAT_PHASE_CONDITION_RE`'s own exact wording) rides the same
    RULE 603.4 intervening-if `ConditionalEffect` key
    (``is_first_combat_phase``) under a harmless wording variant: a combat
    phase only ever happens on its own active player's turn, so "the turn"
    and "your turn" name the same thing for every real card printing
    either.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("tap", {"selector": "creatures_you_control", "untap": True}),
                EffectSpec("extra_combat_phase", {}, condition={"is_first_combat_phase": True}),
            ],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "you"},
                "contributor_power_at_least": 7,
            },
            raw_text="Whenever one or more creatures you control with power 7 or greater deal "
                     "combat damage to a player, untap all creatures you control. If it's the "
                     "first combat phase of your turn, there is an additional combat phase "
                     "after this phase.",
        ),
    ]


register("Tifa, Martial Artist", _tifa_martial_artist)


def _sokenzan_crucible_of_defiance() -> list[AbilitySpec]:
    """{T}: Add {R}.
    Channel — {3}{R}, Discard this card: Create two 1/1 colorless Spirit
    creature tokens. They gain haste until end of turn. This ability
    costs {1} less to activate for each legendary creature you control.

    (The mana ability is bound automatically off the printed "{T}: Add
    {R}." text.) Simplified: the "{1} less for each legendary creature"
    cost reduction isn't modeled (`continuous.activation_cost_reduction_
    for` has no per-count scaling for a hand-zone Channel-style cost yet,
    only a flat subtype-scoped one) — Channel itself (offered and payable
    from hand, discarding this card as its cost) is fully modeled at its
    full printed price.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Spirit"], "keywords": ["haste"], "token_name": "Spirit",
            })],
            cost={"mana": "{3}{R}", "discard_self": True},
            raw_text="Kanalisieren — {3}{R}, Wirf diese Karte ab: Erzeuge zwei 1/1 "
                     "farblose Geist-Kreaturenspielsteine. Sie erhalten Eile bis zum "
                     "Ende des Zuges.",
        ),
    ]


register("Sokenzan, Crucible of Defiance", _sokenzan_crucible_of_defiance)


def _valakut_awakening() -> list[AbilitySpec]:
    """Put any number of cards from your hand on the bottom of your
    library, then draw that many cards plus one.

    Simplified: narrowed to "draw a card" — no primitive puts a player-
    chosen number of hand cards on the bottom of the library paired with a
    scaled draw yet (`PutHandCardsOnTopEffect` is a fixed count, to the
    top, with no paired draw).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("draw", {"count": 1})],
            raw_text="Lege eine beliebige Anzahl Karten aus deiner Hand unter deine "
                     "Bibliothek, ziehe danach so viele Karten plus eine.",
        ),
    ]


register("Valakut Awakening", _valakut_awakening)
register("Valakut Awakening // Valakut Stoneforge", _valakut_awakening)


def _boseiju_who_endures() -> list[AbilitySpec]:
    """{T}: Add {G}.
    Channel — {1}{G}, Discard this card: Destroy target artifact,
    enchantment, or nonbasic land an opponent controls. That player may
    search their library for a land card with a basic land type, put it
    onto the battlefield, then shuffle. This ability costs {1} less to
    activate for each legendary creature you control.

    — Eliferate deck batch. The mana ability is bound automatically off
    the printed "{T}: Add {G}." text. Same Channel/`dynamic_reduction`
    shape as `Eiganjo, Seat of the Empire`'s own per-legendary-creature
    discount (`costs.ActivationCost.dynamic_reduction`'s
    `legendary_creatures_you_control` count_selector). The destroy+search
    body is a new primitive, `effects.
    DestroyControllerMaySearchBasicLandEffect` — pairs `RulesEngine.destroy`
    (unlike Winds of Abandon's exile-then-search sibling, so an
    indestructible/regeneration-shielded target survives) with an
    *optional*, untapped basic-land search offered to the destroyed
    permanent's own controller. `target_kind` drops the "an opponent
    controls" restriction — the same documented simplification
    `ExileControllerSearchesBasicLandEffect` already uses (no target kind
    carries an ownership exclusion yet).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy_controller_may_search_basic_land", {})],
            cost={
                "text": "{1}{G}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
            raw_text="Kanalisieren — {1}{G}, Wirf diese Karte ab: Zerstöre ein "
                     "Zielartefakt, eine Zielverzauberung oder ein nichtgrundlegendes "
                     "Zielland, das ein Gegner kontrolliert. Dieser Spieler kann in "
                     "seiner Bibliothek nach einer Landkarte mit einem grundlegenden "
                     "Landtyp suchen, sie ins Spiel legen und danach seine Bibliothek "
                     "mischen. Diese Fähigkeit kostet {1} weniger für jede legendäre "
                     "Kreatur, die du kontrollierst.",
        ),
    ]


register("Boseiju, Who Endures", _boseiju_who_endures)


def _otawara_soaring_city() -> list[AbilitySpec]:
    """{T}: Add {U}.
    Channel — {3}{U}, Discard this card: Return target artifact, creature,
    enchantment, or planeswalker to its owner's hand. This ability costs
    {1} less to activate for each legendary creature you control.

    Same Channel/`dynamic_reduction` shape as `Eiganjo, Seat of the
    Empire`/`Boseiju, Who Endures` (MEC-12) — the mana ability binds
    automatically off the printed "{T}: Add {U}." text, and the per-
    legendary-creature discount is `costs.ActivationCost.dynamic_reduction`
    with the same `legendary_creatures_you_control` count_selector. The
    bounce targets `targeting.py`'s new `artifact_creature_enchantment_
    or_planeswalker` kind (MEC-12) — the four-permanent-type union this
    card's own printed wording needs, not yet used by any other card.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec(
                "return_to_hand",
                {"target_kind": "artifact_creature_enchantment_or_planeswalker"},
            )],
            cost={
                "text": "{3}{U}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
            raw_text="Kanalisieren — {3}{U}, Wirf diese Karte ab: Gib ein "
                     "Zielartefakt, eine Zielkreatur, eine Zielverzauberung oder "
                     "einen Ziel-Planeswalker der Hand seines Besitzers zurück. "
                     "Diese Fähigkeit kostet {1} weniger für jede legendäre Kreatur, "
                     "die du kontrollierst.",
        ),
    ]


register("Otawara, Soaring City", _otawara_soaring_city)


def _takenuma_abandoned_mire() -> list[AbilitySpec]:
    """{T}: Add {B}.
    Channel — {3}{B}, Discard this card: Mill three cards, then return a
    creature or planeswalker card from your graveyard to your hand. This
    ability costs {1} less to activate for each legendary creature you
    control.

    — Eliferate deck batch, same Channel/`dynamic_reduction` shape as
    `Boseiju, Who Endures`/`Eiganjo, Seat of the Empire`. "Return a creature
    or planeswalker card from your graveyard to your hand" is untargeted
    RAW (no "target"), but reuses `ReturnFromGraveyardEffect`'s own new
    `graveyard_creature_or_planeswalker` kind (`targeting.py`'s
    `_GRAVEYARD_TYPE_FILTERS`) as a targeted choice instead — the same
    targeted-vs-untargeted-choice simplification this engine's whole
    Regrowth-adjacent recursion family already makes.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature_or_planeswalker",
                    "destination": "hand",
                }),
            ],
            cost={
                "text": "{3}{B}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
            raw_text="Kanalisieren — {3}{B}, Wirf diese Karte ab: Mille drei Karten, "
                     "kehre danach eine Kreaturenkarte oder Planeswalkerkarte aus "
                     "deinem Friedhof auf deine Hand zurück. Diese Fähigkeit kostet "
                     "{1} weniger für jede legendäre Kreatur, die du kontrollierst.",
        ),
    ]


register("Takenuma, Abandoned Mire", _takenuma_abandoned_mire)


def _dwynen_gilt_leaf_daen() -> list[AbilitySpec]:
    """Reach
    Other Elf creatures you control get +1/+1.
    Whenever Dwynen attacks, you gain 1 life for each attacking Elf you
    control.

    — Eliferate deck batch. Reach and the anthem already parse; the attack
    trigger's amount is `continuous.count_selector`'s new
    `attacking_creatures_you_control_of_type_<x>` (`GainLifeEffect.
    count_selector`) — the attacking-scoped sibling of the existing
    `creatures_you_control_of_type_` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {
                "count_selector": "attacking_creatures_you_control_of_type_elf",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Dwynen angreift, gewinnst du 1 Leben für jeden "
                     "angreifenden Elfen unter deiner Kontrolle.",
        ),
    ]


register("Dwynen, Gilt-Leaf Daen", _dwynen_gilt_leaf_daen)


def _elvish_warmaster() -> list[AbilitySpec]:
    """Whenever one or more other Elves you control enter, create a 1/1
    green Elf Warrior creature token. This ability triggers only once each
    turn.
    {5}{G}{G}: Elves you control get +2/+2 and gain deathtouch until end of
    turn.

    — Eliferate deck batch. The pump ability already parses; the ETB
    trigger is the same "whenever one or more other X you control enter…
    triggers only once each turn" shape `Merry, Warden of Isengard` already
    uses for artifacts, just subtype-scoped to Elf instead of type-scoped
    to artifact.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "subtypes": ["elf"],
                    "controller": "you", "other": True,
                },
                "limit": True,
            },
            raw_text="Immer wenn ein oder mehr andere Elfen unter deiner Kontrolle ins "
                     "Spiel kommen, erzeuge einen 1/1 grünen Elfen-Krieger-"
                     "Kreaturenspielstein. Diese Fähigkeit wird nur einmal pro Zug "
                     "ausgelöst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 2, "toughness": 2, "keywords": ["deathtouch"],
                "selector": "creatures_you_control_of_type_elf",
            })],
            cost={"text": "{5}{G}{G}"},
            raw_text="{5}{G}{G}: Elfen unter deiner Kontrolle erhalten +2/+2 und "
                     "Todesberührung bis zum Ende des Zuges.",
        ),
    ]


register("Elvish Warmaster", _elvish_warmaster)


def _morcants_loyalist() -> list[AbilitySpec]:
    """Other Elves you control get +1/+1.
    When this creature dies, return another target Elf card from your
    graveyard to your hand.

    — Eliferate deck batch. The anthem already parses; the dies trigger
    reuses `ReturnFromGraveyardEffect`'s new `subtype` filter
    (`targeting.TargetSpec.subtype`) scoped to "elf", which also excludes
    this card's own now-in-the-graveyard copy the same way an ordinary
    battlefield "another" target excludes its own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "subtype": "elf",
                "destination": "hand",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur stirbt, kehre eine andere Zielelfenkarte aus "
                     "deinem Friedhof auf deine Hand zurück.",
        ),
    ]


register("Morcant's Loyalist", _morcants_loyalist)


def _elvish_harbinger() -> list[AbilitySpec]:
    """When this creature enters, you may search your library for an Elf
    card, reveal it, then shuffle and put that card on top.
    {T}: Add one mana of any color.

    — Eliferate deck batch. The mana ability is bound automatically off the
    printed "{T}: Add one mana of any color." text; the ETB tutor is a
    plain `SearchLibraryEffect` — an optional, `{"type": "Elf"}`-filtered
    library search to the top of the library, the same "reveal" simplification
    (not separately modeled) every other tutor in this catalogue makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Elf"}, "destination": "library_top", "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du in deiner Bibliothek "
                     "nach einer Elfenkarte suchen, sie zeigen, mischen und diese Karte "
                     "danach oben auf deine Bibliothek legen.",
        ),
    ]


register("Elvish Harbinger", _elvish_harbinger)


def _elvish_guidance() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional {G} for each Elf on the battlefield.

    — Eliferate deck batch. `Wild Growth`'s own triggered-mana-ability
    shape (RULE 605.1b/605.4), just with a board-scaled amount instead of a
    flat one: `AddManaEffect.amount_selector`'s new unscoped
    `creatures_of_type_<x>` count (`continuous.count_selector`) rather
    than the `_you_control`-scoped form every existing consumer used —
    "on the battlefield" here means every Elf, regardless of controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color": "G", "amount_selector": "creatures_of_type_elf",
                "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
            raw_text="Verzaubere Land\nImmer wenn das verzauberte Land für Mana getappt "
                     "wird, erzeugt sein Beherrscher zusätzlich {G} für jeden Elfen auf "
                     "dem Spielfeld.",
        ),
    ]


register("Elvish Guidance", _elvish_guidance)


def _vanquishers_banner() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    Creatures you control of the chosen type get +1/+1.
    Whenever you cast a creature spell of the chosen type, draw a card.

    — Eliferate deck batch. The ETB type choice and the anthem parse on
    their own (`choose_creature_type_on_enter`/`anthem` with
    `subtype_from_source`) — reproduced here verbatim (whole-card hand-
    authoring replaces the parser's own specs entirely, `specs_for`'s
    registry-wins precedence, so a partial registration would silently
    drop them) — alongside the one clause that didn't: the cast trigger.
    That's a new `effect_binder` predicate, `"cast_of_chosen_type"` —
    reads `GameObject.chosen_type` live at check time (unlike the
    fixed-at-bind `"subtypes"` group filter, the wanted type isn't known
    until the ETB choice resolves) against the live-looked-up cast spell's
    own printed subtypes.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
            raw_text="Wähle beim Ins-Spiel-Kommen dieses Artefakts einen Kreaturentyp.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 1, "affects": "creatures_you_control",
                "subtype_from_source": True,
            })],
            raw_text="Kreaturen des gewählten Typs unter deiner Kontrolle erhalten +1/+1.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
                "cast_of_chosen_type": True,
            },
            raw_text="Immer wenn du einen Kreaturenzauberspruch des gewählten Typs "
                     "wirkst, ziehe eine Karte.",
        ),
    ]


register("Vanquisher's Banner", _vanquishers_banner)


def _realmwalker() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    As this creature enters, choose a creature type.
    You may look at the top card of your library any time.
    You may cast creature spells of the chosen type from the top of your
    library.

    — Eliferate deck batch. Changeling (keyword) and the ETB type choice
    (`choose_creature_type_on_enter`) already parse on their own —
    reproduced here verbatim, since whole-card hand-authoring replaces the
    parser's own output wholesale (`specs_for`'s registry-wins precedence).
    The standing permission is `top_library_permission`'s new
    `chosen_type_creature_only` flag — the same `Oracle of Mul Daya`/
    `Glarb, Calamity's Augur` family, narrowed by `GameObject.chosen_type`
    read live (`game/top_library.py`) instead of a fixed mana-value/
    noncreature gate.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
            raw_text="Wähle beim Ins-Spiel-Kommen dieser Kreatur einen Kreaturentyp.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "chosen_type_creature_only": True,
            })],
            raw_text="Du darfst dir jederzeit die oberste Karte deiner Bibliothek "
                     "ansehen. Du darfst Kreaturenzaubersprüche des gewählten Typs von "
                     "der Oberseite deiner Bibliothek wirken.",
        ),
    ]


register("Realmwalker", _realmwalker)


def _selfless_safewright() -> list[AbilitySpec]:
    """Flash
    Convoke (Your creatures can help cast this spell. Each creature you tap
    while casting this spell pays for {1} or one mana of that creature's
    color.)
    When this creature enters, choose a creature type. Other permanents you
    control of that type gain hexproof and indestructible until end of
    turn.

    — Eliferate deck batch. Flash/Convoke come from the RULE 702 keyword
    catalogue automatically. The ETB clause is a *resolve-time* "choose a
    creature type" (RulesEngine.request_choose_creature_type_grant — see
    its docstring for why this is a different primitive from RULE 601.2b's
    as-it-enters `choose_creature_type_on_enter`), immediately followed by
    the grant (`grant_keywords_to_chosen_type_until_eot`) as its own
    ``then_specs`` tail, parked/resumed by the existing RULE 608.2
    suspended-resolution machinery (`GameState.deferred_effects`) rather
    than any new continuation plumbing.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("request_choose_creature_type_grant", {
                "then_specs": [
                    {
                        "type": "grant_keywords_to_chosen_type_until_eot",
                        "params": {"keywords": ["hexproof", "indestructible"]},
                    },
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, wähle einen Kreaturentyp. "
                     "Andere bleibende Karten dieses Typs unter deiner Kontrolle "
                     "erhalten Unantastbarkeit und Unzerstörbarkeit bis zum Ende des "
                     "Zuges.",
        ),
    ]


register("Selfless Safewright", _selfless_safewright)


def _roaming_throne() -> list[AbilitySpec]:
    """Ward {2}
    As this creature enters, choose a creature type.
    This creature is the chosen type in addition to its other types.
    If a triggered ability of another creature you control of the chosen
    type triggers, it triggers an additional time.

    — Eliferate deck batch, closing the one remaining gap the 2026-08-05
    Eliferate/Keywords Showcase batch deliberately left open (Done_Backend.md
    called out "Roaming Throne's trigger-doubling" by name). Ward, the ETB
    type choice, and the self type-grant already parse on their own —
    reproduced here verbatim (whole-card hand-authoring replaces the
    parser's own output wholesale). The doubling itself is a genuinely new
    RULE 603.3d primitive: `effects.TriggerDoublerEffect`, a continuous
    marker (no `apply()` behaviour of its own, the same
    `TopLibraryPermissionEffect`/`CantBeCounteredEffect` idiom) that
    `continuous.trigger_doubler_bonus` scans for from `game/rules/
    triggers_mixin.py`'s `_collect_triggers` — the one place every
    permanent's own triggered ability gets placed on the stack — which now
    appends `1 + bonus` copies instead of always exactly one. Placed as
    independent extra copies (not a single ability that "resolves twice")
    so 2+ pending copies are still separately orderable (RULE 603.3b) if a
    second trigger is also waiting.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
            raw_text="Wähle beim Ins-Spiel-Kommen dieser Kreatur einen Kreaturentyp.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})],
            raw_text="Diese Kreatur ist zusätzlich zu ihren anderen Typen vom "
                     "gewählten Typ.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {})],
            raw_text="Wenn eine ausgelöste Fähigkeit einer anderen Kreatur des "
                     "gewählten Typs unter deiner Kontrolle ausgelöst wird, wird sie "
                     "ein zusätzliches Mal ausgelöst.",
        ),
    ]


register("Roaming Throne", _roaming_throne)


def _vraska_betrayals_sting() -> list[AbilitySpec]:
    """Compleated ({B/P} can be paid with {B} or 2 life.)
    0: You draw a card and lose 1 life. Proliferate.
    −2: Target creature becomes a Treasure artifact with "{T}: Add one
    mana of any color" and loses all other card types and abilities.
    −9: If target player has fewer than nine poison counters, they get a
    number of poison counters equal to the difference.

    — Eliferate deck batch. Compleated (keyword) and "0:" already parse on
    their own — reproduced here verbatim (whole-card hand-authoring
    replaces the parser's own output wholesale).

    "−2:" is a genuinely permanent (RAW has no "until") characteristic
    overwrite, so it's two chained `grant_until` effects at
    ``duration="rest_of_game"`` rather than a `temp_*`-field pump: the
    first carries the real target and applies `type_change`'s new
    `remove_types`/`add_types`/`add_subtypes` (RULE 613.7f's own
    creature-type-removal path, `GameObject._removed_types`, generalized
    from the Reconfigure-only special case it used to be); the second
    reuses that same target via `previous_subject` (the "Tap target
    land. **It** doesn't untap…" pronoun idiom) to layer on
    `remove_all_abilities` (RULE 613.7f's Humility/Dress Down strip) and
    `grant_mana_ability`. **Documented simplification**: the granted mana
    ability is modeled as a plain "{T}: Add one mana of any color" rather
    than "{T}, Sacrifice this artifact: …" — `granted_mana_options`
    (`GameObject`'s own layer-6 grant list `mana_abilities_for` reads once
    `loses_all_abilities` is set) only ever carries a tap cost, and
    `Card.is_artifact` itself (the printed, immutable characteristic a
    few older code paths read directly rather than through the
    layer-aware `type_words`/`is_creature`) isn't flipped — a spell that
    specifically targets "artifact" via one of those paths won't
    recognize this creature as one, while every layer-aware consumer is
    correct.

    "−9:" is `top_up_player_counter` — a threshold top-up (RULE 122.1)
    rather than a flat amount, new alongside the flat `add_player_counters`
    every other poison-granting card already used.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("lose_life", {"amount": 1}),
                EffectSpec("proliferate", {}),
            ],
            cost={"loyalty": 0},
            raw_text="0: Du ziehst eine Karte und verlierst 1 Leben. Proliferiere.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "target_kind": "creature",
                    "static": {
                        "type": "type_change",
                        "params": {
                            "add_types": ["artifact"], "remove_types": ["creature"],
                            "add_subtypes": ["Treasure"],
                        },
                    },
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "remove_all_abilities", "params": {}},
                }),
                EffectSpec("grant_until", {
                    "duration": "rest_of_game", "previous_subject": True,
                    "static": {"type": "grant_mana_ability", "params": {"mana": [{"ANY": 1}]}},
                }),
            ],
            cost={"loyalty": -2},
            raw_text='−2: Die Zielkreatur wird zu einem Schatz-Artefakt mit "{T}: Erzeuge '
                     'ein Mana einer beliebigen Farbe" und verliert alle anderen '
                     "Kartentypen und Fähigkeiten.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("top_up_player_counter", {"kind": "poison", "threshold": 9})],
            cost={"loyalty": -9},
            raw_text="−9: Falls der Zielspieler weniger als neun Gift-Marken hat, "
                     "erhält er eine Anzahl Gift-Marken gleich der Differenz.",
        ),
    ]


register("Vraska, Betrayal's Sting", _vraska_betrayals_sting)


def _vraska_golgari_queen() -> list[AbilitySpec]:
    """+2: You may sacrifice another permanent. If you do, you gain 1 life
    and draw a card.
    −3: Destroy target nonland permanent with mana value 3 or less.
    −9: You get an emblem with "Whenever a creature you control deals
    combat damage to a player, that player loses the game."

    — Eliferate deck batch. "−3:" already parses (destroy, max_mana_value
    3) — reproduced here verbatim. "+2:" is the shipped `choose_objects`
    wrapper (`ChooseObjectsEffect`, the general "you may sacrifice/tap/
    return a permanent you control" chooser — Tevesh Szat's own "you may
    sacrifice another creature or planeswalker" precedent) with a `then`
    tail; "−9:" is the same quoted-emblem-at-loyalty shape `Tyvar Kell`'s
    own −6 introduced (a genuine nested `AbilitySpec`, since there's no
    card text to recursively parse the way the oracle-text front-end's
    `_emblem_ability_spec` does for a spell/triggered clause).
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("lose_game_trigger_damaged_player", {})],
        trigger={
            "event": EventType.DAMAGE,
            "condition": {"subject": "group", "type": "creature", "controller": "you", "combat": True},
        },
        raw_text="Immer wenn eine Kreatur unter deiner Kontrolle einem Spieler "
                 "Kampfschaden zufügt, verliert dieser Spieler die Partie.",
    )
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "permanent", "optional": True, "exclude_self": True,
                "then": [
                    {"type": "gain_life", "params": {"amount": 1}},
                    {"type": "draw", "params": {"count": 1}},
                ],
            })],
            cost={"loyalty": 2},
            raw_text="+2: Du kannst eine andere bleibende Karte opfern. Falls du dies "
                     "tust, gewinnst du 1 Leben und ziehst eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "permanent", "max_mana_value": 3})],
            cost={"loyalty": -3},
            raw_text="−3: Zerstöre eine bleibende Zielkarte, die kein Land ist, mit "
                     "Manawert 3 oder weniger.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -9},
            raw_text='−9: Du erhältst einen Emblem-Spielstein mit "Immer wenn eine '
                     "Kreatur unter deiner Kontrolle einem Spieler Kampfschaden zufügt, "
                     'verliert dieser Spieler die Partie."',
        ),
    ]


register("Vraska, Golgari Queen", _vraska_golgari_queen)


def _vraskas_fall() -> list[AbilitySpec]:
    """Each opponent sacrifices a creature or planeswalker of their choice
    and gets a poison counter.

    — Eliferate deck batch. `SacrificeEffect`'s existing `selector=
    "each_opponent"` (Professor Onyx's −3 precedent) already opens a real
    RULE 601.2c-style choice *for that opponent* rather than an auto-pick
    when ``greatest_power`` isn't set, and `what="creature_or_planeswalker"`
    is the one compound sacrifice-type word this catalogue already
    recognizes (Tevesh Szat). The poison half is the plain
    `add_player_counters` every other poison-granting card uses, same
    `selector="each_opponent"`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {
                    "selector": "each_opponent", "what": "creature_or_planeswalker",
                }),
                EffectSpec("add_player_counters", {
                    "selector": "each_opponent", "kind": "poison", "amount": 1,
                }),
            ],
            raw_text="Jeder Gegner opfert eine Kreatur oder einen Planeswalker "
                     "eigener Wahl und erhält eine Gift-Marke.",
        ),
    ]


register("Vraska's Fall", _vraskas_fall)


def _glissa_sunslayer() -> list[AbilitySpec]:
    """First strike, deathtouch
    Whenever Glissa Sunslayer deals combat damage to a player, choose one —
    • You draw a card and lose 1 life.
    • Destroy target enchantment.
    • Remove up to three counters from target permanent.

    — Eliferate deck batch. First strike/deathtouch come from the RULE 702
    keyword catalogue automatically. The modal trigger reuses `Bloodforged
    Battle-Axe`'s own "deals combat damage to a player" trigger shape
    (`filter={"combat": True, "is_player": True}`) plus a `triggered`-kind
    `modes` block — RULE 603.3's own "a triggered ability's mode(s) chosen
    as it's put on the stack" path, already shipped and used by parsed
    modal triggers, just not yet by a hand-authored one. The third mode's
    `remove_counters` with `max_count` is the exact primitive
    `RemoveCountersEffect`'s own docstring already names Glissa Sunslayer
    for — built for this card, never previously wired to it.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
            modes={
                "options": [
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [EffectSpec("destroy", {"target_kind": "enchantment"})],
                    [EffectSpec("remove_counters", {"target_kind": "permanent", "max_count": 3})],
                ],
                "descriptions": [
                    "Du ziehst eine Karte und verlierst 1 Leben.",
                    "Zerstöre eine Zielverzauberung.",
                    "Entferne bis zu drei Marken von einer bleibenden Zielkarte.",
                ],
            },
            raw_text="Immer wenn Glissa Sunslayer einem Spieler Kampfschaden zufügt, "
                     "wähle eins —",
        ),
    ]


register("Glissa Sunslayer", _glissa_sunslayer)


def _glissa_herald_of_predation() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, choose one —
    • Incubate 2 twice. (To incubate 2, create an Incubator token with two
      +1/+1 counters on it and "{2}: Transform this token." It transforms
      into a 0/0 Phyrexian artifact creature.)
    • Transform all Incubator tokens you control.
    • Phyrexians you control gain first strike and deathtouch until end of
      turn.

    — Eliferate deck batch. Incubate (RULE 701.51-adjacent) is modeled as
    a genuine two-state token, the same way morph/manifest's face-down
    permanents are: "Incubate 2 twice" creates two power/toughness-less
    "Incubator" tokens (`services.token_database.synthesize_token_card`
    makes a bare token with no P/T a plain noncreature "Token Artifact"
    on its own) each carrying 2 +1/+1 counters (`create_token`'s new
    `extra_counters` param), and the standalone `Incubator` catalogue
    entry below binds onto every one of them (`bind_from_catalogue` reads
    a token's abilities off its own name, "exactly like a real
    permanent") its own "{2}: Transform this token" — a permanent
    (RAW: no "until") `type_change` animation into a 0/0 Phyrexian
    artifact creature, so its counters do the rest. The second mode,
    "transform all Incubator tokens you control", reuses that exact same
    animation en masse via the new `transform_named_tokens` primitive
    rather than a bespoke one-off. The third mode is a plain `pump` with a
    subtype-scoped `selector`, the same `creatures_you_control_of_type_<x>`
    vocabulary `Elvish Warmaster`'s pump ability already uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
            modes={
                "options": [
                    [EffectSpec("create_token", {
                        "count": 2, "token_name": "Incubator",
                        "extra_counters": {"kind": "+1/+1", "count": 2},
                    })],
                    [EffectSpec("transform_named_tokens", {
                        "token_name": "Incubator", "add_types": ["creature"],
                        "add_subtypes": ["Phyrexian"], "power": 0, "toughness": 0,
                    })],
                    [EffectSpec("pump", {
                        "selector": "creatures_you_control_of_type_phyrexian",
                        "keywords": ["first_strike", "deathtouch"],
                    })],
                ],
                "descriptions": [
                    "Inkubiere 2 zweimal.",
                    "Transformiere alle Inkubator-Spielsteine unter deiner Kontrolle.",
                    "Phyrexianer unter deiner Kontrolle erhalten Erstschlag und "
                    "Todesberührung bis zum Ende des Zuges.",
                ],
            },
            raw_text="Zu Beginn des Kampfes in deinem Zug wähle eins —",
        ),
    ]


register("Glissa, Herald of Predation", _glissa_herald_of_predation)


def _incubator_token() -> list[AbilitySpec]:
    """{2}: Transform this token. It transforms into a 0/0 Phyrexian
    artifact creature.

    — the Incubate token family (RULE 701.51-adjacent): any Incubate
    producer's `create_token` call names this token "Incubator", and
    `bind_from_catalogue` binds a fresh token's abilities off its own
    name exactly like a real permanent, so this one registration covers
    every one of them. A genuinely permanent (RAW: no "until")
    characteristic change, so `grant_until` at ``duration="rest_of_game"``
    — targeting the token's own source, no RULE 115 target ("this
    token", the same self-acting mode `RegenerateEffect` uses) — animates
    it into a creature via `type_change`'s existing power/toughness
    animation params (0/0 base; its already-present +1/+1 counters do
    the rest) rather than a new primitive.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                        "power": 0, "toughness": 0,
                    },
                },
            })],
            cost={"text": "{2}"},
            raw_text="{2}: Transformiere diesen Spielstein. Er transformiert sich in "
                     "eine 0/0 farblose phyrexianische Artefaktkreatur.",
        ),
    ]


register("Incubator", _incubator_token)


def _malakir_rebirth() -> list[AbilitySpec]:
    """Choose target creature. You lose 2 life. Until end of turn, that
    creature gains "When this creature dies, return it to the battlefield
    tapped under its owner's control."

    — Eliferate deck batch. A single-target spell (the life loss is
    untargeted, so the *grant* carries the one real RULE 115 target): the
    granted ability is `grant_triggered_ability` (RULE 613.7f, the same
    shape `Kaldra Compleat`'s own quoted grant uses) at
    ``duration="end_of_turn"`` rather than a printed permanent's standing
    grant, wrapping the new `return_self_from_graveyard_untargeted` —
    `effects.ReturnSelfFromGraveyardEffect`'s ``obj=None`` fallback to its
    own ``source``, which `continuous.py`'s layer-6 grant machinery binds
    fresh per affected object, so "it" is always whichever creature the
    grant landed on.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("lose_life", {"amount": 2}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": "creature",
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": EventType.DIES,
                            "grant_effects": [
                                {"type": "return_self_from_graveyard_untargeted",
                                 "params": {"destination": "battlefield", "tapped": True}},
                            ],
                        },
                    },
                }),
            ],
            raw_text="Wähle eine Zielkreatur. Du verlierst 2 Leben. Bis zum Ende des "
                     "Zuges erhält jene Kreatur \"Wenn diese Kreatur stirbt, bringe sie "
                     "getappt unter der Kontrolle ihres Besitzers ins Spiel zurück.\"",
        ),
    ]


register("Malakir Rebirth", _malakir_rebirth)
register("Malakir Rebirth // Malakir Mire", _malakir_rebirth)


def _restless_cottage() -> list[AbilitySpec]:
    """This land enters tapped.
    {T}: Add {B} or {G}.
    {2}{B}{G}: This land becomes a 4/4 black and green Horror creature
    until end of turn. It's still a land.
    Whenever this land attacks, create a Food token and exile up to one
    target card from a graveyard.

    — Eliferate deck batch. "Enters tapped" and the mana ability are both
    oracle-derived/auto-bound, needing no hand-authoring. The animation
    ability reuses the self-targeting `grant_until`/`type_change` shape
    the `Incubator` token's own transform already established (RULE
    613.7c, ``target_kind=None`` — "this land", no RULE 115 target).
    **Documented simplification**: the colour change ("black and green")
    isn't modeled — `type_change`'s layer-4 params have no colour field
    (RULE 613's own layer 5 does colour; no manland in this catalogue sets
    it yet), so the animated creature keeps whatever colour identity the
    land already had (usually colourless).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Horror"],
                        "power": 4, "toughness": 4,
                    },
                },
            })],
            cost={"text": "{2}{B}{G}"},
            raw_text="{2}{B}{G}: Dieses Land wird bis zum Ende des Zuges zu einer 4/4 "
                     "schwarzen und grünen Horror-Kreatur. Es ist weiterhin ein Land.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "optional": True}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Land angreift, erzeuge einen Nahrungsspielstein und "
                     "exiliere bis zu eine Zielkarte aus einem Friedhof.",
        ),
    ]


register("Restless Cottage", _restless_cottage)


def _revitalizing_repast() -> list[AbilitySpec]:
    """Put a +1/+1 counter on target creature. It gains indestructible
    until end of turn.

    — Eliferate deck batch. One real target (the counter effect); the
    keyword grant reuses it via `grant_until`'s `previous_subject` pronoun
    idiom rather than declaring a second target of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["indestructible"]}},
                }),
            ],
            raw_text="Lege eine +1/+1-Marke auf eine Zielkreatur. Sie erhält "
                     "Unzerstörbarkeit bis zum Ende des Zuges.",
        ),
    ]


register("Revitalizing Repast", _revitalizing_repast)
register("Revitalizing Repast // Old-Growth Grove", _revitalizing_repast)


def _champions_of_the_perfect() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, behold an Elf and exile
    it. (Exile an Elf you control or an Elf card from your hand.)
    Whenever you cast a creature spell, draw a card.
    When this creature leaves the battlefield, return the exiled card to
    its owner's hand.

    — Eliferate deck batch. The cast-trigger draw already parses on its
    own — reproduced verbatim. **Documented simplification**: "behold"
    (RULE 601.2b's "exile a permanent you control or a card from your
    hand" additional-cost shape) isn't in `AbilitySpec.additional_cost`'s
    closed vocabulary (`sacrifice`/`discard`/`pay_life` only, and
    ``additional_cost`` is spell-only regardless — adding an exile-and-
    remember-the-card kind is real, cross-cutting cost-payment plumbing
    disproportionate to one card), so this models the tax as `{"sacrifice":
    "creature"}` instead — a real Elf-tribal tax, just paid from the
    battlefield only and to the graveyard rather than exile — and the
    trailing "return the exiled card" trigger (which has nothing to
    reference under this simplification) is left off rather than guessed
    at.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            additional_cost={"sacrifice": "creature"},
            raw_text="Opfere als zusätzliche Kosten für das Wirken dieses Zauberspruchs "
                     "eine Kreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
            },
            raw_text="Immer wenn du einen Kreaturenzauberspruch wirkst, ziehe eine Karte.",
        ),
    ]


register("Champions of the Perfect", _champions_of_the_perfect)


def _flourishing_defenses() -> list[AbilitySpec]:
    """Whenever a -1/-1 counter is put on a creature, you may create a 1/1
    green Elf Warrior creature token.

    — Eliferate deck batch. Unscoped (any creature, any controller) —
    filtered straight off the `COUNTER` event's own payload
    (``kind``/``recipient_is_creature``), no "group" subject needed at
    all since there's no controller/identity restriction to check.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
            optional=True,
            raw_text="Immer wenn eine -1/-1-Marke auf eine Kreatur gelegt wird, kannst "
                     "du einen 1/1 grünen Elfen-Krieger-Kreaturenspielstein erzeugen.",
        ),
    ]


register("Flourishing Defenses", _flourishing_defenses)


def _formidable_speaker() -> list[AbilitySpec]:
    """When this creature enters, you may discard a card. If you do,
    search your library for a creature card, reveal it, put it into your
    hand, then shuffle.
    {1}, {T}: Untap another target permanent.

    — Eliferate deck batch. The ETB is `pay_cost_then` (RULE 118.3) —
    "discard a card" as the optional payment, the search as its "if you
    do" tail; the reveal step isn't separately modeled, the same
    simplification every tutor in this catalogue already makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "search", "params": {"criteria": "Creature", "destination": "hand"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, kannst du eine Karte abwerfen. "
                     "Falls du dies tust, durchsuche deine Bibliothek nach einer "
                     "Kreaturenkarte, zeige sie, nimm sie auf deine Hand und mische "
                     "danach deine Bibliothek.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "permanent"})],
            cost={"text": "{1}, {T}"},
            raw_text="{1}, {T}: Enttappe eine andere Zielkarte, die eine bleibende "
                     "Karte ist.",
        ),
    ]


register("Formidable Speaker", _formidable_speaker)


def _galadhrim_ambush() -> list[AbilitySpec]:
    """Create X 1/1 green Elf Warrior creature tokens, where X is the
    number of attacking creatures.
    Prevent all combat damage that would be dealt this turn by non-Elf
    creatures.

    — Eliferate deck batch. The token creation already parses on its own
    — reproduced verbatim. The prevention clause is `prevent_all_combat_
    damage`'s new `exclude_subtype` qualifier (RULE 615) — see its
    docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "colors": ["G"], "subtypes": ["Elf", "Warrior"], "keywords": [],
                    "token_name": "Elf Warrior", "power": 1, "toughness": 1,
                    "count_selector": "attacking_creatures",
                }),
                EffectSpec("prevent_all_combat_damage", {"exclude_subtype": "elf"}),
            ],
            raw_text="Erzeuge X 1/1 grüne Elfen-Krieger-Kreaturenspielsteine, wobei X "
                     "die Anzahl der angreifenden Kreaturen ist. Verhindere jeglichen "
                     "Kampfschaden, der diesen Zug von Nicht-Elfen-Kreaturen zugefügt "
                     "werden würde.",
        ),
    ]


register("Galadhrim Ambush", _galadhrim_ambush)


def _mirrormind_crown() -> list[AbilitySpec]:
    """As long as this Equipment is attached to a creature, the first time
    you would create one or more tokens each turn, you may instead create
    that many tokens that are copies of equipped creature.
    Equip {2}

    — Eliferate deck batch. Equip is a RULE 702 keyword, auto-bound.
    **Documented simplification**: modeled as an ordinary once-per-turn
    trigger that *additionally* creates the copies (`CopyPermanentEffect`'s
    new `attached_permanent` self-mode + `count_from_trigger_event`)
    rather than a true `CREATE_TOKENS` replacement that *redirects*
    (blocks the original tokens and substitutes copies instead) — that
    event's own replacement hook only lets a `ReplacementEffect` rescale
    the *amount*, never swap in a different token identity, and building
    that redirection is real engine plumbing disproportionate to one
    Equipment. The practical difference only matters when a player would
    have preferred *not* getting the original tokens too, which is rare
    for an "instead" upgrade like this one.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "count_from_trigger_event": "amount",
            })],
            trigger={
                "event": EventType.CREATE_TOKENS,
                "condition": {"subject": "group", "controller": "you"},
                "limit": True,
                "requires_attached": True,
            },
            raw_text="Solange diese Ausrüstung an eine Kreatur befestigt ist, erzeugst "
                     "du das erste Mal, wenn du in diesem Zug einen oder mehr "
                     "Spielsteine erzeugen würdest, zusätzlich ebenso viele Spielsteine, "
                     "die Kopien der ausgerüsteten Kreatur sind.",
        ),
    ]


register("Mirrormind Crown", _mirrormind_crown)


def _throne_of_the_god_pharaoh() -> list[AbilitySpec]:
    """At the beginning of your end step, each opponent loses life equal
    to the number of tapped creatures you control.

    — Eliferate deck batch. `LoseLifeEffect`'s new `amount_from_count_
    selector` (the `GainLifeEffect` sibling it never had) reading the new
    `tapped_creatures_you_control` count (`continuous.count_selector`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent", "amount_from_count_selector": "tapped_creatures_you_control",
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
            },
            raw_text="Zu Beginn deines Endsegments verliert jeder Gegner Leben in Höhe "
                     "der Anzahl getappter Kreaturen, die du kontrollierst.",
        ),
    ]


register("Throne of the God-Pharaoh", _throne_of_the_god_pharaoh)


def _trystan_callous_cultivator() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature enters or transforms into Trystan, Callous
    Cultivator, mill three cards. Then if there is an Elf card in your
    graveyard, you gain 2 life.
    At the beginning of your first main phase, you may pay {B}. If you do,
    transform Trystan.

    — Eliferate deck batch. Deathtouch is a RULE 702 keyword, auto-bound.
    **Documented simplification**: the "or transforms into ~" half of the
    first trigger isn't modeled — this engine has no `TRANSFORMED` event
    at all yet (a genuinely open engine-primitive gap, not specific to
    this card), so only the ETB half fires; the mill+conditional-lifegain
    body itself is fully modeled (`mill` + `EffectSpec.condition`'s new
    `graveyard_has_type`). The second ability is a plain resolve-time
    `pay_cost_then` (RULE 118.3) wrapping `transform`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("gain_life", {"amount": 2}, condition={"graveyard_has_type": "elf"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, mille drei Karten. Falls sich "
                     "danach eine Elfenkarte in deinem Friedhof befindet, gewinnst du 2 "
                     "Leben.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{B}",
                "effects": [{"type": "transform", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
            raw_text="Zu Beginn deines ersten Hauptsegments kannst du {B} bezahlen. "
                     "Falls du dies tust, transformiere Trystan.",
        ),
    ]


register("Trystan, Callous Cultivator", _trystan_callous_cultivator)
register("Trystan, Callous Cultivator // Trystan, Penitent Culler", _trystan_callous_cultivator)


def _high_perfect_morcant() -> list[AbilitySpec]:
    """Whenever High Perfect Morcant or another Elf you control enters,
    each opponent blights 1. (They each put a -1/-1 counter on a creature
    they control.)
    Tap three untapped Elves you control: Proliferate. Activate only as a
    sorcery.

    — Eliferate deck batch. The activated ability already parses on its
    own — reproduced here verbatim. The ETB trigger is the new
    `each_opponent_counter_own_creature` primitive — see its docstring
    for the documented auto-pick simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_opponent_counter_own_creature", {"amount": 1, "kind": "-1/-1"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "subtypes": ["elf"], "controller": "you", "other": True},
            },
            raw_text="Immer wenn High Perfect Morcant oder ein anderer Elf unter "
                     "deiner Kontrolle ins Spiel kommt, verseucht jeder Gegner 1. "
                     "(Sie legen jeweils eine -1/-1-Marke auf eine Kreatur, die sie "
                     "kontrollieren.)",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("proliferate", {}), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Tap three untapped Elves you control"},
            raw_text="Tappe drei enttappte Elfen, die du kontrollierst: Proliferiere. "
                     "Aktiviere nur wie einen Hauptzauberspruch.",
        ),
    ]


register("High Perfect Morcant", _high_perfect_morcant)


def _backdraft_hellkite() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, each instant and sorcery card in your
    graveyard gains flashback until end of turn. The flashback cost is
    equal to its mana cost.

    — Imodane deck batch. Flying is a RULE 702 keyword, auto-bound. The
    grant is the new `grant_graveyard_cast_permission_this_turn` — see
    its docstring for why it's a fresh primitive rather than the existing
    standing `graveyard_cast_permission` (Lurrus-shaped: tied to a
    permanent's continued presence, not turn-scoped).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_graveyard_cast_permission_this_turn", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur angreift, erhält jede Spontanzauber- und "
                     "Hexereikarte in deinem Friedhof bis zum Ende des Zuges "
                     "Wiederkehr. Die Wiederkehrkosten entsprechen ihren Manakosten.",
        ),
    ]


register("Backdraft Hellkite", _backdraft_hellkite)


def _blasphemous_act() -> list[AbilitySpec]:
    """This spell costs {1} less to cast for each creature on the
    battlefield.
    Blasphemous Act deals 13 damage to each creature.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. The cost reduction is `cost_reduction`'s existing
    Delve/Affinity-shaped ``per`` count-selector param, just with the new
    unscoped `creatures_on_battlefield` selector instead of the `_you_
    control`-scoped form every existing consumer used.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1, "per": "creatures_on_battlefield",
            })],
            raw_text="Dieser Zauberspruch kostet {1} weniger, um ihn zu wirken, für "
                     "jede Kreatur auf dem Spielfeld.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 13, "selector": "each_creature"})],
            raw_text="Blasphemous Act fügt jeder Kreatur 13 Schaden zu.",
        ),
    ]


register("Blasphemous Act", _blasphemous_act)


def _chain_lightning() -> list[AbilitySpec]:
    """Chain Lightning deals 3 damage to any target. Then that player or
    that permanent's controller may pay {R}{R}. If the player does, they
    may copy this spell and may choose a new target for that copy.

    — Imodane deck batch. **Documented simplification**: the "hot potato"
    copy-chain (control of the copy passes to whichever player just paid,
    who may then trigger *another* copy) isn't modeled — no primitive
    threads a spell copy's "controller" through a resolve-time optional
    payment offered to the *damage recipient* rather than the caster, and
    building one is disproportionate to this one card. Modeled as the
    bare "deals 3 damage to any target."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 3, "target_kind": "any"})],
            raw_text="Chain Lightning fügt einem beliebigen Ziel 3 Schaden zu.",
        ),
    ]


register("Chain Lightning", _chain_lightning)


def _fireblast() -> list[AbilitySpec]:
    """You may sacrifice two Mountains rather than pay this spell's mana
    cost.
    Fireblast deals 4 damage to any target.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. **Documented simplification**: the alternative
    "sacrifice two Mountains instead of paying mana" cost isn't modeled —
    this engine's cost vocabulary has no free-alternative-cost concept
    (RULE 601.2f's own free-cast condition gate is for a fixed condition,
    not a player-chosen cost substitution); the spell is fully castable
    at its normal printed mana cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
            raw_text="Fireblast fügt einem beliebigen Ziel 4 Schaden zu.",
        ),
    ]


register("Fireblast", _fireblast)


def _frantic_firebolt() -> list[AbilitySpec]:
    """Frantic Firebolt deals X damage to target creature, where X is 2
    plus the number of cards in your graveyard that are instant cards,
    sorcery cards, and/or have an Adventure.

    — Imodane deck batch. `DealDamageEffect`'s new `amount_from_count_
    selector`/`amount_plus_count_selector`, reading the new
    `instant_sorcery_or_adventure_cards_in_your_graveyard` count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "target_kind": "creature",
                "amount_from_count_selector": "instant_sorcery_or_adventure_cards_in_your_graveyard",
                "amount_plus_count_selector": 2,
            })],
            raw_text="Frantic Firebolt fügt einer Zielkreatur X Schaden zu, wobei X 2 "
                     "plus die Anzahl der Karten in deinem Friedhof ist, die "
                     "Spontanzauberkarten, Hexereikarten und/oder Abenteuer sind.",
        ),
    ]


register("Frantic Firebolt", _frantic_firebolt)


def _lava_coil() -> list[AbilitySpec]:
    """Lava Coil deals 4 damage to target creature. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. The second clause is the new
    `grant_die_to_exile_this_turn` — see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "creature"}),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
            raw_text="Lava Coil fügt einer Zielkreatur 4 Schaden zu. Falls jene "
                     "Kreatur in diesem Zug sterben würde, exiliere sie stattdessen.",
        ),
    ]


register("Lava Coil", _lava_coil)


def _lithomantic_barrage() -> list[AbilitySpec]:
    """This spell can't be countered.
    Lithomantic Barrage deals 1 damage to target creature or planeswalker.
    It deals 5 damage instead if that target is white and/or blue.

    — Imodane deck batch. "Can't be countered" already parses on its own
    — reproduced verbatim. The damage clause is `DealDamageEffect`'s new
    `amount_if_target_color`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("cant_be_countered", {})],
            raw_text="Dieser Zauberspruch kann nicht gekontert werden.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 1, "target_kind": "creature_or_planeswalker",
                "amount_if_target_color": {"amount": 5, "colors": ["W", "U"]},
            })],
            raw_text="Lithomantic Barrage fügt einer Zielkreatur oder einem "
                     "Zielplaneswalker 1 Schaden zu. Es fügt stattdessen 5 Schaden "
                     "zu, falls das Ziel weiß und/oder blau ist.",
        ),
    ]


register("Lithomantic Barrage", _lithomantic_barrage)


def _smite_the_deathless() -> list[AbilitySpec]:
    """Smite the Deathless deals 3 damage to target creature. That
    creature loses indestructible until end of turn. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. One real target, reused via `grant_until`'s
    `previous_subject` pronoun idiom for both the keyword-removal and the
    die-to-exile grant.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "remove_keyword", "params": {"keywords": ["indestructible"]}},
                }),
                EffectSpec("grant_die_to_exile_this_turn", {}),
            ],
            raw_text="Smite the Deathless fügt einer Zielkreatur 3 Schaden zu. Jene "
                     "Kreatur verliert Unzerstörbarkeit bis zum Ende des Zuges. Falls "
                     "jene Kreatur in diesem Zug sterben würde, exiliere sie "
                     "stattdessen.",
        ),
    ]


register("Smite the Deathless", _smite_the_deathless)


def _stonesplitter_bolt() -> list[AbilitySpec]:
    """Bargain
    Stonesplitter Bolt deals X damage to target creature or planeswalker.
    If this spell was bargained, it deals twice X damage to that
    permanent instead.

    — Imodane deck batch. Bargain comes from the RULE 702 keyword
    catalogue automatically. The damage clause is `DealDamageEffect`'s new
    `double_if_bargained`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature_or_planeswalker", "double_if_bargained": True,
            })],
            raw_text="Stonesplitter Bolt fügt einer Zielkreatur oder einem "
                     "Zielplaneswalker X Schaden zu. Falls dieser Zauberspruch "
                     "erhandelt wurde, fügt er jener bleibenden Karte stattdessen "
                     "zweimal X Schaden zu.",
        ),
    ]


register("Stonesplitter Bolt", _stonesplitter_bolt)


def _torch_breath() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if it targets a blue permanent.
    This spell can't be countered.
    Torch Breath deals X damage to target creature or planeswalker.

    — Imodane deck batch. **Documented simplification**: the target-
    dependent cost reduction isn't modeled (RULE 601.2f cost reduction is
    a board-state/count-selector concept everywhere else in this catalogue;
    a reduction keyed off a target chosen *during the same cast* is a
    different, unbuilt timing shape) — the spell is fully castable at its
    normal printed cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("damage", {"amount": "x", "target_kind": "creature_or_planeswalker"}),
            ],
            raw_text="Dieser Zauberspruch kann nicht gekontert werden. Torch Breath "
                     "fügt einer Zielkreatur oder einem Zielplaneswalker X Schaden zu.",
        ),
    ]


register("Torch Breath", _torch_breath)


def _torch_the_tower() -> list[AbilitySpec]:
    """Bargain
    Torch the Tower deals 2 damage to target creature or planeswalker. If
    this spell was bargained, instead it deals 3 damage to that permanent
    and you scry 1.
    If a permanent dealt damage by Torch the Tower would die this turn,
    exile it instead.

    — Imodane deck batch. Bargain is auto-bound. **Documented
    simplification**: the bargained "and you scry 1" rider isn't modeled
    alongside the amount override (`amount_if_bargained` swaps the number;
    composing it with a *second*, conditional-only-when-bargained effect
    would need `EffectSpec.condition`'s `bargained` key on a *second*
    `scry` effect — omitted here, so a bargained cast deals 3 damage
    without the scry). The die-to-exile clause is the new
    `grant_die_to_exile_this_turn`, unconditional (it applies whichever
    amount was dealt).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {
                    "amount": 2, "target_kind": "creature_or_planeswalker", "amount_if_bargained": 3,
                }),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
            raw_text="Torch the Tower fügt einer Zielkreatur oder einem "
                     "Zielplaneswalker 2 Schaden zu. Falls dieser Zauberspruch "
                     "erhandelt wurde, fügt er stattdessen 3 Schaden zu. Falls eine "
                     "bleibende Karte, der von Torch the Tower Schaden zugefügt "
                     "wurde, in diesem Zug sterben würde, exiliere sie stattdessen.",
        ),
    ]


register("Torch the Tower", _torch_the_tower)


def _torch_the_witness() -> list[AbilitySpec]:
    """Torch the Witness deals twice X damage to target creature. If
    excess damage was dealt to that creature this way, investigate.
    (Create a Clue token. It's an artifact with "{2}, Sacrifice this
    token: Draw a card.")

    — Imodane deck batch. The new `damage_then_investigate_if_excess` —
    see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_then_investigate_if_excess", {"target_kind": "creature"})],
            raw_text="Torch the Witness fügt einer Zielkreatur zweimal X Schaden zu. "
                     "Falls jener Kreatur dadurch überschüssiger Schaden zugefügt "
                     "wurde, untersuche.",
        ),
    ]


register("Torch the Witness", _torch_the_witness)


def _voltage_surge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice an
    artifact.
    Voltage Surge deals 2 damage to target creature or planeswalker. If
    this spell's additional cost was paid, Voltage Surge deals 4 damage
    instead.

    — Imodane deck batch. **Documented simplification**: the optional
    "you may sacrifice an artifact" additional cost isn't modeled —
    `AbilitySpec.additional_cost`'s closed vocabulary has no *optional*
    sacrifice shape (RULE 702.157's own Bargain keyword is the one
    optional-sacrifice-as-you-cast mechanic this engine has, and this
    card doesn't print it), so building a parallel one-off "may" cost path
    is disproportionate to this one card. Modeled as the unconditional
    base "deals 2 damage" — never the upgraded 4, and never actually
    asking for an artifact.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 2, "target_kind": "creature_or_planeswalker"})],
            raw_text="Voltage Surge fügt einer Zielkreatur oder einem Zielplaneswalker "
                     "2 Schaden zu.",
        ),
    ]


register("Voltage Surge", _voltage_surge)


def _galvanic_relay() -> list[AbilitySpec]:
    """Exile the top card of your library. During your next turn, you may
    play that card.
    Storm (When you cast this spell, copy it for each spell cast before
    it this turn.)

    — Imodane deck batch. Storm is a RULE 702 keyword, auto-bound. The
    exile clause is the shipped `impulsive_draw` (Light Up the Stage-
    shaped) — "during your next turn" is `same_turn_only=False`'s own
    "until the end of your next turn" window, a superset of the printed
    text rather than a narrower one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 1})],
            raw_text="Exiliere die oberste Karte deiner Bibliothek. Während deines "
                     "nächsten Zuges kannst du jene Karte spielen.",
        ),
    ]


register("Galvanic Relay", _galvanic_relay)


def _wrenns_resolve() -> list[AbilitySpec]:
    """Exile the top two cards of your library. Until the end of your
    next turn, you may play those cards.

    — Imodane deck batch. The shipped `impulsive_draw`, count=2.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 2})],
            raw_text="Exiliere die obersten zwei Karten deiner Bibliothek. Bis zum "
                     "Ende deines nächsten Zuges kannst du jene Karten spielen.",
        ),
    ]


register("Wrenn's Resolve", _wrenns_resolve)


def _virtue_of_courage() -> list[AbilitySpec]:
    """Whenever a source you control deals noncombat damage to an
    opponent, you may exile that many cards from the top of your library.
    You may play those cards this turn.

    — Imodane deck batch. `ImpulsiveDrawEffect`'s new `count_from_trigger_
    event` (the firing `DAMAGE` event's own ``amount``), ``same_turn_
    only=True`` for "this turn" rather than "until your next turn".
    **Documented simplification**: "noncombat" isn't filtered (any damage
    to an opponent, combat included, triggers this) — the `DAMAGE` event's
    own ``combat`` field would need a `filter={"combat": False, …}`
    alongside the group condition's own controller check, omitted for
    time; a combat-damage source is rare in a spells-matter red deck so
    the practical difference is small.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {
                "count_from_trigger_event": "amount", "same_turn_only": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"is_player": True},
            },
            raw_text="Immer wenn eine Quelle, die du kontrollierst, einem Gegner "
                     "Nichtkampfschaden zufügt, kannst du so viele Karten von der "
                     "Oberseite deiner Bibliothek exilieren. Du kannst diese Karten "
                     "in diesem Zug spielen.",
        ),
    ]


register("Virtue of Courage", _virtue_of_courage)
register("Virtue of Courage // Embereth Blaze", _virtue_of_courage)


def _sunbirds_invocation() -> list[AbilitySpec]:
    """Whenever you cast a spell from your hand, reveal the top X cards of
    your library, where X is that spell's mana value. You may cast a
    spell with mana value X or less from among cards revealed this way
    without paying its mana cost. Put the rest on the bottom of your
    library in a random order.

    — Imodane deck batch. **Documented simplification**: modeled as
    revealing and offering a free cast of only the *top card* of the
    library (not the top X, and without the "mana value X or less"
    filter) — `dig_until`'s existing "reveal until a match, free-cast the
    hit, shuffle/bottom the rest" shape (Tibalt's Trickery/Possibility
    Storm-shaped), reused with an always-true criteria so it stops at
    exactly one card. A criteria keyed to X (the triggering spell's mana
    value) was tried and reverted: `dig_until` reveals cards *until* one
    matches, so on a low X and an unlucky top of library it would dig
    arbitrarily deep — safe for Tibalt's Trickery (nothing shares its
    exact name) but wrong here, where most of a deck's cards have a
    higher mana value than a cheap spell's X. The real card's "look at X
    cards, pick any one of them, mana-value-gated" breadth isn't modeled
    — a genuinely different chooser shape (`dig_until` stops at the first
    match rather than surveying a fixed window) that would need its own
    primitive.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": "",
                "hit_destination": "cast_free_window",
                "rest_destination": "exile",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"from_hand": True},
            },
            raw_text="Immer wenn du einen Zauberspruch aus deiner Hand wirkst, decke "
                     "die oberste Karte deiner Bibliothek auf. Falls ihr Manawert "
                     "höchstens dem Manawert jenes Zauberspruchs entspricht, kannst du "
                     "sie wirken, ohne ihre Manakosten zu bezahlen.",
        ),
    ]


register("Sunbird's Invocation", _sunbirds_invocation)


def _etali_primal_storm() -> list[AbilitySpec]:
    """Whenever Etali attacks, exile the top card of each player's
    library, then you may cast any number of spells from among those
    cards without paying their mana costs.

    — Imodane deck batch. The new `exile_top_from_each_player_cast_free`
    — see its docstring.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_from_each_player_cast_free", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Wenn Etali angreift, exiliere die oberste Karte der Bibliothek "
                     "jedes Spielers. Danach kannst du eine beliebige Anzahl "
                     "Zaubersprüche von diesen Karten wirken, ohne ihre Manakosten zu "
                     "bezahlen.",
        ),
    ]


register("Etali, Primal Storm", _etali_primal_storm)


def _dual_strike() -> list[AbilitySpec]:
    """When you next cast an instant or sorcery spell with mana value 4
    or less this turn, copy that spell. You may choose new targets for
    the copy.
    Foretell {R}

    — Imodane deck batch. Foretell (RULE 702.166) is a RULE 702 keyword,
    auto-bound. "When you next cast … this turn" is a genuinely new
    primitive, `arm_spell_watcher`/`GameState.spell_watchers` — a one-shot
    watch for the *next* qualifying `SPELL_CAST` this turn, distinct from
    both an ordinary per-firing triggered ability (which only ever fires
    off a matching *object's own* event) and RULE 603.7's fixed-future-
    *step* `CreateDelayedTriggerEffect`. Its `then_specs` tail is the
    already-shipped `copy_spell` (RULE 707.10), applied against the
    just-cast spell's own stack item directly. **Documented
    simplification**: "you may choose new targets for the copy" isn't
    modeled — `CopySpellEffect` already keeps this simplification for
    every other consumer (Reiterate/Dualcaster Mage-shaped), so the copy
    keeps the original's targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("arm_spell_watcher", {
                "max_mana_value": 4, "card_types": ["instant", "sorcery"],
                "then_specs": [{"type": "copy_spell", "params": {}}],
            })],
            raw_text="Wenn du das nächste Mal in diesem Zug einen Spontanzauber- oder "
                     "Hexereispruch mit Manawert 4 oder weniger wirkst, kopiere jenen "
                     "Zauberspruch. Du kannst neue Ziele für die Kopie wählen.",
        ),
    ]


register("Dual Strike", _dual_strike)


def _city_on_fire() -> list[AbilitySpec]:
    """Convoke
    If a source you control would deal damage to a permanent or player,
    it deals triple that damage instead.

    — Imodane deck batch. Convoke is a RULE 702 keyword, auto-bound; the
    replacement clause is word-for-word `Fiery Emancipation`'s own
    ``double_damage`` (``multiplier=3``, ``your_sources_only=True``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})],
            raw_text="Falls eine Quelle, die du kontrollierst, einer bleibenden Karte "
                     "oder einem Spieler Schaden zufügen würde, fügt sie stattdessen "
                     "dreifach so viel Schaden zu.",
        ),
    ]


register("City on Fire", _city_on_fire)


def _mana_geyser() -> list[AbilitySpec]:
    """Add {R} for each tapped land your opponents control.

    — Imodane deck batch. `AddManaEffect`'s existing `amount_selector`,
    with the new unscoped-to-opponents `tapped_lands_opponents_control`
    count selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "R", "amount_selector": "tapped_lands_opponents_control"})],
            raw_text="Erzeuge {R} für jedes getappte Land, das deine Gegner "
                     "kontrollieren.",
        ),
    ]


register("Mana Geyser", _mana_geyser)


def _ruby_medallion() -> list[AbilitySpec]:
    """Red spells you cast cost {1} less to cast.

    — Imodane deck batch. `cost_reduction`'s new `spell_color` filter —
    the Medallion cycle, deliberately left unclaimed by the parser (see
    `parser/oracle/catalogue/static_handlers.py`'s own comment) since
    `continuous._spell_type_matches` only ever read card type, not
    colour, before this batch.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_color": "R"})],
            raw_text="Rote Zaubersprüche, die du wirkst, kosten {1} weniger.",
        ),
    ]


register("Ruby Medallion", _ruby_medallion)


def _runaway_steam_kin() -> list[AbilitySpec]:
    """Whenever you cast a red spell, if this creature has fewer than
    three +1/+1 counters on it, put a +1/+1 counter on this creature.
    Remove three +1/+1 counters from this creature: Add {R}{R}{R}.

    — Imodane deck batch. The trigger's intervening-if is the new
    ``source_counters_below`` (`effect_binder._trigger_condition`) — the
    counter-count sibling of the shipped ``source_state`` (Mana Vault's
    own "if this artifact is tapped"). The mana ability is a plain
    "remove N counters: add mana" activation cost, recognized directly
    from its printed text by `game/costs.py`'s existing
    `_REMOVE_COUNTERS_RE`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_color": "R",
                "source_counters_below": {"kind": "+1/+1", "count": 3},
            },
            raw_text="Immer wenn du einen roten Zauberspruch wirkst, legst du, falls "
                     "diese Kreatur weniger als drei +1/+1-Marken hat, eine "
                     "+1/+1-Marke auf diese Kreatur.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"colors": ["R", "R", "R"]})],
            cost={"text": "Remove three +1/+1 counters from this creature"},
            raw_text="Entferne drei +1/+1-Marken von dieser Kreatur: Erzeuge {R}{R}{R}.",
        ),
    ]


register("Runaway Steam-Kin", _runaway_steam_kin)


def _storm_kiln_artist() -> list[AbilitySpec]:
    """This creature gets +1/+0 for each artifact you control.
    Magecraft — Whenever you cast or copy an instant or sorcery spell,
    create a Treasure token.

    — Imodane deck batch. Magecraft already parses on its own —
    reproduced verbatim. The P/T clause is `anthem`'s existing
    ``power_count``, self-scoped, with the existing
    `artifacts_you_control` selector.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "self", "power": 1, "power_count": "artifacts_you_control"})],
            raw_text="Diese Kreatur erhält +1/+0 für jedes Artefakt, das du "
                     "kontrollierst.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Zauberkunst — Immer wenn du einen Spontanzauber- oder "
                     "Hexereispruch wirkst oder kopierst, erzeuge einen "
                     "Schatz-Spielstein.",
        ),
    ]


register("Storm-Kiln Artist", _storm_kiln_artist)


def _koth_fire_of_resistance() -> list[AbilitySpec]:
    """+2: Search your library for a basic Mountain card, reveal it, put
    it into your hand, then shuffle.
    −3: Koth deals damage to target creature equal to the number of
    Mountains you control.
    −7: You get an emblem with "Whenever a Mountain you control enters,
    this emblem deals 4 damage to any target."

    — Imodane deck batch. "+2:" is the generalized search grammar
    (`search`, ``{"basic": True, "type": "Mountain"}``). "−3:" is
    `DealDamageEffect`'s `amount_from_count_selector` (the existing
    `lands_you_control_of_type_mountain`-shaped count already used
    elsewhere for a threshold filter, here as a magnitude instead).
    "−7:" is the quoted-emblem-at-loyalty shape `Tyvar Kell`/`Vraska,
    Golgari Queen` already established — the emblem's own trigger is a
    genuine `ENTERS_BATTLEFIELD` group condition scoped by subtype, no
    different from a permanent's own.
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        trigger={
            "event": EventType.ENTERS_BATTLEFIELD,
            "condition": {"subject": "group", "subtypes": ["mountain"], "controller": "you"},
        },
        raw_text="Immer wenn ein Gebirge unter deiner Kontrolle ins Spiel kommt, fügt "
                 "dieser Emblem-Spielstein einem beliebigen Ziel 4 Schaden zu.",
    )
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"basic": True, "type": "Mountain"}, "destination": "hand",
            })],
            cost={"loyalty": 2},
            raw_text="+2: Durchsuche deine Bibliothek nach einer Standard-Gebirgskarte, "
                     "zeige sie, nimm sie auf deine Hand und mische danach deine "
                     "Bibliothek.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {
                "target_kind": "creature", "amount_from_count_selector": "lands_you_control_of_type_mountain",
            })],
            cost={"loyalty": -3},
            raw_text="−3: Koth fügt einer Zielkreatur Schaden in Höhe der Anzahl der "
                     "Gebirge zu, die du kontrollierst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -7},
            raw_text='−7: Du erhältst einen Emblem-Spielstein mit "Immer wenn ein '
                     'Gebirge unter deiner Kontrolle ins Spiel kommt, fügt dieser '
                     'Emblem-Spielstein einem beliebigen Ziel 4 Schaden zu."',
        ),
    ]


register("Koth, Fire of Resistance", _koth_fire_of_resistance)


def _stuffy_doll() -> list[AbilitySpec]:
    """Indestructible
    As this creature enters, choose a player.
    Whenever this creature is dealt damage, it deals that much damage to
    the chosen player.
    {T}: This creature deals 1 damage to itself.

    — Imodane deck batch. Indestructible is a RULE 702 keyword, auto-
    bound. The player choice is the new `request_choose_player`
    (`GameObject.chosen_player_id`); the damage-redirect trigger is the
    new `self_as_recipient` trigger subject (the "is dealt damage"
    mirror image of the ordinary source-keyed "self") paired with the
    new `deal_damage_to_chosen_player`, reading the firing event's own
    amount. The activated ability is a plain self-damage.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("request_choose_player", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, wähle einen Spieler.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("deal_damage_to_chosen_player", {})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self_as_recipient"}},
            raw_text="Immer wenn dieser Kreatur Schaden zugefügt wird, fügt sie dem "
                     "gewählten Spieler ebenso viel Schaden zu.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "self"})],
            cost={"text": "{T}"},
            raw_text="{T}: Diese Kreatur fügt sich selbst 1 Schaden zu.",
        ),
    ]


register("Stuffy Doll", _stuffy_doll)


def _grafted_exoskeleton() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has infect.
    Whenever this Equipment becomes unattached from a permanent,
    sacrifice that permanent.
    Equip {2}

    — Imodane deck batch. The anthem+infect grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: "whenever ~ becomes unattached" isn't modeled —
    this engine has no `attached_to` change event at all yet (every
    detach site — RULE 704.5m/n's illegal-attachment cleanup, a manual
    re-equip — mutates `GameObject.attached_to` directly with no
    broadcast), a genuinely open engine-primitive gap beyond this one
    card, so building it here is disproportionate.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["infect"]}),
            ],
            raw_text="Ausgerüstete Kreatur erhält +2/+2 und hat Infektion.",
        ),
    ]


register("Grafted Exoskeleton", _grafted_exoskeleton)


def _sword_of_once_and_future() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from blue and
    from black.
    Whenever equipped creature deals combat damage to a player, surveil
    2. Then you may cast an instant or sorcery spell with mana value 2 or
    less from your graveyard without paying its mana cost. If that spell
    would be put into your graveyard, exile it instead.
    Equip {2}

    — Imodane deck batch. The anthem+protection grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: only "surveil 2" is modeled — the trailing "cast an
    instant or sorcery spell with mana value 2 or less from your
    graveyard without paying its mana cost" needs a chooser over
    graveyard cards matching a filter, cast *for free*; the shipped
    graveyard-cast machinery covers either half alone (`dig_until`'s
    ``cast_free_window`` operates on the *library*, not the graveyard;
    `GraveyardCastPermissionEffect`'s graveyard permission is always at
    normal mana cost, never free) but not their combination, so building
    that chooser is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent", "protections": ["blue", "black"],
                }),
            ],
            raw_text="Ausgerüstete Kreatur erhält +2/+2 und Schutz vor Blau und vor "
                     "Schwarz.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 2})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Wenn die ausgerüstete Kreatur einem Spieler Kampfschaden zufügt, "
                     "surveile 2. Danach kannst du einen Spontanzauber- oder "
                     "Hexereispruch mit Manawert 2 oder weniger aus deinem Friedhof "
                     "wirken, ohne seine Manakosten zu bezahlen.",
        ),
    ]


register("Sword of Once and Future", _sword_of_once_and_future)


def _invasion_of_kaldheim() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, exile all cards from your hand, then draw
    that many cards. Until the end of your next turn, you may play cards
    exiled this way.

    — Imodane deck batch. The RULE 310 battle mechanics (protector
    choice, attackability, defeat/transform cycle) are all engine-level
    and need no hand-authoring. The ETB is the new
    `exile_hand_then_draw_that_many` — see its docstring for the
    documented simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_hand_then_draw_that_many", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Belagerung ins Spiel kommt, exiliere alle Karten "
                     "aus deiner Hand und ziehe danach ebenso viele Karten.",
        ),
    ]


register("Invasion of Kaldheim", _invasion_of_kaldheim)
register("Invasion of Kaldheim // Pyre of the World Tree", _invasion_of_kaldheim)


def _invasion_of_regatha() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, it deals 4 damage to another target battle
    or opponent and 1 damage to up to one target creature.

    — Imodane deck batch. Two independent targeting effects on one
    trigger, gathered one at a time (`_continue_trigger_multi_target`,
    RULE 603.1) rather than `GameEffect.extra_target_specs` — `damage`
    itself only ever reads a single flat targets list, so the second
    requirement needs its own effect, not a bolt-on second target on the
    first. The new `battle_or_opponent` target kind covers the first.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "battle_or_opponent"}),
                EffectSpec("damage", {"amount": 1, "target_kind": "creature", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Belagerung ins Spiel kommt, fügt sie einer anderen "
                     "Zielschlacht oder einem Ziel-Gegner 4 Schaden zu und einer bis "
                     "zu einen Zielkreatur 1 Schaden.",
        ),
    ]


register("Invasion of Regatha", _invasion_of_regatha)
register("Invasion of Regatha // Disciples of the Inferno", _invasion_of_regatha)


def _magda_the_hoardmaster() -> list[AbilitySpec]:
    """Whenever you commit a crime, create a tapped Treasure token. This
    ability triggers only once each turn. (Targeting opponents, anything
    they control, and/or cards in their graveyards is a crime.)
    Sacrifice three Treasures: Create a 4/4 red Scorpion Dragon creature
    token with flying and haste. Activate only as a sorcery.

    — Imodane deck batch. The sacrifice ability already parses on its
    own — reproduced verbatim. **Documented simplification**: "whenever
    you commit a crime" (RULE 701.53 — targeting an opponent, anything
    they control, or a card in their graveyard) isn't modeled — no
    single event unifies "any targeting effect resolving against
    anything opponent-owned" across every effect family in this engine
    (damage, destroy, exile, counter-removal, graveyard recursion, …), so
    the trigger never fires; the treasure-cost payoff still works once
    Treasures exist from any other source.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["R"],
                "subtypes": ["Scorpion", "Dragon"], "keywords": ["flying", "haste"],
                "token_name": "Scorpion Dragon",
            }), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Sacrifice three Treasures"},
            raw_text="Opfere drei Schätze: Erzeuge einen 4/4 roten Skorpiondrache-"
                     "Kreaturenspielstein mit Fliegen und Eile. Aktiviere nur wie "
                     "einen Hauptzauberspruch.",
        ),
    ]


register("Magda, the Hoardmaster", _magda_the_hoardmaster)


def _birgi_god_of_storytelling() -> list[AbilitySpec]:
    """Whenever you cast a spell, add {R}. Until end of turn, you don't
    lose this mana as steps and phases end.
    Creatures you control can boast twice during each of your turns
    rather than once.

    — Imodane deck batch. **Documented simplification**: modeled as a
    plain "whenever you cast a spell, add {R}" (the mana empties at the
    end of the current step/phase as usual, RULE 500.4 — no primitive
    marks specific floating mana as persisting past that) — no mana
    *ritual* value is lost for a spell cast with priority still to
    follow, only the "bank it for later this turn" upside. "Boast twice"
    isn't modeled at all: RULE 702.161's Boast keyword itself has no
    engine primitive yet (no Boast-printing card is in either deck), so
    there's nothing to double.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["R"]})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
            raw_text="Immer wenn du einen Zauberspruch wirkst, erzeuge {R}.",
        ),
    ]


register("Birgi, God of Storytelling", _birgi_god_of_storytelling)
register("Birgi, God of Storytelling // Harnfel, Horn of Bounty", _birgi_god_of_storytelling)


def _display_of_power() -> list[AbilitySpec]:
    """This spell can't be copied.
    Copy any number of target instant and/or sorcery spells. You may
    choose new targets for the copies.

    — Imodane deck batch. "Any number of target spells" is the RULE
    601.2c "any number" idiom Fire Covenant's own ``count=10`` UI cap
    already established, applied to `CopySpellEffect`'s ``target_count``
    (new — every prior copy-spell card only ever named one target).
    **Documented simplification**: "This spell can't be copied" (RULE
    707.12) isn't modeled — no spell-copy-immunity primitive exists yet,
    and nothing in either deck tries to copy a spell that's still on the
    stack as a copy target — so it's harmless in practice; "you may
    choose new targets for the copies" is the same already-documented
    MVP `CopySpellEffect` simplification every other copy-spell card in
    this catalogue shares (keeps the original's targets).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {
                "card_types": ["instant", "sorcery"], "target_count": 10, "optional": True,
            })],
            raw_text="Dieser Zauberspruch kann nicht kopiert werden. Kopiere eine "
                     "beliebige Anzahl Ziel-Hexerei- und/oder Spontanzauber. Du "
                     "kannst für die Kopien neue Ziele wählen.",
        ),
    ]


register("Display of Power", _display_of_power)


def _gamble() -> list[AbilitySpec]:
    """Search your library for a card, put that card into your hand,
    discard a card at random, then shuffle.

    — Imodane deck batch. **Documented simplification**: "at random"
    becomes an ordinary discard choice — the same simplification
    Indoraptor, the Perfect Hybrid's own "choose an opponent at random"
    already established in this catalogue (a real choice instead of
    randomness has no rules-relevant difference an MVP needs to model).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": "", "destination": "hand"}),
                EffectSpec("discard", {"count": 1}),
            ],
            raw_text="Durchsuche deine Bibliothek nach einer Karte, nimm diese "
                     "Karte auf deine Hand, wirf danach zufällig eine Karte ab "
                     "und mische danach deine Bibliothek.",
        ),
    ]


register("Gamble", _gamble)


def _jayas_immolating_inferno() -> list[AbilitySpec]:
    """(You may cast a legendary sorcery only if you control a legendary
    creature or planeswalker.)
    Jaya's Immolating Inferno deals X damage to each of up to three
    targets.

    — Imodane deck batch. "To each of up to three targets" is
    `DealDamageEffect`'s existing ``count``/``optional`` "up to N
    targets" shape (Volcanic Salvo-shaped), unchanged; X is the spell's
    own announced {X}, substituted the same way every other X-damage
    spell in this catalogue already reads it. **Documented
    simplification**: the Legendary Sorcery casting restriction (control
    a legendary creature or planeswalker) isn't enforced — no card-type-
    supertype casting gate exists in `can_cast` yet — so the spell casts
    like an ordinary sorcery; the damage itself is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any", "count": 3, "optional": True})],
            raw_text="Jaya's Immolating Inferno fügt bis zu drei Zielen je X "
                     "Schadenspunkte zu.",
        ),
    ]


register("Jaya's Immolating Inferno", _jayas_immolating_inferno)


def _jeskas_will() -> list[AbilitySpec]:
    """Choose one. If you control a commander as you cast this spell, you
    may choose both instead.
    • Add {R} for each card in target opponent's hand.
    • Exile the top three cards of your library. You may play them this
    turn.

    — Imodane deck batch. Mode 1 needed a genuinely new `AddManaEffect`
    shape (``target_kind``/``amount_from_target_hand_size`` — every prior
    use of that effect was untargeted); mode 2 is `ImpulsiveDrawEffect`
    unchanged (``count=3, same_turn_only=True`` — Ragavan, Nimble
    Pilferer's own shorter "this turn" window rather than Light Up the
    Stage's "until your next turn"). **Documented simplification**:
    ``or_both`` is offered unconditionally rather than gated on "if you
    control a commander" — this app's decks are Commander decks by
    construction, so the gate is true in every real game this engine
    plays; a genuinely commander-less game would let this spell over-
    offer the combined mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "or_both": True,
                "options": [
                    [EffectSpec("add_mana", {
                        "color": "R", "target_kind": "opponent", "amount_from_target_hand_size": True,
                    })],
                    [EffectSpec("impulsive_draw", {"count": 3, "same_turn_only": True})],
                ],
                "descriptions": [
                    "Füge {R} für jede Karte auf der Hand eines Zielgegners hinzu.",
                    "Exiliere die obersten drei Karten deiner Bibliothek. Du "
                    "kannst sie in diesem Zug ausspielen.",
                ],
            },
            raw_text="Wähle eins. Falls du beim Wirken dieses Zauberspruchs "
                     "einen Commander kontrollierst, kannst du stattdessen "
                     "beide wählen.",
        ),
    ]


register("Jeska's Will", _jeskas_will)


def _play_with_fire() -> list[AbilitySpec]:
    """Play with Fire deals 2 damage to any target. If a player is dealt
    damage this way, scry 1.

    — Imodane deck batch. The scry rider is `ConditionalEffect`'s new
    ``target_is_player`` condition key (this batch, shares its shared-
    targets-list idiom with the existing ``target_is_controller``), same
    shape as Trystan's ``graveyard_has_type``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 2, "target_kind": "any"}),
                EffectSpec("scry", {"amount": 1}, condition={"target_is_player": True}),
            ],
            raw_text="Play with Fire fügt einem beliebigen Ziel 2 Schadenspunkte "
                     "zu. Falls einem Spieler auf diese Weise Schaden zugefügt "
                     "wurde, schaue dir die oberste Karte deiner Bibliothek an "
                     "(Scry 1).",
        ),
    ]


register("Play with Fire", _play_with_fire)


def _vandalblast() -> list[AbilitySpec]:
    """Destroy target artifact you don't control.
    Overload {4}{R} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Imodane deck batch. The base mode needed a new `artifact_you_dont_
    control` target kind, the artifact-typed mirror of the existing
    `creature_you_dont_control`. **Documented simplification**: Overload
    (RULE 702.96) isn't modeled, matching the standing precedent Winds of
    Abandon/Damn/Cyclonic Rift already set in this catalogue — no
    alternative-cost mechanism stamps "was this spell cast via its
    overload cost" anywhere yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "artifact_you_dont_control"})],
            raw_text="Zerstöre ein Ziel-Artefakt, das du nicht kontrollierst.",
        ),
    ]


register("Vandalblast", _vandalblast)


def _witchs_mark() -> list[AbilitySpec]:
    """You may discard a card. If you do, draw two cards.
    Create a Wicked Role token attached to up to one target creature you
    control. (If you control another Role on it, put that one into the
    graveyard. Enchanted creature gets +1/+1. When this token is put
    into a graveyard, each opponent loses 1 life.)

    — Imodane deck batch. The loot half is `pay_cost_then` (RULE 118.3),
    the same "discard a card. If you do, …" shape Formidable Speaker's
    ETB already uses. **Documented simplification**: the Role token
    (RULE 701.62, an Aura-shaped token type this engine has no synthesis
    support for — `synthesize_token_card` only builds Creature/Artifact
    tokens, not Enchantment-Aura ones) isn't modeled; the card's real
    functional value (the loot) is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "draw", "params": {"count": 2}}],
            })],
            raw_text="Du kannst eine Karte abwerfen. Falls du dies tust, ziehe "
                     "zwei Karten.",
        ),
    ]


register("Witch's Mark", _witchs_mark)


def _wheel_of_misfortune() -> list[AbilitySpec]:
    """Each player secretly chooses a number 0 or greater, then all
    players reveal those numbers simultaneously and determine the
    highest and lowest numbers revealed this way. Wheel of Misfortune
    deals damage equal to the highest number to each player who chose
    that number. Each player who didn't choose the lowest number
    discards their hand, then draws seven cards.

    — Imodane deck batch. **Documented simplification** (the whole card):
    no "secretly choose a number, then reveal simultaneously" primitive
    exists (a genuinely new interactive-choice subsystem, out of scope
    for the value of one card), so the highest/lowest voting sub-game and
    its damage aren't modeled at all. What's modeled instead is the
    card's Wheel-of-Fortune-shaped headline effect: every player
    discards their hand and draws seven — `DiscardEffect(count=99,
    scope="each_player")` is the same "count large enough to force the
    whole hand" idiom Fire Covenant's own ``count=10`` "any number" UI
    cap uses elsewhere, since `discard_choice` already forces without a
    prompt once ``count`` reaches hand size.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 99, "scope": "each_player"}),
                EffectSpec("draw", {"count": 7, "selector": "each_player"}),
            ],
            raw_text="Jeder Spieler wählt heimlich eine Zahl 0 oder größer, "
                     "danach decken alle Spieler diese Zahlen gleichzeitig auf "
                     "und bestimmen die höchste und die niedrigste auf diese "
                     "Weise aufgedeckte Zahl. Wheel of Misfortune fügt jedem "
                     "Spieler, der diese Zahl gewählt hat, Schaden in Höhe der "
                     "höchsten Zahl zu. Jeder Spieler, der nicht die niedrigste "
                     "Zahl gewählt hat, wirft seine Hand ab und zieht danach "
                     "sieben Karten.",
        ),
    ]


register("Wheel of Misfortune", _wheel_of_misfortune)


def _volcanic_spite() -> list[AbilitySpec]:
    """Volcanic Spite deals 3 damage to target creature, planeswalker, or
    battle. You may put a card from your hand on the bottom of your
    library. If you do, draw a card.

    — Imodane deck batch. The target kind is the new `creature_
    planeswalker_or_battle`. The loot rider is the new `put_hand_card_on_
    bottom_then_draw` primitive (`RulesEngine.put_hand_card_on_bottom_
    then_draw`) — see its docstring for why the "may" is auto-taken
    rather than opening a real chooser.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature_planeswalker_or_battle"}),
                EffectSpec("put_hand_card_on_bottom_then_draw", {}),
            ],
            raw_text="Volcanic Spite fügt einer Zielkreatur, einem Ziel-"
                     "Planeswalker oder einer Zielschlacht 3 Schadenspunkte "
                     "zu. Du kannst eine Karte von deiner Hand unten in deine "
                     "Bibliothek legen. Falls du dies tust, ziehe eine Karte.",
        ),
    ]


register("Volcanic Spite", _volcanic_spite)


def _imodane_the_pyrohammer() -> list[AbilitySpec]:
    """Whenever an instant or sorcery spell you control that targets only
    a single creature deals damage to that creature, Imodane deals that
    much damage to each opponent.

    — Imodane deck batch, the commander's own signature ability and this
    batch's biggest new-primitive investment: `DealDamageEffect.amount_
    from_trigger_event` (new — every other damage-doubling/mirroring
    card in this catalogue reads a count selector or a flat override, not
    a *firing event's own* damage amount) reads the DAMAGE event's
    ``amount`` field the trigger fired with. Two new event flags make the
    trigger condition possible at all: `RulesEngine.deal_damage`/
    `DealDamageEffect.apply` now stamp ``source_is_instant_or_sorcery``
    (the source's own printed card type) and ``source_targets_only_
    single_creature`` (computed from the *resolving effect's own*
    ``target_spec`` — count 1, not optional, not a mass selector — and
    the target's own `is_creature`) onto every DAMAGE event; two matching
    `effect_binder._trigger_condition` predicate keys
    (``requires_source_instant_or_sorcery``/``requires_single_creature_
    target``) check them. "You control" is the ordinary ``"subject":
    "group", "controller": "you"`` group-subject check (DAMAGE's group-
    controller key is already ``source_controller_id``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_opponent",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "requires_source_instant_or_sorcery": True,
                "requires_single_creature_target": True,
            },
            raw_text="Immer wenn ein Spontanzauber oder eine Hexerei unter "
                     "deiner Kontrolle, der/die nur eine einzelne Kreatur zum "
                     "Ziel hat, dieser Kreatur Schaden zufügt, fügt Imodane "
                     "jedem Gegner ebenso viel Schaden zu.",
        ),
    ]


register("Imodane, the Pyrohammer", _imodane_the_pyrohammer)


# --- cEDH lists batch: RULE 118.9 "pitch" alternative-cost family -----------
#
# Force of Will/Negation/Vigor and Daze all print "You may <cost> rather
# than pay this spell's mana cost." — RULE 118.9, an alternative *casting*
# cost the engine doesn't model yet (see `_flare_of_duplication`'s own
# precedent for this same drop). Each card below is hand-authored for its
# *resolution effect only*, fully castable at its real printed mana cost
# (all four have one) — a strict subset of the real card, not a fake one.
# **Documented simplification, all four**: the free/discounted alternative
# cost is dropped; tracked as a real open primitive (RULE 118.9) in
# BACKLOG.md rather than silently rebuilt per card.


def _force_of_will() -> list[AbilitySpec]:
    """You may pay 1 life and exile a blue card from your hand rather than
    pay this spell's mana cost.
    Counter target spell.

    RULE 118.9's own alternative cost (MEC-15, previously dropped — see
    `Done_Backend.md`'s original cEDH batch entry for why it was deferred)
    now ships as a second `spell_effect` spec carrying only `alt_cost` and
    no effects of its own — `effect_binder.attach_to_object` scans every
    spec for it regardless of which one carries the "real" effects, the
    same idiom `additional_cost`/`free_cast_condition` already use. No
    condition: this alt cost is always available, unlike Force of
    Negation/Vigor's "if it's not your turn" gate below. Still also fully
    castable at its printed {3}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {})],
            raw_text="Konteret Ziel-Zauberspruch.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"pay_life": 1, "exile_hand_card_color": "U"},
            raw_text="Du kannst 1 Leben bezahlen und eine blaue Karte aus "
                     "deiner Hand ins Exil schicken, anstatt die Manakosten "
                     "dieses Zauberspruchs zu bezahlen.",
        ),
    ]


register("Force of Will", _force_of_will)


def _force_of_negation() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a blue card from your hand
    rather than pay this spell's mana cost.
    Counter target noncreature spell. If that spell is countered this way,
    exile it instead of putting it into its owner's graveyard.

    RULE 118.9's alternative cost now ships (MEC-15), gated by the
    `alt_cost` dict's own ``condition`` key (`ALLOWED_FREE_CAST_CONDITION_
    KEYS`'s ``not_your_turn`` — shared with `free_cast_condition`'s own
    vocabulary/evaluator, see `condition_query.free_cast_condition_holds`).

    **Documented simplification**: the "exile instead of graveyard" rider
    is still dropped (a real but narrow gap — the counter succeeds either
    way, only the destination zone differs). Still also fully castable at
    its printed {1}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"noncreature": True})],
            raw_text="Konteret einen Ziel-Zauberspruch, der keine Kreatur ist.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "U", "condition": {"not_your_turn": True}},
            raw_text="Falls es nicht dein Zug ist, kannst du eine blaue "
                     "Karte aus deiner Hand ins Exil schicken, anstatt die "
                     "Manakosten dieses Zauberspruchs zu bezahlen.",
        ),
    ]


register("Force of Negation", _force_of_negation)


def _force_of_vigor() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a green card from your hand
    rather than pay this spell's mana cost.
    Destroy up to two target artifacts and/or enchantments.

    RULE 118.9's alternative cost now ships (MEC-15), same "if it's not
    your turn" gate as Force of Negation just above. Still also fully
    castable at its printed {2}{G}{G}; the "up to two" destroy is the
    already-shipped RULE 115.1a N>=2 idiom (`DestroyEffect(count=2,
    optional=True)`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment", "count": 2, "optional": True,
            })],
            raw_text="Zerstöre bis zu zwei Ziel-Artefakte und/oder "
                     "-Verzauberungen.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "G", "condition": {"not_your_turn": True}},
            raw_text="Falls es nicht dein Zug ist, kannst du eine grüne "
                     "Karte aus deiner Hand ins Exil schicken, anstatt die "
                     "Manakosten dieses Zauberspruchs zu bezahlen.",
        ),
    ]


register("Force of Vigor", _force_of_vigor)


def _daze() -> list[AbilitySpec]:
    """You may return an Island you control to its owner's hand rather than
    pay this spell's mana cost.
    Counter target spell unless its controller pays {1}.

    RULE 118.9's alternative cost now ships (MEC-15) as `alt_cost`'s
    ``return_to_hand`` key — the same subtype-word shape `game/costs.py`'s
    `ActivationCost.return_to_hand` already uses for an activated ability's
    "Return a Forest you control…" cost (Quirion Ranger-shaped), reused
    here for a spell's alternative *cast* cost instead. No condition:
    always available. Still also fully castable at its printed {1}{U};
    the "unless controller pays" half is the existing `CounterSpellEffect.
    unless_pays` primitive (Mana Leak's own shape).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"unless_pays": "1"})],
            raw_text="Konteret Ziel-Zauberspruch, falls dessen Kontrolleur "
                     "nicht {1} bezahlt.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"return_to_hand": "island"},
            raw_text="Du kannst eine Insel, die du kontrollierst, auf die "
                     "Hand ihres Besitzers zurückgeben, anstatt die "
                     "Manakosten dieses Zauberspruchs zu bezahlen.",
        ),
    ]


register("Daze", _daze)


# --- cEDH lists batch: tax-draw family ("unless that player pays") --------
#
# New primitive: `TaxedDrawEffect` (RULE 118.3's "unless" idiom applied to a
# draw, not a sacrifice) — the payer is the *triggering spell's own caster*,
# read off `GameContext.trigger_event`, not this ability's controller.


def _rhystic_study() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may draw a card unless that
    player pays {1}.

    — `TaxedDrawEffect`, see the batch header above.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{1}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Immer wenn ein Gegner einen Zauberspruch wirkt, "
                     "kannst du eine Karte ziehen, außer jener Spieler "
                     "bezahlt {1}.",
        )
    ]


register("Rhystic Study", _rhystic_study)


def _mystic_remora() -> list[AbilitySpec]:
    """Cumulative upkeep {1}.
    Whenever an opponent casts a noncreature spell, you may draw a card
    unless that player pays {4}.

    Cumulative upkeep (RULE 702.24, MEC-16) now ships as real behaviour —
    this entry only ever carried the `taxed_draw` trigger; the keyword
    itself binds independently (`game/effect_binder.py`'s keyword dispatch
    table reads `Card.keywords`/oracle text directly, regardless of
    whether the rest of the card is hand-authored), so Mystic Remora
    correctly has to be paid for again, closing the previous "dropped,
    never has to be paid for" simplification without touching this spec
    at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{4}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Immer wenn ein Gegner einen Zauberspruch wirkt, der "
                     "keine Kreatur ist, kannst du eine Karte ziehen, außer "
                     "jener Spieler bezahlt {4}.",
        )
    ]


register("Mystic Remora", _mystic_remora)


def _esper_sentinel() -> list[AbilitySpec]:
    """Whenever an opponent casts their first noncreature spell each turn,
    draw a card unless that player pays {X}, where X is this creature's
    power.

    **Documented simplification**: "their first ... each turn" isn't
    tracked (no per-player per-turn "first qualifying spell" counter exists
    yet) — this fires on *every* qualifying opponent spell instead of just
    the first, a strict upgrade rather than a broken card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"amount_from_source_power": True})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Immer wenn ein Gegner seinen ersten Zauberspruch, der "
                     "keine Kreatur ist, in einem Zug wirkt, ziehst du eine "
                     "Karte, außer jener Spieler bezahlt {X}, wobei X die "
                     "Stärke dieser Kreatur ist.",
        )
    ]


register("Esper Sentinel", _esper_sentinel)


def _smothering_tithe() -> list[AbilitySpec]:
    """Whenever an opponent draws a card, that player may pay {2}. If the
    player doesn't, you create a Treasure token.

    MEC-12 — the same tax-draw family as Rhystic Study/Mystic Remora/Esper
    Sentinel above, but the trigger event is `EventType.DRAW` (an
    ``"opponent draws"`` group condition needed its own
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` entry, ``DRAW``:
    ``"player_id"`` — `RulesEngine.draw` already fired that event with the
    right shape, only this table row was missing) and the "if you don't"
    branch is a Treasure, not a card — `effects.PayCostThenEffect`'s
    general RULE 118.3 "you may pay `<cost>`. If you don't, `<effect>`."
    shape (``payer="event_player"`` reads the *drawing* player off the
    triggering DRAW event, same as `TaxedDrawEffect`'s payer read for its
    own family; the create-token effect resolves under this permanent's
    own controller, matching "**you** create a Treasure token").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "pay_cost_then",
                {
                    "cost": "{2}",
                    "payer": "event_player",
                    "else_effects": [
                        {
                            "type": "create_token",
                            "params": {"token_name": "Treasure", "count": 1},
                        }
                    ],
                },
            )],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Immer wenn ein Gegner eine Karte zieht, kann jener "
                     "Spieler {2} bezahlen. Falls nicht, erschaffst du ein "
                     "Schatz-Spielsteinkarte.",
        )
    ]


register("Smothering Tithe", _smothering_tithe)


def _imperial_recruiter() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    power 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — the generalized tutor grammar (`SearchLibraryEffect`/
    `models.card_query`) doesn't parse a power/toughness qualifier after the
    search noun phrase (a documented gap on the parser side, same family as
    the already-unclaimed "with mana value X or less"); hand-authored
    directly onto the new `card_query.max_power` criteria key instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_power": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Imperial Recruiter ins Spiel kommt, kannst du in "
                     "deiner Bibliothek nach einer Kreaturenkarte mit Stärke "
                     "2 oder weniger suchen, sie offenlegen, auf deine Hand "
                     "nehmen und deine Bibliothek danach mischen.",
        )
    ]


register("Imperial Recruiter", _imperial_recruiter)


def _recruiter_of_the_guard() -> list[AbilitySpec]:
    """When ~ enters, you may search your library for a creature card with
    toughness 2 or less, reveal it, put it into your hand, then shuffle.

    MEC-12 fourth pass — same gap and same fix as Imperial Recruiter above,
    on `card_query.max_toughness` instead of `max_power`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "max_toughness": 2},
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Recruiter of the Guard ins Spiel kommt, kannst du "
                     "in deiner Bibliothek nach einer Kreaturenkarte mit "
                     "Widerstandskraft 2 oder weniger suchen, sie "
                     "offenlegen, auf deine Hand nehmen und deine "
                     "Bibliothek danach mischen.",
        )
    ]


register("Recruiter of the Guard", _recruiter_of_the_guard)


def _wheel_of_fortune() -> list[AbilitySpec]:
    """Each player discards their hand, then draws seven cards.

    MEC-12 fourth pass — `effects.WheelOfFortuneEffect`, the flat-draw-count
    sibling of the already-shipped `WheelEffect` (Timetwister)/
    `WindfallEffect` (Windfall); no oracle-text recognizer yet since this
    exact printed line is a one-card template, not a family.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("wheel_of_fortune", {"draw_count": 7})])]


register("Wheel of Fortune", _wheel_of_fortune)


def _ruination() -> list[AbilitySpec]:
    """Destroy all nonbasic lands.

    MEC-12 fourth pass — `effects.DestroyEffect`'s existing
    ``selector="all_lands"`` mass-wipe path, narrowed by the new
    ``filter={"nonbasic": True}`` key (mirrors ``max_mana_value``'s
    selector+filter split for every other qualified board wipe).
    """
    return [AbilitySpec("spell_effect", [EffectSpec("destroy", {
        "selector": "all_lands", "filter": {"nonbasic": True},
    })])]


register("Ruination", _ruination)


def _city_of_brass() -> list[AbilitySpec]:
    """Whenever this land becomes tapped, it deals 1 damage to you.
    {T}: Add one mana of any color.

    The mana ability itself is covered by the engine's plain mana model
    (`mana_abilities_for`, no spec needed) — only the "becomes tapped"
    drawback needs a spec, `EventType.TAPPED` (already fired for every
    genuine untapped→tapped transition, not just a mana tap).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"selector": "controller"})],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
            raw_text="Immer wenn dieses Land angetappt wird, fügt es dir 1 "
                     "Schadenspunkt zu.",
        )
    ]


register("City of Brass", _city_of_brass)


def _forbidden_orchard() -> list[AbilitySpec]:
    """{T}: Add one mana of any color.
    Whenever you tap this land for mana, target opponent creates a 1/1
    colorless Spirit creature token.

    **Documented simplification**: "target opponent" becomes every
    opponent (`CreateTokenEffect`'s ``each_opponent`` creator) — no single-
    opponent target choice for a land-tap trigger yet; correct in 1v1,
    an overstatement in multiplayer.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "creators": "each_opponent", "power": 1, "toughness": 1,
                "colors": [], "subtypes": ["Spirit"], "token_name": "Spirit",
            })],
            trigger={"event": EventType.TAPPED_FOR_MANA, "condition": {"subject": "self"}},
            raw_text="Immer wenn du dieses Land für Mana tappst, erstellt "
                     "ein Gegner deiner Wahl einen 1/1 farblosen Geist-"
                     "Kreaturspielstein.",
        )
    ]


register("Forbidden Orchard", _forbidden_orchard)


# --- cEDH lists batch: RULE 115.4 "change the target" -----------------------
#
# New primitive: `ChangeTargetEffect`/`RulesEngine.change_target` (RULE
# 115.4/601.2c) — a genuine retarget of an *existing* stack item, not the
# already-shipped "choose new targets for a freshly-made copy" (RULE
# 707.10c). Scoped to a spell with exactly one existing target (see
# `ChangeTargetEffect`'s own docstring); both real cards below only ever
# retarget a single-target spell.


def _misdirection() -> list[AbilitySpec]:
    """You may exile a blue card from your hand rather than pay this
    spell's mana cost.
    Change the target of target spell with a single target.

    **Documented simplification**: the free-cast alternative cost (RULE
    118.9, same drop precedent as the Force of Will cycle) is dropped.
    Fully castable at its printed {3}{U}{U}; the retarget itself is the
    new `change_target` primitive above, mandatory (no "may") per the
    printed text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"single_target": True})],
            raw_text="Ändere das Ziel eines Ziel-Zauberspruchs mit einem "
                     "einzelnen Ziel.",
        )
    ]


register("Misdirection", _misdirection)


def _deflecting_swat() -> list[AbilitySpec]:
    """If you control a commander, you may cast this spell without paying
    its mana cost.
    You may choose new targets for target spell or ability.

    **Documented simplifications**: the commander-tax-free alternative
    cast (RULE 601.2f's `free_cast_condition` — confirmed unreachable from
    a real game session regardless, see BACKLOG.md) is dropped, fully
    castable at its printed {2}{R}. "Spell or ability" is now the real
    printed scope (ENG-26, `spell_or_ability=True` — was **spell**-only
    before the RULE 115 targetable-ability-on-the-stack primitive shipped).
    ``optional=True`` is the printed "you may" (unlike Misdirection's
    mandatory "Change the target").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"optional": True, "spell_or_ability": True})],
            raw_text="Du kannst neue Ziele für einen Ziel-Zauberspruch "
                     "oder eine Ziel-Fähigkeit wählen.",
        )
    ]


register("Deflecting Swat", _deflecting_swat)


def _stifle() -> list[AbilitySpec]:
    """Counter target activated or triggered ability. (Mana abilities
    can't be targeted.)

    — Stifle. The direct payoff of ENG-26's RULE 115/701.5b primitive
    (`counter_ability`/`CounterAbilityEffect`, `targeting.py`'s
    ``"ability"`` kind): a one-clause card that exercises it end to end.
    The parenthetical is reminder text (RULE 115.9c already excludes a
    mana ability from every targetable-ability kind — it never uses the
    stack at all — so nothing extra needs enforcing here).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
            raw_text="Annulliere eine Ziel-Aktivierte oder Ziel-Ausgelöste "
                     "Fähigkeit.",
        )
    ]


register("Stifle", _stifle)


def _trickbind() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Counter target activated or triggered ability. If a permanent's
    ability is countered this way, activated abilities of that permanent
    can't be activated this turn. (Mana abilities can't be targeted.)

    — Trickbind. Shares Stifle's `counter_ability` core.

    **Documented simplifications**: RULE 702.61 Split Second (nothing in
    the codebase recognizes it yet — a cast-timing restriction, not a
    targeting/effect shape, so it's out of ENG-26's own scope) and the
    "activated abilities of that permanent can't be activated this turn"
    post-counter lockout (would need its own per-object, turn-scoped flag
    consulted by `GameEngine.can_activate` — a real but narrow primitive
    no other printed card needs yet) are both dropped; the core "counter
    target activated or triggered ability" line is real behaviour.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
            raw_text="Annulliere eine Ziel-Aktivierte oder Ziel-Ausgelöste "
                     "Fähigkeit.",
        )
    ]


register("Trickbind", _trickbind)


def _finale_of_devastation() -> list[AbilitySpec]:
    """Search your library and/or graveyard for a creature card with mana
    value X or less and put it onto the battlefield. If you search your
    library this way, shuffle. If X is 10 or more, creatures you control
    get +X/+X and gain haste until end of turn.

    — MEC-12 (fifth pass): the "search library and/or graveyard" half
    reuses `SearchLibraryEffect`'s ``zones``/``criteria`` exactly like the
    oracle-text `search_zone_put` handler does, just with the search's own
    ``max_mana_value`` bound left as the ``"x"`` sentinel
    `RulesEngine._substitute_x` now knows to walk into a nested
    ``criteria`` dict (a fifth-pass primitive, alongside Meltdown's
    matching `filter` case); the bonus half is `Martial Coup`'s own
    `source_x_paid_at_least` `ConditionalEffect` gate wrapping a
    `creatures_you_control`-selector `PumpEffect`. Not built as a general
    oracle-text handler (unlike the plain single-zone "with mana value X
    or less" qualifier, which is): this card's own two-sentence shape —
    a conditional bonus keyed to the *same* spell's {X} as its search —
    is a singleton template cache-wide, the sanctioned hand-authoring
    escape valve rather than a family worth its own grammar yet.

    Simplified: the search always shuffles the library when it's among
    the search zones (the same `search_zone_put` simplification the
    oracle-text handler already documents — it doesn't track which zone
    the found card actually came from), so this always shuffles rather
    than only "if you search your library this way".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": {"type": "Creature", "max_mana_value": "x"},
                    "destination": "battlefield",
                    "zones": ["library", "graveyard"],
                }),
                EffectSpec(
                    "pump",
                    {"power": "x", "toughness": "x", "keywords": ["haste"], "selector": "creatures_you_control"},
                    condition={"source_x_paid_at_least": 10},
                ),
            ],
            raw_text="Durchsuche deine Bibliothek und/oder deinen Friedhof nach einer "
                     "Kreaturenkarte mit Manawert X oder weniger und bringe sie ins "
                     "Spiel. Falls du auf diese Weise deine Bibliothek durchsucht hast, "
                     "mische sie. Falls X 10 oder größer ist, erhalten Kreaturen, die du "
                     "kontrollierst, +X/+X und Eile bis zum Ende des Zuges.",
        ),
    ]


register("Finale of Devastation", _finale_of_devastation)


def _ghostfire_slice() -> list[AbilitySpec]:
    """Devoid (This card has no color.)
    This spell costs {2} less to cast if an opponent controls a
    multicolored permanent.
    Ghostfire Slice deals 4 damage to any target.

    — MEC-12 (fifth pass): a genuine gap, not just a missing handler —
    `game/continuous.self_cost_reduction_for`/`EffectRegistry`'s
    ``"cost_reduction"`` factory both already support an `active_if` gate
    (this pass's own primitive, alongside `multicolored_permanents_you_
    control`'s new `count_selector`), but the oracle-text *parser* only
    ever reaches that static path for a **permanent** — `parser/oracle/
    segmenter.py`'s `allow_spell_effect` gate routes every clause on a
    true instant/sorcery through the one-shot `spell_effect` dispatch
    instead, which has no static-ability shape to emit at all. Hand-
    authored as two independent `AbilitySpec`s instead of widening that
    routing (a real but separate architectural gap — `attach_to_object`'s
    `spell_effect` branch would need to split a `StaticAbility` out of its
    bound effects into `obj.static_effects`, which no other card needs
    yet): ``"static"`` doesn't care what kind of card its owner is, so a
    hand-authored `AbilitySpec("static", …)` on an Instant reaches
    `self_cost_reduction_for` exactly like Embercleave's parsed one does
    on an Equipment.

    Simplified: Devoid (a purely cosmetic colour-identity keyword with no
    gameplay effect this engine's card model can't already represent via
    printed colourless mana cost) isn't separately modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "active_if": {
                    "kind": "opponent_count",
                    "selector": "multicolored_permanents_you_control",
                    "min": 1,
                },
            })],
            raw_text="Dieser Zauberspruch kostet {2} weniger, falls ein Gegner "
                     "ein mehrfarbiges Permanent kontrolliert.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"target_kind": "any", "amount": 4})],
            raw_text="~ fügt einem beliebigen Ziel 4 Schadenspunkte zu.",
        ),
    ]


register("Ghostfire Slice", _ghostfire_slice)


def _mox_diamond() -> list[AbilitySpec]:
    """If this artifact would enter, you may discard a land card instead.
    If you do, put this artifact onto the battlefield. If you don't, put
    it into its owner's graveyard.
    {T}: Add one mana of any color.

    — MEC-12 (sixth pass): RULE 614.12's own worked example, confirmed a
    singleton template cache-wide (a raw-text grep for "would enter, you
    may" turns up only this card). `AbilitySpec.enter_or_graveyard_discard_
    land` (`RulesEngine._offer_enter_or_graveyard`, offered *before* every
    other battlefield-entry step, since declining means this never becomes
    a permanent at all) is a new, genuinely general RULE 614.12 primitive
    even though only one card needs it today — a bare marker flag, not a
    parametrized cost, since a second card of this shape would almost
    certainly print the identical "discard a land card" cost anyway. The
    mana ability itself needs no hand-authoring: a plain "{T}: Add one
    mana of any color." is recognized generically by `mana_abilities_for`.
    """
    return [
        AbilitySpec(
            "static", [],
            enter_or_graveyard_discard_land=True,
            raw_text="Falls ~ ins Spiel kommen würde, kannst du stattdessen eine "
                     "Landkarte abwerfen. Wenn du dies tust, bringe ~ ins Spiel. "
                     "Wenn nicht, lege es in den Friedhof seines Besitzers.",
        ),
    ]


register("Mox Diamond", _mox_diamond)


def _eye_of_ugin() -> list[AbilitySpec]:
    """Colorless Eldrazi spells you cast cost {2} less to cast.
    {7}, {T}: Search your library for a colorless creature card, reveal
    it, put it into your hand, then shuffle.

    — MEC-12 (sixth pass). The search half is left to the oracle-text
    parser (`_SEARCH_COLOR_WORD`'s new "colorless" entry, matched onto
    `models.card_query`'s own colour-emptiness check) rather than
    duplicated here — only the static half is hand-authored, since a
    combined colour-emptiness-**and**-creature-subtype cost filter
    ("Colorless Eldrazi spells", as opposed to a bare colour or a bare
    main-card-type filter) is this pass's own new primitive
    (`continuous.cost_reduction_for`'s `spell_color="colorless"` +
    `spell_subtype="Eldrazi"`, composed by plain AND) with no other real
    card on this exact combined shape yet — not worth a general "<colour-
    or-colorless> <optional creature subtype> spells [you cast] cost {N}
    less" grammar until a second one does. Both abilities are hand-
    authored on the same registered card regardless, since a registered
    card's catalogue entry replaces the parser's own output wholesale
    rather than merging with it — the search line below is simply the
    identical shape the parser would already produce for this card on
    its own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 2,
                "spell_color": "colorless", "spell_subtype": "Eldrazi",
            })],
            raw_text="Farblose Eldrazi-Zaubersprüche, die du wirkst, kosten {2} weniger.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "colorless"},
                "destination": "hand",
            })],
            cost={"text": "{7}, {T}"},
            raw_text="{7}, {T}: Durchsuche deine Bibliothek nach einer farblosen "
                     "Kreaturenkarte, zeige sie offen vor, nimm sie auf deine Hand "
                     "und mische deine Bibliothek.",
        ),
    ]


register("Eye of Ugin", _eye_of_ugin)


def _tainted_pact() -> list[AbilitySpec]:
    """Exile the top card of your library. You may put that card into
    your hand unless it has the same name as another card exiled this
    way. Repeat this process until you put a card into your hand or you
    exile two cards with the same name, whichever comes first.

    — MEC-12 (sixth pass). `ExileUntilDuplicateNameEffect`/`RulesEngine.
    exile_until_duplicate_name` — a new, genuinely general RULE 701.19-
    adjacent loop shape (see its own docstring for why it's not an
    instance of `dig_until`), confirmed a singleton template cache-wide
    but built as a real primitive anyway since the loop has no card-
    specific data in it. A real interactive choice each time a fresh
    (non-duplicate) name comes up with cards still left in the library —
    take it, or keep digging (the real reason this card is played: paired
    with Thassa's Oracle in a singleton deck, deliberately declining every
    hit mills the whole library on purpose).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_until_duplicate_name", {})],
            raw_text="Exiliere die oberste Karte deiner Bibliothek. Du kannst diese "
                     "Karte auf deine Hand nehmen, außer sie hat denselben Namen wie "
                     "eine andere auf diese Weise exilierte Karte. Wiederhole diesen "
                     "Vorgang, bis du eine Karte auf deine Hand nimmst oder zwei "
                     "Karten mit demselben Namen exilierst, je nachdem, was zuerst "
                     "eintritt.",
        ),
    ]


register("Tainted Pact", _tainted_pact)


def _transmute_artifact() -> list[AbilitySpec]:
    """Sacrifice an artifact. If you do, search your library for an
    artifact card. If that card's mana value is less than or equal to the
    sacrificed artifact's mana value, put it onto the battlefield. If
    it's greater, you may pay {X}, where X is the difference. If you do,
    put it onto the battlefield. If you don't, put it into its owner's
    graveyard. Then shuffle.

    — MEC-12 (sixth pass). `TransmuteArtifactEffect`/`RulesEngine.
    transmute_artifact` — confirmed a singleton cost-comparison-gated
    placement cache-wide, self-contained (its own three `pending_choice`
    kinds: sacrifice, search, and an optional pay-the-difference) rather
    than composed from the general search/sacrifice/`pay_cost_then`
    primitives, none of which can express a cost computed from what a
    different, just-made choice turned out to be.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("transmute_artifact", {})],
            raw_text="Opfere ein Artefakt. Wenn du dies tust, durchsuche deine "
                     "Bibliothek nach einer Artefaktkarte. Falls der Manawert dieser "
                     "Karte kleiner oder gleich dem Manawert des geopferten Artefakts "
                     "ist, bringe sie ins Spiel. Falls er größer ist, kannst du {X} "
                     "bezahlen, wobei X die Differenz ist. Wenn du dies tust, bringe "
                     "sie ins Spiel. Wenn nicht, lege sie in den Friedhof ihres "
                     "Besitzers. Mische danach.",
        ),
    ]


register("Transmute Artifact", _transmute_artifact)


def _chain_of_vapor() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. Then that
    permanent's controller may sacrifice a land of their choice. If the
    player does, they may copy this spell and may choose a new target for
    that copy.

    — Vivi B4 batch. `return_to_hand` for the bounce; `PayCostThenEffect`'s
    general "you may pay `<cost>`. If you do, nothing further." (RULE
    118.3) models the land sacrifice itself with a new
    ``payer="previous_target_controller"`` (`GameContext.previous_targets`
    — it's the *bounced permanent's* controller being asked, almost always
    an opponent, not this spell's own caster). **Documented
    simplification**: "they may copy this spell and may choose a new
    target for that copy" is dropped rather than approximated —
    `CopySpellEffect.copy_self` ("copy this spell" while it's still
    resolving) can't reach back through a `pending_choice` pause (by the
    time the player answers "pay", the original has already finished
    resolving and left the stack for the graveyard, RULE 608.2m), and a
    same-target "copy" would fizzle for real play anyway: the only target
    this MVP can default to is the permanent the first sentence just
    bounced, which is no longer a legal "target nonland permanent" once
    it's sitting in hand — RAW's own "you may choose new targets" is
    exactly there to route around that, and this engine doesn't offer that
    choice yet. Sacrificing the land is still a real, correctly-costed
    decision on its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"}),
                EffectSpec("pay_cost_then", {
                    "cost": "sacrifice a land",
                    "payer": "previous_target_controller",
                    "effects": [],
                }),
            ],
            raw_text=(
                "return target nonland permanent to its owner's hand. then that "
                "permanent's controller may sacrifice a land of their choice. if "
                "the player does, they may copy this spell and may choose a new "
                "target for that copy."
            ),
        ),
    ]


register("Chain of Vapor", _chain_of_vapor)


def _intuition() -> list[AbilitySpec]:
    """Search your library for three cards and reveal them. Target
    opponent chooses one. Put that card into your hand and the rest into
    your graveyard. Then shuffle.

    — Vivi B4 batch. `IntuitionEffect`/`RulesEngine.request_intuition` —
    a genuinely two-player interactive search (the caster picks the three
    cards, then the *targeted opponent* picks which one is kept), self-
    contained rather than composed from `request_search` (whose single
    ``destination`` has no way to hand off to a second player's choice).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {"count": 3})],
            raw_text=(
                "search your library for 3 cards and reveal them. target opponent "
                "chooses 1. put that card into your hand and the rest into your "
                "graveyard. then shuffle."
            ),
        ),
    ]


register("Intuition", _intuition)


def _ral_monsoon_mage() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell during your turn, flip
    a coin. If you lose the flip, ~ deals 1 damage to you. If you win the
    flip, you may exile ~. If you do, return him to the battlefield
    transformed under his owner's control.

    — Vivi B4 batch. New `CoinFlipEffect`/`RulesEngine.coin_flip` (RULE
    705.1, previously built but unused by any card) branches into the loss
    (``damage`` with the existing ``selector="controller"``, Mana Vault's
    own "deals 1 damage to you" shape) and win (`exile_return_transformed`,
    RULE 400.7/712.8's existing transform-via-zone-change primitive)
    halves. "During your turn" reuses `phase_relation="you"` — built for
    RULE 500.7 "at the beginning of your `<step>`" triggers, but its
    predicate only checks whose turn it currently is, so it gates a
    SPELL_CAST trigger exactly as well. **Documented simplification**:
    "you may exile ~" is modeled as unconditional (always taken) — the
    same accepted simplification `CoinFlipEffect` itself already documents.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 1}}],
                "win_effects": [{"type": "exile_return_transformed", "params": {}}],
            })],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "phase_relation": "you",
            },
            raw_text=(
                "whenever you cast an instant or sorcery spell during your turn, "
                "flip a coin. if you lose the flip, ~ deals 1 damage to you. if "
                "you win the flip, you may exile ~. if you do, return him to the "
                "battlefield transformed under his owner's control."
            ),
        ),
    ]


register("Ral, Monsoon Mage", _ral_monsoon_mage)


def _talon_gates_of_madara() -> list[AbilitySpec]:
    """When this land enters, up to one target creature phases out.
    {T}: Add {C}.
    {1}, {T}: Add one mana of any color.
    {4}: Put this card from your hand onto the battlefield.

    — Vivi B4 batch. The two mana abilities are already oracle-parsed
    (RULE 605); only the ETB phase-out trigger (`PhaseOutEffect`) and the
    new `PutSelfOntoBattlefieldFromHandEffect`/`ActivationCost.hand_zone`
    ("play this land from hand for a generic cost, bypassing RULE 305's
    per-turn land drop — an activated ability, not a land play") needed
    hand-authoring.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("phase_out", {"target_kind": "creature", "optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="when ~ enters, up to 1 target creature phases out.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("put_self_onto_battlefield_from_hand", {})],
            cost="{4}",
            raw_text="{4}: put this card from your hand onto the battlefield.",
        ),
    ]


register("Talon Gates of Madara", _talon_gates_of_madara)


def _urzas_saga() -> list[AbilitySpec]:
    """I — This Saga gains "{T}: Add {C}."
    II — This Saga gains "{2}, {T}: Create a 0/0 colorless Construct
    artifact creature token with 'This token gets +1/+1 for each artifact
    you control.'"
    III — Search your library for an artifact card with mana value 0 or 1,
    put it onto the battlefield, then shuffle.

    — Vivi B4 batch. Chapters I/II are `GrantSelfActivatedAbilityEffect`
    (RULE 714.2c's *lasting* self-grant — new, since a Saga chapter's
    "gains an ability" outlives the trigger that grants it, unlike the
    turn-scoped `grant_graveyard_cast_permission_this_turn` shape it
    otherwise mirrors), each wrapping the ability it grants as nested
    ``EffectSpec`` dicts. Chapter II's Construct token gets its own
    self-scaling +1/+1-per-artifact ability via `CreateTokenEffect.
    grant_self_anthem` (new — appends a real ``anthem``-shaped
    `StaticAbility` onto the *created token itself* rather than the
    effect's source, reusing the oracle-parsed "creatures you control get
    +N/+N" static's own ``power_count``/``toughness_count`` per-count
    scaling). Chapter III is a plain `search`. **Documented
    simplification**: chapter I's granted mana ability resolves through
    the stack like any other granted activated ability (`grant_activated_
    ability`'s general form) rather than as a genuine no-stack RULE 605.1a
    mana ability — functionally equivalent (the mana still reaches the
    pool), just one extra `activate_ability` step instead of an instant
    tap-for-mana shortcut.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"taps_self": True},
                "effects": [{"type": "add_mana", "params": {"colors": ["C"]}}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
            raw_text='i — this saga gains "{t}: add {c}."',
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_self_activated_ability", {
                "cost": {"mana": "{2}", "taps_self": True},
                "effects": [{"type": "create_token", "params": {
                    "power": 0, "toughness": 0, "colors": [], "subtypes": ["Construct"],
                    "token_name": "Construct", "is_artifact": True,
                    "grant_self_anthem": {
                        "power": 1, "toughness": 1,
                        "power_count": "artifacts_you_control",
                        "toughness_count": "artifacts_you_control",
                    },
                }}],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
            raw_text=(
                'ii — this saga gains "{2}, {t}: create a 0/0 colorless construct '
                "artifact creature token with '~ gets +1/+1 for each artifact you "
                "control.'\""
            ),
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": 1},
                "destination": "battlefield",
                "optional": False,
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
            raw_text=(
                "iii — search your library for an artifact card with mana cost "
                "{0} or {1}, put it onto the battlefield, then shuffle."
            ),
        ),
    ]


register("Urza's Saga", _urzas_saga)


def _quicksilver_elemental() -> list[AbilitySpec]:
    """{U}: This creature gains all activated abilities of target creature
    until end of turn. (If any of the abilities use that creature's name,
    use this creature's name instead.)
    You may spend blue mana as though it were mana of any color to pay the
    activation costs of this creature's abilities.

    — MEC-23, the one card the Vivi B4 batch (2026-08-10) left open. Two new
    general primitives, both closing this ticket:

    - `effects.GainActivatedAbilitiesOfTargetEffect` (``"gain_target_
      activated_abilities"``) is the resolve-time, single-target sibling of
      MEC-21's standing layer-6 `grant_borrowed_activated_ability`
      (Agatha's Soul Cauldron): it snapshots ``target.activated_abilities``
      once, at resolution, redirecting each via the same `continuous.
      _retarget_effect_source` (RULE 113.7c), onto a turn-scoped
      `GameObject.temp_granted_activated_abilities` field rather than
      re-deriving live off a standing static every recompute — a later
      change to the target's own ability set doesn't retroactively change
      what was copied, matching the card's own ruling.
    - `continuous.any_color_for_activation` (MEC-21's wildcard-activation
      permission) gained ``from_color``/``self_only`` params: Agatha's
      grant is unscoped ("creatures you control") and lets *any* of the
      five colors pay any colored pip, while this card's is self-scoped
      ("this creature's abilities") and only blue mana counts as the
      wildcard (`ManaPool._solve`'s matching single-color branch) — a red
      pip still needs real red or blue mana, never green/white/black.

    The card's own parenthetical ("use this creature's name instead") is
    reminder text about the *retargeting itself* (RULE 113.7c), not a
    separate behaviour — already covered by `_retarget_effect_source`
    redirecting each borrowed effect's ``.source`` to Quicksilver Elemental.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("gain_target_activated_abilities", {})],
            cost={"mana": "{U}"},
            raw_text=(
                "{u}: this creature gains all activated abilities of "
                "target creature until end of turn. (if any of the "
                "abilities use that creature's name, use this creature's "
                "name instead.)"
            ),
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "from_color": "U",
                "self_only": True,
            })],
            raw_text="you may spend blue mana as though it were mana of "
                     "any color to pay the activation costs of this "
                     "creature's abilities.",
        ),
    ]


register("Quicksilver Elemental", _quicksilver_elemental)


def _drana_and_linvala() -> list[AbilitySpec]:
    """Flying, vigilance
    Activated abilities of creatures your opponents control can't be
    activated.
    Drana and Linvala has all activated abilities of all creatures your
    opponents control. You may spend mana as though it were mana of any
    color to activate those abilities.

    — MEC-26, the first of the two cards a second MEC-23 deferral had left
    open (found while sizing MEC-21, 2026-07-22; deferred again by MEC-23,
    2026-08-11 — this batch is the mandatory "hand-author or promote" close
    per the project's no-half-implementations rule). Needed a genuinely
    **standing, group-scoped** sibling of MEC-21's `grant_borrowed_
    activated_ability` (Agatha's Soul Cauldron) rather than MEC-23's own
    resolve-time single-target snapshot: the donor set here is "all
    creatures your opponents control", read live off the battlefield every
    recompute, not a fixed exiled-card or once-copied list. One new
    ``source_mode="group"`` on the existing static (`continuous.
    _apply_borrowed_activated_abilities`) covers it — reusing the ordinary
    ``affects`` selector vocabulary (`"creatures_opponents_control"`,
    already built for Manglehorn/goad-adjacent cards) as the *donor* scope
    rather than the *grantee* scope `affects` already served.

    The other two printed lines turned out to need no new machinery at
    all: "Activated abilities of creatures your opponents control can't be
    activated" is `activation_prohibition`'s own existing, already-general
    ``affects`` selector (Collector Ouphe-shaped, just never scoped to
    ``"creatures_opponents_control"`` by a real card before); and "You may
    spend mana as though it were mana of any color to activate **those**
    abilities" is MEC-23's `grant_any_color_for_activation`'s own
    ``self_only=True`` — the original MEC-26 filing worried ``self_only``
    would over-scope to "any ability Drana and Linvala has", not just the
    borrowed set, but Drana and Linvala prints no *other* activated
    ability of her own, so in practice the two sets are identical and no
    third param was needed. (Scheming Fence, below, is the same story.)
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "creatures_opponents_control"})],
            raw_text="activated abilities of creatures your opponents "
                     "control can't be activated.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "group",
                "source_affects": "creatures_opponents_control",
            })],
            raw_text="~ has all activated abilities of all creatures your "
                     "opponents control.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "self_only": True,
            })],
            raw_text="you may spend mana as though it were mana of any "
                     "color to activate those abilities.",
        ),
    ]


register("Drana and Linvala", _drana_and_linvala)


def _scheming_fence() -> list[AbilitySpec]:
    """As this creature enters, you may choose a nonland permanent.
    Activated abilities of the chosen permanent can't be activated.
    This creature has all activated abilities of the chosen permanent
    except for loyalty abilities. You may spend mana as though it were
    mana of any color to activate those abilities.

    — MEC-26's second card, the ``source_mode="chosen_permanent"`` sibling
    of Drana and Linvala's ``"group"`` mode: a single donor picked once
    ("the chosen permanent") rather than a whole group, needing its own
    new selector rather than reusing an existing ``affects`` value —
    `GameObject.chosen_permanent_id` (a new ``chosen_*`` field alongside
    `chosen_type`/`chosen_color`/`chosen_player_id`), a new
    ``"chosen_permanent"`` `continuous.group_selector_objects` case (the
    `attached_permanent` idiom, reading a chosen id instead of an
    attachment), and a new `ChoosePermanentEffect`/``"choose_permanent"``
    `RulesEngine.request_choose_objects` action to make the pick (an
    ordinary interactive ETB trigger, not a pre-entry RULE 601.2b
    replacement like `chosen_type`/`chosen_color` — see `GameObject.
    chosen_permanent_id`'s own docstring for why the "as it enters" wording
    doesn't need a pre-entry choice here). "You may" makes this genuinely
    optional (`ChoosePermanentEffect(optional=True)`, the default),
    unlike `chosen_type`/`chosen_color`'s always-mandatory pick.

    "…except for loyalty abilities" is `grant_borrowed_activated_ability`'s
    new ``exclude_loyalty`` param — a planeswalker-only RULE 606.5c concept
    that makes no sense copied onto a creature, dropped at the source
    rather than granted-and-then-unusable. Candidates are *any* nonland
    permanent on the whole battlefield, not just this creature's
    controller's own (`ChoosePermanentEffect`'s own docstring) — Scheming
    Fence borrows an opponent's activated ability just as readily as its
    own controller's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_permanent", {"optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="as ~ enters, you may choose a nonland permanent.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "chosen_permanent"})],
            raw_text="activated abilities of the chosen permanent can't "
                     "be activated.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "chosen_permanent",
                "exclude_loyalty": True,
                # "a nonland permanent" — unlike Drana and Linvala's
                # creature-only donor pool, the chosen permanent can be any
                # nonland type (artifact/enchantment/planeswalker/battle),
                # so the default creature-only donor filter must be off.
                "creature_only": False,
            })],
            raw_text="~ has all activated abilities of the chosen "
                     "permanent except for loyalty abilities.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "self_only": True,
            })],
            raw_text="you may spend mana as though it were mana of any "
                     "color to activate those abilities.",
        ),
    ]


register("Scheming Fence", _scheming_fence)


def _combat_celebrant() -> list[AbilitySpec]:
    """If this creature hasn't been exerted this turn, you may exert it as
    it attacks. When you do, untap all other creatures you control and
    after this phase, there is an additional combat phase.

    — Combat Celebrant. RULE 702.19's Exert is otherwise a plain oracle-text
    parse (`parser/oracle/segmenter.py`'s ``_EXERT_TRIGGER_RE``/
    ``_EXERT_PLAYER_TRIGGER_RE``, `EventType.EXERTED`) — this is the one
    card in the cache printing exert's optional "if ~ hasn't been exerted
    this turn" self-loop guard, hand-authored rather than building a general
    "once per turn" trigger-condition primitive for a single card. Without
    it, this ability's own granted extra combat phase would let the
    creature attack, exert, and grant *another* extra combat phase forever
    — a real infinite loop, not just a flavour simplification. The generic
    parser handler still claims this card's text (it just drops the guard),
    so this entry exists purely to override that with the safe,
    conditioned version; `ConditionalEffect`'s ``not_already_exerted`` key
    reads the firing `EventType.EXERTED` event's own ``already_exerted``
    snapshot (`GameEngine.declare_attackers`), not the object's live
    `exerted_this_turn` flag — that flag is already true by the time this
    trigger resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {"selector": "other_creatures_you_control", "untap": True},
                    condition={"not_already_exerted": True},
                ),
                EffectSpec(
                    "extra_combat_phase", {},
                    condition={"not_already_exerted": True},
                ),
            ],
            trigger={"event": "EXERTED", "condition": {"subject": "self"}},
            raw_text="if ~ hasn't been exerted this turn, you may exert it "
                     "as it attacks. when you do, untap all other creatures "
                     "you control and after this phase, there is an "
                     "additional combat phase.",
        ),
    ]


register("Combat Celebrant", _combat_celebrant)


def _polymorph() -> list[AbilitySpec]:
    """Destroy target creature. It can't be regenerated. Its controller
    reveals cards from the top of their library until they reveal a
    creature card. The player puts that card onto the battlefield, then
    shuffles all other cards revealed this way into their library.

    — MEC-12 (cEDH Kinnan). `DestroyExileThenControllerRevealCreatureEffect`
    is the new general primitive: one atomic effect rather than a two-effect
    list, since the dig has to be run by the *destroyed creature's own
    controller* (read before the RULE 400.7 zone change, the same "read it
    before it leaves the battlefield" idiom `DestroyGainLifeToControllerEffect`
    already uses) — not this spell's own caster. Reuses `dig_until`'s new
    ``rest_destination="library_shuffled"`` (a real shuffle, not just "the
    bottom in a random order" — the two read identically to a player, but
    match Polymorph's actual printed wording).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "destroy", "criteria": "Creature",
            })],
            raw_text="Destroy target creature. It can't be regenerated. Its "
                     "controller reveals cards from the top of their library "
                     "until they reveal a creature card. The player puts that "
                     "card onto the battlefield, then shuffles all other cards "
                     "revealed this way into their library.",
        ),
    ]


register("Polymorph", _polymorph)


def _transmogrify() -> list[AbilitySpec]:
    """Exile target creature. That creature's controller reveals cards
    from the top of their library until they reveal a creature card. That
    player puts that card onto the battlefield, then shuffles the rest
    into their library.

    — MEC-12 (cEDH Kinnan). Transmogrify's own exile-mode sibling of
    Polymorph, sharing the same new effect (`mode="exile"` — no "can't be
    regenerated" clause to carry, since exile isn't destruction to begin
    with).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy_exile_then_controller_reveal_creature", {
                "target_kind": "creature", "mode": "exile", "criteria": "Creature",
            })],
            raw_text="Exile target creature. That creature's controller "
                     "reveals cards from the top of their library until they "
                     "reveal a creature card. That player puts that card onto "
                     "the battlefield, then shuffles the rest into their "
                     "library.",
        ),
    ]


register("Transmogrify", _transmogrify)


def _reality_scramble() -> list[AbilitySpec]:
    """Put target permanent you own on the bottom of your library. Reveal
    cards from the top of your library until you reveal a card that shares
    a card type with that permanent. Put that card onto the battlefield
    and the rest on the bottom of your library in a random order.
    Retrace (You may cast this card from your graveyard by discarding a
    land card in addition to paying its other costs.)

    — MEC-12 (cEDH Kinnan). `ReturnToLibraryThenDigSharedTypeEffect` reads
    the type-matching predicate live off the just-bottomed permanent's own
    printed type words rather than a fixed criteria (see its own
    docstring). Retrace is a printed keyword (`Card.keywords`), recognized
    independently of this catalogue entry — nothing to model here.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_library_then_dig_shared_type", {
                "target_kind": "permanent_you_control",
            })],
            raw_text="Put target permanent you own on the bottom of your "
                     "library. Reveal cards from the top of your library "
                     "until you reveal a card that shares a card type with "
                     "that permanent. Put that card onto the battlefield and "
                     "the rest on the bottom of your library in a random "
                     "order.\nRetrace (You may cast this card from your "
                     "graveyard by discarding a land card in addition to "
                     "paying its other costs.)",
        ),
    ]


register("Reality Scramble", _reality_scramble)


def _sink_into_stupor() -> list[AbilitySpec]:
    """Return target spell or nonland permanent an opponent controls to
    its owner's hand.

    — MEC-12 (cEDH Kinnan/M-K). `ReturnToHandEffect`'s new
    ``spell_or_permanent`` flag routes through `RulesEngine.
    bounce_spell_or_permanent` (a still-on-the-stack target needs pulling
    out of `GameState.stack`, which the ordinary battlefield/zone-based
    `return_to_hand` has no way to reach) instead of the plain bounce.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_nonland_permanent_you_dont_control",
                "spell_or_permanent": True,
            })],
            raw_text="Return target spell or nonland permanent an opponent "
                     "controls to its owner's hand.",
        ),
    ]


register("Sink into Stupor", _sink_into_stupor)
register("Sink into Stupor // Soporific Springs", _sink_into_stupor)


def _spellskite() -> list[AbilitySpec]:
    """{U/P}: Change a target of target spell or ability to this creature.
    ({U/P} can be paid with either {U} or 2 life.)

    — MEC-12 (cEDH Kinnan). `ChangeTargetEffect`'s new ``redirect_to_source``
    flag (built for this card and Hydroelectric Specimen together) — not a
    free choice among every legal alternative the way Misdirection/
    Deflecting Swat's own player-facing pick is, but forced onto Spellskite
    itself if that's even legal. No "you may" printed, so ``optional`` stays
    False: with exactly one candidate alternative (itself), that auto-applies.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("change_target", {
                "spell_or_ability": True, "redirect_to_source": True,
            })],
            cost={"mana": "{U/P}"},
            raw_text="{U/P}: Change a target of target spell or ability to "
                     "this creature. ({U/P} can be paid with either {U} or 2 "
                     "life.)",
        ),
    ]


register("Spellskite", _spellskite)


def _hydroelectric_specimen() -> list[AbilitySpec]:
    """When Hydroelectric Specimen enters, you may change the target of
    target instant or sorcery spell with a single target to Hydroelectric
    Specimen.

    — MEC-12 (cEDH Kinnan). The ETB-triggered, "you may" sibling of
    Spellskite's activated ability, sharing the same `redirect_to_source`
    primitive — narrowed to instant/sorcery spells by `ChangeTargetEffect`'s
    new ``card_types`` param (`targeting._spell_matches_filter`'s existing
    ``card_types`` key, previously only reachable via `CounterSpellEffect`'s
    own ``card_types``, never `ChangeTargetEffect`'s).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("change_target", {
                "card_types": ["instant", "sorcery"], "single_target": True,
                "redirect_to_source": True, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When ~ enters, you may change the target of target "
                     "instant or sorcery spell with a single target to ~.",
        ),
    ]


register("Hydroelectric Specimen", _hydroelectric_specimen)
register("Hydroelectric Specimen // Hydroelectric Laboratory", _hydroelectric_specimen)


def _void_winnower() -> list[AbilitySpec]:
    """Your opponents can't cast spells with even mana values. (Zero is
    even.)
    Your opponents can't block with creatures with even mana values.

    — MEC-12 (cEDH Kinnan). Two new filter keys, both keyed off "Zero is
    even": `cast_prohibition`'s new ``even_mana_value`` param
    (`continuous.cast_prohibited`) for the cast-side clause, and
    `combat.matches_object_filter`'s new ``even_mana_value`` key (checked
    against the *blocker itself* via the new `cant_block_self_filtered`
    combat-restriction kind — every existing blocker-side kind filters the
    *attacker*, which isn't what this card's blocker-own-characteristics
    restriction needs) for the block-side one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "even_mana_value": True,
            })],
            raw_text="Your opponents can't cast spells with even mana "
                     "values. (Zero is even.)",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_block_self_filtered",
                "filter": {"even_mana_value": True},
                "affects": "creatures_opponents_control",
            })],
            raw_text="Your opponents can't block with creatures with even "
                     "mana values.",
        ),
    ]


register("Void Winnower", _void_winnower)


def _nyxbloom_ancient() -> list[AbilitySpec]:
    """Trample
    If you tap a permanent for mana, it produces three times as much of
    that mana instead.

    — MEC-12 (cEDH Kinnan). The new `mana_multiplier` static
    (`continuous.mana_production_multiplier_for`, consulted directly by
    `GameEngine.tap_for_mana`) — Trample is a printed keyword, recognized
    independently of this entry.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_multiplier", {"multiplier": 3})],
            raw_text="If you tap a permanent for mana, it produces three "
                     "times as much of that mana instead.",
        ),
    ]


register("Nyxbloom Ancient", _nyxbloom_ancient)


def _trinisphere() -> list[AbilitySpec]:
    """As long as this artifact is untapped, each spell that would cost
    less than three mana to cast costs three mana to cast instead.

    — MEC-12 (cEDH Kinnan). The new `cost_floor_for`/``min_generic``
    "costs no less than N" primitive — a floor, not the existing
    ``increase``/``generic`` additive tax (see `continuous.cost_floor_for`'s
    own docstring for why the two are kept apart). ``active_if:
    source_untapped`` is the existing RULE 613.6 gate vocabulary, reused
    as-is.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells", "min_generic": 3,
                "active_if": {"kind": "source_untapped"},
            })],
            raw_text="As long as this artifact is untapped, each spell that "
                     "would cost less than three mana to cast costs three "
                     "mana to cast instead.",
        ),
    ]


register("Trinisphere", _trinisphere)


def _tezzeret_the_seeker() -> list[AbilitySpec]:
    """+1: Untap up to two target artifacts.
    −X: Search your library for an artifact card with mana value X or
    less, put it onto the battlefield, then shuffle.
    −5: Artifacts you control become artifact creatures with base power
    and toughness 5/5 until end of turn.

    — MEC-12 (cEDH Kinnan). Hand-authored whole (rather than reusing the
    parser's own claimed +1 spec) since that spec's ``target_kind`` reads
    "permanent" instead of "artifact" — fixed here rather than left
    inconsistent across the card's three abilities. The −X search is the
    existing `search` effect with the ``"x"`` sentinel
    (`RulesEngine._substitute_x` already walks a ``criteria`` dict's
    ``max_mana_value`` for exactly this). The −5 is `GrantUntilEffect`
    wrapping a `type_change` static scoped to ``affects="artifacts_you_
    control"`` — untargeted (``target_kind=None``), since nothing here is a
    RULE 115 target at all, just every artifact the activating player
    already controls.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {
                "target_kind": "artifact", "count": 2, "optional": True, "untap": True,
            })],
            cost={"loyalty": 1},
            raw_text="+1: Untap up to two target artifacts.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact", "max_mana_value": "x"},
                "destination": "battlefield",
            })],
            cost={"loyalty": "-x"},
            raw_text="−X: Search your library for an artifact card with mana "
                     "value X or less, put it onto the battlefield, then "
                     "shuffle.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "affects": "artifacts_you_control", "add_types": ["creature"],
                    "power": 5, "toughness": 5,
                }},
                "duration": "end_of_turn", "target_kind": None,
            })],
            cost={"loyalty": -5},
            raw_text="−5: Artifacts you control become artifact creatures "
                     "with base power and toughness 5/5 until end of turn.",
        ),
    ]


register("Tezzeret the Seeker", _tezzeret_the_seeker)


def _treasure_vault() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {X}{X}, {T}, Sacrifice this land: Create X Treasure tokens.

    — MEC-12 (cEDH Kinnan). The plain "{T}: Add {C}." mana ability needs no
    entry at all here — `game/mana_abilities.py`'s `mana_abilities_for`
    reads it straight off `Card.oracle_text` via its own regex, completely
    independent of catalogue registration (unlike `parse_oracle`'s
    AbilitySpec pipeline, which *does* turn off once a name is registered).
    Only the X-cost second ability needs hand-authoring. ``"count": "x"``
    on `create_token` rides the same ``"x"`` sentinel the ``{X}{X}`` cost
    itself does (`RulesEngine._substitute_x` walks a plain effect ``count``
    attribute).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {"count": "x", "token_name": "Treasure"})],
            cost={"text": "{X}{X}", "tap": True, "sacrifice": "self"},
            raw_text="{X}{X}, {T}, Sacrifice this land: Create X Treasure "
                     "tokens.",
        ),
    ]


register("Treasure Vault", _treasure_vault)


def _narset_parter_of_veils() -> list[AbilitySpec]:
    """Each opponent can't draw more than one card each turn.
    −2: Look at the top four cards of your library. You may reveal a
    noncreature, nonland card from among them and put it into your hand.
    Put the rest on the bottom of your library in a random order.

    — MEC-12 (cEDH M-K). The static is `draw_limit`'s new ``affects``
    param (default was hardwired to ``"all"``, Spirit-of-the-Labyrinth-
    shaped) — see `continuous.max_draws_per_turn`'s own docstring. The
    loyalty ability is `impulsive_look` with the new ``without_type``
    `card_query` key (`"creature"`/`"land"`, AND-combined — RULE 205's
    main types only) and the new ``miss_destination="library_bottom_
    random"`` (a *group* shuffle of the un-revealed cards, not each one
    independently bottomed in reveal order).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"affects": "opponents", "max_per_turn": 1})],
            raw_text="Each opponent can't draw more than one card each turn.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 4, "criteria": {"without_type": ["creature", "land"]},
                "hit_destination": "hand", "miss_destination": "library_bottom_random",
                "optional": True,
            })],
            cost={"loyalty": -2},
            raw_text="−2: Look at the top four cards of your library. You "
                     "may reveal a noncreature, nonland card from among "
                     "them and put it into your hand. Put the rest on the "
                     "bottom of your library in a random order.",
        ),
    ]


register("Narset, Parter of Veils", _narset_parter_of_veils)


def _kediss_emberclaw_familiar() -> list[AbilitySpec]:
    """Whenever a commander you control deals combat damage to an
    opponent, it deals that much damage to each other opponent.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). The new top-level ``contributor_is_commander``
    trigger key (RULE 903's own designation, stamped onto the existing
    MEC-29 aggregate combat-damage event by `GameEngine.
    _apply_combat_damage` — the same "no single acting object, so the
    event carries the aggregate characteristic itself" reasoning as
    `contributor_power_at_least`/`contributor_subtype`, not a live
    per-object `_build_group_ok` filter, since this event names no
    instance to look one up on) combined with the new
    ``each_other_opponent`` `DealDamageEffect` selector (``each_opponent``
    minus whichever opponent the firing event itself already hit). Partner
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_other_opponent",
            })],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_is_commander": True,
            },
            raw_text="Whenever a commander you control deals combat damage "
                     "to an opponent, it deals that much damage to each "
                     "other opponent.",
        ),
    ]


register("Kediss, Emberclaw Familiar", _kediss_emberclaw_familiar)


def _malcolm_keen_eyed_navigator() -> list[AbilitySpec]:
    """Flying
    Whenever one or more Pirates you control deal damage to your
    opponents, you create a Treasure token for each opponent dealt
    damage. (It's an artifact with "{T}, Sacrifice this token: Add one
    mana of any color.")
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH M-K). **Documented simplification**: scoped to *combat*
    damage (the new ``contributor_subtype`` trigger key on the existing
    MEC-29 aggregate event, `GameEngine._apply_combat_damage`'s own
    ``subtypes`` field — the union of every contributing creature's
    subtypes that step), not the printed card's fully general "deal
    damage" — noncombat damage from a controlled Pirate is a vanishingly
    rare case this template doesn't reach. "A Treasure for each opponent
    dealt damage" needs no explicit count: the aggregate event already
    fires once per (controller, opponent-hit) pair (MEC-29), so each
    firing is already scoped to exactly one opponent. Flying/Partner are
    printed keywords, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you"},
                "contributor_subtype": "pirate",
            },
            raw_text="Whenever one or more Pirates you control deal combat "
                     "damage to a player, you create a Treasure token for "
                     "that opponent.",
        ),
    ]


register("Malcolm, Keen-Eyed Navigator", _malcolm_keen_eyed_navigator)


def _glint_horn_buccaneer() -> list[AbilitySpec]:
    """Haste
    Whenever you discard a card, this creature deals 1 damage to each
    opponent.
    {1}{R}, Discard a card: Draw a card. Activate only if this creature
    is attacking.

    — MEC-12 (cEDH M-K). The new ``"DISCARD"`` row in `effect_binder.
    _GROUP_CONTROLLER_EVENT_KEYS` (a plain player-subject trigger,
    ``{"subject": "you"}`` — the same shape "whenever you scry/gain
    life/draw a card" already use, just missing this one event) closes
    the first ability; the second's "activate only if attacking" is
    already-general `ActivationCost.activation_condition` machinery
    (`static_conditions`' existing ``source_attacking`` kind, PAR-10) —
    no new primitive, just the first real card to combine the two. Haste
    is a printed keyword, recognized independently of this entry.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_opponent"})],
            trigger={"event": "DISCARD", "condition": {"subject": "you"}},
            raw_text="Whenever you discard a card, ~ deals 1 damage to "
                     "each opponent.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={
                "mana": "{1}{R}", "discard": 1,
                "activation_condition": {"kind": "source_attacking"},
            },
            raw_text="{1}{R}, Discard a card: Draw a card. Activate only "
                     "if ~ is attacking.",
        ),
    ]


register("Glint-Horn Buccaneer", _glint_horn_buccaneer)


def _horizon_of_progress() -> list[AbilitySpec]:
    """{T}, Pay 1 life: Add one mana of any type that a land you control
    could produce.
    {3}, {T}: You may put a land card from your hand onto the
    battlefield tapped.
    {1}, {T}, Sacrifice this land: Draw a card.

    — MEC-12 (cEDH M-K). The first ability needs no entry at all —
    `mana_abilities_for` reads "any type a land you control could
    produce" straight off oracle text, independent of catalogue
    registration (same reasoning as Treasure Vault's plain mana ability).
    The third is already parser-claimed for free (`reuse` confirms it —
    restated here since registering this name turns the parser fallback
    off for *every* ability, not just the unclaimed one). Only the second
    needs real hand-authoring: `put_from_hand_onto_battlefield`'s new
    ``tapped`` flag.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": "Land", "count": 1, "tapped": True,
            })],
            cost={"text": "{3}, {T}"},
            raw_text="{3}, {T}: You may put a land card from your hand "
                     "onto the battlefield tapped.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}, {T}, Sacrifice ~"},
            raw_text="{1}, {T}, Sacrifice ~: Draw a card.",
        ),
    ]


register("Horizon of Progress", _horizon_of_progress)


def _commandeer() -> list[AbilitySpec]:
    """You may exile two blue cards from your hand rather than pay this
    spell's mana cost.
    Gain control of target noncreature spell. You may choose new targets
    for it. (If that spell is an artifact, enchantment, or planeswalker,
    the permanent enters under your control.)

    — MEC-12 (cEDH M-K). The alt cost is already parser-claimed for free
    (`reuse` confirms it, `AbilitySpec.alt_cost`'s existing
    ``exile_hand_card_color_count`` key). The real gain-control-of-a-
    *spell* effect is new: `GainControlOfSpellEffect`/`RulesEngine.
    gain_control_of_spell` — see its own docstring for why only
    `StackItem.controller_id` (not a battlefield zone-change) needs to
    move, and why the optional retarget runs *before* that flip.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_of_spell", {})],
            raw_text="Gain control of target noncreature spell. You may "
                     "choose new targets for it.",
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color_count": [2, "U"]},
            raw_text="You may exile two blue cards from your hand rather "
                     "than pay this spell's mana cost.",
        ),
    ]


register("Commandeer", _commandeer)


def _days_undoing() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards. If it's your turn, end the turn. (Exile all
    spells and abilities from the stack, including this card. Discard
    down to your maximum hand size. Damage wears off, and "this turn"
    and "until end of turn" effects end.)

    — MEC-12 (cEDH M-K). `wheel` (Timetwister) covers the first sentence
    unchanged. "If it's your turn, end the turn" is the new
    ``is_your_turn`` `ConditionalEffect` gate wrapping the new
    `end_the_turn`/`EndTheTurnEffect` (RulesEngine can't reach
    `GameEngine._turn_steps`/`_cursor` directly, so it exiles the stack
    now and queues `GameState.end_turn_requested` for `GameEngine.
    advance_step` to drain — see both docstrings). "Including this card"
    is a trailing self-exile (``target_kind=None``), the same override
    `_apply_stack_item` already gives `ShuffleSelfIntoLibraryEffect` —
    without it this card would go to its owner's graveyard as normal
    resolution, not exile.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("wheel", {"draw_count": 7}),
                EffectSpec("end_the_turn", {}, condition={"is_your_turn": True}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            raw_text="Each player shuffles their hand and graveyard into "
                     "their library, then draws seven cards. If it's your "
                     "turn, end the turn.",
        ),
    ]


register("Day's Undoing", _days_undoing)


def _lukka_coppercoat_outcast() -> list[AbilitySpec]:
    """+1: Exile the top three cards of your library. Creature cards
    exiled this way gain "You may cast this card from exile as long as
    you control a Lukka planeswalker."
    −2: Exile target creature you control, then reveal cards from the top
    of your library until you reveal a creature card with greater mana
    value. Put that card onto the battlefield and the rest on the bottom
    of your library in a random order.
    −7: Each creature you control deals damage equal to its power to
    each opponent.

    — MEC-12 (cEDH M-K). The +1 is the new `exile_top_then_grant_
    conditional_cast`/`GameState.exile_cast_condition` — a genuinely
    standing (never turn-swept) exile cast permission, unlike every other
    "exile, may cast later" grant in this engine, gated on the new
    ``planeswalkers_you_control_of_type_`` count selector via the
    already-general `control_count` static condition. The −2 is
    `exile_then_reveal_greater_mana_value` (the exiled target's own mana
    value becomes the dig's floor, read at resolution). The −7 is
    `each_creature_you_control_damages_each_opponent`, a double mass
    effect no existing `DealDamageEffect` selector already composes.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_top_then_grant_conditional_cast", {
                "count": 3,
                "condition": {
                    "kind": "control_count",
                    "selector": "planeswalkers_you_control_of_type_lukka",
                    "min": 1,
                },
            })],
            cost={"loyalty": 1},
            raw_text='+1: Exile the top three cards of your library. '
                     'Creature cards exiled this way gain "You may cast '
                     'this card from exile as long as you control a Lukka '
                     'planeswalker."',
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile_then_reveal_greater_mana_value", {
                "target_kind": "creature_you_control",
            })],
            cost={"loyalty": -2},
            raw_text="−2: Exile target creature you control, then reveal "
                     "cards from the top of your library until you reveal "
                     "a creature card with greater mana value. Put that "
                     "card onto the battlefield and the rest on the bottom "
                     "of your library in a random order.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("each_creature_you_control_damages_each_opponent", {})],
            cost={"loyalty": -7},
            raw_text="−7: Each creature you control deals damage equal to "
                     "its power to each opponent.",
        ),
    ]


register("Lukka, Coppercoat Outcast", _lukka_coppercoat_outcast)


def _enduring_vitality() -> list[AbilitySpec]:
    """Vigilance
    Creatures you control have "{T}: Add one mana of any color."
    When Enduring Vitality dies, if it was a creature, return it to the
    battlefield under its owner's control. It's an enchantment. (It's not
    a creature.)

    — MEC-12 (cEDH Kinnan). Vigilance and the granted mana ability are
    both already parser-claimed for free (`reuse` confirms it — restated
    here since registering the name turns that fallback off for every
    ability, not just the unclaimed one). The dies-trigger is the new
    `dies_return_as_enchantment`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keyword": "vigilance", "affects": "self"})],
            raw_text="Vigilance",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "creatures_you_control", "mana": [{"C": 1}],
            })],
            raw_text='Creatures you control have "{T}: Add one mana of any '
                     'color."',
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("dies_return_as_enchantment", {})],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="When ~ dies, if it was a creature, return it to the "
                     "battlefield under its owner's control. It's an "
                     "enchantment.",
        ),
    ]


register("Enduring Vitality", _enduring_vitality)


def _faerie_mastermind() -> list[AbilitySpec]:
    """Flash
    Flying
    Whenever an opponent draws their second card each turn, you draw a
    card.
    {3}{U}: Each player draws a card.

    — MEC-12 (cEDH Kinnan). Flash/Flying and the activated "each player
    draws" are already parser-claimed for free. Only the second-draw
    trigger needs the new ``is_nth_draw_this_turn`` top-level trigger key.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "DRAW", "condition": {"subject": "group", "controller": "not_you"},
                "is_nth_draw_this_turn": 2,
            },
            raw_text="Whenever an opponent draws their second card each "
                     "turn, you draw a card.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1, "selector": "each_player"})],
            cost={"mana": "{3}{U}"},
            raw_text="{3}{U}: Each player draws a card.",
        ),
    ]


register("Faerie Mastermind", _faerie_mastermind)


def _into_the_flood_maw() -> list[AbilitySpec]:
    """Gift a tapped Fish (You may promise an opponent a gift as you cast
    this spell. If you do, they create a tapped 1/1 blue Fish creature
    token before its other effects.)
    Return target creature an opponent controls to its owner's hand. If
    the gift was promised, instead return target nonland permanent an
    opponent controls to its owner's hand.

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the Gift
    mechanic (RULE-adjacent WOE ability word — a cast-time "promise a
    gift" branch with no engine primitive anywhere yet) is dropped
    entirely; this always resolves as the un-gifted base mode ("return
    target creature an opponent controls to its owner's hand"), never
    offering the opponent a Fish or the "any nonland permanent" upgrade.
    Building Gift generally is real, standalone engine work — a genuinely
    new interactive cast-time choice threaded through casting/targeting —
    not something to fold into one card's own entry.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {"target_kind": "creature_you_dont_control"})],
            raw_text="Return target creature an opponent controls to its "
                     "owner's hand.",
        ),
    ]


register("Into the Flood Maw", _into_the_flood_maw)


def _invasion_of_ikoria() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, search your library and/or graveyard for a
    non-Human creature card with mana value X or less and put it onto
    the battlefield. If you search your library this way, shuffle.

    — MEC-12 (cEDH Kinnan). The Siege reminder text is the existing
    generic RULE 310 battle machinery, not modeled here. The search
    itself already fully supports "library and/or graveyard"
    (`SearchLibraryEffect`'s existing ``zones`` param — always shuffles
    when "library" is among them, RULE 701.19e, matching "if you search
    your library this way, shuffle" for the common case of always
    searching both). The only new piece is the ``"source_x_paid"``
    criteria sentinel: this ETB fires well after the original casting
    resolution ends, so the existing bare ``"x"`` sentinel (tied to
    *this* stack item's own announced X, which is 0 for a trigger) can't
    reach the permanent's announced X the way it does for a spell's own
    effects — `GameObject.x_paid`, stamped once at cast time, is read
    instead.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {
                    "type": "Creature", "without_type": "human",
                    "max_mana_value": "source_x_paid",
                },
                "destination": "battlefield",
                "zones": ["library", "graveyard"],
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this Siege enters, search your library and/or "
                     "graveyard for a non-Human creature card with mana "
                     "value X or less and put it onto the battlefield. If "
                     "you search your library this way, shuffle.",
        ),
    ]


register("Invasion of Ikoria", _invasion_of_ikoria)
register("Invasion of Ikoria // Zilortha, Apex of Ikoria", _invasion_of_ikoria)


def _machine_gods_effigy() -> list[AbilitySpec]:
    """You may have this artifact enter as a copy of any creature on the
    battlefield, except it's an artifact and it has "{T}: Add {U}." (It's
    not a creature.)
    {T}: Add {U}.

    — MEC-12 (cEDH Kinnan). `EnterAsCopyReplacement`'s new
    ``grant_mana_option`` param — RULE 707.2's copy replaces the card's
    own printed text (including its own real "{T}: Add {U}." line) with
    the copied creature's, so that ability has to be re-granted as part
    of this same "except" clause rather than assumed to survive; applied
    as a fresh `StaticAbility` on the copy itself once `become_copy`
    resolves (`GameObject.granted_mana_options` is a read-only,
    every-recompute-rederived property, not a settable field). The plain
    "{T}: Add {U}." second line needs no entry of its own — read straight
    off oracle text by `mana_abilities_for`, same as Treasure Vault/
    Horizon of Progress — but note it only actually produces mana while
    this artifact *hasn't* copied anything (a successful copy overwrites
    it, which is exactly why the grant above exists).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "add_types": ["artifact"],
                "grant_mana_option": {"U": 1},
                "optional": True,
            })],
            raw_text="You may have ~ enter as a copy of any creature on "
                     'the battlefield, except it\'s an artifact and it has '
                     '"{T}: Add {U}."',
        ),
    ]


register("Machine God's Effigy", _machine_gods_effigy)


def _moonsilver_key() -> list[AbilitySpec]:
    """{1}, {T}, Sacrifice this artifact: Search your library for an
    artifact card with a mana ability or a basic land card, reveal it,
    put it into your hand, then shuffle.

    — MEC-12 (cEDH Kinnan). The new `card_query` ``"or"``/
    ``"has_mana_ability"`` keys — the first real compound ("X or Y")
    search criteria in the catalogue; every prior search criteria dict
    was a plain AND.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {
                    "or": [
                        {"type": "Artifact", "has_mana_ability": True},
                        {"basic": True},
                    ],
                },
                "destination": "hand",
            })],
            cost={"text": "{1}, {T}, Sacrifice ~"},
            raw_text="{1}, {T}, Sacrifice ~: Search your library for an "
                     "artifact card with a mana ability or a basic land "
                     "card, reveal it, put it into your hand, then "
                     "shuffle.",
        ),
    ]


register("Moonsilver Key", _moonsilver_key)


def _nezahal_primal_tide() -> list[AbilitySpec]:
    """This spell can't be countered.
    You have no maximum hand size.
    Whenever an opponent casts a noncreature spell, draw a card.
    Discard three cards: Exile Nezahal. Return it to the battlefield
    tapped under its owner's control at the beginning of the next end
    step.

    — MEC-12 (cEDH Kinnan). The first three abilities are already
    parser-claimed for free (`reuse` confirms it — restated here since
    registering the name turns the parser fallback off for all of them,
    not just the unclaimed one). The activated ability is the new
    `return_self_to_battlefield`, run via the existing RULE 603.7
    `CreateDelayedTriggerEffect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("no_max_hand_size", {"affects": "you"})],
            raw_text="You have no maximum hand size.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Whenever an opponent casts a noncreature spell, "
                     "draw a card.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_self_to_battlefield", "params": {"tapped": True}}],
                    "description": "Nezahal: return tapped at the next end step",
                }),
            ],
            cost={"discard": 3},
            raw_text="Discard three cards: Exile ~. Return it to the "
                     "battlefield tapped under its owner's control at the "
                     "beginning of the next end step.",
        ),
    ]


register("Nezahal, Primal Tide", _nezahal_primal_tide)


def _thrasios_triton_hero() -> list[AbilitySpec]:
    """{4}: Scry 1, then reveal the top card of your library. If it's a
    land card, put it onto the battlefield tapped. Otherwise, draw a
    card.
    Partner (You can have two commanders if both have partner.)

    — MEC-12 (cEDH Kinnan). `scry` (already general) chained with the new
    `reveal_top_then_land_battlefield_or_draw` — RULE 608.2's "suspend on
    a pending choice, resume once answered" already parks the second
    effect until scry's own interactive choice is settled, so no new
    sequencing primitive is needed, only the reveal-and-branch effect
    itself (a genuine singleton shape with nothing close enough to
    reuse). Partner is a printed keyword, recognized independently of
    this entry.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("scry", {"count": 1}),
                EffectSpec("reveal_top_then_land_battlefield_or_draw", {}),
            ],
            cost={"mana": "{4}"},
            raw_text="{4}: Scry 1, then reveal the top card of your "
                     "library. If it's a land card, put it onto the "
                     "battlefield tapped. Otherwise, draw a card.",
        ),
    ]


register("Thrasios, Triton Hero", _thrasios_triton_hero)


def _veil_of_summer() -> list[AbilitySpec]:
    """Draw a card if an opponent has cast a blue or black spell this
    turn. Spells you control can't be countered this turn. You and
    permanents you control gain hexproof from blue and from black until
    end of turn. (You and they can't be the targets of blue or black
    spells or abilities your opponents control.)

    — MEC-12 (cEDH Kinnan). **Documented simplification**: the third
    sentence ("You and permanents you control gain hexproof from blue
    and from black") is dropped — this engine's `combat.has_hexproof`
    is an unqualified RULE 702.11b flag with no "hexproof from `<quality>`"
    variant (RULE 702.11c), and there is no player-level hexproof/
    targetability check anywhere at all yet (every "player" target kind
    in `targeting.py` returns every living player unconditionally).
    Building qualified hexproof for both permanents and players is a
    real, standalone engine primitive, not something to wedge into this
    card's own entry. The other two clauses are real: the new
    ``opponent_cast_color_this_turn`` `ConditionalEffect` condition
    (`GameState.spell_colors_cast_this_turn`, tracked off `SPELL_CAST`
    the same way `cast_instant_or_sorcery_this_turn` already is) and the
    new `mark_your_spells_on_stack_cant_be_countered` (immediate) +
    `arm_spell_watcher`'s new ``repeat`` flag (for the rest of the turn).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"opponent_cast_color_this_turn": ["U", "B"]},
                ),
                EffectSpec("mark_your_spells_on_stack_cant_be_countered", {}),
                EffectSpec("arm_spell_watcher", {
                    "then_specs": [{"type": "mark_cant_be_countered", "params": {}}],
                    "repeat": True,
                }),
            ],
            raw_text="Draw a card if an opponent has cast a blue or black "
                     "spell this turn. Spells you control can't be "
                     "countered this turn.",
        ),
    ]


register("Veil of Summer", _veil_of_summer)


def _hullbreaker_horror() -> list[AbilitySpec]:
    """Flash
    This spell can't be countered.
    Whenever you cast a spell, choose up to one —
    • Return target spell you don't control to its owner's hand.
    • Return target nonland permanent to its owner's hand.

    — MEC-12 (cEDH Kinnan). Flash and "this spell can't be countered" are
    already parser-claimed for free. The modal trigger needs the new
    RULE 700.2 "choose *up to* one —" quantifier (`AbilitySpec.modes`'s
    new ``optional`` key, `TriggeredAbility.modes_optional`) — the 0-or-1
    sibling of the existing plain "choose one" (always exactly 1) and
    "choose one or both" (1 or 2) shapes, which had no way to express a
    real decline. The first mode's target is the new
    ``spell_you_dont_control`` kind (``ReturnToHandEffect``'s
    ``spell_or_permanent`` flag for the stack-aware bounce).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "triggered",
            [],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"}},
            modes={
                "choose": 1,
                "optional": True,
                "options": [
                    [EffectSpec("return_to_hand", {
                        "target_kind": "spell_you_dont_control", "spell_or_permanent": True,
                    })],
                    [EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"})],
                ],
                "descriptions": [
                    "Return target spell you don't control to its owner's hand.",
                    "Return target nonland permanent to its owner's hand.",
                ],
            },
            raw_text="Whenever you cast a spell, choose up to one —\n"
                     "• Return target spell you don't control to its "
                     "owner's hand.\n"
                     "• Return target nonland permanent to its owner's "
                     "hand.",
        ),
    ]


register("Hullbreaker Horror", _hullbreaker_horror)


# ---------------------------------------------------------------------------
# MEC-12: Ojer cEDH — new core primitive (`EventType.ACTIVATED_ABILITY`,
# RULE 602.2) + oracle-text-blind reuse of the existing TAPPED_FOR_MANA
# "group"/"nonbasic" scoping (effect_binder.py) for the "punisher" family.
# ---------------------------------------------------------------------------


def _manabarbs() -> list[AbilitySpec]:
    """Whenever a player taps a land for mana, this enchantment deals 1
    damage to that player. — Manabarbs. The bare, untyped sibling of Price
    of Glory's own `TAPPED_FOR_MANA` consumer: no `"nonbasic"` filter, and
    `DealDamageEffect`'s existing `selector="event_player"` (Spellshock's
    shape) for "that player" instead of Price of Glory's reflexive-target
    destroy.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land"},
            },
            raw_text="Whenever a player taps a land for mana, this "
                     "enchantment deals 1 damage to that player.",
        )
    ]


register("Manabarbs", _manabarbs)


def _burning_earth() -> list[AbilitySpec]:
    """Whenever a player taps a nonbasic land for mana, this enchantment
    deals 1 damage to that player. — Burning Earth. Manabarbs' own
    `"nonbasic"` sibling — `effect_binder._build_group_ok`'s new supertype
    filter (a live board check, since "Basic" isn't a main type
    `object_types` carries or a subtype after the em dash).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "nonbasic": True},
            },
            raw_text="Whenever a player taps a nonbasic land for mana, "
                     "this enchantment deals 1 damage to that player.",
        )
    ]


register("Burning Earth", _burning_earth)


def _harsh_mentor() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land on the battlefield, if it isn't a mana ability, this creature
    deals 2 damage to that player. — Harsh Mentor. First consumer of the
    new `EventType.ACTIVATED_ABILITY` (`GameEngine.activate_ability`, RULE
    602.2) — mana abilities never reach that event at all (RULE 605.1a:
    they never use the stack, resolving instead through `tap_for_mana`/
    `activate_hand_mana_ability`), so "isn't a mana ability" needs no
    filter of its own. "of an artifact, creature, or land" is simplified to
    "of a permanent" (artifact/creature/land cover the overwhelming
    majority of real activated abilities; a planeswalker/battle/
    enchantment-only activated ability triggering this too is a narrow,
    documented over-trigger rather than a missed one).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent activates an ability of an "
                     "artifact, creature, or land on the battlefield, if "
                     "it isn't a mana ability, this creature deals 2 "
                     "damage to that player.",
        )
    ]


register("Harsh Mentor", _harsh_mentor)


def _immolation_shaman() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of an artifact, creature,
    or land that isn't a mana ability, this creature deals 1 damage to
    that player.
    {3}{R}{R}: This creature gets +3/+3 and gains menace until end of turn.

    — Immolation Shaman. Harsh Mentor's own 1-damage sibling; its pump
    ability is already parser-claimed (`author_card.py reuse`) and just
    copied here verbatim, since registering a card replaces the parser's
    specs wholesale rather than merging with them.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent activates an ability of an "
                     "artifact, creature, or land that isn't a mana "
                     "ability, this creature deals 1 damage to that "
                     "player.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 3, "toughness": 3, "keywords": ["menace"]})],
            cost={"text": "{3}{r}{r}"},
            raw_text="{3}{r}{r}: ~ gets +3/+3 and gains menace until end of turn.",
        ),
    ]


register("Immolation Shaman", _immolation_shaman)


def _zo_zu_the_punisher() -> list[AbilitySpec]:
    """Whenever a land enters, Zo-Zu deals 2 damage to that land's
    controller. — Zo-Zu the Punisher. Named-by-proper-noun self-reference
    (not "this creature"/"~"), which `normalize._fold_self_reference`
    doesn't fold for a hyphenated card name — hand-authored rather than
    chasing that edge case for one card. New `DealDamageEffect`
    ``selector="event_controller"`` (the entering land's own controller,
    distinct from ``"event_player"``'s cast/draw-shaped "acting player").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_controller"})],
            trigger={
                "event": "ENTERS_BATTLEFIELD",
                "condition": {"subject": "group", "type": "land"},
            },
            raw_text="Whenever a land enters, Zo-Zu deals 2 damage to "
                     "that land's controller.",
        )
    ]


register("Zo-Zu the Punisher", _zo_zu_the_punisher)


def _spiteful_banditry() -> list[AbilitySpec]:
    """When this enchantment enters, it deals X damage to each creature.
    Whenever one or more creatures your opponents control die, you create
    a Treasure token. This ability triggers only once each turn.

    — Spiteful Banditry. New `DealDamageEffect.x_multiplier` (the
    `AddCountersEffect` primitive's own sibling) for the ETB's announced
    {X}. The "one or more … die" aggregate quantifier is approximated by
    an ordinary per-creature DIES group trigger plus the printed "only
    once each turn" cap (``trigger["limit"]``) — both shapes create at
    most one Treasure per turn regardless of how many opponent creatures
    die simultaneously, so the board outcome is identical either way.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"x_multiplier": 1, "selector": "each_creature"})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this enchantment enters, it deals X damage to "
                     "each creature.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"token_name": "Treasure", "count": 1})],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature", "controller": "not_you"},
                "limit": True,
            },
            raw_text="Whenever one or more creatures your opponents "
                     "control die, you create a Treasure token. This "
                     "ability triggers only once each turn.",
        ),
    ]


register("Spiteful Banditry", _spiteful_banditry)


def _pyrohemia() -> list[AbilitySpec]:
    """At the beginning of the end step, if no creatures are on the
    battlefield, sacrifice this enchantment.
    {R}: This enchantment deals 1 damage to each creature and each player.

    — Pyrohemia. New `EffectSpec.condition` key ``no_creatures_on_
    battlefield`` (global, unlike the existing controller-scoped
    ``controls_none_of_type``); the activated ability reuses
    `DealDamageEffect`'s already-shipped ``each_creature_and_player``
    selector (Volcanic Fallout-shaped) verbatim — this card's own body just
    hadn't been recognized by the parser yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {}, condition={"no_creatures_on_battlefield": True})],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}},
            raw_text="At the beginning of the end step, if no creatures "
                     "are on the battlefield, sacrifice this enchantment.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_player"})],
            cost={"text": "{r}"},
            raw_text="{r}: this enchantment deals 1 damage to each "
                     "creature and each player.",
        ),
    ]


register("Pyrohemia", _pyrohemia)


def _karn_the_great_creator() -> list[AbilitySpec]:
    """Activated abilities of artifacts your opponents control can't be
    activated.
    +1: Until your next turn, up to one target noncreature artifact
    becomes an artifact creature with power and toughness each equal to
    its mana value.
    -2: You may reveal an artifact card you own from outside the game or
    choose a face-up artifact card you own in exile. Put that card into
    your hand.

    — Karn, the Great Creator. First static already parser-claimed
    (`activation_prohibition`). The +1 needs two new primitives: RULE
    115.1c's `"noncreature_artifact"` target kind, and `type_change`'s new
    ``pt_selector="mana_value"`` (a dynamic sibling of its existing literal
    ``power``/``toughness`` ints), wrapped in the RULE 611.2b
    `GrantUntilEffect` (``duration="your_next_turn"``) — the same primitive
    "until end of turn" grants use, just a different sweep window. The -2
    is a **documented simplification**: this engine has no "outside the
    game" zone (a sideboard-like concept with no Commander legal use), so
    only its real half — reclaim a face-up artifact card from exile — is
    modeled; the "reveal … from outside the game" branch is dropped.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {
                "affects": "opponents_permanents", "card_type": "artifact",
            })],
            raw_text="Activated abilities of artifacts your opponents "
                     "control can't be activated.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "pt_selector": "mana_value",
                }},
                "duration": "your_next_turn",
                "target_kind": "noncreature_artifact",
                "optional": True,
                "count": 1,
            })],
            cost={"loyalty": 1},
            raw_text="+1: Until your next turn, up to one target "
                     "noncreature artifact becomes an artifact creature "
                     "with power and toughness each equal to its mana "
                     "value.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"}, "destination": "hand", "zones": ["exile"],
            })],
            cost={"loyalty": -2},
            raw_text="-2: Choose a face-up artifact card you own in "
                     "exile. Put that card into your hand.",
        ),
    ]


register("Karn, the Great Creator", _karn_the_great_creator)


def _cemetery_gatekeeper() -> list[AbilitySpec]:
    """First strike
    When this creature enters, exile a card from a graveyard.
    Whenever a player plays a land or casts a spell, if it shares a card
    type with the exiled card, this creature deals 2 damage to that
    player.

    — Cemetery Gatekeeper. ``any_graveyard_card`` is the existing Regrowth/
    Reanimate-family target kind ("a graveyard" — RULE 115's "any single
    graveyard, whosever it is"); `ExileEffect.remember` stamps the exiled
    card's `instance_id` onto `GameObject.linked_exile_id`, and the new
    `EffectSpec.condition` key ``shares_type_with_linked_exile`` (RULE
    205.2a real card types only) gates the two payoff triggers — one per
    firing event (LAND_PLAYED/SPELL_CAST), the same "one spec per event"
    shape the "scry or surveil" compound trigger uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "any_graveyard_card", "remember": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this creature enters, exile a card from a "
                     "graveyard.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "LAND_PLAYED", "condition": {"subject": "group"}},
            raw_text="Whenever a player plays a land, if it shares a card "
                     "type with the exiled card, this creature deals 2 "
                     "damage to that player.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"shares_type_with_linked_exile": True})],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "group"}},
            raw_text="Whenever a player casts a spell, if it shares a "
                     "card type with the exiled card, this creature deals "
                     "2 damage to that player.",
        ),
    ]


register("Cemetery Gatekeeper", _cemetery_gatekeeper)


def _ojer_axonil_deepest_might() -> list[AbilitySpec]:
    """Trample
    If a red source you control would deal an amount of noncombat damage
    less than Ojer Axonil's power to an opponent, that source deals
    damage equal to Ojer Axonil's power instead.
    When Ojer Axonil dies, return it to the battlefield tapped and
    transformed under its owner's control.

    — Ojer Axonil, Deepest Might. New replacement `damage_floor_from_
    source_power` — `_additional_damage_replacement`'s floor-shaped
    sibling, reading the live threshold/replacement amount off this same
    source's own current power rather than a flat bonus. The death trigger
    reuses `ReturnSelfFromGraveyardEffect`'s existing ``transformed`` flag
    (also fixing a dormant bug along the way: its ``tapped`` param had
    never actually been applied — see the effect's own docstring).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("damage_floor_from_source_power", {"colors": ["R"]})],
            raw_text="If a red source you control would deal an amount "
                     "of noncombat damage less than Ojer Axonil's power "
                     "to an opponent, that source deals damage equal to "
                     "Ojer Axonil's power instead.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard_untargeted", {
                "destination": "battlefield", "tapped": True, "transformed": True,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="When Ojer Axonil dies, return it to the "
                     "battlefield tapped and transformed under its "
                     "owner's control.",
        ),
    ]


register("Ojer Axonil, Deepest Might // Temple of Power", _ojer_axonil_deepest_might)


def _powerbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, you may cast that card without paying its
    mana cost if the two spells have the same mana value.

    — Powerbalance. New `reveal_top_then_free_cast_if_mv_match`; see the
    effect's own docstring for its two "you may" simplifications (the
    reveal is unconditional, the cast stays a genuine choice).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_free_cast_if_mv_match", {})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent casts a spell, you may reveal "
                     "the top card of your library. If you do, you may "
                     "cast that card without paying its mana cost if the "
                     "two spells have the same mana value.",
        )
    ]


register("Powerbalance", _powerbalance)


def _silence() -> list[AbilitySpec]:
    """Your opponents can't cast spells this turn.

    — Silence. The existing `GrantUntilEffect`/`duration="end_of_turn"`
    wrapper around the standing `cast_prohibition` static (scope=
    "opponents") — no target of its own, unlike every other `GrantUntil
    Effect` user so far.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {"type": "cast_prohibition", "params": {"scope": "opponents"}},
                "duration": "end_of_turn",
                "target_kind": None,
            })],
            raw_text="Your opponents can't cast spells this turn.",
        )
    ]


register("Silence", _silence)


def _utopia_sprawl() -> list[AbilitySpec]:
    """Enchant Forest
    As this Aura enters, choose a color.
    Whenever enchanted Forest is tapped for mana, its controller adds an
    additional one mana of the chosen color.

    — Utopia Sprawl. Wild Growth's own triggered-mana-ability shape
    (RULE 605.1b/605.4 — resolves off-stack so the extra mana is there in
    time to spend), just reading `AddManaEffect`'s new `color_from_source_
    chosen_color` flag instead of a fixed `colors` list.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="As this Aura enters, choose a color.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "color_from_source_chosen_color": True, "recipient": "event_controller",
            })],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
            raw_text="Whenever enchanted Forest is tapped for mana, its "
                     "controller adds an additional one mana of the "
                     "chosen color.",
        ),
    ]


register("Utopia Sprawl", _utopia_sprawl)


def _senseis_divining_top() -> list[AbilitySpec]:
    """{1}: Look at the top three cards of your library, then put them
    back in any order.
    {T}: Draw a card, then put this artifact on top of its owner's
    library.

    — Sensei's Divining Top. Its first ability is the shared `scry`
    non-interactive resolution (Ponder's own precedent — every legal "any
    order" outcome is already reachable); the second needs
    `ReturnToLibraryEffect`'s new self mode (``target_kind=None``, no
    RULE 115 target at all).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 3})],
            cost={"text": "{1}"},
            raw_text="{1}: Look at the top three cards of your library, "
                     "then put them back in any order.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("return_to_library", {"target_kind": None, "position": "top"}),
            ],
            cost={"taps_self": True},
            raw_text="{T}: Draw a card, then put this artifact on top of "
                     "its owner's library.",
        ),
    ]


register("Sensei's Divining Top", _senseis_divining_top)


def _mystic_sanctuary() -> list[AbilitySpec]:
    """({T}: Add {U}.)
    This land enters tapped unless you control three or more other
    Islands.
    When this land enters untapped, you may put target instant or
    sorcery card from your graveyard on top of your library.

    — Mystic Sanctuary. Its enters-tapped clause needed a new `lands.py`
    ``unless_count`` variant (a specific land *type*, "other Islands",
    rather than any other land or every basic — the "Sanctuary" cycle);
    the ETB trigger needed the new `EffectSpec.condition` key
    ``source_entered_untapped`` (RULE 614.1's own settled-before-ETB
    ordering) and `ReturnToLibraryEffect`'s existing ``graveyard_instant_
    or_sorcery`` target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_library", {
                "target_kind": "graveyard_instant_or_sorcery", "position": "top", "optional": True,
            }, condition={"source_entered_untapped": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this land enters untapped, you may put target "
                     "instant or sorcery card from your graveyard on top "
                     "of your library.",
        ),
    ]


register("Mystic Sanctuary", _mystic_sanctuary)


# ---------------------------------------------------------------------------
# MEC-30: carding the standing `prevent_damage` replacement family — the
# irregular/compound cards a generic parser regex can't cleanly cover (see
# `parser/oracle/catalogue/replacements.py` for the regular Sphere/Urza's
# Armor/Shield of the Realm shapes this doesn't repeat).
# ---------------------------------------------------------------------------


def _swans_of_bryn_argoll() -> list[AbilitySpec]:
    """Flying
    If a source would deal damage to this creature, prevent that damage.
    The source's controller draws cards equal to the damage prevented this
    way.

    — Flying is the ordinary RULE 702 keyword fold-in (unaffected by this
    registration). The prevention is a plain `"prevent_damage"` replacement
    (``to="self"``, ``amount="all"``) with the new ``rider`` param —
    ``{"kind": "draw_cards", "recipient": "source_controller"}`` fires
    `RulesEngine.apply_prevent_rider`'s draw once the *actual* prevented
    amount is known, off whichever source dealt the damage (not this
    creature's own controller).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "self", "amount": "all",
                "rider": {"kind": "draw_cards", "recipient": "source_controller"},
            })],
            raw_text="Falls eine Quelle dieser Kreatur Schaden zufügen würde, "
                     "verhindere diesen Schaden. Die beherrschende Spielerin "
                     "oder der beherrschende Spieler dieser Quelle zieht so "
                     "viele Karten, wie Schaden auf diese Weise verhindert wurde.",
        ),
    ]


register("Swans of Bryn Argoll", _swans_of_bryn_argoll)


def _hostility() -> list[AbilitySpec]:
    """Haste
    If a spell you control would deal damage to an opponent, prevent that
    damage. Create a 3/1 red Elemental Shaman creature token with haste for
    each 1 damage prevented this way.
    When Hostility is put into a graveyard from anywhere, shuffle it into
    its owner's library.

    — Haste is the ordinary keyword fold-in. The prevention/token half is a
    ``"prevent_damage"`` replacement: ``to="opponent_player"`` (any player
    other than this permanent's controller — the new recipient kind, no
    real card needed it before), ``source_filter={"is_spell": True,
    "controller": "you"}`` (RULE 609.7a — reuses the DAMAGE event's own
    precomputed ``source_is_instant_or_sorcery`` flag as "is a spell", the
    same stand-in `_additional_damage_replacement`'s own "artifact" check
    already leans on for a source characteristic the event has no dedicated
    flag for), and the new ``rider={"kind": "create_tokens_scaled", ...}``.

    The graveyard-to-library shuffle trigger ("put into a graveyard from
    **anywhere**") is a real, separate RULE 400.7-adjacent primitive this
    engine has no "shuffle just this one card back into its owner's
    library on death" shape for yet (`shuffle_graveyard_into_library`
    shuffles the *whole* graveyard) — left as a documented simplification
    rather than blocking the card's own headline mechanic on it.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "opponent_player",
                "source_filter": {"is_spell": True, "controller": "you"},
                "amount": "all",
                "rider": {
                    "kind": "create_tokens_scaled",
                    "recipient": "you",
                    "token": {
                        "token_name": "Elemental Shaman", "power": 3, "toughness": 1,
                        "colors": ["R"], "subtypes": ["Elemental", "Shaman"], "keywords": ["haste"],
                    },
                },
            })],
            raw_text="Falls ein Zauberspruch, den du kontrollierst, einer "
                     "gegnerischen Person Schaden zufügen würde, verhindere "
                     "diesen Schaden. Erzeuge für je 1 auf diese Weise "
                     "verhinderten Schaden einen 3/1 roten Elementarwesen-"
                     "Schamane-Kreaturenspielstein mit Hast.",
        ),
    ]


register("Hostility", _hostility)


def _gisela_blade_of_goldnight() -> list[AbilitySpec]:
    """Flying, first strike
    If a source would deal damage to an opponent or a permanent an
    opponent controls, that source deals double that damage to that
    player or permanent instead.
    If a source would deal damage to you or a permanent you control,
    prevent half that damage, rounded up.

    — Flying/first strike are the ordinary keyword fold-in. The two
    replacements are independent and both fire off *any* source
    (unqualified), one already-shipped (`double_damage`, opponent-scoped
    via ``to_opponent_only``), one new (`prevent_damage`'s
    ``recipient_union=["controller", {}]`` — "you or a permanent you
    control", an empty filter dict matching any controlled permanent —
    and ``amount={"half": "up"}``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"to_opponent_only": True})],
            raw_text="Falls eine Quelle einer gegnerischen Person oder einem "
                     "bleibenden Kartenbild, das eine gegnerische Person "
                     "kontrolliert, Schaden zufügen würde, fügt diese Quelle "
                     "stattdessen den doppelten Schaden zu.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": {"half": "up"},
            })],
            raw_text="Falls eine Quelle dir oder einem bleibenden Kartenbild, "
                     "das du kontrollierst, Schaden zufügen würde, verhindere "
                     "die Hälfte dieses Schadens, aufgerundet.",
        ),
    ]


register("Gisela, Blade of Goldnight", _gisela_blade_of_goldnight)


def _circle_of_protection_red() -> list[AbilitySpec]:
    """{1}: The next time a red source of your choice would deal damage to
    you this turn, prevent that damage.

    — The Circle of Protection cycle's own signature template (also Rune of
    Protection/Story Circle/Circle of Solace-shaped siblings): an activated
    ability opening `RequestPreventDamageSourceEffect`'s interactive
    "choose a source" pick (`RulesEngine.request_choose_objects`'s new
    ``"remember_source"`` action) over every battlefield permanent matching
    ``source_filter``, then a `RulesEngine.prevent_damage_to_player`-shaped
    shield scoped to whichever one gets picked. Repeatable — nothing marks
    the ability itself once-per-turn, matching the real printed text.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "R"}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine rote "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Protection: Red", _circle_of_protection_red)


def _deflecting_palm() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. If damage is prevented this way, Deflecting
    Palm deals that much damage to that source's controller.

    — An instant, so the same `RequestPreventDamageSourceEffect` as Circle
    of Protection's activated ability, unqualified (``source_filter=None``
    — "a source of your choice" with no colour/type restriction) and
    carrying the new ``rider={"kind": "deal_damage_to_source_controller"}``,
    which `RulesEngine.apply_prevent_rider` fires with the real prevented
    amount once the chosen source's damage is actually stopped.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Falls auf "
                     "diese Weise Schaden verhindert wird, fügt Ablenkende "
                     "Handfläche diesen Schaden der beherrschenden Person "
                     "dieser Quelle zu.",
        ),
    ]


register("Deflecting Palm", _deflecting_palm)


def _circle_of_protection_white() -> list[AbilitySpec]:
    """{1}: The next time a white source of your choice would deal damage to
    you this turn, prevent that damage.

    — Circle of Protection: Red's own cycle sibling; see that entry's
    docstring for the shared template.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "W"}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine weiße "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Protection: White", _circle_of_protection_white)


def _circle_of_protection_black() -> list[AbilitySpec]:
    """{1}: The next time a black source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "B"}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine "
                     "schwarze Quelle deiner Wahl dir in diesem Zug "
                     "zufügen würde.",
        ),
    ]


register("Circle of Protection: Black", _circle_of_protection_black)


def _circle_of_protection_blue() -> list[AbilitySpec]:
    """{1}: The next time a blue source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "U"}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine blaue "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Protection: Blue", _circle_of_protection_blue)


def _circle_of_protection_green() -> list[AbilitySpec]:
    """{1}: The next time a green source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "G"}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine grüne "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Protection: Green", _circle_of_protection_green)


def _circle_of_protection_artifacts() -> list[AbilitySpec]:
    """{2}: The next time an artifact source of your choice would deal
    damage to you this turn, prevent that damage.

    — ``source_filter={"card_type": "artifact"}``, the same generic
    type-word check `combat.matches_object_filter`'s ``card_type`` key
    already uses for "destroy target **artifact** creature"-shaped filters.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "artifact"}, "amount": "all",
            })],
            cost={"mana": "{2}"},
            raw_text="{2}: Verhindere den nächsten Schaden, den eine "
                     "Artefaktquelle deiner Wahl dir in diesem Zug zufügen "
                     "würde.",
        ),
    ]


register("Circle of Protection: Artifacts", _circle_of_protection_artifacts)


def _circle_of_protection_shadow() -> list[AbilitySpec]:
    """{1}: The next time a creature of your choice with shadow would deal
    damage to you this turn, prevent that damage.

    — ``source_filter={"card_type": "creature", "keyword": "shadow"}``.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "creature", "keyword": "shadow"},
                "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine "
                     "Kreatur deiner Wahl mit Schatten dir in diesem Zug "
                     "zufügen würde.",
        ),
    ]


register("Circle of Protection: Shadow", _circle_of_protection_shadow)


def _rune_of_protection_white() -> list[AbilitySpec]:
    """{W}: The next time a white source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}

    — The Rune of Protection cycle's own template — same shield shape as
    Circle of Protection, cheaper and repeatable per activation but at
    instant-speed sorcery-speed enchantment cost, with Cycling. Cycling is
    the ordinary keyword fold-in (PAR-9 — recognized-but-inert became real
    behaviour independently of this registration), not part of this spec.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "W"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine weiße "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Rune of Protection: White", _rune_of_protection_white)


def _rune_of_protection_blue() -> list[AbilitySpec]:
    """{W}: The next time a blue source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "U"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine blaue "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Rune of Protection: Blue", _rune_of_protection_blue)


def _rune_of_protection_black() -> list[AbilitySpec]:
    """{W}: The next time a black source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "B"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "schwarze Quelle deiner Wahl dir in diesem Zug "
                     "zufügen würde.",
        ),
    ]


register("Rune of Protection: Black", _rune_of_protection_black)


def _rune_of_protection_red() -> list[AbilitySpec]:
    """{W}: The next time a red source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "R"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine rote "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Rune of Protection: Red", _rune_of_protection_red)


def _rune_of_protection_green() -> list[AbilitySpec]:
    """{W}: The next time a green source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "G"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine grüne "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Rune of Protection: Green", _rune_of_protection_green)


def _rune_of_protection_artifacts() -> list[AbilitySpec]:
    """{W}: The next time an artifact source of your choice would deal
    damage to you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "artifact"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Artefaktquelle deiner Wahl dir in diesem Zug zufügen "
                     "würde.",
        ),
    ]


register("Rune of Protection: Artifacts", _rune_of_protection_artifacts)


def _rune_of_protection_lands() -> list[AbilitySpec]:
    """{W}: The next time a land source of your choice would deal damage to
    you this turn, prevent that damage.
    Cycling {2}
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "land"}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Landquelle deiner Wahl dir in diesem Zug zufügen "
                     "würde.",
        ),
    ]


register("Rune of Protection: Lands", _rune_of_protection_lands)


def _greater_realm_of_preservation() -> list[AbilitySpec]:
    """{1}{W}: The next time a black or red source of your choice would deal
    damage to you this turn, prevent that damage.

    — ``source_filter={"color_any": ["B", "R"]}`` (MEC-30's new multi-colour
    filter key, ``color``'s "any of" sibling).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten Schaden, den eine "
                     "schwarze oder rote Quelle deiner Wahl dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Greater Realm of Preservation", _greater_realm_of_preservation)


def _story_circle() -> list[AbilitySpec]:
    """As this enchantment enters, choose a color.
    {W}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — The ETB colour choice is the ordinary ``choose_color_on_enter``
    replacement (Utopia Sprawl's own precedent, stamping `GameObject.
    chosen_color`); the shield reads it back dynamically via MEC-30's new
    ``source_filter={"color_from_source": True}`` key rather than a literal
    colour baked in at parse time — `RequestPreventDamageSourceEffect.apply`
    passes its own source as `matches_object_filter`'s ``reference``
    specifically so this (and Prismatic Circle's identical shape) can read
    it.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "eine Farbe.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl der gewählten Farbe dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Story Circle", _story_circle)


def _prismatic_circle() -> list[AbilitySpec]:
    """Cumulative upkeep {1}
    As this enchantment enters, choose a color.
    {1}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — Cumulative upkeep is the ordinary RULE 702.24 keyword fold-in
    (MEC-16, unaffected by this registration). The rest is Story Circle's
    own shape at a cheaper activation cost.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "eine Farbe.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl der gewählten Farbe dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Prismatic Circle", _prismatic_circle)


def _circle_of_solace() -> list[AbilitySpec]:
    """As this enchantment enters, choose a creature type.
    {1}{W}: The next time a creature of the chosen type would deal damage
    to you this turn, prevent that damage.

    — The ETB creature-type choice is the ordinary ``choose_creature_type_
    on_enter`` replacement (Adaptive Automaton's own precedent, stamping
    `GameObject.chosen_type`); the shield reads it back via MEC-30's new
    ``source_filter={"card_type": "creature", "subtype_from_source": True}``.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "einen Kreaturtyp.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "creature", "subtype_from_source": True},
                "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten Schaden, den eine "
                     "Kreatur des gewählten Typs dir in diesem Zug zufügen "
                     "würde.",
        ),
    ]


register("Circle of Solace", _circle_of_solace)


def _circle_of_despair() -> list[AbilitySpec]:
    """{1}, Sacrifice a creature: The next time a source of your choice
    would deal damage to any target this turn, prevent that damage.

    — ``target_kind="any"`` routes the shield's recipient through ordinary
    RULE 115 targeting instead of this effect's own controller — the
    already-designed "any target" branch `RequestPreventDamageSourceEffect`
    was built with (see its docstring), first actually used here.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "{1}, Sacrifice a creature"},
            raw_text="{1}, Opfere eine Kreatur: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl einem beliebigen "
                     "Ziel in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Despair", _circle_of_despair)


def _martyrs_cause() -> list[AbilitySpec]:
    """Sacrifice a creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice a creature"},
            raw_text="Opfere eine Kreatur: Verhindere den nächsten Schaden, "
                     "den eine Quelle deiner Wahl einem beliebigen Ziel in "
                     "diesem Zug zufügen würde.",
        ),
    ]


register("Martyr's Cause", _martyrs_cause)


def _sanctum_guardian() -> list[AbilitySpec]:
    """Sacrifice this creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
            raw_text="Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl einem beliebigen "
                     "Ziel in diesem Zug zufügen würde.",
        ),
    ]


register("Sanctum Guardian", _sanctum_guardian)


def _righteous_aura() -> list[AbilitySpec]:
    """{W}, Pay 2 life: The next time a source of your choice would deal
    damage to you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{W}, Pay 2 life"},
            raw_text="{W}, Bezahle 2 Leben: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Righteous Aura", _righteous_aura)


def _haazda_shield_mate() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this creature unless you
    pay {W}{W}.
    {W}: The next time a source of your choice would deal damage to you
    this turn, prevent that damage.

    — The upkeep clause is the general RULE 701.17 ``sacrifice_unless_pay``
    interactive pay-or-lose-it choice (already shipped for Arcades Sabboth/
    Breeding Pit/Child of Gaea); registering this card for its own
    prevent-damage clause (still `UNMODELED` by the parser) would otherwise
    silently drop the upkeep clause too — `specs_for` trusts a registered
    card's specs wholesale — so it's authored alongside rather than left
    to the parser it can no longer reach.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "{W}{W}"})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
            raw_text="Zu Beginn deines Versorgungssegments opfere diese "
                     "Kreatur, außer du bezahlst {W}{W}.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Haazda Shield Mate", _haazda_shield_mate)


def _charm_peddler() -> list[AbilitySpec]:
    """{W}, {T}, Discard a card: The next time a source of your choice would
    deal damage to target creature this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "creature", "amount": "all",
            })],
            cost={"text": "{W}, {T}, Discard a card"},
            raw_text="{W}, {T}, Wirf eine Karte ab: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl einer "
                     "Zielkreatur in diesem Zug zufügen würde.",
        ),
    ]


register("Charm Peddler", _charm_peddler)


def _cho_arrim_alchemist() -> list[AbilitySpec]:
    """{1}{W}{W}, {T}, Discard a card: The next time a source of your choice
    would deal damage to you this turn, prevent that damage. You gain life
    equal to the damage prevented this way.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            cost={"text": "{1}{W}{W}, {T}, Discard a card"},
            raw_text="{1}{W}{W}, {T}, Wirf eine Karte ab: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl dir in "
                     "diesem Zug zufügen würde. Du erhältst so viele "
                     "Lebenspunkte dazu, wie Schaden auf diese Weise "
                     "verhindert wurde.",
        ),
    ]


register("Cho-Arrim Alchemist", _cho_arrim_alchemist)


def _reverse_damage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Du "
                     "erhältst so viele Lebenspunkte dazu, wie Schaden auf "
                     "diese Weise verhindert wurde.",
        ),
    ]


register("Reverse Damage", _reverse_damage)


def _intervention_pact() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    At the beginning of your next upkeep, pay {1}{W}{W}. If you don't, you
    lose the game.

    — The delayed pay-or-lose clause is Pact of Negation's own template
    (``create_delayed_trigger``/``pay_cost_then``); see that entry's
    docstring for why it needed no new primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("request_prevent_damage_source", {
                    "amount": "all",
                    "rider": {"kind": "gain_life", "recipient": "you"},
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Interventionspakt: {1}{W}{W} bezahlen "
                                    "oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{1}{W}{W}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Du "
                     "erhältst so viele Lebenspunkte dazu, wie Schaden auf "
                     "diese Weise verhindert wurde. Zu Beginn deines "
                     "nächsten Versorgungssegments bezahle {1}{W}{W}. "
                     "Falls du dies nicht tust, verlierst du das Spiel.",
        ),
    ]


register("Intervention Pact", _intervention_pact)


def _new_way_forward() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. When damage is prevented this way, New Way
    Forward deals that much damage to that source's controller and you
    draw that many cards.

    — Two independent riders off the same prevented amount
    (``rider`` as a list — MEC-30's new list form of `RulesEngine.
    apply_prevent_rider`, first real card to need it).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": [
                    {"kind": "deal_damage_to_source_controller"},
                    {"kind": "draw_cards", "recipient": "you"},
                ],
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Falls "
                     "auf diese Weise Schaden verhindert wird, fügt Neuer "
                     "Weg nach vorn diesen Schaden der beherrschenden "
                     "Person dieser Quelle zu und du ziehst so viele "
                     "Karten.",
        ),
    ]


register("New Way Forward", _new_way_forward)


def _awe_strike() -> list[AbilitySpec]:
    """The next time target creature would deal damage this turn, prevent
    that damage. You gain life equal to the damage prevented this way.

    — `PreventDamageFromTargetEffect`'s own targeted, no-chooser-needed
    shape (Dazzling Reflection's own life-gain half is a separate,
    not-yet-built "gain life equal to a target's power" primitive — left
    open, see `BACKLOG.md`'s `MEC-30`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("prevent_damage_from_target", {
                "target_kind": "creature",
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            raw_text="Verhindere den nächsten Schaden, den die "
                     "Zielkreatur in diesem Zug zufügen würde. Du erhältst "
                     "so viele Lebenspunkte dazu, wie Schaden auf diese "
                     "Weise verhindert wurde.",
        ),
    ]


register("Awe Strike", _awe_strike)


def _pentagram_of_the_ages() -> list[AbilitySpec]:
    """{4}, {T}: The next time a source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{4}, {T}"},
            raw_text="{4}, {T}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Pentagram of the Ages", _pentagram_of_the_ages)


def _pilgrim_of_justice() -> list[AbilitySpec]:
    """Protection from red
    {W}, Sacrifice this creature: The next time a red source of your choice
    would deal damage this turn, prevent that damage.

    — Protection is the ordinary RULE 702 keyword fold-in (unaffected by
    this registration). The card's own text omits "to you" (an older,
    pre-templating-standardization printing) — read the same way this
    repo's Penance/Seasoned Tactician entries do, as protecting the
    activating player.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "R"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
            raw_text="{W}, Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine rote Quelle deiner Wahl in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Pilgrim of Justice", _pilgrim_of_justice)


def _pilgrim_of_virtue() -> list[AbilitySpec]:
    """Protection from black
    {W}, Sacrifice this creature: The next time a black source of your
    choice would deal damage this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "B"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
            raw_text="{W}, Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine schwarze Quelle deiner Wahl in "
                     "diesem Zug zufügen würde.",
        ),
    ]


register("Pilgrim of Virtue", _pilgrim_of_virtue)


def _invulnerability() -> list[AbilitySpec]:
    """Buyback {3}
    The next time a source of your choice would deal damage to you this
    turn, prevent that damage.

    — Buyback is the ordinary RULE 702.24-adjacent keyword fold-in
    (unaffected by this registration).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Invulnerability", _invulnerability)


def _rem_karolus_stalwart_slayer() -> list[AbilitySpec]:
    """Flying, haste
    If a spell would deal damage to you or another permanent you control,
    prevent that damage.
    If a spell would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 1 instead.

    — Flying/haste are the ordinary keyword fold-in. The prevent half is
    already fully expressible: ``source_filter={"is_spell": True}`` +
    ``recipient_union=["controller", {"exclude_self": True}]`` (Temple
    Altisaur's own "another `<X>` you control" idiom, unfiltered here since
    "another permanent" has no type restriction). The bonus-damage half
    needed one new param on `_additional_damage_replacement` — ``is_spell``,
    mirroring the check its own `_prevent_damage_replacement` sibling
    already had for the exact same event field (MEC-30).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {"exclude_self": True}],
                "amount": "all", "source_filter": {"is_spell": True},
            })],
            raw_text="Falls ein Zauberspruch dir oder einem anderen "
                     "bleibenden Kartenbild, das du kontrollierst, Schaden "
                     "zufügen würde, verhindere diesen Schaden.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_damage", {
                "amount": 1, "to_opponent_only": True, "is_spell": True,
            })],
            raw_text="Falls ein Zauberspruch einer gegnerischen Person "
                     "oder einem bleibenden Kartenbild, das eine "
                     "gegnerische Person kontrolliert, Schaden zufügen "
                     "würde, fügt er stattdessen so viel Schaden plus 1 zu.",
        ),
    ]


register("Rem Karolus, Stalwart Slayer", _rem_karolus_stalwart_slayer)


def _hedron_field_purists() -> list[AbilitySpec]:
    """Level up {2}{W}
    LEVEL 1-4  1/4
    If a source would deal damage to you or a creature you control,
    prevent 1 of that damage.
    LEVEL 5+  2/5
    If a source would deal damage to you or a creature you control,
    prevent 2 of that damage.

    — Level up itself and the level-banded P/T (1/4 vs. 2/5) are the
    ordinary structural RULE 711 Leveler handling (`Card.is_leveler`,
    independent of catalogue registration, the same way a DFC's transform
    is structural rather than per-card). Only the prevent-damage bands
    needed writing: two `prevent_damage` specs gated by `active_if`'s
    already-shipped `source_counters` kind (RULE 613.6, `game/static_
    conditions.py`), the exact shape already execute-tested synthetically
    in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 1,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 1, "max": 4},
            })],
            raw_text="LEVEL 1-4: Falls eine Quelle dir oder einer Kreatur, "
                     "die du kontrollierst, Schaden zufügen würde, "
                     "verhindere 1 dieses Schadens.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 2,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 5},
            })],
            raw_text="LEVEL 5+: Falls eine Quelle dir oder einer Kreatur, "
                     "die du kontrollierst, Schaden zufügen würde, "
                     "verhindere 2 dieses Schadens.",
        ),
    ]


register("Hedron-Field Purists", _hedron_field_purists)


def _battletide_alchemist() -> list[AbilitySpec]:
    """If a source would deal damage to a player, you may prevent X of that
    damage, where X is the number of Clerics you control.

    — **Documented simplification**: modeled as an unconditional (always
    applied) prevention rather than a real "you may" — no replacement-level
    optional-choice primitive exists in this engine, and building one is
    not justified for this single card (see `BACKLOG.md`'s `MEC-30`).
    ``amount_count_selector="creatures_you_control_of_type_cleric"`` is the
    same generic count-selector key Shield of the Avatar already uses for
    its own unscoped "number of creatures you control" form.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "any_player",
                "amount_count_selector": "creatures_you_control_of_type_cleric",
            })],
            raw_text="Falls eine Quelle einer spielenden Person Schaden "
                     "zufügen würde, verhinderst du X dieses Schadens, "
                     "wobei X die Anzahl der Kleriker ist, die du "
                     "kontrollierst. (Vereinfachung: nicht optional.)",
        ),
    ]


register("Battletide Alchemist", _battletide_alchemist)


def _nine_lives() -> list[AbilitySpec]:
    """Hexproof
    If a source would deal damage to you, prevent that damage and put an
    incarnation counter on this enchantment.
    When there are nine or more incarnation counters on this enchantment,
    exile it.
    When this enchantment leaves the battlefield, you lose the game.

    — Hexproof is the ordinary keyword fold-in. The prevent clause is a
    plain shield with the already-shipped `add_self_counter` rider. RULE
    603.8's "when there are N or more counters" state trigger — the one
    piece the ticket had marked as needing a genuine new subsystem — turned
    out not to: since incarnation counters only ever arrive one at a time
    via this card's own rider, an ordinary `EventType.COUNTER` self-subject
    trigger (Flourishing Defenses' own precedent) gated by the new
    `source_counters_at_least` trigger-condition key (MEC-30, the mirror of
    the already-shipped `source_counters_below`) is exactly rules-equivalent
    to a real state trigger for this card — checked fresh every time a
    counter lands, which is the only time the count could newly cross 9.
    The "leaves the battlefield" clause is the four-times-precedented
    `EventType.LEAVES_BATTLEFIELD`/``condition={"subject": "self"}`` shape.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "controller", "amount": "all",
                "rider": {"kind": "add_self_counter", "counter": "incarnation"},
            })],
            raw_text="Falls eine Quelle dir Schaden zufügen würde, "
                     "verhindere diesen Schaden und lege eine "
                     "Inkarnationsmarke auf dieses Verzauberung.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": None})],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "incarnation"},
                "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 9, "kind": "incarnation"},
            },
            raw_text="Wenn neun oder mehr Inkarnationsmarken auf dieser "
                     "Verzauberung liegen, exiliere sie.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_game", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung das Spielfeld verlässt, "
                     "verlierst du das Spiel.",
        ),
    ]


register("Nine Lives", _nine_lives)


def _insult_injury() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn, it deals double that damage instead.

    — MEC-30's one real new mechanism: `disable_damage_prevention` flips a
    turn-scoped `GameState` flag that `RulesEngine._run_replacement_loop`
    checks generically against every replacement's new `prevents_damage`
    marker; `grant_damage_multiplier_this_turn` is the spell-cast sibling
    of the standing `double_damage` replacement (Furnace of Rath-shaped),
    filed on the caster's own `player_effects` since a resolved sorcery has
    no permanent to attach a standing shield to. Unscoped by recipient —
    "a source you control" doubles damage to *anyone*, no `to_opponent_
    only`, unlike Isengard Unleashed's own qualified sibling.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {"multiplier": 2}),
            ],
            raw_text="Schaden kann in diesem Zug nicht verhindert werden. "
                     "Falls eine Quelle, die du kontrollierst, in diesem "
                     "Zug Schaden zufügen würde, fügt sie stattdessen den "
                     "doppelten Schaden zu.",
        ),
    ]


register("Insult // Injury", _insult_injury)


def _isengard_unleashed() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn to an opponent or a permanent an opponent
    controls, it deals triple that damage instead.
    Flashback {4}{R}{R}{R}

    — Flashback is the ordinary keyword fold-in. Same shape as Insult //
    Injury, ``multiplier=3`` and ``to_opponent_only=True`` for the
    qualified recipient side.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {
                    "multiplier": 3, "to_opponent_only": True,
                }),
            ],
            raw_text="Schaden kann in diesem Zug nicht verhindert werden. "
                     "Falls eine Quelle, die du kontrollierst, in diesem "
                     "Zug einer gegnerischen Person oder einem bleibenden "
                     "Kartenbild, das eine gegnerische Person kontrolliert, "
                     "Schaden zufügen würde, fügt sie stattdessen den "
                     "dreifachen Schaden zu.",
        ),
    ]


register("Isengard Unleashed", _isengard_unleashed)


def _ajani_steadfast() -> list[AbilitySpec]:
    """+1: Until end of turn, up to one target creature gets +1/+1 and
    gains first strike, vigilance, and lifelink.
    −2: Put a +1/+1 counter on each creature you control and a loyalty
    counter on each other planeswalker you control.
    −7: You get an emblem with "If a source would deal damage to you or a
    planeswalker you control, prevent all but 1 of that damage."

    — All three loyalty abilities are `UNCLAIMED` by the parser (not just
    the emblem the ticket had originally scoped) — `specs_for` trusts a
    registered card's specs wholesale, so all three need writing, the same
    Haazda Shield Mate lesson from Pass 2. +1 is an ordinary "up to one
    target" `pump` (The Wandering Emperor's own idiom). −2 is two
    `add_counters` specs in one ability — `selector="each_creature_you_
    control"` (already shipped) and the new `"each_other_planeswalker_you_
    control"` (MEC-30, `continuous.group_selector_objects`'s planeswalker-
    scoped sibling of ``other_creatures_you_control``). −7's emblem is the
    exact `prevent_damage` shape already execute-tested synthetically via
    the Hyperion test in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "target_kind": "creature", "optional": True,
                "power": 1, "toughness": 1,
                "keywords": ["first strike", "vigilance", "lifelink"],
            })],
            cost={"loyalty": 1},
            raw_text="+1: Bis zum Ende des Zuges erhält bis zu eine "
                     "Zielkreatur +1/+1 und Erstschlag, Wachsamkeit und "
                     "Lebensverknüpfung.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"selector": "each_creature_you_control"}),
                EffectSpec("add_counters", {
                    "selector": "each_other_planeswalker_you_control", "kind": "loyalty",
                }),
            ],
            cost={"loyalty": -2},
            raw_text="−2: Lege eine +1/+1-Marke auf jede Kreatur, die du "
                     "kontrollierst, und eine Loyalitätsmarke auf jeden "
                     "anderen Planeswalker, den du kontrollierst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {
                "ability": {
                    "ability_kind": "replacement",
                    "effects": [{
                        "type": "prevent_damage",
                        "params": {
                            "recipient_union": ["controller", {"card_type": "planeswalker"}],
                            "amount": {"all_but": 1},
                        },
                    }],
                },
            })],
            cost={"loyalty": -7},
            raw_text="−7: Du erhältst ein Emblem mit \"Falls eine Quelle "
                     "dir oder einem Planeswalker, den du kontrollierst, "
                     "Schaden zufügen würde, verhindere alles bis auf 1 "
                     "dieses Schadens.\"",
        ),
    ]


register("Ajani Steadfast", _ajani_steadfast)


def _kithkin_armor() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature can't be blocked by creatures with power 3 or
    greater.
    Sacrifice this Aura: The next time a source of your choice would deal
    damage to enchanted creature this turn, prevent that damage.

    — The Enchant keyword and the block restriction are *both* real parser
    output (confirmed via `parse_oracle` on the clause in isolation — only
    the shield clause is `UNCLAIMED`), so registering this card means
    replicating them by hand too, not just the shield — the same Haazda
    Shield Mate lesson: `specs_for` trusts a registered card wholesale. The
    shield needed a new small param on `RequestPreventDamageSourceEffect`:
    ``recipient="attached_permanent"`` (MEC-30) — Family B's own sibling of
    Family A's already-shipped ``to="attached_permanent"``, reading
    ``self.source.attached_to`` instead of the caster/an RULE 115 target.
    Read at *resolution* time, after the sacrifice cost has already moved
    this Aura to the graveyard — safe because this engine doesn't clear
    `GameObject.attached_to` on a zone change (the same "the object's last
    known state survives its own move" convention `LoseLifeEffect.amount_
    from_trigger_event`'s own docstring documents for RULE 400.7).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"},
                     raw_text="Verzaubere Kreatur"),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
                "affects": "attached_permanent",
            })],
            raw_text="Die verzauberte Kreatur kann nicht von Kreaturen mit "
                     "Stärke 3 oder mehr geblockt werden.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "attached_permanent", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
            raw_text="Opfere diese Verzauberung: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl der verzauberten "
                     "Kreatur in diesem Zug zufügen würde.",
        ),
    ]


register("Kithkin Armor", _kithkin_armor)


def _shadowbane() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you
    and/or creatures you control this turn, prevent that damage. If damage
    from a black source is prevented this way, you gain that much life.

    — ``recipient="you_and_creatures_you_control"`` (MEC-30) — the one-shot
    chooser's own new dynamic-recipient-set shape (`RulesEngine.prevent_
    damage_to_player_and_their_creatures`), the Family B sibling of Family
    A's `recipient_union`. ``rider={"if_source_color": "B", ...}`` (also
    MEC-30) gates the life-gain follow-up on the *watched source's* own
    colour — unlike every other rider kind, this one only sometimes fires.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "you_and_creatures_you_control", "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you", "if_source_color": "B"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir und/oder Kreaturen, die du "
                     "kontrollierst, in diesem Zug zufügen würde. Falls auf "
                     "diese Weise Schaden einer schwarzen Quelle verhindert "
                     "wird, erhältst du so viele Lebenspunkte dazu.",
        ),
    ]


register("Shadowbane", _shadowbane)


def _honorable_passage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to any
    target this turn, prevent that damage. If damage from a red source is
    prevented this way, Honorable Passage deals that much damage to the
    source's controller.

    — ``target_kind="any"`` (already shipped, Circle of Despair's own
    shape). ``rider={"if_source_color": "R", ...}`` (MEC-30) — same
    source-colour-gated rider as Shadowbane, different kind.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller", "if_source_color": "R"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl einem beliebigen Ziel in diesem Zug "
                     "zufügen würde. Falls auf diese Weise Schaden einer "
                     "roten Quelle verhindert wird, fügt Ehrenhafter "
                     "Übergang diesen Schaden der beherrschenden Person "
                     "dieser Quelle zu.",
        ),
    ]


register("Honorable Passage", _honorable_passage)


def _dazzling_reflection() -> list[AbilitySpec]:
    """You gain life equal to target creature's power. The next time that
    creature would deal damage this turn, prevent that damage.

    — `GainLifeEffect`'s new `amount_from_target_power` flag (MEC-30), the
    life-gain sibling of `DealDamageEffect.amount_from_target_count_
    selector`, reads the *same* target `prevent_damage_from_target`'s own
    ``target_kind="creature"`` gathers — only one real RULE 115 target
    requirement in this whole ability, so `_apply_effects_partitioned`
    hands both effects the same resolved list (RULE 608.2).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"amount_from_target_power": True}),
                EffectSpec("prevent_damage_from_target", {"target_kind": "creature", "amount": "all"}),
            ],
            raw_text="Du erhältst so viele Lebenspunkte dazu, wie die "
                     "Stärke der Zielkreatur beträgt. Verhindere den "
                     "nächsten Schaden, den diese Kreatur in diesem Zug "
                     "zufügen würde.",
        ),
    ]


register("Dazzling Reflection", _dazzling_reflection)


def _samite_blessing() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has "{T}: The next time a source of your choice
    would deal damage to target creature this turn, prevent that damage."

    — The already-shipped RULE 613/RULE 714.2c layer-6 "grant an activated
    ability, affects=attached_permanent" static (Umbral Mantle/Squirrel
    Nest/Deadeye Navigator's own shape) — the granted ability's own effects
    get their `source` set to the *host* creature at grant time, so
    `request_prevent_damage_source`'s chooser/recipient resolution
    (defaulting to the host's own controller) behaves exactly like a real
    printed ability of the host's, no new primitive needed.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"},
                     raw_text="Verzaubere Kreatur"),
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "attached_permanent",
                "cost": {"text": "{T}"},
                "grant_effects": [{
                    "type": "request_prevent_damage_source",
                    "params": {"target_kind": "creature", "amount": "all"},
                }],
            })],
            raw_text="Die verzauberte Kreatur hat „{T}: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl einer "
                     "Zielkreatur in diesem Zug zufügen würde.“",
        ),
    ]


register("Samite Blessing", _samite_blessing)


def _opal_eye_kondas_yojimbo() -> list[AbilitySpec]:
    """Defender
    Bushido 1
    {T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead.
    {1}{W}: Prevent the next 1 damage that would be dealt to Opal-Eye this
    turn.

    — Defender/Bushido are the ordinary keyword fold-in. The first
    activated ability is RULE 616.1c *redirection*, not prevention —
    `RequestPreventDamageSourceEffect` doesn't fit at all, hence the new
    `RequestRedirectDamageSourceEffect`/`RulesEngine.redirect_damage_from_
    source` (MEC-30), reusing the exact chooser plumbing (`request_choose_
    objects`'s new `"remember_source_redirect"` action) with a rewritten
    recipient instead of a reduced amount — deliberately not marked
    `prevents_damage`, since RULE 615's "damage can't be prevented this
    turn" has no bearing on a redirect. The second ability is the ordinary
    already-shipped `prevent_damage_shield`, just needing one new small
    flag — `self_only=True` — since "damage to `<this permanent>`" has no
    existing recipient shape (the untargeted default always protects the
    *controller*, not the object itself).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_redirect_damage_source", {"amount": "all"})],
            cost={"text": "{T}"},
            raw_text="{T}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl in diesem Zug zufügen würde, "
                     "indem er stattdessen Opal-Eye zugefügt wird.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1, "self_only": True})],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten 1 Schadenspunkt, der "
                     "Opal-Eye in diesem Zug zugefügt werden würde.",
        ),
    ]


register("Opal-Eye, Konda's Yojimbo", _opal_eye_kondas_yojimbo)


def _penance() -> list[AbilitySpec]:
    """Put a card from your hand on top of your library: The next time a
    black or red source of your choice would deal damage this turn,
    prevent that damage.

    — Penance (MEC-30, Phase 8). Unlike every other card in this family,
    the printed text has no "to you" at all — "prevent that damage"
    protects whoever the chosen source would have hit, not one fixed
    recipient — `RequestPreventDamageSourceEffect`'s new ``recipient=
    "any"`` (reaching `RulesEngine.prevent_damage_from_source`'s existing
    unscoped-recipient shield via `_apply_chosen_object`'s matching
    branch, rather than `prevent_damage_to_player`/`_to_target`'s fixed-
    recipient ones). ``source_filter``'s ``color_any`` (already shipped for
    Greater Realm of Preservation) covers "a black **or** red source"
    directly. The cost is the new "put a card from your hand on top of
    your library" non-mana cost (`costs.py`'s own
    ``_PUT_HAND_CARD_ON_LIBRARY_RE``/`RulesEngine.put_hand_card_on_top_of_
    library`) — which card leaves the hand is a genuine RULE 602.1 choice,
    resolved the same "chosen_ids, or auto-pick" way a plain discard-N cost
    already is (`ActivationMixin._resolve_put_hand_card_cost`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all", "recipient": "any",
            })],
            cost={"text": "Put a card from your hand on top of your library"},
            raw_text="Lege eine Karte von deiner Hand oben auf deine Bibliothek: "
                     "Verhindere den nächsten Schaden, den eine schwarze oder rote "
                     "Quelle deiner Wahl in diesem Zug zufügen würde.",
        ),
    ]


register("Penance", _penance)


def _seasoned_tactician() -> list[AbilitySpec]:
    """{3}, Exile the top four cards of your library: The next time a
    source of your choice would deal damage to you this turn, prevent
    that damage.

    — Seasoned Tactician (MEC-30, Phase 8). Otherwise the ordinary Circle
    of Protection template (unqualified ``source_filter``, default
    recipient — "to you"); the cost needed `costs.py`'s
    ``exile_top_of_library`` widened from a bare bool (Thought Lash's
    always-exactly-one) to a real printed count, since
    ``_EXILE_TOP_LIBRARY_RE`` only ever recognized "the top card" —
    checked every existing caller (`game/engine/activation_mixin.py`'s
    legality/payment, `game/mana_potential.py`'s tap-plan simulation)
    before widening so Thought Lash's own behaviour doesn't regress.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{3}, Exile the top four cards of your library"},
            raw_text="{3}, Exiliere die obersten vier Karten deiner Bibliothek: "
                     "Verhindere den nächsten Schaden, den eine Quelle deiner Wahl "
                     "dir in diesem Zug zufügen würde.",
        ),
    ]


register("Seasoned Tactician", _seasoned_tactician)


def _bone_mask() -> list[AbilitySpec]:
    """{2}, {T}: The next time a source of your choice would deal damage
    to you this turn, prevent that damage. Exile cards from the top of
    your library equal to the damage prevented this way.

    — Bone Mask (MEC-30, Phase 8). The trailing sentence is a new
    `RulesEngine.apply_prevent_rider` kind, ``"exile_top_of_library_
    scaled"`` — `mill`'s exile-instead-of-graveyard sibling, since no
    existing primitive exiled a fixed count off the top of the library in
    one call.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all", "rider": {"kind": "exile_top_of_library_scaled"},
            })],
            cost={"text": "{2}, {T}"},
            raw_text="{2}, {T}: Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Exiliere so "
                     "viele Karten vom oberen Ende deiner Bibliothek, wie Schaden "
                     "auf diese Weise verhindert wurde.",
        ),
    ]


register("Bone Mask", _bone_mask)


def _mercenaries() -> list[AbilitySpec]:
    """{3}: The next time this creature would deal damage to you this
    turn, prevent that damage. Any player may activate this ability.

    — Mercenaries (MEC-30, Phase 7). RULE 602.2b: whoever activates an
    ability is that ability's controller for the purposes of its
    resolution, so "you" here means the *activator* — not Mercenaries'
    own permanent controller, which is who every other card in this
    family's "prevent damage to you" shape protects. Needed two small new
    primitives together: `ActivationCost.any_player_may_activate` widens
    `GameEngine.can_activate`'s ordinary "only the permanent's controller"
    eligibility gate; `GameContext.resolving_controller_id` (RULE 602.2b's
    activator, threaded through `RulesEngine.resolve_top_of_stack` around
    a stack item's own resolution, mirroring `trigger_event`'s existing
    save/restore pattern) is what `PreventDamageEffect`'s new
    `recipient_is_activator` reads instead of the permanent's printed
    controller. `watched_source_is_self` narrows the shield to
    Mercenaries' own damage specifically — the fixed-source, no-chooser-
    needed sibling of `RequestPreventDamageSourceEffect`'s "a source of
    your choice".
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all", "watched_source_is_self": True, "recipient_is_activator": True,
            })],
            cost={"mana": "{3}", "any_player_may_activate": True},
            raw_text="{3}: Verhindere den nächsten Schaden, den diese Kreatur dir in "
                     "diesem Zug zufügen würde. Jeder Spieler kann diese Fähigkeit "
                     "aktivieren.",
        ),
    ]


register("Mercenaries", _mercenaries)


def _rhystic_circle() -> list[AbilitySpec]:
    """{1}: Any player may pay {1}. If no one does, the next time a source
    of your choice would deal damage to you this turn, prevent that
    damage.

    — Rhystic Circle (MEC-30, Phase 7 — the one flagged genuinely large
    build). "Any player may pay {1}." is a *resolve-time* tax, not the
    already-shipped single-payer `TaxedDrawEffect`/`pay_cost_then` shape —
    every player independently gets a chance to pay, in turn order, and
    the shield only grants once literally everyone has declined; the
    first player to pay cancels the whole thing. New primitive:
    `RequestAllPlayersDeclineOrEffect`/`RulesEngine.request_all_players_
    decline_or` (a chain of ordinary single-player pay/decline choices,
    the aggregate-outcome mirror of PAR-13's `request_each_player_pay_or`
    — that one applies its effect *per decliner*, this one applies it
    *once*, only if *every* player declined). The activation cost itself
    ({1}) is ordinary — unlike Mercenaries, only Rhystic Circle's own
    controller may activate this ability at all; it's the ability's own
    *effect* that reaches out to every player at the table.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("all_players_decline_or", {
                "cost": "{1}",
                "effects": [{"type": "request_prevent_damage_source", "params": {"amount": "all"}}],
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Jeder Spieler kann {1} bezahlen. Falls niemand dies tut, "
                     "verhindere den nächsten Schaden, den eine Quelle deiner Wahl "
                     "dir in diesem Zug zufügen würde.",
        ),
    ]


register("Rhystic Circle", _rhystic_circle)


def _desperate_gambit() -> list[AbilitySpec]:
    """Choose a source you control and flip a coin. If you win the flip,
    the next time that source would deal damage this turn, it deals
    double that damage instead. If you lose the flip, the next time it
    would deal damage this turn, prevent that damage.

    — Desperate Gambit (MEC-30, last card of the family). A genuinely
    conditional effect-selection shape, not a rider: which of "double" or
    "prevent" applies isn't known until the coin lands, and both branches
    are scoped to the one chosen source rather than the caster's whole
    side. `ChooseSourceCoinFlipEffect` — the chosen-source chooser
    family's third member, narrowed to "a source **you control**" instead
    of "of your choice" — flips the coin only once the pick actually
    resolves and branches into the new `RulesEngine.grant_damage_
    multiplier_from_source` (win, the single-source-scoped sibling of
    `grant_damage_multiplier_this_turn`'s controller-wide shape) or the
    already-shipped `prevent_damage_from_source` (lose). The printed
    "Double" keyword is the ordinary keyword fold-in and needs no separate
    handling — it's just the cached card's own marker for the "deals
    double damage" clause, which the coin-flip branch above already fully
    expresses.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("choose_source_coinflip", {})],
            raw_text="Wähle eine Quelle, die du kontrollierst, und wirf eine Münze. "
                     "Falls du gewinnst, fügt diese Quelle das nächste Mal, wenn sie "
                     "in diesem Zug Schaden zufügen würde, stattdessen den doppelten "
                     "Schaden zu. Falls du verlierst, verhindere den nächsten "
                     "Schaden, den sie in diesem Zug zufügen würde.",
        ),
    ]


register("Desperate Gambit", _desperate_gambit)


def _scab_clan_berserker() -> list[AbilitySpec]:
    """Haste
    Renown 1 (When this creature deals combat damage to a player, if it
    isn't renowned, put a +1/+1 counter on it and it becomes renowned.)
    Whenever an opponent casts a noncreature spell, if this creature is
    renowned, this creature deals 2 damage to that player.

    — Haste/Renown both come from the RULE 702 keyword catalogue
    (`effect_binder._keyword_triggered_abilities`, unaffected by this
    registration — see Relic Seeker's own entry); this only adds the
    card's own third ability, gated by the new `EffectSpec.condition` key
    ``source_is_renowned``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "event_player"},
                        condition={"source_is_renowned": True})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Whenever an opponent casts a noncreature spell, if "
                     "this creature is renowned, this creature deals 2 "
                     "damage to that player.",
        )
    ]


register("Scab-Clan Berserker", _scab_clan_berserker)


def _kamahl_heart_of_krosa() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, creatures you control get
    +3/+3 and gain trample until end of turn.
    {1}{G}: Until end of turn, target land you control becomes a 1/1
    Elemental creature with vigilance, indestructible, and haste. It's
    still a land.
    Partner (You can have two commanders if both have partner.)

    — Partner and the combat-trigger pump are already parser-`MODELED`
    (`gate.parse_oracle` claims both; copied verbatim here rather than
    re-derived, per the hand-author-card skill's own guidance) — hand-
    authoring is only needed at all because of the third ability's "target
    land you control becomes a 1/1 … creature … It's still a land" shape
    (MEC-12), which no prior card had needed: RULE 611's `GrantUntilEffect`
    already covers "until end of turn", and `targeting.py` already has
    ``land_you_control``, but nothing had chained *two* `grant_until`
    statics onto the *same* resolve-time target before. Built as two
    ordinary `grant_until` `EffectSpec`s in one effect list — the first
    targets the land and stamps a `type_change` (``add_types=["creature"]``,
    literal 1/1), the second reuses `GameContext.previous_targets` via
    `GrantUntilEffect`'s own existing ``previous_subject`` pronoun (the
    same "Tap target land. It doesn't untap …" idiom `_apply_effects_
    partitioned` already threads through any effect exposing `target_specs`)
    to lay a `grant_keyword` static onto that exact land without
    re-targeting — no new engine primitive, just the first card to combine
    two already-shipped ones this way. "It's still a land" needs no code:
    `type_change`'s ``add_types`` only *adds* the creature type, never
    removing land — though it did surface a real, general bug fixed
    alongside this card: see Ashaya, Soul of the Wild's own entry just
    below for the `GameObject.is_land` fix that direction depends on too.
    """
    return [
        AbilitySpec(
            "keyword", [], keyword={"name": "partner"},
            raw_text="Partner (You can have two commanders if both have partner.)",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 3, "toughness": 3, "keywords": ["trample"],
                "selector": "creatures_you_control",
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
            raw_text="At the beginning of combat on your turn, creatures "
                     "you control get +3/+3 and gain trample until end of "
                     "turn.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "power": 1, "toughness": 1,
                    }},
                    "duration": "end_of_turn", "target_kind": "land_you_control",
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {
                        "keywords": ["vigilance", "indestructible", "haste"],
                    }},
                    "duration": "end_of_turn", "target_kind": None,
                    "previous_subject": True,
                }),
            ],
            cost={"mana": "{1}{G}"},
            raw_text="{1}{G}: Until end of turn, target land you control "
                     "becomes a 1/1 Elemental creature with vigilance, "
                     "indestructible, and haste. It's still a land.",
        ),
    ]


register("Kamahl, Heart of Krosa", _kamahl_heart_of_krosa)


def _ashaya_soul_of_the_wild() -> list[AbilitySpec]:
    """Ashaya's power and toughness are each equal to the number of lands
    you control.
    Nontoken creatures you control are Forest lands in addition to their
    other types. (They're still affected by summoning sickness.)

    — Both clauses are genuinely new ground for the layer engine (MEC-12),
    not reachable by the oracle-text parser today. The first is RULE
    604.3's ordinary characteristic-defining P/T, built on `pt_cda`
    (registered in `effects.py` since an earlier batch but never bound by
    any card until now) reading the already-existing ``"lands_you_control"``
    `continuous.count_selector`. The second is the *reverse* direction of
    every other "X becomes a land" grant this engine has modeled so far — a
    creature gaining the land type, rather than a land gaining the creature
    type — which needed two things: `continuous.affected_objects`'s new
    ``"nontoken_creatures_you_control"`` scope (RULE 108.3's token filter
    applied to the ordinary controller-scoped creature set), and a real,
    general latent bug fix: `GameObject.is_land` had only ever read the
    printed card, never folding in a layer-4 `add_types` grant the way
    `is_creature` already does — so *no* card could ever have made
    something a land this way, regardless of phrasing. Fixed generally
    (mirrors `is_creature`'s own printed-or-added/removed pattern) rather
    than special-cased for this card; Kamahl, Heart of Krosa's own land-to-
    creature direction (this same batch) doesn't depend on it, since
    `is_creature` already had the fix, but any future "a land becomes a
    creature and loses land-ness" or "a creature becomes a land" card now
    reads correctly either way. Once `is_land` is fixed, the Forest subtype
    grant automatically reaches `mana_abilities._derived_basic_mana_
    options`'s existing RULE 305.6 "a land with a basic land type has that
    type's intrinsic mana ability" pass — so a creature Ashaya grants
    Forest to picks up "{T}: Add {G}." with no extra code — and equally
    automatically becomes a legal casualty of land destruction. The
    reminder text's "still affected by summoning sickness" needs no code:
    nothing about gaining an additional type touches `GameObject.
    summoning_sick`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": "lands_you_control", "toughness_count": "lands_you_control",
            })],
            raw_text="Ashaya's power and toughness are each equal to the "
                     "number of lands you control.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "nontoken_creatures_you_control",
                "add_types": ["land"], "add_subtypes": ["Forest"],
            })],
            raw_text="Nontoken creatures you control are Forest lands in "
                     "addition to their other types.",
        ),
    ]


register("Ashaya, Soul of the Wild", _ashaya_soul_of_the_wild)


def _yawgmoths_will() -> list[AbilitySpec]:
    """Until end of turn, you may play lands and cast spells from your
    graveyard.
    If a card would be put into your graveyard from anywhere this turn,
    exile that card instead.

    — Two new player-scoped, turn-limited primitives (MEC-12), neither
    expressible as a permanent-anchored static since the sorcery granting
    them is gone from every zone but graveyard/exile long before end of
    turn — there is no permanent left on the battlefield for the layer
    engine to scan. `GraveyardPlayPermissionThisTurnEffect` stamps
    `Player.graveyard_play_permission_until_turn`, read by
    `game/graveyard_cast.py`'s new `has_temporary_graveyard_play_
    permission` from both `GameEngine.can_play_land` (lands) and
    `_graveyard_cast_permission` (spells) — the first graveyard-cast
    permission source that has ever covered lands too, since Lurrus of the
    Dream-Den's own permanent-anchored grant explicitly excludes them.
    `GraveyardRedirectToExileEffect` stamps `Player.graveyard_redirect_
    to_exile_until_turn`, checked directly in `RulesEngine.
    _move_to_graveyard` — the one choke point every graveyard-bound move
    funnels through regardless of cause — against whichever player *owns*
    the moving card, since a card only ever enters its own owner's
    graveyard (RULE 404.4/700.4), the player-scoped, whole-turn sibling of
    the existing per-*object* `cast_via_graveyard_cast_permission_until_
    turn` check (Lurrus's own trailing "exile instead" clause) already
    sitting right above it. Together: anything cast/played this way that
    would otherwise die/be discarded/be countered this same turn is exiled
    instead of returning to the graveyard for a second recursion — the
    actual point of the card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("graveyard_play_permission_this_turn", {}),
                EffectSpec("graveyard_redirect_to_exile_this_turn", {}),
            ],
            raw_text="Until end of turn, you may play lands and cast "
                     "spells from your graveyard. If a card would be put "
                     "into your graveyard from anywhere this turn, exile "
                     "that card instead.",
        ),
    ]


register("Yawgmoth's Will", _yawgmoths_will)


def _protean_hulk() -> list[AbilitySpec]:
    """When this creature dies, search your library for any number of
    creature cards with total mana value 6 or less, put them onto the
    battlefield, then shuffle.

    — Needed a genuinely new `SearchLibraryEffect` primitive (MEC-12):
    every existing multi-pick search bounds each round by a fixed
    per-card ``max_mana_value`` in ``criteria``, but this is a *running
    total* shared across the whole open-ended pick — a creature that costs
    5 and one that costs 1 are both individually well under 6, but picking
    both exhausts the budget for a third. `SearchLibraryEffect.total_mana_
    value_budget` (`RulesEngine.request_search`/`_search_choice`/
    `resolve_search_choice`, all three threading a `spent_mana_value`
    running total through the recursive multi-round loop) narrows each
    round's own eligible pool to whatever still fits the *remaining*
    budget, on top of `criteria`'s ordinary type filter — orthogonal to,
    and reusable alongside, a real per-card cap should some future card
    need both at once. "Any number" reuses the already-established
    ``count=99`` sentinel other open-ended searches use, since the real
    stopping condition here is the budget running out, not the count.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True, "total_mana_value_budget": 6,
            })],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
            raw_text="When this creature dies, search your library for "
                     "any number of creature cards with total mana value "
                     "6 or less, put them onto the battlefield, then "
                     "shuffle.",
        ),
    ]


register("Protean Hulk", _protean_hulk)


def _helm_of_the_host() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, create a token that's a
    copy of equipped creature, except the token isn't legendary. That
    token gains haste.
    Equip {5}

    — Equip is synthesized by the keyword catalogue; the triggered ability
    itself needed no new primitive at all (MEC-12). `CopyPermanentEffect`
    already supports ``target_kind="attached_permanent"`` (Mirrormind
    Crown's own "copies of equipped creature"), ``not_legendary``
    (Multiversal Recruitment-shaped), and ``haste`` (Kiki-Jiki, Mirror
    Breaker-shaped) — Helm of the Host is simply the first card combining
    exactly these three already-shipped params on one effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "not_legendary": True, "haste": True,
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
            raw_text="At the beginning of combat on your turn, create a "
                     "token that's a copy of equipped creature, except "
                     "the token isn't legendary. That token gains haste.",
        ),
    ]


register("Helm of the Host", _helm_of_the_host)


def _twinflame() -> list[AbilitySpec]:
    """Strive — This spell costs {2}{R} more to cast for each target
    beyond the first.
    Choose any number of target creatures you control. For each of them,
    create a token that's a copy of that creature, except it has haste.
    Exile those tokens at the beginning of the next end step.

    — Strive itself is an already-shipped primitive (`AbilitySpec.
    strive_cost`, `GameEngine`'s per-extra-target cost scaling); the real
    gap was `CopyPermanentEffect` only ever copying its *first* target,
    even when RULE 115.1a's own "any number of target creatures" widens
    the target count past one (MEC-12). Widened with a genuinely new
    ``target_count``/``target_count_max``/``target_optional`` param triple
    (deliberately distinct from the existing ``count``, which still means
    "N copies of the (one) target" — Rite of Replication-shaped, and could
    combine with this on some future card): when the target spec's own
    ``effective_count != 1``, `apply()` now makes one token copy *per*
    chosen target instead of ``count`` copies of just the first, mirroring
    the established `PumpEffect`/`AddCountersEffect` "each of up to N gets
    the full amount" idiom. "Any number of" reuses the parser's own
    ``_ANY_NUMBER_TARGET_CAP`` (10) sentinel. The delayed exile needed one
    small new primitive: `ExileSpecificEffect`, the plural sibling of
    `SacrificeSpecificEffect` (Kiki-Jiki-shaped) — the existing
    `CreateDelayedTriggerEffect`'s ``capture="created_objects"`` branch
    already special-cased any inner effect exposing a plain ``.objects``
    list, but `ExileEffect` only ever carries one ``.target``, silently
    dropping every token past the first for a multi-target source like
    this one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "target_count": 10,
                    "target_optional": True, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            strive_cost="{2}{R}",
            raw_text="Strive — This spell costs {2}{R} more to cast for "
                     "each target beyond the first. Choose any number of "
                     "target creatures you control. For each of them, "
                     "create a token that's a copy of that creature, "
                     "except it has haste. Exile those tokens at the "
                     "beginning of the next end step.",
        ),
    ]


register("Twinflame", _twinflame)


def _heat_shimmer() -> list[AbilitySpec]:
    """Create a token that's a copy of target creature, except it has
    haste and "At the beginning of the end step, exile this token."

    — The single-target sibling of Twinflame's own delayed-exile shape
    (MEC-12, this same batch): rather than literally granting a quoted
    triggered ability onto the freshly-made token (a real but heavier
    mechanism this engine already avoids for exactly this template — see
    Kiki-Jiki/Puppeteer Clique's own "create/reanimate with haste,
    [sacrifice/exile] it at the beginning of the next end step" primitive
    in `Done_Backend.md`'s Marchesa V4.2 entry), the caster-side
    `create_delayed_trigger`/`exile_specific` pair reaches the identical
    board outcome — the token is gone at the next end step regardless of
    which player controls it. Target is any creature (not "you control"),
    unlike Twinflame — `CopyPermanentEffect`'s plain ``"creature"``
    ``target_kind`` default already matches.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {"target_kind": "creature", "haste": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            raw_text="Create a token that's a copy of target creature, "
                     "except it has haste and \"At the beginning of the "
                     "end step, exile this token.\"",
        ),
    ]


register("Heat Shimmer", _heat_shimmer)


def _necrotic_ooze() -> list[AbilitySpec]:
    """As long as this creature is on the battlefield, it has all
    activated abilities of all creature cards in all graveyards.

    — The third ``source_mode`` for `grant_borrowed_activated_ability`
    (MEC-12, alongside MEC-21/MEC-26's ``exiled_with``/``group``/
    ``chosen_permanent``): ``"all_graveyards"`` reads straight off every
    player's live `Player.graveyard` list rather than a single donor or a
    battlefield selector — the "in all graveyards" scope this card is
    actually named for. `continuous._apply_borrowed_activated_abilities`'s
    existing per-(grantee, donor, ability-index) caching, RULE 113.7c
    source-redirect, and creature-only donor filter are all reused as-is;
    "as long as this creature is on the battlefield" needs no `active_if`
    gate — a static ability only ever applies while its own source is on
    the battlefield in the first place (RULE 613.1).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "all_graveyards",
            })],
            raw_text="As long as this creature is on the battlefield, it "
                     "has all activated abilities of all creature cards "
                     "in all graveyards.",
        ),
    ]


register("Necrotic Ooze", _necrotic_ooze)


def _alms_collector() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw two or more cards, instead you and that
    player each draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The draw-replacement
    clause needed a genuinely new primitive: no per-card `DRAW` event can
    see "the whole attempted instruction was for 2+ cards" (each card in a
    multi-draw is independently replaceable per RULE 120.3), so
    `RulesEngine.draw` was restructured to fire one `EventType.DRAW_
    INSTRUCTION` event for the whole call before splitting into per-card
    `DRAW` events — see that event's own docstring and `effects.
    _split_multi_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("split_multi_draw", {"min_count": 2})],
            raw_text="Flash\nIf an opponent would draw two or more cards, "
                     "instead you and that player each draw a card.",
        ),
    ]


register("Alms Collector", _alms_collector)


def _notion_thief() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw a card except the first one they draw in
    each of their draw steps, instead that player skips that draw and you
    draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The exemption clause
    ("except the first one … in each of their draw steps") needed a new
    `GameState.first_draw_done_this_step` per-player tracker, reset right
    as a player's own draw step begins (`game/engine/turn_loop_mixin.py`'s
    `_run_step`) — distinct from the existing whole-turn `cards_drawn_
    this_turn`, since a draw from a spell earlier in the same turn must
    not count as the step's own first draw. See `effects.
    _steal_non_first_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("steal_non_first_draw", {})],
            raw_text="Flash\nIf an opponent would draw a card except the "
                     "first one they draw in each of their draw steps, "
                     "instead that player skips that draw and you draw a "
                     "card.",
        ),
    ]


register("Notion Thief", _notion_thief)


def _chains_of_mephistopheles() -> list[AbilitySpec]:
    """If a player would draw a card except the first one they draw in
    each of their draw steps, that player discards a card instead. If the
    player discards a card this way, they draw a card. If the player
    doesn't discard a card this way, they mill a card.

    — MEC-32. The same ``first_in_draw_step`` exemption Notion Thief's
    entry above reads, but table-wide (no opponent/you scoping) and its
    own three-branch discard/draw/mill body, genuinely bespoke enough to
    need its own replacement type rather than a combination of existing
    ones — see `effects._discard_instead_of_non_first_draw_replacement`
    for the full RULE 616.1f recursive-termination reasoning (each
    replaced draw's own compensating draw can itself be replaced again,
    strictly shrinking the affected player's hand each time, until it's
    empty and the mill branch fires instead).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("discard_instead_of_non_first_draw", {})],
            raw_text="If a player would draw a card except the first one "
                     "they draw in each of their draw steps, that player "
                     "discards a card instead. If the player discards a "
                     "card this way, they draw a card. If the player "
                     "doesn't discard a card this way, they mill a card.",
        ),
    ]


register("Chains of Mephistopheles", _chains_of_mephistopheles)


def _animate_dead() -> list[AbilitySpec]:
    """Enchant creature card in a graveyard
    When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto the
    battlefield with this Aura." Return enchanted creature card to the
    battlefield under your control and attach this Aura to it. When this
    Aura leaves the battlefield, that creature's controller sacrifices it.
    Enchanted creature gets -1/-0.

    — MEC-34, RULE 303.4f's reanimator-Aura template: the Aura's own cast
    target is a graveyard *card*, not a battlefield permanent, so it can't
    attach the ordinary way as it resolves. Needed three pieces, none of
    them previously reachable by any shipped card: (1) `RulesEngine.
    _resolve_permanent_spell` recognizes a graveyard-zone attach target
    and leaves the Aura on the battlefield unattached instead of sending
    it to the graveyard for the "failed" attach, stashing the target on
    the new `GameObject.reanimate_target_id`; (2) `targeting.legal_
    targets` gained a graveyard-wide branch for an "Enchant `<type>` card
    in a graveyard" quality, since the existing "enchant" branch only ever
    searched the battlefield; (3) the ETB ability itself —
    `ReturnFromGraveyardEffect`'s new ``target_kind="self_enchant_
    target"`` reads that stashed id back (rather than a fresh RULE 115
    target) to reanimate the right card under this Aura's controller, then
    the already-shipped `AttachEffect(target_kind="created")` attaches
    this Aura to whatever `ReturnFromGraveyardEffect` just put onto the
    battlefield. The "when this Aura leaves the battlefield, sacrifice
    it" clause is the new `SacrificeAttachedPermanentEffect` (reads
    `attached_to` live, since `GameState.remove_from_battlefield` never
    clears it). The self-referential "it loses/gains" text-change clause
    is RULE 303.4f reminder text describing exactly this behavior with no
    separate gameplay effect — not modeled as its own clause. RULE 704.5n's
    "Aura attached to nothing → owner's graveyard" SBA sweep never
    interferes: it only ever revalidates a permanent whose `attached_to`
    is already set, so the brief window where this Aura is on the
    battlefield but not yet attached is naturally safe.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "self_enchant_target",
                    "under_your_control": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When this Aura enters, if it's on the battlefield, "
                     "it loses \"enchant creature card in a graveyard\" "
                     "and gains \"enchant creature put onto the "
                     "battlefield with this Aura.\" Return enchanted "
                     "creature card to the battlefield under your control "
                     "and attach this Aura to it.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When this Aura leaves the battlefield, that "
                     "creature's controller sacrifices it.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": -1, "toughness": 0})],
            raw_text="Enchanted creature gets -1/-0.",
        ),
    ]


register("Animate Dead", _animate_dead)


def _damping_sphere() -> list[AbilitySpec]:
    """If a land is tapped for two or more mana, it produces {C} instead of
    any other type and amount.
    Each spell a player casts costs {1} more to cast for each other spell
    that player has cast this turn.

    — MEC-36. Two independent unscoped statics, neither previously
    reachable. The first is a new `StaticAbility` layer,
    `"mana_type_override"`, consulted directly by `GameEngine.
    tap_for_mana` (`continuous.mana_type_override_for`) right alongside
    the already-shipped `mana_multiplier` (Nyxbloom Ancient) — a boolean
    override on the *true*, post-multiplier produced total, not a layer-6
    ability grant. The second is `cost_reduction`'s existing `per`
    count-selector vocabulary widened with a new `"spells_cast_this_turn"`
    key: `continuous._cost_static_amount` already evaluates `per` against
    the *casting* player (not this static's own controller), and
    `RulesEngine._track_spell_cast` increments `GameState.spells_cast_
    this_turn` strictly after cost is computed for the spell just cast —
    so "for each other spell" falls out for free with no off-by-one
    correction needed. That field's own reset had to widen from
    "just the incoming active player" (its original RULE 731.2-only
    scope) to every player, every turn, since a non-active player's own
    running total needs to stay accurate too.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 2, "to": "C"})],
            raw_text="If a land is tapped for two or more mana, it "
                     "produces {C} instead of any other type and amount.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells",
                "generic": 1,
                "increase": True,
                "per": "spells_cast_this_turn",
            })],
            raw_text="Each spell a player casts costs {1} more to cast "
                     "for each other spell that player has cast this "
                     "turn.",
        ),
    ]


register("Damping Sphere", _damping_sphere)


def _doomsday() -> list[AbilitySpec]:
    """Search your library and graveyard for five cards and exile the
    rest. Put the chosen cards on top of your library in any order. You
    lose half your life, rounded up.

    — MEC-37. The original ticket framing ("exile up to five cards in a
    pile") turned out to describe a mechanic Doomsday doesn't actually
    have — its real printed text needed no new search primitive at all,
    only a re-check against the real oracle text: `SearchLibraryEffect`
    already supports `zones=["library", "graveyard"]` (combined-zone
    search), `exile_rest` (its own docstring already says
    "…Doomsday-shaped", built with this exact card in mind but never
    reached before now), and `destination="library_top"` — and since a
    multi-card `library_top` search already offers its picks one at a
    time and stacks each new pick *above* the last, the player already
    has full control over the final order simply by choosing which card
    to name each round (name the card that should be drawn last first,
    the one that should be drawn first last) — RULE 601.2c's "in any
    order" falls out for free. The only genuinely new piece is
    `LoseLifeEffect`'s new `amount_from_half_own_life` param — "half your
    life, rounded up" (RULE 107.3) — reading this ability's own controller
    at resolution.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {
                    "criteria": "",
                    "destination": "library_top",
                    "count": 5,
                    "optional": False,
                    "zones": ["library", "graveyard"],
                    "exile_rest": True,
                }),
                EffectSpec("lose_life", {"amount_from_half_own_life": True}),
            ],
            raw_text="Search your library and graveyard for five cards "
                     "and exile the rest. Put the chosen cards on top of "
                     "your library in any order. You lose half your "
                     "life, rounded up.",
        ),
    ]


register("Doomsday", _doomsday)


def _necropotence() -> list[AbilitySpec]:
    """Skip your draw step.
    Whenever you discard a card, exile that card from your graveyard.
    Pay 1 life: Exile the top card of your library face down. Put that
    card into your hand at the beginning of your next end step.

    — MEC-38. Three real pieces, none previously reachable: (1) "Skip
    your draw step" is a new `StaticAbility` layer, `"skip_step"` —
    `RulesEngine.should_skip_step` already existed but had never had a
    real card wired to it (its own `Player.player_effects`/`StaticEffect`
    path is a designed-but-never-instantiated primitive; this uses a live
    battlefield read instead, `continuous.skipped_steps_for`, the same
    "no separate enter/leave lifecycle to build" shape `mana_type_
    override`/MEC-36 already established). (2) The discard trigger needed
    a new per-card `EventType.DISCARD_CARD` (the existing `DISCARD` only
    ever carried an aggregate `count`, the same granularity gap MEC-32
    found on the draw side — `RulesEngine.discard`/`discard_specific`/RULE
    614.12's "discard a land instead" now all fire it) plus `ExileEffect`'s
    new `target_kind="trigger_subject"` (mirroring `TapEffect`'s own),
    reading the discarded card's `instance_id` straight off the firing
    event rather than a chosen target — by the time this resolves the
    card is already sitting in the graveyard (discard moves it there
    before firing), so this is a real zone change into exile. (3) The
    activation cost is the already-shipped `ActivationCost.pay_life`; the
    effect needed a new `ExileTopOfLibraryEffect` (deterministic top-card
    exile, unlike `SearchLibraryEffect`'s real choice among the whole
    zone even at `count=1`) feeding `CreateDelayedTriggerEffect`'s
    existing `capture="created_objects"`, widened with a third captured
    attribute name (`exiled_object`, alongside the pre-existing `objects`/
    `target`) so the delayed half can reuse `ReturnUncastExiledEffect`
    unchanged — previously only ever constructed directly in Python
    (Beseech the Mirror/Rebound's own "if it wasn't cast this way" tail),
    never reachable through the `EffectSpec` whitelist until this card
    needed it as an ordinary delayed effect rather than a bespoke one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("skip_step", {"step": "draw"})],
            raw_text="Skip your draw step.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "trigger_subject"})],
            trigger={"event": "DISCARD_CARD", "condition": {"subject": "you"}},
            raw_text="Whenever you discard a card, exile that card from "
                     "your graveyard.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_top_of_library", {"face_down": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [
                        {"type": "return_uncast_exiled", "params": {"destination": "hand"}}
                    ],
                }),
            ],
            cost={"text": "Pay 1 life"},
            raw_text="Pay 1 life: Exile the top card of your library face "
                     "down. Put that card into your hand at the beginning "
                     "of your next end step.",
        ),
    ]


register("Necropotence", _necropotence)


def _opposition_agent() -> list[AbilitySpec]:
    """Flash
    You control your opponents while they're searching their libraries.
    While an opponent is searching their library, they exile each card
    they find. You may play those cards for as long as they remain
    exiled, and you may spend mana as though it were mana of any color to
    cast them.

    — MEC-39. Flash is the ordinary keyword fold-in. The "you control
    your opponents while searching" clause is deliberately not modeled as
    a genuine RULE 269.4 control exchange of the player — this engine's
    search flow has no other decision point during a search a real
    control swap would change (the searching player still picks which
    cards they find; only where those cards end up is redirected), so
    the second, fully mechanical paragraph already describes the whole
    gameplay outcome. `RulesEngine._finish_search` now consults a new
    `StaticAbility` layer, `"search_redirect"` (`continuous.search_
    redirect_controller_for`), right where it computes each found card's
    destination: an opponent's search has *every* found card's
    destination overridden to exile, and the already-shipped `GameState.
    exile_cast_condition`/`mana_wildcard_permission` pair (every other
    "play a card from exile" mechanism already uses these) is granted to
    this permanent's controller rather than the found card's own owner —
    the one genuine generalization needed, since every existing grantor
    of those two maps had only ever pointed them at the exiled card's own
    owner.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("search_redirect", {})],
            raw_text="You control your opponents while they're searching "
                     "their libraries.\nWhile an opponent is searching "
                     "their library, they exile each card they find. You "
                     "may play those cards for as long as they remain "
                     "exiled, and you may spend mana as though it were "
                     "mana of any color to cast them.",
        ),
    ]


register("Opposition Agent", _opposition_agent)


def _leonin_arbiter() -> list[AbilitySpec]:
    """Players can't search libraries. Any player may pay {2} for that
    player to ignore this effect until end of turn.

    — MEC-35. Two pieces. (1) The already-shipped `grant_search_
    prohibited` (Stranglehold's own effect type) gained a new `scope`
    param: `"opponents"` (the pre-existing default, matching Stranglehold's
    "**your opponents** can't…") vs. `"all"` (this card's own unqualified
    "**Players** can't…", which also restricts its own controller). (2)
    "Any player may pay {2}… to ignore this effect until end of turn" is a
    genuine RULE 116.2a special action — no stack, no timing restriction,
    repeatable (paying twice just wastes {2}, same as the real card) —
    `GameEngine.pay_search_exemption`/`pay_search_exemption_actions`,
    mirroring `turn_face_up`'s own established "offered only when payable,
    reclaims priority for its taker" shape exactly. `GameState.search_
    exempt_until_turn` is the same "stops matching once the turn advances,
    no cleanup bookkeeping needed" idiom `temp_flash_until_turn` already
    uses. The exemption is read as "ignore every current search
    prohibition," not just this one specific effect (the printed wording
    says "this effect") — no shipped card yet combines Leonin Arbiter with
    a second, independent prohibition source, so the simpler reading costs
    nothing today; narrow it if that ever changes.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_search_prohibited", {"scope": "all"})],
            raw_text="Players can't search libraries. Any player may pay "
                     "{2} for that player to ignore this effect until end "
                     "of turn.",
        ),
    ]


register("Leonin Arbiter", _leonin_arbiter)


def _return_the_favor() -> list[AbilitySpec]:
    """Spree (Choose one or more additional costs.)
    + {1} — Copy target instant spell, sorcery spell, activated ability, or
    triggered ability. You may choose new targets for the copy.
    + {1} — Change the target of target spell or ability with a single
    target.

    — MEC-31, the ticket's own named card (`Ojer cEDH`). RULE 702.172a
    Spree — a genuine new modal shape, not RULE 700.2's "choose N or more"
    with a shared cost: every mode prices *itself*
    (`AbilitySpec.modes["mode_costs"]`, one raw mana-cost string per
    option, parallel to ``options``/``descriptions`` — the parser's own
    `catalogue/modal.split_spree_block` builds the same dict for a
    cache-wide Spree card; this one is hand-authored only for its first
    mode's effect body, not its modal shape). `effect_binder._build_mode_
    entries` folds ``mode_costs[i]`` onto ``spell_modes[i]["cost"]``;
    `GameEngine._modal_extra_cost` sums the chosen combination's own costs
    on top of the printed {R}{R}, consulted by `effective_cast_cost`/
    `can_cast`/`_auto_tap_for_cast_if_needed` and surfaced per legal-action
    combination by `_modal_cast_actions`/`_cast_action` (each combination
    locks independently when its own total isn't affordable).

    The second mode ("change the target…") is exactly the parser's own
    already-built `_change_target` handler output — `EffectSpec
    ("change_target", {"spell_or_ability": True})`, ENG-26's union
    spell-or-ability stack-item lookup, unchanged.

    The first mode ("copy target … spell, activated ability, or triggered
    ability … choose new targets") is hand-authored with the same two
    simplifications every other targeted-copy catalogue entry already
    carries (Reiterate/Narset's Reversal/Dualcaster Mage) —
    `CopySpellEffect`'s own docstring names both: it only targets a real
    spell (`TargetSpec(kind="spell")`, RULE 707.10's copiable-object rule
    still applies fine to instants/sorceries but `RulesEngine.copy_spell`
    has no path for an *ability* StackItem at all, whose `obj` is always
    `None` — a real, separate primitive this card doesn't need to build to
    become playable, tracked as its own future gap rather than silently
    modeled here), and it keeps the original's targets rather than opening
    an interactive "choose new targets" pick (`copy_spell`'s own
    `new_targets` param exists but no caller wires an interactive choice to
    it yet). Both match every real card sharing this template today.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "mode_costs": ["{1}", "{1}"],
                "options": [
                    [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
                    [EffectSpec("change_target", {"spell_or_ability": True})],
                ],
                "descriptions": [
                    "Copy target instant spell, sorcery spell, activated ability, "
                    "or triggered ability. You may choose new targets for the copy.",
                    "Change the target of target spell or ability with a single target.",
                ],
            },
            raw_text="Spree (Choose one or more additional costs.)\n"
                     "+ {1} — Copy target instant spell, sorcery spell, activated "
                     "ability, or triggered ability. You may choose new targets for "
                     "the copy.\n"
                     "+ {1} — Change the target of target spell or ability with a "
                     "single target.",
        ),
    ]


register("Return the Favor", _return_the_favor)


def _omen_machine() -> list[AbilitySpec]:
    """Players can't draw cards.
    At the beginning of each player's draw step, that player exiles the
    top card of their library. If it's a land card, the player puts it
    onto the battlefield. Otherwise, the player casts it without paying
    its mana cost if able.

    — MEC-33. Two independent pieces, neither needing a genuinely new
    engine mechanism once diagnosed against what already exists. (1) "Players
    can't draw cards" is just RULE 121.5-adjacent `draw_limit`
    (`continuous.max_draws_per_turn`, already built for Spirit of the
    Labyrinth/Narset, Parter of Veils) at `max_per_turn=0` with its
    already-default `affects="all"` — a flat cap of zero *is* an outright
    ban, no new code at all, just a value the primitive had never been
    asked for before. (2) The replacement action is a `STEP_BEGIN`
    trigger on the "draw" step with no `phase_relation` at all (RULE
    500.7 — since only the active player ever has a draw step, an
    unscoped "at the beginning of the draw step" trigger fires exactly
    once per turn, for whoever that is — the same "each player's step"
    shape a `phase_relation` of "you"/"not_you" would otherwise narrow,
    just left unnarrowed here) chaining `ExileTopOfLibraryEffect`'s new
    `player_selector="active_player"` (mirroring `DealDamageEffect`'s own
    `"active_player"` selector, the established "no subject of its own,
    read live off `GameState.active_player`" idiom — Roiling Vortex-
    shaped) into the new `LandOrFreeCastEffect`, which reads whatever
    `ExileTopOfLibraryEffect` just exiled (`GameContext.created_objects`)
    and either puts a land onto the battlefield or attempts a free cast
    "if able" (RULE 601.2c — no legal target, and it just stays exiled;
    the printed text names no other fallback). The same tail also prints
    on Wild Evocation (off a *revealed random hand card* instead of an
    exiled library card), confirming `LandOrFreeCastEffect` is a real
    two-card shared primitive worth building generally rather than a
    one-off tied to how the card got there.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 0})],
            raw_text="Players can't draw cards.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {"player_selector": "active_player"}),
                EffectSpec("land_or_free_cast", {"player_selector": "active_player"}),
            ],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "draw"}},
            raw_text="At the beginning of each player's draw step, that player "
                     "exiles the top card of their library. If it's a land "
                     "card, the player puts it onto the battlefield. "
                     "Otherwise, the player casts it without paying its mana "
                     "cost if able.",
        ),
    ]


register("Omen Machine", _omen_machine)


def _necromancy() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash. If you cast it any
    time a sorcery couldn't have been cast, the controller of the
    permanent it becomes sacrifices it at the beginning of the next
    cleanup step.
    When this enchantment enters, if it's on the battlefield, it becomes
    an Aura with "enchant creature put onto the battlefield with
    Necromancy." Put target creature card from a graveyard onto the
    battlefield under your control and attach this enchantment to it.
    When this enchantment leaves the battlefield, that creature's
    controller sacrifices it.

    — MEC-44, RULE 303.4f's *non-Aura* reanimator template (Animate Dead's
    own sibling ticket, MEC-34 — that card is a real Aura from load time;
    this one prints as a plain Enchantment and only becomes an Aura once
    it resolves). Three real gaps closed, none needing as much new
    machinery as first diagnosed. (1) The unconditional flash grant needed
    only a trivially-true `conditional_flash={"unconditional": True}`
    key (`ALLOWED_CAST_CONDITION_KEYS`/`condition_query.
    conditional_flash_holds`), since every prior key gated on something.
    (2) "If cast at a time a sorcery couldn't have been cast, sacrifice at
    next cleanup" needed a new `GameObject.cast_outside_sorcery_speed`
    flag, stamped once at cast time (`GameEngine._cast_current_face`,
    since the board — and so the answer — has moved on by the time this
    resolves) and read by a new `EffectSpec.condition` key of the same
    name gating a `create_delayed_trigger`/`sacrifice_self` pair — no new
    delayed-trigger primitive at all: `CreateDelayedTriggerEffect`'s
    existing `step`/`scope` params already cover "at the beginning of the
    next cleanup step" (RULE 514), and `sacrifice_self` already exists
    (Dress Down/Underworld Breach). (3) "It becomes an Aura with
    '`<quoted text>`'" — the ticket's own flagged "real blocker" — turned
    out to need far less than fresh threading through every
    `_attachment_kind`/`_attachment_legal`/`_detach_attachments_from`
    reader: all three already read `GameObject.parametric_keywords` fresh
    off the live object every call, never a load-time snapshot, so the
    new `BecomeAuraEffect` just writes `parametric_keywords["enchant"]`
    directly and every reader picks it up for free.

    Reuses Animate Dead's own `ReturnFromGraveyardEffect`/`AttachEffect
    (target_kind="created")`/`SacrificeAttachedPermanentEffect` wholesale,
    but with a genuine RULE 115 target on the *reanimate* clause itself
    (`target_kind="any_graveyard_creature"` — "**a** graveyard", any
    player's, unlike Animate Dead's own printed-on-the-Aura target)
    rather than Animate Dead's stashed-at-cast-time shape, since Necromancy
    carries no "Enchant" line at cast time at all for `_resolve_permanent_
    spell`'s graveyard-attach recognition to key off — its target is
    chosen when the *triggered ability* resolves instead. **Documented
    simplification**, matching Animate Dead's own: the "it loses/gains"
    self-referential quality-text-change isn't modeled as its own clause
    (RULE 303.4f reminder text describing exactly this behavior, no
    separate gameplay effect) — `BecomeAuraEffect`'s `quality="creature"`
    default is close enough that `_attachment_legal`'s permissive fallback
    (any quality string it doesn't recognize matches everything) covers it
    regardless.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("become_aura", {"quality": "creature"}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "any_graveyard_creature",
                    "under_your_control": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "cleanup", "scope": "controller",
                        "effects": [{"type": "sacrifice_self", "params": {}}],
                        "description": "Necromancy: am Anfang des nächsten "
                                        "Aufräumschritts opfern",
                    },
                    condition={"cast_outside_sorcery_speed": True},
                ),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            conditional_flash={"unconditional": True},
            raw_text="You may cast this spell as though it had flash. If "
                     "you cast it any time a sorcery couldn't have been "
                     "cast, the controller of the permanent it becomes "
                     "sacrifices it at the beginning of the next cleanup "
                     "step.\nWhen this enchantment enters, if it's on the "
                     "battlefield, it becomes an Aura with \"enchant "
                     "creature put onto the battlefield with Necromancy.\" "
                     "Put target creature card from a graveyard onto the "
                     "battlefield under your control and attach this "
                     "enchantment to it.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When this enchantment leaves the battlefield, that "
                     "creature's controller sacrifices it.",
        ),
    ]


register("Necromancy", _necromancy)


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco / cEDH staples remaining gaps (batch 1)
# ---------------------------------------------------------------------------


def _culling_ritual() -> list[AbilitySpec]:
    """Culling Ritual (Sorcery, {2}{B}{G})

    "Destroy each nonland permanent with mana value 2 or less. Add {B} or
    {G} for each permanent destroyed this way."

    The destroy half is a plain parser-claimable mass wipe on its own
    (`_MASS_DESTROY_NOUNS_SINGULAR`'s new "nonland permanent" entry) —
    hand-authored here only because the mana rider needs a same-resolution
    accumulator (`GameContext.permanents_destroyed_this_way`, mirroring the
    existing `life_lost_this_way`) the parser has no vocabulary for yet.

    **Documented simplification**: the real card lets you split the
    produced mana between {B} and {G} independently, mana by mana (RULE
    106.1); `AddManaEffect.any_color_choices` offers one colour choice for
    the *whole* amount instead (see its own docstring for why) — no
    per-unit "how many of each" interactive shape exists yet. Still fully
    usable colored mana, just less flexible than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec(
                    "destroy",
                    {"selector": "all_nonland_permanents", "filter": {"max_mana_value": 2}},
                ),
                EffectSpec(
                    "add_mana",
                    {
                        "colors": ["ANY"],
                        "any_color_choices": ["B", "G"],
                        "any_amount_from_context": "permanents_destroyed_this_way",
                    },
                ),
            ],
            raw_text="Destroy each nonland permanent with mana value 2 or "
                     "less. Add {B} or {G} for each permanent destroyed "
                     "this way.",
        ),
    ]


register("Culling Ritual", _culling_ritual)


def _cabal_ritual() -> list[AbilitySpec]:
    """Cabal Ritual (Instant, {1}{B})

    "Add {B}{B}{B}.
    Threshold — Add {B}{B}{B}{B}{B} instead if there are seven or more
    cards in your graveyard."

    Modeled as a flat 3 B plus a *conditional extra 2 B* rather than a true
    "instead" override — mathematically identical (5 = 3 + 2) and avoids
    needing the general, still-unbuilt "if kicked, `<effect>` instead"
    override primitive (CLAUDE.md's Notable Gaps) for what is, arithmetically,
    an additive bonus. `EffectSpec.condition`'s new `cards_in_graveyard_at_
    least` key (RULE 702.19 Threshold's own gate) is a plain graveyard-size
    read, reusable by any future Threshold card with the same "Add X
    instead" phrasing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_mana", {"colors": ["B", "B", "B"]}),
                EffectSpec(
                    "add_mana", {"colors": ["B", "B"]},
                    condition={"cards_in_graveyard_at_least": 7},
                ),
            ],
            raw_text="Add {B}{B}{B}.\nThreshold — Add {B}{B}{B}{B}{B} "
                     "instead if there are seven or more cards in your "
                     "graveyard.",
        ),
    ]


register("Cabal Ritual", _cabal_ritual)


def _ranger_captain_of_eos() -> list[AbilitySpec]:
    """Ranger-Captain of Eos (Creature — Human Soldier Ranger, {1}{W}{W})

    "When this creature enters, you may search your library for a creature
    card with mana value 1 or less, reveal it, put it into your hand, then
    shuffle.
    Sacrifice this creature: Your opponents can't cast noncreature spells
    this turn."

    The ETB is already parser-claimable as-is (`author_card.py reuse`
    confirms it); hand-authored only because the sacrifice ability's own
    "this turn" duration needs `GrantUntilEffect` to wrap the standing
    `cast_prohibition` static (Gaddock Teeg-shaped) instead of a
    permanent's own always-on line — `target_kind=None` since the
    prohibition is scoped by the static's own ``scope="opponents"``
    (read off the ability's ``source``, i.e. this card, which survives
    being sacrificed since `GameEffect.source` keeps its object reference
    regardless of zone), not by a chosen target.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {"criteria": {"type": "creature", "max_mana_value": 1}, "destination": "hand"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
            raw_text="When this creature enters, you may search your "
                     "library for a creature card with mana value 1 or "
                     "less, reveal it, put it into your hand, then "
                     "shuffle.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "cast_prohibition",
                            "params": {"scope": "opponents", "noncreature": True},
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "Sacrifice ~"},
            raw_text="Sacrifice this creature: Your opponents can't cast "
                     "noncreature spells this turn.",
        ),
    ]


register("Ranger-Captain of Eos", _ranger_captain_of_eos)


def _vexing_shusher() -> list[AbilitySpec]:
    """Vexing Shusher (Creature — Goblin Shaman, {1}{R})

    "This spell can't be countered.
    {R/G}: Target spell can't be countered."

    The static is already parser-claimable as-is; hand-authored only for
    the activated ability, which is `MarkCantBeCounteredEffect`'s existing
    resolve-time marker (built for Mistrise Village's untargeted "next
    spell you cast") widened with a real `target_kind="spell"` RULE 115
    target instead.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("mark_cant_be_countered", {"target_kind": "spell"})],
            cost={"text": "{R/G}"},
            raw_text="{R/G}: Target spell can't be countered.",
        ),
    ]


register("Vexing Shusher", _vexing_shusher)


def _tinder_wall() -> list[AbilitySpec]:
    """Tinder Wall (Creature — Plant Wall, {G})

    "Defender (This creature can't attack.)
    Sacrifice this creature: Add {R}{R}.
    {R}, Sacrifice this creature: It deals 2 damage to target creature it's
    blocking."

    Defender and the plain sacrifice-for-mana ability are both already
    picked up independent of this registration (`parse_keywords`/
    `mana_abilities_for` scan the card's own oracle text directly, not
    gated by `ability_catalogue` registration) — hand-authored only for
    the damage ability, which needs the new `"creature_source_is_
    blocking"` target kind (`game/targeting.py`) no existing card had.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"target_kind": "creature_source_is_blocking", "amount": 2})],
            cost={"text": "{R}, Sacrifice ~"},
            raw_text="{R}, Sacrifice this creature: It deals 2 damage to "
                     "target creature it's blocking.",
        ),
    ]


register("Tinder Wall", _tinder_wall)


# ---------------------------------------------------------------------------
# MEC-40: cEDH Rocco's remaining gaps, done to completion
# ---------------------------------------------------------------------------


def _academy_rector() -> list[AbilitySpec]:
    """Academy Rector (Creature — Human Cleric, {3}{W})

    "When this creature dies, you may exile it. If you do, search your
    library for an enchantment card, put that card onto the battlefield,
    then shuffle."

    The "you may X. If you do, Y." shape collapses to the ability's own
    `optional=True` (the same idiom Ranger-Captain of Eos's ETB and
    Necromancy's reanimate already use) since there's no *further*
    decision point between the exile and the search — declining the whole
    ability leaves Academy Rector undisturbed in the graveyard.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "battlefield"}),
            ],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            optional=True,
            raw_text="When this creature dies, you may exile it. If you "
                     "do, search your library for an enchantment card, "
                     "put that card onto the battlefield, then shuffle.",
        ),
    ]


register("Academy Rector", _academy_rector)


def _ajani_nacatl_pariah() -> list[AbilitySpec]:
    """Ajani, Nacatl Pariah // Ajani, Nacatl Avenger (Legendary Creature —
    Cat Warrior, {1}{W})

    "When Ajani enters, create a 2/1 white Cat Warrior creature token.
    Whenever one or more other Cats you control die, you may exile Ajani,
    then return him to the battlefield transformed under his owner's
    control."

    The ETB token is already parser-claimable as-is. The transform trigger
    reuses `ExileReturnTransformedEffect` (RULE 400.7/712.8, built for
    Ayara/Clive/Jin-Gitaxias) completely unchanged — untargeted and always
    self, exactly this shape. **Documented simplification**: a group DIES
    trigger fires once per dying Cat rather than once per simultaneous
    batch (RULE 603.3b's stricter "one or more" reading isn't modeled),
    self-limiting in practice since the first firing exiles Ajani, and
    every further firing that turn finds no source left to act on.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "create_token",
                    {"count": 1, "power": 2, "toughness": 1, "colors": ["W"],
                     "subtypes": ["Cat", "Warrior"], "keywords": [], "token_name": "Cat Warrior"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, create a 2/1 white Cat Warrior creature token.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_return_transformed", {})],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "you", "subtypes": ["cat"]},
            },
            optional=True,
            raw_text="Whenever one or more other Cats you control die, "
                     "you may exile ~, then return him to the battlefield "
                     "transformed under his owner's control.",
        ),
    ]


register("Ajani, Nacatl Pariah", _ajani_nacatl_pariah)


def _allosaurus_shepherd() -> list[AbilitySpec]:
    """Allosaurus Shepherd (Creature — Elf Shaman, {G})

    "This spell can't be countered.
    Green spells you control can't be countered.
    {4}{G}{G}: Until end of turn, each Elf creature you control has base
    power and toughness 5/5 and becomes a Dinosaur in addition to its
    other creature types."

    The self-uncounterable static is already parser-claimable. The second
    static reuses `GrantCantBeCounteredEffect`'s new ``color`` param
    (MEC-40). The activated ability reuses the standing ``creatures_you_
    control_of_type_elf`` group selector (`continuous.group_selector_
    objects`, an already-general subtype-scoped anthem affects string) via
    `GrantUntilEffect` wrapping ``type_change`` — the same "until end of
    turn" resolve-time grant Crew's own "becomes an artifact creature"
    reuses (MEC-29).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
            raw_text="This spell can't be countered.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "color_spells_you_control", "color": "G"})],
            raw_text="Green spells you control can't be countered.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "type_change",
                            "params": {
                                "power": 5, "toughness": 5, "add_subtypes": ["Dinosaur"],
                                "affects": "creatures_you_control_of_type_elf",
                            },
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "{4}{G}{G}"},
            raw_text="{4}{G}{G}: Until end of turn, each Elf creature you "
                     "control has base power and toughness 5/5 and "
                     "becomes a Dinosaur in addition to its other "
                     "creature types.",
        ),
    ]


register("Allosaurus Shepherd", _allosaurus_shepherd)


def _domri_anarch_of_bolas() -> list[AbilitySpec]:
    """Domri, Anarch of Bolas (Legendary Planeswalker — Domri, {1}{R}{G})

    "Creatures you control get +1/+0.
    +1: Add {R} or {G}. Creature spells you cast this turn can't be
    countered.
    −2: Target creature you control fights target creature you don't
    control."

    The anthem and the fight ability are already parser-claimable as-is.
    The +1's mana half is the existing ``add_mana``/``colors=["ANY"]``
    single-choice shape narrowed to R/G; its "can't be countered" half
    reuses `arm_spell_watcher` (RULE 118.3, Dual Strike-shaped) with
    ``card_types=["creature"]`` and ``repeat=True`` (Veil of Summer's own
    "for the rest of the turn" idiom) feeding `MarkCantBeCounteredEffect`
    via ``then_specs`` — no new primitive needed at all.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 0, "affects": "creatures_you_control"})],
            raw_text="Creatures you control get +1/+0.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_mana", {"colors": ["ANY"], "any_color_choices": ["R", "G"]}),
                EffectSpec(
                    "arm_spell_watcher",
                    {"card_types": ["creature"], "repeat": True,
                     "then_specs": [{"type": "mark_cant_be_countered", "params": {}}]},
                ),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Add {R} or {G}. Creature spells you cast this "
                     "turn can't be countered.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("fight", {"fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control"})],
            cost={"loyalty": -2},
            raw_text="−2: Target creature you control fights target "
                     "creature you don't control.",
        ),
    ]


register("Domri, Anarch of Bolas", _domri_anarch_of_bolas)


def _eladamri_korvecdal() -> list[AbilitySpec]:
    """Eladamri, Korvecdal (Legendary Creature — Elf Warrior, {1}{G}{G})

    "You may look at the top card of your library any time.
    You may cast creature spells from the top of your library.
    {G}, {T}, Tap two untapped creatures you control: Reveal a card from
    your hand or the top card of your library. If you reveal a creature
    card this way, put it onto the battlefield. Activate only during your
    turn."

    The "look" permission is already parser-claimable; the "cast creature
    spells from the top" clause is the same standing static widened with
    `TopLibraryPermissionEffect.creature_only` (MEC-40). **Documented
    simplification** on the reveal ability: `SearchLibraryEffect`'s
    ``zones`` param has no "just the top card" source (only whole-zone
    scans — "library"/"graveyard"/"hand"/"exile"), so it's modeled as
    "reveal a card from your hand" only, dropping the "or the top card of
    your library" alternative — Eladamri's own standing "look at the top
    card any time" permission still lets a player plan around what that
    card is even though this ability can't reach it directly.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
            raw_text="You may look at the top card of your library any time.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "creature_only": True})],
            raw_text="You may cast creature spells from the top of your library.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"type": "creature"}, "zones": ["hand"],
                        "destination": "battlefield", "optional": True, "count": 1,
                    },
                )
            ],
            cost={"text": "{G}, {T}, Tap two untapped creatures you control"},
            raw_text="{G}, {T}, Tap two untapped creatures you control: "
                     "Reveal a card from your hand or the top card of "
                     "your library. If you reveal a creature card this "
                     "way, put it onto the battlefield. Activate only "
                     "during your turn.",
        ),
    ]


register("Eladamri, Korvecdal", _eladamri_korvecdal)


def _elesh_norn_mother_of_machines() -> list[AbilitySpec]:
    """Elesh Norn, Mother of Machines (Legendary Creature — Phyrexian
    Praetor, {4}{W})

    "Vigilance
    If a permanent entering causes a triggered ability of a permanent you
    control to trigger, that ability triggers an additional time.
    Permanents entering don't cause abilities of permanents your opponents
    control to trigger."

    Vigilance is already parser-claimable. The trigger-doubling clause is
    `TriggerDoublerEffect`'s new ``cause_filter`` scoping (MEC-40, unscoped
    by the doubled permanent's own type, unlike Roaming Throne's
    ``chosen_type`` gate). The suppression clause reuses the standing
    ``trigger_prohibition`` static (Tocatli Honor Guard/Torpor Orb-shaped)
    widened with a new ``scope="opponents"`` (`continuous.trigger_
    suppressed_for`), since the printed clause silences only *opponents'*
    triggers, not the controller's own.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"cause_filter": [EventType.ENTERS_BATTLEFIELD]})],
            raw_text="If a permanent entering causes a triggered ability "
                     "of a permanent you control to trigger, that ability "
                     "triggers an additional time.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_prohibition", {"event": EventType.ENTERS_BATTLEFIELD, "scope": "opponents"})],
            raw_text="Permanents entering don't cause abilities of "
                     "permanents your opponents control to trigger.",
        ),
    ]


register("Elesh Norn, Mother of Machines", _elesh_norn_mother_of_machines)


def _flamescroll_celebrant() -> list[AbilitySpec]:
    """Flamescroll Celebrant // Revel in Silence (Creature — Human Shaman,
    {1}{R})

    "Whenever an opponent activates an ability that isn't a mana ability,
    this creature deals 1 damage to that player.
    {1}{R}: This creature gets +2/+0 until end of turn."

    The pump ability is already parser-claimable. The trigger is Harsh
    Mentor/Immolation Shaman's own already-shipped shape (RULE 602.2's
    `EventType.ACTIVATED_ABILITY`, which mana abilities never reach at all
    since they resolve through the separate `tap_for_mana` fast path
    instead of the stack — "isn't a mana ability" needs no extra filter),
    just copied verbatim.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent activates an ability that "
                     "isn't a mana ability, ~ deals 1 damage to that "
                     "player.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0})],
            cost={"text": "{1}{R}"},
            raw_text="{1}{R}: ~ gets +2/+0 until end of turn.",
        ),
    ]


register("Flamescroll Celebrant", _flamescroll_celebrant)


def _gandalf_the_white() -> list[AbilitySpec]:
    """Gandalf the White (Legendary Creature — Avatar Wizard, {3}{W}{W})

    "Flash
    You may cast legendary spells and artifact spells as though they had
    flash.
    If a legendary permanent or an artifact entering or leaving the
    battlefield causes a triggered ability of a permanent you control to
    trigger, that ability triggers an additional time."

    Flash is already parser-claimable. The standing flash-permission
    static reuses `flash_permission`'s new ``type_filter`` (MEC-40,
    ``noncreature_only``/``creature_only``'s sibling for a closed
    "legendary"/"artifact" word list). The trigger-doubling clause is
    Elesh Norn's own ``cause_filter`` widened to *two* event types
    ("entering **or** leaving") plus the new ``cause_type_filter``
    (unlike Elesh Norn's own unscoped "**a** permanent", this one is
    narrowed to legendary permanents/artifacts specifically).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"type_filter": ["legendary", "artifact"]})],
            raw_text="You may cast legendary spells and artifact spells "
                     "as though they had flash.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "trigger_doubler",
                    {
                        "cause_filter": [EventType.ENTERS_BATTLEFIELD, EventType.LEAVES_BATTLEFIELD],
                        "cause_type_filter": ["legendary", "artifact"],
                    },
                )
            ],
            raw_text="If a legendary permanent or an artifact entering or "
                     "leaving the battlefield causes a triggered ability "
                     "of a permanent you control to trigger, that ability "
                     "triggers an additional time.",
        ),
    ]


register("Gandalf the White", _gandalf_the_white)


def _guardian_project() -> list[AbilitySpec]:
    """Guardian Project (Enchantment, {3}{G})

    "Whenever a nontoken creature you control enters, if it doesn't have
    the same name as another creature you control or a creature card in
    your graveyard, draw a card."

    The RULE 603.1 group-subject trigger condition ("a nontoken creature
    you control enters") is already-general segmenter vocabulary. The
    "if it doesn't have the same name as…" gate is the new
    ``entering_object_unique_name`` `EffectSpec.condition` key (MEC-40).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"entering_object_unique_name": True},
                )
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
            },
            raw_text="Whenever a nontoken creature you control enters, if "
                     "it doesn't have the same name as another creature "
                     "you control or a creature card in your graveyard, "
                     "draw a card.",
        ),
    ]


register("Guardian Project", _guardian_project)


def _guardian_sunmare() -> list[AbilitySpec]:
    """Guardian Sunmare (Creature — Horse Mount, {3}{W}{W})

    "Ward {2}
    Whenever this creature attacks while saddled, search your library for
    a nonland permanent card with mana value 3 or less, put it onto the
    battlefield, then shuffle.
    Saddle 4"

    Ward and Saddle are both already parser-claimable keywords — Saddle's
    own cost/state (`ActivationCost.saddle_power`, `GameObject.saddled_
    until_turn`, `effects.BecomeSaddledEffect`) is new real behaviour
    (MEC-40; previously keyword-recognized only, per RULE 702.171). The
    attack trigger's own "while saddled" gate is the new ``requires_
    saddled`` trigger-condition key, the same "checks the source's own
    live state" idiom `requires_equipped` uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {
                            "type": ["Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"],
                            "without_type": "Land", "max_mana_value": 3,
                        },
                        "destination": "battlefield",
                    },
                )
            ],
            trigger={
                "event": EventType.ATTACKS, "condition": {"subject": "self"}, "requires_saddled": True,
            },
            raw_text="Whenever ~ attacks while saddled, search your "
                     "library for a nonland permanent card with mana "
                     "value 3 or less, put it onto the battlefield, then "
                     "shuffle.",
        ),
    ]


register("Guardian Sunmare", _guardian_sunmare)


def _kutzil_malamet_exemplar() -> list[AbilitySpec]:
    """Kutzil, Malamet Exemplar (Legendary Creature — Cat Warrior, {1}{G}{W})

    "Your opponents can't cast spells during your turn.
    Whenever one or more creatures you control each with power greater
    than its base power deals combat damage to a player, draw a card."

    The first static is already parser-claimable (``cast_prohibition``
    with an ``active_if: your_turn`` RULE 613.6 gate). The trigger is the
    new ``contributor_power_gt_base`` aggregate-event qualifier (MEC-40,
    `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`'s own sibling to
    MEC-29's ``contributor_power_at_least``/``contributor_subtype``).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {"scope": "opponents", "active_if": {"kind": "your_turn"}})],
            raw_text="Your opponents can't cast spells during your turn.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "you"},
                "contributor_power_gt_base": True,
            },
            raw_text="Whenever one or more creatures you control each "
                     "with power greater than its base power deals combat "
                     "damage to a player, draw a card.",
        ),
    ]


register("Kutzil, Malamet Exemplar", _kutzil_malamet_exemplar)


def _moon_blessed_cleric() -> list[AbilitySpec]:
    """Moon-Blessed Cleric (Creature — Human Elf Cleric, {2}{W})

    "Divine Intervention — When this creature enters, you may search your
    library for an enchantment card, reveal it, then shuffle and put that
    card on top."

    A plain optional search onto the library's own top — the ability-word
    "Divine Intervention —" prefix carries no separate rules meaning
    (RULE 207.2c reminder-text-style flavour heading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "enchantment"}, "destination": "library_top"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
            raw_text="Divine Intervention — When ~ enters, you may search "
                     "your library for an enchantment card, reveal it, "
                     "then shuffle and put that card on top.",
        ),
    ]


register("Moon-Blessed Cleric", _moon_blessed_cleric)


def _sigarda_font_of_blessings() -> list[AbilitySpec]:
    """Sigarda, Font of Blessings (Legendary Creature — Angel, {2}{G}{W})

    "Flying
    Other permanents you control have hexproof.
    You may look at the top card of your library any time.
    You may cast Angel spells and Human spells from the top of your
    library."

    Flying and the hexproof anthem are already parser-claimable. The look
    permission is already-general `top_library_permission`. The cast
    permission reuses its own new ``subtypes`` filter (MEC-40, Eladamri's
    sibling ``creature_only`` narrowed to two named creature types
    instead) — union semantics, either subtype qualifies.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True})],
            raw_text="You may look at the top card of your library any time.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"cast_spells": True, "subtypes": ["Angel", "Human"]})],
            raw_text="You may cast Angel spells and Human spells from "
                     "the top of your library.",
        ),
    ]


register("Sigarda, Font of Blessings", _sigarda_font_of_blessings)


def _squee_the_immortal() -> list[AbilitySpec]:
    """Squee, the Immortal (Legendary Creature — Goblin, {1}{R}{R})

    "You may cast this card from your graveyard or from exile."

    A bare self-referential zone permission — `SelfGraveyardOrExileCast
    PermissionEffect` (MEC-40), read directly off this object's own
    ``static_effects`` regardless of which of the two zones it's
    currently sitting in.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("self_graveyard_or_exile_cast_permission", {})],
            raw_text="You may cast this card from your graveyard or from exile.",
        ),
    ]


register("Squee, the Immortal", _squee_the_immortal)


def _sylvan_library() -> list[AbilitySpec]:
    """Sylvan Library (Enchantment, {1}{G})

    "At the beginning of your draw step, you may draw two additional
    cards. If you do, choose two cards in your hand drawn this turn. For
    each of those cards, pay 4 life or put the card on top of your
    library."

    The whole "you may draw… if you do, choose… for each, pay-or-return"
    sequence is `SylvanLibraryEffect` (MEC-40) — see its own docstring for
    the documented "always the two just-drawn cards" simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sylvan_library", {"life": 4, "count": 2})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "draw"}, "phase_relation": "you",
            },
            optional=True,
            raw_text="At the beginning of your draw step, you may draw "
                     "two additional cards. If you do, choose two cards "
                     "in your hand drawn this turn. For each of those "
                     "cards, pay 4 life or put the card on top of your "
                     "library.",
        ),
    ]


register("Sylvan Library", _sylvan_library)


def _the_jolly_balloon_man() -> list[AbilitySpec]:
    """The Jolly Balloon Man (Legendary Creature — Human Clown, {1}{R}{W})

    "Haste
    {1}, {T}: Create a token that's a copy of another target creature you
    control, except it's a 1/1 red Balloon creature in addition to its
    other colors and types and it has flying and haste. Sacrifice it at
    the beginning of the next end step. Activate only as a sorcery."

    Haste is already parser-claimable. The activated ability reuses
    `CopyPermanentEffect`'s new ``set_power``/``set_toughness``
    (MEC-40, "except it's a 1/1") and ``extra_temp_keywords`` (flying,
    alongside the existing ``haste`` bool) plus its existing
    ``add_subtypes``; the delayed self-sacrifice reuses the already-general
    `CreateDelayedTriggerEffect` (RULE 603.7, step="end") the Marchesa
    V4.2 batch's Kiki-Jiki primitive established. **Documented
    simplification**: the token doesn't actually gain the printed extra
    "red" colour (`Card` has no colour-override field — colours are
    derived from mana cost, which a token has none of to override) —
    cosmetic only, no gameplay-visible effect for a token sacrificed at
    the next end step.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "copy_permanent",
                    {
                        "target_kind": "other_creature_you_control",
                        "set_power": 1, "set_toughness": 1,
                        "add_subtypes": ["Balloon"],
                        "haste": True, "extra_temp_keywords": ["flying"],
                    },
                ),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "end", "scope": "any", "capture": "created_objects",
                        "effects": [{"type": "sacrifice_specific", "params": {}}],
                        "description": "The Jolly Balloon Man: Balloon-Token am "
                                        "nächsten Endsegment opfern",
                    },
                ),
            ],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
            raw_text="{1}, {T}: Create a token that's a copy of another "
                     "target creature you control, except it's a 1/1 red "
                     "Balloon creature in addition to its other colors "
                     "and types and it has flying and haste. Sacrifice it "
                     "at the beginning of the next end step. Activate "
                     "only as a sorcery.",
        ),
    ]


register("The Jolly Balloon Man", _the_jolly_balloon_man)


def _yasharn_implacable_earth() -> list[AbilitySpec]:
    """Yasharn, Implacable Earth (Legendary Creature — Elemental Boar,
    {2}{G}{W})

    "When Yasharn enters, search your library for a basic Forest card and
    a basic Plains card, reveal those cards, put them into your hand, then
    shuffle.
    Players can't pay life or sacrifice nonland permanents to cast spells
    or activate abilities."

    The ETB is two independent single-card searches (a Forest, then a
    Plains — `SearchLibraryEffect` has no "two distinct named basics in
    one search" shape, but running it twice with different criteria is
    rules-equivalent and simpler). The restriction reuses the new
    ``cost_restriction`` static (MEC-40), checked at every cost-payment
    choke point that offers a pay-life/sacrifice component.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("search", {"criteria": {"basic": True, "type": "Forest"}, "destination": "hand"}),
                EffectSpec("search", {"criteria": {"basic": True, "type": "Plains"}, "destination": "hand"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, search your library for a basic "
                     "Forest card and a basic Plains card, reveal those "
                     "cards, put them into your hand, then shuffle.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_restriction", {"kinds": ["pay_life", "sacrifice_nonland_permanent"]})],
            raw_text="Players can't pay life or sacrifice nonland "
                     "permanents to cast spells or activate abilities.",
        ),
    ]


register("Yasharn, Implacable Earth", _yasharn_implacable_earth)


# MEC-41: [cEDH] Glarb Bloomsday's remaining 8 gaps, done to completion


def _ad_nauseam() -> list[AbilitySpec]:
    """Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value. You may repeat this
    process any number of times.

    — MEC-41. New `reveal_top_hand_lose_life_loop`/`RulesEngine.request_
    reveal_top_hand_lose_life_loop` — the engine's second open-ended,
    self-re-opening loop (see its own docstring for why it's a genuinely
    distinct shape from Lim-Dûl's Vault's `look_top_pay_life_loop`, not a
    parameterization of it): life lost varies per revealed card instead of
    a flat cost, the destination is hand instead of back into the library,
    and nothing stops the loop at 0 life (RULE 118.4 doesn't apply to a
    life-*loss* effect, only to paying life as a cost) — SBAs simply
    aren't checked mid-resolution.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_top_hand_lose_life_loop", {})],
            raw_text="Reveal the top card of your library and put that "
                     "card into your hand. You lose life equal to its "
                     "mana value. You may repeat this process any number "
                     "of times.",
        ),
    ]


register("Ad Nauseam", _ad_nauseam)


def _autumns_veil() -> list[AbilitySpec]:
    """Spells you control can't be countered by blue or black spells this
    turn, and creatures you control can't be the targets of blue or black
    spells this turn.

    — MEC-41. New `grant_cant_be_target_of_spell_color` for the second
    clause — RULE 115's own targeting restriction, deliberately narrower
    than hexproof (which also blocks *abilities*, and which this engine
    has no colour-qualified form of yet — Veil of Summer's own entry
    documents that gap) and than full protection (which also blocks
    damage/blocking/enchanting); see the effect's own docstring.
    **Documented simplification**: the first clause is modeled as
    unconditional "can't be countered this turn" (Veil of Summer's own
    `mark_your_spells_on_stack_cant_be_countered`/`arm_spell_watcher
    (repeat=True)` shape) rather than qualified by the countering spell's
    own colour — `RulesEngine._is_cant_be_countered`'s RULE 118 check has
    no notion of *what* is doing the countering at all, only whether the
    target carries the marker, and this is a strict *widening* (protects
    against every counterspell, not just blue/black ones) rather than a
    wrongly-narrower one; non-blue/black counterspells are rare enough
    that building the qualified form is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("mark_your_spells_on_stack_cant_be_countered", {}),
                EffectSpec("arm_spell_watcher", {
                    "then_specs": [{"type": "mark_cant_be_countered", "params": {}}],
                    "repeat": True,
                }),
                EffectSpec("grant_cant_be_target_of_spell_color", {
                    "colors": ["U", "B"], "selector": "creatures_you_control",
                }),
            ],
            raw_text="Spells you control can't be countered by blue or "
                     "black spells this turn, and creatures you control "
                     "can't be the targets of blue or black spells this "
                     "turn.",
        ),
    ]


register("Autumn's Veil", _autumns_veil)


def _bring_to_light() -> list[AbilitySpec]:
    """Converge — Search your library for a creature, instant, or sorcery
    card with mana value less than or equal to the number of colors of
    mana spent to cast this spell, exile that card, then shuffle. You may
    cast that card without paying its mana cost.

    — MEC-41. RULE 702.108a Converge's own count (`GameObject.colors_
    spent_to_cast`, diffed off the payer's `ManaPool` before vs. after
    payment at `RulesEngine.cast_spell`) reaches `SearchLibraryEffect`'s
    criteria the same way the existing ``"x"``/``"source_x_paid"``
    sentinels do — `RulesEngine._substitute_x`'s own criteria-walking pass
    gained a third sentinel, ``"colors_spent_to_cast"``. The exile-then-
    standing-free-cast destination (``"exile_free_cast"``) is also new
    (see `SearchLibraryEffect`'s own docstring) — distinct from the
    already-shipped ``"cast_free"`` (which casts immediately, Sunforger-
    shaped): here the found card sits in exile with a standing permission
    until the caster chooses to use it, exactly as printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {
                    "type": ["Creature", "Instant", "Sorcery"],
                    "max_mana_value": "colors_spent_to_cast",
                },
                "destination": "exile_free_cast",
                "zones": ["library"],
            })],
            raw_text="Converge — Search your library for a creature, "
                     "instant, or sorcery card with mana value less than "
                     "or equal to the number of colors of mana spent to "
                     "cast this spell, exile that card, then shuffle. You "
                     "may cast that card without paying its mana cost.",
        ),
    ]


register("Bring to Light", _bring_to_light)


def _counterbalance() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may reveal the top card of
    your library. If you do, counter that spell if it has the same mana
    value as the revealed card.

    — MEC-41. New `reveal_top_then_counter_if_mv_match` — the counter-
    target sibling of Powerbalance's own `reveal_top_then_free_cast_if_
    mv_match` (Vivi B4 batch); see that effect's docstring for the shared
    "reveal is informational" simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_counter_if_mv_match", {})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "controller": "not_you"},
            },
            raw_text="Whenever an opponent casts a spell, you may reveal "
                     "the top card of your library. If you do, counter "
                     "that spell if it has the same mana value as the "
                     "revealed card.",
        ),
    ]


register("Counterbalance", _counterbalance)


def _lazotep_quarry() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice a creature: Add one mana of any color.
    {X}{2}, {T}, Sacrifice a Desert: Exile target creature card with mana
    value X from your graveyard. Create a token that's a copy of it,
    except it's a 4/4 black Zombie. Activate only as a sorcery.

    — MEC-41. The two mana abilities are plain oracle-derived RULE 605.1a
    lines (`game/mana_abilities.py`'s `parse_mana_abilities`, read off the
    card's own printed text unconditionally regardless of catalogue
    registration — see this module's own opening docstring) and need no
    entry here; only the third needs hand-authoring. New
    `exile_own_graveyard_card_mana_value_x` (reading the ability's own
    announced ``{X}`` via `GameObject.x_paid`, now stamped for an
    activated ability's own source too — see `GameEngine.activate_
    ability`) chained via ``then_specs`` into `create_token_copy_of_
    linked_exile`. **Documented simplifications**: RULE 115's "target" is
    read as a resolve-time pick instead (see the first effect's own
    docstring for why); colour ("black") is dropped, the same
    simplification The Jolly Balloon Man's own entry accepts (`Card.
    as_copy` has no colour override).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_own_graveyard_card_mana_value_x", {
                "then_specs": [
                    {"type": "create_token_copy_of_linked_exile", "params": {
                        "set_power": 4, "set_toughness": 4, "add_subtypes": ["Zombie"],
                    }},
                ],
            })],
            cost={"text": "{X}{2}, {T}, Sacrifice a Desert", "sorcery_speed_only": True},
            raw_text="{X}{2}, {T}, Sacrifice a Desert: Exile target "
                     "creature card with mana value X from your "
                     "graveyard. Create a token that's a copy of it, "
                     "except it's a 4/4 black Zombie. Activate only as a "
                     "sorcery.",
        ),
    ]


register("Lazotep Quarry", _lazotep_quarry)


def _nissa_steward_of_elements() -> list[AbilitySpec]:
    """+2: Scry 2.
    0: Look at the top card of your library. If it's a land card or a
    creature card with mana value less than or equal to the number of
    loyalty counters on Nissa, Steward of Elements, you may put that card
    onto the battlefield.
    −6: Untap up to two target lands you control. They become 5/5
    Elemental creatures with flying and haste until end of turn. They're
    still lands.

    — MEC-41. +2 is the already-shipped plain ``scry`` effect. New
    `reveal_top_then_maybe_battlefield_if_land_or_cheap_creature` for the
    0 ability (`GameObject.loyalty`'s live count). The −6 reuses Kamahl,
    Heart of Krosa's own "target land becomes a creature until end of
    turn, still a land" `grant_until`/`type_change`+`grant_keyword` chain
    (MEC-12) verbatim, just widened to "up to two" targets — `TapEffect`'s
    own pre-existing "untap up to two target lands" shape (Snap-shaped) —
    instead of Kamahl's single one.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 2})],
            cost={"loyalty": 2},
            raw_text="+2: Scry 2.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("reveal_top_then_maybe_battlefield_if_land_or_cheap_creature", {})],
            cost={"loyalty": 0},
            raw_text="0: Look at the top card of your library. If it's a "
                     "land card or a creature card with mana value less "
                     "than or equal to the number of loyalty counters on "
                     "Nissa, Steward of Elements, you may put that card "
                     "onto the battlefield.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {
                    "target_kind": "land_you_control", "count": 2, "optional": True, "untap": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Elemental"],
                        "power": 5, "toughness": 5,
                    }},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {"keywords": ["flying", "haste"]}},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }),
            ],
            cost={"loyalty": -6},
            raw_text="−6: Untap up to two target lands you control. They "
                     "become 5/5 Elemental creatures with flying and "
                     "haste until end of turn. They're still lands.",
        ),
    ]


register("Nissa, Steward of Elements", _nissa_steward_of_elements)


def _valley_floodcaller() -> list[AbilitySpec]:
    """Flash
    You may cast noncreature spells as though they had flash.
    Whenever you cast a noncreature spell, Birds, Frogs, Otters, and Rats
    you control get +1/+1 until end of turn. Untap them.

    — MEC-41. Flash and the standing flash-permission clause are already
    parser-MODELED (copied verbatim per the hand-author-card skill's own
    guidance — `flash_permission`'s ``noncreature_only``, already built
    with this very card in mind, see its own registry comment); the third
    clause needed `PumpEffect`/`TapEffect`'s own new ``subtypes`` param —
    a ``selector`` group narrowed by a subtype list, the sibling
    `AddCountersEffect.subtypes` already had, that neither previously did.
    **Documented note**: the pump and untap clauses each carry their own
    copy of the four-subtype list rather than a cross-clause pronoun,
    since `GameContext.previous_selector` (MEC-28) only carries the bare
    selector *name*, not any subtype narrowing layered on top of it.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}, raw_text="Flash"),
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"noncreature_only": True})],
            raw_text="You may cast noncreature spells as though they had "
                     "flash.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", {
                    "power": 1, "toughness": 1, "selector": "creatures_you_control",
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
                EffectSpec("tap", {
                    "selector": "creatures_you_control", "untap": True,
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
            ],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Whenever you cast a noncreature spell, Birds, "
                     "Frogs, Otters, and Rats you control get +1/+1 until "
                     "end of turn. Untap them.",
        ),
    ]


register("Valley Floodcaller", _valley_floodcaller)


def _gifts_ungiven() -> list[AbilitySpec]:
    """Search your library for up to four cards with different names and
    reveal them. Target opponent chooses two of those cards. Put the
    chosen cards into your graveyard and the rest into your hand. Then
    shuffle.

    — MEC-41. Intuition's own two-phase `intuition_search`/`RulesEngine.
    request_intuition` shape, generalized with ``search_optional``/
    ``distinct_names``/``chosen_count``/``chosen_destination``/
    ``rest_destination`` — see that method's own docstring for exactly how
    Gifts Ungiven's shape differs from Intuition's (2 chosen instead of 1,
    and the chosen/rest destinations swapped — Gifts Ungiven's opponent
    pick sends the *chosen* pair to the graveyard and the *rest* to the
    searcher's hand, the mirror image of Intuition's "chosen → hand, rest
    → graveyard").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("intuition_search", {
                "count": 4, "search_optional": True, "distinct_names": True,
                "chosen_count": 2, "chosen_destination": "graveyard",
                "rest_destination": "hand",
            })],
            raw_text="Search your library for up to four cards with "
                     "different names and reveal them. Target opponent "
                     "chooses two of those cards. Put the chosen cards "
                     "into your graveyard and the rest into your hand. "
                     "Then shuffle.",
        ),
    ]


register("Gifts Ungiven", _gifts_ungiven)


# ---------------------------------------------------------------------------
# MEC-42: `cEDH staples`'s remaining 12 gaps
# ---------------------------------------------------------------------------


def _ashling_the_limitless() -> list[AbilitySpec]:
    """Elemental permanent spells you cast from your hand gain evoke {4} as
    you cast them. (If you cast a spell for its evoke cost, it's
    sacrificed when it enters.)
    Whenever you sacrifice a nontoken Elemental, create a token that's a
    copy of it. The token gains haste until end of turn. At the beginning
    of your next end step, sacrifice it unless you pay {W}{U}{B}{R}{G}.

    — MEC-42. Evoke (RULE 702.74) had never been built at all — Solitude's
    own catalogue entry explicitly documented it as unmodeled — so this
    card needed the real primitive, not just a per-card workaround: a new
    ``evoke`` cast branch threaded through `can_cast`/`effective_cast_cost`/
    `cast_spell` exactly like Mutate's own substitution (`GameEngine.
    _evoke_cost`, `GameObject.cast_via_evoke`), and a genuinely new "sacrifice
    it when it enters" consequence (not a replacement — its own ETB trigger
    fires first) added right after `_resolve_permanent_spell`'s
    ENTERS_BATTLEFIELD event. This closes the *mana-cost* Evoke family for
    free (Mulldrifter/Shriekmaw/Wall of Reverence-shaped, whose printed
    Evoke line is a plain mana cost parsed straight into `parametric_
    keywords` like Mutate/Escalate's own cost-bearing keywords) — but NOT
    Solitude/Endurance/Fury/Subtlety/Grief's, whose Evoke cost is "exile a
    `<color>` card from your hand" (RULE 118.9's *alternative*-cost shape,
    not a mana cost at all — the segmenter's cost-run regex never even
    claims that text into `parametric_keywords` in the first place). Those
    five still need their own alt-cost hand-authoring; their own catalogue
    entries' "Evoke isn't modeled" notes stand unchanged.
    Ashling's own *grant* ("Elemental permanent spells you cast from your
    hand gain evoke {4}") is a new `grant_evoke` static
    (`continuous.granted_evoke_cost_for`, the hand-cast-cost sibling of
    `has_standing_flash_permission`'s "permission static outside the layer
    engine" idiom, since a card still in hand has nothing for RULE 613's
    layer engine to have stamped).

    The second ability needed two more small primitives: `CopyPermanentEffect`'s
    new ``referent="trigger_event"`` (reads the firing SACRIFICE event's own
    ``instance_id`` via `GameState.find_object`, which searches every zone —
    the sacrificed creature is already in the graveyard by the time this
    trigger resolves, so neither the existing ``"source"`` nor ``"previous"``
    referent could name it), and `SacrificeUnlessPayEffect`'s new ``target``
    override (falls back to its own source, as every existing caller already
    relies on) so `CreateDelayedTriggerEffect`'s existing ``capture=
    "created_objects"`` — the same Kiki-Jiki/Puppeteer Clique "create/
    reanimate with haste, [sacrifice/exile] it at the beginning of the next
    end step" primitive — can bake the *token*, not Ashling herself, into
    the delayed "unless you pay" sacrifice. The trigger itself is RULE
    701.17's `EventType.SACRIFICE`, scoped ``sacrifice_type="elemental"`` +
    ``filter={"is_token": False}`` + ``condition={"subject": "you"}`` —
    entirely off the event's own existing payload, no new trigger-condition
    vocabulary needed.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_evoke", {"cost": "{4}", "subtype": "elemental"})],
            raw_text="Elemental permanent spells you cast from your hand "
                     "gain evoke {4} as you cast them. (If you cast a "
                     "spell for its evoke cost, it's sacrificed when it "
                     "enters.)",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": None, "referent": "trigger_event", "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [
                        {"type": "sacrifice_unless_pay", "params": {"cost": "{W}{U}{B}{R}{G}"}},
                    ],
                    "description": "Ashling, the Limitless: Kopie opfern, "
                                   "außer {W}{U}{B}{R}{G} wird bezahlt",
                }),
            ],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "elemental",
                "filter": {"is_token": False},
            },
            raw_text="Whenever you sacrifice a nontoken Elemental, create "
                     "a token that's a copy of it. The token gains haste "
                     "until end of turn. At the beginning of your next "
                     "end step, sacrifice it unless you pay "
                     "{W}{U}{B}{R}{G}.",
        ),
    ]


register("Ashling, the Limitless", _ashling_the_limitless)


def _derevi_empyrial_tactician() -> list[AbilitySpec]:
    """Flying
    When Derevi enters and whenever a creature you control deals combat
    damage to a player, you may tap or untap target permanent.
    {1}{G}{W}{U}: Put Derevi onto the battlefield from the command zone.

    — MEC-42. Flying is a plain printed keyword, recognized independent
    of catalogue registration. The shared "you may tap or untap target
    permanent" clause needed a genuine new choice — `TapEffect`'s existing
    ``untap`` bool is fixed at bind time, but this is a real decision at
    resolution, layered on top of RULE 115's own "up to one" target
    optionality — so `TapEffect.choose_tap_or_untap` opens a new, small
    `RulesEngine.request_tap_or_untap_choice` `pending_choice` instead of
    applying a fixed tap/untap directly; two `AbilitySpec`s (ETB self,
    and the already-general RULE 603.1 group-subject "a creature you
    control deals combat damage to a player" shape Bident of Thassa/
    Deepfathom Skulker/Rapacious Guest already use) share the same effect
    *shape*, each its own fresh `EffectSpec` instance.

    Documented simplification: the third ability — "{1}{G}{W}{U}: Put
    Derevi onto the battlefield from the command zone." — is a genuinely
    different mechanism from RULE 903's ordinary command-zone *casting*
    (which this engine already fully supports, tax and all): a bare
    battlefield-entry with no stack, spell, or ETB-timing restriction,
    activated from a zone (command) no other activated ability in this
    engine can be offered from. Left unmodeled — RULE 903's normal
    "cast Derevi from the command zone" path already reaches the same
    outcome (Derevi returns to the battlefield), just through the stack
    and at full (taxed) cost rather than this flat discount, so nothing
    about the card is actually unplayable without it.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, you may tap or untap target permanent.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "permanent", "optional": True, "choose_tap_or_untap": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "controller": "you", "other": False},
                "filter": {"combat": True, "is_player": True},
            },
            raw_text="Whenever a creature you control deals combat damage "
                     "to a player, you may tap or untap target permanent.",
        ),
    ]


register("Derevi, Empyrial Tactician", _derevi_empyrial_tactician)


def _dauthi_voidwalker() -> list[AbilitySpec]:
    """Shadow (This creature can block or be blocked by only creatures
    with shadow.)
    If a card would be put into an opponent's graveyard from anywhere,
    instead exile it with a void counter on it.
    {T}, Sacrifice this creature: Choose an exiled card an opponent owns
    with a void counter on it. You may play it this turn without paying
    its mana cost.

    — MEC-42. Shadow is a plain printed evasion keyword, already
    recognized independent of catalogue registration. The graveyard
    redirect is a new standing `void_counter_redirect` static
    (`continuous.void_counter_redirect_controller_for`, the same
    battlefield-static-scan idiom Opposition Agent's `search_redirect`
    already uses), checked from `RulesEngine._move_to_graveyard` — the one
    choke point every graveyard-bound move funnels through — right
    alongside the existing Lurrus/Yawgmoth's Will redirects there;
    `GameState.void_counter_holder` (``instance_id -> holder player_id``)
    is the marker itself, never swept. The activated ability's own
    `ChooseVoidCounterCardEffect` gathers the live candidate pool (every
    opponent's exile zone, filtered to that marker) and reuses MEC-20's
    already-general ``"grant_free_cast"`` chooser action — a same-turn
    free-cast window, exactly what "you may play it this turn without
    paying its mana cost" asks for.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("void_counter_redirect", {})],
            raw_text="If a card would be put into an opponent's graveyard "
                     "from anywhere, instead exile it with a void counter "
                     "on it.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("choose_void_counter_card", {})],
            cost={"text": "{T}, Sacrifice this creature"},
            raw_text="{t}, sacrifice ~: choose an exiled card an opponent "
                     "owns with a void counter on it. you may play it "
                     "this turn without paying its mana cost.",
        ),
    ]


register("Dauthi Voidwalker", _dauthi_voidwalker)


def _mana_crypt() -> list[AbilitySpec]:
    """At the beginning of your upkeep, flip a coin. If you lose the flip,
    this artifact deals 3 damage to you.
    {T}: Add {C}{C}.

    — MEC-42. `CoinFlipEffect`'s already-established "damage with
    ``selector='controller'``" shape (Mana Vault's own "deals 1 damage to
    you", Vivi B4 batch) at Mana Crypt's own printed amount; no win
    branch (losing the flip is the only outcome with a consequence). The
    mana ability needs no catalogue entry at all — `game/mana_abilities.py`
    reads a card's plain "{T}: Add …" text unconditionally, independent of
    catalogue registration (confirmed by Lazotep Quarry, MEC-41).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("coin_flip", {
                "lose_effects": [{"type": "damage", "params": {"selector": "controller", "amount": 3}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="At the beginning of your upkeep, flip a coin. If "
                     "you lose the flip, ~ deals 3 damage to you.",
        ),
    ]


register("Mana Crypt", _mana_crypt)


def _march_of_swirling_mist() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any number
    of blue cards from your hand. This spell costs {2} less to cast for
    each card exiled this way.
    Up to X target creatures phase out. (While they're phased out,
    they're treated as though they don't exist. Each one phases in before
    its controller untaps during their next untap step.)

    — MEC-42. Neither clause had a primitive: the additional cost needed a
    genuine RULE 601.2b "announce a value, adjust cost, then pay it"
    shape (mirroring Kicker's own sequencing exactly, just subtracting
    generic instead of adding it) — new `cast_spell`/`can_cast`/`effective_
    cast_cost` param ``exile_discount``, gated by a new `exile_discount_
    cost` static (`continuous.exile_discount_spec_for`, read straight off
    the spell's own `static_effects` in hand, the same way Delve/
    Affinity's own printed "costs less" static already is) so the
    mechanism stays generic rather than hardcoded to blue/{2}. "Up to X
    target creatures phase out" needed `PhaseOutEffect` widened from a
    single fixed target to a real multi-target count (`TargetSpec.
    count_selector`'s new ``"source_x_paid"`` entry, reading `GameObject.
    x_paid` — the spell's own announced {X} — fresh at target-gathering
    time, the same "read a live count, not a printed one" idiom Goad's
    own count-selector already established for a different source).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "U", "generic_per_card": 2})],
            raw_text="As an additional cost to cast this spell, you may "
                     "exile any number of blue cards from your hand. "
                     "This spell costs {2} less to cast for each card "
                     "exiled this way.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("phase_out", {
                "target_kind": "creature", "optional": True, "count_selector": "source_x_paid",
            })],
            raw_text="Up to X target creatures phase out.",
        ),
    ]


register("March of Swirling Mist", _march_of_swirling_mist)


def _orcish_bowmasters() -> list[AbilitySpec]:
    """Flash
    When this creature enters and whenever an opponent draws a card
    except the first one they draw in each of their draw steps, this
    creature deals 1 damage to any target. Then amass Orcs 1.

    — MEC-42. Flash is a plain printed keyword. "Except the first one
    they draw in each of their draw steps" is MEC-32's own `EventType.
    DRAW` ``first_in_draw_step`` flag (`RulesEngine._single_draw`, already
    built for Notion Thief/Chains of Mephistopheles' replacement effects)
    — the first *trigger* consumer of it, via a plain ``filter`` exact-
    match (`{"first_in_draw_step": False}`) rather than a replacement
    condition. Amass (RULE 701.48) had no primitive at all yet — new
    `AmassEffect`. Two `AbilitySpec`s (ETB self, and the opponent-scoped
    DRAW trigger) share the same effect *shape*, each its own fresh
    `EffectSpec` instance, the same split Derevi's own ETB-and-combat-
    damage pair uses right above.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, ~ deals 1 damage to any target. "
                     "Then amass Orcs 1.",
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
                EffectSpec("amass", {"subtype": "Orc", "count": 1}),
            ],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "filter": {"first_in_draw_step": False},
            },
            raw_text="Whenever an opponent draws a card except the first "
                     "one they draw in each of their draw steps, ~ deals "
                     "1 damage to any target. Then amass Orcs 1.",
        ),
    ]


register("Orcish Bowmasters", _orcish_bowmasters)


def _praetors_grasp() -> list[AbilitySpec]:
    """Search target opponent's library for a card and exile it face down.
    Then that player shuffles. You may play that card for as long as it
    remains exiled.

    — MEC-42. RULE 701.19a "search **target opponent's** library" needed
    `SearchLibraryEffect`'s own controller (who actually picks) to differ
    from the library it searches/shuffles (the RULE 115 target) — new
    ``player_from_target`` (resolves ``player`` to the targeted opponent)
    threading a real ``chooser`` through `RulesEngine.request_search`
    down to `_search_choice`/`_finish_search`/`_put_searched_card`
    (``player_id`` in the pending choice becomes "who answers", a new
    ``library_owner_id`` carries "whose library" — the general "who's
    searching vs. who owns the library" split, reusable by any future
    Bribery/Mind's Desire-shaped card). The new ``"exile_face_down_
    standing_cast"`` destination combines the existing face-down-in-exile
    marker (Beseech the Mirror) with a standing (never-swept)
    `GameState.exile_cast_condition` grant to the *chooser*, not the
    searched player — the ordinary-cost sibling of Bring to Light's own
    same-player ``"exile_free_cast"`` (MEC-41). Also fixed a real, general
    gap found on the way: `can_play_land` never checked `_has_conditional_
    exile_permission` at all, so this permission (or Lukka's own) could
    never actually offer a land.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": "", "destination": "exile_face_down_standing_cast",
                "player_from_target": True,
            })],
            raw_text="Search target opponent's library for a card and "
                     "exile it face down. Then that player shuffles. You "
                     "may play that card for as long as it remains exiled.",
        ),
    ]


register("Praetor's Grasp", _praetors_grasp)


def _sevinnes_reclamation() -> list[AbilitySpec]:
    """Return target permanent card with mana value 3 or less from your
    graveyard to the battlefield. If this spell was cast from a
    graveyard, you may copy this spell and may choose a new target for
    the copy.
    Flashback {4}{W} (You may cast this card from your graveyard for its
    flashback cost. Then exile it.)

    — MEC-42. Flashback is a plain printed cost-bearing keyword, already
    read straight off `parametric_keywords` independent of catalogue
    registration. The reanimation half is `ReturnFromGraveyardEffect`'s
    already-general ``target_kind="graveyard_permanent"``/``max_mana_
    value`` (RULE 701.3 family). "If this spell was cast from a
    graveyard, you may copy this spell..." needed a genuine new self-copy
    primitive — new `RulesEngine.copy_self_spell`, the sibling of `copy_
    spell` that builds the copy `StackItem` directly off this spell's own
    `GameObject` rather than looking up a live stack entry, since by the
    time this trailing clause resolves the original has already been
    popped off `GameState.stack` for resolution. Reads `GameObject.
    cast_via_flashback` directly (still true at this point — the "exile
    instead of graveyard" clearing happens only after every effect,
    this one included, has resolved). **Documented simplification**: "may
    choose a new target" keeps the original's own already-gathered target
    by default (RULE 707.10c's default outcome) rather than opening a
    genuine new-target choice — the same "no real new-targeting yet"
    simplification `CopySpellEffect` already documents for every other
    copy-a-spell card in this engine, not a fresh gap; reanimating the
    same (now already-battlefield) permanent a second time is simply a
    no-op, same as a real player declining to bother re-choosing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "max_mana_value": 3,
                    "destination": "battlefield",
                }),
                EffectSpec("copy_self_if_cast_from_graveyard", {}),
            ],
            raw_text="Return target permanent card with mana value 3 or "
                     "less from your graveyard to the battlefield. If "
                     "this spell was cast from a graveyard, you may copy "
                     "this spell and may choose a new target for the "
                     "copy.",
        ),
    ]


register("Sevinne's Reclamation", _sevinnes_reclamation)


def _teferi_time_raveler() -> list[AbilitySpec]:
    """Each opponent can cast spells only any time they could cast a
    sorcery.
    +1: Until your next turn, you may cast sorcery spells as though they
    had flash.
    −3: Return up to one target artifact, creature, or enchantment to
    its owner's hand. Draw a card.

    — MEC-42. The static needed a genuinely new restriction — new
    `sorcery_speed_only` (`continuous.forced_sorcery_speed_only`,
    consulted directly in `GameEngine.can_cast`'s own timing computation,
    forcing RULE 601.3b sorcery-speed timing for a restricted opponent
    even over an instant/Flash spell) — the mirror image of `flash_
    permission`'s existing "permission static outside the layer engine"
    treatment. The +1 reuses that same `flash_permission` static with a
    widened ``type_filter`` (``"sorcery"``, `continuous.has_standing_
    flash_permission`'s own word-list check) wrapped in `GrantUntilEffect`
    at the ``"your_next_turn"`` duration RULE 611.2b already supports.
    The −3 is fully `MODELED` by the oracle-text parser already
    (`ReturnToHandEffect` + `DrawCardEffect`); reused as-is via the
    `hand-author-card` skill's own `reuse` command rather than re-derived.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("sorcery_speed_only", {})],
            raw_text="Each opponent can cast spells only any time they "
                     "could cast a sorcery.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "flash_permission", "params": {"type_filter": ["sorcery"]}},
                "duration": "your_next_turn",
                "target_kind": None,
            })],
            cost={"loyalty": 1},
            raw_text="+1: Until your next turn, you may cast sorcery "
                     "spells as though they had flash.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_to_hand", {"target_kind": "permanent", "optional": True}), EffectSpec("draw", {"count": 1})],
            cost={"loyalty": -3},
            raw_text="−3: return up to 1 target artifact, creature, or "
                     "enchantment to its owner's hand. draw a card.",
        ),
    ]


register("Teferi, Time Raveler", _teferi_time_raveler)


def _touch_the_spirit_realm() -> list[AbilitySpec]:
    """When this enchantment enters, exile up to one target artifact or
    creature until this enchantment leaves the battlefield.
    Channel — {1}{W}, Discard this card: Exile target artifact or
    creature. Return it to the battlefield under its owner's control at
    the beginning of the next end step.

    — MEC-42. The ETB half is the established O-Ring shape (`ExileEffect
    (remember=True)` + `ReturnLinkedExileEffect` on LEAVES_BATTLEFIELD,
    Shire Shirriff/Leonin Relic-Warder-shaped), just a new union target
    kind — `targeting`'s new ``"artifact_or_creature"``, the same "two
    single-type kinds getting their own combined kind" idiom
    ``artifact_or_enchantment`` already established. Channel (RULE
    702.29) needed no new primitive at all: its "Discard this card:" cost
    is already `ActivationCost.discard_self`, already fully wired for a
    hand-zone activation (`GameEngine.can_activate`'s own documented
    Channel/Cycling branch) — just never bound to a real card doing
    anything but Cycling before. Its own return clause reuses `Return
    LinkedExileEffect` again, this time fired from a plain
    `create_delayed_trigger` (``step="end", scope="any"``) rather than a
    LEAVES_BATTLEFIELD trigger, since nothing here is attached to a
    permanent still on the battlefield to fire that trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "artifact_or_creature", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, exile up to one target artifact or "
                     "creature until ~ leaves the battlefield.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ leaves the battlefield, return the exiled "
                     "card.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "artifact_or_creature", "remember": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "effects": [{"type": "return_linked_exile", "params": {}}],
                    "description": "Touch the Spirit Realm: exiliertes "
                                   "Objekt zurückbringen",
                }),
            ],
            cost={"text": "{1}{W}, Discard this card"},
            raw_text="Channel — {1}{w}, discard this card: exile target "
                     "artifact or creature. return it to the battlefield "
                     "under its owner's control at the beginning of the "
                     "next end step.",
        ),
    ]


register("Touch the Spirit Realm", _touch_the_spirit_realm)


def _tymna_the_weaver() -> list[AbilitySpec]:
    """Lifelink
    At the beginning of each of your postcombat main phases, you may pay
    X life, where X is the number of opponents that were dealt combat
    damage this turn. If you do, draw X cards.
    Partner (You can have two commanders if both have partner.)

    — MEC-42. Lifelink/Partner are plain printed keywords, recognized
    independent of catalogue registration (Partner is a legality flag
    `services/commander_legality.py` reads, not a gameplay ability with
    anything to bind). The trigger's own X needed a genuine new count
    selector — `continuous.count_selector`'s new
    ``"opponents_dealt_combat_damage_this_turn"``, aggregating `GameState.
    combat_damage_to_players_this_turn` (RULE 120.3, previously only ever
    read per-source) across every source that hit this turn, unlike that
    field's own keyed-by-source shape. The pay-X-draw-X body is the new
    `PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect` — computes X
    once, then opens the already-general `RulesEngine.request_pay_cost_
    then` choice with a dynamically built cost/effect pair, since neither
    the printed cost text nor the effect amount is a fixed value.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_life_equal_to_opponents_combat_damaged_draw_that_many", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"},
            raw_text="At the beginning of each of your postcombat main "
                     "phases, you may pay X life, where X is the number "
                     "of opponents that were dealt combat damage this "
                     "turn. If you do, draw X cards.",
        ),
    ]


register("Tymna the Weaver", _tymna_the_weaver)


# ---------------------------------------------------------------------------
# MEC-43: `cEDH staples 2`'s undiagnosed remainder — first batch, near-free
# reuses of primitives shipped for entirely different cards.
# ---------------------------------------------------------------------------


def _contamination() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this enchantment unless
    you sacrifice a creature.
    If a land is tapped for mana, it produces {B} instead of any other
    type and amount.

    — MEC-43. The upkeep clause is already fully `MODELED` by the
    oracle-text parser (`sacrifice_unless_pay`); reused as-is. The second
    clause is an exact param match for `mana_type_override` (built for
    Damping Sphere's "if a land is tapped for 2 or more mana, {C}
    instead") — unscoped (``affects="all_lands"``, matching Damping
    Sphere's own unqualified reach) with ``min_amount=1`` instead of 2
    and ``to="B"`` instead of ``"C"``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "sacrifice a creature"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="at the beginning of your upkeep, sacrifice ~ unless you sacrifice a creature.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("mana_type_override", {"min_amount": 1, "to": "B"})],
            raw_text="If a land is tapped for mana, it produces {B} "
                     "instead of any other type and amount.",
        ),
    ]


register("Contamination", _contamination)


def _leveler() -> list[AbilitySpec]:
    """When this creature enters, exile all cards from your library.

    — MEC-43. `ExileLibraryEffect`/`"exile_library"` was already
    registered (built for Paradigm Shift) but had no real consumer yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_library", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, exile all cards from your library.",
        ),
    ]


register("Leveler", _leveler)


def _natural_order() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a green
    creature.
    Search your library for a green creature card, put it onto the
    battlefield, then shuffle.

    — MEC-43. The search half is already fully `MODELED` by the
    oracle-text parser; reused as-is. The additional cost needed a new
    color+type compound sacrifice-cost sentinel — `_matches_sacrifice_
    type`'s new ``"<color>_creature"`` branch (a catalogue-chosen
    sentinel, not derived from printed text by a parser handler),
    matched against the object's own layer-5 derived colours.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "G"}, "destination": "battlefield",
            })],
            additional_cost={"sacrifice": "green_creature"},
            raw_text="As an additional cost to cast this spell, "
                     "sacrifice a green creature. Search your library "
                     "for a green creature card, put it onto the "
                     "battlefield, then shuffle.",
        ),
    ]


register("Natural Order", _natural_order)


def _magda_brazen_outlaw() -> list[AbilitySpec]:
    """Other Dwarves you control get +1/+0.
    Whenever a Dwarf you control becomes tapped, create a Treasure
    token.
    Sacrifice five Treasures: Search your library for an artifact or
    Dragon card, put that card onto the battlefield, then shuffle.

    — MEC-43. The anthem and the tap-trigger are already fully `MODELED`
    by the oracle-text parser; reused as-is. The activated ability is
    `costs.ActivationCost.sacrifice_count`'s already-shipped ``(count,
    subtype)`` shape (Trail of Crumbs/Cauldron Familiar-family, ``(3,
    "food")``) at Magda's own ``(5, "Treasure")``, plus the already-
    general `SearchLibraryEffect` with an "artifact or Dragon" criteria
    union.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 0, "affects": "other_creatures_you_control", "subtype": "Dwarf",
            })],
            raw_text="Other Dwarves you control get +1/+0.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.TAPPED,
                "condition": {
                    "subject": "group", "subtypes": ["dwarf"], "nontoken": False,
                    "controller": "you", "other": False,
                },
            },
            raw_text="Whenever a Dwarf you control becomes tapped, "
                     "create a Treasure token.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": ["Artifact", "Dragon"]}, "destination": "battlefield",
            })],
            cost={"sacrifice_count": (5, "treasure")},
            raw_text="Sacrifice five Treasures: Search your library for "
                     "an artifact or Dragon card, put that card onto "
                     "the battlefield, then shuffle.",
        ),
    ]


register("Magda, Brazen Outlaw", _magda_brazen_outlaw)


def _unmarked_grave() -> list[AbilitySpec]:
    """Search your library for a nonlegendary card, put that card into
    your graveyard, then shuffle.

    — MEC-43. Plain `SearchLibraryEffect(destination="graveyard")`; only
    needed a new ``"nonlegendary": True`` key in the search-criteria
    vocabulary (`models/card_query.py`), the negation of the already-
    supported "legendary" type-line word.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {"criteria": {"nonlegendary": True}, "destination": "graveyard"})],
            raw_text="Search your library for a nonlegendary card, put "
                     "that card into your graveyard, then shuffle.",
        ),
    ]


register("Unmarked Grave", _unmarked_grave)


def _unsubstantiate() -> list[AbilitySpec]:
    """Return target spell or creature to its owner's hand.

    — MEC-43. Reuses `RulesEngine.bounce_spell_or_permanent` (Sink into
    Stupor/Hullbreaker Horror's own "still on the stack" bounce,
    MEC-12 M-K) — that method is already fully generic (falls back to
    ordinary `return_to_hand` whenever the target *isn't* currently a
    spell on the stack), so only a new, narrower `targeting` union kind
    (``"spell_or_creature"``, the "target spell or ability" (ENG-26)
    idiom applied to a permanent instead of an ability) was needed, not a
    new resolve-time mechanism.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_creature", "spell_or_permanent": True,
            })],
            raw_text="Return target spell or creature to its owner's hand.",
        ),
    ]


register("Unsubstantiate", _unsubstantiate)


def _teferi_master_of_time() -> list[AbilitySpec]:
    """You may activate loyalty abilities of Teferi on any player's turn
    any time you could cast an instant.
    +1: Draw a card, then discard a card.
    −3: Target creature you don't control phases out.
    −10: Take two extra turns after this one.

    — MEC-43. The instant-speed activation clause reuses The Wandering
    Emperor's own `conditional_flash` mechanism (`GameEngine._can_
    activate_loyalty`), just with MEC-44's already-shipped
    ``"unconditional": True`` member (Necromancy's own "as though it had
    flash" with no gate at all) instead of Emperor's own "entered this
    turn" gate — carried on the first loyalty ability below, the same
    "`effect_binder.attach_to_object` scans every spec regardless of
    which one carries it" convention Emperor's own entry documents.
    −3 is `PhaseOutEffect(target_kind="creature_you_dont_control")`
    (already-general). −10 is `TakeExtraTurnEffect` listed twice — it
    has no ``count`` param, so "two" is just two queued turns.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1}), EffectSpec("discard", {"count": 1})],
            cost={"loyalty": 1},
            conditional_flash={"unconditional": True},
            raw_text="+1: Draw a card, then discard a card.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {"target_kind": "creature_you_dont_control"})],
            cost={"loyalty": -3},
            raw_text="−3: Target creature you don't control phases out.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("take_extra_turn", {}), EffectSpec("take_extra_turn", {})],
            cost={"loyalty": -10},
            raw_text="−10: Take two extra turns after this one.",
        ),
    ]


register("Teferi, Master of Time", _teferi_master_of_time)


def _march_of_otherworldly_light() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any
    number of white cards from your hand. This spell costs {2} less to
    cast for each card exiled this way.
    Exile target artifact, creature, or enchantment with mana value X
    or less.

    — MEC-43. The additional cost is an exact recolor of March of
    Swirling Mist's own `exile_discount_cost` static (MEC-42) — white
    instead of blue, otherwise identical. The exile clause is an
    ordinary targeted `ExileEffect` with an MV filter, off the spell's
    own announced X (`max_mana_value_selector`-style — read fresh via
    the same `_substitute_x` sentinel machinery already generalized in
    MEC-41 for Bring to Light).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "W", "generic_per_card": 2})],
            raw_text="As an additional cost to cast this spell, you may "
                     "exile any number of white cards from your hand. "
                     "This spell costs {2} less to cast for each card "
                     "exiled this way.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "artifact_creature_or_enchantment", "max_mana_value": "x",
            })],
            raw_text="Exile target artifact, creature, or enchantment "
                     "with mana value X or less.",
        ),
    ]


register("March of Otherworldly Light", _march_of_otherworldly_light)


# MEC-42: cEDH staples's last card, Delay


def _delay() -> list[AbilitySpec]:
    """Counter target spell. If the spell is countered this way, exile it
    with three time counters on it instead of putting it into its owner's
    graveyard. If it doesn't have suspend, it gains suspend. (At the
    beginning of its owner's upkeep, they remove a time counter. When the
    last is removed, they may play it without paying its mana cost. If
    it's a creature, it has haste.)

    — MEC-42. `parser_probe.py blocked` confirms this exact template is a
    genuine singleton (SOLO on 1, no other cached card shares it), but it
    was left open for two prior batches because closing it correctly needs
    RULE 702.62 Suspend's own time-counter/cast-on-zero mechanism, which
    had never been built at all (only keyword-recognized) — this batch
    builds that as a real, general primitive rather than special-casing
    Delay alone:

    * `RulesEngine.counter_spell`'s new `suspend_time_counters` param
      (threaded through `counter_unless_pays`, `CounterSpellEffect`'s own
      new `suspend_instead`, and `GameContext.counter`) redirects the
      countered spell to exile with N time counters instead of the
      graveyard, and stamps `GameObject.granted_suspend` when the card has
      no printed Suspend of its own (RULE 702.62's "if it doesn't have
      suspend, it gains suspend").
    * RULE 702.62a's second and third abilities — "at the beginning of your
      upkeep, remove a time counter" and "when the last is removed, you may
      cast it without paying its mana cost" — are collected fresh every
      owner's upkeep by `_collect_suspend_triggers` (`game/rules/
      triggers_mixin.py`) rather than bound once at load time: a suspended
      card sits in exile, never a permanent, so `_collect_triggers`'s
      battlefield-only scan can never see it, and Suspend can be *granted*
      mid-game with nothing printed on the card to have pre-attached a
      bound `TriggeredAbility` to in the first place — the same "no
      permanent to hang an ability off" shape `_collect_inherent_triggers`
      already uses for Monarch/Initiative. `SuspendUpkeepEffect`
      (`game/effects.py`) is the combined atomic action (remove one
      counter; at zero, open the free-cast window), the same "remove, then
      branch on empty" shape Vanishing's own upkeep pair
      (`RemoveCounterOrSacrificeEffect`) already established.
    * The free-cast offer itself reuses `RulesEngine.grant_free_cast_
      window_from_exile` — the same same-turn-only standing permission
      Rebound's own delayed half already grants (`ReboundFreeCastWindow
      Effect`), a documented fidelity trade-off for "no synchronous
      mid-resolution yes/no chooser" rather than a new one invented for
      Suspend. "If you cast a creature spell this way, it gains haste" is
      `GameObject.granted_suspend_haste`, stamped alongside the window and
      consumed once at resolution exactly like `cast_via_evoke`.

    Deliberately *not* built: RULE 702.62a's own *first* ability — "pay the
    Suspend cost rather than the mana cost, exiling it with N time counters,
    from hand" — since Delay's own path never uses it (the object is
    exiled directly, already carrying its counters) and no other card in
    this project's tracked cube pools currently prints a bare "Suspend
    N—cost" that would need it; a real, separately-scoped gap if a future
    card needs it, not silently assumed done.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"suspend_instead": 3})],
            raw_text=(
                "Counter target spell. If the spell is countered this way, "
                "exile it with three time counters on it instead of "
                "putting it into its owner's graveyard. If it doesn't have "
                "suspend, it gains suspend."
            ),
        ),
    ]


register("Delay", _delay)


def _gaddock_teeg() -> list[AbilitySpec]:
    """Noncreature spells with mana value 4 or greater can't be cast.
    Noncreature spells with {X} in their mana costs can't be cast.

    — MEC-43, one of `cast_prohibition`'s two "shared primitive" clusters:
    the first clause needed a **literal** threshold (`max_mana_value`, new
    — every prior `cast_prohibition` card read a dynamic `count_selector`
    instead), the second a wholly independent flat check on the printed
    cost string (`has_x_cost`) unrelated to mana value at all. Two
    separate statics rather than one combined check, since a spell can
    trip either clause without the other (a noncreature {X} spell of mana
    value 2 is still illegal). ``scope="all"``: unlike the "opponents"
    default this static family started with, Gaddock Teeg restricts
    *every* player, its own controller included.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "max_mana_value": 3,
            })],
            raw_text="Noncreature spells with mana value 4 or greater "
                     "can't be cast.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "has_x_cost": True,
            })],
            raw_text="Noncreature spells with {X} in their mana costs "
                     "can't be cast.",
        ),
    ]


register("Gaddock Teeg", _gaddock_teeg)


def _sanctum_prelate() -> list[AbilitySpec]:
    """As this creature enters, choose a number.
    Noncreature spells with mana value equal to the chosen number can't
    be cast.

    — MEC-43. The other half of `cast_prohibition`'s literal-threshold
    cluster: an "equal to" comparison (`cmp="eq"`, new) against a number
    picked as this enters, not a fixed constant — `ChooseNumberReplacement`
    (new, a fifth `enter_choice_effects` sibling of `ChooseCreatureType
    Replacement`/`ChooseColorReplacement`/`ChooseNamedModeReplacement`/
    `ChooseCardNameReplacement`) offers a free-text numeric pick the same
    way `ChooseCardNameReplacement` offers a free-text name, stamping
    `GameObject.chosen_number`; `max_mana_value`'s new ``"chosen_number"``
    sentinel reads it back live off this object every check, so a Replay-
    mode edit to the choice is honoured immediately.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_number_on_enter", {})],
            raw_text="As this creature enters, choose a number.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True,
                "max_mana_value": "chosen_number", "cmp": "eq",
            })],
            raw_text="Noncreature spells with mana value equal to the "
                     "chosen number can't be cast.",
        ),
    ]


register("Sanctum Prelate", _sanctum_prelate)


def _chalice_of_the_void() -> list[AbilitySpec]:
    """This artifact enters with X charge counters on it.
    Whenever a player casts a spell with mana value equal to the number
    of charge counters on this artifact, counter that spell.

    — MEC-43, the "counter-trigger sibling" of Gaddock Teeg/Sanctum
    Prelate's `cast_prohibition` cluster: unlike those two, Chalice
    doesn't stop the spell from being *cast* at all — it lets it be cast
    and then counters it, RULE 701.5's actual mechanism, so this is a
    triggered ability rather than a third `cast_prohibition`. The first
    clause needs no code at all: `ability_catalogue.entry_counters`
    (`parser.oracle.catalogue.counters.entry_counters`) already recognizes
    "enters with X `<kind>` counters" generically off the card's own raw
    oracle text at every battlefield-entry site, independent of whether
    the card has a catalogue registration — confirmed live against this
    card's cached text. The trigger reuses `CounterSpellEffect.
    target_from_trigger_event` (Vexing Bauble's own "if no mana was spent
    to cast it, counter that spell" shape) for "counter *that* spell" —
    the very spell whose cast fired this ability, not a chosen target —
    and a new `mana_value_equals_source_counters` trigger-condition key
    (`effect_binder._trigger_condition`) for the live "mana value == this
    permanent's own charge-counter count" comparison, since no existing
    predicate reads a counter count off the ability's own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"target_from_trigger_event": "instance_id"})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "mana_value_equals_source_counters": "charge",
            },
            raw_text="Whenever a player casts a spell with mana value "
                     "equal to the number of charge counters on this "
                     "artifact, counter that spell.",
        ),
    ]


register("Chalice of the Void", _chalice_of_the_void)


def _ethersworn_canonist() -> list[AbilitySpec]:
    """Each player who has cast a nonartifact spell this turn can't cast
    additional nonartifact spells.

    — MEC-43, `cast_prohibition`'s second shared-primitive cluster: a
    boolean-flag restriction rather than any mana-value comparison at
    all — "already cast a nonartifact spell this turn", a different shape
    from the literal/selector mana-value family Gaddock Teeg/Sanctum
    Prelate use. `GameState.nonartifact_spells_cast_this_turn` (new, the
    nonartifact-scoped sibling of `noncreature_spells_cast_this_turn`,
    incremented in lockstep by the same `RulesEngine._track_spell_cast`)
    backs a new `min_count_selector` param: prohibited once that count is
    >= 1 **for the casting player**, checked before the current cast's own
    increment lands (the same "already reflects the very spell" ordering
    every other `spells_cast_this_turn`-family check relies on, so a
    player's own *first* nonartifact spell is never wrongly caught). RULE
    613.6-adjacent ``scope="all"``: the restriction binds every player,
    Canonist's own controller included, exactly like Gaddock Teeg.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "nonartifact": True,
                "min_count_selector": "nonartifact_spells_cast_this_turn",
            })],
            raw_text="Each player who has cast a nonartifact spell this "
                     "turn can't cast additional nonartifact spells.",
        ),
    ]


register("Ethersworn Canonist", _ethersworn_canonist)


def _birthing_pod() -> list[AbilitySpec]:
    """{1}{G/P}, {T}, Sacrifice a creature: Search your library for a
    creature card with mana value equal to 1 plus the sacrificed
    creature's mana value, put that card onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, the other shared-primitive cluster: `GameObject.sacrificed_
    cost_mana_value` was only ever stamped for a *spell's* RULE 601.2b
    additional cost (`_pay_additional_cast_cost`) — an *activated
    ability's* own sacrifice cost (`_pay_activation_cost`) stamped
    nothing at all. Mirroring the same stamp there (right after the
    victim reaches the graveyard, cleared unconditionally at the top of
    every payment the same way the cast-cost site does) is the one new
    piece; `SearchLibraryEffect.mana_value_from` (Eldritch Evolution/
    Neoform's own "N plus the sacrificed X's mana value" shape) already
    reads it generically off whatever `GameObject` an effect's ``source``
    resolves to — an activated ability's own permanent, here — with no
    changes needed on the search side at all.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{1}{G/P}, {T}, Sacrifice a creature", "sorcery_speed_only": True},
            raw_text="{1}{G/P}, {T}, Sacrifice a creature: Search your "
                     "library for a creature card with mana value equal "
                     "to 1 plus the sacrificed creature's mana value, put "
                     "that card onto the battlefield, then shuffle. "
                     "Activate only as a sorcery.",
        ),
    ]


register("Birthing Pod", _birthing_pod)


def _oswald_fiddlebender() -> list[AbilitySpec]:
    """Magical Tinkering — {W}, {T}, Sacrifice an artifact: Search your
    library for an artifact card with mana value equal to 1 plus the
    sacrificed artifact's mana value, put it onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, Birthing Pod's own artifact-scoped mirror, closing the same
    activation-cost sacrifice-stamp cluster's second card. "Magical
    Tinkering" is a bare ability word (RULE 207.2c) — flavour only, no
    rules meaning, so it's dropped rather than modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Artifact"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{W}, {T}, Sacrifice an artifact", "sorcery_speed_only": True},
            raw_text="Magical Tinkering — {W}, {T}, Sacrifice an "
                     "artifact: Search your library for an artifact card "
                     "with mana value equal to 1 plus the sacrificed "
                     "artifact's mana value, put it onto the battlefield, "
                     "then shuffle. Activate only as a sorcery.",
        ),
    ]


register("Oswald Fiddlebender", _oswald_fiddlebender)


def _chandras_incinerator() -> list[AbilitySpec]:
    """This spell costs {X} less to cast, where X is the total amount of
    noncombat damage dealt to your opponents this turn.
    Trample
    Whenever a source you control deals noncombat damage to an opponent,
    this creature deals that much damage to target creature or
    planeswalker that player controls.

    — MEC-45 (Ojer cEDH's last gap). The cost reduction reuses
    `self_cost_reduction_for`'s existing "generic-times-count_selector"
    multiply-by-`per` shape (Delve/Affinity's own mechanism) — the only
    new piece is `GameState.noncombat_damage_to_opponents_this_turn`, a
    running per-player *amount* total (`RulesEngine.deal_damage`
    increments it directly on any noncombat hit against an opponent),
    registered as a `count_selector` value the same way every other
    per-turn tracker is. The trigger's amount half is already fully
    general (`DealDamageEffect.amount_from_trigger_event`, Imodane's own
    primitive); its target half needed two genuinely new pieces: a
    `requires_damage_to_opponent` trigger-condition predicate (the DAMAGE
    event's recipient must be some player other than this ability's own
    controller — the "group"/"controller": "you" check only ever scopes
    the *source*, not who was hit) combined with the DAMAGE event's own
    already-general ``"filter": {"combat": False}`` for "noncombat", and a
    wholly new `targeting.py` kind, ``creature_or_planeswalker_that_
    player_controls`` — "that player" is whichever opponent the *firing*
    trigger event actually named, not a fixed "opponent" role, so
    `legal_targets` needed a new ``trigger_event`` parameter threaded from
    `triggers_mixin.py`'s own two target-gathering call sites.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "per": "noncombat_damage_to_opponents_this_turn",
            })],
            raw_text="This spell costs {X} less to cast, where X is the "
                     "total amount of noncombat damage dealt to your "
                     "opponents this turn.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "target_kind": "creature_or_planeswalker_that_player_controls",
                "amount_from_trigger_event": "amount",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False},
                "requires_damage_to_opponent": True,
            },
            raw_text="Whenever a source you control deals noncombat "
                     "damage to an opponent, this creature deals that "
                     "much damage to target creature or planeswalker "
                     "that player controls.",
        ),
    ]


register("Chandra's Incinerator", _chandras_incinerator)


# ---------------------------------------------------------------------------
# MEC-43 "near-free reuses" batch (2026-08-21) — cEDH staples 2's remaining
# gaps that only needed an existing primitive recoloured/param-widened, per
# BACKLOG.md's own clustering. See Done_Backend.md's "MEC-43" entry for the
# primitives each of these closed along the way (sacrificed_cost_power,
# graveyard_redirect, cast_prohibition's color/creature_only/zones knobs,
# dig_until's graveyard rest destination, grant_borrowed_activated_ability's
# top_of_library source mode, the each_player_pay_or scope/effect_targets
# widening, the Uba Mask draw replacement, and several small trigger-
# condition/target-kind additions).
# ---------------------------------------------------------------------------


def _aetherflux_reservoir() -> list[AbilitySpec]:
    """Whenever you cast a spell, you gain 1 life for each spell you've
    cast this turn.
    Pay 50 life: This artifact deals 50 damage to any target.

    — MEC-43. The life-gain trigger reuses `continuous.count_selector`'s
    existing ``"spells_cast_this_turn"`` entry — incremented synchronously
    at cast time, so it already includes the just-cast spell by the time
    this ability resolves off the stack; the activated ability is a plain
    RULE 118.4 ``{"pay_life": 50}`` cost into an ordinary any-target damage
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"count_selector": "spells_cast_this_turn"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
            raw_text="Whenever you cast a spell, you gain 1 life for each "
                     "spell you've cast this turn.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 50, "target_kind": "any"})],
            cost={"pay_life": 50},
            raw_text="Pay 50 life: This artifact deals 50 damage to any target.",
        ),
    ]


register("Aetherflux Reservoir", _aetherflux_reservoir)


def _altar_of_dementia() -> list[AbilitySpec]:
    """Sacrifice a creature: Target player mills cards equal to the
    sacrificed creature's power.

    — MEC-43. Needed the power sibling of `GameObject.sacrificed_cost_
    mana_value` (`sacrificed_cost_power`, now stamped by `GameEngine.
    _pay_ability_cost` alongside the mana-value one) and a new `MillEffect.
    count_selector` param reading it back via `continuous.count_selector`'s
    matching new entry.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {
                "target_kind": "player", "count_selector": "sacrificed_cost_power",
            })],
            cost={"sacrifice": "creature"},
            raw_text="Sacrifice a creature: Target player mills cards "
                     "equal to the sacrificed creature's power.",
        ),
    ]


register("Altar of Dementia", _altar_of_dementia)


def _burnt_offering() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add X mana in any combination of {B} and/or {R}, where X is the
    sacrificed creature's mana value.

    — MEC-43. The same "any combination of `<colors>`" simplification
    (`AddManaEffect.any_color_choices`) Culling Ritual already established,
    with the amount now driven by the widened ``amount_selector`` ANY-branch
    reading `GameObject.sacrificed_cost_mana_value` (stamped by the
    RULE 601.2b additional-cost payment, the same channel Eldritch
    Evolution/Neoform already use).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "any_color_choices": ["B", "R"],
                "amount_selector": "sacrificed_cost_mana_value",
            })],
            additional_cost={"sacrifice": "creature"},
            raw_text="As an additional cost to cast this spell, sacrifice "
                     "a creature. Add X mana in any combination of {B} "
                     "and/or {R}, where X is the sacrificed creature's "
                     "mana value.",
        ),
    ]


register("Burnt Offering", _burnt_offering)


def _sacrifice() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add an amount of {B} equal to the sacrificed creature's mana value.

    — MEC-43. Burnt Offering's fixed-colour sibling: `AddManaEffect`'s
    existing ``color``/``amount_selector`` variable-count form (the same
    shape Mana Drain already used), reading `sacrificed_cost_mana_value`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "B", "amount_selector": "sacrificed_cost_mana_value"})],
            additional_cost={"sacrifice": "creature"},
            raw_text="As an additional cost to cast this spell, sacrifice "
                     "a creature. Add an amount of {B} equal to the "
                     "sacrificed creature's mana value.",
        ),
    ]


register("Sacrifice", _sacrifice)


def _rain_of_filth() -> list[AbilitySpec]:
    """Until end of turn, lands you control gain "Sacrifice this land:
    Add {B}."

    — MEC-43. `GrantUntilEffect` wrapping the existing quoted-mana-ability
    grant (`grant_mana_ability`, Tyvar Kell's "Elves you control have
    '{T}: Add {B}.'") with its own ``cost`` upgrade (MEC-25, Goldspan
    Dragon) set to a self-sacrifice instead of the bare default {T} — an
    *added* ability on each land, not a replacement of anything printed,
    since a self-sacrifice cost never matches a land's own {T}-shaped mana
    ability. Untargeted (``target_kind=None``): the static's own ``affects``
    already scopes it to "lands you control".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {
                    "type": "grant_mana_ability",
                    "params": {
                        "mana": [{"color": "B", "amount": 1}],
                        "cost": {"sacrifice": "self"},
                        "affects": "lands_you_control",
                    },
                },
                "duration": "end_of_turn",
                "target_kind": None,
            })],
            raw_text="Until end of turn, lands you control gain "
                     "\"Sacrifice this land: Add {B}.\"",
        ),
    ]


register("Rain of Filth", _rain_of_filth)


def _conspicuous_snoop() -> list[AbilitySpec]:
    """Play with the top card of your library revealed.
    You may cast Goblin spells from the top of your library.
    As long as the top card of your library is a Goblin card, this
    creature has all activated abilities of that card.

    — MEC-43. The first two lines are `top_library.py`'s existing standing
    permission (`TopLibraryPermissionEffect`, ``subtypes=["goblin"]`` —
    "play with revealed" is this permission's own always-on visibility
    side effect, per its docstring, so it needs no separate clause here);
    the third is `grant_borrowed_activated_ability`'s new ``source_mode=
    "top_of_library"`` — a scratch, off-zone `GameObject` bound purely to
    read the top card's own activated abilities (a library card is never
    otherwise boarded), narrowed by the new ``donor_subtype`` filter.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "subtypes": ["goblin"],
            })],
            raw_text="Play with the top card of your library revealed. "
                     "You may cast Goblin spells from the top of your "
                     "library.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self", "source_mode": "top_of_library",
                "donor_subtype": "goblin", "creature_only": False,
            })],
            raw_text="As long as the top card of your library is a "
                     "Goblin card, ~ has all activated abilities of that "
                     "card.",
        ),
    ]


register("Conspicuous Snoop", _conspicuous_snoop)


def _defense_of_the_heart() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if an opponent controls three or
    more creatures, sacrifice this enchantment, search your library for up
    to two creature cards, put those cards onto the battlefield, then
    shuffle.

    — MEC-43. A RULE 500.7 upkeep trigger gated by the new ``min_opponent_
    creatures`` RULE 603.4 intervening-if (`effect_binder._trigger_
    condition`), whose effects are a plain `sacrifice_self` followed by
    `SearchLibraryEffect(count=2, destination="battlefield")` — "up to two"
    is that effect's own existing ``optional=True`` default.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice_self", {}),
                EffectSpec("search", {
                    "criteria": {"type": "Creature"}, "count": 2, "destination": "battlefield",
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "min_opponent_creatures": 3,
            },
            raw_text="At the beginning of your upkeep, if an opponent "
                     "controls three or more creatures, sacrifice this "
                     "enchantment, search your library for up to two "
                     "creature cards, put those cards onto the "
                     "battlefield, then shuffle.",
        ),
    ]


register("Defense of the Heart", _defense_of_the_heart)


def _earthcraft() -> list[AbilitySpec]:
    """Tap an untapped creature you control: Untap target basic land.

    — MEC-43. `ActivationCost.tap_others`'s existing bare-main-type
    matching (``(1, "creature")`` — RULE 118.9-style "an untapped creature
    you control" as a cost, already recognized for Dark Triumph's own
    "cycle" siblings) into `TapEffect`'s ``untap=True`` mode, targeting the
    new ``"basic_land"`` kind (the inverse filter of the existing
    ``"nonbasic_land"``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "basic_land"})],
            cost={"tap_others": [1, "creature"]},
            raw_text="Tap an untapped creature you control: Untap target "
                     "basic land.",
        ),
    ]


register("Earthcraft", _earthcraft)


def _hermit_druid() -> list[AbilitySpec]:
    """{G}, {T}: Reveal cards from the top of your library until you
    reveal a basic land card. Put that card into your hand and all other
    cards revealed this way into your graveyard.

    — MEC-43. `dig_until`'s existing dig with the new ``rest_destination=
    "graveyard"`` value (`RulesEngine._graveyard_remaining`, the graveyard
    sibling of the existing library-bottom/shuffled destinations) — the
    hit destination stays the default ``"hand"``.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("dig_until", {
                "criteria": {"basic": True}, "hit_destination": "hand",
                "rest_destination": "graveyard",
            })],
            cost={"text": "{G}, {T}"},
            raw_text="{G}, {T}: Reveal cards from the top of your library "
                     "until you reveal a basic land card. Put that card "
                     "into your hand and all other cards revealed this "
                     "way into your graveyard.",
        ),
    ]


register("Hermit Druid", _hermit_druid)


def _kogla_the_titan_ape() -> list[AbilitySpec]:
    """When Kogla enters, it fights up to one target creature you don't
    control.
    Whenever Kogla attacks, destroy target artifact or enchantment
    defending player controls.
    {1}{G}: Return target Human you control to its owner's hand. Kogla
    gains indestructible until end of turn.

    — MEC-43. The ETB fight was already parser-MODELED; the other two are
    hand-authored here so the whole card is AUTHORED. The attack trigger
    needed a new ``defending_player_id`` field on the `EventType.ATTACKS`
    event itself (the already-resolved RULE 508.1a defender, not
    previously threaded into the event) and a matching `targeting.py`
    kind reading it, the same trigger-event-scoped idiom `creature_or_
    planeswalker_that_player_controls` uses for a DAMAGE event's
    recipient. The activated ability's "target Human you control" reuses
    `TargetSpec.creature_filter` (now threaded through `ReturnToHandEffect`
    too) rather than a new fixed target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("fight", {
                "fighter_kind": None, "other_kind": "creature_you_dont_control",
                "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, it fights up to one target creature "
                     "you don't control.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment_defending_player_controls",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Whenever ~ attacks, destroy target artifact or "
                     "enchantment defending player controls.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_to_hand", {
                    "target_kind": "creature_you_control", "creature_filter": {"subtype": "human"},
                }),
                EffectSpec("pump", {"power": 0, "toughness": 0, "keywords": ["indestructible"]}),
            ],
            cost={"text": "{1}{G}"},
            raw_text="{1}{G}: Return target Human you control to its "
                     "owner's hand. ~ gains indestructible until end of turn.",
        ),
    ]


register("Kogla, the Titan Ape", _kogla_the_titan_ape)


def _leyline_of_the_void() -> list[AbilitySpec]:
    """If this card is in your opening hand, you may begin the game with
    it on the battlefield.
    If a card would be put into an opponent's graveyard from anywhere,
    exile it instead.

    — MEC-43. The opening-hand permission is read straight off oracle text
    by `opening_hand_battlefield_permission` independent of catalogue
    registration (see its own docstring) — nothing to author here. The
    redirect is the new `graveyard_redirect` static (``scope="opponent"``,
    the default), the plain-exile sibling of Dauthi Voidwalker's
    `void_counter_redirect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "opponent"})],
            raw_text="If a card would be put into an opponent's "
                     "graveyard from anywhere, exile it instead.",
        ),
    ]


register("Leyline of the Void", _leyline_of_the_void)


def _rest_in_peace() -> list[AbilitySpec]:
    """When this enchantment enters, exile all graveyards.
    If a card or token would be put into a graveyard from anywhere, exile
    it instead.

    — MEC-43. The ETB is the already-shipped `ExileAllGraveyardsEffect`
    (Farewell's own mass-exile mode); the static is `graveyard_redirect`
    with ``scope="any"`` (unscoped, unlike Leyline of the Void's
    opponent-only reading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, exile all graveyards.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any"})],
            raw_text="If a card or token would be put into a graveyard "
                     "from anywhere, exile it instead.",
        ),
    ]


register("Rest in Peace", _rest_in_peace)


def _soulless_jailer() -> list[AbilitySpec]:
    """Permanent cards in graveyards can't enter the battlefield.
    Players can't cast noncreature spells from graveyards or exile.

    — MEC-43. The first clause is `graveyard_library_entry_prohibition`'s
    new ``card_type="permanent"`` value (unconditionally true — everything
    this check is ever reached for is already a permanent card); the
    second is `cast_prohibition`'s new ``zones`` allowlist (the sibling of
    its existing ``hand_only`` single-zone exemption) combined with the
    already-shipped ``noncreature``/``scope="all"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_library_entry_prohibition", {"card_type": "permanent"})],
            raw_text="Permanent cards in graveyards can't enter the battlefield.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True, "zones": ["graveyard", "exile"],
            })],
            raw_text="Players can't cast noncreature spells from "
                     "graveyards or exile.",
        ),
    ]


register("Soulless Jailer", _soulless_jailer)


def _chain_of_smog() -> list[AbilitySpec]:
    """Target player discards two cards. That player may copy this spell
    and may choose a new target for that copy.

    — MEC-43. The discard is ordinary; the copy is the new
    `CopySelfControlledByPreviousTargetEffect` — the discard target
    (`GameContext.previous_targets`) becomes the copy's controller,
    mirroring `CopySelfIfCastFromGraveyardEffect`'s own "may" simplification
    (always copies, keeps the same target) rather than opening a fresh
    interactive retarget.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 2, "target_kind": "player"}),
                EffectSpec("copy_self_controlled_by_previous_target", {}),
            ],
            raw_text="Target player discards two cards. That player may "
                     "copy this spell and may choose a new target for "
                     "that copy.",
        ),
    ]


register("Chain of Smog", _chain_of_smog)


def _destiny_spinner() -> list[AbilitySpec]:
    """Creature and enchantment spells you control can't be countered.
    {3}{G}: Target land you control becomes an X/X Elemental creature with
    trample and haste until end of turn, where X is the number of
    enchantments you control. It's still a land.

    — MEC-43. Only the first clause is authored here (`GrantCantBeCountered
    Effect`'s new ``"creature_or_enchantment_spells_you_control"`` scope,
    the two-type union sibling of the existing creature-only one); the
    land-animation activated ability is the recurring "animate a
    noncreature permanent into an X/Y creature" gap `BACKLOG.md` already
    tracks as its own open item, deliberately left unbound rather than
    stubbed here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "creature_or_enchantment_spells_you_control"})],
            raw_text="Creature and enchantment spells you control can't "
                     "be countered.",
        ),
    ]


register("Destiny Spinner", _destiny_spinner)


def _llawan_cephalid_empress() -> list[AbilitySpec]:
    """When Llawan enters, return all blue creatures your opponents
    control to their owners' hands.
    Your opponents can't cast blue creature spells.

    — MEC-43. The ETB is `ReturnToHandEffect`'s new ``"opponents_
    creatures"`` mass selector (the opponent-scoped sibling of the existing
    ``"all_creatures"``) combined with its also-new ``filter={"color":
    "U"}``; the static is `cast_prohibition`'s new ``color``/
    ``creature_only`` combination (MEC-43's first card needing both a
    card-type and a colour restriction on the same clause).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {
                "selector": "opponents_creatures", "filter": {"color": "U"},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, return all blue creatures your "
                     "opponents control to their owners' hands.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents", "creature_only": True, "color": "U",
            })],
            raw_text="Your opponents can't cast blue creature spells.",
        ),
    ]


register("Llawan, Cephalid Empress", _llawan_cephalid_empress)


def _mana_breach() -> list[AbilitySpec]:
    """Whenever a player casts a spell, that player returns a land they
    control to its owner's hand.

    — MEC-43. A plain "group" subject with no ``controller`` filter (any
    player's cast, the same idiom Nether Void's own unscoped trigger
    uses); the new `BounceOwnLandFromTriggerEffect` reads the firing
    `SPELL_CAST` event's own ``player_id`` as the chooser/owner instead of
    this ability's own controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bounce_own_land_from_trigger", {})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
            raw_text="Whenever a player casts a spell, that player "
                     "returns a land they control to its owner's hand.",
        ),
    ]


register("Mana Breach", _mana_breach)


def _selvala_heart_of_the_wilds() -> list[AbilitySpec]:
    """Whenever another creature enters, its controller may draw a card if
    its power is greater than each other creature's power.
    {G}, {T}: Add X mana in any combination of colors, where X is the
    greatest power among creatures you control.

    — MEC-43. The mana ability is a plain RULE 605 ability, parsed by
    `mana_abilities_for` rather than bound here. The trigger is the new
    `DrawIfTriggerObjectGreatestPowerEffect` — RULE 603.1's "its" resolves
    to the firing `ENTERS_BATTLEFIELD` event's own object, compared live
    against every other creature's derived power.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_if_trigger_object_greatest_power", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "other": True},
            },
            raw_text="Whenever another creature enters, its controller "
                     "may draw a card if its power is greater than each "
                     "other creature's power.",
        ),
    ]


register("Selvala, Heart of the Wilds", _selvala_heart_of_the_wilds)


def _shifting_woodland() -> list[AbilitySpec]:
    """This land enters tapped unless you control a Forest.
    {T}: Add {G}.
    Delirium — {2}{G}{G}: This land becomes a copy of target permanent
    card in your graveyard until end of turn. Activate only if there are
    four or more card types among cards in your graveyard.

    — MEC-43. The enters-tapped clause is read straight off oracle text by
    `land_tap_condition` independent of catalogue registration, and the
    mana ability is a plain RULE 605 ability — neither needs authoring
    here. The Delirium-gated copy ability is `BecomeCopyUntilEndOfTurnEffect`
    retargeted at the new ``"graveyard_permanent"`` kind (the existing
    graveyard-target family's own ``"permanent"`` filter, own-graveyard
    scoped), gated by `ActivationCost.activation_condition` reusing RULE
    702.137 Delirium's existing `static_conditions` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "graveyard_permanent"})],
            cost={
                "text": "{2}{G}{G}",
                "activation_condition": {"kind": "card_types_in_graveyard_at_least", "amount": 4},
            },
            raw_text="Delirium — {2}{G}{G}: ~ becomes a copy of target "
                     "permanent card in your graveyard until end of turn. "
                     "Activate only if there are four or more card types "
                     "among cards in your graveyard.",
        ),
    ]


register("Shifting Woodland", _shifting_woodland)


def _tataru_taru() -> list[AbilitySpec]:
    """When Tataru Taru enters, you draw a card and target opponent may
    draw a card.
    Scions' Secretary — Whenever an opponent draws a card, if it isn't
    that player's turn, create a tapped Treasure token. This ability
    triggers only once each turn.

    — MEC-43. The ETB is a plain self-draw plus an optional targeted
    opponent draw. The second ability reuses `effect_binder`'s existing
    ``not_controllers_turn`` predicate (checked against the firing DRAW
    event's own actor, exactly "if it isn't **that player's** turn") and
    `TriggeredAbility.once_per_turn`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "target_kind": "opponent", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="When ~ enters, you draw a card and target opponent "
                     "may draw a card.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Treasure", "subtypes": ["Treasure"],
                "is_artifact": True, "tapped": True,
            })],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "not_controllers_turn": True,
                "limit": True,
            },
            raw_text="Scions' Secretary — Whenever an opponent draws a "
                     "card, if it isn't that player's turn, create a "
                     "tapped Treasure token. This ability triggers only "
                     "once each turn.",
        ),
    ]


register("Tataru Taru", _tataru_taru)


def _uba_mask() -> list[AbilitySpec]:
    """If a player would draw a card, that player exiles that card face up
    instead.
    Each player may play lands and cast spells from among cards they
    exiled with ~ this turn.

    — MEC-43. One replacement effect (`draw_exile_face_up`) covers both
    printed lines: it performs the exile itself and stamps `GameState.
    temp_play_permissions` on the exiled card in the same step, so the
    second line is a consequence of the first rather than a separate
    clause — the same "castable/playable from exile this turn" marker
    every other temp-exile-permission card already reads from `can_cast`/
    `can_play_land`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("draw_exile_face_up", {})],
            raw_text="If a player would draw a card, that player exiles "
                     "that card face up instead. Each player may play "
                     "lands and cast spells from among cards they exiled "
                     "with ~ this turn.",
        ),
    ]


register("Uba Mask", _uba_mask)


def _acererak_the_archlich() -> list[AbilitySpec]:
    """When Acererak enters, if you haven't completed Tomb of Annihilation,
    return Acererak to its owner's hand and venture into the dungeon.
    Whenever Acererak attacks, for each opponent, you create a 2/2 black
    Zombie creature token unless that player sacrifices a creature of
    their choice.

    — MEC-43. The ETB combines the new ``not_completed_dungeon`` RULE
    603.4 intervening-if (reading `Player.completed_dungeons`, RULE 309.7)
    with the already-shipped self-bounce + `venture` effects. The attack
    trigger is `EachPlayerPayOrEffect`'s new ``scope="each_opponent"``/
    ``effect_targets="controller"`` combination — every opponent
    independently chooses whether to sacrifice, and only a decliner's
    absence of payment lets Acererak's own controller make the token,
    never the decliner themselves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_to_hand", {"target_kind": None}),
                EffectSpec("venture", {}),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
                "not_completed_dungeon": "Tomb of Annihilation",
            },
            raw_text="When ~ enters, if you haven't completed Tomb of "
                     "Annihilation, return ~ to its owner's hand and "
                     "venture into the dungeon.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_pay_or", {
                "cost": "Sacrifice a creature",
                "scope": "each_opponent",
                "effect_targets": "controller",
                "effects": [{
                    "type": "create_token",
                    "params": {
                        "count": 1, "power": 2, "toughness": 2, "colors": ["B"],
                        "subtypes": ["Zombie"], "token_name": "Zombie",
                    },
                }],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Whenever ~ attacks, for each opponent, you create a "
                     "2/2 black Zombie creature token unless that player "
                     "sacrifices a creature of their choice.",
        ),
    ]


register("Acererak the Archlich", _acererak_the_archlich)


def _jeweled_amulet() -> list[AbilitySpec]:
    """{1}, {T}: Put a charge counter on this artifact. Note the type of
    mana spent to pay this activation cost. Activate only if there are no
    charge counters on this artifact.
    {T}, Remove a charge counter from this artifact: Add one mana of this
    artifact's last noted type.

    — MEC-43 (the ticket's one deliberately-deferred card, closed in a
    follow-up pass rather than a third deferral). "Note the type of mana
    spent" needed a genuinely new primitive: `ManaPool.pay` now stamps
    `last_payment_types` (which type(s) it actually drained — this card's
    own {1} cost has no fixed pip of its own to read instead), and
    `ActivationCost.note_spent_color` copies that onto `GameObject.
    noted_mana_color` right after payment (`GameEngine._pay_ability_cost`).
    This engine has no interactive "which color pays a generic pip" choice
    (`ManaPool._spend_generic`'s own colorless-first order decides it
    deterministically), so what gets noted isn't always a genuine player
    pick — an accepted simplification, the same tier every other "spend
    from the pool" caller already gets. The second ability reads it back
    via `AddManaEffect`'s new `color_from_source_noted_color`, the exact
    sibling of the existing `color_from_source_chosen_color` (Utopia
    Sprawl-shaped RULE 601.2b colour choices already use it the same way).
    "Activate only if there are no charge counters" is `ActivationCost.
    activation_condition` reusing the existing `source_counters` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "charge", "count": 1}),
            ],
            cost={
                "text": "{1}, {T}",
                "note_spent_color": True,
                "activation_condition": {"kind": "source_counters", "counter": "charge", "max": 0},
            },
            raw_text="{1}, {T}: Put a charge counter on ~. Note the type "
                     "of mana spent to pay this activation cost. Activate "
                     "only if there are no charge counters on ~.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"color_from_source_noted_color": True})],
            cost={"taps_self": True, "remove_counters": ["charge", 1]},
            raw_text="{T}, Remove a charge counter from ~: Add one mana "
                     "of ~'s last noted type.",
        ),
    ]


register("Jeweled Amulet", _jeweled_amulet)


def _sanctifier_en_vec() -> list[AbilitySpec]:
    """Protection from black and from red
    When this creature enters, exile all cards that are black or red from
    all graveyards.
    If a black or red permanent, spell, or card not on the battlefield
    would be put into a graveyard, exile it instead.

    — MEC-43 round 2. Protection comes from the RULE 702 keyword catalogue
    (unaffected by hand-authoring — read straight off the printed card
    regardless of registration). The ETB sweep reuses `exile_all_
    graveyards`' new `colors` filter (round 1's Rest in Peace made the
    selector itself; this just narrows it). The replacement reuses round
    1's `graveyard_redirect` static with its new `colors` param instead of
    `scope` — Sanctifier's clause names no owner at all, so it always
    passes ``scope="any"`` alongside the colour filter that does the real
    work.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {"colors": ["B", "R"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, exiliere alle schwarzen "
                     "oder roten Karten aus allen Friedhöfen.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any", "colors": ["B", "R"]})],
            raw_text="Falls ein schwarzes oder rotes Permanent, ein solcher Zauberspruch "
                     "oder eine solche Karte, die sich nicht im Spiel befindet, in einen "
                     "Friedhof gelegt werden würde, exiliere sie stattdessen.",
        ),
    ]


register("Sanctifier en-Vec", _sanctifier_en_vec)


def _beacon_of_unrest() -> list[AbilitySpec]:
    """Put target artifact or creature card from a graveyard onto the
    battlefield under your control. Shuffle Beacon of Unrest into its
    owner's library.

    — MEC-43 round 2, the reanimation-family batch. ``target_kind=
    "graveyard_artifact_or_creature"`` is the new combined graveyard-
    target filter; ``shuffle_self_into_library`` (Green Sun's Zenith) is
    reused verbatim for the second clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_artifact_or_creature", "under_your_control": True,
                }),
                EffectSpec("shuffle_self_into_library", {}),
            ],
            raw_text="Bringe eine Zielkarte eines Artefakts oder einer Kreatur aus einem "
                     "Friedhof unter deine Kontrolle ins Spiel. Mische ~ in die Bibliothek "
                     "seines Besitzers.",
        )
    ]


register("Beacon of Unrest", _beacon_of_unrest)


def _rise_from_the_grave() -> list[AbilitySpec]:
    """Put target creature card from a graveyard onto the battlefield
    under your control. That creature is a black Zombie in addition to
    its other colors and types.

    — MEC-43 round 2. The type/colour addition is `grant_until`'s
    ``previous_subject``/``duration="rest_of_game"`` combination (RULE
    611.2c — a resolving spell's own effect with no stated duration lasts
    indefinitely), reading back the just-reanimated creature the same way
    "It fights…" reads a prior clause's target — RULE 400.7 keeps the
    object's `instance_id` (and so its place in `previous_targets`) stable
    across the graveyard-to-battlefield zone change.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Zombie"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
            raw_text="Bringe eine Zielkreaturenkarte aus einem Friedhof unter deine "
                     "Kontrolle ins Spiel. Diese Kreatur ist zusätzlich zu ihren anderen "
                     "Farben und Typen ein schwarzer Zombie.",
        )
    ]


register("Rise from the Grave", _rise_from_the_grave)


def _tenacious_dead() -> list[AbilitySpec]:
    """When this creature dies, you may pay {1}{B}. If you do, return it
    to the battlefield tapped under its owner's control.

    — MEC-43 round 2. ``remember_trigger_subject`` (`PayCostThenEffect`)
    stamps the dying creature's own `instance_id` onto `GameObject.
    remembered_instance_id` before the interactive pay-or-decline choice
    opens (`context.trigger_event` is only live for the first, synchronous
    `apply()` call — the "if you do" branch runs later); the new
    `return_from_graveyard` `trigger_subject_key="remembered"` mode reads
    it back instead of taking a RULE 115 target, and the new ``tapped``
    param is the printed "return it to the battlefield **tapped**".
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}{B}",
                "remember_trigger_subject": True,
                "effects": [{
                    "type": "return_from_graveyard",
                    "params": {"trigger_subject_key": "remembered", "tapped": True},
                }],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur stirbt, darfst du {1}{B} bezahlen. Falls du dies "
                     "tust, bringe sie getappt unter die Kontrolle ihres Besitzers ins Spiel.",
        )
    ]


register("Tenacious Dead", _tenacious_dead)


def _chainer_dementia_master() -> list[AbilitySpec]:
    """All Nightmares get +1/+1.
    {B}{B}{B}, Pay 3 life: Put target creature card from a graveyard onto
    the battlefield under your control. That creature is black and is a
    Nightmare in addition to its other creature types.
    When Chainer leaves the battlefield, exile all Nightmares.

    — MEC-43 round 2. The anthem is reproduced verbatim (whole-card
    hand-authoring replaces the parser's own output, which would
    otherwise have claimed it alone). The reanimation ability reuses
    `grant_until`'s type/colour addition exactly like Rise from the Grave;
    "Pay 3 life" is a plain life-payment cost component. The leaves
    trigger reuses `exile_all_graveyards`'s sibling mass-exile shape via
    the new ``"exile"`` ``filter={"subtype": ...}`` key — a *battlefield*
    sweep this time, not a graveyard one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "all_creatures", "subtype": "nightmare", "power": 1, "toughness": 1})],
            raw_text="Alle Alpträume erhalten +1/+1.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "under_your_control": True,
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Nightmare"]}},
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
                }),
            ],
            cost={"text": "{B}{B}{B}", "pay_life": 3},
            raw_text="{B}{B}{B}, Bezahle 3 Lebenspunkte: Bringe eine Zielkreaturenkarte "
                     "aus einem Friedhof unter deine Kontrolle ins Spiel. Diese Kreatur ist "
                     "schwarz und zusätzlich zu ihren anderen Kreaturentypen ein Alptraum.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"selector": "all_creatures", "filter": {"subtype": "nightmare"}})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Chainer das Spielfeld verlässt, exiliere alle Alpträume.",
        ),
    ]


register("Chainer, Dementia Master", _chainer_dementia_master)


def _kenriths_transformation() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card.
    Enchanted creature loses all abilities and is a green Elk creature
    with base power and toughness 3/3.

    — MEC-43 round 2, the "Elk" template (Oko, Thief of Crowns' +1 shares
    the same clause but needs its own resolve-time `grant_until` wiring
    plus its other two loyalty abilities — a bigger lift left open).
    "Enchant creature"/the attach itself comes from the RULE 702 keyword
    catalogue, unaffected by hand-authoring. **Documented simplification**:
    only the creature type is *added* (`type_change`'s ``add_types``), the
    permanent's other printed card types aren't stripped — `Card.
    is_artifact`/``is_enchantment`` read the printed card directly, not a
    layer-4-aware property (`GameObject.is_land`'s own docstring already
    flags this as a gap worth extending, not yet done) — low practical
    impact, since the Elk has no abilities left to use any type distinction.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung ins Spiel kommt, ziehe eine Karte.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("type_change", {
                    "affects": "attached_permanent", "add_types": ["creature"],
                    "set_subtypes": ["Elk"], "power": 3, "toughness": 3,
                }),
                EffectSpec("color_change", {"affects": "attached_permanent", "colors": ["G"], "set": True}),
            ],
            raw_text="Verzauberte Kreatur verliert alle Fähigkeiten und ist ein grüner "
                     "Elch mit den Grundwerten 3/3.",
        ),
    ]


register("Kenrith's Transformation", _kenriths_transformation)


def _conquerors_flail() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each color among permanents you
    control.
    As long as this Equipment is attached to a creature, your opponents
    can't cast spells during your turn.
    Equip {2}

    — MEC-43 round 2. The anthem reuses the new `count_selector`
    ``"colors_among_permanents_you_control"`` (the P/T sibling of ENG-27's
    same-named mana-ability selector). The cast lockdown needs two
    independent gates ANDed at once — attached, and only during the
    Equipment's controller's own turn — which no single `static_
    conditions` ``kind`` could express before this batch's new ``"all"``
    combinator. "Equip {2}" is the RULE 702.6 keyword, unaffected by
    hand-authoring.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
            raw_text="Bezauberte Kreatur erhält +1/+1 für jede Farbe unter den Permanenten, "
                     "die du kontrollierst.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents",
                "active_if": {
                    "kind": "all",
                    "conditions": [{"kind": "source_attached"}, {"kind": "your_turn"}],
                },
            })],
            raw_text="Solange diese Ausrüstung an eine Kreatur angelegt ist, können deine "
                     "Gegner während deines Zuges keine Zaubersprüche wirken.",
        ),
    ]


register("Conqueror's Flail", _conquerors_flail)


def _faeburrow_elder() -> list[AbilitySpec]:
    """Vigilance
    This creature gets +1/+1 for each color among permanents you control.
    {T}: For each color among permanents you control, add one mana of
    that color.

    — MEC-43 round 2. Vigilance and the mana ability both already parse on
    their own (the latter via `mana_abilities_for`'s own oracle-text read,
    entirely independent of `bind_from_catalogue`/hand-authoring — see
    CLAUDE.md's RULE 605 note); only the P/T anthem needs hand-authoring,
    reusing Conqueror's Flail's own new ``colors_among_permanents_you_
    control`` selector with ``affects="self"``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
            raw_text="~ erhält +1/+1 für jede Farbe unter den Permanenten, die du "
                     "kontrollierst.",
        )
    ]


register("Faeburrow Elder", _faeburrow_elder)


def _delney_streetwise_lookout() -> list[AbilitySpec]:
    """Creatures you control with power 2 or less can't be blocked by
    creatures with power 3 or greater.
    If a triggered ability of a creature you control with power 2 or less
    triggers, that ability triggers an additional time.

    — MEC-43 round 2. The first clause is the already-shipped qualified
    combat-restriction shape (Challenger Troll/Flopsie's own group
    ``min_power``/``max_power`` scoping, here on the *restricted* side
    instead), just with a blocker-power filter instead of a group-scope
    P/T qualifier. The second reuses `TriggerDoublerEffect`'s new
    ``max_power`` axis — unscoped by "another" (the printed clause names
    none, unlike Roaming Throne's), so Delney's own future triggers would
    double themselves too, though this card prints no other trigger of
    its own for that to matter today.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "affects": "creatures_you_control", "max_power": 2,
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
            })],
            raw_text="Kreaturen, die du kontrollierst und die Stärke 2 oder weniger haben, "
                     "können nicht von Kreaturen mit Stärke 3 oder mehr geblockt werden.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"max_power": 2})],
            raw_text="Falls eine ausgelöste Fähigkeit einer Kreatur, die du kontrollierst "
                     "und die Stärke 2 oder weniger hat, ausgelöst wird, wird sie ein "
                     "zusätzliches Mal ausgelöst.",
        ),
    ]


register("Delney, Streetwise Lookout", _delney_streetwise_lookout)


def _runic_armasaur() -> list[AbilitySpec]:
    """Whenever an opponent activates an ability of a creature or land
    that isn't a mana ability, you may draw a card.

    — MEC-43 round 2. `EventType.ACTIVATED_ABILITY` already fires for
    every non-mana activated ability (RULE 605.1a mana abilities never use
    the stack, so they never reach this event at all — "isn't a mana
    ability" needs no separate check), with `object_types`/``controller_id``
    already matching this trigger's own default group-subject keys. The
    only real gap was the group-subject ``type`` filter's shape: it only
    ever took one word before this batch, and "creature or land" needs
    two ORed together (`effect_binder._group_ok`'s new list-``type``
    support). **Documented simplification**: "may" is read as
    unconditional, the same accepted convention every other untargeted
    "you may draw"/"you may `<upside>`" trigger with no real downside to
    declining already gets in this engine (Selvala, Heart of the Wilds's
    own docstring names the same precedent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "type": ["creature", "land"], "controller": "not_you"},
            },
            raw_text="Immer wenn ein Gegner eine Fähigkeit einer Kreatur oder eines Landes "
                     "aktiviert, die keine Manafähigkeit ist, darfst du eine Karte ziehen.",
        )
    ]


register("Runic Armasaur", _runic_armasaur)


def _peer_into_the_abyss() -> list[AbilitySpec]:
    """Target player draws cards equal to half the number of cards in
    their library and loses half their life. Round up each time.

    — MEC-43 round 2. `DrawCardEffect`'s new ``count_selector=
    "half_target_library_round_up"`` and `LoseLifeEffect`'s new
    ``amount_from_half_target_life`` are the *targeted* siblings of the
    existing "half your own life" shapes (MEC-37's Doomsday), both scoped
    to whichever player the single "target player" resolves to rather
    than the caster. `LoseLifeEffect.previous_subject` reads that same
    resolved target back (`GameContext.previous_targets`) instead of
    declaring a second RULE 115 target of its own — the real card only
    targets once, for both verbs.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {
                    "target_kind": "player", "count_selector": "half_target_library_round_up",
                }),
                EffectSpec("lose_life", {
                    "previous_subject": True, "amount_from_half_target_life": True,
                }),
            ],
            raw_text="Zielspieler zieht so viele Karten, wie die Hälfte der Karten in "
                     "seiner Bibliothek beträgt, und verliert die Hälfte seines Lebens. "
                     "Runde jeweils auf.",
        )
    ]


register("Peer into the Abyss", _peer_into_the_abyss)


def _soul_conduit() -> list[AbilitySpec]:
    """{6}, {T}: Two target players exchange life totals.

    — MEC-43 round 2. The new `ExchangeLifeTotalsEffect` — a genuinely new
    one-shot, since every other life effect in this engine is a single-
    player delta.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_totals", {})],
            cost={"text": "{6}", "taps_self": True},
            raw_text="{6}, {T}: Zwei Zielspieler tauschen ihre Lebenspunkte.",
        )
    ]


register("Soul Conduit", _soul_conduit)
