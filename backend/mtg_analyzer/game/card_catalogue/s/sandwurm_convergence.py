from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sandwurm_convergence() -> list[AbilitySpec]:
    """Creatures with flying can't attack you or planeswalkers you control.
    At the beginning of your end step, create a 5/5 green Wurm creature token.

    — PLAY-ALL (Jump Scare!). The Wurm trigger is the parser's. The restriction is `cant_attack_defender` (RULE 508.1)
    with an ``attacker_filter`` on the ``flying`` keyword (a new key of `continuous._defender_attack_ban_matches`).
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_attack_defender", {
            "defender_scope": "player_or_planeswalker", "attacker_filter": {"keyword": "flying"},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 5, "toughness": 5, "colors": ["G"], "subtypes": ["Wurm"], "keywords": [],
                "token_name": "Wurm",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Sandwurm Convergence", _sandwurm_convergence)
