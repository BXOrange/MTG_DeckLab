"""Blufferfish, Smart Ass, Gollum Scheming Guide, Kamiz Obscura Oculus, Sewers of Estark (singletons Batch 1)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object
from tests.test_weathered_sentinels import _to

CARDS = ["Blufferfish", "Smart Ass", "Gollum, Scheming Guide", "Kamiz, Obscura Oculus", "Sewers of Estark"]


def _creature(engine, name, player="p1", power=2, toughness=2):
    obj = battlefield_object(engine, player, name, "Creature", is_creature=True, power=power, toughness=toughness)
    obj.summoning_sick = False
    return obj


def _attack(engine, attackers, defender="p2"):
    _to(engine, "p1", "declare_attackers")
    engine.declare_attackers(engine.state.player_by_id("p1"), [
        {"attacker": a, "defender": engine.state.player_by_id(defender)} for a in attackers
    ])


def _answer_all(engine, answers):
    """Resolve the stack, answering each open choice from ``answers`` (kind or note -> option id); the first option
    otherwise. Returns the list of (player_id, note-or-kind) asked, in order."""
    asked = []
    for _ in range(20):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if not choice:
            return asked
        key = choice.get("note") or choice["kind"]
        asked.append((choice["player_id"], key))
        engine.resolve_pending_choice(answers.get(key, choice["options"][0]["id"]))
    raise AssertionError(f"choices never ended: {asked}")


@pytest.mark.parametrize("name", CARDS)
def test_registered_and_fresh_each_call(name):
    obj = _card(_game(), name, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first[0] is not second[0]


# --- Blufferfish ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("secret,guess,right", [("true", "true", True), ("false", "false", True),
                                                 ("true", "false", False), ("false", "true", False)])
def test_blufferfish_pumps_and_evades_only_on_a_correct_guess(secret, guess, right):
    engine = _game()
    fish = _card(engine, "Blufferfish")
    for _ in range(4):
        _card(engine, "Island")
    _to(engine, "p1", "main1")
    engine.activate_ability(engine.state.player_by_id("p1"), fish)
    engine.resolve_until_stable()
    opened = engine.state.pending_choice
    assert opened["player_id"] == "p2" and opened["note"] == "secret"
    engine.resolve_pending_choice(secret)
    guessing = engine.state.pending_choice
    # The guesser's choice never carries the opponent's note (RULE 400.2): only the generic two options.
    assert guessing["player_id"] == "p1" and guessing["note"] == "guess"
    assert secret not in {k: v for k, v in guessing.items() if k != "options"}.values()
    engine.resolve_pending_choice(guess)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert bool(fish.temp_unblockable) is right
    assert fish.power == fish.card.power + (2 if right else 0)


def test_blufferfish_hidden_note_is_absent_from_game_object_view():
    engine = _game()
    fish = _card(engine, "Blufferfish")
    fish.guess_notes["secret"] = "true"
    assert "guess_notes" not in fish.to_dict()


# --- Sewers of Estark -------------------------------------------------------------------------------------------


def _sewers_position():
    engine = _game()
    attacker = _creature(engine, "Attacker", power=3, toughness=3)
    other = _creature(engine, "Other", power=2, toughness=2)
    blocker = _creature(engine, "Blocker", player="p2", power=2, toughness=4)
    _attack(engine, [attacker, other])
    engine.advance_step()
    engine.declare_blockers(engine.state.player_by_id("p2"), [(blocker, attacker)])
    return engine, attacker, other, blocker


def _cast_sewers(engine, target, player="p1"):
    for _ in range(4):
        _card(engine, "Swamp", player=player)
    spell = _card(engine, "Sewers of Estark", player=player, zone=Zone.HAND)
    engine.cast_spell(engine.state.player_by_id(player), spell, targets=[target])
    engine.resolve_until_stable()


def test_sewers_on_blocking_creature_prevents_damage_dealt_by_it_and_what_it_blocks():
    engine, attacker, other, blocker = _sewers_position()
    _cast_sewers(engine, blocker, player="p2")
    assert blocker.__dict__.get("temp_prevent_combat_damage_dealt") and attacker.__dict__.get("temp_prevent_combat_damage_dealt")
    assert not other.__dict__.get("temp_prevent_combat_damage_dealt") and not blocker.temp_unblockable


def test_sewers_on_attacking_creature_makes_it_unblockable_and_prevents_nothing():
    engine = _game()
    attacker = _creature(engine, "Attacker")
    _attack(engine, [attacker])
    _cast_sewers(engine, attacker)
    assert attacker.temp_unblockable and not attacker.__dict__.get("temp_prevent_combat_damage_dealt")


def test_sewers_on_an_idle_creature_does_nothing():
    engine = _game()
    idle = _creature(engine, "Idle")
    _to(engine, "p1", "main1")
    _cast_sewers(engine, idle)
    assert not idle.temp_unblockable and not idle.__dict__.get("temp_prevent_combat_damage_dealt")


# --- Kamiz, Obscura Oculus --------------------------------------------------------------------------------------


def test_kamiz_unblockable_connive_then_double_strike_to_a_lesser_attacker():
    engine = _game()
    _card(engine, "Kamiz, Obscura Oculus")
    big = _creature(engine, "Big", power=3, toughness=3)
    small = _creature(engine, "Small", power=1, toughness=1)
    equal = _creature(engine, "Equal", power=3, toughness=3)
    _card(engine, "Grizzly Bears", zone=Zone.HAND)  # connive discards a nonland card: +1/+1 counter on the target
    _attack(engine, [big, small, equal])
    engine.advance_step()  # RULE 508.1: ATTACKERS_DECLARED ("whenever you attack") fires as the declaration step ends
    asked = _answer_all(engine, {})
    assert big.temp_unblockable
    # Only an attacker with power below the target's may be picked: never the target, never the equal-power one.
    doubled = [o for o in (big, small, equal) if {"double strike", "double_strike"} & set(o.temp_keywords)]
    assert doubled == [small], (asked, doubled)


# --- Gollum, Scheming Guide -------------------------------------------------------------------------------------


def _gollum_game(top_is_land):
    engine = _game()
    gollum = _card(engine, "Gollum, Scheming Guide")
    gollum.summoning_sick = False
    if not top_is_land:
        _card(engine, "Grizzly Bears", zone=Zone.LIBRARY)
    return engine, gollum


@pytest.mark.parametrize("top_is_land,kind,guess,right", [
    (True, "land", "land", True), (True, "land", "nonland", False),
    (False, "land", "land", False), (False, "nonland", "nonland", True),
    (True, "nonland", "nonland", False),
])
def test_gollum_guess_outcomes(top_is_land, kind, guess, right):
    engine, gollum = _gollum_game(top_is_land)
    hand_before = len(engine.state.player_by_id("p1").hand)
    _attack(engine, [gollum])
    # The opponent's yes/no is stored as the kind it predicts; "guess" here is that predicted kind.
    asked = _answer_all(engine, {"kind": kind, "guess": guess})
    assert ("p2", "guess") in asked
    drew = len(engine.state.player_by_id("p1").hand) - hand_before
    if right:  # RULE 506.4: removed from combat, no card
        assert not gollum.attacking and drew == 0 and not gollum.temp_unblockable
    else:
        assert gollum.attacking and gollum.temp_unblockable and drew == 1


# --- Smart Ass --------------------------------------------------------------------------------------------------


def _smart_ass_game(hand_card):
    engine = _game()
    ass = _card(engine, "Smart Ass")
    ass.summoning_sick = False
    if hand_card:
        _card(engine, hand_card, player="p2", zone=Zone.HAND)
    return engine, ass


def test_smart_ass_defender_declines_to_reveal_so_it_is_unblockable():
    engine, ass = _smart_ass_game(None)
    _attack(engine, [ass])
    engine.resolve_until_stable()
    named = engine.state.pending_choice
    assert named["player_id"] == "p1"
    engine.resolve_pending_choice("Lightning Bolt")
    engine.resolve_until_stable()
    asked = engine.state.pending_choice
    assert asked["player_id"] == "p2"
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert ass.temp_unblockable


def test_smart_ass_defender_reveals_hand_publicly():
    engine, ass = _smart_ass_game("Grizzly Bears")
    _attack(engine, [ass])
    engine.resolve_until_stable()
    engine.resolve_pending_choice("Lightning Bolt")
    engine.resolve_until_stable()
    engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    assert not ass.temp_unblockable
    assert engine.state.public_card_knowledge.cards


def test_smart_ass_defender_holding_the_named_card_is_never_asked():
    engine, ass = _smart_ass_game("Grizzly Bears")
    _attack(engine, [ass])
    engine.resolve_until_stable()
    engine.resolve_pending_choice("Grizzly Bears")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert not ass.temp_unblockable
