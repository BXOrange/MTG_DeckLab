"""Skyway Robber offers one spell from its original escape-cost exile visits."""
from .core import GameEffect, _controller_of
from ..linked_exile import linked_cards


class SkywayRobberCastEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        allowed = ['artifact', 'instant', 'sorcery']
        candidates = []
        for obj in linked_cards(context.state, self.source, context.resolving_source_incarnation):
            faces = [obj.card]
            if not obj.card.is_transforming:
                faces.append(obj.card.back_face())
            for card in faces:
                if card is not None and any(word in card.type_line.lower().split('—')[0].split() for word in allowed):
                    candidates.append(obj)
                    break
        context.engine._request_resolution_play(player, candidates, only_spells=True, free=True,
                                                 allowed_spell_types=allowed)
