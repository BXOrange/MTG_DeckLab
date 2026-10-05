"""RULE 122 — the resolve-time optional energy payment "you may pay {E}{E}.
If you do, `<effect>`." (Aether Chaser/Herder/Inspector/Swooper-shaped
triggered abilities), plus the "you get {E}{E}" production side.

The flat "Pay {E}" *activated-ability cost* (`ActivationCost.pay_energy`) is
covered by `test_energy_cost.py`; this file is the interactive
`pay_energy_then` primitive (`PayEnergyThenEffect`/`RulesEngine.request_pay_
energy_then`), modeled like the shock-land pay-life choice. Only untargeted
follow-ups are modeled (every real card with this rider creates a token /
gains life / draws); a *targeted* follow-up (Guide of Souls) stays
unclaimed.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.gate import MODELED
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


_AETHER_CHASER_TEXT = (
    "First strike\n"
    "When this creature enters, you get {E}{E} (two energy counters).\n"
    "Whenever this creature attacks, you may pay {E}{E}. If you do, create a 1/1 "
    "colorless Servo artifact creature token."
)


def _aether_chaser(text=_AETHER_CHASER_TEXT):
    return Card(id="Aether Chaser", name="Aether Chaser",
                type_line="Creature — Human Warrior", is_creature=True,
                power=2, toughness=1, oracle_text=text)


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_get_energy_effect_is_recognized():
    (spec,) = parse_effect_body("you get {e}{e}")
    assert spec.type == "add_player_counters"
    assert spec.params == {"amount": 2, "kind": "energy"}


def test_pay_energy_then_effect_is_recognized_with_untargeted_follow_up():
    specs = parse_effect_body(
        "you may pay {e}{e}. if you do, create a 1/1 colorless servo artifact creature token"
    )
    (spec,) = specs
    assert spec.type == "pay_energy_then"
    assert spec.params["amount"] == 2
    assert spec.params["effects"][0]["type"] == "create_token"


def test_pay_energy_then_with_targeted_follow_up_stays_unclaimed():
    # Guide of Souls-shaped targeted follow-up ("put two +1/+1 counters on
    # target attacking creature") — no untargeted model, so fail-closed.
    assert parse_effect_body(
        "you may pay {e}{e}. if you do, put 2 +1/+1 counters on target attacking creature"
    ) is None


def test_aether_chaser_is_fully_modeled():
    result = parse_oracle(_aether_chaser())
    assert result.coverage == MODELED
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    attack_trigger = next(s for s in triggered if s.trigger.get("event") == "ATTACKS")
    # The trigger is *not* marked optional — the "you may" is the energy
    # payment's own choice, modeled by the pay_energy_then effect.
    assert attack_trigger.optional is False
    assert attack_trigger.effects[0].type == "pay_energy_then"


# ---------------------------------------------------------------------------
# ENGINE: production + optional payment
# ---------------------------------------------------------------------------


def _servo_count(state):
    return sum(1 for o in state.battlefield if o.card.name == "Servo")


def _fire_attacks(eng, obj):
    eng.state.fire_event(GameEvent(
        EventType.ATTACKS, object=obj.name, controller_id=obj.controller_id,
        instance_id=obj.instance_id, object_types=["creature"],
    ))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


def test_you_get_energy_effect_adds_energy_counters_to_controller():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    source = GameObject(_aether_chaser(), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(source)
    (spec,) = parse_effect_body("you get {e}{e}")
    (effect,) = build_effects([EffectSpec(spec.type, dict(spec.params))], source)
    effect.apply(GameContext(eng.state, eng.rules))
    assert p1.counters.get("energy") == 2


def test_pay_energy_then_pays_and_creates_the_token():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    chaser = GameObject(_aether_chaser(), owner_id="p1", zone=Zone.BATTLEFIELD)
    chaser.summoning_sick = False
    bind_from_catalogue(chaser)
    eng.state.add_to_battlefield(chaser)
    eng.rules.add_player_counters(p1, 2, "energy")

    _fire_attacks(eng, chaser)
    assert eng.state.pending_choice["kind"] == "pay_energy_then"
    eng.resolve_pending_choice("pay")
    assert p1.counters.get("energy", 0) == 0
    assert _servo_count(eng.state) == 1


def test_pay_energy_then_decline_leaves_energy_and_makes_no_token():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    chaser = GameObject(_aether_chaser(), owner_id="p1", zone=Zone.BATTLEFIELD)
    chaser.summoning_sick = False
    bind_from_catalogue(chaser)
    eng.state.add_to_battlefield(chaser)
    eng.rules.add_player_counters(p1, 2, "energy")

    _fire_attacks(eng, chaser)
    eng.resolve_pending_choice("decline")
    assert p1.counters.get("energy", 0) == 2
    assert _servo_count(eng.state) == 0


def test_pay_energy_then_offers_no_choice_when_unaffordable():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    chaser = GameObject(_aether_chaser(), owner_id="p1", zone=Zone.BATTLEFIELD)
    chaser.summoning_sick = False
    bind_from_catalogue(chaser)
    eng.state.add_to_battlefield(chaser)
    eng.rules.add_player_counters(p1, 1, "energy")  # only 1, need 2

    _fire_attacks(eng, chaser)
    assert eng.state.pending_choice is None  # can't afford → no choice, no token
    assert _servo_count(eng.state) == 0
    assert p1.counters.get("energy", 0) == 1
