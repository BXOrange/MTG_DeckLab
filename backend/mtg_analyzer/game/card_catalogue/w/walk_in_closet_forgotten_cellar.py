"""Walk-In Closet // Forgotten Cellar, with independently bound doors."""
from ....models.game.events import EventType
from ....parser.oracle.catalogue.player_event_head import THIS_DOOR
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _walk_in_closet():
    """You may play lands from your graveyard."""
    return [AbilitySpec("static", [EffectSpec("graveyard_cast_permission", {"lands_only": True})])]


def _forgotten_cellar():
    """When you unlock this door, you may cast spells from your graveyard this turn, and if a card would be put into your graveyard from anywhere this turn, exile it instead."""
    return [AbilitySpec("triggered", [
        EffectSpec("graveyard_cast_pool_this_turn", {}),
        EffectSpec("graveyard_redirect_to_exile_this_turn", {}),
    ], trigger={"event": EventType.DOOR_UNLOCKED, "condition": {"subject": "self"},
                "filter": {"door": THIS_DOOR}})]


register("Walk-In Closet", _walk_in_closet)
register("Forgotten Cellar", _forgotten_cellar)
