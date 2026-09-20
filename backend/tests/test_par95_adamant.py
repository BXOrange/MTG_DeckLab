"""PAR-95 — Adamant's per-mana-type cast-payment riders."""

from mtg_analyzer.game.effects.damage_draw import DealDamageEffect
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition


def _card(name: str, text: str) -> Card:
    return Card(id=name, name=name, type_line="Creature — Human", is_creature=True,
                power=2, toughness=2, oracle_text=text)


def test_adamant_entry_counter_requires_the_actual_color_quantity():
    text = "If at least 3 white mana was spent to cast this spell, ~ enters with a +1/+1 counter on it."
    assert entry_counters_condition(text) == {
        "is_x": False, "count": 1, "counter_type": "+1/+1",
        "mana_color_spent_gate": {"color": "W", "amount": 3},
    }
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    obj = GameObject(_card("Adamant Knight", text), owner_id="p1", zone=Zone.HAND)
    obj.mana_by_color_spent_to_cast = {"W": 2}
    engine.rules._apply_entry_counters(obj)
    assert obj.counters == {}
    obj.mana_by_color_spent_to_cast = {"W": 3}
    engine.rules._apply_entry_counters(obj)
    assert obj.counters == {"+1/+1": 1}


def test_adamant_damage_override_is_not_an_additional_hit():
    source = GameObject(_card("Slaying Fire", ""), owner_id="p1", zone=Zone.STACK)
    damage = DealDamageEffect(3, source=source, amount_if_mana_color_spent={
        "color": "R", "threshold": 3, "amount": 4,
    })
    source.mana_by_color_spent_to_cast = {"R": 2}
    assert damage.amount == 3
    source.mana_by_color_spent_to_cast = {"R": 3}
    assert damage.amount == 4


def test_adamant_sundering_override_hits_each_chosen_target_in_full():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    source = GameObject(_card("Sundering Stroke", ""), owner_id="p1", zone=Zone.STACK)
    a = GameObject(_card("A", ""), owner_id="p2", zone=Zone.BATTLEFIELD)
    b = GameObject(_card("B", ""), owner_id="p2", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(a)
    engine.state.add_to_battlefield(b)
    damage = DealDamageEffect(7, source=source, target_kind="any", count=2, divided=True,
                              each_target_if_mana_color_spent={"color": "R", "threshold": 7})
    source.mana_by_color_spent_to_cast = {"R": 7}
    damage.apply(GameContext(engine.state, engine.rules), [a, b])
    assert a.damage_marked == b.damage_marked == 7


def test_adamant_parses_entry_additive_and_override_forms():
    cards = [
        _card("Ardenvale Paladin", "If at least 3 white mana was spent to cast this spell, ~ enters with a +1/+1 counter on it."),
        Card(id="SB", name="Searing Barrage", type_line="Sorcery", is_sorcery=True,
             oracle_text="~ deals 5 damage to target creature.\nIf at least 3 red mana was spent to cast this spell, ~ deals 3 damage to that creature's controller."),
        Card(id="SF", name="Slaying Fire", type_line="Instant", is_instant=True,
             oracle_text="~ deals 3 damage to any target.\nIf at least 3 red mana was spent to cast this spell, it deals 4 damage instead."),
    ]
    results = [parse_oracle(card) for card in cards]
    assert all(result.coverage == MODELED for result in results)
    assert results[2].specs[0].effects[0].params["amount_if_mana_color_spent"] == {
        "color": "R", "threshold": 3, "amount": 4,
    }
