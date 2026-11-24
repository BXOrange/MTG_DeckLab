"""Resolve name references before an operation changes the reference's zone."""
from __future__ import annotations

from typing import Any, Optional

from .composition import _CompositeEffect, _build
from .core import EffectRegistry, GameEffect, _controller_of, _apply_effects_partitioned
from .. import effect_conditions
from ...models.cards import card_query
from ...models.cards.card_query import names_overlap

#: RULE 400.2 / 701.23: the zones a same-name sweep reads, public graveyard first, then the two hidden ones.
SWEEP_ZONES = ("graveyard", "hand", "library")


class SameNameSearchEffect(_CompositeEffect):
    """RULE 608.2h / 701.23: capture a name and player before moving the target.

    Public graveyard matches must all be found; a hidden-zone quality search
    may fail to find. Choices use the existing search continuation and remain
    serializable through clone/undo.

    The name operand is the target of the leading ``effects`` clause (Counterbore, Surgical Extraction: the default), or,
    with ``from_previous``, the card(s) an earlier clause of this resolution picked or exiled (``previous_targets``:
    Lobotomy's chosen card, Pick the Brain's exiled card, Reap Intellect's exiled cards -- one sweep for every name, one
    shuffle). ``reference_filter`` gates the search on the reference card (Deicide's "if the exiled card is a God
    card"; a failed gate does not search, but the separate "Then that player shuffles" still happens, RULE 608.2c), ``condition`` on the game as the sweep begins
    (Invasive Surgery's delirium, read after the counter resolved). ``then_effects`` run as the searched player once per
    sweep when at least one card left their *hand*, ``$n`` being that count ("draws a card for each card exiled from
    their hand this way", Test of Talents). ``zones`` narrows the sweep (Haunting Echoes: the library only).
    """

    def __init__(self, effects=None, player_role='owner', any_number=False, from_previous=False,
                 reference_filter=None, condition=None, then_effects=None, zones=None, source=None):
        super().__init__(effects, source)
        self.player_role = player_role
        self.any_number = any_number
        self.from_previous = bool(from_previous)
        self.reference_filter = dict(reference_filter or {})
        self.condition = dict(condition) if condition else None
        self.then_effects = [dict(spec) for spec in (then_effects or [])]
        self.zones = [zone for zone in (zones or SWEEP_ZONES) if zone in SWEEP_ZONES]

    @property
    def target_specs(self):
        return [spec for effect in _build(self.inner_specs, self.source) for spec in effect.target_specs]

    def apply(self, context, targets=None):
        if self.from_previous:
            references = [getattr(obj, 'obj', None) or obj for obj in (getattr(context, 'previous_targets', None) or [])]
        else:
            references = [getattr(targets[0], 'obj', None) or targets[0]] if targets else []
        if not references:
            return
        # RULE 608.2c: the gate decides the sweep only; the lead clause (Deicide's exile) happens either way.
        gated_in = not self.reference_filter or all(
            card_query.matches(reference.card, self.reference_filter) for reference in references)
        names = [reference.name for reference in references]
        reference = references[0]
        player_id = reference.owner_id if self.player_role == 'owner' else reference.controller_id
        owner = context.state.player_by_id(player_id)
        chooser = _controller_of(self.source, context)
        # RULE 701.23: a search prohibition applies to the searching player.
        effects = _build(self.inner_specs, self.source)
        effects.append(_SearchCapturedNameEffect(
            names, owner.id, chooser.id, self.any_number, self.source,
            condition=self.condition, then_effects=self.then_effects, zones=self.zones, gated_in=gated_in))
        _apply_effects_partitioned(effects, context, targets, None, source=self.source,
                                   previous_targets=list(getattr(context, 'previous_targets', []) or []))


class _SearchCapturedNameEffect(_CompositeEffect):
    def __init__(self, names, owner_id, chooser_id, any_number, source, condition=None, then_effects=None, zones=None, gated_in=True):
        super().__init__(source=source)
        self.gated_in = gated_in
        self.names = [names] if isinstance(names, str) else list(names)
        self.owner_id, self.chooser_id = owner_id, chooser_id
        self.any_number = any_number
        self.condition = condition
        self.then_effects = then_effects or []
        self.zones = list(zones or SWEEP_ZONES)

    def _matches(self, obj):
        return any(names_overlap(obj.name, name) for name in self.names)

    def apply(self, context, targets=None):
        if not self.gated_in:
            # RULE 608.2c: "Then that player shuffles" is its own instruction after the gated search (Deicide on a
            # non-God): the library is shuffled although nothing was searched for. RULE 701.24a.
            if 'library' in self.zones:
                context.shuffle_library(context.state.player_by_id(self.owner_id))
            return
        if self.condition and not effect_conditions.condition_holds(self.condition, context, self.source, targets):
            return
        owner = context.state.player_by_id(self.owner_id)
        chooser = context.state.player_by_id(self.chooser_id)
        if context.engine.is_search_prohibited_for(chooser):
            if 'library' in self.zones:
                context.shuffle_library(owner)
            return
        criteria = {'same_name_as': self.names[0]} if len(self.names) == 1 else \
            {'or': [{'same_name_as': name} for name in self.names]}
        zones = list(self.zones)
        required = [] if self.any_number else [obj.instance_id for obj in owner.graveyard
                                               if 'graveyard' in zones and self._matches(obj)]
        count = sum(len(getattr(owner, zone)) for zone in zones)
        then_specs = None
        if self.then_effects and 'hand' in zones:
            hand_ids = [obj.instance_id for obj in owner.hand if self._matches(obj)]
            then_specs = [{'type': 'exiled_from_hand_follow_up', 'params': {
                'hand_ids': hand_ids, 'player_id': owner.id, 'effects': self.then_effects}}]
        context.engine._request_search(owner, criteria, 'exile', count, True,
            zones=zones, chooser=chooser, source=self.source, required_ids=required, then_specs=then_specs)


class ExiledFromHandFollowUpEffect(GameEffect):
    """RULE 608.2c: "... then draws a card for each card exiled from their hand this way" after a same-name sweep. Runs as
    the sweep's ``then_specs`` (the found cards are the ``previous_targets``); ``hand_ids`` were measured when the sweep
    opened, because the cards have left the hand by now. The follow-up acts as the searched player."""

    def __init__(self, hand_ids=None, player_id: Optional[str] = None, effects=None, source=None):
        super().__init__(source)
        self.hand_ids = set(hand_ids or [])
        self.player_id = player_id
        self.effects = [dict(spec) for spec in (effects or [])]
        self.target_spec = None

    def apply(self, context, targets=None):
        count = sum(1 for obj in (getattr(context, 'previous_targets', None) or []) if obj.instance_id in self.hand_ids)
        if not count or not self.effects:
            return
        outer = context.acting_player_id
        context.acting_player_id = self.player_id
        try:
            context.engine._apply_effect_specs(
                [{'type': 'bind', 'params': {'name': 'n', 'amount': count, 'effects': self.effects}}], self.source)
        finally:
            context.acting_player_id = outer


EffectRegistry.register('same_name_search', lambda p: SameNameSearchEffect(
    p.get('effects'), p.get('player_role', 'owner'), bool(p.get('any_number', False)),
    from_previous=bool(p.get('from_previous', False)), reference_filter=p.get('reference_filter'),
    condition=p.get('condition'), then_effects=p.get('then_effects'), zones=p.get('zones')))
EffectRegistry.register('exiled_from_hand_follow_up', lambda p: ExiledFromHandFollowUpEffect(
    p.get('hand_ids'), p.get('player_id'), p.get('effects')))
