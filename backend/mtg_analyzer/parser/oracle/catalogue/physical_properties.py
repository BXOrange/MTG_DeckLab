"""Physical printed-layout operands; Oracle wrapping is never a measurement."""
import re
from ..spec import EffectSpec


def physical_fight_specs(body):
    if re.fullmatch(r"choose target creature you don't control\. reveal the top card of your library\. ~ gets \+x/\+0 until end of turn, where x is the number of lines of rules text of the revealed card\. ~ fights that creature\.?", body):
        return [EffectSpec('choose_targets', {'kinds': ['creature_you_dont_control']}),
                EffectSpec('reveal_top', {}),
                EffectSpec('measure_physical_property', {'property': 'printed_rules_lines', 'of': 'revealed'}),
                EffectSpec('pump', {'dynamic_amount': {'kind': 'physical_property', 'of': 'revealed', 'property': 'printed_rules_lines'}, 'amount_from_count_selector_axis': 'power'}),
                EffectSpec('fight', {'other_kind': 'previous_target'})]
    return None
