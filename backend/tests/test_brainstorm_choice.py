"""Brainstorm's hand selection and library order must remain interactive."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Human", []), ("p2", "Bot", [])], starting_hand=0,
    )


def _put(player, zone, name):
    obj = GameObject(Card(id=name, name=name, type_line="Instant", is_instant=True),
                     owner_id=player.id, zone=zone)
    player.add_to_zone(obj, zone)
    return obj


@pytest.mark.parametrize("active_player_index", [0, 1])
def test_brainstorm_cast_offers_entire_hand_and_preserves_selected_order(active_player_index):
    eng = _engine()
    eng.state.active_player_index = active_player_index
    p = eng.state.players[0]
    eng.state.current_step = "main1"
    old = _put(p, Zone.HAND, "Old hand card")
    for i in range(5):
        _put(p, Zone.LIBRARY, f"Library {i}")
    spell = GameObject(Card(
        id="brainstorm", name="Brainstorm", type_line="Instant", is_instant=True,
        mana_cost_string="{U}", oracle_text="Draw three cards, then put two cards from your hand "
        "on top of your library in any order.",
    ), owner_id=p.id, zone=Zone.HAND)
    p.hand.append(spell)
    bind_from_catalogue(spell)
    p.mana_pool.add("U", 1)
    eng.cast_spell(p, spell)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects"
    assert choice["player_id"] == p.id
    assert {o["instance_id"] for o in choice["options"]} == {o.instance_id for o in p.hand}
    drawn = p.hand[-1]
    eng.resolve_pending_choice(old.instance_id)
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(drawn.instance_id)
    assert eng.state.pending_choice is None
    assert p.library[-2:] == [old, drawn]
    assert len(p.hand) == 2
    eng.resolve_until_stable()
    assert spell in p.graveyard


@pytest.mark.parametrize("hand_size", [0, 1, 2])
def test_return_all_available_hand_cards_still_allows_order(hand_size):
    eng = _engine()
    p = eng.state.active_player
    cards = [_put(p, Zone.HAND, f"Hand {i}") for i in range(hand_size)]
    eng.rules.put_hand_cards_on_top(p, 2)
    if hand_size == 2:
        assert eng.state.pending_choice is not None
        with pytest.raises(ValueError):
            eng.resolve_pending_choice(None)
        for card in reversed(cards):
            eng.resolve_pending_choice(card.instance_id)
        assert p.library == list(reversed(cards))
    else:
        assert eng.state.pending_choice is None
        assert p.library == cards
    assert not p.hand
