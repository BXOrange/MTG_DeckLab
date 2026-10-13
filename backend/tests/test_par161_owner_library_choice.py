"""PAR-161 -- "<Target>'s owner puts it on their choice of the top or bottom of their library." (RULE 401.4).

Parser side: the "the owner of target X" / "target X's owner" forms bind to `owner_puts_on_top_or_bottom`.  Engine side: the
*owner* (not the caster) answers a `library_position` choice, and the card lands on the chosen end of that owner's library.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from tests.support.deck_batch import cast, filler, game, stack_library

OWNER_FIRST = "Target creature's owner puts it on their choice of the top or bottom of their library."
OWNER_OF = "The owner of target nonland permanent puts it on their choice of the top or bottom of their library."
OWNER_OF_SPELL = "The owner of target spell or nonland permanent puts it on their choice of the top or bottom of their library."
WITH_SCRY = OWNER_OF + " Scry 2."


def _spell_card(text):
    return Card(id="Src", name="Src", type_line="Instant", is_instant=True, oracle_text=text)


@pytest.mark.parametrize("text", [OWNER_FIRST, OWNER_OF, OWNER_OF_SPELL, WITH_SCRY])
def test_clause_is_modeled(text):
    assert parse_oracle(_spell_card(text)).coverage == MODELED


@pytest.mark.parametrize("text", [
    "Target attacking creature's owner puts it on their choice of the top or bottom of their library.",
    "Target creature that's tapped's owner puts it on their choice of the top or bottom of their library.",
])
def test_unresolvable_target_stays_unclaimed(text):
    assert parse_oracle(_spell_card(text)).coverage != MODELED


def _board(text):
    engine = game()
    spell = filler(engine, "Setback", type_line="Instant", player="p1", zone=Zone.HAND, oracle_text=text)
    victim = filler(engine, "Victim", power=2, toughness=2, player="p2")
    return engine, spell, victim


@pytest.mark.parametrize("answer_id, expect_top", [("top", True), ("bottom", False)])
def test_opponent_owner_chooses_the_end(answer_id, expect_top):
    engine, spell, victim = _board(OWNER_FIRST)
    cast(engine, spell, targets=[victim])
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p2"
    engine.resolve_pending_choice(answer_id)
    library = engine.state.player_by_id("p2").library
    assert victim.zone == Zone.LIBRARY
    assert (library[-1] is victim) == expect_top and (library[0] is victim) == (not expect_top)
    assert engine.state.pending_choice is None


def test_own_permanent_is_chosen_by_its_owner_the_caster():
    engine, spell, _ = _board(OWNER_FIRST)
    mine = filler(engine, "Mine", power=1, toughness=1, player="p1")
    cast(engine, spell, targets=[mine])
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice("bottom")
    assert engine.state.player_by_id("p1").library[0] is mine


def test_stolen_permanent_goes_to_its_owner_not_its_controller():
    engine, spell, victim = _board(OWNER_FIRST)
    victim.owner_id, victim.controller_id = "p1", "p2"  # p2 controls a creature p1 owns
    cast(engine, spell, targets=[victim])
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice("top")
    assert engine.state.player_by_id("p1").library[-1] is victim


def test_spell_target_leaves_the_stack_for_the_owners_library():
    engine, spell, _ = _board(OWNER_OF_SPELL)
    theirs = filler(engine, "Their Instant", type_line="Instant", mv=2, player="p2", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    from tests.support.deck_batch import main_phase
    main_phase(engine)
    p2.mana_pool.add_many({"C": 2})
    engine.cast_spell(p2, theirs)
    cast(engine, spell, targets=[engine.state.stack[0]])
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("bottom")
    assert theirs.zone == Zone.LIBRARY and p2.library[0] is theirs
    assert not [i for i in engine.state.stack if i.obj is theirs]


def test_trailing_clause_still_resolves_after_the_choice():
    engine, spell, victim = _board(WITH_SCRY)
    stack_library(engine, "p1", filler(engine, "L1", zone=Zone.LIBRARY), filler(engine, "L2", zone=Zone.LIBRARY))
    cast(engine, spell, targets=[victim])
    assert engine.state.pending_choice["kind"] == "library_position"
    engine.resolve_pending_choice("top")
    kinds = []
    while engine.state.pending_choice is not None and len(kinds) < 6:
        kinds.append(engine.state.pending_choice["kind"])
        engine.resolve_pending_choice(None)
    assert any("scry" in k for k in kinds), kinds


# --- milestone 2: the controller chooses, and the odd target shapes --------------------------------------------------

@pytest.mark.parametrize("name", [
    "Not Forgotten", "Arashin Sovereign", "Swat Away", "Guidance Failure", "Aether Gust", "Subtlety", "Hinder",
])
def test_milestone_two_cards_are_claimed(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.card_registry import is_registered
    from mtg_analyzer.services.card_database import CardDatabase

    card_obj = CardDatabase(DB_PATH).get_card(name)
    assert is_registered(name) or parse_oracle(card_obj).coverage == MODELED


def test_not_forgotten_controller_picks_the_end_of_the_owners_library():
    from tests.support.deck_batch import card
    engine = game()
    spell = card(engine, "Not Forgotten", player="p1", zone=Zone.HAND)
    theirs = filler(engine, "Their Dead", player="p2", zone=Zone.GRAVEYARD)
    p2 = engine.state.player_by_id("p2")
    cast(engine, spell, targets=[theirs])
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p1"  # the caster, not the owner
    engine.resolve_pending_choice("bottom")
    assert theirs.zone == Zone.LIBRARY and p2.library[0] is theirs
    tokens = [o for o in engine.state.permanents() if o.is_token and o.controller_id == "p1"]
    assert len(tokens) == 1  # the Spirit rider still resolves after the choice


@pytest.mark.parametrize("answer_id", ["top", "bottom", "decline"])
def test_arashin_sovereign_dies_trigger_you_may(answer_id):
    from tests.support.deck_batch import card
    engine = game()
    sovereign = card(engine, "Arashin Sovereign", player="p1")
    engine.rules.destroy(sovereign)
    engine.resolve_until_stable()
    prompt = engine.state.pending_choice
    assert prompt["kind"] == "trigger_target" and {o["id"] for o in prompt["options"]} == {"do", "decline"}  # "you may"
    if answer_id == "decline":
        engine.resolve_pending_choice("decline")
        assert engine.state.pending_choice is None
    else:
        engine.resolve_pending_choice("do")
        choice = engine.state.pending_choice
        assert choice["kind"] == "library_position" and choice["player_id"] == "p1"
        engine.resolve_pending_choice(answer_id)
    library = engine.state.player_by_id("p1").library
    if answer_id == "decline":
        assert sovereign.zone == Zone.GRAVEYARD
    else:
        assert sovereign.zone == Zone.LIBRARY
        assert (library[-1] is sovereign) == (answer_id == "top")


def _opponent_spell(engine, name="Their Spell", type_line="Instant"):
    from tests.support.deck_batch import main_phase
    theirs = filler(engine, name, type_line=type_line, mv=2, player="p2", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    main_phase(engine)
    engine.state.active_player_index = engine.state.players.index(p2)  # a creature spell needs their own main phase
    p2.mana_pool.add_many({"C": 2})
    engine.cast_spell(p2, theirs)
    return theirs


def test_hinder_caster_puts_the_countered_card_in_the_owners_library():
    from tests.support.deck_batch import card
    engine = game()
    theirs = _opponent_spell(engine)
    hinder = card(engine, "Hinder", player="p1", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 3})
    engine.cast_spell(p1, hinder, targets=[engine.state.stack[0]])
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p1"
    engine.resolve_pending_choice("bottom")
    p2 = engine.state.player_by_id("p2")
    assert theirs.zone == Zone.LIBRARY and p2.library[0] is theirs
    assert theirs not in p2.graveyard
    assert not [i for i in engine.state.stack if i.obj is theirs]


def test_hinder_does_not_ask_when_the_spell_cannot_be_countered():
    from tests.support.deck_batch import card
    engine = game()
    theirs = _opponent_spell(engine)
    engine.rules._is_cant_be_countered = lambda obj: obj is theirs  # RULE 701.5b: the counter does nothing
    hinder = card(engine, "Hinder", player="p1", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 3})
    engine.cast_spell(p1, hinder, targets=[engine.state.stack[0]])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and theirs.zone != Zone.LIBRARY


def test_aether_gust_only_offers_red_or_green_objects():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets
    engine = game()
    red = filler(engine, "Red Bear", power=2, toughness=2, player="p2", color_identity={"R"})
    filler(engine, "Blue Bear", power=2, toughness=2, player="p2", color_identity={"U"})
    filler(engine, "Green Land", type_line="Land", player="p2", color_identity={"G"})
    spec = TargetSpec(kind="spell_or_permanent", colors=("R", "G"))
    names = {t["name"] for t in legal_targets(engine.state, "p1", spec)}
    assert names == {"Red Bear", "Green Land"}


def test_aether_gust_resolves_with_the_owners_choice():
    from tests.support.deck_batch import card
    engine = game()
    red = filler(engine, "Red Bear", power=2, toughness=2, player="p2", color_identity={"R"})
    gust = card(engine, "Aether Gust", player="p1", zone=Zone.HAND)
    cast(engine, gust, targets=[red])
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("top")
    assert red.zone == Zone.LIBRARY


def test_guidance_failure_targets_a_spacecraft_and_its_owner_chooses():
    from tests.support.deck_batch import card
    engine = game()
    ship = filler(engine, "Ship", type_line="Artifact — Spacecraft", player="p2")
    spell = card(engine, "Guidance Failure", player="p1", zone=Zone.HAND)
    cast(engine, spell, targets=[ship])
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("bottom")
    assert ship.zone == Zone.LIBRARY


def test_subtlety_offers_only_creature_and_planeswalker_spells():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets
    engine = game()
    _opponent_spell(engine, "Their Bear", type_line="Creature")
    spec = TargetSpec(kind="spell", spell_filter={"card_types": ["creature", "planeswalker"]})
    assert [t["name"] for t in legal_targets(engine.state, "p1", spec)] == ["Their Bear"]
    engine2 = game()
    _opponent_spell(engine2, "Their Bolt", type_line="Instant")
    assert not legal_targets(engine2.state, "p1", spec)


def test_subtlety_enters_trigger_hands_the_spell_to_its_owner():
    from tests.support.deck_batch import put_on_battlefield
    engine = game()
    theirs = _opponent_spell(engine, "Their Bear", type_line="Creature")
    put_on_battlefield(engine, "Subtlety", "p1")
    choice = engine.state.pending_choice
    assert choice is not None, "the enters trigger never asked for a target or a position"
    if choice["kind"] != "library_position":
        engine.resolve_pending_choice(theirs.instance_id)  # the target pick
        choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p2"
    engine.resolve_pending_choice("top")
    assert theirs.zone == Zone.LIBRARY


def test_swat_away_costs_two_less_while_a_creature_attacks_you():
    from mtg_analyzer.game.static_conditions import condition_holds
    from tests.support.deck_batch import attack
    engine = game()
    cond = {"kind": "creature_attacking_you"}
    assert not condition_holds(cond, engine.state, None, "p2")
    bear = filler(engine, "Attacker", power=2, toughness=2, player="p1")
    attack(engine, [bear])
    assert condition_holds(cond, engine.state, None, "p2")
    assert not condition_holds(cond, engine.state, None, "p1")  # it attacks p2, not the attacker


def test_swat_away_cast_cost_drops_by_two_only_while_attacked():
    from tests.support.deck_batch import attack, card
    engine = game()
    swat = card(engine, "Swat Away", player="p2", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    assert engine.effective_cast_cost(p2, swat).converted_mana_cost == 4
    attack(engine, [filler(engine, "Attacker", power=2, toughness=2, player="p1")])
    assert engine.effective_cast_cost(p2, swat).converted_mana_cost == 2
