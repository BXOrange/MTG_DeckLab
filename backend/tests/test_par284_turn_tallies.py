"""PAR-284 milestone 18: turn-history tallies read off the event log.

"the number of times you descended this turn" (RULE 700.11), "for each card type among spells you've cast this turn"
(RULE 601.2i), "for each spell you've cast this turn other than the first", "for each +1/+1 counter you've put on
creatures under your control this turn" (RULE 122.1) and "for each 1 life your opponents have lost this turn"
(RULE 119.3). Each is resolved against a real engine's turn log; the log events they read are fired by the engine
itself where a rule action produces them (death, counters, life loss) and stamped where the engine records only the cast.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_turn_history_counts import _creature, _engine, _library, _spell


def _resolve(eng, oracle):
    spell = _spell(eng, oracle)
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 1})
    before = len(p1.hand)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    return len(p1.hand) - (before - 1)  # cards gained net of the spell leaving the hand


def test_times_descended_counts_each_permanent_card_put_into_your_graveyard():
    eng = _engine()
    _library(eng)
    for i in range(2):
        eng.rules.destroy(_creature(eng, f"Mine{i}", owner="p1"))
    eng.rules.destroy(_creature(eng, "Theirs", owner="p2"))  # not your graveyard
    assert eng.state.times_descended_this_turn["p1"] == 2
    assert _resolve(eng, "Draw X cards, where X is the number of times you descended this turn.") == 2


def test_card_types_among_spells_cast_this_turn_is_a_union():
    eng = _engine()
    _library(eng)
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", colors=[], object_types=["artifact", "creature"]))
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", colors=[], object_types=["creature"]))
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", colors=[], object_types=["land"]))
    # the probe sorcery itself is cast too, so its type joins the union: artifact, creature, sorcery
    assert _resolve(eng, "Draw a card for each card type among spells you've cast this turn.") == 3


def test_other_than_the_first_floors_at_zero_and_precedes_the_multiplier():
    eng = _engine()
    specs = parse_effect_body("put 2 +1/+1 counters on it for each spell you've cast this turn other than the first.")
    amount = specs[0].params["amount"]
    assert amount["exclude_first"] is True and amount["multiply"] == 2
    from mtg_analyzer.game.effect_amounts import amount_of
    from types import SimpleNamespace

    context = SimpleNamespace(state=eng.state, controller_id="p1", trigger_event=None)
    source = _creature(eng, "Stitcher")
    assert amount_of(amount, context, source, []) == 0  # no spell cast yet: floor, not -2
    for _ in range(3):
        eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", colors=[], object_types=["instant"]))
    assert amount_of(amount, context, source, []) == 4  # (3 - 1) * 2, not 3 * 2 - 1


def test_counters_put_on_your_creatures_sum_their_amounts():
    eng = _engine()
    _library(eng)
    mine, theirs = _creature(eng, "Mine"), _creature(eng, "Theirs", owner="p2")
    eng.rules.add_counters(mine, 2, "+1/+1", source=mine)
    eng.rules.add_counters(mine, 1, "+1/+1", source=mine)
    eng.rules.add_counters(mine, 4, "-1/-1", source=mine)  # a different kind
    eng.rules.add_counters(theirs, 5, "+1/+1", source=mine)  # not a creature under your control
    eng.rules.add_counters(mine, 3, "+1/+1", source=theirs)  # put by an opponent's source
    assert _resolve(eng, "Draw a card for each +1/+1 counter you've put on creatures under your control this turn.") == 3


def test_opponents_life_lost_feeds_mana():
    eng = _engine()
    from mtg_analyzer.game.continuous import count_selector

    specs = parse_effect_body("add {r} for each 1 life your opponents have lost this turn.")
    selector = specs[0].params["amount"]["selector"]
    assert selector == "opponents_life_lost_this_turn"
    eng.rules.lose_life(eng.state.players[1], 3)
    eng.rules.lose_life(eng.state.players[0], 2)  # your own loss is not an opponent's
    assert count_selector(eng.state, "p1", selector) == 3


@pytest.mark.parametrize("name, type_line, oracle", [
    ("The Mycotyrant", "Legendary Creature — Elder Fungus",
     'At the beginning of your end step, create X 1/1 black Fungus creature tokens with "This creature can\'t block," '
     "where X is the number of times you descended this turn."),
    ("April O'Neil, Hacktivist", "Legendary Creature — Human Scientist",
     "At the beginning of your end step, draw a card for each card type among spells you've cast this turn."),
    ("Iridescent Hornbeetle", "Creature — Insect",
     "At the beginning of your end step, create a 1/1 green Insect creature token for each +1/+1 counter you've put on "
     "creatures under your control this turn."),
    ("Neheb, the Eternal", "Legendary Creature — Zombie Minotaur Warrior",
     "At the beginning of each of your postcombat main phases, add {R} for each 1 life your opponents have lost this turn."),
    ("Outlaw Stitcher", "Creature — Human Warlock",
     "When ~ enters, create a 2/2 blue and black Zombie Rogue creature token, then put 2 +1/+1 counters on that token for "
     "each spell you've cast this turn other than the first."),
])
def test_real_cards_are_modeled(name, type_line, oracle):
    from tests.test_par284_this_way_windows import _card

    result = parse_oracle(_card(name, type_line, oracle, is_creature=True, power=2, toughness=2))
    assert result.modeled, (name, result.unclaimed)
