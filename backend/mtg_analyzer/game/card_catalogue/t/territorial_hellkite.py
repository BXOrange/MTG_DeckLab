from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _territorial_hellkite() -> list[AbilitySpec]:
    """Flying, haste
    At the beginning of combat on your turn, choose an opponent at random that this creature didn't attack during your last combat. This creature attacks that player this combat if able. If you can't choose an opponent this way, tap this creature.

    — PLAY-ALL Step 2 (Temur Roar). Flying/haste are printed keywords. The trigger is the `STEP_BEGIN`
    beginning-of-combat head Rionya uses; its body is the new `force_attack_unattacked_opponent` (see
    `ForceAttackUnattackedOpponentEffect`): the random pick excludes the players the Hellkite attacked in its
    controller's previous combat (`GameObject.last_combat_attacked_ids`, recorded at end of combat), the pick
    becomes a `must_attack_player_id` requirement enforced when attackers are declared, and with nobody left
    it taps itself.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("force_attack_unattacked_opponent", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Territorial Hellkite", _territorial_hellkite)
