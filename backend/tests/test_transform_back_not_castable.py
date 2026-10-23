"""RULE 712.2 / 310.1: the back of a transforming double-faced card (a Battle's flip side) is never offered for casting."""
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _hand_card(layout):
    card = Card(id="x", name="Front", type_line="Battle — Siege", mana_cost_string="{2}{R}", converted_mana_cost=3,
                layout=layout, back_name="Back", back_type_line="Creature — Dragon", back_power=3, back_toughness=3)
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_phase, eng.state.current_step = "precombat_main", "main1"
    player = eng.state.player_by_id("p1")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    player.add_to_zone(obj, Zone.HAND)
    return eng, player, obj


def test_transform_back_face_is_not_offered_or_castable():
    eng, player, obj = _hand_card("transform")
    assert not eng.can_cast(player, obj, face="back", assume_mana_available=True)
    assert all(a.get("face") != "back" for a in eng.legal_actions(player) if a.get("instance_id") == obj.instance_id)


def test_modal_dfc_back_face_stays_castable():
    eng, player, obj = _hand_card("modal_dfc")
    assert eng.can_cast(player, obj, face="back", assume_mana_available=True)
