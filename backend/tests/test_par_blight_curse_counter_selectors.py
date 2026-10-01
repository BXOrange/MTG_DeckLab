"""Blight Curse — mass -1/-1 counter clauses (RULE 122.1a)."""

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.card_registry import is_registered, specs_for
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _creature(state, name, controller):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature", is_creature=True, power=2, toughness=2),
        owner_id=controller,
        zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    state.add_to_battlefield(obj)
    return obj


def test_mass_counter_selectors_parse_without_claiming_qualified_near_misses():
    assert match_clause("put a -1/-1 counter on each creature") == [
        EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "selector": "each_creature"})
    ]
    assert match_clause("put x -1/-1 counters on each creature") == [
        EffectSpec("add_counters", {"kind": "-1/-1", "selector": "each_creature", "x_multiplier": 1})
    ]
    # A qualified group is no near miss any more: the shared group grammar reads "nonblack" (batch 5,
    # `handlers._ADD_PT_COUNTER_GROUP_RE`) as a structured selector, not a closed named one.
    assert match_clause("put a -1/-1 counter on each nonblack creature") == [
        EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "group": {
            "zone": "battlefield", "of": "any", "filter": {"without_color": "B", "card_type": "creature"},
        }})
    ]
    assert match_clause("put a -1/-1 counter on each creature that was dealt damage this turn") is None


def test_blight_curse_cards_with_plain_mass_counter_clauses_are_modeled():
    black_sun = Card(
        id="zenith", name="Black Sun's Zenith", type_line="Sorcery", is_sorcery=True,
        oracle_text="Put X -1/-1 counters on each creature. Shuffle Black Sun's Zenith into its owner's library.",
    )
    carnifex = Card(
        id="carnifex", name="Carnifex Demon", type_line="Creature", is_creature=True,
        oracle_text="Flying\nThis creature enters with two -1/-1 counters on it.\n{B}, Remove a -1/-1 counter from this creature: Put a -1/-1 counter on each other creature.",
    )
    assert parse_oracle(black_sun).modeled
    assert parse_oracle(carnifex).modeled


def test_each_other_creature_excludes_the_activated_ability_source():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    source = _creature(engine.state, "Carnifex Demon", "p1")
    ally = _creature(engine.state, "Ally", "p1")
    opponent = _creature(engine.state, "Opponent", "p2")
    effect = build_effects([
        EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "selector": "each_other_creature"})
    ], source)[0]

    effect.apply(GameContext(engine.state, engine.rules))

    assert source.counters.get("-1/-1", 0) == 0
    assert ally.counters.get("-1/-1") == 1
    assert opponent.counters.get("-1/-1") == 1


def test_chain_reaction_catalogue_entry_uses_the_live_creature_count():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    first = _creature(engine.state, "First", "p1")
    second = _creature(engine.state, "Second", "p2")
    card = Card(id="chain", name="Chain Reaction", type_line="Sorcery", is_sorcery=True)
    source = GameObject(card, owner_id="p1", zone=Zone.STACK)
    source.controller_id = "p1"

    assert is_registered(card.name)
    effect = build_effects(specs_for(card)[0].effects, source)[0]
    effect.apply(GameContext(engine.state, engine.rules))

    assert first.damage_marked == 2
    assert second.damage_marked == 2
