"""Revenant Patriarch — "When this creature enters, if {W} was spent to cast it, target player skips their next
combat phase." is a RULE 603.4 intervening-if: checked when the permanent enters (no trigger, hence no target to
choose, when white was not spent) and again as it resolves. What was spent to cast is history, so the second check
is the first under last-known information; it is therefore made once, at trigger time, and not re-read off a source
that may have left the battlefield by then (a new object, RULE 400.7, with nothing spent).

Reference: parser/oracle/segmenter.py (`_etb_intervening_if`), game/binding/core.py (``trigger["active_if"]``).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

TEXT = ("When this creature enters, if {W} was spent to cast it, target player skips their next combat phase.\n"
        "This creature can't block.")


def _patriarch():
    return Card(id="rp", name="Revenant Patriarch", type_line="Creature — Spirit", oracle_text=TEXT,
                is_creature=True, power=3, toughness=3)


def _enter(spent):
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(_patriarch(), owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    obj.mana_by_color_spent_to_cast = dict(spent)
    bind_from_catalogue(obj)
    eng.rules._put_searched_card(eng.state.player_by_id("p1"), obj, "battlefield")
    return eng, obj


def test_parses_as_a_trigger_time_condition_with_no_second_per_effect_gate():
    result = parse_oracle(_patriarch())
    assert result.modeled
    [trigger] = [s for s in result.specs if getattr(s, "trigger", None)]
    assert trigger.trigger["active_if"] == {"kind": "mana_color_spent_to_cast_at_least", "color": "W", "amount": 1}
    assert all(e.condition is None for e in trigger.effects)


def test_without_white_it_does_not_trigger_at_all():
    eng, _ = _enter({"B": 1, "G": 4})
    assert eng.rules.put_triggers_on_stack() == 0
    assert not eng.state.stack and eng.state.pending_choice is None


def test_with_white_it_triggers_and_the_target_player_skips_combat():
    eng, obj = _enter({"B": 1, "W": 1, "G": 3})
    assert eng.rules.put_triggers_on_stack() == 1
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # white was spent: a target is asked for
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    assert eng.rules.should_skip_step(eng.state.player_by_id("p2"), "combat")
    assert not eng.rules.should_skip_step(eng.state.player_by_id("p1"), "combat")
