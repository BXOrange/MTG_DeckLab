"""Batch 4 (docs/implementation-state/ToDo_Backend.md): the
self-referential-trigger family's two foundational pieces —

* **RULE 207.2c ability-word stripping** (`normalize._strip_ability_words`)
  — "Landfall — Whenever a land you control enters, …" now recognizes just
  like an unlabeled card, since the label carries no rules meaning of its
  own; also covers Constellation/Battalion.
* **Controller-scoped phase triggers** (RULE 500.7,
  `segmenter._PHASE_TRIGGER_RE` + `AbilitySpec.trigger["phase_relation"]` +
  `effect_binder._trigger_condition`) — "at the beginning of your upkeep"/
  "at the beginning of each opponent's upkeep" now check whose turn it is
  against the ability's own source, alongside the pre-existing unscoped
  "each upkeep"/"the end step" forms (regression-checked here too).
* **Self-subject "deals (combat) damage to a player/creature"**
  (`segmenter._SELF_DAMAGE_TRIGGER_RE`, RULE 120.3) — `EventType.DAMAGE`
  plus a `{"combat": ..., "is_player": ...}` filter; also extended
  `grant_triggered_ability`/`continuous._granted_trigger_condition` to
  DAMAGE events, closing Batch 3's deferred quoted-DAMAGE-grant gap
  (Combat Research-shaped).

Each family is driven through real oracle text via `parse_oracle` **and**
bound + exercised against a real `GameEngine`/`RulesEngine`.

Reference: mtg_analyzer/parser/oracle/{normalize,segmenter}.py,
mtg_analyzer/game/{effect_binder,continuous,rules_engine}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text, power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness, oracle_text=oracle_text,
    )


def _permanent(name, oracle_text, type_line="Enchantment"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _battlefield_obj(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- ability-word stripping ---------------------------------------------------


def test_landfall_prefix_is_stripped_and_recognized():
    card = _creature(
        "Lotus Cobra", "Landfall — Whenever a land you control enters, ~ gets +1/+1 until end of turn."
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_battalion_prefix_is_stripped():
    card = _creature(
        "Battalion Bear",
        "Battalion — Whenever ~ and at least two other creatures attack, ~ gets +1/+1 until end of turn.",
    )
    # The body itself uses a compound "and at least N other creatures attack"
    # condition this batch doesn't model — the point of this test is only
    # that the *label* no longer blocks recognition outright regardless.
    result = parse_oracle(card)
    assert "battalion" not in " ".join(result.unclaimed)


# -- controller-scoped phase triggers -----------------------------------------


def test_your_upkeep_simple_effect_is_modeled():
    card = _permanent("Bit of Faith", "At the beginning of your upkeep, you gain 1 life.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_each_opponents_upkeep_simple_effect_is_modeled():
    card = _permanent(
        "Fright Bell", "At the beginning of each opponent's upkeep, you gain 1 life."
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_each_upkeep_unscoped_is_modeled():
    card = _permanent("Howling Mine Clone", "At the beginning of each upkeep, draw a card.")
    assert parse_oracle(card).unclaimed == []


def test_the_end_step_unscoped_still_works():
    # Pre-existing "the <step> step" wording — regression check.
    card = _permanent("Old Style", "At the beginning of the end step, you gain 1 life.")
    assert parse_oracle(card).unclaimed == []


def test_your_end_step_scoped_is_modeled():
    card = _permanent("Cement Shoes Lite", "At the beginning of your end step, you gain 1 life.")
    assert parse_oracle(card).unclaimed == []


def test_sacrifice_unless_pay_body_stays_unclaimed():
    # Fail-closed: the phase-scope wrapper is now recognized, but the
    # "sacrifice ~ unless you pay <cost>" *body* is a distinct, still-
    # unmodeled effect shape (a real new primitive, not this batch's scope).
    card = _permanent(
        "Icatian Store", "At the beginning of your upkeep, sacrifice ~ unless you pay {1}."
    )
    assert parse_oracle(card).coverage == UNMODELED


# -- "deals (combat) damage to a player/creature" -----------------------------


def test_deals_combat_damage_to_a_player_is_modeled():
    card = _creature(
        "Bloodthirsty Blade",
        "Whenever ~ deals combat damage to a player, put a +1/+1 counter on it.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_deals_combat_damage_to_a_creature_is_modeled():
    card = _creature("Vicious Biter", "Whenever ~ deals combat damage to a creature, put a +1/+1 counter on it.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_group_subject_damage_trigger_stays_unclaimed():
    # Fail-closed: only the "~" self-subject phrasing is claimed today.
    card = _permanent(
        "Blood Artist Cousin",
        "Whenever a creature you control deals combat damage to a player, you gain 1 life.",
        type_line="Creature — Bear",
    )
    assert parse_oracle(card).coverage == UNMODELED


def test_quoted_damage_grant_is_now_modeled():
    # Closes Batch 3's deferred quoted-DAMAGE-grant gap.
    card = _permanent(
        "Combat Research",
        'Enchant creature\nEnchanted creature has "whenever ~ deals combat damage to '
        'a player, draw a card."',
        type_line="Enchantment — Aura",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- execute-side (bind → engine) --------------------------------------------


def test_your_upkeep_trigger_fires_only_on_own_upkeep():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(state, _permanent("Bit of Faith", "At the beginning of your upkeep, you gain 1 life."))

    from mtg_analyzer.models.events import EventType, GameEvent

    # Not this player's upkeep — must not fire.
    state.active_player_index = 1  # p2's turn
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    assert eng.rules.put_triggers_on_stack() == 0

    # This player's own upkeep — must fire.
    state.active_player_index = 0  # p1's turn
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert state.player_by_id("p1").life == 21


def test_each_opponents_upkeep_trigger_fires_only_on_opponents_upkeep():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _permanent("Fright Bell", "At the beginning of each opponent's upkeep, you gain 1 life."),
        controller="p1",
    )

    from mtg_analyzer.models.events import EventType, GameEvent

    # p1's own upkeep — must NOT fire (p1 is the controller, not an opponent).
    state.active_player_index = 0
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    assert eng.rules.put_triggers_on_stack() == 0

    # p2's upkeep — must fire.
    state.active_player_index = 1
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    assert eng.rules.put_triggers_on_stack() == 1


def test_deals_combat_damage_to_a_player_trigger_fires_and_pumps():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _creature(
            "Bloodthirsty Blade",
            "Whenever ~ deals combat damage to a player, put a +1/+1 counter on it.",
        ),
    )

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=obj, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert obj.counters.get("+1/+1") == 1


def test_deals_combat_damage_trigger_does_not_fire_for_a_different_creature():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _creature(
            "Bloodthirsty Blade",
            "Whenever ~ deals combat damage to a player, put a +1/+1 counter on it.",
        ),
    )
    bystander = _battlefield_obj(state, _creature("Bystander", ""))

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=bystander, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0


def test_deals_combat_damage_to_a_creature_does_not_fire_on_player_damage():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _creature("Vicious Biter", "Whenever ~ deals combat damage to a creature, put a +1/+1 counter on it."),
    )

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=obj, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0


def test_quoted_damage_grant_fires_for_its_own_host_only():
    eng = _engine()
    state = eng.state
    host = _battlefield_obj(state, _creature("Bear", ""), controller="p1")
    bystander = _battlefield_obj(state, _creature("Bystander", ""), controller="p1")
    aura = _battlefield_obj(
        state,
        _permanent(
            "Combat Research",
            'Enchant creature\nEnchanted creature has "whenever ~ deals combat damage to '
            'a player, draw a card."',
            type_line="Enchantment — Aura",
        ),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Library Bear", ""), owner_id="p1", zone=Zone.LIBRARY))

    from mtg_analyzer.game import continuous

    continuous.recompute(state)

    # A different creature dealing combat damage must not trigger the grant.
    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=bystander, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0

    # The enchanted host dealing combat damage does.
    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=host, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1
