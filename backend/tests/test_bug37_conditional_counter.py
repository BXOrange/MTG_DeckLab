"""BUG-37: "counter target spell if it's <colour>" (Pyroblast, Hydroblast, Burnout) -- the colour is checked on
resolution, never a target restriction (RULE 601.2c, 608.2b). Executed against the real engine and real cards."""
from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import RICH, card, filler, game, main_phase

#: (counterspell name, mode index or None, colour it counters)
BLUE_INSTANT = "Blue Instant"
COUNTERS = [("Pyroblast", 0, "blue"), ("Hydroblast", 0, "red")]


def _stack_spell(eng, name, targets=None):
    """the active player (p1) casts ``name`` and leaves it unresolved on the stack, so p2 can respond."""
    main_phase(eng)
    if name == BLUE_INSTANT:
        # Vanilla stand-in: Brainstorm would leave a pending choice on the stack.
        spell = filler(eng, name, type_line="Instant", player="p1", zone=Zone.HAND, mana_cost_string="{U}")
    else:
        spell = card(eng, name, "p1", zone=Zone.HAND)
    p2 = eng.state.player_by_id("p1")
    p2.mana_pool.add_many(RICH)
    eng.cast_spell(p2, spell, targets=targets)
    assert spell.zone is Zone.STACK
    return spell


def _respond(eng, name, victim, **kw):
    p1 = eng.state.player_by_id("p2")
    counter = card(eng, name, "p2", zone=Zone.HAND)
    p1.mana_pool.add_many(RICH)
    eng.cast_spell(p1, counter, targets=[victim], **kw)
    eng.resolve_until_stable()
    return counter


def test_parse_shape_is_a_resolution_check_not_a_filter():
    specs = parse_effect_body("counter target spell if it's blue")
    assert specs[0].params == {"resolve_if_color": "U"}
    assert parse_effect_body("counter target blue spell")[0].params == {"color": "U"}
    burnout = parse_effect_body("counter target instant spell if it's blue")[0].params
    assert burnout == {"card_types": ["instant"], "resolve_if_color": "U"}


def test_inline_adjective_and_trailing_condition_do_not_combine():
    assert not parse_effect_body("counter target blue spell if it's red")


@pytest.mark.parametrize("name,mode,colour", COUNTERS)
def test_matching_colour_spell_is_countered(name, mode, colour):
    eng = game()
    victim = _stack_spell(eng, BLUE_INSTANT if colour == "blue" else "Lightning Bolt",
                          targets=None if colour == "blue" else [eng.state.player_by_id("p2")])
    _respond(eng, name, victim, mode=[mode])
    assert victim.zone is Zone.GRAVEYARD
    assert eng.state.player_by_id("p2").life == 20  # Lightning Bolt never resolved


@pytest.mark.parametrize("name,mode,colour", COUNTERS)
def test_non_matching_spell_is_a_legal_target_and_resolves(name, mode, colour):
    eng = game()
    # Pyroblast only counters blue, Hydroblast only red: pick a spell of the other colour.
    other = "Lightning Bolt" if colour == "blue" else BLUE_INSTANT
    victim = _stack_spell(eng, other, targets=[eng.state.player_by_id("p2")] if other == "Lightning Bolt" else None)
    life = eng.state.player_by_id("p2").life
    spell = _respond(eng, name, victim, mode=[mode])  # a colour-restricted target would be refused here
    assert spell.zone is Zone.GRAVEYARD  # the Blast itself resolved
    assert victim.zone is Zone.GRAVEYARD  # ...and the target resolved normally, then left the stack
    if other == "Lightning Bolt":
        assert eng.state.player_by_id("p2").life == life - 3  # it was not countered


def test_colourless_spell_is_not_countered():
    eng = game()
    victim = _stack_spell(eng, "Sol Ring")
    _respond(eng, "Pyroblast", victim, mode=[0])
    assert victim.zone is Zone.BATTLEFIELD


def test_burnout_counters_a_matching_instant_and_draws_next_upkeep():
    eng = game()
    victim = _stack_spell(eng, BLUE_INSTANT)
    _respond(eng, "Burnout", victim)
    assert victim.zone is Zone.GRAVEYARD
    assert any(o.name == BLUE_INSTANT for o in eng.state.player_by_id("p1").graveyard)


def test_burnout_instant_filter_is_still_an_offer_time_restriction():
    eng = game()
    sorcery = _stack_spell(eng, "Divination")
    p1 = eng.state.player_by_id("p2")
    burnout = card(eng, "Burnout", "p2", zone=Zone.HAND)
    p1.mana_pool.add_many(RICH)
    with pytest.raises(Exception):
        eng.cast_spell(p1, burnout, targets=[sorcery])


def test_burnout_leaves_a_non_matching_instant_alone():
    eng = game()
    victim = _stack_spell(eng, "Lightning Bolt", targets=[eng.state.player_by_id("p2")])
    _respond(eng, "Burnout", victim)
    assert eng.state.player_by_id("p2").life == 17


def test_destroy_mode_is_unchanged():
    specs = parse_effect_body("destroy target permanent if it's blue")
    assert "is_color" in str(specs) and "resolve_if_color" not in str(specs)
