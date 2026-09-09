"""ENG-3: cost-payment auto-picks upgraded to a real RULE 602.1 choice.

A spell's own "as an additional cost to cast this spell, sacrifice/discard
…" (RULE 601.2b, `GameEngine._pay_additional_cast_cost`) and an activated
ability's plain "discard N cards" cost component
(`GameEngine._pay_activation_cost`) used to auto-pick — the first matching
permanent, the back of hand — even though RULE 602.1 makes both a genuine
player choice. Cost payment is one synchronous call inside `cast_spell`/
`activate_ability`, so it can't pause for a `_request_choose_objects`
`pending_choice` the way an *effect* resolving can (see ENG-2,
`RulesEngine.sacrifice`) — instead the choice is threaded in as an action
parameter, the same `tap_choices`/`sacrifice_choice` shape the mana-tap and
sacrifice-cost paths already used (`GameEngine._resolve_tap_others`/
`_sacrifice_candidate`). This adds the `discard_choices` counterpart and
extends `sacrifice_choice`/the new `discard_choices` onto `can_cast`/
`cast_spell`'s own additional-cost payment.

Reference: mtg_analyzer/game/game_engine.py (`_resolve_discard_cost`,
`_can_pay_additional_cast_cost`, `_pay_additional_cast_cost`,
`_can_pay_activation_cost`, `_pay_activation_cost`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.costs import ActivationCost
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost


def creature(name="Bear", cost="{1}{G}", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True, power=power, toughness=toughness,
    )


def instant(name="Spell", cost="{1}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _in_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


# -- additional cast cost: sacrifice (RULE 601.2b) ---------------------------


def test_additional_cost_sacrifice_honours_an_explicit_choice():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    bear = _bf(eng, creature("Bear"))
    wolf = _bf(eng, creature("Wolf"))
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(sacrifice="creature")
    p1.mana_pool.add("C", 1)

    eng.cast_spell(p1, spell, sacrifice_choice=wolf.instance_id)

    assert wolf in p1.graveyard
    assert bear in eng.state.battlefield


def test_additional_cost_sacrifice_rejects_an_invalid_choice():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _bf(eng, creature("Bear"))
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(sacrifice="creature")
    p1.mana_pool.add("C", 1)

    assert not eng.can_cast(p1, spell, sacrifice_choice=999999)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, sacrifice_choice=999999)


# -- additional cast cost: discard (RULE 601.2b) ------------------------------


def test_additional_cost_discard_honours_an_explicit_choice():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(discard=2)
    a = _in_hand(eng, creature("A"))
    b = _in_hand(eng, creature("B"))
    c = _in_hand(eng, creature("C"))
    p1.mana_pool.add("C", 1)

    eng.cast_spell(p1, spell, discard_choices=[a.instance_id, c.instance_id])

    assert a in p1.graveyard and c in p1.graveyard
    assert b in p1.hand


def test_additional_cost_discard_rejects_the_wrong_count():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(discard=2)
    a = _in_hand(eng, creature("A"))
    _in_hand(eng, creature("B"))
    p1.mana_pool.add("C", 1)

    assert not eng.can_cast(p1, spell, discard_choices=[a.instance_id])


def test_additional_cost_discard_excludes_the_spell_itself():
    # RULE 601.2b: the spell being cast is still in hand at payment time but
    # isn't a legal discard candidate for its own cost.
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(discard=1)
    p1.mana_pool.add("C", 1)

    assert not eng.can_cast(p1, spell, discard_choices=[spell.instance_id])


def test_additional_cost_discard_falls_back_to_auto_pick_without_a_choice():
    # Non-interactive callers (tests, the goldfish auto-player) still work:
    # `None` (the default) auto-picks, unchanged from before ENG-3.
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = _in_hand(eng, instant())
    spell.additional_cast_cost = ActivationCost(discard=1)
    a = _in_hand(eng, creature("A"))
    p1.mana_pool.add("C", 1)

    eng.cast_spell(p1, spell)

    assert a in p1.graveyard
    assert len(p1.hand) == 0


# -- activated ability discard cost (RULE 602.1) ------------------------------


def test_activated_ability_discard_cost_honours_an_explicit_choice():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    source = _bf(eng, creature("Looter"))
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=ActivationCost(discard=1),
        source=source,
    )
    source.activated_abilities.append(ability)
    a = _in_hand(eng, creature("A"))
    b = _in_hand(eng, creature("B"))

    assert eng.can_activate(p1, source, ability, discard_choices=[b.instance_id])
    eng.activate_ability(p1, source, discard_choices=[b.instance_id])

    assert b in p1.graveyard
    assert a in p1.hand
