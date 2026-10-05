from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _march_of_the_world_ooze() -> list[AbilitySpec]:
    """Creatures you control have base power and toughness 6/6 and are Oozes
    in addition to their other types.
    Whenever an opponent casts a spell, if it's not their turn, you create a
    3/3 green Elephant creature token.

    — PLAY-ALL Step 2 (Raggadragga). The sentence is two layers: Humility's
    layer-7b `pt_set` (here scoped to ``creatures_you_control``) and the
    parser's own layer-4 `type_change` for "are Oozes in addition to their
    other types" (probed alone; only the combined sentence was unclaimed).
    The trigger is the parser's "whenever an opponent casts a spell" shape
    with Price of Glory's ``not_controllers_turn`` as the "if it's not their
    turn" intervening-if, checked against the *caster* — so it also fires in
    a multiplayer game on a third player's turn, which a plain "during your
    turn" would miss.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_set", {"power": 6, "toughness": 6, "affects": "creatures_you_control"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {"affects": "creatures_you_control", "add_subtypes": ["Ooze"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 3, "colors": ["G"],
                "subtypes": ["Elephant"], "keywords": [], "token_name": "Elephant",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "not_controllers_turn": True,
            },
        ),
    ]


register("March of the World Ooze", _march_of_the_world_ooze)
