"""Ophidian Eye: cast Aura, attached source, opponent damage and optional draw."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


@pytest.mark.parametrize("combat", [False, True])
@pytest.mark.parametrize("host_owner", ["p1", "p2"])
def test_ophidian_eye_cast_then_damage_offers_draw_to_aura_controller(combat, host_owner):
    fillers = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Instant") for i in range(10)]
    engine = GameEngine.new_game([("p1", "Alice", fillers), ("p2", "Bob", fillers)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1, p2 = engine.state.players
    host = GameObject(Card(id="host", name="Host", type_line="Creature", is_creature=True,
                           power=2, toughness=2), owner_id=host_owner, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(host)
    aura = GameObject(Card(
        id="Ophidian Eye", name="Ophidian Eye", type_line="Enchantment — Aura",
        mana_cost_string="{2}{U}", converted_mana_cost=3,
        oracle_text="Flash (You may cast this spell any time you could cast an instant.)\n"
                    "Enchant creature\n"
                    "Whenever enchanted creature deals damage to an opponent, you may draw a card.",
    ), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(aura)
    p1.add_to_zone(aura, Zone.HAND)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, aura, targets=[host])
    engine.resolve_until_stable()
    assert aura.attached_to == host.instance_id
    assert aura in engine.state.battlefield
    engine.rules.deal_damage(p2, 1, source=host, combat=combat)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["player_id"] == "p1"
    assert {o["id"] for o in choice["options"]} == {"do", "decline"}
    before = len(p1.hand)
    engine.resolve_pending_choice("do")
    assert len(p1.hand) == before + 1
    assert len(p2.hand) == 0


@pytest.mark.parametrize("via_failed_action", [False, True])
def test_ophidian_eye_trigger_uses_restored_aura_attachment_after_state_clone(via_failed_action):
    filler = Card(id="f", name="Filler", type_line="Instant")
    engine = GameEngine.new_game([("p1", "Alice", [filler] * 10), ("p2", "Bob", [])], starting_hand=0)
    host = GameObject(Card(id="host", name="Host", type_line="Creature", is_creature=True,
                           power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(host)
    eye = GameObject(Card(id="Eye", name="Ophidian Eye", type_line="Enchantment — Aura",
                          oracle_text="Enchant creature\nWhenever enchanted creature deals damage to an opponent, you may draw a card."),
                     owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(eye)
    engine.state.players[0].add_to_zone(eye, Zone.HAND)
    # Session error rollback/take-back builds a fresh engine from a clone.
    # The Aura was still in hand at the moment captured by the snapshot.
    if via_failed_action:
        from mtg_analyzer.services.game_session import GameSession, GameActionError
        session = GameSession(engine)
        with pytest.raises(GameActionError):
            session.apply_action({"type": "tap_for_mana", "instance_id": host.instance_id})
        restored = session.engine
        assert restored is not engine
    else:
        restored = GameEngine(engine.state.clone())
    live_eye = restored.state.find_object(eye.instance_id)
    live_host = restored.state.find_object(host.instance_id)
    restored.state.players[0].remove_from_zone(live_eye, Zone.HAND)
    restored.state.add_to_battlefield(live_eye)
    assert restored.rules.attach_to_target(live_eye, live_host)
    restored.rules.deal_damage(restored.state.players[1], 1, source=live_host)
    restored.resolve_until_stable()
    assert restored.state.pending_choice is not None
    assert restored.state.pending_choice["player_id"] == "p1"
