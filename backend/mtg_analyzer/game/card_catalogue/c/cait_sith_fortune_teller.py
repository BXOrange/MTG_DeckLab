from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cait_sith_fortune_teller() -> list[AbilitySpec]:
    """Lucky Slots — At the beginning of combat on your turn, scry 1, then exile the top card of your library. You may play that card this turn. When you exile a card this way, target creature you control gets +X/+0 until end of turn, where X is that card's mana value.

    — PLAY-ALL (Limit Break). `scry`, then Tavern Brawler's `impulsive_draw` (exile with a same-turn play permission, seeding the ``created`` referent), then a `bind` of the exiled card's mana
    value into a reflexive `pump` trigger. Its target is chosen after the scry and exile.
    An empty library creates no reflexive trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("scry", {"count": 1}),
                EffectSpec("impulsive_draw", {"count": 1, "same_turn_only": True}),
                EffectSpec("bind", {
                    "name": "mv", "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "created"},
                    "effects": [{"type": "reflexive_trigger", "params": {"then_trigger": [
                        {"type": "pump", "params": {"power": "$mv", "toughness": 0, "target_kind": "creature_you_control"}},
                    ]}}],
                }, condition={"kind": "amount_compare", "op": "gt",
                    "left": {"kind": "created_count"}, "right": {"kind": "fixed", "amount": 0}}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Cait Sith, Fortune Teller", _cait_sith_fortune_teller)
