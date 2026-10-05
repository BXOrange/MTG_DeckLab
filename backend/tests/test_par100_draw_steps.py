"""PAR-100: additional draws belong to the player whose draw step it is."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.continuous import cost_reduction_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _engine(text, name="Draw Step Test"):
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Charlie", [])],
        starting_hand=0, starting_life=20,
    )
    card = Card(id=name, name=name, type_line="Enchantment", oracle_text=text)
    assert parse_oracle(card).modeled
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    for player in eng.state.players:
        for i in range(8):
            card = Card(id=f"{player.id}-{i}", name=f"{player.id}-{i}", type_line="Sorcery")
            player.library.append(GameObject(card, owner_id=player.id, zone=Zone.LIBRARY))
    return eng, source


def _trigger(eng, player_index=1):
    eng.state.active_player_index = player_index
    eng.state.current_step = "draw"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="draw", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    while eng.state.stack and eng.state.pending_choice is None:
        eng.rules.resolve_top_of_stack()


@pytest.mark.parametrize("count", ["an", "two", "three", "four"])
@pytest.mark.parametrize("player_index", [0, 1, 2])
def test_additional_draws_go_only_to_active_player(count, player_index):
    plural = "card" if count == "an" else "cards"
    eng, _ = _engine(f"At the beginning of each player's draw step, that player draws {count} additional {plural}.")
    _trigger(eng, player_index)
    expected = {"an": 1, "two": 2, "three": 3, "four": 4}[count]
    assert [len(p.hand) for p in eng.state.players] == [expected if i == player_index else 0 for i in range(3)]


@pytest.mark.parametrize("player_index,expected", [(0, 2), (1, 1), (2, 1)])
def test_well_of_ideas_scopes(player_index, expected):
    eng, _ = _engine("At the beginning of each other player's draw step, that player draws an additional card.\n"
                     "At the beginning of your draw step, draw two additional cards.")
    _trigger(eng, player_index)
    assert len(eng.state.players[player_index].hand) == expected
    assert sum(len(p.hand) for p in eng.state.players) == expected


def test_howling_mine_checks_untapped_at_trigger_and_resolution():
    eng, source = _engine("At the beginning of each player's draw step, if this enchantment is untapped, that player draws an additional card.")
    source.tapped = True
    _trigger(eng)
    assert not eng.state.stack and not eng.state.players[1].hand
    source.tapped = False
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="draw", phase="beginning"))
    assert eng.rules.put_triggers_on_stack() == 1
    source.tapped = True
    eng.rules.resolve_top_of_stack()
    assert not eng.state.players[1].hand
    source.tapped = False
    _trigger(eng)
    assert len(eng.state.players[1].hand) == 1


def test_anvil_discards_from_active_players_hand():
    eng, _ = _engine("At the beginning of each player's draw step, that player draws an additional card, then discards a card.")
    eng.rules.draw(eng.state.players[1])
    _trigger(eng)
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    eng.resolve_pending_choice(choice["options"][0]["id"])
    assert not eng.state.players[0].hand
    assert len(eng.state.players[1].hand) == 1
    assert len(eng.state.players[1].graveyard) == 1


@pytest.mark.parametrize("accept", [False, True])
def test_loremaster_optional_draw_and_tax_belong_to_active_player(accept):
    eng, source = _engine("At the beginning of each player's draw step, that player may draw an additional card. "
                         "If they do, spells they cast this turn cost {2} more to cast.")
    _trigger(eng)
    assert eng.state.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("yes" if accept else "decline")
    p1, p2, _ = eng.state.players
    assert len(p2.hand) == int(accept)
    assert not p1.hand
    assert cost_reduction_for(eng.state, p2)[0] == (-2 if accept else 0)
    assert cost_reduction_for(eng.state, p1)[0] == 0
    # The turn-scoped tax survives the source leaving the battlefield.
    eng.state.remove_from_battlefield(source)
    assert cost_reduction_for(eng.state, p2)[0] == (-2 if accept else 0)
    eng._step_cleanup()
    assert cost_reduction_for(eng.state, p2)[0] == 0


@pytest.mark.parametrize("hand_size", [0, 1, 3])
def test_puzzle_box_orders_hand_then_draws_original_hand_size(hand_size):
    eng, _ = _engine("At the beginning of each player's draw step, that player puts the cards in their hand "
                     "on the bottom of their library in any order, then draws that many cards.")
    player = eng.state.players[1]
    eng.rules.draw(player, hand_size)
    original = list(player.hand)
    top_cards = list(reversed(player.library[-hand_size:])) if hand_size else []
    _trigger(eng)
    if hand_size > 1:
        assert eng.state.pending_choice["kind"] == "hand_bottom"
        assert eng.state.pending_choice["player_id"] == "p2"
        assert player.hand == original  # drawing waits for the ordering choice
        eng.resolve_pending_choice(str(original[-1].instance_id))
        eng.resolve_pending_choice("decline")
        assert player.library[:hand_size] == list(reversed([original[-1], *original[:-1]]))
    assert player.hand == top_cards
    assert not eng.state.players[0].hand
    assert not eng.state.pending_choice


def test_mornsong_prohibits_draw_and_life_gain_but_searches_for_active_player():
    eng, _ = _engine("Players can't draw cards or gain life.\nAt the beginning of each player's draw step, "
                     "that player loses 3 life, searches their library for a card, puts it into their hand, then shuffles.")
    for player in eng.state.players:
        eng.rules.draw(player)
        eng.rules.gain_life(player, 5)
        assert not player.hand and player.life == 20
    _trigger(eng)
    player = eng.state.players[1]
    assert player.life == 17
    assert eng.state.players[0].life == 20
    assert eng.state.pending_choice["player_id"] == "p2"
    selected = player.library[0]
    eng.resolve_pending_choice(str(selected.instance_id))
    assert selected in player.hand
    assert not eng.state.players[0].hand


def test_puzzle_box_partner_commander_choices_finish_before_drawing():
    eng, _ = _engine("At the beginning of each player's draw step, that player puts the cards in their hand "
                     "on the bottom of their library in any order, then draws that many cards.")
    player = eng.state.players[1]
    eng.rules.draw(player, 2)
    commanders = list(player.hand)
    for obj in commanders:
        obj.is_commander = True
    _trigger(eng)
    eng.resolve_pending_choice("decline")  # retain the default library order
    for obj in commanders:
        assert eng.state.pending_choice["kind"] == "commander_zone"
        assert eng.state.pending_choice["instance_id"] == obj.instance_id
        assert len(player.hand) < 2  # the replacement draw is still paused
        eng.resolve_pending_choice("command")
    assert len(player.hand) == 2
    assert all(obj.zone == Zone.COMMAND for obj in commanders)
    assert not eng.state.players[0].hand
    assert not eng.state.pending_choice


@pytest.mark.parametrize("body", [
    "that player draws two additional cards if the moon is full",
    "that player draws an additional card and you draw a card",
])
def test_unhandled_counts_and_multiple_player_referents_stay_unmodeled(body):
    card = Card(id="unknown", name="Unknown", type_line="Enchantment",
                oracle_text=f"At the beginning of each player's draw step, {body}.")
    assert not parse_oracle(card).modeled


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Academy Loremaster", "Anvil of Bogardan", "Dictate of Kruphix", "Font of Mythos",
    "Howling Mine", "Kami of the Crescent Moon", "Nekusar, the Mindrazer",
    "Rites of Flourishing", "Spiteful Visions", "Teferi's Puzzle Box", "Mornsong Aria",
    "Well of Ideas",
])
def test_real_ticket_cards_are_fully_parsed_and_bound(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    db = CardDatabase(DB_PATH)
    try:
        card = db.get_card(name)
    finally:
        db.close()
    if card is None:
        pytest.skip("Full card cache unavailable")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert obj.triggered_abilities
