"""One announced target, with Court's monarch-dependent copy instruction."""
from .core import EffectRegistry, GameEffect, _controller_of
from .composition import OptionalEffect
from .counters_tokens import BecomeCopyPermanentEffect, CopyPermanentEffect
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class CourtCopyEffect(GameEffect):
    def __init__(self, ability_line, mode=None, source=None):
        super().__init__(source)
        self.ability_line = ability_line
        self.mode = mode
        self.target_spec = (TargetSpec(kind='artifact_or_enchantment', exclude_source=True, optional=True)
                            if mode is None else None)

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        if self.mode is None:
            # RULE 608.2c: check the designation now, not when the trigger fired.
            mode = 'token' if context.state.monarch_id == controller.id else 'source'
            OptionalEffect(effects=[{'type': 'court_copy', 'params': {
                'ability_line': self.ability_line, 'mode': mode,
            }}], source=self.source).apply(context, targets)
        elif self.mode == 'token':
            CopyPermanentEffect(target_kind='artifact_or_enchantment', source=self.source).apply(context, targets)
        elif self.mode == 'source':
            # RULE 400.7: the trigger cannot change a returned Court's new visit.
            source = self.source
            visit = context.resolving_source_incarnation
            if source is None or source.zone != Zone.BATTLEFIELD or (
                    visit is not None and source.zone_incarnation != visit):
                return
            # RULE 707.9a: retain just this ability as part of the copiable values.
            BecomeCopyPermanentEffect(target_kind='artifact_or_enchantment',
                add_ability_lines=[self.ability_line], source=source).apply(context, targets)


EffectRegistry.register('court_copy', lambda p: CourtCopyEffect(p['ability_line'], p.get('mode')))
