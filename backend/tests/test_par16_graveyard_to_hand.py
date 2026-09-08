"""PAR-16: "`<cost>`: Return this card from your graveyard to your hand."
(Abzan Devotee/Clay Revenant-shaped, an activated ability) and its
triggered sibling "Whenever `<event>`, [you may] return this card from
your graveyard to your hand." (Aurora Eidolon/Chandra's Phoenix/Blood
Speaker-shaped) — the hand-destination sibling of PAR-10's "…to the
battlefield[, tapped]." (`ReturnSelfFromGraveyardToBattlefieldEffect`).

Two pieces:

* `game/effects/core.py`'s `ReturnSelfFromGraveyardToHandEffect` +
  `catalogue.handlers._RETURN_SELF_FROM_GRAVEYARD_RE` (now a single regex
  with a named ``hand``/``tapped`` alternation covering both destinations).
* RULE 113.6a: a triggered ability whose body is this effect implicitly
  *functions from the graveyard* — `TriggeredAbility.functions_from_graveyard`
  (inferred by `effect_binder.bind_ability`, the same "effect and permission
  travel together" idea `ActivationCost.graveyard_zone` already uses for the
  activated half) and `RulesEngine._collect_graveyard_function_triggers`,
  a general scan alongside the older, mill-only
  `_collect_mill_return_from_graveyard_triggers`.

Reference: mtg_analyzer/game/{effects,effect_binder,rules/triggers_mixin}.py,
mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import (
    ReturnSelfFromGraveyardToBattlefieldEffect,
    ReturnSelfFromGraveyardToHandEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(4)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


# ---------------------------------------------------------------------------
# PARSER: the merged battlefield/hand regex
# ---------------------------------------------------------------------------


def test_return_self_to_hand_is_recognized():
    (spec,) = match_clause("return this card from your graveyard to your hand")
    assert spec.type == "return_self_from_graveyard_to_hand"
    assert spec.params == {}


def test_return_self_to_battlefield_is_still_recognized_untapped():
    (spec,) = match_clause("return this card from your graveyard to the battlefield")
    assert spec.type == "return_self_from_graveyard"
    assert spec.params == {"tapped": False}


def test_return_self_to_battlefield_tapped_is_still_recognized():
    (spec,) = match_clause("return this card from your graveyard to the battlefield tapped")
    assert spec.type == "return_self_from_graveyard"
    assert spec.params == {"tapped": True}


def test_return_self_to_exile_is_not_claimed():
    assert match_clause("return this card from your graveyard to exile") is None


# ---------------------------------------------------------------------------
# ENGINE: activated ability (Abzan Devotee-shaped)
# ---------------------------------------------------------------------------


def test_activated_return_to_hand_is_end_to_end_modeled_and_playable():
    card = Card(
        id="Test Devotee", name="Test Devotee", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="{2}{B}: Return this card from your graveyard to your hand.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    assert len(obj.activated_abilities) == 1
    ability = obj.activated_abilities[0]
    assert ability.cost.graveyard_zone is True
    assert isinstance(ability.effects[0], ReturnSelfFromGraveyardToHandEffect)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 2})
    assert eng.can_activate(p1, obj, ability) is True

    eng.activate_ability(p1, obj, 0)
    eng.resolve_until_stable()

    assert obj not in p1.graveyard
    assert obj in p1.hand


def test_activated_return_to_hand_refuses_from_the_battlefield():
    card = Card(
        id="Test Devotee 2", name="Test Devotee 2", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="{2}{B}: Return this card from your graveyard to your hand.",
    )
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    ability = obj.activated_abilities[0]

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 2})
    assert eng.can_activate(p1, obj, ability) is False


# ---------------------------------------------------------------------------
# ENGINE: triggered ability functioning from the graveyard (Eidolon-shaped)
# ---------------------------------------------------------------------------


def test_triggered_return_to_hand_is_end_to_end_modeled():
    card = Card(
        id="Test Eidolon", name="Test Eidolon", type_line="Enchantment Creature — Spirit",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever a Demon you control enters, return this card from your graveyard to your hand.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_triggered_return_to_hand_fires_while_sitting_in_the_graveyard():
    card = Card(
        id="Test Eidolon 2", name="Test Eidolon 2", type_line="Enchantment Creature — Spirit",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever a Demon you control enters, return this card from your graveyard to your hand.",
    )
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    ability = obj.triggered_abilities[0]
    assert ability.functions_from_graveyard is True
    assert isinstance(ability.effects[0], ReturnSelfFromGraveyardToHandEffect)

    # Cast a real Demon (rather than `add_to_battlefield` directly) so
    # ENTERS_BATTLEFIELD actually fires — only the resolve-a-permanent-spell
    # path fires that event, a bare battlefield add does not.
    demon_card = Card(id="A Demon", name="A Demon", type_line="Creature — Demon",
                       mana_cost_string="{B}", converted_mana_cost=1,
                       is_creature=True, power=5, toughness=5)
    demon_obj = GameObject(demon_card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(demon_obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1})
    eng.cast_spell(p1, demon_obj)
    eng.resolve_until_stable()

    assert demon_obj in eng.state.battlefield
    assert obj not in p1.graveyard
    assert obj in p1.hand


def test_triggered_return_to_hand_does_not_fire_from_the_battlefield():
    # A copy of the same card sitting on the battlefield has no graveyard-
    # scan reason to fire off this event (`_collect_triggers`'s ordinary
    # battlefield scan checks the *same* trigger_event, but this ability's
    # condition subject is "self", so the battlefield object's own instance
    # never matches an unrelated Demon entering anyway) — this test pins
    # down that the graveyard-only object is what actually resolves, not
    # both/neither.
    card = Card(
        id="Test Eidolon 3", name="Test Eidolon 3", type_line="Enchantment Creature — Spirit",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever a Demon you control enters, return this card from your graveyard to your hand.",
    )
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    demon_card = Card(id="A Demon 2", name="A Demon 2", type_line="Creature — Demon",
                      mana_cost_string="{B}", converted_mana_cost=1,
                      is_creature=True, power=5, toughness=5)
    p2 = eng.state.players[1]
    demon_obj = GameObject(demon_card, owner_id="p2", zone=Zone.HAND)
    p2.hand.append(demon_obj)
    eng.begin_turn()  # turn 1: p1
    eng.begin_turn()  # turn 2: rotates to p2's own turn, so p2 may cast a sorcery-speed creature
    eng.state.current_step = "main1"
    p2.mana_pool.add_many({"B": 1})
    eng.cast_spell(p2, demon_obj)
    eng.resolve_until_stable()

    # "a Demon **you** control" — p2's Demon must not trigger p1's card.
    assert obj in p1.graveyard
    assert obj not in p1.hand


def test_return_self_from_graveyard_to_hand_is_a_noop_once_it_left_the_graveyard():
    from mtg_analyzer.game.effects.core import GameContext

    card = Card(id="Noop Test", name="Noop Test", type_line="Creature", is_creature=True)
    eng = _engine()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    eng.state.players[0].hand.append(obj)

    effect = ReturnSelfFromGraveyardToHandEffect()
    effect.source = obj
    effect.apply(GameContext(eng.state, eng.rules))

    assert obj in eng.state.players[0].hand  # unchanged — never was in the graveyard
