"""Continuous bodies composed with the shared duration grammar (RULE 611.2)."""
from ...spec import EffectSpec
from ..static_handlers import quoted_ability_grant_effects_list
# These are ordinary continuous bodies; the duration axis above composes
# them with any supported clock rather than enumerating per-card phrases.
from .shared import EffectHandler, compile_clause
from ..subgrammars import TARGET, resolve_target_kind, target_is_optional, target_quality_filter, target_kind_allowed


def _continuous_body(m):
    kind = resolve_target_kind(m['target'])
    if not target_kind_allowed(kind, ('creature', 'artifact', 'land', 'permanent', 'enchantment', 'planeswalker')):
        return None
    static = {'type': 'no_untap', 'params': {}}
    if m.groupdict().get('loss'):
        statics = [{'type': 'remove_all_abilities', 'params': {}}, {'type': 'grant_keyword', 'params': {'keywords': ['cant_attack', 'cant_block']}}]
    elif m.groupdict().get('quote'):
        grants = quoted_ability_grant_effects_list(m['quote'])
        if not grants:
            return None
        statics = [{'type': g.type, 'params': {**g.params, 'affects': 'self'}} for g in grants]
    else:
        statics = [static]
    return [EffectSpec('grant_until', {
        'target_kind': kind, 'optional': target_is_optional(m),
        'creature_filter': target_quality_filter(m['target']),
        'static': statics[0], 'extra_statics': statics[1:], 'duration': 'end_of_turn',
    })]


ROWS = [
    EffectHandler('duration_loss_restriction_target', compile_clause(
        rf"{TARGET} (?P<loss>loses all abilities and can'?t attack or block) until end of turn"), _continuous_body),
    EffectHandler('duration_quoted_target', compile_clause(
        rf'{TARGET} (?:gains?|has) "(?P<quote>.+)" until end of turn'), _continuous_body),
    EffectHandler('duration_no_untap_target', compile_clause(
        rf"{TARGET} doesn'?t untap during its controller'?s untap step until end of turn"), _continuous_body),
]
