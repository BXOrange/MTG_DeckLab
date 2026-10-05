from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "permanent", "max_mana_value": 3})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -9},
        ),
    ]


register("Vraska, Golgari Queen", _vraska_golgari_queen)
