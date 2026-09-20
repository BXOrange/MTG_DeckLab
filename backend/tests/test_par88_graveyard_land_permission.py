"""PAR-88 — standing permission to play land cards from a graveyard."""

from mtg_analyzer.game.effects.core import GraveyardCastPermissionEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.graveyard_cast import graveyard_land_play_grant_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def test_crucible_wording_parses_to_a_land_only_graveyard_permission():
    card = Card(id="cw", name="Crucible of Worlds", type_line="Artifact",
                oracle_text="You may play lands from your graveyard.")
    result = parse_oracle(card)
    assert result.modeled
    assert result.specs[0].effects[0].type == "graveyard_cast_permission"
    assert result.specs[0].effects[0].params == {"lands_only": True}


def test_permission_allows_playing_a_graveyard_land_without_muldrotha_limit():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    player = eng.state.players[0]
    source = GameObject(Card(id="cw", name="Crucible", type_line="Artifact"),
                        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    source.static_effects.append(GraveyardCastPermissionEffect(source=source, lands_only=True))
    eng.state.add_to_battlefield(source)
    land = GameObject(_land(), owner_id="p1", zone=Zone.GRAVEYARD)
    player.add_to_zone(land, Zone.GRAVEYARD)
    eng.begin_turn()
    eng.state.current_step = "main1"
    assert graveyard_land_play_grant_for(player, eng.state, land.card) is not None
    assert eng.can_play_land(player, land)
    eng.play_land(player, land)
    assert land in eng.state.battlefield
