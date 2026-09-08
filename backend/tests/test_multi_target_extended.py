"""Tests for RULE 115.1a "N target(s)" generalized to N>=2, extended to the
four effect families `tests/test_multi_target.py` (destroy/exile/damage)
didn't cover: `return_to_hand`/`tap`/`add_counters`/`return_from_graveyard`.
`TapEffect` already supported ``count`` end-to-end before this — only its
parser grammar was missing; the other three needed both.

Mirrors `test_multi_target.py`'s fixture pattern and
parser-recognition-then-engine-drive split; supersedes the "stays N=1-only"
framing in `test_optional_targets.py`'s module docstring and its
`test_up_to_2_targets_still_unclaimed_for_a_family_not_yet_generalized`.
"""

from mtg_analyzer.game.effects.core import (
    AddCountersEffect,
    ReturnFromGraveyardEffect,
    ReturnToHandEffect,
    TapEffect,
)
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import all_requirements_satisfiable, requirements_with_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True, oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2)


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [instant("filler")] * 5), ("p2", "Bob", [instant("f")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def give_spell(eng, player, card, effects):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    obj.spell_effects = effects
    for e in effects:
        e.source = obj
    player.hand.append(obj)
    return obj


def cast_action_for(eng, player, obj):
    for a in eng.legal_actions(player):
        if a.get("type") == "cast_spell" and a["instance_id"] == obj.instance_id:
            return a
    return None


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_tap_multi_target_recognized():
    (spec,) = parse_effect_body("tap 2 target creatures")
    assert spec.type == "tap"
    assert spec.params == {"target_kind": "creature", "count": 2, "untap": False}


def test_untap_up_to_two_target_lands_recognized():
    # Snap-shaped: "Untap up to two target lands."
    (spec,) = parse_effect_body("untap up to 2 target lands")
    assert spec.type == "tap"
    assert spec.params == {"target_kind": "permanent", "count": 2, "untap": True, "optional": True}


def test_return_to_hand_multi_target_recognized():
    (spec,) = parse_effect_body("return 2 target creatures to their owners' hands")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": "creature", "count": 2}


def test_return_from_graveyard_multi_target_recognized():
    specs = parse_effect_body(
        "return up to 2 target creature cards from your graveyard to your hand"
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "return_from_graveyard"
    assert spec.params == {
        "target_kind": "graveyard_creature", "destination": "hand", "count": 2, "optional": True,
    }


def test_add_counters_multi_target_recognized():
    # Ajani, Adversary of Tyrants-shaped: "Put a +1/+1 counter on each of up
    # to two target creatures."
    (spec,) = parse_effect_body(
        "put a +1/+1 counter on each of up to 2 target creatures"
    )
    assert spec.type == "add_counters"
    assert spec.params == {
        "count": 1, "kind": "+1/+1", "target_kind": "creature", "target_count": 2, "optional": True,
    }


def test_add_counters_multi_target_with_other_and_mandatory_count():
    (spec,) = parse_effect_body(
        "put 2 +1/+1 counters on each of 2 other target creatures"
    )
    assert spec.type == "add_counters"
    assert spec.params == {
        "count": 2, "kind": "+1/+1", "target_kind": "creature", "target_count": 2,
    }


def test_count_of_one_stays_unclaimed_for_new_families():
    assert parse_effect_body("tap 1 target creature") is None
    assert parse_effect_body("return 1 target creature to their owners' hands") is None


def test_unrecognized_kind_stays_unclaimed():
    # "target players" isn't a legal return_to_hand kind.
    assert parse_effect_body("return 2 target players to their owners' hands") is None


# ---------------------------------------------------------------------------
# EFFECT CLASSES: count propagates to TargetSpec
# ---------------------------------------------------------------------------


def test_count_reaches_target_spec_on_the_four_new_families():
    assert TapEffect(count=2).target_spec.count == 2
    assert ReturnToHandEffect(count=2).target_spec.count == 2
    assert ReturnFromGraveyardEffect(target_kind="graveyard_creature", count=2).target_spec.count == 2
    assert AddCountersEffect(target_kind="creature", count=2).target_spec.count == 2
    # Defaults stay 1, unaffected.
    assert TapEffect().target_spec.count == 1
    assert ReturnToHandEffect().target_spec.count == 1


def test_add_counters_amount_and_target_count_are_independent():
    # Two +1/+1 counters, on each of three targets — not conflated.
    effect = AddCountersEffect(amount=2, target_kind="creature", count=3)
    assert effect.amount == 2
    assert effect.target_spec.count == 3


# ---------------------------------------------------------------------------
# ENGINE: RULE 601.2c castability
# ---------------------------------------------------------------------------


def test_mandatory_two_targets_locks_return_to_hand_with_only_one_legal_target():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Double Bounce"), [ReturnToHandEffect(count=2)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is True


def test_optional_add_counters_never_locks_even_with_an_empty_board():
    eng, p1, p2 = two_player_engine()
    obj = give_spell(
        eng, p1, instant("Maybe Buff Two"),
        [AddCountersEffect(target_kind="creature", count=2, optional=True)],
    )
    action = cast_action_for(eng, p1, obj)
    assert action.get("requires_target") is True
    assert action.get("locked") is None


# ---------------------------------------------------------------------------
# ENGINE: resolution applies to exactly the chosen (up to) N targets
# ---------------------------------------------------------------------------


def test_tap_effect_taps_both_chosen_targets():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Double Tap"), [TapEffect(count=2)])
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.tapped is True
    assert wolf.tapped is True


def test_return_to_hand_returns_both_chosen_targets():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Double Bounce"), [ReturnToHandEffect(count=2)])
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.HAND
    assert wolf.zone == Zone.HAND


def test_add_counters_puts_the_amount_on_each_of_two_targets():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(
        eng, p1, instant("Twin Growth"),
        [AddCountersEffect(amount=1, target_kind="creature", count=2)],
    )
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.counters.get("+1/+1", 0) == 1
    assert wolf.counters.get("+1/+1", 0) == 1


def test_return_from_graveyard_returns_both_chosen_cards_to_hand():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p1", zone=Zone.GRAVEYARD)
    wolf = GameObject(creature("Wolf"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bear)
    p1.graveyard.append(wolf)
    obj = give_spell(
        eng, p1, instant("Double Regrowth"),
        [ReturnFromGraveyardEffect(target_kind="graveyard_creature", destination="hand", count=2)],
    )
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.HAND
    assert wolf.zone == Zone.HAND


def test_a_shared_targets_list_longer_than_count_is_not_over_consumed_by_add_counters():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    fox = GameObject(creature("Fox"), owner_id="p2", zone=Zone.BATTLEFIELD)
    for o in (bear, wolf, fox):
        eng.state.add_to_battlefield(o)
    obj = give_spell(
        eng, p1, instant("Twin Growth"),
        [AddCountersEffect(amount=1, target_kind="creature", count=2)],
    )
    eng.cast_spell(p1, obj, targets=[bear, wolf, fox])
    eng.rules.resolve_top_of_stack()
    assert bear.counters.get("+1/+1", 0) == 1
    assert wolf.counters.get("+1/+1", 0) == 1
    assert fox.counters.get("+1/+1", 0) == 0


# ---------------------------------------------------------------------------
# END-TO-END: real card oracle text -> parse -> bind -> cast -> resolve
# ---------------------------------------------------------------------------


def test_ajani_adversary_of_tyrants_plus_one_end_to_end():
    card = instant(
        "Twincast Growth", cost="{1}{G}",
        oracle_text="Put a +1/+1 counter on each of up to two target creatures.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    requirements = requirements_with_targets(eng.state, "p1", obj)
    assert len(requirements) == 1
    assert requirements[0]["count"] == 2
    assert all_requirements_satisfiable(requirements)

    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.counters.get("+1/+1", 0) == 1
    assert wolf.counters.get("+1/+1", 0) == 1


def test_death_duet_shaped_return_from_graveyard_end_to_end():
    card = instant(
        "Twinned Return", cost="{2}{B}",
        oracle_text="Return two target creature cards from your graveyard to your hand.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p1", zone=Zone.GRAVEYARD)
    wolf = GameObject(creature("Wolf"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bear)
    p1.graveyard.append(wolf)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    requirements = requirements_with_targets(eng.state, "p1", obj)
    assert len(requirements) == 1
    assert requirements[0]["count"] == 2
    assert all_requirements_satisfiable(requirements)

    p1.mana_pool.add_many({"B": 1, "C": 2})
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.HAND
    assert wolf.zone == Zone.HAND
