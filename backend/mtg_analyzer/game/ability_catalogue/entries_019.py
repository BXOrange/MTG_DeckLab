"""Card -> AbilitySpec catalogue entries, part 019.

Secrets of Strixhaven Commander decks (saved-deck playability batch, PAR-60,
resumed 2026-09-08). Each entry is one card the fail-closed oracle parser
cannot fully claim, hand-authored against an engine primitive. See
`docs/implementation-state/Done_Backend.md` -> "Deck/Cube Playability
Batches" and PAR-60 in `BACKLOG.md`.

Waves in this file:
- wave 22: Silverquill "Influence" — the Aura / enchantments-matter cluster.
- wave 23: Witherbloom "Pestilence" — "life you gained this turn" + the
  sacrifice-matters cluster. New engine primitives: the
  ``gained_life_this_turn`` `static_conditions` kind and the
  ``life_gained_this_turn`` `continuous.count_selector`.
- wave 24: Quandrix "Unlimited" (+ one Lorehold land) — {X}/counter singletons
  built on existing primitives. Engine: ``times`` added to
  `RulesEngine._substitute_x`'s attr list (proliferate X).
"""

from __future__ import annotations

from ...models.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register


# ===========================================================================
# wave 22 — Silverquill Influence: Auras and "enchantments you control"
# ===========================================================================
#
# Shared shapes: a static bonus scoped ``affects="attached_permanent"`` (the
# Aura's own buff, RULE 303.4c), and "for each Aura you control" counts via
# the new ``auras_you_control`` `continuous.count_selector` and the
# ``auras_attached_to_self`` per-object `_pt_mod_count` selector (the Aura
# sibling of ``equipment_attached_to_self``). "Enchant creature" itself keeps
# coming from the RULE 702.5 keyword catalogue even for a registered card.


def _kor_spiritdancer() -> list[AbilitySpec]:
    """This creature gets +2/+2 for each Aura attached to it.
    Whenever you cast an Aura spell, you may draw a card."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 2, "toughness": 2,
                "power_count": "auras_attached_to_self",
                "toughness_count": "auras_attached_to_self",
            })],
            raw_text="~ erhält +2/+2 für jede an sie angelegte Aura.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "subtypes": ["aura"], "controller": "you"},
            },
            optional=True,
            raw_text="Immer wenn du einen Aura-Zauberspruch wirkst, darfst du eine Karte ziehen.",
        ),
    ]


register("Kor Spiritdancer", _kor_spiritdancer)


def _sages_reverie() -> list[AbilitySpec]:
    """Enchant creature
    When this Aura enters, draw a card for each Aura you control that's
    attached to a creature.
    Enchanted creature gets +1/+1 for each Aura you control that's attached
    to a creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"amount_from_count_selector": "auras_you_control"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura ins Spiel kommt, ziehe eine Karte für jede Aura, "
                     "die du kontrollierst und die an eine Kreatur angelegt ist.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "auras_you_control", "toughness_count": "auras_you_control",
            })],
            raw_text="Verzauberte Kreatur erhält +1/+1 für jede Aura, die du kontrollierst "
                     "und die an eine Kreatur angelegt ist.",
        ),
    ]


register("Sage's Reverie", _sages_reverie)


def _eidolon_of_countless_battles() -> list[AbilitySpec]:
    """Bestow {2}{W}{W}
    This creature and enchanted creature each get +1/+1 for each creature you
    control and +1/+1 for each Aura you control.

    Four `anthem` layer-7d specs: {self, attached} x {creatures, Auras}. When
    cast as a creature (not bestowed) the ``attached_permanent`` halves match
    nothing, exactly as the rules read."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "self", "power": 1, "toughness": 1,
                    "power_count": "creatures_you_control",
                    "toughness_count": "creatures_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "self", "power": 1, "toughness": 1,
                    "power_count": "auras_you_control", "toughness_count": "auras_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "creatures_you_control",
                    "toughness_count": "creatures_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "auras_you_control", "toughness_count": "auras_you_control",
                }),
            ],
            raw_text="~ und die verzauberte Kreatur erhalten je +1/+1 für jede Kreatur, "
                     "die du kontrollierst, und +1/+1 für jede Aura, die du kontrollierst.",
        ),
    ]


register("Eidolon of Countless Battles", _eidolon_of_countless_battles)


def _angelic_destiny() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +4/+4, has flying and first strike, and is an
    Angel in addition to its other types.
    When enchanted creature dies, return this card to its owner's hand."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 4, "toughness": 4}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["flying", "first strike"],
                }),
                EffectSpec("type_change", {
                    "affects": "attached_permanent", "add_subtypes": ["Angel"],
                }),
            ],
            raw_text="Verzauberte Kreatur erhält +4/+4, hat Fliegend und Erstschlag und "
                     "ist zusätzlich zu ihren anderen Typen ein Engel.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.DIES, "condition": {"subject": "attached_permanent"}},
            raw_text="Wenn die verzauberte Kreatur stirbt, bringe diese Karte auf die Hand "
                     "ihres Besitzers zurück.",
        ),
    ]


register("Angelic Destiny", _angelic_destiny)


def _eldrazi_conscription() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +10/+10 and has trample and annihilator 2."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 10, "toughness": 10}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["trample"],
                    "parametric_keywords": [{"name": "annihilator", "n": 2}],
                }),
            ],
            raw_text="Verzauberte Kreatur erhält +10/+10 und hat Trampelschaden und "
                     "Auslöschung 2.",
        ),
    ]


register("Eldrazi Conscription", _eldrazi_conscription)


def _shielded_by_faith() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has indestructible.
    Whenever a creature enters, you may attach this Aura to that creature."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "attached_permanent", "keywords": ["indestructible"],
            })],
            raw_text="Verzauberte Kreatur ist unzerstörbar.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_triggering_permanent", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject_type": "creature"}},
            optional=True,
            raw_text="Immer wenn eine Kreatur ins Spiel kommt, darfst du diese Aura an "
                     "jene Kreatur anlegen.",
        ),
    ]


register("Shielded by Faith", _shielded_by_faith)


def _sheltered_by_ghosts() -> list[AbilitySpec]:
    """Enchant creature you control
    When this Aura enters, exile target nonland permanent an opponent
    controls until this Aura leaves the battlefield.
    Enchanted creature gets +1/+0 and has lifelink and ward {2}."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent_you_dont_control",
                "remember": True, "until_source_leaves": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura ins Spiel kommt, exiliere ein nichtländisches "
                     "Zielpermanent, das ein Gegner kontrolliert, bis diese Aura das "
                     "Spiel verlässt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura das Spiel verlässt, bringe das exilierte Permanent "
                     "zurück.",
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 0}),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["lifelink"], "ward_cost": "{2}",
                }),
            ],
            raw_text="Verzauberte Kreatur erhält +1/+0 und hat Lebensverknüpfung und Schutzgeld {2}.",
        ),
    ]


register("Sheltered by Ghosts", _sheltered_by_ghosts)


def _chains_of_custody() -> list[AbilitySpec]:
    """Enchant creature you control
    When this Aura enters, exile target nonland permanent an opponent
    controls until this Aura leaves the battlefield.
    Enchanted creature has ward {2}."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent_you_dont_control",
                "remember": True, "until_source_leaves": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura ins Spiel kommt, exiliere ein nichtländisches "
                     "Zielpermanent, das ein Gegner kontrolliert, bis diese Aura das "
                     "Spiel verlässt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura das Spiel verlässt, bringe das exilierte Permanent zurück.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "ward_cost": "{2}"})],
            raw_text="Verzauberte Kreatur hat Schutzgeld {2}.",
        ),
    ]


register("Chains of Custody", _chains_of_custody)


def _darksteel_mutation() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature is an Insect artifact creature with base power and
    toughness 0/1 and has indestructible, and it loses all other abilities,
    card types, and creature types.

    — the Kenrith's Transformation "Elk" template plus an artifact type and
    indestructible. Documented simplification: only creature types are
    replaced (`set_subtypes`) and artifact/creature are added; a prior
    *enchantment* card type isn't stripped (`Card.is_enchantment` reads the
    printed card, not a layer-4 property — the same gap Kenrith's
    Transformation flags)."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("remove_all_abilities", {"affects": "attached_permanent"}),
                EffectSpec("type_change", {
                    "affects": "attached_permanent",
                    "add_types": ["artifact", "creature"],
                    "set_subtypes": ["Insect"], "power": 0, "toughness": 1,
                }),
                EffectSpec("grant_keyword", {
                    "affects": "attached_permanent", "keywords": ["indestructible"],
                }),
            ],
            raw_text="Verzauberte Kreatur ist ein Insekt-Artefaktkreatur mit den "
                     "Grundwerten 0/1 und ist unzerstörbar. Sie verliert alle anderen "
                     "Fähigkeiten, Kartentypen und Kreaturtypen.",
        ),
    ]


register("Darksteel Mutation", _darksteel_mutation)


def _fallen_ideal() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has flying and "Sacrifice a creature: This creature
    gets +2/+1 until end of turn."
    When this Aura is put into a graveyard from the battlefield, return it to
    its owner's hand."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["flying"]}),
                EffectSpec("grant_activated_ability", {
                    "affects": "attached_permanent",
                    "cost": {"text": "Sacrifice a creature"},
                    "grant_effects": [{"type": "pump", "params": {"power": 2, "toughness": 1}}],
                }),
            ],
            raw_text='Verzauberte Kreatur hat Fliegend und "Opfere eine Kreatur: Diese '
                     'Kreatur erhält +2/+1 bis zum Ende des Zuges."',
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            raw_text="Wenn diese Aura von einem Schlachtfeld auf einen Friedhof gelegt "
                     "wird, bringe sie auf die Hand ihres Besitzers zurück.",
        ),
    ]


register("Fallen Ideal", _fallen_ideal)


def _raffines_guidance() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1.
    You may cast this card from your graveyard by paying {2}{W} rather than
    paying its mana cost.

    Documented simplification: the graveyard recast is modeled with the
    ``self_graveyard_or_exile_cast_permission`` marker (Squee-shaped — "you
    may cast this from your graveyard"), which pays the card's *printed*
    `{1}{W}` rather than the printed alternative `{2}{W}`; the recursion
    itself is what matters and the 1-mana delta is immaterial in these
    singleton decks."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
            raw_text="Verzauberte Kreatur erhält +1/+1.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("self_graveyard_or_exile_cast_permission", {})],
            raw_text="Du darfst diese Karte aus deinem Friedhof wirken.",
        ),
    ]


register("Raffine's Guidance", _raffines_guidance)


def _ajanis_chosen() -> list[AbilitySpec]:
    """Whenever an enchantment you control enters, create a 2/2 white Cat
    creature token. If that enchantment is an Aura, you may attach it to the
    token.

    Documented simplification: only the token creation is modeled; the "if
    it's an Aura, attach it to the token" rider is dropped (a re-attach of
    the just-entered Aura — a corner these decks don't lean on)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Cat", "power": 2, "toughness": 2,
                "colors": ["W"], "subtypes": ["Cat"],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "object_types": ["enchantment"], "controller": "you"},
            },
            raw_text="Immer wenn eine Verzauberung, die du kontrollierst, ins Spiel kommt, "
                     "erzeuge einen 2/2 weißen Katze-Kreaturtoken.",
        ),
    ]


register("Ajani's Chosen", _ajanis_chosen)


# ===========================================================================
# wave 23 — Witherbloom Pestilence: "life you gained this turn" + sacrifice
# ===========================================================================


def _mortality_spear() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if you gained life this turn.
    Destroy target nonland permanent."""
    MORTALITY_SPEAR_DISCOUNT = 2
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": MORTALITY_SPEAR_DISCOUNT,
                "active_if": {"kind": "gained_life_this_turn"},
            })],
            raw_text="Dieser Zauberspruch kostet {2} weniger, wenn du in diesem Zug "
                     "Lebenspunkte dazugewonnen hast.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "nonland_permanent"})],
            raw_text="Zerstoere ein Zielpermanent, das kein Land ist.",
        ),
    ]


register("Mortality Spear", _mortality_spear)


def _defiling_daemogoth() -> list[AbilitySpec]:
    """Menace
    Whenever a creature you control deals combat damage to a player, you gain
    1 life.
    At the beginning of your end step, each opponent loses X life, where X is
    the amount of life you gained this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "type": "creature", "other": False,
                              "controller": "you"},
                "filter": {"is_player": True, "combat": True},
            },
            raw_text="Immer wenn eine Kreatur, die du kontrollierst, einem Spieler "
                     "Kampfschaden zufuegt, erhaeltst du 1 Lebenspunkt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount_from_count_selector": "life_gained_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments verliert jeder Gegner X Lebenspunkte, "
                     "wobei X die Anzahl der in diesem Zug dazugewonnenen Lebenspunkte ist.",
        ),
    ]


register("Defiling Daemogoth", _defiling_daemogoth)


def _witch_of_the_moors() -> list[AbilitySpec]:
    """Deathtouch
    At the beginning of your end step, if you gained life this turn, each
    opponent sacrifices a creature of their choice and you return up to one
    target creature card from your graveyard to your hand."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice", {"selector": "each_opponent", "what": "creature",
                                         "count": 1}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "destination": "hand",
                    "optional": True,
                }),
            ],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "gained_life_this_turn"},
            },
            raw_text="Zu Beginn deines Endsegments, falls du in diesem Zug Lebenspunkte "
                     "dazugewonnen hast, opfert jeder Gegner eine Kreatur seiner Wahl "
                     "und du bringst bis zu eine Zielkreaturenkarte aus deinem Friedhof "
                     "auf deine Hand zurueck.",
        ),
    ]


register("Witch of the Moors", _witch_of_the_moors)


def _blossoming_bogbeast() -> list[AbilitySpec]:
    """Whenever this creature attacks, you gain 2 life. Then creatures you
    control gain trample and get +X/+X until end of turn, where X is the
    amount of life you gained this turn.

    ``gain_life`` runs first so ``life_gained_this_turn`` already includes the
    2 by the time the group pump reads it."""
    BOGBEAST_LIFEGAIN = 2
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"amount": BOGBEAST_LIFEGAIN}),
                EffectSpec("pump", {
                    "selector": "creatures_you_control", "keywords": ["trample"],
                    "amount_from_count_selector": "life_gained_this_turn",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, erhaeltst du 2 Lebenspunkte. "
                     "Danach erhalten Kreaturen, die du kontrollierst, Trampelschaden "
                     "und +X/+X bis zum Ende des Zuges, wobei X die Anzahl der in diesem "
                     "Zug dazugewonnenen Lebenspunkte ist.",
        ),
    ]


register("Blossoming Bogbeast", _blossoming_bogbeast)


def _eccentric_pestfinder() -> list[AbilitySpec]:
    """Trample
    At the beginning of each end step, if you gained life this turn, this
    creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "gained_life_this_turn"},
            },
            raw_text="Zu Beginn jedes Endsegments, falls du in diesem Zug Lebenspunkte "
                     "dazugewonnen hast, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Eccentric Pestfinder", _eccentric_pestfinder)
register("Eccentric Pestfinder // Turn Stones", _eccentric_pestfinder)


def _merchant_of_venom() -> list[AbilitySpec]:
    """Menace
    When this creature enters, each player sacrifices a creature of their
    choice.
    Whenever a player sacrifices a permanent, put a +1/+1 counter on this
    creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature",
                                      "count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, opfert jeder Spieler eine "
                     "Kreatur seiner Wahl.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {})],
            trigger={"event": EventType.SACRIFICE},
            raw_text="Immer wenn ein Spieler eine bleibende Karte opfert, lege einen "
                     "+1/+1-Marker auf diese Kreatur.",
        ),
    ]


register("Merchant of Venom", _merchant_of_venom)


def _mazirek_kraul_death_priest() -> list[AbilitySpec]:
    """Flying
    Whenever a player sacrifices another permanent, put a +1/+1 counter on
    each creature you control."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"selector": "each_creature_you_control"})],
            trigger={"event": EventType.SACRIFICE, "condition": {"other": True}},
            raw_text="Immer wenn ein Spieler eine andere bleibende Karte opfert, lege "
                     "einen +1/+1-Marker auf jede Kreatur, die du kontrollierst.",
        ),
    ]


register("Mazirek, Kraul Death Priest", _mazirek_kraul_death_priest)


def _smothering_abomination() -> list[AbilitySpec]:
    """Devoid
    Flying
    At the beginning of your upkeep, sacrifice a creature.
    Whenever you sacrifice a creature, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"what": "creature", "count": 1})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments opferst du eine Kreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SACRIFICE, "condition": {"subject": "you"},
                     "sacrifice_type": "creature"},
            raw_text="Immer wenn du eine Kreatur opferst, ziehe eine Karte.",
        ),
    ]


register("Smothering Abomination", _smothering_abomination)


def _dina_soul_steeper() -> list[AbilitySpec]:
    """Whenever you gain life, each opponent loses 1 life.
    {1}, Sacrifice another creature: Dina gets +X/+0 until end of turn, where
    X is the sacrificed creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
            raw_text="Immer wenn du Lebenspunkte dazugewinnst, verliert jeder Gegner "
                     "1 Lebenspunkt.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0,
                "amount_from_count_selector": "sacrificed_cost_power",
                "amount_from_count_selector_axis": "power",
            })],
            cost={"mana": "{1}", "text": "{1}, Sacrifice another creature"},
            raw_text="{1}, opfere eine andere Kreatur: ~ erhaelt +X/+0 bis zum Ende des "
                     "Zuges, wobei X die Staerke der geopferten Kreatur ist.",
        ),
    ]


register("Dina, Soul Steeper", _dina_soul_steeper)


def _dina_essence_brewer() -> list[AbilitySpec]:
    """Whenever you sacrifice a creature, draw a card. This ability triggers
    only once each turn.
    {2}, {T}, Sacrifice another creature: You gain X life and put X +1/+1
    counters on target creature you control, where X is the sacrificed
    creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SACRIFICE, "condition": {"subject": "you"},
                "sacrifice_type": "creature", "limit": True,
            },
            raw_text="Immer wenn du eine Kreatur opferst, ziehe eine Karte. Diese "
                     "Faehigkeit wird nur einmal pro Zug ausgeloest.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("gain_life", {"count_selector": "sacrificed_cost_power"}),
                EffectSpec("add_counters", {
                    "target_kind": "creature_you_control",
                    "amount_from_count_selector": "sacrificed_cost_power",
                }),
            ],
            cost={"mana": "{2}", "taps_self": True,
                  "text": "{2}, {T}, Sacrifice another creature"},
            raw_text="{2}, {T}, opfere eine andere Kreatur: Du erhaeltst X Lebenspunkte "
                     "und legst X +1/+1-Marker auf eine Zielkreatur, die du "
                     "kontrollierst, wobei X die Staerke der geopferten Kreatur ist.",
        ),
    ]


register("Dina, Essence Brewer", _dina_essence_brewer)


# ===========================================================================
# wave 24 — Quandrix Unlimited singletons (+ Emeria, a Lorehold land)
# ===========================================================================


def _lotus_field() -> list[AbilitySpec]:
    """Hexproof
    This land enters tapped.
    When this land enters, sacrifice two lands.
    {T}: Add three mana of any one color.

    Hexproof / enters-tapped / the mana ability all come from the ordinary
    keyword + land pipelines; only the ETB self-sacrifice needs authoring."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"what": "land", "count": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Land ins Spiel kommt, opferst du zwei Laender.",
        ),
    ]


register("Lotus Field", _lotus_field)


def _staff_of_the_storyteller() -> list[AbilitySpec]:
    """When this artifact enters, create a 1/1 white Spirit creature token
    with flying.
    Whenever you create one or more creature tokens, put a story counter on
    this artifact.
    {W}, {T}, Remove a story counter from this artifact: Draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Spirit", "power": 1, "toughness": 1,
                "colors": ["W"], "subtypes": ["Spirit"], "keywords": ["flying"],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Artefakt ins Spiel kommt, erzeuge einen 1/1 weissen "
                     "Geist-Kreaturtoken mit Fliegend.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "story"})],
            trigger={
                "event": EventType.CREATE_TOKENS,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
                "limit": True,
            },
            raw_text="Immer wenn du einen oder mehr Kreaturtoken erzeugst, lege eine "
                     "Geschichtsmarke auf dieses Artefakt.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"mana": "{W}", "taps_self": True, "remove_counters": ["story", 1]},
            raw_text="{W}, {T}, entferne eine Geschichtsmarke von diesem Artefakt: "
                     "Ziehe eine Karte.",
        ),
    ]


register("Staff of the Storyteller", _staff_of_the_storyteller)


def _emeria_the_sky_ruin() -> list[AbilitySpec]:
    """This land enters tapped.
    At the beginning of your upkeep, if you control seven or more Plains, you
    may return target creature card from your graveyard to the battlefield.
    {T}: Add {W}."""
    EMERIA_PLAINS_THRESHOLD = 7
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "optional": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {
                    "kind": "control_count",
                    "selector": "lands_you_control_of_type_plains",
                    "min": EMERIA_PLAINS_THRESHOLD,
                },
            },
            raw_text="Zu Beginn deines Versorgungssegments, falls du sieben oder mehr "
                     "Ebenen kontrollierst, darfst du eine Zielkreaturenkarte aus deinem "
                     "Friedhof auf das Schlachtfeld zurueckbringen.",
        ),
    ]


register("Emeria, the Sky Ruin", _emeria_the_sky_ruin)


def _hangarback_walker() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    When this creature dies, create a 1/1 colorless Thopter artifact creature
    token with flying for each +1/+1 counter on this creature.
    {1}, {T}: Put a +1/+1 counter on this creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Thopter", "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Thopter"], "keywords": ["flying"], "artifact": True,
                "count_from_trigger_event_counter": "+1/+1",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur stirbt, erzeuge einen 1/1 farblosen "
                     "Thopter-Artefaktkreaturtoken mit Fliegend fuer jede +1/+1-Marke "
                     "auf dieser Kreatur.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            cost={"mana": "{1}", "taps_self": True},
            raw_text="{1}, {T}: Lege eine +1/+1-Marke auf diese Kreatur.",
        ),
    ]


register("Hangarback Walker", _hangarback_walker)


def _ingenious_prodigy() -> list[AbilitySpec]:
    """Skulk
    This creature enters with X +1/+1 counters on it.
    At the beginning of your upkeep, if this creature has one or more +1/+1
    counters on it, you may remove a +1/+1 counter from it. If you do, draw a
    card."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("remove_counters", {}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "source_counters", "counter": "+1/+1", "min": 1},
            },
            optional=True,
            raw_text="Zu Beginn deines Versorgungssegments, falls sich eine oder mehr "
                     "+1/+1-Marken auf dieser Kreatur befinden, darfst du eine "
                     "+1/+1-Marke von ihr entfernen. Falls du dies tust, ziehe eine Karte.",
        ),
    ]


register("Ingenious Prodigy", _ingenious_prodigy)


def _zimone_quandrix_prodigy() -> list[AbilitySpec]:
    """{1}, {T}: You may put a land card from your hand onto the battlefield
    tapped.
    {4}, {T}: Draw a card. If you control eight or more lands, draw two cards
    instead."""
    ZIMONE_LAND_THRESHOLD = 8
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": {"type": "land"}, "count": 1, "tapped": True, "optional": True,
            })],
            cost={"text": "{1}, {T}"},
            raw_text="{1}, {T}: Du darfst eine Landkarte aus deiner Hand getappt ins "
                     "Spiel bringen.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "condition": {
                    "count_selector_at_least": {"selector": "lands_you_control",
                                                "count": ZIMONE_LAND_THRESHOLD},
                }}),
            ],
            cost={"text": "{4}, {T}"},
            raw_text="{4}, {T}: Ziehe eine Karte. Falls du acht oder mehr Laender "
                     "kontrollierst, ziehe stattdessen zwei Karten.",
        ),
    ]


register("Zimone, Quandrix Prodigy", _zimone_quandrix_prodigy)


def _expansion_algorithm() -> list[AbilitySpec]:
    """Proliferate X times."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("proliferate", {"times": "x"})],
            raw_text="Wende X-mal Auswucherung an.",
        ),
    ]


register("Expansion Algorithm", _expansion_algorithm)


def _mana_bloom() -> list[AbilitySpec]:
    """This enchantment enters with X charge counters on it.
    Remove a charge counter from this enchantment: Add one mana of any color.
    Activate only once each turn.
    At the beginning of your upkeep, if this enchantment has no charge
    counters on it, return it to its owner's hand."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_mana", {"colors": ["ANY"]}),
                EffectSpec("once_per_turn_marker", {}),
            ],
            cost={"remove_counters": ["charge", 1]},
            raw_text="Entferne eine Ladungsmarke von dieser Verzauberung: Erzeuge ein "
                     "Mana einer beliebigen Farbe. Aktiviere nur einmal pro Zug.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "source_counters", "counter": "charge", "max": 0},
            },
            raw_text="Zu Beginn deines Versorgungssegments, falls sich keine "
                     "Ladungsmarken auf dieser Verzauberung befinden, bringe sie auf "
                     "die Hand ihres Besitzers zurueck.",
        ),
    ]


register("Mana Bloom", _mana_bloom)


# ===========================================================================
# wave 25 — Witherbloom Pestilence: Eldrazi Spawn / devour token payoffs,
# recursion, and the sacrifice tail. Engine: ``plus_one_counters_on_source``
# `continuous.count_selector`; ``opponent_life_at_most`` `static_conditions`
# kind.
# ===========================================================================
#
# Documented simplification shared by Awakening Zone / Pawn of Ulamog: the
# 0/1 Eldrazi Spawn token is created as a plain colourless body — its own
# "Sacrifice this creature: Add {C}" mana ability is not baked on (no
# `create_token` param grants a token a quoted activated ability yet).


def _awakening_zone() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may create a 0/1 colorless
    Eldrazi Spawn creature token. It has "Sacrifice this token: Add {C}."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Eldrazi Spawn", "power": 0, "toughness": 1,
                "colors": [], "subtypes": ["Eldrazi", "Spawn"],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            optional=True,
            raw_text="Zu Beginn deines Versorgungssegments darfst du einen 0/1 farblosen "
                     "Eldrazi-Brut-Kreaturtoken erzeugen.",
        ),
    ]


register("Awakening Zone", _awakening_zone)


def _pawn_of_ulamog() -> list[AbilitySpec]:
    """Whenever this creature or another nontoken creature you control dies,
    you may create a 0/1 colorless Eldrazi Spawn creature token. It has
    "Sacrifice this token: Add {C}."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Eldrazi Spawn", "power": 0, "toughness": 1,
                "colors": [], "subtypes": ["Eldrazi", "Spawn"],
            })],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
                "filter": {"want_token": False},
            },
            optional=True,
            raw_text="Immer wenn diese oder eine andere Nichtspielstein-Kreatur, die du "
                     "kontrollierst, stirbt, darfst du einen 0/1 farblosen "
                     "Eldrazi-Brut-Kreaturtoken erzeugen.",
        ),
    ]


register("Pawn of Ulamog", _pawn_of_ulamog)


def _mycoloth() -> list[AbilitySpec]:
    """Devour 2
    At the beginning of your upkeep, create a 1/1 green Saproling creature
    token for each +1/+1 counter on this creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Saproling", "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Saproling"], "count_selector": "plus_one_counters_on_source",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments erzeuge einen 1/1 gruenen "
                     "Setzling-Kreaturtoken fuer jede +1/+1-Marke auf dieser Kreatur.",
        ),
    ]


register("Mycoloth", _mycoloth)


def _ribtruss_roaster() -> list[AbilitySpec]:
    """Devour 1
    At the beginning of your end step, create a number of 1/1 black and green
    Pest creature tokens equal to the number of +1/+1 counters on this
    creature. They have "When this token dies, you gain 1 life."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Pest", "power": 1, "toughness": 1, "colors": ["B", "G"],
                "subtypes": ["Pest"], "count_selector": "plus_one_counters_on_source",
                "token_dies_gain_life": 1,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text='Zu Beginn deines Endsegments erzeuge so viele 1/1 schwarz-gruene '
                     'Ungeziefer-Kreaturtoken mit "Wenn dieser Token stirbt, erhaeltst '
                     'du 1 Lebenspunkt", wie +1/+1-Marken auf dieser Kreatur liegen.',
        ),
    ]


register("Ribtruss Roaster", _ribtruss_roaster)


def _beledros_witherbloom() -> list[AbilitySpec]:
    """Flying
    At the beginning of each upkeep, create a 1/1 black and green Pest
    creature token with "When this token dies, you gain 1 life."
    Pay 10 life: Untap all lands you control. Activate only once each turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Pest", "power": 1, "toughness": 1,
                "colors": ["B", "G"], "subtypes": ["Pest"], "token_dies_gain_life": 1,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text='Zu Beginn jedes Versorgungssegments erzeuge einen 1/1 '
                     'schwarz-gruenen Ungeziefer-Kreaturtoken mit "Wenn dieser Token '
                     'stirbt, erhaeltst du 1 Lebenspunkt".',
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("tap", {"selector": "lands_you_control", "untap": True}),
                EffectSpec("once_per_turn_marker", {}),
            ],
            cost={"text": "Pay 10 life"},
            raw_text="Bezahle 10 Lebenspunkte: Enttappe alle Laender, die du "
                     "kontrollierst. Aktiviere nur einmal pro Zug.",
        ),
    ]


register("Beledros Witherbloom", _beledros_witherbloom)


def _haywire_mite() -> list[AbilitySpec]:
    """When this creature dies, you gain 2 life.
    {G}, Sacrifice this creature: Exile target noncreature artifact or
    noncreature enchantment.

    Documented simplification: the target is modeled as ``artifact_or_
    enchantment`` — the "noncreature" narrowing isn't expressible on the
    exile target kind, so an artifact-creature / enchantment-creature is a
    legal target here where the real card forbids it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 2})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur stirbt, erhaeltst du 2 Lebenspunkte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "artifact_or_enchantment"})],
            cost={"mana": "{G}", "text": "{G}, Sacrifice ~"},
            raw_text="{G}, opfere diese Kreatur: Exiliere ein Ziel-Artefakt oder eine "
                     "Zielverzauberung, das bzw. die keine Kreatur ist.",
        ),
    ]


register("Haywire Mite", _haywire_mite)


def _bloodghast() -> list[AbilitySpec]:
    """This creature can't block.
    This creature has haste as long as an opponent has 10 or less life.
    Landfall — Whenever a land you control enters, you may return this card
    from your graveyard to the battlefield."""
    BLOODGHAST_LIFE_THRESHOLD = 10
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})],
            raw_text="Diese Kreatur kann nicht blocken.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["haste"], "affects": "self",
                "active_if": {"kind": "opponent_life_at_most", "amount": BLOODGHAST_LIFE_THRESHOLD},
            })],
            raw_text="Diese Kreatur hat Eile, solange ein Gegner 10 oder weniger "
                     "Lebenspunkte hat.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard", {"tapped": False})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you",
                              "other": False},
            },
            optional=True,
            raw_text="Landfall — Immer wenn ein Land unter deiner Kontrolle ins Spiel "
                     "kommt, darfst du diese Karte aus deinem Friedhof auf das "
                     "Schlachtfeld zurueckbringen.",
        ),
    ]


register("Bloodghast", _bloodghast)


def _nether_traitor() -> list[AbilitySpec]:
    """Haste
    Shadow
    Whenever another creature is put into your graveyard from the
    battlefield, you may pay {B}. If you do, return this card from your
    graveyard to the battlefield.

    Documented simplification: "into your graveyard" (ownership) is modeled
    as "another creature you control dies" (control) — the common case."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{B}",
                "effects": [{"type": "return_self_from_graveyard", "params": {}}],
            })],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "controller": "you", "other": True}},
            raw_text="Immer wenn eine andere Kreatur von einem Schlachtfeld auf deinen "
                     "Friedhof gelegt wird, darfst du {B} bezahlen. Falls du dies tust, "
                     "bringe diese Karte aus deinem Friedhof auf das Schlachtfeld "
                     "zurueck.",
        ),
    ]


register("Nether Traitor", _nether_traitor)


def _deadly_brew() -> list[AbilitySpec]:
    """Each player sacrifices a creature or planeswalker of their choice. If
    you sacrificed a permanent this way, you may return another permanent
    card from your graveyard to your hand.

    Documented simplification: the "if you sacrificed a permanent this way"
    gate and the "another" narrowing are dropped — the return is offered as
    an optional graveyard-permanent pick."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {
                    "selector": "each_player", "what": "creature_or_planeswalker", "count": 1,
                }),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_permanent", "destination": "hand", "optional": True,
                }),
            ],
            raw_text="Jeder Spieler opfert eine Kreatur oder einen Planeswalker seiner "
                     "Wahl. Falls du auf diese Weise ein Permanent geopfert hast, darfst "
                     "du eine andere Permanentkarte aus deinem Friedhof auf deine Hand "
                     "zurueckbringen.",
        ),
    ]


register("Deadly Brew", _deadly_brew)


# ===========================================================================
# wave 26 — Lorehold "land catch-up" + "a card left your graveyard this turn"
# ===========================================================================
# Engine: `static_conditions` kinds `opponent_controls_more_lands` and
# `card_left_graveyard_this_turn` (the latter backed by the new
# `GameState.cards_left_graveyard_this_turn` per-turn set).


def _land_tax() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if an opponent controls more lands
    than you, you may search your library for up to three basic land cards,
    reveal them, put them into your hand, then shuffle."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"basic": True}, "count": 3, "destination": "hand",
                "optional": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
            raw_text="Zu Beginn deines Versorgungssegments, falls ein Gegner mehr Laender "
                     "als du kontrolliert, darfst du deine Bibliothek nach bis zu drei "
                     "Standardland-Karten durchsuchen, sie offen auf deine Hand nehmen "
                     "und dann mischen.",
        ),
    ]


register("Land Tax", _land_tax)


def _archaeomancers_map() -> list[AbilitySpec]:
    """When this artifact enters, search your library for up to two basic
    Plains cards, reveal them, put them into your hand, then shuffle.
    Whenever a land an opponent controls enters, if that player controls more
    lands than you, you may put a land card from your hand onto the
    battlefield.

    Documented simplification: the intervening-if is "any opponent controls
    more lands than you" rather than "the player whose land entered" — a
    difference only in a 3+ player game where a *different* opponent is
    ahead."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"basic": True, "type": "plains"}, "count": 2,
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Artefakt ins Spiel kommt, durchsuche deine Bibliothek "
                     "nach bis zu zwei Standard-Ebenen-Karten, nimm sie offen auf deine "
                     "Hand und mische dann.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": {"type": "land"}, "count": 1, "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "not_you",
                              "other": True},
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
            raw_text="Immer wenn ein Land unter der Kontrolle eines Gegners ins Spiel "
                     "kommt und jener Spieler mehr Laender als du kontrolliert, darfst du "
                     "eine Landkarte aus deiner Hand ins Spiel bringen.",
        ),
    ]


register("Archaeomancer's Map", _archaeomancers_map)


def _claim_jumper() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, if an opponent controls more lands than you,
    you may search your library for a Plains card and put it onto the
    battlefield tapped. Then if an opponent controls more lands than you,
    repeat this process once. If you search your library this way, shuffle.

    Documented simplification: "repeat this process once" is modeled as a
    single search for *up to two* Plains onto the battlefield tapped."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "plains"}, "count": 2,
                "destination": "battlefield_tapped", "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"},
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
            raw_text="Wenn diese Kreatur ins Spiel kommt und ein Gegner mehr Laender als "
                     "du kontrolliert, darfst du deine Bibliothek nach bis zu zwei "
                     "Ebenen-Karten durchsuchen und sie getappt ins Spiel bringen.",
        ),
    ]


register("Claim Jumper", _claim_jumper)


def _primary_research() -> list[AbilitySpec]:
    """When this enchantment enters, return target nonland permanent card
    with mana value 3 or less from your graveyard to the battlefield.
    At the beginning of your end step, if a card left your graveyard this
    turn, draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": 3,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung ins Spiel kommt, bringe eine "
                     "Nichtland-Permanentkarte mit Manawert 3 oder weniger aus deinem "
                     "Friedhof auf das Schlachtfeld zurueck.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "card_left_graveyard_this_turn"},
            },
            raw_text="Zu Beginn deines Endsegments, falls in diesem Zug eine Karte "
                     "deinen Friedhof verlassen hat, ziehe eine Karte.",
        ),
    ]


register("Primary Research", _primary_research)


def _relic_retriever() -> list[AbilitySpec]:
    """First strike
    At the beginning of each end step, if a card left your graveyard this
    turn, create a Treasure token."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "card_left_graveyard_this_turn"},
            },
            raw_text="Zu Beginn jedes Endsegments, falls in diesem Zug eine Karte deinen "
                     "Friedhof verlassen hat, erzeuge einen Schatz-Token.",
        ),
    ]


register("Relic Retriever", _relic_retriever)


# ===========================================================================
# wave 27 — the "~ becomes prepared" trigger cluster (STX Learn/Prepared DFCs)
# ===========================================================================
# The `become_prepared` effect + the parser's own body handler already exist;
# only the trigger *headers* were unreachable. Engine: binder predicates
# `spell_mana_value_at_least` and `attackers_at_least`; `static_conditions`
# kinds `graveyard_card_type_count_at_least`, `any_player_cards_in_hand_at_most`.


def _eiganjo_dynastorian() -> list[AbilitySpec]:
    """Vigilance
    Whenever you attack with two or more creatures, this creature becomes
    prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"},
                     "attackers_at_least": 2},
            raw_text="Immer wenn du mit zwei oder mehr Kreaturen angreifst, wird diese "
                     "Kreatur vorbereitet.",
        ),
    ]


register("Eiganjo Dynastorian", _eiganjo_dynastorian)
register("Eiganjo Dynastorian // Replenish", _eiganjo_dynastorian)


def _dirgur_focusmage() -> list[AbilitySpec]:
    """Instant and sorcery spells you cast cost {1} less to cast.
    Whenever you cast an instant or sorcery spell with mana value 5 or
    greater from your hand, this creature becomes prepared."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 1, "spell_type": ["instant", "sorcery"],
            })],
            raw_text="Spontanzauber und Hexereien, die du wirkst, kosten {1} weniger.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "spell_mana_value_at_least": 5,
                "filter": {"from_hand": True},
            },
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei mit Manawert 5 "
                     "oder mehr aus deiner Hand wirkst, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Dirgur Focusmage", _dirgur_focusmage)
register("Dirgur Focusmage // Braingeyser", _dirgur_focusmage)


def _lorehold_archivist() -> list[AbilitySpec]:
    """First strike
    At the beginning of your upkeep, if there are three or more artifact
    and/or creature cards in your graveyard, this creature becomes
    prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "graveyard_card_type_count_at_least",
                              "types": ["artifact", "creature"], "amount": 3},
            },
            raw_text="Zu Beginn deines Versorgungssegments, falls sich drei oder mehr "
                     "Artefakt- und/oder Kreaturenkarten in deinem Friedhof befinden, "
                     "wird diese Kreatur vorbereitet.",
        ),
    ]


register("Lorehold Archivist", _lorehold_archivist)
register("Lorehold Archivist // Restore Relic", _lorehold_archivist)


def _naktamun_lorespinner() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if a player has one or fewer cards in
    hand, this creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "any_player_cards_in_hand_at_most", "amount": 1},
            },
            raw_text="Zu Beginn deines Versorgungssegments, falls ein Spieler eine oder "
                     "weniger Karten auf der Hand hat, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Naktamun Lorespinner", _naktamun_lorespinner)
register("Naktamun Lorespinner // Wheel of Fortune", _naktamun_lorespinner)


def _inspired_skypainter() -> list[AbilitySpec]:
    """Flying
    When this creature enters and whenever one or more creature tokens you
    control deal combat damage to a player, this creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, wird sie vorbereitet.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn ein oder mehr Kreaturtoken, die du kontrollierst, einem "
                     "Spieler Kampfschaden zufuegen, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Inspired Skypainter", _inspired_skypainter)
register("Inspired Skypainter // Maestro's Gift", _inspired_skypainter)


def _firemane_commando() -> list[AbilitySpec]:
    """Flying
    Whenever you attack with two or more creatures, draw a card.
    Whenever another player attacks with two or more creatures, they draw a
    card if none of those creatures attacked you.

    Documented simplification: only the "you attack" half is modeled; the
    symmetric "another player" gift-draw is dropped (a rare political
    corner)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"},
                     "attackers_at_least": 2},
            raw_text="Immer wenn du mit zwei oder mehr Kreaturen angreifst, ziehe eine Karte.",
        ),
    ]


register("Firemane Commando", _firemane_commando)


# ===========================================================================
# wave 28 — Prismari "Artistry": instant/sorcery cast-matters payoffs
# ===========================================================================
# Engine: `PumpEffect.amount_from_count_selector_axis` now also governs the
# ``amount_from_trigger_event`` path (Renegade Bull's +X/+0).


def _prismari_pianist() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, create a 1/1 blue and
    red Elemental creature token. If that spell's mana value is 5 or greater,
    create three of those tokens instead.

    Modeled as two mana-value-gated SPELL_CAST triggers (<=4 -> 1 token,
    >=5 -> 3), exactly one of which fires per cast."""
    def _tok(count):
        return EffectSpec("create_token", {
            "count": count, "token_name": "Elemental", "power": 1, "toughness": 1,
            "colors": ["U", "R"], "subtypes": ["Elemental"],
        })
    base = {"subject": "group", "controller": "you"}
    return [
        AbilitySpec(
            "triggered", [_tok(1)],
            trigger={"event": EventType.SPELL_CAST, "condition": dict(base),
                     "spell_card_types": ["instant", "sorcery"],
                     "spell_mana_value_at_most": 4},
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei mit Manawert 4 "
                     "oder weniger wirkst, erzeuge einen 1/1 blau-roten "
                     "Elementarwesen-Kreaturtoken.",
        ),
        AbilitySpec(
            "triggered", [_tok(3)],
            trigger={"event": EventType.SPELL_CAST, "condition": dict(base),
                     "spell_card_types": ["instant", "sorcery"],
                     "spell_mana_value_at_least": 5},
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei mit Manawert 5 "
                     "oder mehr wirkst, erzeuge drei davon.",
        ),
    ]


register("Prismari Pianist", _prismari_pianist)


def _manaform_hellkite() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a noncreature spell, create an X/X red Dragon Illusion
    creature token with flying and haste, where X is the amount of mana spent
    to cast that spell. Exile that token at the beginning of the next end
    step."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Dragon Illusion", "colors": ["R"],
                    "subtypes": ["Dragon", "Illusion"], "keywords": ["flying", "haste"],
                    "pt_from_trigger_event": "mana_spent",
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_exclude_card_types": ["creature"],
            },
            raw_text="Immer wenn du einen Nicht-Kreatur-Zauberspruch wirkst, erzeuge "
                     "einen X/X roten Drache-Illusion-Kreaturtoken mit Fliegend und "
                     "Eile, wobei X so viel ist wie das fuer jenen Zauberspruch "
                     "ausgegebene Mana. Exiliere jenen Token zu Beginn des naechsten "
                     "Endsegments.",
        ),
    ]


register("Manaform Hellkite", _manaform_hellkite)


def _leitmotif_composer() -> list[AbilitySpec]:
    """Whenever this creature deals combat damage to a player, draw a card.
    Whenever you cast an instant or sorcery spell with mana value 5 or
    greater, create a token that's a copy of this creature.
    {2}{U}: Creatures named Leitmotif Composer can't be blocked this turn.

    Documented simplification: the {2}{U} mass-unblockable activated ability
    is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"is_player": True, "combat": True}},
            raw_text="Immer wenn diese Kreatur einem Spieler Kampfschaden zufuegt, "
                     "ziehe eine Karte.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token_copy_of_named", {"card_name": "Leitmotif Composer"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
                "spell_mana_value_at_least": 5,
            },
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei mit Manawert 5 "
                     "oder mehr wirkst, erzeuge einen Token, der eine Kopie dieser "
                     "Kreatur ist.",
        ),
    ]


register("Leitmotif Composer", _leitmotif_composer)


def _renegade_bull() -> list[AbilitySpec]:
    """Trample
    Whenever you cast an instant or sorcery spell, this creature gets +X/+0
    until end of turn, where X is that spell's mana value.
    Whenever this creature attacks, exile up to one target instant or sorcery
    card from your graveyard and copy it. You may cast the copy without
    paying its mana cost.

    Documented simplification: the attack-trigger flashback-copy clause is
    not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0,
                "amount_from_trigger_event": "mana_value",
                "amount_from_count_selector_axis": "power",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei wirkst, erhaelt "
                     "diese Kreatur +X/+0 bis zum Ende des Zuges, wobei X der Manawert "
                     "jenes Zauberspruchs ist.",
        ),
    ]


register("Renegade Bull", _renegade_bull)


def _deekah_fractal_theorist() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    create a 0/0 green and blue Fractal creature token. Put X +1/+1 counters
    on it, where X is that spell's mana value.
    {3}{U}: Target creature token can't be blocked this turn.

    Documented simplification: the {3}{U} unblockable activated ability is
    not modeled; "or copy" is covered by the `SPELL_CAST` trigger (no
    separate spell-copy event bus)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
                "colors": ["G", "U"], "subtypes": ["Fractal"],
                "extra_counters": {"kind": "+1/+1", "count_from_trigger_event": "mana_value"},
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Zauberkunst — Immer wenn du einen Spontanzauber oder eine Hexerei "
                     "wirkst oder kopierst, erzeuge einen 0/0 gruen-blauen "
                     "Fraktal-Kreaturtoken. Lege X +1/+1-Marken darauf, wobei X der "
                     "Manawert jenes Zauberspruchs ist.",
        ),
    ]


register("Deekah, Fractal Theorist", _deekah_fractal_theorist)


def _galazeth_prismari() -> list[AbilitySpec]:
    """Flying
    When Galazeth Prismari enters, create a Treasure token.
    Artifacts you control have "{T}: Add one mana of any color. Spend this
    mana only to cast an instant or sorcery spell."

    Documented simplification: the granted mana ability's "spend only to
    cast an instant or sorcery spell" restriction is not modeled — the mana
    is unrestricted."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Galazeth Prismari ins Spiel kommt, erzeuge einen Schatz-Token.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "artifacts_you_control",
                "mana": [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}],
            })],
            raw_text='Artefakte, die du kontrollierst, haben "{T}: Erzeuge ein Mana einer '
                     'beliebigen Farbe."',
        ),
    ]


register("Galazeth Prismari", _galazeth_prismari)


# ===========================================================================
# wave 29 — Quandrix charge-counter / {X}-matters singletons
# ===========================================================================
# Engine: `SPELL_CAST` event now carries ``has_x``; binder predicate
# ``spell_has_x`` reads it.


def _astral_cornucopia() -> list[AbilitySpec]:
    """This artifact enters with X charge counters on it.
    {T}: Choose a color. Add one mana of that color for each charge counter
    on this artifact."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "amount_selector": "charge_counters_on_source",
            })],
            cost={"text": "{T}"},
            raw_text="{T}: Waehle eine Farbe. Erzeuge ein Mana dieser Farbe fuer jede "
                     "Ladungsmarke auf diesem Artefakt.",
        ),
    ]


register("Astral Cornucopia", _astral_cornucopia)


def _elementalists_palette() -> list[AbilitySpec]:
    """Whenever you cast a spell with {X} in its mana cost, put two charge
    counters on this artifact.
    {T}: Add one mana of any color.
    {T}: Add {C} for each charge counter on this artifact. Spend this mana
    only on costs that contain {X}.

    Only the {X}-cast trigger needs authoring; the two plain mana abilities
    fold in from the parser. Documented simplification: the second mana
    ability's "spend only on {X} costs" restriction is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "charge", "count": 2})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
            },
            raw_text="Immer wenn du einen Zauberspruch mit {X} in seinen Manakosten "
                     "wirkst, lege zwei Ladungsmarken auf dieses Artefakt.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"colors": ["ANY"]})],
            cost={"text": "{T}"},
            raw_text="{T}: Erzeuge ein Mana einer beliebigen Farbe.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {
                "colors": ["C"], "amount_selector": "charge_counters_on_source",
            })],
            cost={"text": "{T}"},
            raw_text="{T}: Erzeuge {C} fuer jede Ladungsmarke auf diesem Artefakt.",
        ),
    ]


register("Elementalist's Palette", _elementalists_palette)


def _silkguard() -> list[AbilitySpec]:
    """Put a +1/+1 counter on each of up to X target creatures you control.
    Auras, Equipment, and modified creatures you control gain hexproof until
    end of turn.

    Documented simplification: the second clause is modeled as "creatures
    you control gain hexproof until end of turn" — the Aura/Equipment and
    "modified" narrowing isn't expressible on the mass-pump selector."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {
                    "target_kind": "creature_you_control", "count": "x", "count_max": "x",
                    "kind": "+1/+1",
                }),
                EffectSpec("pump", {
                    "selector": "creatures_you_control", "keywords": ["hexproof"],
                }),
            ],
            raw_text="Lege eine +1/+1-Marke auf jede von bis zu X Zielkreaturen, die du "
                     "kontrollierst. Kreaturen, die du kontrollierst, erhalten "
                     "Fluchsicherheit bis zum Ende des Zuges.",
        ),
    ]


register("Silkguard", _silkguard)


# ===========================================================================
# wave 30 — Lorehold spirits: graveyard-reanimate-by-dynamic-mv + phasing
# ===========================================================================
# Engine: `targeting.legal_targets` gained ``max_mana_value`` sentinels
# ``source_power`` and ``trigger_damage_amount``.


def _guardian_scalelord() -> list[AbilitySpec]:
    """Backup 1
    Flying
    Whenever this creature attacks, return target nonland permanent card with
    mana value X or less from your graveyard to the battlefield, where X is
    this creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": "source_power",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, bringe eine Nichtland-"
                     "Permanentkarte mit Manawert X oder weniger aus deinem Friedhof "
                     "auf das Schlachtfeld zurueck, wobei X die Staerke dieser Kreatur "
                     "ist.",
        ),
    ]


register("Guardian Scalelord", _guardian_scalelord)


def _venerable_warsinger() -> list[AbilitySpec]:
    """Vigilance, trample
    Whenever this creature deals combat damage to a player, you may return
    target creature card with mana value X or less from your graveyard to the
    battlefield, where X is the amount of damage this creature dealt to that
    player."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "max_mana_value": "trigger_damage_amount", "optional": True,
            })],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"is_player": True, "combat": True}},
            raw_text="Immer wenn diese Kreatur einem Spieler Kampfschaden zufuegt, "
                     "darfst du eine Zielkreaturenkarte mit Manawert X oder weniger aus "
                     "deinem Friedhof auf das Schlachtfeld zurueckbringen, wobei X so "
                     "viel ist wie der jenem Spieler zugefuegte Schaden.",
        ),
    ]


register("Venerable Warsinger", _venerable_warsinger)


def _drumbellower() -> list[AbilitySpec]:
    """Flying
    Untap all creatures you control during each other player's untap step."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"selector": "creatures_you_control", "untap": True})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "untap"},
                     "phase_relation": "not_you"},
            raw_text="Enttappe alle Kreaturen, die du kontrollierst, waehrend des "
                     "Enttappsegments jedes anderen Spielers.",
        ),
    ]


register("Drumbellower", _drumbellower)


def _guardian_of_faith() -> list[AbilitySpec]:
    """Flash
    Vigilance
    When this creature enters, any number of other target creatures you
    control phase out."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("phase_out", {
                "target_kind": "other_creature_you_control", "count": 10, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, lassen beliebig viele andere "
                     "Zielkreaturen, die du kontrollierst, aus der Phase gehen.",
        ),
    ]


register("Guardian of Faith", _guardian_of_faith)


# ===========================================================================
# wave 31 — mixed singletons on small new primitives
# ===========================================================================
# Engine: `_mass_wipe_objects` ``enchanted`` filter (Winds of Rath);
# `cost_reduction_for` ``reduce_if_targets`` (Killian, Ink Duelist);
# `continuous.count_selector` ``total_power_creatures_you_control`` (Volcanic
# Salvo); `DealDamageEffect` selector
# ``each_creature_and_planeswalker_opponents_control`` (Volcanic Torrent);
# binder predicate ``entering_mana_value_at_most`` (Tocasia's Welcome).


def _winds_of_rath() -> list[AbilitySpec]:
    """Destroy all creatures that aren't enchanted. They can't be
    regenerated."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "selector": "all_creatures", "filter": {"enchanted": False},
                "can_be_regenerated": False,
            })],
            raw_text="Zerstoere alle Kreaturen, die nicht verzaubert sind. Sie koennen "
                     "nicht regeneriert werden.",
        ),
    ]


register("Winds of Rath", _winds_of_rath)


def _the_goose_mother() -> list[AbilitySpec]:
    """Flying
    The Goose Mother enters with X +1/+1 counters on it.
    When The Goose Mother enters, create half X Food tokens, rounded up.
    Whenever The Goose Mother attacks, you may sacrifice a Food. If you do,
    draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": "half_x_up", "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn The Goose Mother ins Spiel kommt, erzeuge die Haelfte von X "
                     "Nahrung-Token, aufgerundet.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Sacrifice a Food",
                "effects": [{"type": "draw", "params": {"count": 1}}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn The Goose Mother angreift, darfst du eine Nahrung "
                     "opfern. Falls du dies tust, ziehe eine Karte.",
        ),
    ]


register("The Goose Mother", _the_goose_mother)


def _killian_ink_duelist() -> list[AbilitySpec]:
    """Lifelink
    Menace
    Spells you cast that target a creature cost {2} less to cast."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 2,
                "reduce_if_targets": {"is_creature": True},
            })],
            raw_text="Zaubersprueche, die du wirkst und die eine Kreatur als Ziel haben, "
                     "kosten {2} weniger.",
        ),
    ]


register("Killian, Ink Duelist", _killian_ink_duelist)


def _volcanic_salvo() -> list[AbilitySpec]:
    """This spell costs {X} less to cast, where X is the total power of
    creatures you control.
    Volcanic Salvo deals 6 damage to each of up to two target creatures
    and/or planeswalkers."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1,
                "per": "total_power_creatures_you_control",
            })],
            raw_text="Dieser Zauberspruch kostet {X} weniger, wobei X die Gesamtstaerke "
                     "der Kreaturen ist, die du kontrollierst.",
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 6, "target_kind": "creature_or_planeswalker", "count": 2,
                "optional": True,
            })],
            raw_text="~ fuegt jeder von bis zu zwei Zielkreaturen und/oder "
                     "-planeswalkern 6 Schadenspunkte zu.",
        ),
    ]


register("Volcanic Salvo", _volcanic_salvo)


def _volcanic_torrent() -> list[AbilitySpec]:
    """Cascade
    Volcanic Torrent deals X damage to each creature and planeswalker your
    opponents control, where X is the number of spells you've cast this
    turn."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "selector": "each_creature_and_planeswalker_opponents_control",
                "amount_from_count_selector": "spells_cast_this_turn",
            })],
            raw_text="~ fuegt jeder Kreatur und jedem Planeswalker, die deine Gegner "
                     "kontrollieren, X Schadenspunkte zu, wobei X die Anzahl der "
                     "Zaubersprueche ist, die du in diesem Zug gewirkt hast.",
        ),
    ]


register("Volcanic Torrent", _volcanic_torrent)


def _tocasias_welcome() -> list[AbilitySpec]:
    """Whenever one or more creatures you control with mana value 3 or less
    enter, draw a card. This ability triggers only once each turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "creature", "controller": "you",
                              "other": False},
                "entering_mana_value_at_most": 3,
                "limit": True,
            },
            raw_text="Immer wenn eine oder mehr Kreaturen mit Manawert 3 oder weniger, "
                     "die du kontrollierst, ins Spiel kommen, ziehe eine Karte. Diese "
                     "Faehigkeit wird nur einmal pro Zug ausgeloest.",
        ),
    ]


register("Tocasia's Welcome", _tocasias_welcome)


# ===========================================================================
# wave 32 — modal "choose one [or more]" spells
# ===========================================================================
# Engine: `_mass_wipe_objects` ``token`` filter (Perplexing Test).


def _casualties_of_war() -> list[AbilitySpec]:
    """Choose one or more —
    • Destroy target artifact.
    • Destroy target creature.
    • Destroy target enchantment.
    • Destroy target land.
    • Destroy target planeswalker."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "at_least": True,
                "options": [
                    [EffectSpec("destroy", {"target_kind": "artifact"})],
                    [EffectSpec("destroy", {"target_kind": "creature"})],
                    [EffectSpec("destroy", {"target_kind": "enchantment"})],
                    [EffectSpec("destroy", {"target_kind": "land"})],
                    [EffectSpec("destroy", {"target_kind": "planeswalker"})],
                ],
                "descriptions": [
                    "Zerstoere ein Ziel-Artefakt.",
                    "Zerstoere eine Zielkreatur.",
                    "Zerstoere eine Zielverzauberung.",
                    "Zerstoere ein Zielland.",
                    "Zerstoere einen Zielplaneswalker.",
                ],
            },
            raw_text="Waehle eins oder mehr —",
        ),
    ]


register("Casualties of War", _casualties_of_war)


def _final_act() -> list[AbilitySpec]:
    """Choose one or more —
    • Destroy all creatures.
    • Destroy all planeswalkers.
    • Destroy all battles.
    • Exile all graveyards.
    • Each opponent loses all counters.

    Documented simplification: "Destroy all battles" is modeled as
    ``selector="all_battles"`` (inert if the mass-wipe helper doesn't know
    the selector — no cached battle in these decks reaches it)."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "at_least": True,
                "options": [
                    [EffectSpec("destroy", {"selector": "all_creatures"})],
                    [EffectSpec("destroy", {"selector": "all_planeswalkers"})],
                    [EffectSpec("destroy", {"selector": "all_battles"})],
                    [EffectSpec("exile_all_graveyards", {})],
                    [EffectSpec("lose_all_player_counters", {"selector": "each_opponent"})],
                ],
                "descriptions": [
                    "Zerstoere alle Kreaturen.",
                    "Zerstoere alle Planeswalker.",
                    "Zerstoere alle Kaempfe.",
                    "Exiliere alle Friedhoefe.",
                    "Jeder Gegner verliert alle Marken.",
                ],
            },
            raw_text="Waehle eins oder mehr —",
        ),
    ]


register("Final Act", _final_act)


def _perplexing_test() -> list[AbilitySpec]:
    """Choose one —
    • Return all creature tokens to their owners' hands.
    • Return all nontoken creatures to their owners' hands."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("return_to_hand", {
                        "selector": "all_creatures", "filter": {"token": True},
                    })],
                    [EffectSpec("return_to_hand", {
                        "selector": "all_creatures", "filter": {"token": False},
                    })],
                ],
                "descriptions": [
                    "Bringe alle Kreaturtoken auf die Haende ihrer Besitzer zurueck.",
                    "Bringe alle Nichtspielstein-Kreaturen auf die Haende ihrer Besitzer zurueck.",
                ],
            },
            raw_text="Waehle eins —",
        ),
    ]


register("Perplexing Test", _perplexing_test)


# ===========================================================================
# wave 33 — Quandrix "your first spell with {X} in its mana cost each turn"
# ===========================================================================
# Engine: `GameState.cast_x_spell_this_turn` per-turn set + `SPELL_CAST`
# ``first_x_spell`` flag + binder predicate ``first_x_spell``; count_selector
# ``study_counters_on_source``.


def _zimone_infinite_analyst() -> list[AbilitySpec]:
    """The first spell you cast with {X} in its mana cost each turn costs {1}
    less to cast for each +1/+1 counter on Zimone.
    Whenever you cast your first spell with {X} in its mana cost each turn,
    put two +1/+1 counters on Zimone.

    Documented simplification: the per-counter cost reduction on that first
    {X} spell is not modeled — only the +1/+1 counter payoff."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
            raw_text="Immer wenn du deinen ersten Zauberspruch mit {X} in seinen "
                     "Manakosten in einem Zug wirkst, lege zwei +1/+1-Marken auf Zimone.",
        ),
    ]


register("Zimone, Infinite Analyst", _zimone_infinite_analyst)


def _owlin_spiralmancer() -> list[AbilitySpec]:
    """Flying, vigilance
    Whenever you cast your first spell with {X} in its mana cost each turn,
    you may copy it. You may choose new targets for the copy."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
            optional=True,
            raw_text="Immer wenn du deinen ersten Zauberspruch mit {X} in seinen "
                     "Manakosten in einem Zug wirkst, darfst du ihn kopieren.",
        ),
    ]


register("Owlin Spiralmancer", _owlin_spiralmancer)


def _nev_the_practical_dean() -> list[AbilitySpec]:
    """Creatures you control with counters on them have trample.
    Whenever you cast your first spell with {X} in its mana cost each turn,
    put X +1/+1 counters on Nev.

    Documented simplifications: "with counters" is narrowed to "with +1/+1
    counters"; the counter payoff uses the firing spell's mana value as X
    (exact for an {X}-only cost)."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["trample"],
                "has_counter_kind": "+1/+1",
            })],
            raw_text="Kreaturen, die du kontrollierst und auf denen Marken liegen, "
                     "haben Trampelschaden.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount_from_trigger_event": "mana_value",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
            raw_text="Immer wenn du deinen ersten Zauberspruch mit {X} in seinen "
                     "Manakosten in einem Zug wirkst, lege X +1/+1-Marken auf Nev.",
        ),
    ]


register("Nev, the Practical Dean", _nev_the_practical_dean)


def _lattice_library() -> list[AbilitySpec]:
    """This enchantment enters with X study counters on it.
    When this enchantment enters and whenever you cast your first spell with
    {X} in its mana cost each turn, create a 0/0 green and blue Fractal
    creature token. Put a number of +1/+1 counters on it equal to the number
    of study counters on this enchantment."""
    def _make():
        return EffectSpec("create_token", {
            "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
            "colors": ["G", "U"], "subtypes": ["Fractal"],
            "extra_counters": {"kind": "+1/+1",
                               "count_from_count_selector": "study_counters_on_source"},
        })
    return [
        AbilitySpec(
            "triggered", [_make()],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung ins Spiel kommt, erzeuge einen 0/0 "
                     "gruen-blauen Fraktal-Kreaturtoken mit study-Marken-vielen "
                     "+1/+1-Marken.",
        ),
        AbilitySpec(
            "triggered", [_make()],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
            raw_text="Immer wenn du deinen ersten Zauberspruch mit {X} in seinen "
                     "Manakosten in einem Zug wirkst, erzeuge einen solchen Fraktal-Token.",
        ),
    ]


register("Lattice Library", _lattice_library)


# ===========================================================================
# wave 34 — mixed singletons
# ===========================================================================
# Engine: binder predicate ``defender_is_you`` (Mangara / Tomik).


def _pest_infestation() -> list[AbilitySpec]:
    """Destroy up to X target artifacts and/or enchantments. Create twice X
    1/1 black and green Pest creature tokens with "When this token dies, you
    gain 1 life."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {
                    "target_kind": "artifact_or_enchantment", "count": "x", "count_max": "x",
                    "optional": True,
                }),
                EffectSpec("create_token", {
                    "x_multiplier": 2, "token_name": "Pest",
                    "power": 1, "toughness": 1, "colors": ["B", "G"], "subtypes": ["Pest"],
                    "token_dies_gain_life": 1,
                }),
            ],
            raw_text="Zerstoere bis zu X Ziel-Artefakte und/oder -Verzauberungen. Erzeuge "
                     'zweimal X 1/1 schwarz-gruene Ungeziefer-Kreaturtoken mit "Wenn '
                     'dieser Token stirbt, erhaeltst du 1 Lebenspunkt".',
        ),
    ]


register("Pest Infestation", _pest_infestation)


def _excava_the_risen_past() -> list[AbilitySpec]:
    """Flying, haste
    Whenever Excava attacks, return up to one target artifact, creature, or
    non-Aura enchantment card with mana value 3 or less from your graveyard
    to the battlefield with a finality counter on it. It's a 1/1 Spirit
    creature with flying in addition to its other types.

    Documented simplification: the finality counter and the 1/1 Spirit
    flying type-overlay are not modeled — the card returns to the battlefield
    as-is."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": 3, "optional": True,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Excava angreift, bringe bis zu eine Ziel-Artefakt-, "
                     "-Kreaturen- oder Nicht-Aura-Verzauberungskarte mit Manawert 3 "
                     "oder weniger aus deinem Friedhof auf das Schlachtfeld zurueck.",
        ),
    ]


register("Excava, the Risen Past", _excava_the_risen_past)


def _mangara_the_diplomat() -> list[AbilitySpec]:
    """Lifelink
    Whenever an opponent attacks with creatures, if two or more of those
    creatures are attacking you and/or planeswalkers you control, draw a
    card.
    Whenever an opponent casts their second spell each turn, draw a card.

    Documented simplification: "attacking you and/or planeswalkers you
    control" is modeled as "attacking you" (the `PLAYER_ATTACKED` aggregate
    names the defending player, not a planeswalker)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "controller": "not_you"},
                "defender_is_you": True, "attackers_at_least": 2,
            },
            raw_text="Immer wenn ein Gegner mit Kreaturen angreift und zwei oder mehr "
                     "davon dich angreifen, ziehe eine Karte.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "is_nth_spell_cast_this_turn": 2,
            },
            raw_text="Immer wenn ein Gegner in einem Zug seinen zweiten Zauberspruch "
                     "wirkt, ziehe eine Karte.",
        ),
    ]


register("Mangara, the Diplomat", _mangara_the_diplomat)


def _tomik_wielder_of_law() -> list[AbilitySpec]:
    """Affinity for planeswalkers
    Flying, vigilance
    Whenever an opponent attacks with creatures, if two or more of those
    creatures are attacking you and/or planeswalkers you control, that
    opponent loses 3 life and you draw a card.

    Same "attacking you" simplification as Mangara. Affinity for
    planeswalkers folds in from the keyword catalogue."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 3, "selector": "event_player"}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "controller": "not_you"},
                "defender_is_you": True, "attackers_at_least": 2,
            },
            raw_text="Immer wenn ein Gegner mit Kreaturen angreift und zwei oder mehr "
                     "davon dich angreifen, verliert jener Gegner 3 Lebenspunkte und du "
                     "ziehst eine Karte.",
        ),
    ]


register("Tomik, Wielder of Law", _tomik_wielder_of_law)


# ===========================================================================
# wave 35 — Vanishing Verse (new target kind) + two manland/token singletons
# ===========================================================================
# Engine: `targeting` target kind ``monocolored_permanent`` (Vanishing Verse).


def _vanishing_verse() -> list[AbilitySpec]:
    """Exile target monocolored permanent."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {"target_kind": "monocolored_permanent"})],
            raw_text="Exiliere ein einfarbiges Zielpermanent.",
        ),
    ]


register("Vanishing Verse", _vanishing_verse)


def _restless_spire() -> list[AbilitySpec]:
    """This land enters tapped.
    {T}: Add {U} or {R}.
    {U}{R}: Until end of turn, this land becomes a 2/1 blue and red Elemental
    creature with "During your turn, this creature has first strike." It's
    still a land.
    Whenever this land attacks, scry 1.

    — the Restless Cottage manland template. Documented simplifications: the
    colour change and the "during your turn" narrowing on first strike are
    not modeled (the animated creature keeps first strike unconditionally
    while animated)."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": None,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Elemental"],
                        "power": 2, "toughness": 1,
                    }},
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": None,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["first strike"]}},
                }),
            ],
            cost={"text": "{U}{R}"},
            raw_text="{U}{R}: Bis zum Ende des Zuges wird dieses Land zu einer 2/1 "
                     "blau-roten Elementarwesen-Kreatur mit Erstschlag. Es ist "
                     "weiterhin ein Land.",
        ),
    ]


register("Restless Spire", _restless_spire)


def _determined_iteration() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, populate. The token created
    this way gains haste. Sacrifice it at the beginning of the next end step.

    Documented simplification: "gains haste" is not modeled — the populated
    copy is sacrificed at the next end step regardless, and it copies an
    existing token whose keywords (often haste already) it inherits."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("populate", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn des Kampfes in deinem Zug, bevoelkere. Opfere den so "
                     "erzeugten Token zu Beginn des naechsten Endsegments.",
        ),
    ]


register("Determined Iteration", _determined_iteration)


# ===========================================================================
# wave 36 — attack-trigger P/T match, mass keyword strip, end-step exile+token
# ===========================================================================


def _tanazir_quandrix() -> list[AbilitySpec]:
    """Flying, trample
    When Tanazir Quandrix enters, double the number of +1/+1 counters on
    target creature you control.
    Whenever Tanazir Quandrix attacks, you may have the base power and
    toughness of other creatures you control become equal to Tanazir
    Quandrix's power and toughness until end of turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {
                "target_kind": "creature_you_control", "kind": "+1/+1",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Tanazir Quandrix ins Spiel kommt, verdopple die Anzahl der "
                     "+1/+1-Marken auf einer Zielkreatur, die du kontrollierst.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "pt_cda", "params": {
                    "affects": "other_creatures_you_control",
                    "power_count": "source_power", "toughness_count": "source_toughness",
                }},
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            optional=True,
            raw_text="Immer wenn Tanazir Quandrix angreift, kannst du bewirken, dass die "
                     "Grundstaerke und -widerstandskraft anderer Kreaturen, die du "
                     "kontrollierst, bis zum Ende des Zuges gleich der Staerke und "
                     "Widerstandskraft von Tanazir Quandrix werden.",
        ),
    ]


register("Tanazir Quandrix", _tanazir_quandrix)


def _arcane_lighthouse() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}, {T}: Until end of turn, creatures your opponents control lose
    hexproof and shroud and can't have hexproof or shroud.

    Documented simplification: the "can't have" clause (a prohibition on
    *re-gaining* those keywords this turn) is not modeled — the keywords are
    stripped for the turn."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "remove_keyword", "params": {
                    "affects": "creatures_opponents_control",
                    "keywords": ["hexproof", "shroud"],
                }},
            })],
            cost={"mana": "{1}", "taps_self": True},
            raw_text="{1}, {T}: Bis zum Ende des Zuges verlieren Kreaturen, die deine "
                     "Gegner kontrollieren, Fluchsicherheit und Schutz.",
        ),
    ]


register("Arcane Lighthouse", _arcane_lighthouse)


def _quintorius_loremaster() -> list[AbilitySpec]:
    """Vigilance
    At the beginning of your end step, exile target noncreature, nonland card
    from your graveyard. Create a 3/2 red and white Spirit creature token.
    {1}{R}{W}, {T}, Sacrifice a Spirit: Choose target card exiled with
    Quintorius. You may cast that card this turn without paying its mana
    cost. …

    Documented simplifications: the end-step exile target is modeled as any
    graveyard card (the "noncreature, nonland" narrowing isn't on the
    kind); the "cast a card exiled with Quintorius" activated ability is not
    modeled."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_target_graveyard", {"target_kind": "graveyard_card"}),
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Spirit", "power": 3, "toughness": 2,
                    "colors": ["R", "W"], "subtypes": ["Spirit"],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments exiliere eine Nicht-Kreatur- und "
                     "Nicht-Land-Zielkarte aus deinem Friedhof. Erzeuge einen 3/2 "
                     "rot-weissen Geist-Kreaturtoken.",
        ),
    ]


register("Quintorius, Loremaster", _quintorius_loremaster)


# ===========================================================================
# wave 37 — a few more tractable singletons
# ===========================================================================
# Engine: `ConditionalEffect` gained ``previous_target_power_at_least``
# (Yavimaya Bloomsage).


def _yavimaya_bloomsage() -> list[AbilitySpec]:
    """At the beginning of your end step, put a +1/+1 counter on target
    creature you control. Then if that creature has power 7 or greater, this
    creature becomes prepared."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"target_kind": "creature_you_control",
                                            "kind": "+1/+1", "count": 1}),
                EffectSpec("become_prepared", {},
                           condition={"previous_target_power_at_least": 7}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments lege eine +1/+1-Marke auf eine "
                     "Zielkreatur, die du kontrollierst. Falls jene Kreatur dann "
                     "Staerke 7 oder mehr hat, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Yavimaya Bloomsage", _yavimaya_bloomsage)
register("Yavimaya Bloomsage // Channel", _yavimaya_bloomsage)


def _herald_of_amity() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exile the top eight cards of your library. You
    may cast an Aura spell from among them without paying its mana cost. Then
    put the rest on the bottom of your library in a random order.
    Whenever this creature attacks, it gets +X/+X until end of turn, where X
    is the number of Auras you control.

    Documented simplification: the ETB is modeled with
    ``draw_reveal_cast_one_free`` (count 8) — the eight cards go to hand
    rather than being exiled/bottomed, and the free cast is not narrowed to
    an Aura. The attack pump ("+X/+X where X is the number of Auras you
    control") is modeled via a per-count anthem pump on ``self``."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_reveal_cast_one_free", {"count": 8})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, sieh dir die obersten acht "
                     "Karten deiner Bibliothek an. Du darfst einen Aura-Zauberspruch "
                     "von ihnen wirken, ohne seine Manakosten zu bezahlen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 1, "toughness": 1,
                "amount_from_count_selector": "auras_you_control",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, erhaelt sie +X/+X bis zum Ende "
                     "des Zuges, wobei X die Anzahl der Auren ist, die du kontrollierst.",
        ),
    ]


register("Herald of Amity", _herald_of_amity)


# ===========================================================================
# wave 38 — more singletons on existing primitives
# ===========================================================================


def _curse_of_the_swine() -> list[AbilitySpec]:
    """Exile X target creatures. For each creature exiled this way, its
    controller creates a 2/2 green Boar creature token.

    Documented simplification: all X Boars go to the *first* exiled
    creature's controller (`creators="previous_target_controller"` reads
    only one previous target) — exact in a two-player game where every
    exiled creature has the same controller, a precision loss only in
    multiplayer."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {"target_kind": "creature", "count": "x", "count_max": "x"}),
                EffectSpec("create_token", {
                    "creators": "previous_target_controller", "count": "x",
                    "token_name": "Boar", "power": 2, "toughness": 2,
                    "colors": ["G"], "subtypes": ["Boar"],
                }),
            ],
            raw_text="Exiliere X Zielkreaturen. Fuer jede auf diese Weise exilierte "
                     "Kreatur erzeugt ihr Beherrscher einen 2/2 gruenen "
                     "Wildschwein-Kreaturtoken.",
        ),
    ]


register("Curse of the Swine", _curse_of_the_swine)


def _forum_filibuster() -> list[AbilitySpec]:
    """At the beginning of your upkeep, create a 2/1 white and black Inkling
    creature token with flying. When you do, return up to one target Aura or
    Equipment card from your graveyard to the battlefield attached to that
    token.

    Documented simplification: the "attached to that token" placement of the
    returned Aura/Equipment is not modeled — it returns to the battlefield
    on its own (an Equipment stays unattached; an Aura with no legal object
    is put into the graveyard by SBA, a rare corner these decks don't lean
    on)."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Inkling", "power": 2, "toughness": 1,
                    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
                }),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_artifact_or_creature", "destination": "battlefield",
                    "optional": True,
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments erzeuge einen 2/1 "
                     "weiss-schwarzen Tintling-Kreaturtoken mit Fliegend. Wenn du dies "
                     "tust, bringe bis zu eine Ziel-Aura- oder -Ausruestungskarte aus "
                     "deinem Friedhof auf das Schlachtfeld zurueck.",
        ),
    ]


register("Forum Filibuster", _forum_filibuster)


# ===========================================================================
# wave 39 — Gyome / Jadar (new per-turn tracker + keyword-scoped condition)
# ===========================================================================
# Engine: `GameState.nontoken_creatures_entered_this_turn` +
# `continuous.count_selector` ``nontoken_creatures_you_entered_this_turn``;
# `static_conditions` kind ``control_no_creatures_with_keyword``.


def _gyome_master_chef() -> list[AbilitySpec]:
    """Trample
    At the beginning of your end step, create a number of Food tokens equal
    to the number of nontoken creatures you had enter the battlefield under
    your control this turn.
    {1}, Sacrifice a Food: Target creature gains indestructible until end of
    turn. Tap it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Food",
                "count_selector": "nontoken_creatures_you_entered_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments erzeuge so viele Nahrung-Token wie "
                     "Nichtspielstein-Kreaturen in diesem Zug unter deiner Kontrolle "
                     "ins Spiel gekommen sind.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("pump", {"keywords": ["indestructible"], "target_kind": "creature"}),
                EffectSpec("tap", {"target_kind": None}),
            ],
            cost={"text": "{1}, Sacrifice a Food"},
            raw_text="{1}, opfere eine Nahrung: Eine Zielkreatur erhaelt Unzerstoerbarkeit "
                     "bis zum Ende des Zuges. Tappe sie.",
        ),
    ]


register("Gyome, Master Chef", _gyome_master_chef)


def _jadar_ghoulcaller_of_nephalia() -> list[AbilitySpec]:
    """At the beginning of your end step, if you control no creatures with
    decayed, create a 2/2 black Zombie creature token with decayed."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Zombie", "power": 2, "toughness": 2,
                "colors": ["B"], "subtypes": ["Zombie"], "keywords": ["decayed"],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
                "active_if": {"kind": "control_no_creatures_with_keyword", "keyword": "decayed"},
            },
            raw_text="Zu Beginn deines Endsegments, falls du keine Kreaturen mit "
                     "Verfall kontrollierst, erzeuge einen 2/2 schwarzen "
                     "Zombie-Kreaturtoken mit Verfall.",
        ),
    ]


register("Jadar, Ghoulcaller of Nephalia", _jadar_ghoulcaller_of_nephalia)


# ===========================================================================
# wave 40 — the "that many plus one +1/+1 counters" replacement (Hardened
# Scales family) + Kinetic Ooze's X-tiered ETB
# ===========================================================================
# All on existing primitives: the `double_counters` replacement's ``plus``
# param, and `EffectSpec.condition`'s ``source_x_paid_at_least`` key.


def _ozolith_the_shattered_spire() -> list[AbilitySpec]:
    """If one or more +1/+1 counters would be put on an artifact or creature
    you control, that many plus one +1/+1 counters are put on it instead.
    {1}{G}, {T}: Put a +1/+1 counter on target artifact or creature you
    control. Activate only as a sorcery.
    Cycling {2}

    Documented simplification: "an artifact or creature you control" is
    modeled as ``recipient="permanent_you_control"`` — a noncreature
    nonartifact permanent you control (a land, an enchantment) would also
    get the +1 here, a rare corner."""
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_counters", {
                "kind": "+1/+1", "plus": 1, "recipient": "permanent_you_control",
            })],
            raw_text="Falls eine oder mehr +1/+1-Marken auf ein Artefakt oder eine "
                     "Kreatur, die du kontrollierst, gelegt wuerden, werden stattdessen "
                     "so viele plus eine +1/+1-Marke darauf gelegt.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"target_kind": "artifact_or_creature_you_control",
                                            "kind": "+1/+1", "count": 1}),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost={"mana": "{1}{G}", "taps_self": True},
            raw_text="{1}{G}, {T}: Lege eine +1/+1-Marke auf ein Ziel-Artefakt oder eine "
                     "Zielkreatur, die du kontrollierst. Aktiviere nur wie eine Hexerei.",
        ),
    ]


register("Ozolith, the Shattered Spire", _ozolith_the_shattered_spire)


def _benevolent_hydra() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    If one or more +1/+1 counters would be put on another creature you
    control, that many plus one +1/+1 counters are put on it instead.
    {T}, Remove a +1/+1 counter from this creature: Put a +1/+1 counter on
    another target creature you control.

    Documented simplification: the "another" exclusion on the replacement
    (Benevolent Hydra itself also getting the +1 when counters land on it)
    isn't expressible on the `double_counters` recipient scope — a minor
    over-application."""
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_counters", {
                "kind": "+1/+1", "plus": 1, "recipient": "creature_you_control",
            })],
            raw_text="Falls eine oder mehr +1/+1-Marken auf eine andere Kreatur, die du "
                     "kontrollierst, gelegt wuerden, werden stattdessen so viele plus "
                     "eine +1/+1-Marke darauf gelegt.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"target_kind": "other_creature_you_control",
                                         "kind": "+1/+1", "count": 1})],
            cost={"taps_self": True, "remove_counters": ["+1/+1", 1]},
            raw_text="{T}, entferne eine +1/+1-Marke von dieser Kreatur: Lege eine "
                     "+1/+1-Marke auf eine andere Zielkreatur, die du kontrollierst.",
        ),
    ]


register("Benevolent Hydra", _benevolent_hydra)


def _kinetic_ooze() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it.
    When this creature enters, destroy up to one target artifact or
    enchantment with mana value X or less. If X is 5 or more, you draw a
    card. If X is 10 or more, double the number of +1/+1 counters on any
    number of other target creatures."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"target_kind": "artifact_or_enchantment",
                                       "max_mana_value": "x", "optional": True}),
                EffectSpec("draw", {"count": 1},
                           condition={"source_x_paid_at_least": 5}),
                EffectSpec("double_counters_on_target",
                           {"target_kind": "creature", "kind": "+1/+1"},
                           condition={"source_x_paid_at_least": 10}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, zerstoere bis zu ein "
                     "Ziel-Artefakt oder eine Zielverzauberung mit Manawert X oder "
                     "weniger. Falls X 5 oder mehr ist, ziehe eine Karte. Falls X 10 "
                     "oder mehr ist, verdopple die Anzahl der +1/+1-Marken auf "
                     "beliebig vielen anderen Zielkreaturen.",
        ),
    ]


register("Kinetic Ooze", _kinetic_ooze)


# ===========================================================================
# wave 41 — "for each time you've cast your commander from the command zone"
# ===========================================================================
# Engine: `continuous.count_selector` ``commander_casts_this_game`` (sum of
# `Player.commander_casts`).


def _vanguard_of_the_restless() -> list[AbilitySpec]:
    """Flying
    Spirits you control get +1/+1 for each time you've cast your commander
    from the command zone this game.
    Whenever a Spirit you control enters, you may pay {2}{W}. If you do,
    return this card from your graveyard to the battlefield."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "subtype": "Spirit",
                "power": 1, "toughness": 1,
                "power_count": "commander_casts_this_game",
                "toughness_count": "commander_casts_this_game",
            })],
            raw_text="Geister, die du kontrollierst, erhalten +1/+1 fuer jedes Mal, das "
                     "du in diesem Spiel deinen Kommandeur aus der Kommandozone "
                     "gewirkt hast.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "pay {2}{W}",
                "effects": [{"type": "return_self_from_graveyard", "params": {"tapped": False}}],
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "subtypes": ["spirit"], "nontoken": False,
                              "controller": "you", "other": False},
            },
            raw_text="Immer wenn ein Geist, den du kontrollierst, ins Spiel kommt, "
                     "darfst du {2}{W} bezahlen. Falls du dies tust, bringe diese Karte "
                     "aus deinem Friedhof auf das Schlachtfeld zurueck.",
        ),
    ]


register("Vanguard of the Restless", _vanguard_of_the_restless)


def _commanders_insight() -> list[AbilitySpec]:
    """Target player draws X cards plus an additional card for each time
    they've cast a commander from the command zone this game.

    Documented simplification: the "for each time *they've* cast a commander"
    count is read as *your* commander-cast tally
    (``commander_casts_this_game`` is always the resolving controller's) —
    exact when you target yourself, an approximation otherwise."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"target_kind": "player", "count": "x"}),
                EffectSpec("draw", {"target_kind": "player",
                                    "count_selector": "commander_casts_this_game"}),
            ],
            raw_text="Ein Zielspieler zieht X Karten plus eine zusaetzliche Karte fuer "
                     "jedes Mal, das er in diesem Spiel einen Kommandeur aus der "
                     "Kommandozone gewirkt hat.",
        ),
    ]


register("Commander's Insight", _commanders_insight)


# ===========================================================================
# wave 42 — "whenever you discard a card, exile it from your graveyard,
# then you may play it this turn"
# ===========================================================================
# Engine: `ExileTriggeringDiscardMayPlayThisTurnEffect`
# ("exile_triggering_discard_may_play_this_turn").


def _containment_construct() -> list[AbilitySpec]:
    """Whenever you discard a card, you may exile that card from your
    graveyard. If you do, you may play that card this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {})],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
            raw_text="Immer wenn du eine Karte abwirfst, darfst du jene Karte aus deinem "
                     "Friedhof exilieren. Falls du dies tust, darfst du jene Karte in "
                     "diesem Zug spielen.",
        ),
    ]


register("Containment Construct", _containment_construct)


def _conspiracy_theorist() -> list[AbilitySpec]:
    """Whenever this creature attacks, you may pay {1} and discard a card. If
    you do, draw a card.
    Whenever you discard one or more nonland cards, you may exile one of them
    from your graveyard. If you do, you may cast it this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}",
                "effects": [
                    {"type": "discard", "params": {"count": 1}},
                    {"type": "draw", "params": {"count": 1}},
                ],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, darfst du {1} bezahlen und eine "
                     "Karte abwerfen. Falls du dies tust, ziehe eine Karte.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {})],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
            raw_text="Immer wenn du eine oder mehr Nichtland-Karten abwirfst, darfst du "
                     "eine davon aus deinem Friedhof exilieren. Falls du dies tust, "
                     "darfst du sie in diesem Zug wirken.",
        ),
    ]


register("Conspiracy Theorist", _conspiracy_theorist)


# ===========================================================================
# wave 43 — Prismari cast-triggered copy effects
# ===========================================================================


def _muddle_the_ever_changing() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, Muddle becomes a copy
    of up to one target nonlegendary creature you control until end of turn,
    except it has myriad.

    Documented simplifications: "up to one target" is modeled as a required
    target; the "except it has myriad" grant is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_copy_until_eot", {"target_kind": "creature_you_control"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Immer wenn du einen Spontanzauber oder eine Hexerei wirkst, wird "
                     "Muddle bis zum Ende des Zuges zu einer Kopie von bis zu einer "
                     "nichtlegendaeren Zielkreatur, die du kontrollierst.",
        ),
    ]


register("Muddle, the Ever-Changing", _muddle_the_ever_changing)


def _rionya_fire_dancer() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, create X tokens that are
    copies of another target creature you control, where X is one plus the
    number of instant and sorcery spells you've cast this turn. They gain
    haste. Exile them at the beginning of the next end step.

    Documented simplifications: X is modeled as *the number of spells you've
    cast this turn* (`spells_cast_this_turn`), missing the "+1" and the
    instant/sorcery narrowing."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "other_creature_you_control",
                    "count_selector": "spells_cast_this_turn", "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn des Kampfes in deinem Zug erzeuge X Token, die Kopien "
                     "einer anderen Zielkreatur sind, die du kontrollierst, wobei X "
                     "eins plus die Anzahl der in diesem Zug von dir gewirkten "
                     "Spontanzauber und Hexereien ist. Sie erhalten Eile. Exiliere sie "
                     "zu Beginn des naechsten Endsegments.",
        ),
    ]


register("Rionya, Fire Dancer", _rionya_fire_dancer)


# ===========================================================================
# wave 44 — a copy-spell activated ability + a graveyard-recycle land
# ===========================================================================


def _rootha_mercurial_artist() -> list[AbilitySpec]:
    """{2}, Return Rootha to its owner's hand: Copy target instant or sorcery
    spell you control. You may choose new targets for the copy."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]})],
            cost={"mana": "{2}", "text": "{2}, Return ~ to its owner's hand"},
            raw_text="{2}, bringe Rootha auf die Hand ihres Besitzers zurueck: Kopiere "
                     "einen Ziel-Spontanzauber oder eine Zielhexerei, die du "
                     "kontrollierst. Du darfst neue Ziele fuer die Kopie bestimmen.",
        ),
    ]


register("Rootha, Mercurial Artist", _rootha_mercurial_artist)


def _mistveil_plains() -> list[AbilitySpec]:
    """({T}: Add {W}.)
    This land enters tapped.
    {W}, {T}: Put target card from your graveyard on the bottom of your
    library. Activate only if you control two or more white permanents.

    Documented simplification: the "activate only if you control two or more
    white permanents" gate is not modeled — the ability is always
    available."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("graveyard_to_library_bottom_random", {"target_kind": "graveyard_card"})],
            cost={"mana": "{W}", "taps_self": True},
            raw_text="{W}, {T}: Lege eine Zielkarte aus deinem Friedhof unter deine "
                     "Bibliothek.",
        ),
    ]


register("Mistveil Plains", _mistveil_plains)


# ===========================================================================
# wave 45 — Fractal Harness ETB + Ceaseless Conflict board wipe
# ===========================================================================
# Engine: ``permanents_destroyed_this_way`` added to
# `_TOKEN_COUNT_CONTEXT_ACCUMULATORS`.


def _fractal_harness() -> list[AbilitySpec]:
    """When this Equipment enters, create a 0/0 green and blue Fractal
    creature token. Put X +1/+1 counters on it and attach this Equipment to
    it.
    Whenever equipped creature attacks, double the number of +1/+1 counters
    on it.
    Equip {2}"""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Fractal", "power": 0, "toughness": 0,
                    "colors": ["G", "U"], "subtypes": ["Fractal"],
                    "extra_counters": {"kind": "+1/+1",
                                       "count_from_count_selector": "source_x_paid"},
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Ausruestung ins Spiel kommt, erzeuge einen 0/0 "
                     "gruen-blauen Fraktal-Kreaturtoken. Lege X +1/+1-Marken darauf "
                     "und lege diese Ausruestung an ihn an.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("double_counters_on_target", {"target_kind": "attached_permanent",
                                                      "kind": "+1/+1"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Immer wenn die ausgeruestete Kreatur angreift, verdopple die "
                     "Anzahl der +1/+1-Marken auf ihr.",
        ),
    ]


register("Fractal Harness", _fractal_harness)


def _ceaseless_conflict() -> list[AbilitySpec]:
    """Destroy all creatures. Then create a 3/2 red and white Spirit creature
    token for each nontoken creature you controlled that was destroyed this
    way.

    Documented simplification: the token count is *every* creature destroyed
    (`permanents_destroyed_this_way`), not just your nontoken ones."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures"}),
                EffectSpec("create_token", {
                    "token_name": "Spirit", "power": 3, "toughness": 2,
                    "colors": ["R", "W"], "subtypes": ["Spirit"],
                    "count_from_context": "permanents_destroyed_this_way",
                }),
            ],
            raw_text="Zerstoere alle Kreaturen. Erzeuge dann einen 3/2 rot-weissen "
                     "Geist-Kreaturtoken fuer jede Nichtspielstein-Kreatur, die du "
                     "kontrolliert hast und die auf diese Weise zerstoert wurde.",
        ),
    ]


register("Ceaseless Conflict", _ceaseless_conflict)


# ===========================================================================
# wave 46 — Hydroid Krasis "half X" cast payoff
# ===========================================================================


def _hydroid_krasis() -> list[AbilitySpec]:
    """When you cast this spell, you gain half X life and draw half X cards.
    Round down each time.
    Flying, trample
    This creature enters with X +1/+1 counters on it.

    Documented simplification: the "when you cast this spell" trigger is
    modeled as a resolution (`spell_effect`) payoff — it happens as the
    spell resolves rather than on cast, a minor timing difference (it can't
    be responded to between). The ``half_x_down`` sentinel is rewritten by
    `RulesEngine._substitute_x` to floor(X/2)."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"amount": "half_x_down"}),
                EffectSpec("draw", {"count": "half_x_down"}),
            ],
            raw_text="Wenn du diesen Zauberspruch wirkst, erhaeltst du die Haelfte von X "
                     "Lebenspunkten und ziehst die Haelfte von X Karten. Runde jedes "
                     "Mal ab.",
        ),
    ]


register("Hydroid Krasis", _hydroid_krasis)


# ===========================================================================
# wave 47 — Feral Appetite (conditional-on-what-was-exiled) + Teshar (historic)
# ===========================================================================
# Engine: binder predicate ``spell_is_historic`` (Teshar).


def _feral_appetite() -> list[AbilitySpec]:
    """Attacking Pests you control get +1/+0 and have deathtouch.
    {1}{G}: Exile target card from a graveyard. If a creature card is exiled
    this way, create a 1/1 black and green Pest creature token with "When
    this token dies, you gain 1 life."

    The attacking-Pests anthem folds in from the parser (wave 19); only the
    activated ability's conditional token needs authoring."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_target_graveyard", {"target_kind": "graveyard_card"}),
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Pest", "power": 1, "toughness": 1,
                    "colors": ["B", "G"], "subtypes": ["Pest"], "token_dies_gain_life": 1,
                }, condition={"previous_target_is_creature": True}),
            ],
            cost={"mana": "{1}{G}"},
            raw_text="{1}{G}: Exiliere eine Zielkarte aus einem Friedhof. Falls auf "
                     "diese Weise eine Kreaturenkarte exiliert wird, erzeuge einen 1/1 "
                     'schwarz-gruenen Ungeziefer-Kreaturtoken mit "Wenn dieser Token '
                     'stirbt, erhaeltst du 1 Lebenspunkt".',
        ),
    ]


register("Feral Appetite", _feral_appetite)


def _teshar_ancestors_apostle() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a historic spell, return target creature card with mana
    value 3 or less from your graveyard to the battlefield. (Artifacts,
    legendaries, and Sagas are historic.)"""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield",
                "max_mana_value": 3,
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_is_historic": True,
            },
            raw_text="Immer wenn du einen historischen Zauberspruch wirkst, bringe eine "
                     "Zielkreaturenkarte mit Manawert 3 oder weniger aus deinem "
                     "Friedhof auf das Schlachtfeld zurueck.",
        ),
    ]


register("Teshar, Ancestor's Apostle", _teshar_ancestors_apostle)


# ===========================================================================
# wave 48 — Killian, Decisive Mentor (Aura-enchanted-creature attack trigger)
# ===========================================================================
# Engine: `_build_group_ok` gained the ``enchanted_by_your_aura`` filter.


def _killian_decisive_mentor() -> list[AbilitySpec]:
    """Whenever an enchantment you control enters, tap up to one target
    creature and goad it.
    Whenever one or more creatures that are enchanted by an Aura you control
    attack, draw a card.

    The first ability folds in from the parser; only the attack trigger
    needs authoring. Modeled as a per-creature ATTACKS trigger capped once
    per turn (RULE 603.3b "one or more" aggregate)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"target_kind": "creature", "optional": True}),
             EffectSpec("goad", {"target_kind": None})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "enchantment", "controller": "you",
                              "other": False},
            },
            raw_text="Immer wenn eine Verzauberung, die du kontrollierst, ins Spiel "
                     "kommt, tappe bis zu eine Zielkreatur und provoziere sie.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {"subject": "group", "controller": "you",
                              "enchanted_by_your_aura": True},
                "limit": True,
            },
            raw_text="Immer wenn eine oder mehr Kreaturen, die von einer Aura verzaubert "
                     "sind, die du kontrollierst, angreifen, ziehe eine Karte.",
        ),
    ]


register("Killian, Decisive Mentor", _killian_decisive_mentor)


# ===========================================================================
# wave 49 — "creatures matching FILTER can't attack you or planeswalkers you
# control" static (Eriette of the Charmed Apple, PAR-60)
# ===========================================================================
# Engine: new `cant_attack_defender` EffectRegistry static + the
# `continuous.defender_attack_prohibited` scan consulted by
# `combat_mixin._can_attack`. ``attacker_filter`` narrows which creatures the
# bar bites (``enchanted_by_controller_aura`` / ``subtype`` /
# ``has_counter_kind`` / ``has_any_counter``).


def _eriette_of_the_charmed_apple() -> list[AbilitySpec]:
    """Each creature that's enchanted by an Aura you control can't attack you
    or planeswalkers you control.
    At the beginning of your end step, each opponent loses X life and you gain
    X life, where X is the number of Auras you control.

    The end-step drain folds in from the parser (it fully claims that line);
    only the combat static needs authoring."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_attack_defender", {
                "defender_scope": "player_or_planeswalker",
                "attacker_filter": {"enchanted_by_controller_aura": True},
            })],
            raw_text="Jede Kreatur, die von einer Aura verzaubert ist, die du "
                     "kontrollierst, kann dich oder Planeswalker, die du kontrollierst, "
                     "nicht angreifen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "amount_from_count_selector": "creatures_you_control_of_type_aura",
                "selector": "each_opponent"}),
             EffectSpec("gain_life", {
                "count_selector": "creatures_you_control_of_type_aura"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments verliert jeder Gegner X Lebenspunkte "
                     "und du erhaeltst X Lebenspunkte, wobei X die Anzahl der Auras ist, "
                     "die du kontrollierst.",
        ),
    ]


register("Eriette of the Charmed Apple", _eriette_of_the_charmed_apple)


# ===========================================================================
# wave 50 — Quintorius, History Chaser (planeswalker: parser-claimed
# graveyard-exit token trigger + two loyalty abilities) — PAR-60
# ===========================================================================
# Engine: new `may_discard_then_draw_mill` effect (loot with a fixed
# payoff). The -4 reuses `pump` with a ``subtypes`` filter on a
# ``selector`` group (Valley Floodcaller idiom).


def _quintorius_history_chaser() -> list[AbilitySpec]:
    """Whenever one or more cards leave your graveyard, create a 3/2 red and
    white Spirit creature token.
    +1: You may discard a card. If you do, draw two cards, then mill a card.
    -4: Spirits you control gain double strike and vigilance until end of turn.

    The graveyard-exit trigger folds in from the parser (it fully claims
    that line); only the two loyalty abilities need authoring."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 2, "colors": ["R", "W"],
                "subtypes": ["Spirit"], "keywords": [], "token_name": "Spirit"})],
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you"},
            raw_text="Immer wenn eine oder mehr Karten deinen Friedhof verlassen, "
                     "erzeuge einen 3/2 rot-weissen Geist-Kreaturen-Token.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("may_discard_then_draw_mill", {"draw": 2, "mill": 1})],
            cost={"loyalty": 1},
            raw_text="+1: Du darfst eine Karte abwerfen. Falls du dies tust, ziehe zwei "
                     "Karten und muehle dann eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "keywords": ["double_strike", "vigilance"],
                "selector": "creatures_you_control", "subtypes": ["Spirit"]})],
            cost={"loyalty": -4},
            raw_text="-4: Geister, die du kontrollierst, erhalten Doppelschlag und "
                     "Wachsamkeit bis zum Ende des Zuges.",
        ),
    ]


register("Quintorius, History Chaser", _quintorius_history_chaser)


# ===========================================================================
# wave 51 — triggered-ability doubling generalized (PAR-60)
# ===========================================================================
# `TriggerDoublerEffect` (Roaming Throne / Elesh Norn / Delney) gained two
# scoping axes: ``subject_subtype_any`` (a fixed subtype list on the doubled
# permanent — Harmonic Prodigy) and ``cause_spell_type_any`` (narrows a
# ``cause_filter`` match to the firing spell's card types — Veyran).


def _veyran_voice_of_duality() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    Veyran gets +1/+1 until end of turn.
    If you casting or copying an instant or sorcery spell causes a triggered
    ability of a permanent you control to trigger, that ability triggers an
    additional time.

    The magecraft pump folds in from the parser (it fully claims that line);
    only the trigger-doubler clause needs authoring — an Elesh Norn-shaped
    ``cause_filter`` doubler narrowed to instant/sorcery casts."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_card_types": ["instant", "sorcery"]},
            raw_text="Magiekunst — Immer wenn du einen Spontanzauber oder eine Hexerei "
                     "wirkst oder kopierst, erhaelt Veyran +1/+1 bis zum Ende des Zuges.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {
                "cause_filter": [EventType.SPELL_CAST],
                "cause_spell_type_any": ["instant", "sorcery"]})],
            raw_text="Falls das Wirken oder Kopieren eines Spontanzaubers oder einer "
                     "Hexerei durch dich eine ausgeloeste Faehigkeit einer bleibenden "
                     "Karte, die du kontrollierst, ausloest, loest jene Faehigkeit ein "
                     "zusaetzliches Mal aus.",
        ),
    ]


register("Veyran, Voice of Duality", _veyran_voice_of_duality)


def _harmonic_prodigy() -> list[AbilitySpec]:
    """Prowess.
    If a triggered ability of a Shaman or another Wizard you control
    triggers, that ability triggers an additional time.

    Prowess folds in from the RULE 702 keyword catalogue even for a
    registered card; only the trigger-doubler clause needs authoring."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"subject_subtype_any": ["Shaman", "Wizard"]})],
            raw_text="Falls eine ausgeloeste Faehigkeit eines Schamanen oder eines "
                     "anderen Magiers, den du kontrollierst, ausgeloest wird, loest jene "
                     "Faehigkeit ein zusaetzliches Mal aus.",
        ),
    ]


register("Harmonic Prodigy", _harmonic_prodigy)


# ===========================================================================
# wave 52 — reveal-until-a-type impulse cast (PAR-60)
# ===========================================================================
# `RulesEngine.dig_until` (the generalized cascade dig) already does
# "reveal from the top until <predicate>, free-cast the hit, rest to the
# bottom in a random order". Creative Technique is exactly that with a
# ``shuffle`` prologue.


def _creative_technique() -> list[AbilitySpec]:
    """Demonstrate (folds in from the RULE 702 keyword catalogue).
    Shuffle your library, then reveal cards from the top of it until you
    reveal a nonland card. Exile that card and put the rest on the bottom of
    your library in a random order. You may cast the exiled card without
    paying its mana cost."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("shuffle", {}),
             EffectSpec("dig_until", {
                 "criteria": {"without_type": "land"},
                 "hit_destination": "cast_free_window",
                 "rest_destination": "library_bottom_random",
             })],
            raw_text="Mische deine Bibliothek und decke dann Karten oben von ihr auf, "
                     "bis du eine Nichtland-Karte aufdeckst. Exiliere jene Karte und lege "
                     "den Rest zufaellig geordnet unter deine Bibliothek. Du darfst die "
                     "exilierte Karte wirken, ohne ihre Manakosten zu bezahlen.",
        ),
    ]


register("Creative Technique", _creative_technique)


# ===========================================================================
# wave 53 — ``entered_this_turn`` object filter key (PAR-60)
# ===========================================================================
# `combat.matches_object_filter` gained an ``entered_this_turn`` key
# (`GameObject.turn_entered` vs the current turn), and `AddCountersEffect`'s
# ``selector`` branch now threads ``state`` into that call so a mass
# counter effect can narrow to just-entered creatures.


def _oran_rief_the_vastwood() -> list[AbilitySpec]:
    """This land enters tapped.  {T}: Add {G}.  (both from the land pipeline)
    {T}: Put a +1/+1 counter on each green creature that entered this turn."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "selector": "each_creature",
                "creature_filter": {"color": "G", "entered_this_turn": True},
            })],
            cost={"text": "{T}"},
            raw_text="{T}: Lege eine +1/+1-Marke auf jede gruene Kreatur, die in diesem "
                     "Zug ins Spiel gekommen ist.",
        ),
    ]


register("Oran-Rief, the Vastwood", _oran_rief_the_vastwood)


# ===========================================================================
# wave 54 — permanent (RULE 611.2 no-duration) gain-control one-shot (PAR-60)
# ===========================================================================
# `GainControlUntilEndOfTurnEffect` (Zealous Conscripts family) gained a
# ``duration`` axis: ``"permanent"`` + ``untap=False`` + ``haste=False`` is
# the Mind Control / Control Magic / Persuasion / Corrupted Conscience /
# Entrancing Melody family — a bare, non-reverting ``controller_id`` change.


def _entrancing_melody() -> list[AbilitySpec]:
    """Gain control of target creature with mana value X.

    Documented simplification: modeled as ``max_mana_value`` (mv <= X), the
    engine's only mana-value target cap — very slightly more permissive than
    the printed exact "mana value X", but the caster picks X to hit the
    creature they want anyway."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("gain_control_until_eot", {
                "target_kind": "creature", "max_mana_value": "x",
                "duration": "permanent", "untap": False, "haste": False,
            })],
            raw_text="Uebernimm die Kontrolle ueber eine Zielkreatur mit Manawert X.",
        ),
    ]


register("Entrancing Melody", _entrancing_melody)


# ===========================================================================
# wave 55 — magecraft + ``impulsive_look`` (PAR-60)
# ===========================================================================
# `ImpulsiveLookEffect` ("look at the top N, take one matching a filter,
# rest to Y") already does exactly Quandrix Apprentice's dig.


def _quandrix_apprentice() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    look at the top three cards of your library. You may reveal a land card
    from among them and put that card into your hand. Put the rest on the
    bottom of your library in any order.

    Documented simplification: like the parser's own magecraft modeling,
    "or copy" is treated as just the cast."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_look", {
                "count": 3, "criteria": {"type": "land"},
                "hit_destination": "hand",
                "miss_destination": "library_bottom_random",
                "optional": True,
            })],
            trigger={"event": EventType.SPELL_CAST,
                     "condition": {"subject": "group", "controller": "you"},
                     "spell_card_types": ["instant", "sorcery"]},
            raw_text="Magiekunst — Immer wenn du einen Spontanzauber oder eine Hexerei "
                     "wirkst oder kopierst, sieh dir die obersten drei Karten deiner "
                     "Bibliothek an. Du darfst eine Landkarte aus ihnen offen vorzeigen "
                     "und auf deine Hand nehmen. Lege den Rest unter deine Bibliothek.",
        ),
    ]


register("Quandrix Apprentice", _quandrix_apprentice)


# ===========================================================================
# wave 56 — ``per_opponent`` token creation (PAR-60)
# ===========================================================================
# `CreateTokenEffect.per_opponent` ("for each opponent, create a … token")
# already exists; Furygale Flocking is that with ``count=2``.


def _furygale_flocking() -> list[AbilitySpec]:
    """This spell costs {1} less for each instant/sorcery card in your
    graveyard (folds in from the parser).
    For each opponent, create two 3/3 blue and red Elemental creature tokens
    with flying that attack that opponent this turn if able. They gain haste
    until end of turn.

    Documented simplification: the "attack that opponent this turn if able"
    directed requirement is dropped (no turn-scoped directed must-attack
    designation for a freshly created token); the tokens keep flying + haste
    and the caster swings them. Haste is baked on rather than until-end-of-
    turn — unobservable past the turn they're made (summoning sickness)."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_token", {
                "count": 2, "per_opponent": True, "power": 3, "toughness": 3,
                "colors": ["U", "R"], "subtypes": ["Elemental"],
                "keywords": ["flying", "haste"], "token_name": "Elemental",
            })],
            raw_text="Erzeuge fuer jeden Gegner zwei 3/3 blau-rote Elementar-"
                     "Kreaturtoken mit Fliegend, die in diesem Zug jenen Gegner "
                     "angreifen, wenn moeglich. Sie erhalten Eile bis zum Ende des Zuges.",
        ),
    ]


register("Furygale Flocking", _furygale_flocking)


# ===========================================================================
# wave 57 — Chaos Warp (shuffle a permanent away + reveal-top) — PAR-60
# ===========================================================================
# New `shuffle_target_into_library_reveal_top` effect.


def _chaos_warp() -> list[AbilitySpec]:
    """The owner of target permanent shuffles it into their library, then
    reveals the top card of their library. If it's a permanent card, they
    put it onto the battlefield."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("shuffle_target_into_library_reveal_top",
                        {"target_kind": "permanent"})],
            raw_text="Der Besitzer einer bleibenden Zielkarte mischt sie in seine "
                     "Bibliothek und deckt dann die oberste Karte seiner Bibliothek auf. "
                     "Falls es eine bleibende Karte ist, bringt er sie ins Spiel.",
        ),
    ]


register("Chaos Warp", _chaos_warp)


# ===========================================================================
# wave 58 — Thunderclap Drake (arm-a-spell-watcher + commander-cast-count
# copy) — PAR-60
# ===========================================================================
# `CopySpellEffect` gained ``count_selector`` (copy count read live from a
# `continuous.count_selector`); the delayed "when you next cast" hook is the
# existing `arm_spell_watcher`. The ``commander_casts_this_game`` selector
# was added in wave 41.


def _thunderclap_drake() -> list[AbilitySpec]:
    """Flying.  Instant and sorcery spells you cast cost {1} less (folds in
    from the parser).
    {2}{U}, Sacrifice this creature: When you next cast an instant or sorcery
    spell this turn, copy it for each time you've cast your commander from
    the command zone this game. You may choose new targets for the copies.

    Documented simplification (shared with `CopySpellEffect`): the copies
    keep the original's targets rather than opening a new-target pick."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("arm_spell_watcher", {
                "card_types": ["instant", "sorcery"],
                "then_specs": [{
                    "type": "copy_spell",
                    "params": {"count_selector": "commander_casts_this_game"},
                }],
            })],
            cost={"text": "{2}{U}, Sacrifice ~"},
            raw_text="{2}{U}, opfere diese Kreatur: Wenn du das naechste Mal in diesem Zug "
                     "einen Spontanzauber oder eine Hexerei wirkst, kopiere ihn fuer jedes "
                     "Mal, das du in diesem Spiel deinen Kommandeur aus der Kommandozone "
                     "gewirkt hast.",
        ),
    ]


register("Thunderclap Drake", _thunderclap_drake)


# ===========================================================================
# wave 59 — Priest of Forgotten Gods (pure composition of shipped primitives)
# ===========================================================================


def _priest_of_forgotten_gods() -> list[AbilitySpec]:
    """{T}, Sacrifice two other creatures: Any number of target players each
    lose 2 life and sacrifice a creature of their choice. You add {B}{B} and
    draw a card.

    Documented simplification: "any number of target players" is modeled as
    "each opponent" (the standard goldfish reading — `LoseLifeEffect` /
    `SacrificeEffect` both already take ``selector="each_opponent"``)."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}),
             EffectSpec("sacrifice", {"selector": "each_opponent", "what": "creature",
                                      "count": 1}),
             EffectSpec("add_mana", {"colors": ["B", "B"]}),
             EffectSpec("draw", {"count": 1})],
            cost={"text": "{T}", "sacrifice_count": [2, "creature"]},
            raw_text="{T}, opfere zwei andere Kreaturen: Jeder Gegner verliert 2 "
                     "Lebenspunkte und opfert eine Kreatur seiner Wahl. Du erzeugst "
                     "{B}{B} und ziehst eine Karte.",
        ),
    ]


register("Priest of Forgotten Gods", _priest_of_forgotten_gods)


# ===========================================================================
# wave 60 — Woe Strider ("escapes with counters") — PAR-60
# ===========================================================================
# New `GameObject.cast_via_escape` flag (stamped at the Escape cast site,
# like ``cast_via_flashback``) + a ``cast_via_escape`` condition key. The
# "enters with N +1/+1 counters" rider is modeled as an ETB add_counters
# gated on it (the same enters-with-counters simplification prior waves use).


def _woe_strider() -> list[AbilitySpec]:
    """Escape—{3}{B}{B}, Exile four other cards from your graveyard (folds in
    from the RULE 702 keyword catalogue).
    When this creature enters, create a 0/1 white Goat creature token.
    Sacrifice another creature: Scry 1.
    This creature escapes with two +1/+1 counters on it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 0, "toughness": 1, "colors": ["W"],
                "subtypes": ["Goat"], "keywords": [], "token_name": "Goat"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, erzeuge einen 0/1 weissen "
                     "Ziegen-Kreaturtoken.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 2},
                        condition={"cast_via_escape": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Diese Kreatur flieht mit zwei +1/+1-Marken auf ihr.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("scry", {"count": 1})],
            cost={"text": "Sacrifice another creature"},
            raw_text="Opfere eine andere Kreatur: Hellsicht 1.",
        ),
    ]


register("Woe Strider", _woe_strider)


# ===========================================================================
# wave 61 — Nexus Mentality (modal counter shuffle) — PAR-60
# ===========================================================================
# `MoveCountersEffect` gained ``move_all_kinds`` and `RemoveCountersEffect`
# gained ``draw_per_removed``.


def _nexus_mentality() -> list[AbilitySpec]:
    """Choose one. If you control a commander as you cast this spell, you may
    choose both instead.
    • Move all counters from target nonland permanent you control onto
      another target nonland permanent you control.
    • Remove all counters from target nonland permanent you control. Draw a
      card for each counter removed this way.

    Documented simplification: the "choose both" upside is modeled as an
    unconditional ``or_both`` (a Commander player virtually always controls
    or has cast their commander), rather than gating it on live commander
    control."""
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "or_both": True,
                "options": [
                    [EffectSpec("move_counters", {
                        "source_target_kind": "nonland_permanent_you_control",
                        "dest_target_kind": "nonland_permanent_you_control",
                        "move_all_kinds": True,
                    })],
                    [EffectSpec("remove_counters", {
                        "target_kind": "nonland_permanent_you_control",
                        "draw_per_removed": True,
                    })],
                ],
                "descriptions": [
                    "Bewege alle Marken von einer bleibenden Nichtland-Zielkarte, die du "
                    "kontrollierst, auf eine andere.",
                    "Entferne alle Marken von einer bleibenden Nichtland-Zielkarte, die du "
                    "kontrollierst. Ziehe eine Karte fuer jede so entfernte Marke.",
                ],
            },
            raw_text="Waehle eins. Falls du einen Kommandeur kontrollierst, waehle beides.",
        )
    ]


register("Nexus Mentality", _nexus_mentality)


# ===========================================================================
# wave 62 — Open the Way (reveal-until-N-lands ramp) — PAR-60
# ===========================================================================
# New `RulesEngine.reveal_until_matching` (the `card_query`-predicate
# sibling of `reveal_until_creature_type`) + a ``reveal_until`` effect.


def _open_the_way() -> list[AbilitySpec]:
    """X can't be greater than the number of players in the game.
    Reveal cards from the top of your library until you reveal X land cards.
    Put those land cards onto the battlefield tapped and the rest on the
    bottom of your library in a random order.

    Documented simplification: the "X can't be greater than the number of
    players" cap is not enforced."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_until", {
                "criteria": {"type": "land"}, "count": "x",
                "hit_destination": "battlefield", "tapped": True,
                "rest_destination": "library_bottom_random",
            })],
            raw_text="Decke Karten oben von deiner Bibliothek auf, bis du X Landkarten "
                     "aufdeckst. Bringe jene Landkarten getappt ins Spiel und lege den "
                     "Rest zufaellig geordnet unter deine Bibliothek.",
        ),
    ]


register("Open the Way", _open_the_way)


# ===========================================================================
# wave 63 — Gorma, the Gullet (count-scaled extra ETB counters) — PAR-60
# ===========================================================================
# `continuous.extra_etb_counters_for` / the ``extra_etb_counter`` static
# gained ``count_selector`` (live count instead of a fixed ``count``) and a
# ``nontoken`` filter.


def _gorma_the_gullet() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Whenever another creature you control dies, put a +1/+1 counter on Gorma
    (parser-claimed — re-added here).
    Nontoken creatures you control enter with an additional +1/+1 counter on
    them for each creature that died under your control this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "controller": "you", "other": True}},
            raw_text="Immer wenn eine andere Kreatur, die du kontrollierst, stirbt, lege "
                     "eine +1/+1-Marke auf Gorma.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("extra_etb_counter", {
                "kind": "+1/+1", "nontoken": True,
                "count_selector": "creatures_died_this_turn"})],
            raw_text="Nichttoken-Kreaturen, die du kontrollierst, kommen mit einer "
                     "zusaetzlichen +1/+1-Marke fuer jede Kreatur ins Spiel, die in "
                     "diesem Zug unter deiner Kontrolle gestorben ist.",
        ),
    ]


register("Gorma, the Gullet", _gorma_the_gullet)


# ===========================================================================
# wave 64 — Promise of Loyalty (each player keeps one creature) — PAR-60
# ===========================================================================
# Pure reuse: `SacrificeEffect(selector="each_player", count="all_but_one")`
# is exactly "each player puts a vow counter on a creature they control and
# sacrifices the rest" minus the mark.


def _promise_of_loyalty() -> list[AbilitySpec]:
    """Each player puts a vow counter on a creature they control and
    sacrifices the rest. Each of those creatures can't attack you or
    planeswalkers you control for as long as it has a vow counter on it.

    Documented simplification: modeled as "each player sacrifices all
    creatures but one" (`SacrificeEffect` ``count="all_but_one"``); the vow
    counter on the kept creature and its "can't attack you" rider are
    dropped (no hook to mark the specific creature left behind by an
    interactive keep-one)."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("sacrifice", {"selector": "each_player", "what": "creature",
                                      "count": "all_but_one"})],
            raw_text="Jeder Spieler legt eine Geluebde-Marke auf eine Kreatur, die er "
                     "kontrolliert, und opfert die restlichen.",
        ),
    ]


register("Promise of Loyalty", _promise_of_loyalty)


# ===========================================================================
# wave 65 — Songbirds' Blessing (Aura attack-trigger dig) — PAR-60
# ===========================================================================
# Pure reuse: `dig_until` on an ``attached_permanent`` ATTACKS trigger.


def _songbirds_blessing() -> list[AbilitySpec]:
    """Enchant creature (folds in).
    Whenever enchanted creature attacks, reveal cards from the top of your
    library until you reveal an Aura card. You may put that card onto the
    battlefield. If you don't, put it into your hand. Put the rest on the
    bottom of your library in a random order.

    Documented simplification: the "you may put that card onto the
    battlefield" option is dropped (an Aura put onto the battlefield by an
    effect needs an enchant-target choice not wired for this dig) — the
    revealed Aura always goes to hand instead."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": "Aura"}, "hit_destination": "hand",
                "rest_destination": "library_bottom_random"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Immer wenn die verzauberte Kreatur angreift, decke Karten oben von "
                     "deiner Bibliothek auf, bis du eine Aura-Karte aufdeckst. Nimm sie "
                     "auf deine Hand. Lege den Rest zufaellig geordnet unter deine "
                     "Bibliothek.",
        ),
    ]


register("Songbirds' Blessing", _songbirds_blessing)


# ===========================================================================
# wave 66 — Altered Ego (Clone + X counters) — PAR-60
# ===========================================================================
# `EnterAsCopyReplacement` gained ``extra_counters_from_x`` (the copy spell's
# own announced {X} as the extra-+1/+1 count, resolved when the copy is made).


def _altered_ego() -> list[AbilitySpec]:
    """This spell can't be countered (parser-claimed — re-added).
    You may have this creature enter as a copy of any creature on the
    battlefield, except it enters with X additional +1/+1 counters on it."""
    return [
        AbilitySpec("static", [EffectSpec("cant_be_countered", {})],
                    raw_text="Dieser Zauberspruch kann nicht neutralisiert werden."),
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "optional": True,
                "extra_counters_from_x": True,
            })],
            raw_text="Du darfst diese Kreatur als Kopie einer beliebigen Kreatur im Spiel "
                     "ins Spiel kommen lassen, doch kommt sie mit X zusaetzlichen "
                     "+1/+1-Marken ins Spiel.",
        ),
    ]


register("Altered Ego", _altered_ego)


# ===========================================================================
# wave 67 — Rootha, Mastering the Moment (greatest i/s mv this turn) — PAR-60
# ===========================================================================
# New `GameState.greatest_instant_sorcery_mv_this_turn` tracker (bumped in
# `_track_spell_cast`, reset in `begin_turn`) + the
# ``greatest_instant_sorcery_mv_this_turn`` count_selector + a
# ``cast_instant_or_sorcery_this_turn`` trigger intervening-if predicate.
# `CreateTokenEffect.pt_from_count_selector` already exists.


def _rootha_mastering_the_moment() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, if you've cast an instant or
    sorcery spell this turn, create an X/X blue and red Elemental creature
    token with flying and haste, where X is the greatest mana value among
    instant and sorcery spells you've cast this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "colors": ["U", "R"], "subtypes": ["Elemental"],
                "keywords": ["flying", "haste"], "token_name": "Elemental",
                "pt_from_count_selector": "greatest_instant_sorcery_mv_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you",
                     "cast_instant_or_sorcery_this_turn": True},
            raw_text="Zu Beginn des Kampfes in deinem Zug, falls du in diesem Zug einen "
                     "Spontanzauber oder eine Hexerei gewirkt hast, erzeuge einen X/X "
                     "blau-roten Elementar-Kreaturtoken mit Fliegend und Eile, wobei X "
                     "der hoechste Manawert unter den Spontanzaubern und Hexereien ist, "
                     "die du in diesem Zug gewirkt hast.",
        ),
    ]


register("Rootha, Mastering the Moment", _rootha_mastering_the_moment)


# ===========================================================================
# wave 68 — Spirit of Resilience (graveyard-exit +1/+1) — PAR-60
# ===========================================================================
# Pure reuse of the batched ``CARDS_LEFT_GRAVEYARD`` trigger (Quintorius,
# Advanced Reconstruction share it).


def _spirit_of_resilience() -> list[AbilitySpec]:
    """Whenever one or more cards leave your graveyard, put a +1/+1 counter
    on this creature, then you may have this creature become a copy of an
    artifact or creature card from among those cards until end of turn.

    Documented simplification: the "become a copy of a card from among those
    that left" rider is dropped (no primitive for BecomeCopy chosen from a
    transient set of just-departed graveyard cards) — the +1/+1 growth,
    the card's dominant effect, is kept."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you"},
            raw_text="Immer wenn eine oder mehr Karten deinen Friedhof verlassen, lege "
                     "eine +1/+1-Marke auf diese Kreatur.",
        ),
    ]


register("Spirit of Resilience", _spirit_of_resilience)


# ===========================================================================
# wave 69 — Stensian Sanguinist (attack -> grant deathtouch -> prepared) —
# PAR-60
# ===========================================================================
# Pure reuse: `PLAYER_ATTACKED` + `grant_until` (deathtouch) + a DAMAGE
# trigger firing `become_prepared` (waves 23/27 primitive).


def _stensian_sanguinist() -> list[AbilitySpec]:
    """Whenever you attack, target creature gains deathtouch until end of
    turn. Whenever that creature deals combat damage to a player this
    combat, this creature becomes prepared.

    Documented simplification: the "that creature" link between the two
    clauses is approximated as "a creature you control" (no linked-target
    delayed-DAMAGE-trigger primitive) — Stensian's own grant-then-connect
    intent is preserved."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "target_kind": "creature", "duration": "end_of_turn",
                "static": {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}},
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"}},
            raw_text="Immer wenn du angreifst, erhaelt eine Zielkreatur Todesberuehrung "
                     "bis zum Ende des Zuges.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_prepared", {})],
            trigger={"event": EventType.DAMAGE,
                     "condition": {"subject": "group", "controller": "you", "type": "creature"},
                     "filter": {"combat": True, "is_player": True}},
            raw_text="Immer wenn eine Kreatur, die du kontrollierst, einem Spieler "
                     "Kampfschaden zufuegt, wird diese Kreatur vorbereitet.",
        ),
    ]


register("Stensian Sanguinist", _stensian_sanguinist)
register("Stensian Sanguinist // Exsanguinate", _stensian_sanguinist)


# ===========================================================================
# wave 70 — Currency Converter ("exiled with this" cash-out) — PAR-60
# ===========================================================================
# Reuse of MEC-21's `GameObject.exiled_with_ids` accumulating tracker
# (Agatha's Soul Cauldron). The discard trigger now feeds it via
# `ExileTriggeringDiscardMayPlayThisTurnEffect`'s new ``track_exiled_with``
# (``play_permission`` off — Currency Converter grants no play window); the
# new `currency_converter_cash_out` effect reads it back.


def _currency_converter() -> list[AbilitySpec]:
    """Whenever you discard a card, you may exile that card from your
    graveyard.
    {2}, {T}: Draw a card, then discard a card.
    {T}: Put a card exiled with this artifact into its owner's graveyard. If
    it's a land card, create a Treasure token. If it's a nonland card,
    create a 2/2 black Rogue creature token.

    Documented simplification: the discard-exile "you may" is modeled as
    always taking it (same call the wave-42 Containment Construct entry
    makes) — banking a just-discarded card for the {T} payoff is what this
    card wants every time."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_triggering_discard_may_play_this_turn", {
                "play_permission": False, "track_exiled_with": True,
            })],
            trigger={"event": EventType.DISCARD_CARD, "condition": {"subject": "you"}},
            raw_text="Immer wenn du eine Karte abwirfst, darfst du jene Karte aus deinem "
                     "Friedhof exilieren.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1}), EffectSpec("discard", {"count": 1})],
            cost={"text": "{2}, {T}"},
            raw_text="{2}, {T}: Ziehe eine Karte und wirf dann eine Karte ab.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("currency_converter_cash_out", {})],
            cost={"text": "{T}"},
            raw_text="{T}: Lege eine mit diesem Artefakt verbannte Karte in den Friedhof "
                     "ihres Besitzers. Falls es eine Landkarte ist, erschaffe einen "
                     "Schatz-Spielstein. Falls es eine Nichtland-Karte ist, erschaffe "
                     "einen 2/2 schwarzen Schurken-Kreaturspielstein.",
        ),
    ]


register("Currency Converter", _currency_converter)


# ===========================================================================
# wave 71 — Fateful Tempest (council's dilemma) — PAR-60
# ===========================================================================
# Reuse of the PAR-29 vote subsystem (`VoteEffect` / `request_vote` with
# ``per_vote_specs``). New primitive: `mill_then_damage_each_opponent_by_mv`
# folds the "mill, then deal damage = total MV milled" pair into one atomic
# effect (a per-vote-scaled ``count``), avoiding a milled-MV context
# accumulator for the one card that wants it. The present branch reuses
# `impulsive_draw`, whose default window is exactly "until the end of your
# next turn".


def _fateful_tempest() -> list[AbilitySpec]:
    """Council's dilemma — Starting with you, each player votes for past or
    present. You mill a card for each past vote, then Fateful Tempest deals
    damage to each opponent equal to the total mana value of cards milled
    this way. Exile the top card of your library for each present vote.
    Until the end of your next turn, you may play the exiled cards."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("vote", {
                "options": ["past", "present"],
                "per_vote_specs": [
                    {"option": 0,
                     "effects": [{"type": "mill_then_damage_each_opponent_by_mv",
                                  "params": {"count": 1}}],
                     "scale": 1},
                    {"option": 1,
                     "effects": [{"type": "impulsive_draw", "params": {"count": 1}}],
                     "scale": 1},
                ],
            })],
            raw_text="Ratsdilemma - Beginnend mit dir, stimmt jeder Spieler fuer "
                     "Vergangenheit oder Gegenwart. Du legst fuer jede Stimme fuer "
                     "Vergangenheit eine Karte von deiner Bibliothek in deinen Friedhof, "
                     "dann fuegt ~ jedem Gegner so viel Schaden zu wie die "
                     "Gesamt-Manakosten der so hineingelegten Karten. Verbanne fuer jede "
                     "Stimme fuer Gegenwart die oberste Karte deiner Bibliothek. Bis zum "
                     "Ende deines naechsten Zuges darfst du die verbannten Karten spielen.",
        ),
    ]


register("Fateful Tempest", _fateful_tempest)


# ===========================================================================
# wave 72 — Augusta, Order Returned (each-player graveyard exile payoff) —
# PAR-60
# ===========================================================================
# New `each_player_exile_from_graveyard_then_counters` effect: one atomic
# effect over a shared "target attacking creature" (the
# `CounterUntapGrantKeywordEffect` "don't double-prompt" idiom). Documented
# simplification: each player's exile is auto-picked (oldest graveyard card)
# rather than an interactive per-player choice.


def _augusta_order_returned() -> list[AbilitySpec]:
    """Flying, vigilance (fold in from the RULE 702 catalogue).
    Whenever Augusta attacks, each player exiles a card from their
    graveyard. When one or more nonland cards are exiled this way, put that
    many +1/+1 counters on target attacking creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_player_exile_from_graveyard_then_counters", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Augusta angreift, verbannt jeder Spieler eine Karte aus "
                     "seinem Friedhof. Wenn auf diese Weise eine oder mehr "
                     "Nichtland-Karten verbannt werden, lege ebenso viele +1/+1-Marken "
                     "auf eine angreifende Zielkreatur.",
        ),
    ]


register("Augusta, Order Returned", _augusta_order_returned)


# ===========================================================================
# wave 73 — Combat Calligrapher (attacker-makes-the-token) — PAR-60
# ===========================================================================
# Reuse of wave 49's `cant_attack_defender` static (its ``subtype``
# attacker_filter was designed with this card in mind). New primitives: the
# `defender_is_opponent` binder trigger predicate ("a player attacks one of
# your opponents") + the `attacker_creates_attacking_token` effect (the
# *attacking* player, off the `PLAYER_ATTACKED` aggregate, makes and
# controls a token attacking that same defender).


def _combat_calligrapher() -> list[AbilitySpec]:
    """Flying (folds in from the RULE 702 catalogue).
    Inklings can't attack you or planeswalkers you control.
    Whenever a player attacks one of your opponents, that attacking player
    creates a tapped 2/1 white and black Inkling creature token with flying
    that's attacking that opponent."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_attack_defender", {
                "defender_scope": "player_or_planeswalker",
                "attacker_filter": {"subtype": "Inkling"},
            })],
            raw_text="Tintlinge koennen dich oder Planeswalker, die du kontrollierst, "
                     "nicht angreifen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attacker_creates_attacking_token", {
                "power": 2, "toughness": 1, "colors": ["W", "B"],
                "subtypes": ["Inkling"], "keywords": ["flying"], "token_name": "Inkling",
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "defender_is_opponent": True},
            raw_text="Immer wenn ein Spieler einen deiner Gegner angreift, erschafft "
                     "jener angreifende Spieler einen getappten 2/1 weiss-schwarzen "
                     "Tintling-Kreaturspielstein mit Fliegend, der jenen Gegner angreift.",
        ),
    ]


register("Combat Calligrapher", _combat_calligrapher)


# ===========================================================================
# wave 74 — Breena, the Demagogue (multi-opponent life-compare trigger) —
# PAR-60
# ===========================================================================
# Reuse of wave 73's `defender_is_opponent`. New primitives: the
# `defending_opponent_leads_an_opponent` binder intervening-if predicate
# ("that opponent has more life than another of your opponents") + a
# `selector="attacking_player"` mode on `DrawCardEffect` (draw for the
# `PLAYER_ATTACKED` aggregate's named attacker, not this controller).


def _breena_the_demagogue() -> list[AbilitySpec]:
    """Flying (folds in).
    Whenever a player attacks one of your opponents, if that opponent has
    more life than another of your opponents, that attacking player draws a
    card and you put two +1/+1 counters on a creature you control."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1, "selector": "attacking_player"}),
                EffectSpec("add_counters", {
                    "count": 2, "kind": "+1/+1", "target_kind": "creature_you_control",
                }),
            ],
            trigger={"event": EventType.PLAYER_ATTACKED, "defender_is_opponent": True,
                     "defending_opponent_leads_an_opponent": True},
            raw_text="Immer wenn ein Spieler einen deiner Gegner angreift und jener "
                     "Gegner mehr Lebenspunkte hat als ein anderer deiner Gegner, zieht "
                     "jener angreifende Spieler eine Karte und du legst zwei "
                     "+1/+1-Marken auf eine Kreatur, die du kontrollierst.",
        ),
    ]


register("Breena, the Demagogue", _breena_the_demagogue)


# ===========================================================================
# wave 75 — Hateful Eidolon (auras-attached snapshot on DIES) — PAR-60
# ===========================================================================
# New: `RulesEngine._move_to_graveyard` now snapshots
# ``attached_aura_controller_ids`` onto the DIES event (fired while the
# dying creature + its Auras are still on the battlefield, RULE 603.6a),
# read by the `draw_per_attached_aura_controller` effect. The trigger reuses
# wave 48's ``enchanted_by_your_aura`` group-condition key on a DIES subject
# (only fires when this controller had an Aura on the creature — exactly
# when the draw is nonzero).


def _hateful_eidolon() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Whenever an enchanted creature dies, draw a card for each Aura you
    controlled that was attached to it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw_per_attached_aura_controller", {})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "enchanted_by_your_aura": True}},
            raw_text="Immer wenn eine verzauberte Kreatur stirbt, ziehe eine Karte fuer "
                     "jede Aura, die du kontrolliert hast und die an sie angelegt war.",
        ),
    ]


register("Hateful Eidolon", _hateful_eidolon)


# ===========================================================================
# wave 76 — Gift of Immortality (Aura death-loop) — PAR-60
# ===========================================================================
# Reuse of Ghoulish Impetus's `create_delayed_trigger` ->
# `return_self_from_graveyard` shape for the "return this Aura attached at
# the next end step" clause. New `return_dying_subject_to_battlefield`
# effect for the "return that card under its owner's control" clause (off
# the DIES event's ``instance_id``).


def _gift_of_immortality() -> list[AbilitySpec]:
    """Enchant creature (folds in).
    When enchanted creature dies, return that card to the battlefield under
    its owner's control. Return this card to the battlefield attached to
    that creature at the beginning of the next end step."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gift_of_immortality_dies", {})],
            trigger={"event": EventType.DIES, "condition": {"subject": "attached_permanent"}},
            raw_text="Wenn die verzauberte Kreatur stirbt, bringe jene Karte unter der "
                     "Kontrolle ihres Besitzers auf das Schlachtfeld zurueck. Bringe diese "
                     "Karte zu Beginn des naechsten Endsegments an jene Kreatur angelegt "
                     "auf das Schlachtfeld zurueck.",
        ),
    ]


register("Gift of Immortality", _gift_of_immortality)


# ===========================================================================
# wave 77 — Scriv, the Obligator (Aura token with a quoted ability) — PAR-60
# ===========================================================================
# New `create_attached_aura_token` effect (create + RULE 115 attach); the
# token's quoted ability is authored under its token name ("Contract"),
# picked up by the `bind_from_catalogue` `create_token` already runs. The
# quoted ability reuses `LoseLifeEffect` ``selector="attached_permanent_
# controller"`` (Parasitic Impetus family).
# Documented simplification: the quoted ability's "+2/+0 if it's attacking
# one of your opponents. Otherwise, …" fork is dropped — the drain (the
# meaningful downside of an Aura forced onto an opponent's creature) is
# always applied.


def _contract_token() -> list[AbilitySpec]:
    """(Scriv's "Contract" Aura token.)
    Whenever enchanted creature attacks, its controller loses 2 life."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 2, "selector": "attached_permanent_controller"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Immer wenn die verzauberte Kreatur angreift, verliert ihr "
                     "Beherrscher 2 Lebenspunkte.",
        ),
    ]


register("Contract", _contract_token)


def _scriv_the_obligator() -> list[AbilitySpec]:
    """Flying, deathtouch (fold in).
    Whenever Scriv enters or attacks, create a white Aura enchantment token
    named Contract attached to target creature an opponent controls."""
    make = EffectSpec("create_attached_aura_token", {
        "token_name": "Contract", "colors": ["W"],
        "target_kind": "creature_you_dont_control",
    })
    return [
        AbilitySpec(
            "triggered", [make],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Immer wenn Scriv ins Spiel kommt, erschaffe einen weissen "
                     "Aura-Verzauberungsspielstein namens Vertrag, der an eine "
                     "Zielkreatur, die ein Gegner kontrolliert, angelegt ist.",
        ),
        AbilitySpec(
            "triggered", [make],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Scriv angreift, erschaffe einen weissen "
                     "Aura-Verzauberungsspielstein namens Vertrag, der an eine "
                     "Zielkreatur, die ein Gegner kontrolliert, angelegt ist.",
        ),
    ]


register("Scriv, the Obligator", _scriv_the_obligator)


# ===========================================================================
# wave 78 — Shadrix Silverquill (modal choose-two, each targets a player) —
# PAR-60
# ===========================================================================
# Reuse of the modal ``modes={"choose": 2, "options": [...]}`` triggered-
# ability shape (Titan of Industry) + `target_player_draw_lose_life`. New
# small `target_player_counter_each_creature` effect for mode 3.
# Documented simplification: "Each mode must target a different player" is
# dropped (the engine has no cross-mode target-distinctness constraint) —
# the modal choice + per-mode player target is preserved.


def _shadrix_silverquill() -> list[AbilitySpec]:
    """Flying, double strike (fold in).
    At the beginning of combat on your turn, you may choose two. Each mode
    must target a different player.
    • Target player creates a 2/1 white and black Inkling token with flying.
    • Target player draws a card and loses 1 life.
    • Target player puts a +1/+1 counter on each creature they control."""
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
            modes={"choose": 2, "may": True, "options": [
                [EffectSpec("create_token", {
                    "token_name": "Inkling", "power": 2, "toughness": 1,
                    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
                    "target_kind": "player", "creators": "target",
                })],
                [EffectSpec("target_player_draw_lose_life", {"draw_count": 1, "life_loss": 1})],
                [EffectSpec("target_player_counter_each_creature", {"amount": 1, "kind": "+1/+1"})],
            ]},
            raw_text="Zu Beginn des Kampfes in deinem Zug darfst du zwei Modi waehlen. "
                     "Jeder Modus muss auf einen anderen Spieler abzielen. "
                     "- Ein Zielspieler erschafft einen 2/1 weiss-schwarzen "
                     "Tintling-Spielstein mit Fliegend. "
                     "- Ein Zielspieler zieht eine Karte und verliert 1 Lebenspunkt. "
                     "- Ein Zielspieler legt eine +1/+1-Marke auf jede Kreatur, die er "
                     "kontrolliert.",
        ),
    ]


register("Shadrix Silverquill", _shadrix_silverquill)


# ===========================================================================
# wave 79 — Zimone's Hypothesis (odd/even mass bounce) — PAR-60
# ===========================================================================
# New `return_creatures_by_power_parity` effect; the "choose odd or even" is
# a `modes` choice of the two fixed-parity variants. Documented
# simplification: the leading "You may put a +1/+1 counter on a creature"
# rider (a parity nudge) is dropped — the parity mass bounce is the payoff.


def _zimones_hypothesis() -> list[AbilitySpec]:
    """You may put a +1/+1 counter on a creature. Then choose odd or even.
    Return each creature with power of the chosen quality to its owner's
    hand. (Zero is even.)"""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={"choose": 1, "options": [
                [EffectSpec("return_creatures_by_power_parity", {"parity": "odd"})],
                [EffectSpec("return_creatures_by_power_parity", {"parity": "even"})],
            ], "descriptions": ["ungerade", "gerade"]},
            raw_text="Waehle ungerade oder gerade. Bringe jede Kreatur mit Staerke der "
                     "gewaehlten Beschaffenheit auf die Hand ihres Besitzers zurueck. "
                     "(Null ist gerade.)",
        ),
    ]


register("Zimone's Hypothesis", _zimones_hypothesis)


# ===========================================================================
# wave 80 — Zimone, All-Questioning (prime land count) — PAR-60
# ===========================================================================
# New `GameState.lands_entered_this_turn` tracker (creature-sibling) + the
# self-gating `zimone_all_questioning_end_step` effect (prime check inline).


def _zimone_all_questioning() -> list[AbilitySpec]:
    """At the beginning of your end step, if a land entered the battlefield
    under your control this turn and you control a prime number of lands,
    create Primo, the Indivisible, a legendary 0/0 green and blue Fractal
    creature token, then put that many +1/+1 counters on it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("zimone_all_questioning_end_step", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments, falls in diesem Zug ein Land unter "
                     "deiner Kontrolle ins Spiel gekommen ist und du eine Primzahl an "
                     "Ländern kontrollierst, erschaffe Primo die Unteilbare, einen "
                     "legendären 0/0 grün-blauen Fraktal-Kreaturspielstein, und lege "
                     "dann ebenso viele +1/+1-Marken auf ihn.",
        ),
    ]


register("Zimone, All-Questioning", _zimone_all_questioning)


# ===========================================================================
# wave 81 — Forgotten Ancient (distribute counters) — PAR-60
# ===========================================================================
# New `move_all_plus_one_counters_from_self` effect (documented
# simplification: all counters onto one up-to-one target rather than RULE
# 122's per-counter distribution across several). The cast trigger re-adds
# the parser-claimed clause (a registered card turns parse_oracle off).


def _forgotten_ancient() -> list[AbilitySpec]:
    """Whenever a player casts a spell, you may put a +1/+1 counter on this
    creature.
    At the beginning of your upkeep, you may move any number of +1/+1
    counters from this creature onto other creatures."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
            raw_text="Immer wenn ein Spieler einen Zauberspruch wirkt, darfst du eine "
                     "+1/+1-Marke auf diese Kreatur legen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("move_all_plus_one_counters_from_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments darfst du beliebig viele "
                     "+1/+1-Marken von dieser Kreatur auf andere Kreaturen verschieben.",
        ),
    ]


register("Forgotten Ancient", _forgotten_ancient)


# ===========================================================================
# wave 82 — Animist's Awakening (reveal top X, take all lands) — PAR-60
# ===========================================================================
# New `animists_awakening` effect (a *fixed*-X reveal that takes every land,
# distinct from wave-62's `reveal_until` which reveals *until* N hits). Spell
# mastery (RULE 702.101a) untap folded in.


def _animists_awakening() -> list[AbilitySpec]:
    """Reveal the top X cards of your library. Put all land cards from among
    them onto the battlefield tapped and the rest on the bottom of your
    library in a random order.
    Spell mastery — If there are two or more instant and/or sorcery cards in
    your graveyard, untap those lands."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("animists_awakening", {"count": "x"})],
            raw_text="Decke die obersten X Karten deiner Bibliothek auf. Bringe alle "
                     "Landkarten davon getappt ins Spiel und lege den Rest in zufaelliger "
                     "Reihenfolge unter deine Bibliothek. Zaubermeisterschaft - Falls "
                     "sich zwei oder mehr Spontanzauber- und/oder Hexereikarten in deinem "
                     "Friedhof befinden, enttappe jene Laender.",
        ),
    ]


register("Animist's Awakening", _animists_awakening)


# ===========================================================================
# wave 83 — Expressive Iteration (look 3: hand / bottom / exile-play) — PAR-60
# ===========================================================================
# New `expressive_iteration` effect: two chained `request_choose_objects`
# picks (hand card, then which of the last two to exile with a this-turn
# play window; the other goes to the bottom).


def _expressive_iteration() -> list[AbilitySpec]:
    """Look at the top three cards of your library. Put one of them into
    your hand, put one of them on the bottom of your library, and exile one
    of them. You may play the exiled card this turn."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("expressive_iteration", {})],
            raw_text="Sieh dir die obersten drei Karten deiner Bibliothek an. Nimm eine "
                     "davon auf deine Hand, lege eine davon unter deine Bibliothek und "
                     "verbanne eine davon. Du darfst die verbannte Karte in diesem Zug "
                     "spielen.",
        ),
    ]


register("Expressive Iteration", _expressive_iteration)


# ===========================================================================
# wave 84 — Tragic Arrogance (mass keep-one-of-each) — PAR-60
# ===========================================================================
# New `tragic_arrogance` effect. Documented simplification: the caster's
# per-(player, type) choice is auto-resolved — keep the highest-MV of each
# type among the caster's own permanents, the lowest-MV among opponents'.


def _tragic_arrogance() -> list[AbilitySpec]:
    """For each player, you choose from among the permanents that player
    controls an artifact, a creature, an enchantment, and a planeswalker.
    Then each player sacrifices all other nonland permanents they control."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("tragic_arrogance", {})],
            raw_text="Fuer jeden Spieler waehlst du aus den bleibenden Karten, die jener "
                     "Spieler kontrolliert, ein Artefakt, eine Kreatur, eine "
                     "Verzauberung und einen Planeswalker aus. Dann opfert jeder Spieler "
                     "alle anderen bleibenden Nichtland-Karten, die er kontrolliert.",
        ),
    ]


register("Tragic Arrogance", _tragic_arrogance)


# ===========================================================================
# wave 85 — Oversimplify (per-player payoff from a mass exile) — PAR-60
# ===========================================================================
# New `oversimplify` effect: snapshot each player's total creature power,
# exile all creatures, then one Fractal token per player with that many
# +1/+1 counters.


def _oversimplify() -> list[AbilitySpec]:
    """Exile all creatures. Each player creates a 0/0 green and blue Fractal
    creature token and puts a number of +1/+1 counters on it equal to the
    total power of creatures they controlled that were exiled this way."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("oversimplify", {})],
            raw_text="Verbanne alle Kreaturen. Jeder Spieler erschafft einen 0/0 "
                     "gruen-blauen Fraktal-Kreaturspielstein und legt so viele "
                     "+1/+1-Marken darauf wie die Gesamtstaerke der Kreaturen, die er "
                     "kontrolliert hat und die auf diese Weise verbannt wurden.",
        ),
    ]


register("Oversimplify", _oversimplify)


# ===========================================================================
# wave 86 — Redoubled Stormsinger (copy each just-entered token) — PAR-60
# ===========================================================================
# New `redoubled_stormsinger_copies` effect + the existing
# `create_delayed_trigger` ``capture="created_objects"`` + `sacrifice_
# specific` idiom for the "sacrifice those tokens at the next end step" tail.


def _redoubled_stormsinger() -> list[AbilitySpec]:
    """First strike (folds in).
    Whenever this creature attacks, for each creature token you control that
    entered this turn, create a tapped and attacking token that's a copy of
    that token. At the beginning of the next end step, sacrifice those
    tokens."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("redoubled_stormsinger_copies", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Redoubled Stormsinger: Spielsteine opfern",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn diese Kreatur angreift, erschaffe fuer jeden "
                     "Kreatur-Spielstein, den du kontrollierst und der in diesem Zug ins "
                     "Spiel gekommen ist, einen getappten und angreifenden Spielstein, "
                     "der eine Kopie jenes Spielsteins ist. Zu Beginn des naechsten "
                     "Endsegments opfere jene Spielsteine.",
        ),
    ]


register("Redoubled Stormsinger", _redoubled_stormsinger)


# ===========================================================================
# wave 87 — Surge to Victory (exile i/s from gy + team anthem) — PAR-60
# ===========================================================================
# New `surge_to_victory` effect. Documented simplification: the "whenever a
# creature deals combat damage, copy the exiled card and cast it free"
# rider is dropped (no per-firing copy-a-remembered-exiled-card primitive).


def _surge_to_victory() -> list[AbilitySpec]:
    """Exile target instant or sorcery card from your graveyard. Creatures
    you control get +X/+0 until end of turn, where X is that card's mana
    value. Whenever a creature you control deals combat damage to a player
    this turn, copy the exiled card. You may cast the copy without paying
    its mana cost."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("surge_to_victory", {})],
            raw_text="Verbanne eine Spontanzauber- oder Hexereikarte als Ziel aus deinem "
                     "Friedhof. Kreaturen, die du kontrollierst, erhalten +X/+0 bis zum "
                     "Ende des Zuges, wobei X die Manakosten jener Karte sind.",
        ),
    ]


register("Surge to Victory", _surge_to_victory)


# ===========================================================================
# wave 88 — Brudiclad, Telchor Engineer (each other token becomes a copy) —
# PAR-60
# ===========================================================================
# New `brudiclad_combat` + `brudiclad_become_copies` effects (reuse
# `RulesEngine.become_copy`, RULE 706.2). The "creature tokens you control
# have haste" static folds in from the parser (re-added here).


def _brudiclad_telchor_engineer() -> list[AbilitySpec]:
    """Creature tokens you control have haste.
    At the beginning of combat on your turn, create a 2/1 blue Phyrexian Myr
    artifact creature token. Then you may choose a token you control. If you
    do, each other token you control becomes a copy of that token."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["haste"], "affects": "creatures_you_control", "tokens": True,
            })],
            raw_text="Kreatur-Spielsteine, die du kontrollierst, haben Eile.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("brudiclad_combat", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn des Kampfes in deinem Zug erschaffe einen 2/1 blauen "
                     "Phyrexianischen Myr-Artefaktkreaturspielstein. Dann darfst du einen "
                     "Spielstein waehlen, den du kontrollierst. Falls du dies tust, wird "
                     "jeder andere Spielstein, den du kontrollierst, zu einer Kopie jenes "
                     "Spielsteins.",
        ),
    ]


register("Brudiclad, Telchor Engineer", _brudiclad_telchor_engineer)


# ===========================================================================
# wave 89 — Ao, the Dawn Sky (modal dies: budget dig / mass counters) — PAR-60
# ===========================================================================
# New `budget_dig_onto_battlefield` effect (greedy cheapest-first
# auto-selection under a total-MV budget). Mode 2 reuses `add_counters`
# with a mass selector.


def _ao_the_dawn_sky() -> list[AbilitySpec]:
    """Flying, vigilance (fold in).
    When Ao dies, choose one —
    • Look at the top seven cards of your library. Put any number of nonland
      permanent cards with total mana value 4 or less from among them onto
      the battlefield. Put the rest on the bottom of your library in a
      random order.
    • Put two +1/+1 counters on each permanent you control that's a creature
      or Vehicle.

    Documented simplification: mode 2's "or Vehicle" is dropped (each
    creature you control)."""
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            modes={"choose": 1, "options": [
                [EffectSpec("budget_dig_onto_battlefield", {"look": 7, "budget": 4})],
                [EffectSpec("add_counters", {
                    "amount": 2, "kind": "+1/+1", "selector": "creatures_you_control",
                })],
            ], "descriptions": ["graben", "marken"]},
            raw_text="Wenn Ao stirbt, waehle eine Moeglichkeit - Sieh dir die obersten "
                     "sieben Karten deiner Bibliothek an. Bringe beliebig viele "
                     "Nichtland-Karten bleibender Karten mit Gesamt-Manakosten von "
                     "hoechstens 4 davon ins Spiel. Lege den Rest in zufaelliger "
                     "Reihenfolge unter deine Bibliothek. - Lege zwei +1/+1-Marken auf "
                     "jede bleibende Karte, die du kontrollierst und die eine Kreatur "
                     "oder ein Fahrzeug ist.",
        ),
    ]


register("Ao, the Dawn Sky", _ao_the_dawn_sky)


# ===========================================================================
# wave 90 — Hofri Ghostforge (dies -> exile -> Spirit copy token) — PAR-60
# ===========================================================================
# New `hofri_ghostforge_dies` effect (reuse `copy_permanent` with
# ``add_subtypes=["Spirit"]``). The Spirit anthem static folds in from the
# parser (re-added). Documented simplification: the copy token's own "when
# this token leaves the battlefield, return the exiled card" rider dropped.


def _hofri_ghostforge() -> list[AbilitySpec]:
    """Spirits you control get +1/+1 and have trample and haste.
    Whenever another nontoken creature you control dies, exile it. If you
    do, create a token that's a copy of that creature, except it's a Spirit
    in addition to its other types and it has "When this token leaves the
    battlefield, return the exiled card to its owner's graveyard."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "power": 1, "toughness": 1, "affects": "creatures_you_control",
                    "subtype": "Spirit",
                }),
                EffectSpec("grant_keyword", {
                    "keywords": ["trample", "haste"], "affects": "creatures_you_control",
                    "subtype": "Spirit",
                }),
            ],
            raw_text="Geister, die du kontrollierst, erhalten +1/+1 und haben Trampelschaden "
                     "und Eile.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("hofri_ghostforge_dies", {})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "controller": "you",
                                   "type": "creature", "nontoken": True, "other": True}},
            raw_text="Immer wenn eine andere Nichtspielstein-Kreatur, die du "
                     "kontrollierst, stirbt, verbanne sie. Falls du dies tust, erschaffe "
                     "einen Spielstein, der eine Kopie jener Kreatur ist, ausser dass er "
                     "zusaetzlich zu seinen anderen Typen ein Geist ist.",
        ),
    ]


register("Hofri Ghostforge", _hofri_ghostforge)


# ===========================================================================
# wave 91 — Serra Paragon (graveyard recursion once/turn) — PAR-60
# ===========================================================================
# Reuse of `graveyard_cast_permission` (Lurrus-shaped: MV cap + once/turn +
# its own ``exile_if_would_be_put_into_graveyard`` rider — exactly Serra's
# "it gains 'when put into a graveyard from the battlefield, exile it'").
# Documented simplification: the "play a land from your graveyard"
# alternative and the "you gain 2 life" tail are dropped.


def _serra_paragon() -> list[AbilitySpec]:
    """Flying (folds in).
    Once during each of your turns, you may play a land from your graveyard
    or cast a permanent spell with mana value 3 or less from your graveyard.
    If you do, it gains "When this permanent is put into a graveyard from
    the battlefield, exile it and you gain 2 life."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "max_mana_value": 3, "permanent_only": True, "once_per_turn": True,
                "exile_if_would_be_put_into_graveyard": True,
            })],
            raw_text="Einmal waehrend jedes deiner Zuege darfst du eine bleibende Karte mit "
                     "Manakosten von hoechstens 3 aus deinem Friedhof wirken. Falls du "
                     "dies tust, wird sie exiliert, wenn sie von hier aus auf einen "
                     "Friedhof gelegt wuerde.",
        ),
    ]


register("Serra Paragon", _serra_paragon)


# ===========================================================================
# wave 92 — Pearl-Ear, Imperial Advisor (affinity for Auras + aura-cast
# draw) — PAR-60
# ===========================================================================
# Reuse of `cost_reduction` (``spell_type`` + ``per`` count_selector) for
# "affinity for Auras" and Kor Spiritdancer's own "whenever you cast an Aura
# spell" group trigger for the draw. Documented simplification: the draw's
# "that targets a modified permanent you control" narrowing is dropped.


def _pearl_ear_imperial_advisor() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Enchantment spells you cast have affinity for Auras. (They cost {1} less
    to cast for each Aura you control.)
    Whenever you cast an Aura spell that targets a modified permanent you
    control, draw a card."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 1,
                "spell_type": "enchantment", "per": "auras_you_control",
            })],
            raw_text="Verzauberungszauber, die du wirkst, haben Affinitaet zu Auras. "
                     "(Sie kosten {1} weniger fuer jede Aura, die du kontrollierst.)",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SPELL_CAST,
                     "condition": {"subject": "group", "subtypes": ["aura"],
                                   "controller": "you"}},
            raw_text="Immer wenn du einen Aura-Zauberspruch wirkst, der eine modifizierte "
                     "bleibende Karte als Ziel hat, die du kontrollierst, ziehe eine Karte.",
        ),
    ]


register("Pearl-Ear, Imperial Advisor", _pearl_ear_imperial_advisor)


# ===========================================================================
# wave 93 — Rousing Refrain (ritual off opponent's hand size) — PAR-60
# ===========================================================================
# Reuse of `AddManaEffect` (``target_kind="opponent"`` +
# ``amount_from_target_hand_size``). Suspend folds in from the RULE 702
# keyword catalogue. Documented simplification: "Until end of turn, you
# don't lose this mana as steps and phases end" (an acknowledged engine
# gap) and "Exile Rousing Refrain with three time counters on it" are
# dropped.


def _rousing_refrain() -> list[AbilitySpec]:
    """Add {R} for each card in target opponent's hand. Until end of turn,
    you don't lose this mana as steps and phases end. Exile Rousing Refrain
    with three time counters on it.
    Suspend 3—{1}{R}"""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "color": "R", "target_kind": "opponent",
                "amount_from_target_hand_size": True,
            })],
            raw_text="Erzeuge {R} fuer jede Karte in der Hand eines Zielgegners.",
        ),
    ]


register("Rousing Refrain", _rousing_refrain)


# ===========================================================================
# wave 94 — Dance with Calamity (MV-budget exile loop) — PAR-60
# ===========================================================================
# New `dance_with_calamity` effect. Documented simplification: the "as many
# times as you choose" gamble is auto-resolved greedily (exile from the top
# while running total MV stays <= 13), and every non-land card exiled gets a
# this-turn free-cast window.


def _dance_with_calamity() -> list[AbilitySpec]:
    """Shuffle your library. As many times as you choose, you may exile the
    top card of your library. If the total mana value of the cards exiled
    this way is 13 or less, you may cast any number of spells from among
    those cards without paying their mana costs."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("dance_with_calamity", {})],
            raw_text="Mische deine Bibliothek. Beliebig oft darfst du die oberste Karte "
                     "deiner Bibliothek verbannen. Falls die Gesamt-Manakosten der so "
                     "verbannten Karten hoechstens 13 betragen, darfst du beliebig viele "
                     "Zauber daraus wirken, ohne ihre Manakosten zu bezahlen.",
        ),
    ]


register("Dance with Calamity", _dance_with_calamity)


# ===========================================================================
# wave 95 — Abstract Performance (two piles, opponent splits) — PAR-60
# ===========================================================================
# New `abstract_performance` effect. Documented simplification: "an opponent
# chooses one of those piles" is auto-resolved (the higher-total-MV pile
# goes to your graveyard); from the kept pile the highest-MV non-land card
# gets a this-turn free-cast window, the rest go to your hand.


def _abstract_performance() -> list[AbilitySpec]:
    """Exile the top four cards of your library in a face-down pile, then
    exile the top four cards of your library in a face-up pile. An opponent
    chooses one of those piles. Put that pile into your graveyard. Look at
    the cards in the other pile. You may cast a spell from among them
    without paying its mana cost. Put the rest into your hand."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("abstract_performance", {})],
            raw_text="Verbanne die obersten vier Karten deiner Bibliothek verdeckt als "
                     "Stapel, dann verbanne die obersten vier Karten deiner Bibliothek "
                     "offen als Stapel. Ein Gegner waehlt einen jener Stapel. Lege jenen "
                     "Stapel in deinen Friedhof. Sieh dir die Karten im anderen Stapel "
                     "an. Du darfst einen Zauber daraus wirken, ohne seine Manakosten zu "
                     "bezahlen. Nimm die uebrigen auf deine Hand.",
        ),
    ]


register("Abstract Performance", _abstract_performance)


# ===========================================================================
# wave 96 — Plargg and Nassari (each-player dig, opp denies, cast 2 free) —
# PAR-60
# ===========================================================================
# New `plargg_and_nassari` effect. Documented simplification: "an opponent
# chooses a nonland card exiled this way" is auto-resolved (highest-MV
# nonland denied); up to two of the remaining nonland cards get a this-turn
# free-cast window.


def _plargg_and_nassari() -> list[AbilitySpec]:
    """At the beginning of your upkeep, each player exiles cards from the top
    of their library until they exile a nonland card. An opponent chooses a
    nonland card exiled this way. You may cast up to two spells from among
    the other cards exiled this way without paying their mana costs."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("plargg_and_nassari", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments verbannt jeder Spieler Karten "
                     "von seiner Bibliothek, bis er eine Nichtland-Karte verbannt. Ein "
                     "Gegner waehlt eine so verbannte Nichtland-Karte. Du darfst bis zu "
                     "zwei Zauber aus den anderen so verbannten Karten wirken, ohne ihre "
                     "Manakosten zu bezahlen.",
        ),
    ]


register("Plargg and Nassari", _plargg_and_nassari)


# ===========================================================================
# wave 97 — Inkshield (prevent combat damage to you -> tokenize) — PAR-60
# ===========================================================================
# Reuses `RulesEngine.prevent_damage_to_player`'s existing ``rider`` hook
# (`apply_prevent_rider`'s ``create_tokens_scaled`` kind — Bone Mask /
# New Way Forward family) plus a new ``combat_only`` flag on the "…to you"
# shield. No new effect class.


def _inkshield() -> list[AbilitySpec]:
    """Prevent all combat damage that would be dealt to you this turn. For
    each 1 damage prevented this way, create a 2/1 white and black Inkling
    creature token with flying."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("prevent_damage_shield", {
                "amount": "all",
                "combat_only": True,
                "rider": {
                    "kind": "create_tokens_scaled",
                    "recipient": "you",
                    "token": {
                        "token_name": "Inkling", "power": 2, "toughness": 1,
                        "colors": ["W", "B"], "subtypes": ["Inkling"],
                        "keywords": ["flying"],
                    },
                },
            })],
            raw_text="Verhindere den gesamten Kampfschaden, der dir in diesem Zug "
                     "zugefuegt wuerde. Fuer jeden 1 Schadenspunkt, der auf diese "
                     "Weise verhindert wird, erzeuge einen 2/1 weiss-schwarzen "
                     "Tintling-Spielstein mit Fliegend.",
        ),
    ]


register("Inkshield", _inkshield)


# ===========================================================================
# wave 98 — Plumb the Forbidden (sacrifice one or more -> scaled draw/lose)
# ===========================================================================
# New `sacrifice_any_number_draw_lose_scaled` effect — the Eventide's Shadow
# sacrifice-choose + graveyard-delta-tail idiom. Documented simplification:
# "copy this spell for each creature sacrificed" is modeled as its net
# effect (one extra draw + 1 life loss per creature), not real stack copies.


def _plumb_the_forbidden() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice one or
    more creatures. When you do, copy this spell for each creature
    sacrificed this way. You draw a card and lose 1 life."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("sacrifice_any_number_draw_lose_scaled", {})],
            raw_text="Als zusaetzliche Kosten, um diesen Zauberspruch zu wirken, darfst "
                     "du eine oder mehr Kreaturen opfern. Wenn du dies tust, kopiere "
                     "diesen Zauberspruch fuer jede so geopferte Kreatur. Du ziehst eine "
                     "Karte und verlierst 1 Lebenspunkt.",
        ),
    ]


register("Plumb the Forbidden", _plumb_the_forbidden)


# ===========================================================================
# wave 99 — Immoral Bargain (sacrifice X creatures -> destroy X) — PAR-60
# ===========================================================================
# New `immoral_bargain` effect + a new ``destroy`` action for
# `request_choose_objects` (the destroy sibling of ``sacrifice``). X is
# defined by the additional-cost sacrifice, resolved at resolution.


def _immoral_bargain() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice X creatures.
    Destroy X target nonland permanents."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("immoral_bargain", {})],
            raw_text="Als zusaetzliche Kosten, um diesen Zauberspruch zu wirken, opfere "
                     "X Kreaturen. Zerstoere X Ziel-Nichtland-bleibende-Karten.",
        ),
    ]


register("Immoral Bargain", _immoral_bargain)


# ===========================================================================
# wave 100 — Primo, the Unbounded (twice-X entry counters + base-power-0
# combat-damage Fractal) — PAR-60
# ===========================================================================
# Clause 1 reuses `AddCountersEffect.x_multiplier` (Banquet Guests). Clause
# 2 reuses `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` with a new
# ``contributor_base_power_zero`` predicate + a `base0_combat_damage_fractal`
# effect. Trample folds in from the RULE 702 keyword catalogue.


def _primo_the_unbounded() -> list[AbilitySpec]:
    """Trample
    Primo enters with twice X +1/+1 counters on it.
    Whenever one or more creatures you control with base power 0 deal combat
    damage to a player, create a 0/0 green and blue Fractal creature token.
    Put a number of +1/+1 counters on it equal to the damage dealt."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"x_multiplier": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Primo kommt mit doppelt X +1/+1-Marken ins Spiel.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("base0_combat_damage_fractal", {})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
                "contributor_base_power_zero": True,
            },
            raw_text="Immer wenn ein oder mehr Kreaturen, die du kontrollierst und "
                     "deren Grundstaerke 0 ist, einem Spieler Kampfschaden zufuegen, "
                     "erzeuge einen 0/0 gruen-blauen Fraktal-Spielstein. Lege so viele "
                     "+1/+1-Marken darauf, wie Schaden zugefuegt wurde.",
        ),
    ]


register("Primo, the Unbounded", _primo_the_unbounded)


# ===========================================================================
# wave 101 — Unbound Flourishing (double X on permanent spell + copy {X}
# instant/sorcery) — PAR-60
# ===========================================================================
# Clause 2 is Owlin Spiralmancer's shape (SPELL_CAST + ``spell_has_x`` +
# `copy_spell` from the trigger event). Clause 1 is a new `double_cast_x`
# effect that doubles the announced X on the stack item.


def _unbound_flourishing() -> list[AbilitySpec]:
    """Whenever you cast a permanent spell with a mana cost that contains
    {X}, double the value of X.
    Whenever you cast an instant or sorcery spell or activate an ability, if
    that spell's mana cost or that ability's activation cost contains {X},
    copy that spell or ability. You may choose new targets for the copy.

    Documented simplification: clause 2's "or activate an ability" half is
    dropped (only spells are copied); clause 1 fires for every {X} spell you
    cast and no-ops unless it is a permanent spell."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("double_cast_x", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
            },
            raw_text="Immer wenn du einen Zauberspruch einer bleibenden Karte mit {X} "
                     "in seinen Manakosten wirkst, verdopple den Wert von X.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_has_x": True,
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Immer wenn du einen Hexerei- oder Spontanzauber wirkst, dessen "
                     "Manakosten {X} enthalten, kopiere jenen Zauberspruch. Du darfst "
                     "neue Ziele fuer die Kopie bestimmen.",
        ),
    ]


register("Unbound Flourishing", _unbound_flourishing)


# ===========================================================================
# wave 102 — Laelia, the Blade Reforged (exile-from-library/graveyard
# counter trigger) — PAR-60
# ===========================================================================
# Attack trigger reuses `impulsive_draw` (same_turn_only). The counter
# trigger is a new binder key ``exiled_from_your_library_or_graveyard`` on
# `EventType.EXILE` (which now carries ``from_zone``). Haste folds in from
# the RULE 702 keyword catalogue.


def _laelia_the_blade_reforged() -> list[AbilitySpec]:
    """Haste
    Whenever Laelia attacks, exile the top card of your library. You may
    play that card this turn.
    Whenever one or more cards are put into exile from your library and/or
    your graveyard, put a +1/+1 counter on Laelia."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {"count": 1, "same_turn_only": True})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Laelia angreift, verbanne die oberste Karte deiner "
                     "Bibliothek. Du darfst jene Karte in diesem Zug spielen.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": EventType.EXILE,
                "exiled_from_your_library_or_graveyard": True,
            },
            raw_text="Immer wenn eine oder mehr Karten aus deiner Bibliothek und/oder "
                     "deinem Friedhof ins Exil geschickt werden, lege eine "
                     "+1/+1-Marke auf Laelia.",
        ),
    ]


register("Laelia, the Blade Reforged", _laelia_the_blade_reforged)


# ===========================================================================
# wave 103 — Mirrorwing Dragon (spell-copy per other creature, retargeted)
# ===========================================================================
# New `mirrorwing_copy` effect — `RulesEngine.copy_spell` called once per
# other creature the caster controls, each with its own ``new_targets``.
# Flying folds in from the RULE 702 keyword catalogue.


def _mirrorwing_dragon() -> list[AbilitySpec]:
    """Flying
    Whenever a player casts an instant or sorcery spell that targets only
    this creature, that player copies that spell for each other creature
    they control that the spell could target. Each copy targets a different
    one of those creatures."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mirrorwing_copy", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group"},
                "spell_card_types": ["instant", "sorcery"],
            },
            raw_text="Immer wenn ein Spieler einen Spontan- oder Hexereizauber wirkt, "
                     "der nur diese Kreatur als Ziel hat, kopiert jener Spieler jenen "
                     "Zauberspruch fuer jede andere Kreatur, die er kontrolliert und "
                     "die der Zauberspruch als Ziel haben koennte. Jede Kopie hat eine "
                     "andere jener Kreaturen zum Ziel.",
        ),
    ]


register("Mirrorwing Dragon", _mirrorwing_dragon)


# ===========================================================================
# wave 104 — Nils, Discipline Enforcer (per-player end-step counter +
# per-attacker-variable counter attack tax) — PAR-60
# ===========================================================================
# Clause 1 is a new `nils_end_step_counters` effect (auto-picks each
# player's highest-power creature — documented simplification of "up to one
# target creature that player controls"). Clause 2 extends the existing
# `attack_tax` static with ``attacker_filter`` + ``amount_per_attacker_
# counter`` (each counter-bearing attacker pays its own counter count).


def _nils_discipline_enforcer() -> list[AbilitySpec]:
    """At the beginning of your end step, for each player, put a +1/+1
    counter on up to one target creature that player controls.
    Each creature with one or more counters on it can't attack you or
    planeswalkers you control unless its controller pays {X}, where X is the
    number of counters on that creature."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("nils_end_step_counters", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments legst du fuer jeden Spieler eine "
                     "+1/+1-Marke auf bis zu eine Zielkreatur, die jener Spieler "
                     "kontrolliert.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("attack_tax", {
                "attacker_filter": {"has_any_counter": True},
                "amount_per_attacker_counter": "any",
                "defender_scope": "player_or_planeswalker",
            })],
            raw_text="Jede Kreatur mit einer oder mehr Marken kann dich oder "
                     "Planeswalker, die du kontrollierst, nicht angreifen, es sei denn, "
                     "ihr Beherrscher bezahlt {X}, wobei X die Anzahl der Marken auf "
                     "jener Kreatur ist.",
        ),
    ]


register("Nils, Discipline Enforcer", _nils_discipline_enforcer)


# ===========================================================================
# wave 105 — Intermediate Chirography (hand-authored Class) — PAR-60
# ===========================================================================
# The parser already claims 4 of 5 clauses; only the level-3 "modified
# creature died" end-step trigger was a gap. Hand-authored as a full Class
# instead (the parser's own Class shapes: a ``class_level`` level-up
# activated ability per level + ``min_level``/``level_counter="class_level"``
# gates on each body ability). The level-3 body self-gates on the new
# `GameState.modified_creatures_died_this_turn` tracker.

_INKLING = {
    "count": 1, "token_name": "Inkling", "power": 2, "toughness": 1,
    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
}


def _intermediate_chirography() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    When this Class enters, create a 2/1 white and black Inkling creature
    token with flying.
    {1}{B}: Level 2
    Whenever you lose life for the first time each turn, put a +1/+1 counter
    on target creature you control.
    {2}{B}: Level 3
    At the beginning of each end step, if a modified creature died under your
    control this turn, create a 2/1 white and black Inkling creature token
    with flying."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", dict(_INKLING))],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Klasse ins Spiel kommt, erzeuge einen 2/1 "
                     "weiss-schwarzen Tintling-Spielstein mit Fliegend.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{1}{B}", "sorcery_speed_only": True, "class_level": 2},
            raw_text="{1}{B}: Stufe 2",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1",
                                         "target_kind": "creature_you_control"})],
            trigger={
                "event": "LIFE_LOST", "condition": {"subject": "you"}, "limit": True,
                "min_level": 2, "level_counter": "class_level",
            },
            raw_text="Immer wenn du zum ersten Mal in einem Zug Lebenspunkte verlierst, "
                     "lege eine +1/+1-Marke auf eine Zielkreatur, die du kontrollierst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{2}{B}", "sorcery_speed_only": True, "class_level": 3},
            raw_text="{2}{B}: Stufe 3",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("intermediate_chirography_l3", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "min_level": 3, "level_counter": "class_level",
            },
            raw_text="Zu Beginn jedes Endsegments, falls in diesem Zug eine "
                     "modifizierte Kreatur unter deiner Kontrolle gestorben ist, "
                     "erzeuge einen 2/1 weiss-schwarzen Tintling-Spielstein mit Fliegend.",
        ),
    ]


register("Intermediate Chirography", _intermediate_chirography)


# ===========================================================================
# wave 106 — Advanced Reconstruction (hand-authored Class) — PAR-60
# ===========================================================================
# Level 1: new `advanced_reconstruction_l1` effect (mill + random graveyard
# exile + play-this-turn). Level 2: the batched ``CARDS_LEFT_GRAVEYARD``
# trigger (Quintorius / Spirit of Resilience family) -> 2 damage to each
# opponent. Level 3: `cost_reduction` with the new ``not_from_hand`` param.


def _advanced_reconstruction() -> list[AbilitySpec]:
    """(Gain the next level as a sorcery to add its ability.)
    At the beginning of your first main phase, mill a card, then exile a
    card from your graveyard at random. You may play the exiled card this
    turn.
    {1}{R}: Level 2
    Whenever one or more cards leave your graveyard, this Class deals 2
    damage to each opponent.
    {1}{R}: Level 3
    Spells you cast from anywhere other than your hand cost {2} less to
    cast."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("advanced_reconstruction_l1", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                     "phase_relation": "you"},
            raw_text="Zu Beginn deiner ersten Hauptphase lege eine Karte in deinen "
                     "Friedhof (mahlen), dann verbanne zufaellig eine Karte aus deinem "
                     "Friedhof. Du darfst die verbannte Karte in diesem Zug spielen.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 2})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": 2},
            raw_text="{1}{R}: Stufe 2",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})],
            trigger={
                "event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you",
                "min_level": 2, "level_counter": "class_level",
            },
            raw_text="Immer wenn eine oder mehr Karten deinen Friedhof verlassen, fuegt "
                     "diese Klasse jedem Gegner 2 Schadenspunkte zu.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("class_level", {"level": 3})],
            cost={"text": "{1}{R}", "sorcery_speed_only": True, "class_level": 3},
            raw_text="{1}{R}: Stufe 3",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 2, "not_from_hand": True,
                "min_level": 3, "level_counter": "class_level",
            })],
            raw_text="Zauberspreuche, die du von woanders als aus deiner Hand wirkst, "
                     "kosten beim Wirken {2} weniger.",
        ),
    ]


register("Advanced Reconstruction", _advanced_reconstruction)
