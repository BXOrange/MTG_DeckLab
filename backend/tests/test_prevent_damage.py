"""Tests for RULE 615's one-shot "prevent all/the next N damage that would
be dealt to you this turn" family (Riot Control/Thought Lash) — the new
`PreventDamageEffect` one-shot, `RulesEngine.prevent_damage_to_player`'s
turn-scoped shield mechanism (a `ReplacementEffect` living on
`Player.player_effects`, not a permanent's own `replacement_effects` —
Regenerate-shaped, but player- rather than object-scoped), and the two
supporting additions both real cards needed: `GainLifeEffect.count_selector`
(Riot Control's "for each creature your opponents control") and the new
`ActivationCost.exile_top_of_library` cost (Thought Lash's own repeatable
activated ability).

Mirrors `test_regenerate.py`'s layered pattern: engine-level shield tests
via a bare `RulesEngine`/`GameState`, then a `RegenerateEffect`-analogous
direct `PreventDamageEffect.apply()` test, then end-to-end catalogue-driven
tests for both real cards via `bind_from_catalogue`.
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import GameContext, GainLifeEffect, PreventDamageEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.rules_engine import RulesEngine


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bear(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# ENGINE: the "all" shield (Riot Control)
# ---------------------------------------------------------------------------


def test_prevent_all_damage_shield_absorbs_lethal_damage():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, "all")
    rules.deal_damage(p1, 25)
    assert p1.life == 20


def test_prevent_all_damage_shield_persists_across_multiple_events():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, "all")
    rules.deal_damage(p1, 5)
    rules.deal_damage(p1, 7)
    assert p1.life == 20
    assert any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)


def test_prevent_all_damage_shield_does_not_affect_a_different_player():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, "all")
    rules.deal_damage(p2, 5)
    assert p2.life == 15


# ---------------------------------------------------------------------------
# ENGINE: the capped/cumulative shield (Thought Lash)
# ---------------------------------------------------------------------------


def test_prevent_next_n_damage_partially_absorbs_then_lets_the_rest_through():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, 1)
    rules.deal_damage(p1, 5)
    assert p1.life == 16  # 1 point prevented, 4 dealt


def test_prevent_next_n_damage_self_removes_once_exhausted():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, 1)
    rules.deal_damage(p1, 5)
    assert not any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)
    rules.deal_damage(p1, 3)
    assert p1.life == 13  # the second hit isn't prevented at all


def test_prevent_next_n_damage_spends_cumulative_bank_across_events():
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, 3)
    rules.deal_damage(p1, 1)
    rules.deal_damage(p1, 1)
    assert p1.life == 20  # both 1-point hits fully absorbed, 1 left in the bank
    rules.deal_damage(p1, 5)
    assert p1.life == 16  # 1 more prevented, 4 dealt; bank now exhausted


def test_multiple_activations_stack_independent_shields():
    # Two shields simultaneously applicable to the same DAMAGE event is RULE
    # 616.1e ambiguity, same as `test_regenerate.py`'s own multi-shield case
    # — resolve the interactive ordering choice(s) before the damage clears.
    rules, state, p1, p2 = _rules()
    rules.prevent_damage_to_player(p1, 1)
    rules.prevent_damage_to_player(p1, 1)
    rules.deal_damage(p1, 5)
    assert state.pending_choice is not None
    rules.resolve_replacement_order_choice(0)
    if state.pending_choice is not None:
        rules.resolve_replacement_order_choice(0)
    assert p1.life == 17  # 2 points prevented (one from each shield), 3 dealt


# ---------------------------------------------------------------------------
# ENGINE: cleanup sweep (RULE 514.2 "this turn" expiry)
# ---------------------------------------------------------------------------


def test_unused_all_shield_expires_at_cleanup():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    p1 = eng.state.player_by_id("p1")
    eng.rules.prevent_damage_to_player(p1, "all")
    eng._step_cleanup()
    assert not any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)
    eng.rules.deal_damage(p1, 5)
    assert p1.life == 15  # shield is gone, damage goes through


def test_unused_capped_shield_expires_at_cleanup_even_with_remaining_balance():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    p1 = eng.state.player_by_id("p1")
    eng.rules.prevent_damage_to_player(p1, 3)
    eng._step_cleanup()
    assert not any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)


def test_cleanup_does_not_sweep_other_player_effects():
    from mtg_analyzer.game.effects import ReplacementEffect
    from mtg_analyzer.models.events import EventType

    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    p1 = eng.state.player_by_id("p1")
    other = ReplacementEffect(event_type=EventType.DAMAGE, replacement_fn=lambda e, c: e)
    p1.player_effects.append(other)
    eng.rules.prevent_damage_to_player(p1, "all")
    eng._step_cleanup()
    assert p1.player_effects == [other]


# ---------------------------------------------------------------------------
# PreventDamageEffect.apply() unit tests
# ---------------------------------------------------------------------------


def test_prevent_damage_effect_targets_its_own_controller():
    rules, state, p1, p2 = _rules()
    source = _bf(state, _bear(), controller="p1")
    ctx = GameContext(state, rules)
    PreventDamageEffect(amount="all", source=source).apply(ctx)
    assert any(getattr(e, "damage_prevention_shield", False) for e in p1.player_effects)
    assert not any(getattr(e, "damage_prevention_shield", False) for e in p2.player_effects)


# ---------------------------------------------------------------------------
# GainLifeEffect.count_selector
# ---------------------------------------------------------------------------


def test_gain_life_count_selector_counts_opponents_creatures():
    rules, state, p1, p2 = _rules()
    source = _bf(state, _bear("Source"), controller="p1")
    _bf(state, _bear("Opp Bear 1"), controller="p2")
    _bf(state, _bear("Opp Bear 2"), controller="p2")
    _bf(state, _bear("Own Bear"), controller="p1")
    ctx = GameContext(state, rules)
    GainLifeEffect(count_selector="creatures_opponents_control", source=source).apply(ctx)
    assert p1.life == 22  # started at 20, +2 for the two opponent creatures


# ---------------------------------------------------------------------------
# ActivationCost.exile_top_of_library
# ---------------------------------------------------------------------------


def test_exile_top_of_library_cost_is_recognized():
    cost = parse_activation_cost({"text": "Exile the top card of your library"})
    assert cost.exile_top_of_library is True


def test_exile_top_of_library_cost_is_unpayable_with_an_empty_library():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()
    cost = parse_activation_cost({"text": "Exile the top card of your library"})
    source = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    assert not eng._can_pay_activation_cost(p1, source, cost, x=0)


def test_exile_top_of_library_cost_exiles_the_top_card():
    eng = GameEngine.new_game(
        [("p1", "Alice", [_bear("Deck Card")]), ("p2", "Bob", [])], starting_hand=0
    )
    p1 = eng.state.player_by_id("p1")
    top = p1.library[-1]
    cost = parse_activation_cost({"text": "Exile the top card of your library"})
    source = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng._pay_activation_cost(p1, source, cost, x=0)
    assert top in p1.exile
    assert top not in p1.library


# ---------------------------------------------------------------------------
# End to end: Riot Control (catalogue "spell_effect")
# ---------------------------------------------------------------------------


def _riot_control_card():
    return Card(id="Riot Control", name="Riot Control", type_line="Instant",
                mana_cost_string="{2}{W}", converted_mana_cost=3, is_instant=True,
                oracle_text="You gain 1 life for each creature your opponents "
                             "control. Prevent all damage that would be dealt "
                             "to you this turn.")


def test_riot_control_gains_life_and_prevents_damage_this_turn():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _bf(eng.state, _bear("Opp Bear 1"), controller="p2")
    _bf(eng.state, _bear("Opp Bear 2"), controller="p2")

    spell = GameObject(_riot_control_card(), owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(spell)
    ctx = GameContext(eng.state, eng.rules)
    for effect_spec_effect in spell.spell_effects:
        effect_spec_effect.apply(ctx)

    assert p1.life == 22
    eng.rules.deal_damage(p1, 10)
    assert p1.life == 22


# ---------------------------------------------------------------------------
# End to end: Thought Lash's shield ability (catalogue "activated")
# ---------------------------------------------------------------------------


def _thought_lash_card():
    return Card(
        id="Thought Lash", name="Thought Lash", type_line="Enchantment",
        mana_cost_string="{2}{U}{U}", converted_mana_cost=4,
        oracle_text="Cumulative upkeep—Exile the top card of your library.\n"
                    "When a player doesn't pay this enchantment's cumulative "
                    "upkeep, that player exiles all cards from their library.\n"
                    "Exile the top card of your library: Prevent the next 1 "
                    "damage that would be dealt to you this turn.",
    )


def test_thought_lash_activated_ability_exiles_top_card_and_prevents_damage():
    eng = GameEngine.new_game(
        [("p1", "Alice", [_bear("Deck Card")]), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    permanent = GameObject(_thought_lash_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    permanent.summoning_sick = False
    bind_from_catalogue(permanent)
    eng.state.add_to_battlefield(permanent)
    top = p1.library[-1]

    eng.activate_ability(p1, permanent, ability_index=0)
    assert top in p1.exile
    eng.resolve_until_stable()

    eng.rules.deal_damage(p1, 5)
    assert p1.life == 16  # 1 prevented, 4 dealt
