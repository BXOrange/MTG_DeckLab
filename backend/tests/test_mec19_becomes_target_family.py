"""Tests for MEC-19 — RULE 115/601.2c's "becomes the target of a
spell/ability" as a real `EventType` (`BECOMES_TARGET`).

Before this, RULE 115 targeting never reached the event bus at all — Ward
(RULE 702.21) was checked directly at cast-time in `RulesEngine.check_ward`,
so nothing else could key a trigger off "became a target". `check_ward` is
now the general RULE 601.2c/602.2b/603.3d "targets finalized" choke point
every spell/activated-ability/triggered-ability call site already reaches
unconditionally (`_fire_becomes_target_events`) — Ward's own cast-time check
is untouched, just a sibling consumer of the same moment.

Two things are new:
  * `EventType.BECOMES_TARGET` + `effect_binder`'s `caster_relation`
    predicate and `_GROUP_CONTROLLER_EVENT_KEYS["BECOMES_TARGET"]` entry —
    powers Goldspan Dragon/Tectonic Giant's "attacks or becomes the target
    of a spell [an opponent controls]" (hand-authored: two `AbilitySpec`s
    per card, same "one spec per compound-triggered event" idiom as
    "~ enters or attacks").
  * `CounterUnlessPayEffect`/`counter_unless_pay` — the un-keyworded-
    Ward-shaped "whenever ~ becomes the target of a spell or ability an
    opponent controls, counter it unless that player pays `<cost>`." cycle
    (~90 real cache cards, none of which print the Ward keyword itself, so
    the existing keyword catalogue never reaches them). A thin adapter
    onto `RulesEngine.resolve_ward_effect` — rules-identical outcome, ward's
    own machinery, not a parallel implementation.

Reference: mtg_analyzer/models/events.py (`EventType.BECOMES_TARGET`),
mtg_analyzer/game/rules/misc_mixin.py (`check_ward`,
`_fire_becomes_target_events`), mtg_analyzer/game/binding/core.py
(`caster_relation`), mtg_analyzer/game/effects/core.py
(`CounterUnlessPayEffect`), mtg_analyzer/game/card_registry.py
(Goldspan Dragon, Tectonic Giant), RULE 115/601.2c/603.1/702.21.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def two_player_engine():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def to_hand(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id(controller).hand.append(obj)
    return obj


def advance_to_main(eng):
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.recompute_continuous_effects()


def count_treasures(eng, controller="p1"):
    return sum(
        1 for o in eng.state.battlefield
        if o.controller_id == controller and "Treasure" in o.card.type_line
    )


# ---------------------------------------------------------------------------
# EventType.BECOMES_TARGET fires for both objects and players
# ---------------------------------------------------------------------------


def test_becomes_target_fires_once_per_target():
    eng, p1, p2 = two_player_engine()
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    before = len(eng.state.event_log)
    eng.cast_spell(p2, bolt, targets=[p1])
    fired = [e for e in eng.state.event_log[before:] if e.type == EventType.BECOMES_TARGET]
    assert len(fired) == 1
    assert fired[0].get("is_player") is True
    assert fired[0].get("controller_id") == "p2"
    assert fired[0].get("item_kind") == "spell"


# ---------------------------------------------------------------------------
# Goldspan Dragon — real hand-authored card, both compound-trigger halves
# ---------------------------------------------------------------------------


def test_goldspan_dragon_creates_treasure_when_targeted_by_a_spell():
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Goldspan Dragon", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    before = count_treasures(eng, "p1")
    eng.cast_spell(p2, bolt, targets=[eng.state.battlefield[-1]])
    eng.resolve_until_stable()
    assert count_treasures(eng, "p1") == before + 1


def test_goldspan_dragon_creates_treasure_when_targeted_by_its_own_controllers_spell():
    """Unlike Tectonic Giant, Goldspan Dragon's own printed clause has no
    "an opponent controls" qualifier — it fires off *any* spell."""
    eng, p1, _p2 = two_player_engine()
    battlefield(eng, "Goldspan Dragon", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("R", 1)
    before = count_treasures(eng, "p1")
    eng.cast_spell(p1, bolt, targets=[eng.state.battlefield[-1]])
    eng.resolve_until_stable()
    assert count_treasures(eng, "p1") == before + 1


def test_goldspan_dragon_attacks_trigger_is_unaffected():
    eng, p1, p2 = two_player_engine()
    dragon = battlefield(eng, "Goldspan Dragon", "p1")
    advance_to_main(eng)
    eng.state.current_step = "declare_attackers"
    before = count_treasures(eng, "p1")
    eng.declare_attackers(p1, [{"attacker": dragon, "defender": p2}])
    eng.resolve_until_stable()
    assert count_treasures(eng, "p1") == before + 1


# ---------------------------------------------------------------------------
# Tectonic Giant — real hand-authored card, caster_relation="opponent" gate
# ---------------------------------------------------------------------------


def test_tectonic_giant_choice_offered_when_an_opponent_targets_it():
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Tectonic Giant", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    before_life = p2.life
    eng.cast_spell(p2, bolt, targets=[eng.state.battlefield[-1]])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "trigger_mode"
    eng.resolve_pending_choice("0")
    assert eng.state.pending_choice is None
    assert p2.life == before_life - 3


def test_tectonic_giant_does_not_trigger_off_its_own_controllers_spell():
    eng, p1, _p2 = two_player_engine()
    battlefield(eng, "Tectonic Giant", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("R", 1)
    eng.cast_spell(p1, bolt, targets=[eng.state.battlefield[-1]])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None


# ---------------------------------------------------------------------------
# CounterUnlessPayEffect — a thin adapter onto resolve_ward_effect
# ---------------------------------------------------------------------------


def _source_with_counter_unless_pay(eng, cost: str, controller="p1"):
    src = GameObject(
        Card(id="Warden", name="Warden", type_line="Creature — Wizard",
             is_creature=True, power=1, toughness=1),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    src.summoning_sick = False
    ability = bind_ability(
        AbilitySpec(
            "triggered",
            [EffectSpec("counter_unless_pay", {"cost": cost})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "caster_relation": "opponent",
            },
        ),
        src,
    )
    src.triggered_abilities.append(ability)
    eng.state.add_to_battlefield(src)
    return src


def test_counter_unless_pay_opens_the_ward_choice_and_counters_if_declined():
    eng, p1, p2 = two_player_engine()
    src = _source_with_counter_unless_pay(eng, "pay {2}")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 2)  # enough left over for the {2} ward tax, so declining is a real choice
    eng.cast_spell(p2, bolt, targets=[src])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "ward"
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.stack == []
    assert any(o.card.name == "Lightning Bolt" for o in p2.graveyard)  # countered → owner's GY
    assert src in eng.state.battlefield  # never dealt damage


def test_counter_unless_pay_resolves_normally_if_paid():
    eng, p1, p2 = two_player_engine()
    src = _source_with_counter_unless_pay(eng, "pay {2}")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 2)
    eng.cast_spell(p2, bolt, targets=[src])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "ward"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert p2.mana_pool.total() == 0  # the {2} tax was paid
    assert src not in eng.state.battlefield  # Lightning Bolt resolved: 3 damage killed the 1/1


def test_counter_unless_pay_auto_counters_when_unpayable():
    eng, p1, p2 = two_player_engine()
    src = _source_with_counter_unless_pay(eng, "pay {2}")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)  # not enough left over for the {2} ward tax
    eng.cast_spell(p2, bolt, targets=[src])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # unpayable → no real choice offered
    assert src in eng.state.battlefield  # countered before it could resolve


# ---------------------------------------------------------------------------
# Parse-level: the real ~90-card "counter it unless that player pays" cycle,
# the group-subject "you control" scoping, and once-per-turn
# ---------------------------------------------------------------------------


def test_battle_mammoth_is_fully_modeled_with_group_subject_and_caster_relation():
    result = parse_oracle(_card("Battle Mammoth"))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert any(s.trigger.get("event") == "BECOMES_TARGET" for s in triggered)
    mammoth_trig = next(s for s in triggered if s.trigger.get("event") == "BECOMES_TARGET")
    # PAR-131: "a permanent" composes to no filter at all (every group
    # subject of a BECOMES_TARGET event is already a permanent).
    assert mammoth_trig.trigger["condition"] == {
        "subject": "group", "other": False, "controller": "you",
    }
    assert mammoth_trig.trigger.get("caster_relation") == "opponent"


def test_angelic_cub_is_fully_modeled_with_once_per_turn():
    result = parse_oracle(_card("Angelic Cub"))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    becomes_target = next(s for s in triggered if s.trigger.get("event") == "BECOMES_TARGET")
    assert becomes_target.trigger.get("limit") is True


def test_frost_titans_becomes_target_clause_is_claimed():
    """Frost Titan became fully MODELED at PARSER_VERSION 148 (its "tap
    target permanent. That permanent doesn't untap during its controller's
    next untap step." ability is now the `skip_next_untap` family). This
    still guards that the BECOMES_TARGET clause itself parses correctly.
    """
    result = parse_oracle(_card("Frost Titan"))
    assert result.coverage == "MODELED"
    becomes_target = [
        s for s in result.specs
        if s.ability_kind == "triggered" and s.trigger and s.trigger.get("event") == "BECOMES_TARGET"
    ]
    assert len(becomes_target) == 1
    assert becomes_target[0].effects[0].type == "counter_unless_pay"
    assert becomes_target[0].effects[0].params["cost"] == "pay {2}"
