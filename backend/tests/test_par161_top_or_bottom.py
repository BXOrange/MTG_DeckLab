"""PAR-161: "its owner puts it on their choice of the top or bottom of their library" (RULE 401.4) and the
"put it on *your* choice of the top or bottom of its owner's library" siblings, parsed onto
`owner_puts_on_top_or_bottom`; Hinder is the hand-authored counter-replacement form."""
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import (
    card, cast, filler, game, main_phase, put_on_battlefield,
)

OWNER = "p2"


def _lib(engine, player=OWNER):
    return engine.state.player_by_id(player).library


def _choice(engine, player):
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "library_position" and choice["player_id"] == player
    return choice


def test_creature_target_owner_not_controller_chooses_bottom():
    engine = game()
    spell = card(engine, "Run Behind", zone=Zone.HAND)
    victim = filler(engine, "Victim", power=2, toughness=2, player=OWNER)
    cast(engine, spell, targets=[victim])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("bottom")
    assert victim.zone == Zone.LIBRARY and _lib(engine)[0] is victim


def test_creature_target_top_choice_and_stolen_creature_goes_to_its_owner():
    engine = game()
    spell = card(engine, "Misleading Motes", zone=Zone.HAND)
    victim = filler(engine, "Victim", power=2, toughness=2, player=OWNER)
    victim.controller_id = "p1"  # stolen: p1 controls it, p2 still owns it
    cast(engine, spell, targets=[victim])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("top")
    assert victim.zone == Zone.LIBRARY and _lib(engine)[-1] is victim


def test_trailing_clause_runs_after_the_choice_vanish_from_sight_surveils():
    engine = game()
    spell = card(engine, "Vanish from Sight", zone=Zone.HAND)
    perm = filler(engine, "Relic", type_line="Artifact", player=OWNER)
    cast(engine, spell, targets=[perm])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("bottom")
    assert perm.zone == Zone.LIBRARY


def test_token_clause_is_not_lost_revenge_of_the_drowned():
    engine = game()
    spell = card(engine, "Revenge of the Drowned", zone=Zone.HAND)
    victim = filler(engine, "Victim", power=2, toughness=2, player=OWNER)
    cast(engine, spell, targets=[victim])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("top")
    assert victim.zone == Zone.LIBRARY
    assert any(o.name == "Zombie" and o.controller_id == "p1" for o in engine.state.battlefield)


def test_nonland_permanent_target_run_out_of_town():
    engine = game()
    spell = card(engine, "Run Out of Town", zone=Zone.HAND)
    perm = filler(engine, "Relic", type_line="Artifact", player=OWNER)
    cast(engine, spell, targets=[perm])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("top")
    assert perm.zone == Zone.LIBRARY and _lib(engine)[-1] is perm


def test_artifact_or_creature_pool_accepts_an_artifact():
    engine = game()
    spell = card(engine, "Unlucky Drop", zone=Zone.HAND)
    perm = filler(engine, "Relic", type_line="Artifact", player=OWNER)
    cast(engine, spell, targets=[perm])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("bottom")
    assert _lib(engine)[0] is perm


def test_spacecraft_is_a_legal_guidance_failure_target():
    engine = game()
    spell = card(engine, "Guidance Failure", zone=Zone.HAND)
    ship = filler(engine, "Ship", type_line="Artifact — Spacecraft", player=OWNER)
    cast(engine, spell, targets=[ship])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("top")
    assert ship.zone == Zone.LIBRARY


def test_sudden_setback_takes_a_spell_off_the_stack():
    engine = game()
    setback = card(engine, "Sudden Setback", zone=Zone.HAND)
    theirs = filler(engine, "Their Instant", type_line="Instant", mv=2, player=OWNER, zone=Zone.HAND)
    p2 = engine.state.player_by_id(OWNER)
    main_phase(engine)
    p2.mana_pool.add_many({"C": 2})
    engine.cast_spell(p2, theirs)
    cast(engine, setback, targets=[engine.state.stack[0]])
    _choice(engine, OWNER)
    engine.resolve_pending_choice("bottom")
    assert theirs.zone == Zone.LIBRARY and _lib(engine)[0] is theirs


def test_not_forgotten_the_controller_chooses_for_a_card_in_the_opponents_graveyard():
    engine = game()
    spell = card(engine, "Not Forgotten", zone=Zone.HAND)
    corpse = filler(engine, "Corpse", power=2, toughness=2, player=OWNER, zone=Zone.GRAVEYARD)
    cast(engine, spell, targets=[corpse])
    _choice(engine, "p1")  # the spell's controller decides, not the card's owner
    engine.resolve_pending_choice("bottom")
    assert corpse.zone == Zone.LIBRARY and _lib(engine)[0] is corpse
    assert any(o.name == "Spirit" for o in engine.state.battlefield)


def test_arashin_sovereign_dies_trigger_may_be_declined():
    engine = game()
    dragon = card(engine, "Arashin Sovereign")
    engine.rules.destroy(dragon)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "trigger_target"  # the "you may" confirmation
    engine.resolve_pending_choice("decline")
    assert engine.state.pending_choice is None and dragon.zone == Zone.GRAVEYARD


def test_arashin_sovereign_dies_trigger_can_go_to_the_bottom():
    engine = game()
    dragon = card(engine, "Arashin Sovereign")
    engine.rules.destroy(dragon)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("do")
    _choice(engine, "p1")
    engine.resolve_pending_choice("bottom")
    assert dragon.zone == Zone.LIBRARY and _lib(engine, "p1")[0] is dragon


def test_hinder_counters_and_the_countering_player_picks_the_owners_library_end():
    engine = game()
    hinder = card(engine, "Hinder", zone=Zone.HAND)
    theirs = filler(engine, "Their Instant", type_line="Instant", mv=2, player=OWNER, zone=Zone.HAND)
    p2 = engine.state.player_by_id(OWNER)
    main_phase(engine)
    p2.mana_pool.add_many({"C": 2})
    engine.cast_spell(p2, theirs)
    cast(engine, hinder, targets=[engine.state.stack[0]])
    _choice(engine, "p1")
    assert theirs not in p2.graveyard and not engine.state.stack
    engine.resolve_pending_choice("bottom")
    assert theirs.zone == Zone.LIBRARY and _lib(engine)[0] is theirs and theirs not in p2.graveyard


def test_moonsnare_prototype_channel_from_hand():
    from tests.support.deck_batch import activate
    engine = game()
    proto = card(engine, "Moonsnare Prototype", zone=Zone.HAND)
    perm = filler(engine, "Relic", type_line="Artifact", player=OWNER)
    main_phase(engine)
    engine.state.player_by_id("p1").mana_pool.add_many({"U": 5})
    activate(engine, proto, index=0, targets=[perm])  # Channel (the mana ability is not in this list)
    _choice(engine, OWNER)
    engine.resolve_pending_choice("bottom")
    assert perm.zone == Zone.LIBRARY and proto.zone == Zone.GRAVEYARD
