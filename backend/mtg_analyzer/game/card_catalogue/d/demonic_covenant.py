from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demonic_covenant() -> list[AbilitySpec]:
    """Whenever one or more Demons you control attack a player, you draw a card and lose 1 life.
    At the beginning of your end step, create a 5/5 black Demon creature token with flying, then mill two cards. If two cards that share all their card types were milled this way, sacrifice this enchantment.

    — PLAY-ALL (Death Toll). The attack trigger is an `ATTACKERS_DECLARED` head counting Demons (``defender: "player"`` — an attacker aimed at a
    planeswalker doesn't count, RULE 508.1b). The end-step trigger creates the token, mills two, then an `if_else` on the
    ``milled_cards_share_all_types`` condition (RULE 608.2's "this way": reads the cards that mill actually moved, `GameContext.moved_objects`)
    sacrifices the Covenant.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("lose_life", {"amount": 1})],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"subtype": "demon"}, "min": 1, "defender": "player"},
            },
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "power": 5, "toughness": 5, "colors": ["B"], "subtypes": ["Demon"],
                    "keywords": ["flying"], "token_name": "Demon",
                }),
                EffectSpec("mill", {"count": 2}),
                EffectSpec("if_else", {
                    "condition": {"kind": "milled_cards_share_all_types"},
                    "then": [{"type": "sacrifice_self", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Demonic Covenant", _demonic_covenant)
