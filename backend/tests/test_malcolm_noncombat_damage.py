"""Malcolm counts noncombat Pirate damage, including Kediss's extra hits."""
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import DealDamageEffect, GameContext
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _setup():
    filler = Card(id="f", name="Filler", type_line="Instant")
    engine = GameEngine.new_game([(p, p, [filler] * 20) for p in ("p1", "p2", "p3", "p4")], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    malcolm = _put(engine, Card(id="Malcolm", name="Malcolm, Keen-Eyed Navigator",
                              type_line="Legendary Creature — Siren Pirate", is_creature=True,
                              power=2, toughness=2, oracle_text="Flying"))
    malcolm.is_commander = True
    return engine, malcolm


def _put(engine, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _treasures(engine):
    return [o for o in engine.state.battlefield if o.name == "Treasure"]


def test_malcolm_creates_one_treasure_per_opponent_hit_by_noncombat_damage():
    engine, malcolm = _setup()
    DealDamageEffect(1, selector="each_opponent", source=malcolm).apply(GameContext(engine.state, engine.rules))
    engine.resolve_until_stable()
    assert len(_treasures(engine)) == 3


def test_simultaneous_pirates_hitting_same_opponent_count_only_once():
    engine, malcolm = _setup()
    pirate = _put(engine, Card(id="Pirate", name="Pirate", type_line="Creature — Pirate", is_creature=True, power=1, toughness=1))
    with engine.state.simultaneous():
        engine.rules.deal_damage(engine.state.players[1], 1, source=malcolm)
        engine.rules.deal_damage(engine.state.players[1], 1, source=pirate)
    engine.resolve_until_stable()
    assert len(_treasures(engine)) == 1


def test_kediss_echo_preserves_malcolm_as_damage_source():
    engine, malcolm = _setup()
    _put(engine, Card(id="Kediss", name="Kediss, Emberclaw Familiar", type_line="Legendary Creature — Elemental Lizard",
                      is_creature=True, power=1, toughness=1,
                      oracle_text="Whenever a commander you control deals combat damage to an opponent, it deals that much damage to each other opponent."))
    engine.rules.deal_damage(engine.state.players[1], 2, source=malcolm, combat=True)
    engine.resolve_until_stable()
    assert len(_treasures(engine)) == 2  # direct DAMAGE call does not emit the combat contributor event
    assert [p.life for p in engine.state.players[1:]] == [38, 38, 38]


def test_both_commanders_attack_with_eye_on_kediss_creates_three_treasures_and_three_draws():
    engine, malcolm = _setup()
    kediss = _put(engine, Card(id="Kediss", name="Kediss, Emberclaw Familiar", type_line="Legendary Creature — Elemental Lizard",
                              is_creature=True, power=1, toughness=1,
                              oracle_text="Whenever a commander you control deals combat damage to an opponent, it deals that much damage to each other opponent."))
    kediss.is_commander = True
    eye = _put(engine, Card(id="Eye", name="Ophidian Eye", type_line="Enchantment — Aura",
                           oracle_text="Flash\nEnchant creature\nWhenever enchanted creature deals damage to an opponent, you may draw a card."))
    assert engine.rules.attach_to_target(eye, kediss)
    malcolm.summoning_sick = kediss.summoning_sick = False
    state = engine.state
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.players[0], [
        {"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}
        for attacker in [malcolm, kediss]
    ])
    engine._step_combat_damage()
    decisions = 0
    engine.resolve_until_stable()
    while state.pending_choice:
        assert state.pending_choice["player_id"] == "p1"
        engine.resolve_pending_choice("do")
        decisions += 1
        assert decisions <= 3
    assert decisions == 3
    assert len(state.players[0].hand) == 3
    assert len(_treasures(engine)) == 3
    assert [p.life for p in state.players[1:]] == [37, 37, 37]
