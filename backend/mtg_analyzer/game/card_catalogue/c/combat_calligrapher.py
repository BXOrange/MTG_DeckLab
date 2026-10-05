from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Combat Calligrapher (attacker-makes-the-token) — PAR-60
# ===========================================================================
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
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attacker_creates_attacking_token", {
                "power": 2, "toughness": 1, "colors": ["W", "B"],
                "subtypes": ["Inkling"], "keywords": ["flying"], "token_name": "Inkling",
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "defender_is_opponent": True},
        ),
    ]


register("Combat Calligrapher", _combat_calligrapher)
