"""Resolve name references before an operation changes the reference's zone."""
from __future__ import annotations

from .composition import _CompositeEffect, _build
from .core import EffectRegistry, _controller_of, _apply_effects_partitioned
from ...models.cards.card_query import names_overlap


class SameNameSearchEffect(_CompositeEffect):
    """RULE 608.2h / 701.23: capture a name and player before moving the target.

    Public graveyard matches must all be found; a hidden-zone quality search
    may fail to find. Choices use the existing search continuation and remain
    serializable through clone/undo.
    """

    def __init__(self, effects=None, player_role='owner', any_number=False, source=None):
        super().__init__(effects, source)
        self.player_role = player_role
        self.any_number = any_number

    @property
    def target_specs(self):
        return [spec for effect in _build(self.inner_specs, self.source) for spec in effect.target_specs]

    def apply(self, context, targets=None):
        if not targets:
            return
        reference = getattr(targets[0], 'obj', None) or targets[0]
        name = reference.name
        player_id = reference.owner_id if self.player_role == 'owner' else reference.controller_id
        owner = context.state.player_by_id(player_id)
        chooser = _controller_of(self.source, context)
        # RULE 701.23: a search prohibition applies to the searching player.
        effects = _build(self.inner_specs, self.source)
        effects.append(_SearchCapturedNameEffect(name, owner.id, chooser.id, self.any_number, self.source))
        _apply_effects_partitioned(effects, context, targets, None, source=self.source)


class _SearchCapturedNameEffect(_CompositeEffect):
    def __init__(self, name, owner_id, chooser_id, any_number, source):
        super().__init__(source=source)
        self.name, self.owner_id, self.chooser_id = name, owner_id, chooser_id
        self.any_number = any_number

    def apply(self, context, targets=None):
        owner = context.state.player_by_id(self.owner_id)
        chooser = context.state.player_by_id(self.chooser_id)
        if context.engine.is_search_prohibited_for(chooser):
            context.shuffle_library(owner)
            return
        criteria = {'same_name_as': self.name}
        zones = ['graveyard', 'hand', 'library']
        required = [] if self.any_number else [obj.instance_id for obj in owner.graveyard
                                               if names_overlap(obj.name, self.name)]
        count = sum(len(getattr(owner, zone)) for zone in zones)
        context.engine._request_search(owner, criteria, 'exile', count, True,
            zones=zones, chooser=chooser, source=self.source, required_ids=required)


EffectRegistry.register('same_name_search', lambda p: SameNameSearchEffect(
    p.get('effects'), p.get('player_role', 'owner'), bool(p.get('any_number', False))))
