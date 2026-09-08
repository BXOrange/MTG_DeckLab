"""Named (non-P/T) counter kinds for the plain "put a `<kind>` counter on X"
shape (RULE 122.1) — the `_add_counters` P/T-only row's sibling.
`AddCountersEffect.kind` was already a free string; only "spore" recognition
was missing (Deathspore Thallid/Elvish Farmer/Feral Thallid-shaped).

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_put_a_spore_counter_on_self_parses():
    assert match_clause("put a spore counter on ~") == [
        EffectSpec("add_counters", {"count": 1, "kind": "spore"})
    ]


def test_put_a_spore_counter_on_target_fungus_stays_unclaimed():
    # "target fungus" isn't a `TARGET` row this grammar recognises (a
    # creature-subtype-scoped target, a different, still-open gap) — fail
    # closed rather than dropping the subtype filter.
    assert match_clause("put a spore counter on target fungus") is None


def test_deathspore_thallid_full_card_is_modeled():
    card = Card(
        id="Deathspore Thallid", name="Deathspore Thallid", type_line="Creature — Fungus",
        is_creature=True, power=0, toughness=1,
        oracle_text=(
            "At the beginning of your upkeep, put a spore counter on this creature.\n"
            "Remove three spore counters from this creature: Create a 1/1 green "
            "Saproling creature token.\n"
            "Sacrifice a Saproling: Target creature gets -1/-1 until end of turn."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled


def test_spore_counter_trigger_executes():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    card = Card(
        id="Test Thallid", name="Test Thallid", type_line="Creature — Fungus",
        is_creature=True, power=0, toughness=1,
        oracle_text="At the beginning of your upkeep, put a spore counter on this creature.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    from mtg_analyzer.models.game.events import EventType, GameEvent
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert obj.counters.get("spore", 0) == 1
