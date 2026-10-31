"""Attached-host step heads and untargeted counter recipients (RULE 303.4m)."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


CARDS = [
    ("Unstable Mutation", "+3/+3", "-1/-1"),
    ("Essence Flare", "+2/+0", "-0/-1"),
]


def _card(name, pump, kind):
    return Card(id=name, name=name, type_line="Enchantment — Aura", oracle_text=(
        f"Enchant creature\nEnchanted creature gets {pump}.\n"
        "At the beginning of the upkeep of enchanted creature's controller, "
        f"put a {kind} counter on that creature."
    ))


@pytest.mark.parametrize("name,pump,kind", CARDS)
def test_real_card_specs(name, pump, kind):
    result = parse_oracle(_card(name, pump, kind))
    assert result.modeled
    trigger = next(s for s in result.specs if s.ability_kind == "triggered")
    assert trigger.trigger == {"event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                               "phase_relation": "attached_permanent"}
    assert trigger.effects == [EffectSpec("add_counters", {
        "count": 1, "kind": kind, "target_kind": "attached_permanent"})]


def test_counter_reference_requires_antecedent():
    text = "put a -1/-1 counter on that creature"
    assert match_clause(text) is None
    assert match_clause(text, reading=ClauseReading(attached_subject=True)) == [
        EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "target_kind": "attached_permanent"})]
    # A preceding target takes precedence over a host mentioned in the head.
    assert match_clause(text, reading=ClauseReading(attached_subject=True, previous_subject=True))[0].params["previous_subject"]
    assert match_clause(text + " and draw a card", reading=ClauseReading(attached_subject=True)) is None


def _game(name, pump, kind):
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", []),
                                  ("p3", "Cara", [])], starting_hand=0, starting_life=20)
    host = GameObject(Card(id="host", name="Host", type_line="Creature — Bear", is_creature=True,
                           power=5, toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(host)
    aura = GameObject(_card(name, pump, kind), owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.attached_to = host.instance_id
    bind_from_catalogue(aura)
    engine.state.add_to_battlefield(aura)
    return engine, host, aura


def _step(engine, player_index, step="upkeep"):
    engine.state.active_player_index = player_index
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, phase="beginning"))
    return engine.rules.put_triggers_on_stack()


@pytest.mark.parametrize("name,pump,kind", CARDS)
def test_live_controller_scope_and_counter_resolution(name, pump, kind):
    engine, host, aura = _game(name, pump, kind)
    assert _step(engine, 0) == 0  # Aura controller is unrelated.
    assert _step(engine, 2) == 0
    assert _step(engine, 1, "draw") == 0
    assert _step(engine, 1) == 1
    # Changing control after triggering does not counter the stacked ability.
    host.controller_id = "p3"
    engine.rules.resolve_top_of_stack()
    assert host.counters.get(kind, 0) == 1
    assert not aura.counters
    assert _step(engine, 1) == 0
    assert _step(engine, 2) == 1
    engine.rules.resolve_top_of_stack()
    assert host.counters.get(kind, 0) == 2
    aura.attached_to = None
    assert _step(engine, 2) == 0


def test_detaching_before_resolution_does_not_counter_source():
    engine, host, aura = _game(*CARDS[0])
    assert _step(engine, 1) == 1
    aura.attached_to = None
    engine.rules.resolve_top_of_stack()
    assert not host.counters
    assert not aura.counters


def test_reattached_source_counters_current_host():
    engine, old_host, aura = _game(*CARDS[0])
    assert _step(engine, 1) == 1
    new_host = GameObject(Card(id="new", name="New host", type_line="Creature", is_creature=True,
                              power=5, toughness=5), owner_id="p3", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(new_host)
    aura.attached_to = new_host.instance_id
    engine.rules.resolve_top_of_stack()
    assert not old_host.counters
    assert new_host.counters.get("-1/-1") == 1


def test_source_leaves_before_resolution_uses_last_attachment():
    engine, host, aura = _game(*CARDS[0])
    assert _step(engine, 1) == 1
    engine.rules.destroy(aura)
    assert aura.zone == Zone.GRAVEYARD
    engine.rules.resolve_top_of_stack()
    assert host.counters.get("-1/-1") == 1


def test_host_leaves_before_resolution_receives_no_counter():
    engine, host, aura = _game(*CARDS[0])
    assert _step(engine, 1) == 1
    engine.rules.destroy(host)
    engine.rules.resolve_top_of_stack()
    assert not host.counters
    assert not aura.counters


def test_scaled_damage_reads_counter_amount_and_step_player():
    engine, host, aura = _game(*CARDS[0])
    aura.card = Card(id="festering", name="Festering Wound", type_line="Enchantment — Aura", oracle_text=(
        "Enchant creature\nAt the beginning of your upkeep, you may put an infection counter on this Aura.\n"
        "At the beginning of the upkeep of enchanted creature's controller, this Aura deals X damage to "
        "that player, where X is the number of infection counters on this Aura."
    ))
    aura.triggered_abilities.clear()
    aura.static_effects.clear()
    bind_from_catalogue(aura)
    aura.counters["infection"] = 3
    assert _step(engine, 1) == 1
    engine.rules.resolve_top_of_stack()
    assert engine.state.player_by_id("p2").life == 17
    assert engine.state.player_by_id("p1").life == 20


def test_explicit_enchanted_recipient_is_untargeted():
    engine, host, aura = _game(*CARDS[0])
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    specs = match_clause("put 2 +1/+1 counters on enchanted creature")
    effects = build_effects(specs, aura)
    assert effects[0].target_spec is None
    effects[0].apply(GameContext(engine.state, engine.rules))
    assert host.counters.get("+1/+1") == 2
    assert not aura.counters


def test_phase_damage_rewrite_does_not_touch_future_granted_trigger():
    from mtg_analyzer.parser.oracle.segmenter import _phase_damage_referents
    damage = {"type": "damage", "params": {"amount": 2, "selector": "event_player"}}
    future = EffectSpec("grant_triggered_ability", {"effects": [damage]})
    assert _phase_damage_referents([future]) == [future]
