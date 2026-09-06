"""Card -> AbilitySpec catalogue entries, part 001 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

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
    creature's own controller, not the exiled creature's. MEC-65 binds its
    printed exile-a-white-card Evoke cost through the shared RULE 702.74
    alternate-cast path. "Target
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

