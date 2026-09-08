"""PAR-14: RULE 603.2's once-per-turn trigger limiter, in both printed
spellings — the trailing sentence ("…put a +1/+1 counter on this creature.
**This ability triggers only once each turn.**", Chance-Met Elves/Prudent
Fateseer-shaped) and the in-condition one ("whenever you surveil **for the
first time each turn**", Whispering Snitch-shaped).

The underlying mechanism (`TriggeredAbility.once_per_turn`/
`_last_triggered_turn`, RULE 603.2) already existed — built for Dionus,
Elvish Archdruid's *granted* ability — so this ticket is pure parser wiring:
`catalogue.handlers.TRIGGER_ONCE_PER_TURN_MARKER` (a trailing-sentence
marker `segmenter.segment_line` strips out of the parsed body) and
`segmenter._ONCE_PER_TURN_CONDITION_SUFFIX_RE` (stripped off the trigger
*condition* text before any subject-family dispatch, so every trigger
family picks it up for free), both folding into the same
`AbilitySpec.trigger["limit"]` flag `effect_binder.bind_ability` reads as
`TriggeredAbility(once_per_turn=...)`.

Reference: mtg_analyzer/parser/oracle/{segmenter,catalogue/handlers}.py,
mtg_analyzer/game/binding/core.py, mtg_analyzer/game/effects/core.py
(`TriggeredAbility.check_trigger`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _seg(line):
    return segment_line(line, allow_spell_effect=False, provenance=ParserProvenance(version="test", source="test"))


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


# ---------------------------------------------------------------------------
# PARSER: the trailing-sentence marker
# ---------------------------------------------------------------------------


def test_trailing_once_per_turn_sentence_sets_the_limit_flag():
    seg = _seg("whenever you scry, put a +1/+1 counter on ~. this ability triggers only once each turn.")
    assert seg.claimed
    assert seg.spec.trigger.get("limit") is True
    assert [e.type for e in seg.spec.effects] == ["add_counters"]


def test_without_the_trailing_sentence_no_limit_flag_is_set():
    seg = _seg("whenever you scry, put a +1/+1 counter on ~.")
    assert seg.claimed
    assert "limit" not in seg.spec.trigger


# ---------------------------------------------------------------------------
# PARSER: the inline "for the first time each turn" condition suffix
# ---------------------------------------------------------------------------


def test_for_the_first_time_each_turn_sets_the_limit_flag_on_a_player_trigger():
    seg = _seg("whenever you surveil for the first time each turn, ~ deals 1 damage to each opponent.")
    assert seg.claimed
    assert seg.spec.trigger.get("limit") is True
    assert seg.spec.trigger["event"] == "SURVEIL"


def test_for_the_first_time_each_turn_sets_the_limit_flag_on_a_self_subject_trigger():
    seg = _seg("whenever ~ attacks for the first time each turn, draw a card.")
    assert seg.claimed
    assert seg.spec.trigger.get("limit") is True
    assert seg.spec.trigger["condition"] == {"subject": "self"}


def test_without_the_suffix_no_limit_flag_is_set():
    seg = _seg("whenever you surveil, ~ deals 1 damage to each opponent.")
    assert seg.claimed
    assert "limit" not in seg.spec.trigger


# ---------------------------------------------------------------------------
# END TO END: both real cache cards named in the ticket
# ---------------------------------------------------------------------------


def test_chance_met_elves_shaped_card_is_fully_modeled():
    card = Card(
        id="Test Chance-Met Elves", name="Test Chance-Met Elves", type_line="Creature — Elf",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you scry, put a +1/+1 counter on this creature. "
                    "This ability triggers only once each turn.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_whispering_snitch_shaped_card_is_fully_modeled():
    card = Card(
        id="Test Whispering Snitch", name="Test Whispering Snitch", type_line="Creature — Rat",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you surveil for the first time each turn, this creature deals "
                    "1 damage to each opponent and you gain 1 life.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: the limiter actually limits (once per turn, not once per firing)
# ---------------------------------------------------------------------------


def _chance_met_elves_obj(p1):
    card = Card(
        id="Test Chance-Met Elves 2", name="Test Chance-Met Elves 2", type_line="Creature — Elf",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you scry, put a +1/+1 counter on this creature. "
                    "This ability triggers only once each turn.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    ability = obj.triggered_abilities[0]
    assert ability.once_per_turn is True
    p1.hand.clear()
    return obj, ability


def test_scrying_twice_in_one_turn_only_adds_one_counter():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng = _engine()
    p1 = eng.state.players[0]
    obj, ability = _chance_met_elves_obj(p1)
    eng.state.add_to_battlefield(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"

    event = GameEvent(EventType.SCRY, player_id="p1")
    assert ability.check_trigger(event, eng.rules.context) is True
    assert ability.check_trigger(event, eng.rules.context) is False  # same turn, already fired


def test_the_limiter_resets_next_turn():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng = _engine()
    p1 = eng.state.players[0]
    obj, ability = _chance_met_elves_obj(p1)
    eng.state.add_to_battlefield(obj)
    eng.begin_turn()  # turn 1
    eng.state.current_step = "main1"

    event = GameEvent(EventType.SCRY, player_id="p1")
    assert ability.check_trigger(event, eng.rules.context) is True

    eng.begin_turn()  # turn 2
    assert ability.check_trigger(event, eng.rules.context) is True
