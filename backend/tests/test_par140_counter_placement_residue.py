"""PAR-140: the counter-placement residue MEC-108 turned up.

(A) "put a `<kind>` counter on **a** creature you control" — a non-targeted pick;
(B) "if ~ doesn't have a `<kind>` counter on it" / "…without a `<kind>` counter on it";
(C) "it becomes a `<type>` in addition to its other types" after a put/return clause;
(D) "you may remove a `<kind>` counter from it. When you do, …" — a counter paid off the source.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec

CREATURE_GROUP = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _card(name: str = "Bear", text: str = "", type_line: str = "Creature — Bear") -> Card:
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=creature,
        is_sorcery=type_line.startswith("Sorcery"), is_instant=type_line.startswith("Instant"),
        is_land="Land" in type_line,
        power=2 if creature else None, toughness=2 if creature else None, oracle_text=text,
    )


def _put(eng: GameEngine, card: Card, owner: str = "p1", bind: bool = False) -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _fire_enters(eng: GameEngine, obj: GameObject) -> None:
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id,
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    eng.rules.put_triggers_on_stack()


# ---------------------------------------------------------------------------
# (A) a counter on "a creature you control"
# ---------------------------------------------------------------------------


def test_counter_on_a_creature_you_control_parses_as_a_pick_not_a_target():
    assert match_clause("put a menace counter on a creature you control") == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "menace", "group": CREATURE_GROUP, "choose_one": True,
        })
    ]


def test_another_becomes_the_groups_other_and_minus_counters_keep_their_kind():
    [spec] = match_clause("put a -1/-1 counter on another creature you control")
    assert spec.params["kind"] == "-1/-1" and spec.params["group"]["filter"]["not_reference"] is True
    [spec] = match_clause("put 2 +1/+1 counters on an artifact you control")
    assert spec.params["count"] == 2 and spec.params["group"]["filter"] == {"card_type": "artifact"}


def test_counter_pick_does_not_claim_a_target_or_an_opponents_permanent():
    assert match_clause("put a menace counter on a creature an opponent controls") is None
    [spec] = match_clause("put a menace counter on target creature you control")
    assert "choose_one" not in spec.params and spec.params["target_kind"] == "creature_you_control"


def test_blood_curdle_is_modeled():
    card = _card("Blood Curdle", "Destroy target creature. Put a menace counter on a creature you control.",
                 "Instant")
    assert parse_oracle(card).coverage is MODELED


def _pick_counter_source(eng: GameEngine, clause: str) -> GameObject:
    return _put(eng, _card("Curator", f"When ~ enters, {clause}"), bind=True)


def test_a_pick_among_several_creatures_asks_and_places_on_the_choice():
    eng = _engine()
    a = _put(eng, _card("A"))
    b = _put(eng, _card("B"))
    src = _pick_counter_source(eng, "put a menace counter on another creature you control.")
    _fire_enters(eng, src)
    eng.rules.resolve_top_of_stack()
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "counter_recipient"
    assert {o["instance_id"] for o in choice["options"]} == {a.instance_id, b.instance_id}  # not ~ itself
    eng.resolve_pending_choice(str(b.instance_id))
    eng.recompute_continuous_effects()
    assert b.counters == {"menace": 1} and not a.counters and not src.counters
    assert combat.has_menace(b)


def test_a_single_eligible_creature_is_taken_without_asking():
    eng = _engine()
    only = _put(eng, _card("Only"))
    src = _pick_counter_source(eng, "put a +1/+1 counter on another creature you control.")
    _fire_enters(eng, src)
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice is None
    assert only.plus_one_counters == 1


def test_no_eligible_creature_does_nothing_and_opponents_creatures_are_never_offered():
    eng = _engine()
    _put(eng, _card("Theirs"), owner="p2")
    src = _pick_counter_source(eng, "put a +1/+1 counter on another creature you control.")
    _fire_enters(eng, src)
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice is None and not src.counters


def test_a_bad_recipient_answer_falls_back_to_the_first_eligible_creature():
    eng = _engine()
    a = _put(eng, _card("A"))
    _put(eng, _card("B"))
    src = _pick_counter_source(eng, "put a flying counter on another creature you control.")
    _fire_enters(eng, src)
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("999999")
    assert a.counters == {"flying": 1}


# ---------------------------------------------------------------------------
# (B) "doesn't have a <kind> counter on it" / "without a <kind> counter on it"
# ---------------------------------------------------------------------------


def test_negated_counter_conditions_parse_as_max_zero():
    card = _card("Wing", "At the beginning of your end step, if ~ doesn't have a flying counter on it, "
                         "put a flying counter on it.")
    result = parse_oracle(card)
    assert result.coverage is MODELED
    [spec] = [s for s in result.effect_specs if s.ability_kind == "triggered"]
    assert spec.effects[0].condition == {"kind": "source_counters", "counter": "flying", "max": 0}


@pytest.mark.parametrize("clause,expected", [
    ("if ~ has no +1/+1 counters on it", {"kind": "source_counters", "max": 0, "counter": "+1/+1"}),
    ("if ~ has no counters on it", {"kind": "source_counters", "max": 0}),
    ("if it doesn't have a +1/+1 counter on it", {"kind": "source_counters", "counter": "+1/+1", "max": 0}),
])
def test_negated_counter_condition_forms(clause, expected):
    card = _card("Holder", f"At the beginning of your end step, {clause}, draw a card.")
    [spec] = [s for s in parse_oracle(card).effect_specs if s.ability_kind == "triggered"]
    assert spec.effects[0].condition == expected


def test_the_negated_condition_gates_the_effect():
    eng = _engine()
    card = _card("Wing", "At the beginning of your end step, if ~ doesn't have a flying counter on it, "
                         "put a flying counter on it.")
    obj = _put(eng, card, bind=True)
    for _ in range(2):  # the second end step must do nothing: it now has the counter
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()
    assert obj.counters == {"flying": 1}


def test_without_a_counter_is_a_group_filter():
    assert parse_object_phrase("creatures without a +1/+1 counter on them", plural=True) == (
        {"card_type": "creature", "without_counter_kind": "+1/+1"}, None,
    )
    assert parse_object_phrase("creatures you control without counters on them", plural=True) == (
        {"card_type": "creature", "no_counters": True}, "you",
    )
    # the "with" qualifier learned the two-word kinds too
    assert parse_object_phrase("creatures with a first strike counter on them", plural=True) == (
        {"card_type": "creature", "has_counter_kind": "first strike"}, None,
    )


def test_a_mass_clause_with_a_plus_one_counter_filter_now_parses():
    [spec] = match_clause("return each creature without a +1/+1 counter on it to its owner's hand")
    assert spec.type == "return_to_hand"
    assert spec.params["group"]["filter"] == {"card_type": "creature", "without_counter_kind": "+1/+1"}


def test_wave_goodbye_returns_only_the_counterless_creatures():
    eng = _engine()
    plain = _put(eng, _card("Plain"))
    grown = _put(eng, _card("Grown"), owner="p2")
    eng.rules.add_counters(grown, 1, "+1/+1")
    spell = GameObject(
        _card("Wave Goodbye", "Return each creature without a +1/+1 counter on it to its owner's hand.",
              "Sorcery"),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    eng.state.players[0].hand.append(spell)
    eng.state.players[0].mana_pool.add_many({"C": 4})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.state.players[0].mana_pool.add_many({"C": 4})
    eng.cast_spell(eng.state.players[0], spell)
    eng.resolve_until_stable()
    assert plain not in eng.state.battlefield and plain in eng.state.players[0].hand
    assert grown in eng.state.battlefield


def test_object_filter_without_counter_kind_matches_only_counterless_objects():
    eng = _engine()
    bare = _put(eng, _card("Bare"))
    marked = _put(eng, _card("Marked"))
    eng.rules.add_counters(marked, 1, "flying")
    filt = {"without_counter_kind": "flying"}
    assert combat.matches_object_filter(bare, filt, state=eng.state)
    assert not combat.matches_object_filter(marked, filt, state=eng.state)


# ---------------------------------------------------------------------------
# (C) "it becomes a <type> in addition to its other types"
# ---------------------------------------------------------------------------


def test_becomes_in_addition_after_a_put_reads_the_previous_pick():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [put, become] = parse_effect_body(
        "put a menace counter on another target creature. it becomes a rogue in addition to its other types."
    )
    assert put.type == "add_counters" and put.params["target_kind"] == "creature"
    assert become == EffectSpec("grant_until", {
        "duration": "rest_of_game", "previous_subject": True, "target_kind": None,
        "static": {"type": "type_change", "params": {"add_subtypes": ["Rogue"]}},
    })


def test_becomes_in_addition_forms():
    [spec] = match_clause("target creature becomes an artifact in addition to its other types until end of turn")
    assert spec.params["duration"] == "end_of_turn"
    assert spec.params["static"]["params"] == {"add_types": ["artifact"]}
    assert spec.params["target_kind"] == "creature"
    [spec] = match_clause("~ becomes an assassin in addition to its other types until end of turn")
    assert spec.params["self_subject"] is True
    [spec] = match_clause("target land becomes an island in addition to its other types")
    assert spec.params["static"]["params"] == {"add_subtypes": ["Island"]}
    assert spec.params["duration"] == "rest_of_game"


def test_becomes_in_addition_fails_closed():
    assert match_clause("target creature becomes a banana in addition to its other types") is None
    # a bare pronoun with no previous pick is not offered
    assert match_clause("it becomes a rogue in addition to its other types") is None
    # a new P/T or ability is a different (animation) clause
    assert match_clause("target creature becomes a 3/3 angel in addition to its other types") is None


def test_the_rider_adds_the_subtype_to_the_creature_that_got_the_counter():
    eng = _engine()
    ally = _put(eng, _card("Ally"))
    src = _put(eng, _card(
        "Corrupter",
        "When ~ enters, put a menace counter on target creature you control. "
        "It becomes a Rogue in addition to its other types.",
    ), bind=True)
    _fire_enters(eng, src)
    choice = eng.state.pending_choice
    if choice:
        picked = [o for o in choice["options"] if o.get("instance_id") == ally.instance_id]
        eng.resolve_pending_choice((picked or choice["options"])[0]["id"])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    receivers = [o for o in (ally, src) if o.counters.get("menace")]
    assert len(receivers) == 1
    receiver = receivers[0]
    other = ally if receiver is src else src
    assert continuous.has_subtype(receiver, "Rogue")  # the creature that got the counter...
    assert not continuous.has_subtype(other, "Rogue")  # ...and only that one
    assert continuous.has_subtype(receiver, "Bear") or receiver is src  # "in addition to" keeps the rest


def test_until_end_of_turn_type_addition_is_removed_at_cleanup():
    eng = _engine()
    wand = _put(eng, _card("Wand", "{T}: Target land becomes an artifact in addition to its other types "
                                    "until end of turn.", "Artifact"), bind=True)
    land = _put(eng, _card("Forest", "", "Basic Land — Forest"))
    assert "artifact" not in land.type_words
    effect = wand.activated_abilities[0].effects[0]
    effect.apply(eng.rules.context, [land])
    eng.recompute_continuous_effects()
    assert "artifact" in land.type_words
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert "artifact" not in land.type_words


# ---------------------------------------------------------------------------
# (D) "you may remove a <kind> counter from it. When you do, …"
# ---------------------------------------------------------------------------


def test_remove_a_counter_then_reflexive_parses_as_pay_cost_then():
    [spec] = match_clause(
        "you may remove a menace counter from ~. when you do, exile target artifact or enchantment that "
        "player controls"
    ) or [None]
    assert spec is not None and spec.type == "pay_cost_then"
    assert spec.params["cost"] == "remove a menace counter from ~"
    assert spec.params["then_trigger"][0]["type"] == "exile"


def test_remove_a_counter_if_you_do_parses_with_an_effect_branch():
    [spec] = match_clause("you may remove a +1/+1 counter from ~. if you do, draw a card")
    assert spec.type == "pay_cost_then" and spec.params["effects"][0]["type"] == "draw"


def test_kappa_tech_wrecker_is_modeled():
    card = _card(
        "Kappa Tech-Wrecker",
        "Whenever ~ deals combat damage to a player, you may remove a deathtouch counter from it. "
        "When you do, exile target artifact or enchantment that player controls.",
    )
    assert parse_oracle(card).coverage is MODELED


def _upkeep(eng: GameEngine) -> None:
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


DRAW_ON_REMOVE = (
    "At the beginning of each upkeep, you may remove a charge counter from ~. If you do, you gain 1 life."
)


def test_paying_by_removing_a_counter_takes_it_off_the_source_and_runs_the_effect():
    eng = _engine()
    obj = _put(eng, _card("Droplet", DRAW_ON_REMOVE, "Artifact"), bind=True)
    eng.rules.add_counters(obj, 2, "charge")
    _upkeep(eng)
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    assert obj.counters == {"charge": 1}
    assert eng.state.player_by_id("p1").life == 21


def test_declining_keeps_the_counter_and_does_nothing():
    eng = _engine()
    obj = _put(eng, _card("Droplet", DRAW_ON_REMOVE, "Artifact"), bind=True)
    eng.rules.add_counters(obj, 1, "charge")
    _upkeep(eng)
    eng.resolve_pending_choice("decline")
    assert obj.counters == {"charge": 1} and eng.state.player_by_id("p1").life == 20


def test_with_no_counter_to_remove_the_player_is_never_asked():
    eng = _engine()
    obj = _put(eng, _card("Droplet", DRAW_ON_REMOVE, "Artifact"), bind=True)
    _upkeep(eng)
    assert eng.state.pending_choice is None
    assert not obj.counters and eng.state.player_by_id("p1").life == 20


def test_the_wrong_kind_of_counter_does_not_pay():
    eng = _engine()
    obj = _put(eng, _card("Droplet", DRAW_ON_REMOVE, "Artifact"), bind=True)
    eng.rules.add_counters(obj, 3, "oil")
    _upkeep(eng)
    assert eng.state.pending_choice is None and obj.counters == {"oil": 3}


def test_a_group_trigger_it_is_not_read_as_the_source_that_pays():
    # "it" is the dying creature there, not the permanent with the trigger.
    assert match_clause(
        "you may remove a menace counter from it. when you do, draw a card", group_subject=True
    ) is None
