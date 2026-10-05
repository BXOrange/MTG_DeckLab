from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"kind": "frodo_stage", "amount": 1})],
            cost={
                "mana": "{B}{B}{B}",
                "activation_condition": {"kind": "source_counters", "counter": "frodo_stage", "min": 1, "max": 1},
            },
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
                            "type": "if_else",
                            "params": {
                                "condition": {"kind": "ring_tempted", "min": 4},
                                "then": [
                                    {"type": "lose_game_trigger_damaged_player",
                                     "params": {}},
                                ],
                                "else": [
                                    {"type": "the_ring_tempts_you", "params": {}},
                                ],
                            },
                        },
                    ],
                    "active_if": {"kind": "source_counters", "counter": "frodo_stage", "min": 2},
                }),
            ],
        ),
    ]


register("Frodo, Sauron's Bane", _frodo_saurons_bane)
