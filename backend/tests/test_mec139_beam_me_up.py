"""MEC-139 -- Beam me up (RULE 702.196), driven on real cached TRK cards in a real engine.

Covers the printed keyword (alternative cost = beam cost + returning a creature, exile instead of leaving the stack
anywhere else), RULE 702.196b ("can't be beamed up", Marooned) and Scotty, Miracle Worker's granted beam me up.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import cast, game, vanilla

#: Beam me up cost of Energize ({3}{U}); Energize's mana cost is {1}{U}.
ENERGIZE_BEAM_MANA = {"C": 3, "U": 1}


def _to_graveyard(player, obj: GameObject) -> GameObject:
    player.hand.remove(obj)
    player.add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def _setup_energize():
    engine, p1, p2 = game("Energize")
    spell = _to_graveyard(p1, p1.hand[0])
    mine = vanilla(engine, "p1", "Mine")
    theirs = vanilla(engine, "p2", "Theirs")
    return engine, p1, p2, spell, mine, theirs


def _offer(engine, player, spell):
    return next((a for a in engine.legal_actions(player) if a.get("instance_id") == spell.instance_id), None)


def test_parser_models_the_twelve_cards_that_only_needed_the_keyword():
    for name in ("Adversary by Algorithm", "Boarding Action", "Energize", "Final Frontier", "Open Communications",
                 "Pattern Buffer Preservation", "Pure Energy", "Transporter Malfunction", "Scotty, Miracle Worker",
                 "Marooned"):
        assert parse_oracle(get_cached_card(name)).coverage == MODELED, name


def test_offer_lists_one_option_per_returnable_creature_with_the_beam_cost():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    other = vanilla(engine, "p1", "Other")
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    offer = _offer(engine, p1, spell)
    assert offer["cast_from_graveyard"] == "beam_me_up"
    assert offer["effective_cost"] == "{3}{U}"  # the beam cost, not the printed {1}{U}
    assert {o["instance_id"] for o in offer["sacrifice_count_cost"]["options"]} == {mine.instance_id, other.instance_id}
    assert offer["sacrifice_count_cost"]["verb"] == "return"


def test_cast_pays_beam_cost_returns_the_chosen_creature_and_exiles_on_resolution():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    other = vanilla(engine, "p1", "Other")
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    engine.cast_spell(p1, spell, targets=[theirs], sacrifice_choices=[other.instance_id])
    assert other in p1.hand and mine in engine.state.battlefield  # the picked creature, not the first one
    assert p1.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert theirs in p2.hand
    assert spell in p1.exile and spell not in p1.graveyard  # RULE 702.196a: exiled instead of the graveyard


def test_countered_beam_spell_is_exiled_too():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    engine.cast_spell(p1, spell, targets=[theirs])
    engine.rules.counter_spell(engine.state.stack[-1])
    assert spell in p1.exile and spell not in p1.graveyard
    assert theirs in engine.state.battlefield


def test_fizzled_beam_spell_is_exiled_too():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    engine.cast_spell(p1, spell, targets=[theirs])
    engine.rules.return_to_hand(theirs)  # the target is gone before resolution
    engine.resolve_until_stable()
    assert spell in p1.exile and spell not in p1.graveyard


def test_no_offer_and_no_cast_without_a_creature_to_return():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    engine.rules.return_to_hand(mine)
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    assert _offer(engine, p1, spell) is None
    assert not engine.can_cast(p1, spell)


def test_illegal_return_pick_is_rejected_before_anything_is_paid():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    try:
        engine.cast_spell(p1, spell, targets=[theirs], sacrifice_choices=[theirs.instance_id])  # not my creature
    except ValueError:
        pass
    else:
        raise AssertionError("returning an opponent's creature must be rejected")
    assert spell in p1.graveyard and mine in engine.state.battlefield and p1.mana_pool.total() == 4


def test_summoning_sick_creature_may_be_returned():
    # Returning a creature is not a {T} cost, so summoning sickness is irrelevant (RULE 302.6 only restricts {T}/{Q}).
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    mine.summoning_sick = True
    assert mine in engine.beam_me_up_return_pool(p1, spell)


def test_marooned_host_cant_be_beamed_up():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    marooned = GameObject(get_cached_card("Marooned"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(marooned)
    bind_from_catalogue(marooned)
    cast(engine, p1, marooned, targets=[mine])
    assert marooned in engine.state.battlefield
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    assert engine.beam_me_up_return_pool(p1, spell) == []  # RULE 702.196b: the only creature can't be beamed up
    assert _offer(engine, p1, spell) is None
    spare = vanilla(engine, "p1", "Spare")
    assert engine.beam_me_up_return_pool(p1, spell) == [spare]


def _setup_scotty(step="main1", spell_name="Energize"):
    engine, p1, p2 = game(spell_name, "Scotty, Miracle Worker")
    spell = _to_graveyard(p1, next(c for c in p1.hand if c.name == spell_name))
    scotty = next(c for c in p1.hand if c.name == "Scotty, Miracle Worker")
    p1.hand.remove(scotty)
    scotty.zone = Zone.BATTLEFIELD
    scotty.summoning_sick = False
    engine.state.add_to_battlefield(scotty)
    engine.recompute_continuous_effects()
    engine.state.current_step = step
    return engine, p1, p2, spell, scotty


def test_scotty_grants_beam_me_up_at_the_cards_mana_cost_and_cant_return_himself():
    # Final Frontier's own printed beam me up is {1}{G}; use a card without one so only Scotty's grant applies.
    engine, p1, p2, spell, scotty = _setup_scotty(spell_name="Lightning Bolt")
    p1.mana_pool.add_many({"R": 1})
    assert engine._graveyard_cast_keyword(spell) == "beam_me_up"
    assert engine.beam_me_up_return_pool(p1, spell) == []  # Scotty is the only creature and can't be beamed up
    assert not engine.can_cast(p1, spell)
    bear = vanilla(engine, "p1", "Bear")
    offer = _offer(engine, p1, spell)
    assert offer["effective_cost"] == "{R}"  # cost equal to the card's mana cost
    assert [o["instance_id"] for o in offer["sacrifice_count_cost"]["options"]] == [bear.instance_id]
    engine.cast_spell(p1, spell, targets=[p2], sacrifice_choices=[bear.instance_id])
    engine.resolve_until_stable()
    assert bear in p1.hand and scotty in engine.state.battlefield and spell in p1.exile
    assert p2.life == 17


def test_scotty_grant_is_main_phase_only():
    engine, p1, p2, spell, scotty = _setup_scotty(step="beginning_of_combat", spell_name="Lightning Bolt")
    assert engine._graveyard_cast_keyword(spell) is None


def test_scotty_grant_is_for_instants_and_sorceries_only():
    engine, p1, p2, spell, scotty = _setup_scotty(spell_name="Grizzly Bears")
    assert engine._graveyard_cast_keyword(spell) is None


def test_card_with_printed_beam_me_up_prefers_scottys_cheaper_cost_but_falls_back_to_the_printed_one():
    engine, p1, p2, spell, scotty = _setup_scotty()
    # Only Scotty on board: his grant has nobody to return, so the printed beam me up ({3}{U}) is the way, and it may
    # return Scotty (his self-exclusion covers only the beam me up he grants).
    assert engine._beam_me_up_source(spell) is spell
    assert engine.beam_me_up_return_pool(p1, spell) == [scotty]
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    assert _offer(engine, p1, spell)["effective_cost"] == "{3}{U}"
    bear = vanilla(engine, "p1", "Bear")
    assert engine._beam_me_up_source(spell) is not spell  # now the granted, cheaper one is payable
    assert _offer(engine, p1, spell)["effective_cost"] == "{1}{U}"
    assert engine.beam_me_up_return_pool(p1, spell) == [bear]


def test_beam_flag_survives_a_state_clone():
    engine, p1, p2, spell, mine, theirs = _setup_energize()
    p1.mana_pool.add_many(ENERGIZE_BEAM_MANA)
    engine.cast_spell(p1, spell, targets=[theirs])
    clone = engine.state.clone()
    cloned_spell = next(item.obj for item in clone.stack)
    assert cloned_spell.cast_graveyard_exile_replacement is True


# --- the other TRK beam-me-up cards, cast for their beam cost in a real engine --------------------------------------


def _beam_cast(card_name, mana, targets=None, library=()):
    """``card_name`` in p1's graveyard, p1 controlling one bear, cast for its beam me up cost; returns the pieces."""
    engine, p1, p2 = game(card_name)
    spell = _to_graveyard(p1, p1.hand[0])
    bear = vanilla(engine, "p1", "Bear")
    for card in library:
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        p1.library.append(obj)
    p1.mana_pool.add_many(mana)
    engine.cast_spell(p1, spell, targets=targets(engine, p1, p2, bear) if targets else None)
    engine.resolve_until_stable()
    return engine, p1, p2, spell, bear


def _finish(engine, spell, p1, bear):
    assert spell in p1.exile and spell not in p1.graveyard  # RULE 702.196a
    assert bear in p1.hand  # the returned creature


def test_open_communications_draws_for_its_beam_cost():
    stock = get_cached_card("Plains")
    engine, p1, p2, spell, bear = _beam_cast("Open Communications", {"C": 2, "U": 1}, library=[stock])
    _finish(engine, spell, p1, bear)
    assert any(c.name == "Plains" for c in p1.hand)


def test_boarding_action_and_adversary_by_algorithm_make_their_tokens():
    engine, p1, p2, spell, bear = _beam_cast("Boarding Action", {"C": 2, "R": 1})
    _finish(engine, spell, p1, bear)
    assert any(c.is_token and "Klingon" in c.name for c in engine.state.battlefield)
    engine, p1, p2, spell, bear = _beam_cast("Adversary by Algorithm", {"C": 3, "G": 1})
    _finish(engine, spell, p1, bear)
    assert any(c.is_token and c.is_creature for c in engine.state.battlefield)


def test_transporter_malfunction_deals_three_damage():
    engine, p1, p2, spell, bear = _beam_cast(
        "Transporter Malfunction", {"C": 3, "R": 3}, targets=lambda e, a, b, c: [b])
    _finish(engine, spell, p1, bear)
    assert p2.life == 17


def test_pure_energy_distributes_counters():
    engine, p1, p2 = game("Pure Energy")
    spell = _to_graveyard(p1, p1.hand[0])
    returned, kept = vanilla(engine, "p1", "Returned"), vanilla(engine, "p1", "Kept")
    p1.mana_pool.add_many({"C": 2, "W": 1})
    engine.cast_spell(p1, spell, targets=[kept], sacrifice_choices=[returned.instance_id])
    engine.resolve_until_stable()
    assert spell in p1.exile and returned in p1.hand
    assert kept.counters.get("+1/+1") == 2


def test_federation_resupply_finds_an_aura_equipment_or_spacecraft():
    from tests.support.deck_batch import answer, pick_label
    aura, junk = get_cached_card("Marooned"), get_cached_card("Plains")
    engine, p1, p2, spell, bear = _beam_cast("Federation Resupply", {"C": 3, "W": 1}, library=[aura, junk])
    answer(engine, pick_label("Marooned"))
    _finish(engine, spell, p1, bear)
    assert any(c.name == "Marooned" for c in p1.hand)
    assert not any(c.name == "Plains" for c in p1.hand)


def test_theres_coffee_in_that_nebula_takes_a_plains_or_cheap_nonland_permanent():
    from tests.support.deck_batch import answer, pick_label
    cards = [get_cached_card(n) for n in ("Plains", "Marooned", "Lightning Bolt")]
    engine, p1, p2, spell, bear = _beam_cast("There's Coffee in that Nebula", {"C": 2, "W": 1}, library=cards)
    answer(engine, pick_label("Plains", "Marooned"))
    _finish(engine, spell, p1, bear)
    assert any(c.name in ("Plains", "Marooned") for c in p1.hand)
    assert not any(c.name == "Lightning Bolt" for c in p1.hand)


def test_final_frontier_and_pattern_buffer_preservation_run():
    from tests.support.deck_batch import answer
    lib = [get_cached_card("Plains"), get_cached_card("Plains")]
    engine, p1, p2, spell, bear = _beam_cast("Final Frontier", {"C": 1, "G": 1}, library=lib)
    answer(engine)
    _finish(engine, spell, p1, bear)
    assert any(c.name == "Plains" for c in engine.state.battlefield)
    engine, p1, p2, spell, bear = _beam_cast("Pattern Buffer Preservation", {"C": 1, "B": 1}, library=lib)
    answer(engine)
    _finish(engine, spell, p1, bear)
    assert len(p1.hand) == 2  # the returned bear + the kept card
