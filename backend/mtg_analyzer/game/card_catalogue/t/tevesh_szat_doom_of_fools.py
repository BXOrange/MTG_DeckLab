from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


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
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_control_of_all_commanders", {})],
            cost={"loyalty": -10},
        ),
    ]


register("Tevesh Szat, Doom of Fools", _tevesh_szat_doom_of_fools)
