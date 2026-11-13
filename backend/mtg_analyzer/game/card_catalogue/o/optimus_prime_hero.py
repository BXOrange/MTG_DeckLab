"""Both physical faces of Optimus Prime."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hero():
    """More Than Meets the Eye {2}{U}{R}{W} (You may cast this card converted for {2}{U}{R}{W}.)
At the beginning of each end step, bolster 1. (Choose a creature with the least toughness among creatures you control and put a +1/+1 counter on it.)
When Optimus Prime dies, return it to the battlefield converted under its owner's control."""
    return [
        AbilitySpec("triggered", [EffectSpec("bolster", {"amount": 1})],
                    trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}}),
        AbilitySpec("triggered", [EffectSpec("optimus_return_converted", {})],
                    trigger={"event": EventType.DIES, "condition": {"subject": "self"}}),
    ]


def _autobot_leader():
    """Living metal (During your turn, this Vehicle is also a creature.)
Trample
Whenever you attack, bolster 2. The chosen creature gains trample until end of turn. When that creature deals combat damage to a player this turn, convert Optimus Prime."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "living_metal"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("triggered", [EffectSpec("optimus_attack_bolster", {})],
                    trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}}),
    ]


register("Optimus Prime, Hero", _hero)
register("Optimus Prime, Hero // Optimus Prime, Autobot Leader", _hero)
register("Optimus Prime, Autobot Leader", _autobot_leader)
