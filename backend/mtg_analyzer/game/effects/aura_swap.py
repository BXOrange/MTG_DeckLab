"""RULE 702.65 / 701.12: exchange an Aura with a legal Aura from its owner's hand."""
from .core import GameEffect, _controller_of
from ...models.game.game_object import Zone


def options_for(rules, player, source):
    if (source not in rules.state.permanents() or source.owner_id != player.id
            or source.is_token or source.attached_to is None):
        return {}
    host = rules.state.find_object(source.attached_to)
    if host is None:
        return {}
    return {
        str(card.instance_id): card for card in player.hand
        if card.has_subtype("aura") and rules._attachment_legal(card, host)
    }


class AuraSwapEffect(GameEffect):
    def apply(self, context, targets=None):
        source = self.source
        player = _controller_of(source, context)
        visit = context.resolving_source_incarnation
        if source.zone != Zone.BATTLEFIELD or source.zone_incarnation != visit:
            return
        options = options_for(context.engine, player, source)
        if options:
            context.engine.open_choice({
                "kind": "aura_swap", "player_id": player.id, "source_id": source.instance_id,
                "visit": visit, "prompt": "Aura swap",
                "options": [{"id": key, "label": card.name} for key, card in options.items()]
                           + [{"id": "decline", "label": "Decline"}],
            })
