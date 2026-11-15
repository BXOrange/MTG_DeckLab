"""Outside-game cards and explicit casting permission (RULE 400.11)."""
from ..models.game.game_object import GameObject

def seat_uses_sideboard(commanders=None, game_format=None):
    """RULE 903.5f: Commander games do not use sideboards.

    A seat is in a Commander game when it brings a commander or the game's
    format is Commander-shaped (singleton: Commander, Planechase Commander).
    The stored decklist keeps its sideboard section; only the in-game
    ``Player.sideboard`` is withheld. Other formats (and the format-less
    low-level builders without commanders) still load it.
    """
    if commanders:
        return False
    if game_format:
        from ..models.decks.formats import get_format
        return not get_format(game_format).singleton
    return True

def load_sideboard(player, cards, commanders=None, game_format=None):
    if not seat_uses_sideboard(commanders, game_format):
        return
    from .binding.core import bind_from_catalogue
    for card in cards or []:
        obj = GameObject(card, owner_id=player.id, zone=None)
        bind_from_catalogue(obj)
        player.sideboard.append(obj)

def has_permission(state, player):
    from .continuous import _battlefield_static_abilities
    return any(ab.layer == "sideboard_cast_permission" and ab.source.controller_id == player.id
               for ab in _battlefield_static_abilities(state))

def outside_play_grant_for(state, player, obj, card=None):
    """RULE 400.11: a permanent-card play grant shares its use with the graveyard."""
    from .graveyard_cast import active_graveyard_cast_grants
    from ..models.cards import card_query
    if (obj.zone is not None or obj.owner_id != player.id
            or not any(candidate.instance_id == obj.instance_id for candidate in player.sideboard)):
        return None
    card = card or obj.card
    for effect in active_graveyard_cast_grants(player, state):
        if effect.outside_game and card_query.is_permanent_card(card):
            return effect
    return None


def can_cast_from_sideboard(state, player, obj, card=None):
    # Match stable identity: can_cast previews alternative faces on clones.
    return (obj.zone is None and obj.owner_id == player.id
            and any(card.instance_id == obj.instance_id for card in player.sideboard)
            and (has_permission(state, player) or outside_play_grant_for(state, player, obj, card) is not None))
