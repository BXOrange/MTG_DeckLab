from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bespoke_battlewagon() -> list[AbilitySpec]:
    """{T}: You get {E}{E} (two energy counters).
    {T}, Pay {E}{E}: Tap target creature.
    {T}, Pay {E}{E}{E}: Draw a card.
    Pay {E}{E}{E}{E}: This Vehicle becomes an artifact creature until end of turn.
    Crew 4

    — PLAY-ALL (Living Energy). Crew is the keyword's. The first three abilities are the parser's; the animation is
    Crew's own `grant_until`/`type_change` shape with the printed 5/6 Vehicle power and toughness.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_player_counters", {"amount": 2, "kind": "energy"})],
            cost={"text": "{t}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"target_kind": "creature", "untap": False})],
            cost={"text": "{t}, pay {e}{e}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{t}, pay {e}{e}{e}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "type_change", "params": {"add_types": ["creature"], "power": 5, "toughness": 6}},
            })],
            cost={"text": "pay {e}{e}{e}{e}"},
        ),
    ]


register("Bespoke Battlewagon", _bespoke_battlewagon)
