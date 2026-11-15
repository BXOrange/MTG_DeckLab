"""Court's upkeep ability survives its copy effect and is itself copiable."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register, register_ability_line


UPKEEP = "At the beginning of your upkeep, choose up to one other target enchantment or artifact. If you're the monarch, you may create a token that's a copy of it. If you're not the monarch, you may have this enchantment become a copy of it, except it has this ability."


def _upkeep():
    return [AbilitySpec('triggered', [EffectSpec('court_copy', {'ability_line': UPKEEP})],
                        trigger={'event': EventType.STEP_BEGIN, 'step': 'upkeep',
                                 'condition': {'subject': 'you'}}, raw_text=UPKEEP)]


def _court_of_vantress():
    "When this enchantment enters, you become the monarch.\nAt the beginning of your upkeep, choose up to one other target enchantment or artifact. If you're the monarch, you may create a token that's a copy of it. If you're not the monarch, you may have this enchantment become a copy of it, except it has this ability."
    return [AbilitySpec('triggered', [EffectSpec('become_monarch', {})],
                        trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}},
                        raw_text='When this enchantment enters, you become the monarch.'), *_upkeep()]


register_ability_line(UPKEEP, _upkeep)
register('Court of Vantress', _court_of_vantress)
