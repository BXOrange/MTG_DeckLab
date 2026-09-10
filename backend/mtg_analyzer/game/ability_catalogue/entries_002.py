"""Card -> AbilitySpec catalogue entries, part 002 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _encroaching_wastes() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {4}, {T}, Sacrifice this land: Destroy target nonbasic land.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "nonbasic_land"})],
            cost={"mana": "{4}", "taps_self": True, "sacrifice": "self"},
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"type": "Equipment"}, "destination": "hand"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
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
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "plus_one_counters_on_self", "toughness_count": "plus_one_counters_on_self",
            })],
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
        )
    ]


register("Relic Seeker", _relic_seeker)


def _robe_of_stars() -> list[AbilitySpec]:
    """Equipped creature gets +0/+3.
    Astral Projection — {1}{W}: Equipped creature phases out.
    Equip {1}

    — Robe of Stars. Astral Projection is now real (RULE 702.26 phasing,
    `game/effects/core.py`'s `PhaseOutEffect`, scoped to the single-permanent
    case this card needs — no "phase out together" attachment chain).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 0, "toughness": 3})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {})],
            cost={"mana": "{1}{W}"},
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "defending_player"})],
            trigger={"event": EventType.BECOMES_BLOCKED, "condition": {"subject": "self_or_attached_permanent"}},
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec(effect.type, dict(effect.params))],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Instant", "color": ["R", "W"], "max_mana_value": 4},
                "destination": "cast_free",
            })],
            cost={"mana": "{R}{W}", "unattach_self": True},
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield"})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "battlefield_tapped"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
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
        ),
    ]


register("Sword of Truth and Justice", _sword_of_truth_and_justice)


def _swords_to_plowshares() -> list[AbilitySpec]:
    """Exile target creature. Its controller gains life equal to its power.

    ENG-37: the first fused effect type retired onto the composition axis.
    This shipped as one welded `exile_gain_life_equal_power` class whose own
    docstring explained why it had to be — "`GainLifeEffect` deliberately
    never reads a shared ``targets`` list, so composing two effects here
    couldn't pass the power along". That was true of the *operand* axis, not
    of composition: the life is measured off the exiled creature and paid to
    **its** controller, and neither the amount nor the recipient could name a
    referent. `effect_amounts` supplies the first and `effect_operands` the
    second, so the card is now what it reads as — an exile, then a life gain
    that points back at what the exile chose.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {"target_kind": "creature"}),
                EffectSpec("bind", {
                    "name": "power",
                    "amount": {
                        "kind": "characteristic", "characteristic": "power",
                        "of": "previous_target",
                    },
                    "effects": [{
                        "type": "gain_life",
                        "params": {
                            "amount": "$power",
                            "player": {"of": "previous_target", "as": "controller"},
                        },
                    }],
                }),
            ],
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
        )
    ]


register("Volcanic Fallout", _volcanic_fallout)


def _wrath_of_god() -> list[AbilitySpec]:
    """Destroy all creatures. They can't be regenerated."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "can_be_regenerated": False})],
        )
    ]


register("Wrath of God", _wrath_of_god)


def _crypt_incursion() -> list[AbilitySpec]:
    """Exile all creature cards from target player's graveyard. You gain 3
    life for each card exiled this way.

    ENG-37 B3: a `seq` of `exile_target_graveyard` (``card_type="creature"``)
    then a `bind` measuring ``objects_exiled_this_way`` (×3) into `gain_life`
    — retiring the fused `exile_graveyard_creatures_gain_life`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_target_graveyard",
                 "params": {"target_kind": "player", "card_type": "creature"}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "this_way", "tally": "objects_exiled_this_way",
                               "multiply": 3},
                    "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
                }},
            ]})],
        )
    ]


register("Crypt Incursion", _crypt_incursion)


def _sign_in_blood() -> list[AbilitySpec]:
    """Target player draws two cards and loses 2 life.

    — ENG-37 B4: a `seq` whose first clause (`draw`) carries the sole RULE 115
    player target and whose second (`lose_life` with ``previous_subject``)
    acts on that same player via `GameContext.previous_targets`, retiring the
    fused ``target_player_draw_lose_life``. One announced target, as before —
    `lose_life` declares none of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "draw", "params": {"count": 2, "target_kind": "player"}},
                {"type": "lose_life", "params": {"amount": 2, "previous_subject": True}},
            ]})],
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
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("destroy", {"selector": "all_artifacts"}),
                EffectSpec("destroy", {"selector": "all_enchantments"}),
            ],
            cost={"text": "{6}{W}{W}, Discard this card"},
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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{2}{W}, Discard this card"},
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
            [
                # ENG-37 B4: one "up to one target creature" (the counter
                # clause), reused by `grant_until`'s ``previous_subject``
                # pronoun for "It gains first strike until end of turn."
                # instead of the fused ``add_counter_first_strike``.
                EffectSpec("add_counters", {
                    "kind": "+1/+1", "amount": 1,
                    "target_kind": "creature", "optional": True,
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["first_strike"]}},
                }),
            ],
            cost={"loyalty": 1},
            conditional_flash={"entered_this_turn": True},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "token_name": "Samurai", "power": 2, "toughness": 2, "count": 1,
                "colors": ["W"], "subtypes": ["Samurai"], "keywords": ["vigilance"],
            })],
            cost={"loyalty": -1},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "creature"}),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            cost={"loyalty": -2},
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

    ENG-37: retired from `destroy_lose_life_equal_mana_value`. Unlike Swords
    to Plowshares and Nature's Claim, the recipient here needed no referent
    ("**you** lose life"), only the *amount* did — so this one is a plain
    `destroy` plus a `bind` reading the destroyed permanent's printed mana
    value (RULE 202.3, stable after it leaves — RULE 608.2h last-known
    information, which is what the welded version read too).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "permanent"}),
                EffectSpec("bind", {
                    "name": "mv",
                    "amount": {
                        "kind": "characteristic", "characteristic": "mana_value",
                        "of": "previous_target",
                    },
                    "effects": [
                        {"type": "lose_life", "params": {"amount": "$mv"}},
                    ],
                }),
            ],
        )
    ]


register("Feed the Swarm", _feed_the_swarm)


def _resculpt() -> list[AbilitySpec]:
    """Exile target artifact or creature. Its controller creates a 4/4 blue
    and red Elemental creature token.

    — Resculpt. ``target_kind="permanent"`` is the same documented
    simplification Feed the Swarm's entry above uses (drops the artifact/
    creature type union — no target kind names exactly that pair). ENG-37 B3:
    a `seq` of `exile` then `create_token` with ``creators="previous_target_
    controller"`` — `create_token` reads the just-exiled object's last-known
    controller (RULE 608.2h), which survives the zone change — retiring the
    fused `exile_create_token`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile", "params": {"target_kind": "permanent"}},
                {"type": "create_token", "params": {
                    "power": 4, "toughness": 4, "colors": ["U", "R"],
                    "subtypes": ["Elemental"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Resculpt", _resculpt)


def _crib_swap() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    Exile target creature. Its controller creates a 1/1 colorless
    Shapeshifter creature token with changeling.

    The one-card token-replacement shape is not worth a parser row (the
    cache probe finds Crib Swap alone). ENG-37 B3: a `seq` of `exile` then
    `create_token` with ``creators="previous_target_controller"`` (reads the
    exiled creature's last-known controller, RULE 608.2h), retiring the fused
    ``exile_create_token``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile", "params": {"target_kind": "creature"}},
                {"type": "create_token", "params": {
                    "power": 1, "toughness": 1, "subtypes": ["Shapeshifter"],
                    "keywords": ["changeling"], "token_name": "Shapeshifter",
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Crib Swap", _crib_swap)


def _lamentation() -> list[AbilitySpec]:
    """When this creature enters, destroy target creature an opponent controls.
    You gain 3 life.
    Encore {6}{B}{B}

    A singleton precon creature: the engine already composes one targeted
    destruction with a following untargeted life gain, and the existing
    Encore keyword binding supplies its graveyard activated ability.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"target_kind": "creature_you_dont_control"}),
                EffectSpec("gain_life", {"amount": 3}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Lamentation", _lamentation)


def _springleaf_parade() -> list[AbilitySpec]:
    """When this enchantment enters, create X 1/1 colorless Shapeshifter
    creature tokens with changeling. (They're every creature type.)
    Creature tokens you control have "{T}: Add one mana of any color."

    A deck-local singleton: the X-token sentinel and layer-6 mana grant
    already exist, so a catalogue entry is smaller and safer than widening
    the oracle token grammar for one card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "source_x_paid", "power": 1, "toughness": 1,
                "subtypes": ["Shapeshifter"], "keywords": ["changeling"],
                "token_name": "Shapeshifter",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "creatures_you_control", "tokens": True,
                "mana": [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}],
            })],
        ),
    ]


register("Springleaf Parade", _springleaf_parade)


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
        )
    ]


register("Steal Enchantment", _steal_enchantment)


def _grinding_station() -> list[AbilitySpec]:
    """{T}, Sacrifice an artifact: Target player mills three cards.
    Whenever an artifact enters, you may untap this artifact.

    The untap names ``target_kind="source"`` rather than the bare ``None``
    that means the same thing, because this is a RULE 603.1 ``"group"``
    trigger: `effect_binder._retarget_implicit_subject_effects` rewrites a
    bare ``None`` there into "whichever object fired the trigger" (right for
    Raiyuu's "untap **it**", wrong here — RULE 109.2's "this artifact" is
    Grinding Station itself). Untapping the artifact that just entered is a
    silent no-op, which is exactly how this went unnoticed.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("mill", {"count": 3, "target_kind": "player"})],
            cost={"text": "{T}, Sacrifice an artifact"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "source", "untap": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "group", "type": "artifact"}},
            optional=True,
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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_artifact", "destination": "battlefield"})],
            cost={"text": "{R}, {T}, Sacrifice an artifact"},
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
    indestructible`, `game/effects/core.py`'s `ReturnCreatureGrantIndestructibleEffect`
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
        )
    ]


register("Brainstorm", _brainstorm)


def _timetwister() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards.

    — Timetwister. `wheel` (`game/effects/core.py`'s `WheelEffect`) is written
    generically (not Timetwister-specific) since Time Reversal/Echo of
    Eons print the identical line.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("wheel", {"draw_count": 7})],
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
        )
    ]


register("Power Artifact", _power_artifact)


def _fertile_ground() -> list[AbilitySpec]:
    """Enchant land
    Whenever enchanted land is tapped for mana, its controller adds an
    additional one mana of any color.

    The attached-land trigger is Wild Growth's existing triggered-mana
    ability.  ``ANY`` preserves the controller's colour choice and
    ``event_controller`` correctly follows the enchanted land if control
    changes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["ANY"], "recipient": "event_controller"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "attached_permanent"},
                "mana_ability": True,
            },
        )
    ]


register("Fertile Ground", _fertile_ground)


def _reality_shift() -> list[AbilitySpec]:
    """Exile target creature. Its controller manifests the top card of their library."""
    return [AbilitySpec(
        "spell_effect",
        [
            EffectSpec("exile", {"target_kind": "creature"}),
            EffectSpec("manifest", {"player": "previous_target_controller"}),
        ],
    )]


register("Reality Shift", _reality_shift)


def _shatter_the_sky() -> list[AbilitySpec]:
    """Each player who controls a creature with power 4 or greater draws a card.
    Then destroy all creatures."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("draw_each_player_with_creature_power", {"min_power": 4}),
        EffectSpec("destroy", {"selector": "all_creatures"}),
    ])]


register("Shatter the Sky", _shatter_the_sky)


def _greenwarden_of_murasa() -> list[AbilitySpec]:
    """Both recursion triggers of Greenwarden of Murasa."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_card", "destination": "hand",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("may_exile_source_then", {"then_trigger": [
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_card", "destination": "hand",
                }},
            ]})],
            trigger={"event": EventType.DIES},
        ),
    ]


register("Greenwarden of Murasa", _greenwarden_of_murasa)


def _risen_reef() -> list[AbilitySpec]:
    return [AbilitySpec(
        "triggered", [EffectSpec("peek_top_land_or_hand", {})],
        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
            "subject_subtype": "Elemental", "controller": "you",
        }},
    )]


register("Risen Reef", _risen_reef)


def _muldrotha_the_gravetide() -> list[AbilitySpec]:
    return [AbilitySpec(
        "static", [EffectSpec("graveyard_cast_permission", {
            "per_permanent_type": True, "once_per_turn": False,
        })],
    )]


register("Muldrotha, the Gravetide", _muldrotha_the_gravetide)


def _distant_melody() -> list[AbilitySpec]:
    return [AbilitySpec("spell_effect", [
        EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
            {"type": "draw_controlled_chosen_creature_type", "params": {}},
        ]}),
    ])]


register("Distant Melody", _distant_melody)


def _bane_of_progress() -> list[AbilitySpec]:
    return [AbilitySpec("triggered", [EffectSpec("destroy_artifacts_enchantments_then_counters", {})],
                        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}})]


register("Bane of Progress", _bane_of_progress)


def _yarok_the_desecrated() -> list[AbilitySpec]:
    return [AbilitySpec(
        "static", [EffectSpec("trigger_doubler", {"cause_filter": [EventType.ENTERS_BATTLEFIELD]})],
    )]


register("Yarok, the Desecrated", _yarok_the_desecrated)


def _titan_of_industry() -> list[AbilitySpec]:
    return [AbilitySpec(
        "triggered", [], trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        modes={"choose": 2, "options": [
            [EffectSpec("destroy", {"target_kind": "artifact_or_enchantment"})],
            [EffectSpec("gain_life", {"amount": 5, "target_kind": "player"})],
            [EffectSpec("create_token", {"token_name": "Rhino", "power": 4, "toughness": 4, "colors": ["G"], "subtypes": ["Rhino", "Warrior"]})],
            [EffectSpec("add_counters", {"amount": 1, "kind": "shield", "target_kind": "creature_you_control"})],
        ]},
    )]


register("Titan of Industry", _titan_of_industry)


def _raging_ravine() -> list[AbilitySpec]:
    """Raging Ravine's animation and its self-attack growth trigger.

    Entering tapped and the two-colour mana ability are parsed from the card
    itself.  The colour layer of the animation is not represented by this
    engine yet, but the creature type, base P/T, and attack counter are.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "add_types": ["creature"], "add_subtypes": ["Elemental"],
                    "power": 3, "toughness": 3,
                }},
            })],
            cost={"mana": "{2}{R}{G}"},
        ),
        AbilitySpec(
            "triggered", [EffectSpec("add_counters", {"amount": 1, "kind": "+1/+1", "target_kind": None})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Raging Ravine", _raging_ravine)


def _haunting_voyage() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
                {"type": "return_chosen_creature_type_from_graveyard", "params": {}},
            ]})],
        ),
        AbilitySpec("keyword", [], keyword={"name": "foretell", "cost": "{5}{B}{B}"}),
    ]


register("Haunting Voyage", _haunting_voyage)


def _horde_of_notions() -> list[AbilitySpec]:
    return [
        AbilitySpec("keyword", [], keyword={"name": "vigilance"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("keyword", [], keyword={"name": "haste"}),
        AbilitySpec(
            "activated", [EffectSpec("cast_target_elemental_from_graveyard_free", {})],
            cost={"mana": "{W}{U}{B}{R}{G}"},
        ),
    ]


register("Horde of Notions", _horde_of_notions)


def _descendants_fury() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("descendants_fury_sacrifice", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
            },
        ),
    ]


register("Descendants' Fury", _descendants_fury)


def _kindred_summons() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("_request_choose_creature_type_grant", {"then_specs": [
                {"type": "kindred_summons", "params": {}},
            ]})],
        ),
    ]


register("Kindred Summons", _kindred_summons)


def _eclipsed_flamekin() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 4,
                "filter": {"subtypes": ["Elemental", "Island", "Mountain"]},
                "action": "library_to_hand",
                "rest_destination": "library_bottom_random",
                "optional": True,
                "prompt": "Elemental-, Island- oder Mountain-Karte wählen",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
        ),
    ]


register("Eclipsed Flamekin", _eclipsed_flamekin)


def _cream_of_the_crop() -> list[AbilitySpec]:
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": "trigger_power",
                "action": "library_top",
                "rest_destination": "library_bottom_random",
                "optional": True,
                "decline_leaves_untouched": True,
                "prompt": "Eine Karte oben auf die Bibliothek legen (Rest nach unten)",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
            },
        ),
    ]


register("Cream of the Crop", _cream_of_the_crop)


def _cavalier_of_thorns() -> list[AbilitySpec]:
    return [
        AbilitySpec("keyword", [], keyword={"name": "reach"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 5,
                "filter": {"is_land": True},
                "action": "library_to_battlefield",
                "rest_destination": "graveyard",
                "optional": False,
                "prompt": "Länderkarte auf das Spielfeld bringen (Rest in den Friedhof)",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("may_exile_source_then", {"then_trigger": [
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_card", "destination": "library_top",
                }},
            ]})],
            trigger={"event": EventType.DIES},
        ),
    ]


register("Cavalier of Thorns", _cavalier_of_thorns)
