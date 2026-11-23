"""Execute the printed mechanics through their normal action and binding paths."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _game(step="main1"):
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = step
    return engine, engine.state.active_player


def _card(engine, player, name, text="", *, hand=False, power=2, cost="{2}"):
    keywords = [keyword for keyword in ("Plot", "Enlist", "Outlast")
                if any(line.split(" ", 1)[0].rstrip(",") == keyword for line in text.splitlines())]
    card = Card(keywords=keywords, id=name, name=name, type_line="Creature — Human", oracle_text=text,
                is_creature=True, power=power, toughness=3, mana_cost_string=cost)
    assert parse_oracle(card).modeled
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND if hand else Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    if hand:
        player.hand.append(obj)
    else:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    return obj


def test_plot_pays_and_triggers_from_exile_then_casts_on_a_later_turn():
    engine, player = _game()
    obj = _card(engine, player, "Plot Creature",
                "When this card becomes plotted, you gain 2 life.\nPlot {G}", hand=True)
    assert not any(a["type"] == "plot" for a in engine.legal_actions(player))
    player.mana_pool.add("G", 1)
    assert any(a["type"] == "plot" for a in engine.legal_actions(player))
    engine.state.current_step = "begin_combat"
    with pytest.raises(ValueError):
        engine.plot(player, obj)
    engine.state.current_step = "main1"
    life = player.life
    engine.plot(player, obj)
    assert obj in player.exile and obj.plotted_card
    assert not engine.state.stack
    assert player.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert player.life == life + 2
    assert not engine.can_cast(player, obj)
    engine.state.internal_turn.number += 1
    engine.state.current_step = "main1"
    assert engine.can_cast(player, obj)
    engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    assert obj in engine.state.battlefield
    assert not obj.plotted_card


def test_enlist_rejects_attackers_and_sick_creatures_then_reads_power_at_resolution():
    engine, player = _game("declare_attackers")
    attacker = _card(engine, player, "Enlisting Creature",
                     "Enlist\nWhenever this creature enlists a creature, you gain 2 life.")
    helper = _card(engine, player, "Helper", power=3)
    helper.summoning_sick = True
    declaration = {"attacker": attacker, "enlist": [helper]}
    with pytest.raises(ValueError):
        engine.declare_attackers(player, [declaration])
    helper.summoning_sick = False
    with pytest.raises(ValueError):
        engine.declare_attackers(player, [declaration, helper])
    assert not attacker.tapped and not helper.tapped
    life = player.life
    engine.declare_attackers(player, [declaration])
    assert helper.tapped and not helper.attacking
    assert attacker.power == 2
    helper.add_counters("+1/+1", 1)
    engine.resolve_until_stable()
    assert attacker.power == 6
    assert player.life == life + 2


def test_outlast_pays_taps_and_fires_a_self_scoped_activation_trigger():
    engine, player = _game()
    herald = _card(engine, player, "Herald of Anafenza",
                   "Outlast {2}{W}\nWhenever you activate this creature's outlast ability, "
                   "create a 1/1 white Warrior creature token.")
    other = _card(engine, player, "Other Outlast Creature", "Outlast {W}")
    player.mana_pool.add("W", 2)
    player.mana_pool.add("C", 2)
    herald.summoning_sick = True
    with pytest.raises(ValueError):
        engine.activate_ability(player, herald, 0)
    herald.summoning_sick = False
    engine.state.current_step = "begin_combat"
    with pytest.raises(ValueError):
        engine.activate_ability(player, herald, 0)
    engine.state.current_step = "main1"
    engine.activate_ability(player, other, 0)
    engine.resolve_until_stable()
    assert not any(obj.is_token for obj in engine.state.battlefield)
    engine.activate_ability(player, herald, 0)
    assert herald.tapped and not herald.counters
    assert player.mana_pool.total() == 0
    assert any(event.type == EventType.ACTIVATED_ABILITY and event.get("ability_keyword") == "outlast"
               for event in engine.state.event_log)
    engine.resolve_until_stable()
    assert herald.counters["+1/+1"] == 1
    assert sum(obj.is_token for obj in engine.state.battlefield) == 1


def test_enlist_instances_each_use_a_distinct_helper_and_track_previous_visit():
    engine, player = _game("declare_attackers")
    attacker = _card(engine, player, "Enlisting Creature", "Enlist, enlist")
    first = _card(engine, player, "First Helper", power=3)
    second = _card(engine, player, "Second Helper", power=4)
    with pytest.raises(ValueError):
        engine.declare_attackers(player, [{"attacker": attacker, "enlist": [first, first]}])
    engine.declare_attackers(player, [{"attacker": attacker, "enlist": [first, second]}])
    first.add_counters("+1/+1", 1)
    engine.recompute_continuous_effects()
    engine.rules.exile(first)
    engine.resolve_until_stable()
    assert attacker.power == 10


@pytest.mark.parametrize("name", ["Aloe Alchemist", "Longhorn Sharpshooter", "Guardian of New Benalia", "Herald of Anafenza"])
def test_printed_cards_parse(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    assert parse_oracle(card).modeled
