"""RULE 603.1/603.2: coordinated object-event heads retain each event's scope."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _compound_trigger_heads


def _card(head, body="you gain 1 life."):
    return Card(id="Sentinel", name="Sentinel", type_line="Creature — Horse",
                is_creature=True, power=2, toughness=3,
                oracle_text=f"Whenever Sentinel {head}, {body}")


@pytest.mark.parametrize("head,events", [
    ("attacks or becomes the target of a spell an opponent controls", ["ATTACKS", "BECOMES_TARGET"]),
    ("becomes the target of an ability or attacks", ["BECOMES_TARGET", "ATTACKS"]),
    ("attacks, blocks, or becomes the target of a spell or ability an opponent controls",
     ["ATTACKS", "BLOCKS", "BECOMES_TARGET"]),
    ("blocks, attacks, or dies", ["BLOCKS", "ATTACKS", "DIES"]),
    ("enters or deals combat damage to a player", ["ENTERS_BATTLEFIELD", "DAMAGE"]),
])
def test_coordinated_heads_keep_all_events(head, events):
    result = parse_oracle(_card(head))
    assert result.modeled
    assert [s.trigger["event"] for s in result.specs] == events


def test_target_filters_belong_only_to_target_head():
    result = parse_oracle(_card("attacks or becomes the target of a spell an opponent controls"))
    assert result.specs[0].trigger == {"event": "ATTACKS", "condition": {"subject": "self"}}
    assert result.specs[1].trigger == {
        "event": "BECOMES_TARGET", "condition": {"subject": "self"},
        "filter": {"item_kind": "spell"}, "caster_relation": "opponent",
    }


@pytest.mark.parametrize("head", [
    "attacks or becomes the target of a spell an opponent owns",
    "attacks, blocks, or becomes famous",
    "attacks or becomes the target of a spell for the first time each turn",
])
def test_unsupported_or_overlapping_heads_fail_closed(head):
    assert not parse_oracle(_card(head)).modeled


def test_subject_union_is_inherited_whole_and_internal_or_is_preserved():
    assert _compound_trigger_heads(
        "~ or another nontoken artifact you control dies or is put into exile from the battlefield"
    ) == ["~ or another nontoken artifact you control dies",
          "~ or another nontoken artifact you control is put into exile from the battlefield"]
    result = parse_oracle(Card(id="Watcher", name="Watcher", type_line="Enchantment",
        oracle_text="Whenever a Samurai or Warrior you control attacks or becomes the target "
                    "of a spell or ability, you gain 1 life."))
    assert result.modeled
    assert len(result.specs) == 2
    first, second = [s.trigger["condition"] for s in result.specs]
    assert first["subtypes"] == second["filter"]["subtype_any"] == ["samurai", "warrior"]
    assert first["controller"] == second["controller"] == "you"
    assert "caster_relation" not in result.specs[1].trigger


def _engine(card):
    filler = Card(id="Filler", name="Filler", type_line="Creature", is_creature=True,
                  power=2, toughness=2)
    eng = GameEngine.new_game([("p1", "Alice", [filler] * 10),
                              ("p2", "Bob", [filler] * 10)], starting_hand=0)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return eng, obj


def _fire(eng, obj, event, expected, **data):
    eng.state.fire_event(GameEvent(event, instance_id=obj.instance_id, **data))
    assert eng.rules.put_triggers_on_stack() == expected
    if expected:
        eng.rules.resolve_top_of_stack()


def test_bound_attack_block_and_target_heads_execute_independently():
    eng, obj = _engine(_card("attacks, blocks, or becomes the target of a spell an opponent controls"))
    player = eng.state.player_by_id("p1")
    before = player.life
    for event in (EventType.ATTACKS, EventType.BLOCKS):
        _fire(eng, obj, event, 1)
    _fire(eng, obj, EventType.BECOMES_TARGET, 0, controller_id="p1", item_kind="spell")
    _fire(eng, obj, EventType.BECOMES_TARGET, 0, controller_id="p2", item_kind="ability")
    _fire(eng, obj, EventType.BECOMES_TARGET, 1, controller_id="p2", item_kind="spell")
    assert player.life == before + 3


def test_real_shield_mare_is_modeled_and_both_heads_execute():
    card = Card(id="Shield Mare", name="Shield Mare", type_line="Creature — Horse",
        is_creature=True, power=2, toughness=3,
        oracle_text="This creature can't be blocked by red creatures.\n"
                    "When this creature enters or becomes the target of a spell or ability "
                    "an opponent controls, you gain 3 life.")
    assert parse_oracle(card).modeled
    eng, obj = _engine(card)
    player = eng.state.player_by_id("p1")
    before = player.life
    _fire(eng, obj, EventType.ENTERS_BATTLEFIELD, 1)
    _fire(eng, obj, EventType.BECOMES_TARGET, 1, controller_id="p2", item_kind="ability")
    assert player.life == before + 6


def test_modal_body_preserves_every_head_and_its_filter():
    card = _card("attacks or becomes the target of a spell an opponent controls",
                 "choose one —\n• You gain 1 life.\n• Draw a card.")
    result = parse_oracle(card)
    assert result.modeled
    assert [s.trigger["event"] for s in result.specs] == ["ATTACKS", "BECOMES_TARGET"]
    assert result.specs[1].trigger["caster_relation"] == "opponent"
    assert all(len(s.modes["options"]) == 2 for s in result.specs)


def test_compound_splitter_refuses_duplicate_and_cofiring_events():
    assert _compound_trigger_heads("~ attacks or attacks") is None
    assert _compound_trigger_heads("~ dies or leaves the battlefield") is None
    assert _compound_trigger_heads("~ attacks or dies during your turn") is None
    assert _compound_trigger_heads("~ attacks, blocks, or dies during your turn") is None


def test_modal_attack_and_target_heads_both_open_and_resolve_mode_choice():
    card = _card("attacks or becomes the target of a spell an opponent controls",
                 "choose one —\n• You gain 1 life.\n• Draw a card.")
    eng, obj = _engine(card)
    player = eng.state.player_by_id("p1")
    before = player.life
    for event, data in ((EventType.ATTACKS, {}),
                        (EventType.BECOMES_TARGET, {"controller_id": "p2", "item_kind": "spell"})):
        eng.state.fire_event(GameEvent(event, instance_id=obj.instance_id, **data))
        eng.rules.put_triggers_on_stack()
        assert eng.state.pending_choice["kind"] == "trigger_mode"
        eng.rules.resolve_choice("0")
        assert eng.state.pending_choice is None
        assert len(eng.state.stack) == 1
        eng.rules.resolve_top_of_stack()
    assert player.life == before + 2


def test_body_trigger_limit_does_not_become_separate_event_limits():
    card = _card("attacks or becomes the target of a spell",
                 "you gain 1 life. This ability triggers only once each turn.")
    assert not parse_oracle(card).modeled


def test_exhausted_modal_history_does_not_become_separate_event_histories():
    card = _card("attacks or becomes the target of a spell",
                 "choose one that hasn't been chosen this turn —\n• You gain 1 life.\n• Draw a card.")
    assert not parse_oracle(card).modeled
