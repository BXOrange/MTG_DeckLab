"""ENG-69 -- RULE 118.9 / 601.2b-h: the caster picks which hand cards a pitch or land-discard alternative cost spends and
which untapped permanents a tap alternative cost taps (Force of Will / Vigor / Negation, Commandeer, Abolish, Sephara,
Angelic Favor), through the same resumable `cast_alt_cost_object` choice ENG-65 introduced."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.catalogue import two_player_game
from tests.test_eng65_alt_cost_payment_choice import (
    CHOICE_KIND, card, cast_alt, main_phase, option_ids, stack_spell,
)


def ids(*objs):
    return sorted(o.instance_id for o in objs)


def force_of_will_board():
    engine, p1 = two_player_game()
    main_phase(engine)
    fow = card(engine, "Force of Will", Zone.HAND)
    blues = [card(engine, "Counterspell", Zone.HAND), card(engine, "Brainstorm", Zone.HAND),
             card(engine, "Opt", Zone.HAND)]
    red = card(engine, "Lightning Bolt", Zone.HAND)
    return engine, p1, fow, blues, red


def test_force_of_will_asks_which_blue_card_and_never_offers_itself():
    engine, p1, fow, blues, red = force_of_will_board()
    target = stack_spell(engine)
    life = p1.life
    cast_alt(engine, p1, fow, targets=[target])
    pending = engine.state.pending_choice
    assert pending["kind"] == CHOICE_KIND and pending["player_id"] == "p1"
    assert sorted(option_ids(engine)) == ids(*blues)  # not the red card, not Force of Will itself
    assert all(b.zone == Zone.HAND for b in blues) and fow.zone == Zone.HAND  # nothing paid yet
    engine.resolve_pending_choice(str(blues[2].instance_id))  # the last one, not the engine's first
    engine.resolve_until_stable()
    assert blues[2].zone == Zone.EXILE and blues[0].zone == Zone.HAND and blues[1].zone == Zone.HAND
    assert red.zone == Zone.HAND and p1.life == life - 1
    assert target.zone == Zone.GRAVEYARD


def test_force_of_will_with_exactly_one_blue_card_is_forced():
    engine, p1 = two_player_game()
    main_phase(engine)
    fow = card(engine, "Force of Will", Zone.HAND)
    only = card(engine, "Counterspell", Zone.HAND)
    cast_alt(engine, p1, fow, targets=[stack_spell(engine)])
    assert engine.state.pending_choice is None
    assert only.zone == Zone.EXILE


def test_force_of_will_alone_in_hand_is_unpayable():
    engine, p1 = two_player_game()
    main_phase(engine)
    fow = card(engine, "Force of Will", Zone.HAND)
    card(engine, "Lightning Bolt", Zone.HAND)
    assert not engine.can_cast(p1, fow, alt_cost=True)
    with pytest.raises(ValueError):
        cast_alt(engine, p1, fow, targets=[stack_spell(engine)])
    assert fow.zone == Zone.HAND and engine.state.pending_choice is None


def test_pitched_card_is_public_in_exile_and_prompt_is_caster_only():
    from mtg_analyzer.services.game_session import GameSession
    engine, p1, fow, blues, red = force_of_will_board()
    stack_spell(engine)
    session = GameSession(engine, require_setup=False)
    cast = next(a for a in session.legal_actions("p1")
                if a["type"] == "cast_spell" and a.get("alt_cost") and a.get("instance_id") == fow.instance_id)
    session.apply_action(cast, "p1")
    assert session.view("p1")["pending_choice"]["kind"] == CHOICE_KIND
    assert session.view("p2")["pending_choice"] is None  # the opponent only sees a "waiting" marker
    answers = [a for a in session.legal_actions("p1") if a["type"] == "choose"]
    assert {a["instance_id"] for a in answers} == set(ids(*blues))
    assert not [a for a in session.legal_actions("p2") if a["type"] == "choose"]
    session.apply_action(answers[1], "p1")
    pitched = session.engine.state.find_object(answers[1]["instance_id"])
    assert pitched.zone == Zone.EXILE


def test_force_of_vigor_pitches_the_chosen_green_card_among_several():
    engine, p1 = two_player_game()
    main_phase(engine)
    engine.state.active_player_index = 1  # alt-cost condition: not your turn
    fov = card(engine, "Force of Vigor", Zone.HAND)
    greens = [card(engine, "Giant Growth", Zone.HAND), card(engine, "Llanowar Elves", Zone.HAND),
              card(engine, "Rampant Growth", Zone.HAND)]
    card(engine, "Counterspell", Zone.HAND)
    assert engine.can_cast(p1, fov, alt_cost=True)
    cast_alt(engine, p1, fov)
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == ids(*greens)
    engine.resolve_pending_choice(str(greens[2].instance_id))
    assert engine.state.pending_choice is None  # Force of Vigor pitches exactly one green card
    assert greens[2].zone == Zone.EXILE and greens[1].zone == Zone.HAND and greens[0].zone == Zone.HAND


def test_force_of_negation_off_turn_pitches_the_chosen_blue_card():
    engine, p1 = two_player_game()
    main_phase(engine)
    engine.state.active_player_index = 1
    fon = card(engine, "Force of Negation", Zone.HAND)
    blues = [card(engine, "Brainstorm", Zone.HAND), card(engine, "Opt", Zone.HAND)]
    spell = stack_spell(engine)
    cast_alt(engine, p1, fon, targets=[spell])
    assert sorted(option_ids(engine)) == ids(*blues)
    engine.resolve_pending_choice(str(blues[1].instance_id))
    assert blues[1].zone == Zone.EXILE and blues[0].zone == Zone.HAND


def test_commandeer_exiles_the_two_chosen_blue_cards():
    engine, p1 = two_player_game()
    main_phase(engine)
    cmd = card(engine, "Commandeer", Zone.HAND)
    blues = [card(engine, "Counterspell", Zone.HAND), card(engine, "Opt", Zone.HAND),
             card(engine, "Brainstorm", Zone.HAND)]
    card(engine, "Lightning Bolt", Zone.HAND)
    target = stack_spell(engine)
    cast_alt(engine, p1, cmd, targets=[target])
    assert sorted(option_ids(engine)) == ids(*blues)
    engine.resolve_pending_choice(str(blues[2].instance_id))
    assert sorted(option_ids(engine)) == ids(blues[0], blues[1])
    engine.resolve_pending_choice(str(blues[0].instance_id))
    assert blues[2].zone == Zone.EXILE and blues[0].zone == Zone.EXILE and blues[1].zone == Zone.HAND


def test_commandeer_with_exactly_two_blue_cards_is_forced():
    engine, p1 = two_player_game()
    main_phase(engine)
    cmd = card(engine, "Commandeer", Zone.HAND)
    blues = [card(engine, "Counterspell", Zone.HAND), card(engine, "Opt", Zone.HAND)]
    cast_alt(engine, p1, cmd, targets=[stack_spell(engine)])
    assert engine.state.pending_choice is None
    assert all(b.zone == Zone.EXILE for b in blues)


def test_abolish_discards_the_chosen_plains_only():
    engine, p1 = two_player_game()
    main_phase(engine)
    abolish = card(engine, "Abolish", Zone.HAND)
    plains = [card(engine, "Plains", Zone.HAND) for _ in range(3)]
    island = card(engine, "Island", Zone.HAND)
    from mtg_analyzer.game.cast_alt_cost_payment import announced_alt_cost, plan_picks
    cost = announced_alt_cost(engine, p1, abolish, {"alt_cost": True})
    picks, options = plan_picks(engine, p1, abolish, cost, [])
    assert sorted(o.instance_id for o in options) == ids(*plains) and island not in options
    cast_alt(engine, p1, abolish, targets=[card(engine, "Bad Moon", owner="p2")])
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    engine.resolve_pending_choice(str(plains[1].instance_id))
    assert plains[1].zone == Zone.GRAVEYARD and plains[0].zone == Zone.HAND and island.zone == Zone.HAND


def sephara_board(extra_flyers=1):
    engine, p1 = two_player_game()
    main_phase(engine)
    sephara = card(engine, "Sephara, Sky's Blade", Zone.HAND)
    flyers = [card(engine, "Serra Angel") for _ in range(4 + extra_flyers)]
    ground = card(engine, "Grizzly Bears")
    enemy = card(engine, "Serra Angel", owner="p2")
    p1.mana_pool.add("W", 1)
    engine.recompute_continuous_effects()
    return engine, p1, sephara, flyers, ground, enemy


def test_sephara_taps_the_four_chosen_flyers_among_more():
    engine, p1, sephara, flyers, ground, enemy = sephara_board(extra_flyers=2)
    flyers[0].tapped = True  # a tapped flyer is never offered
    assert engine.can_cast(p1, sephara, alt_cost=True)
    cast_alt(engine, p1, sephara)
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert sorted(option_ids(engine)) == ids(*flyers[1:])  # untapped own flyers: not the ground bear, not the enemy
    engine.resolve_pending_choice(str(flyers[5].instance_id))
    engine.resolve_pending_choice(str(flyers[1].instance_id))
    engine.resolve_pending_choice(str(flyers[2].instance_id))
    engine.resolve_pending_choice(str(flyers[4].instance_id))
    assert engine.state.pending_choice is None
    assert [f.tapped for f in flyers] == [True, True, True, False, True, True]  # flyers[3] was never picked
    assert not ground.tapped and not enemy.tapped


def test_sephara_with_exactly_four_untapped_flyers_asks_nothing():
    engine, p1, sephara, flyers, *_ = sephara_board(extra_flyers=0)
    cast_alt(engine, p1, sephara)
    assert engine.state.pending_choice is None and all(f.tapped for f in flyers)


def test_sephara_unpayable_with_three_untapped_flyers():
    engine, p1, sephara, flyers, *_ = sephara_board(extra_flyers=0)
    flyers[0].tapped = True
    assert not engine.can_cast(p1, sephara, alt_cost=True)
    assert not any(f.tapped for f in flyers[1:])


# ---------------------------------------------------------------------------
# Resumability: clone, wrong answers, explicit picks, bots.
# ---------------------------------------------------------------------------

def test_pending_pitch_survives_clone_and_undo_snapshot():
    engine, p1, fow, blues, red = force_of_will_board()
    target = stack_spell(engine)
    snapshot = engine.state.clone()
    cast_alt(engine, p1, fow, targets=[target])
    restored = GameEngine(engine.state.clone())
    assert restored.state.pending_choice["kind"] == CHOICE_KIND
    restored.resolve_pending_choice(str(blues[0].instance_id))
    restored.resolve_until_stable()
    assert restored.state.find_object(blues[0].instance_id).zone == Zone.EXILE
    assert blues[0].zone == Zone.HAND and engine.state.pending_choice is not None  # the live game still waits
    rewound = GameEngine(snapshot)  # session undo restores the pre-cast clone
    assert rewound.state.pending_choice is None
    assert rewound.state.find_object(fow.instance_id).zone == Zone.HAND
    assert all(rewound.state.find_object(b.instance_id).zone == Zone.HAND for b in blues)


def test_answer_outside_the_pool_reasks_without_paying():
    engine, p1, fow, blues, red = force_of_will_board()
    cast_alt(engine, p1, fow, targets=[stack_spell(engine)])
    engine.resolve_pending_choice(str(red.instance_id))
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    engine.resolve_pending_choice(str(fow.instance_id))  # the spell itself is not a candidate
    assert engine.state.pending_choice["kind"] == CHOICE_KIND
    assert all(c.zone == Zone.HAND for c in blues + [red, fow])


def test_explicit_picks_are_validated():
    engine, p1, fow, blues, red = force_of_will_board()
    target = stack_spell(engine)
    with pytest.raises(ValueError):
        cast_alt(engine, p1, fow, targets=[target], alt_cost_choices=[red.instance_id])
    with pytest.raises(ValueError):
        cast_alt(engine, p1, fow, targets=[target], alt_cost_choices=[fow.instance_id])
    assert all(c.zone == Zone.HAND for c in blues)
    cast_alt(engine, p1, fow, targets=[target], alt_cost_choices=[blues[1].instance_id])
    assert engine.state.pending_choice is None and blues[1].zone == Zone.EXILE


def test_bot_answers_the_pitch_choice():
    from mtg_analyzer.services.bot_policies.base import Bot
    engine, p1, fow, blues, red = force_of_will_board()
    cast_alt(engine, p1, fow, targets=[stack_spell(engine)])
    pending = engine.state.pending_choice
    bot = Bot.__new__(Bot)
    view = {"pending_choice": pending, "state": {"battlefield": [], "players": []}}
    answers = [{"type": "choose", "option_id": o["id"], "instance_id": o["instance_id"], "name": o["label"]}
               for o in pending["options"]]
    picked = Bot.answer_choice(bot, view, answers)
    assert int(picked["option_id"]) in {b.instance_id for b in blues}
    engine.resolve_pending_choice(picked["option_id"])
    engine.resolve_until_stable()
    assert engine.state.find_object(int(picked["option_id"])).zone == Zone.EXILE


def test_session_wire_answers_a_tap_choice():
    from mtg_analyzer.services.game_session import GameSession
    engine, p1, sephara, flyers, *_ = sephara_board(extra_flyers=1)
    session = GameSession(engine, require_setup=False)
    cast = next(a for a in session.legal_actions("p1")
                if a["type"] == "cast_spell" and a.get("alt_cost") and a.get("instance_id") == sephara.instance_id)
    session.apply_action(cast, "p1")
    answers = [a for a in session.legal_actions("p1") if a["type"] == "choose"]
    assert {a["instance_id"] for a in answers} == set(ids(*flyers))
    kept = flyers[0].instance_id
    for _ in range(4):
        answers = [a for a in session.legal_actions("p1") if a["type"] == "choose" and a["instance_id"] != kept]
        session.apply_action(answers[0], "p1")
    live = {f.instance_id: session.engine.state.find_object(f.instance_id) for f in flyers}
    assert sum(f.tapped for f in live.values()) == 4 and not live[kept].tapped
