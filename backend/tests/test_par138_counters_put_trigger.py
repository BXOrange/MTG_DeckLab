"""PAR-138 — "Whenever 1 or more +1/+1 counters are put on `<subject>`" trigger head.

`RulesEngine.add_counters` already fired `EventType.COUNTER` after the counters landed (Flourishing
Defenses, Hapatra, Danny Pink consume it); the parser had no head for it. The head
(`object_trigger_head._parse_counters_put_head`) names the *recipient* as the event's subject: `~`, or a
group phrase with its controller scope; the counter kind is an exact event filter; "for the first time each
turn" / "this ability triggers only once each turn" are a once-per-turn limit.

Reference: parser/oracle/catalogue/object_trigger_head.py, game/rules/mana_counters_mixin.py
(`add_counters`), game/binding/core.py (``_SUBJECT_EVENT_KEYS["COUNTER"]``).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, oracle_text="", type_line="Creature — Bear", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=True,
                power=2, toughness=2, converted_mana_cost=2, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _put(eng, obj, kind="+1/+1", amount=1):
    eng.rules.add_counters(obj, amount, kind)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


def _tokens(eng, name):
    return [o for o in eng.state.battlefield if o.name == name]


# --- parse -----------------------------------------------------------------


def test_head_shapes():
    head = parse_object_trigger_head("1 or more +1/+1 counters are put on ~")
    assert (head.event, head.condition, head.trigger) == ("COUNTER", {"subject": "self"}, {"filter": {"kind": "+1/+1"}})
    head = parse_object_trigger_head("a +1/+1 counter is put on ~")
    assert head.trigger == {"filter": {"kind": "+1/+1"}}
    head = parse_object_trigger_head("1 or more +1/+1 counters are put on another creature you control")
    assert head.condition["subject"] == "group" and head.condition["other"] is True
    assert head.condition["controller"] == "you"
    head = parse_object_trigger_head("1 or more +1/+1 counters are put on ~ for the first time each turn")
    assert head.trigger["limit"] is True
    head = parse_object_trigger_head("1 or more counters are put on ~")
    assert "filter" not in head.trigger  # any kind


def test_a_heads_not_in_the_grammar_stays_unclaimed():
    assert parse_object_trigger_head("the fourth plan counter is put on ~") is None  # ordinal state trigger
    assert parse_object_trigger_head("1 or more +1/+1 counters are put on ~ or another creature") is None


def test_real_cards_are_modeled():
    for name, text in {
        "Scurry Oak": "Evolve\nWhenever 1 or more +1/+1 counters are put on this creature, you may create a 1/1 "
                      "green Squirrel creature token.",
        "Enduring Scalelord": "Flying\nWhenever 1 or more +1/+1 counters are put on another creature you control, "
                              "you may put a +1/+1 counter on this creature.",
    }.items():
        assert parse_oracle(_card(name, text)).modeled, name


# --- execute ---------------------------------------------------------------

SQUIRREL = ("Whenever 1 or more +1/+1 counters are put on this creature, create a 1/1 green Squirrel creature "
            "token.")


def test_self_trigger_fires_only_for_counters_on_itself_and_only_of_that_kind():
    eng = _engine()
    oak = _bf(eng, _card("Oak", SQUIRREL))
    other = _bf(eng, _card("Other"))
    _put(eng, other)
    assert not any(o.name == "Squirrel" for o in eng.state.battlefield)  # counters on someone else
    _put(eng, oak, kind="-1/-1")
    assert not any(o.name == "Squirrel" for o in eng.state.battlefield)  # wrong kind
    _put(eng, oak, amount=2)
    assert len([o for o in eng.state.battlefield if o.name == "Squirrel"]) == 1  # 2 counters at once: one trigger


def test_another_creature_you_control_excludes_itself_and_the_opponents():
    eng = _engine()
    lord = _bf(eng, _card("Scalelord", "Whenever 1 or more +1/+1 counters are put on another creature you "
                                       "control, put a +1/+1 counter on this creature."))
    mine = _bf(eng, _card("Mine"))
    theirs = _bf(eng, _card("Theirs"), controller="p2")
    base = lord.plus_one_counters
    _put(eng, lord)  # on itself: "another" excludes it
    assert lord.plus_one_counters == base + 1
    _put(eng, theirs)
    assert lord.plus_one_counters == base + 1
    _put(eng, mine)
    assert lord.plus_one_counters == base + 2  # reacts to a creature of its controller


def test_that_much_reads_the_number_of_counters_placed():
    eng = _engine()
    _bf(eng, _card("Shalai", "Whenever 1 or more +1/+1 counters are put on a creature you control, this "
                              "creature deals that much damage to target opponent."))
    mine = _bf(eng, _card("Mine"))
    _put(eng, mine, amount=3)
    assert eng.state.pending_choice["kind"] == "trigger_target"  # "target opponent" is asked for
    eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 20 - 3


def test_first_time_each_turn_is_a_once_per_turn_limit():
    eng = _engine()
    artisan = _bf(eng, _card("Artisan", "Whenever 1 or more +1/+1 counters are put on this creature for the "
                                        "first time each turn, create a Treasure token."))
    _put(eng, artisan)
    _put(eng, artisan)
    assert len([o for o in eng.state.battlefield if o.name == "Treasure"]) == 1
