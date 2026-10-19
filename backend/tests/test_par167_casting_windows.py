"""PAR-167 -- casting-window grammar compositions.

Every shape here is parsed from real oracle wording and then *executed*: the permitted spell is cast, its
post-cast zone and the permission's expiry are checked, with negative controls for what must stay refused.
"""
import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached

RIDER = " if that spell would be put into {gy} graveyard, exile it instead."


def _instant(name="Insight", cost="{1}", mv=1, sorcery=False, identity=None):
    return Card(id=name, name=name, type_line="Sorcery" if sorcery else "Instant", is_instant=not sorcery,
                is_sorcery=sorcery, mana_cost_string=cost, converted_mana_cost=mv, color_identity=identity,
                oracle_text="Draw a card.")


def _in_graveyard(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(owner).graveyard.append(obj)
    return obj


def _apply(eng, text, target, source=None):
    source = source or _bf(eng, _creature("Grantor"))
    specs = parse_effect_body(text)
    assert specs, text
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, [target])
    return source


def _spec_for(text, source):
    return build_effects(parse_effect_body(text), source)[0].target_spec


FREE = "you may cast target instant or sorcery card from {who} graveyard without paying its mana cost."


def test_free_resolution_local_cast_from_opponent_graveyard_exiles_afterwards():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant(), owner="p2")
    _apply(eng, FREE.format(who="an opponent's") + RIDER.format(gy="their"), spell)
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    eng.play_resolution_card(p1, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE
    assert p1.mana_pool.total() == 0


def test_resolution_local_permission_is_gone_once_declined():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant())
    _apply(eng, FREE.format(who="your") + RIDER.format(gy="your"), spell)
    eng.resolve_pending_choice("decline")
    assert spell.zone == Zone.GRAVEYARD
    assert not eng.can_cast(p1, spell)


def test_free_cast_without_a_rider_goes_back_to_the_graveyard():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant())
    _apply(eng, FREE.format(who="your"), spell)
    eng.play_resolution_card(p1, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD


def test_normal_cost_resolution_local_cast_charges_the_mana_cost():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant())
    _apply(eng, "you may cast target instant or sorcery card with mana value 3 or less from your graveyard."
           + RIDER.format(gy="your"), spell)
    with pytest.raises(ValueError):
        eng.play_resolution_card(p1, spell)  # {1} unpaid
    p1.mana_pool.add("C", 1)
    eng.play_resolution_card(p1, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE


def test_mana_value_cap_and_colour_narrow_the_targets():
    eng = _engine()
    source = _bf(eng, _creature("Grantor"))
    cheap = _in_graveyard(eng, _instant("Cheap", mv=1))
    dear = _in_graveyard(eng, _instant("Dear", "{4}", 4))
    spec = _spec_for("you may cast target instant or sorcery card with mana value 3 or less from your graveyard.", source)
    ids = {t["instance_id"] for t in targeting.legal_targets(eng.state, "p1", spec, source=source)}
    assert ids == {cheap.instance_id}
    red = _in_graveyard(eng, _instant("Bolt", "{R}", 1, identity={"R"}))
    spec = _spec_for("you may cast target red instant or sorcery card from your graveyard.", source)
    ids = {t["instance_id"] for t in targeting.legal_targets(eng.state, "p1", spec, source=source)}
    assert ids == {red.instance_id}


def test_source_power_cap():
    eng = _engine()
    source = _bf(eng, _creature("Arcanist", power=2))
    two = _in_graveyard(eng, _instant("Two", "{1}{1}", 2))
    three = _in_graveyard(eng, _instant("Three", "{3}", 3))
    spec = _spec_for("you may cast target instant or sorcery card with mana value less than or equal to ~'s power "
                     "from your graveyard without paying its mana cost.", source)
    ids = {t["instance_id"] for t in targeting.legal_targets(eng.state, "p1", spec, source=source)}
    assert ids == {two.instance_id}


def test_turn_long_free_permission_expires_at_cleanup():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant())
    _apply(eng, "until end of turn, you may cast target instant or sorcery card from your graveyard without paying "
           "its mana cost." + RIDER.format(gy="your"), spell)
    assert eng.state.pending_choice is None
    assert eng.can_cast(p1, spell)
    eng._step_cleanup()
    assert not eng.can_cast(p1, spell)
    eng2 = _engine()
    p1 = eng2.state.player_by_id("p1")
    spell = _in_graveyard(eng2, _instant())
    _apply(eng2, "until end of turn, you may cast target instant or sorcery card from your graveyard without paying "
           "its mana cost." + RIDER.format(gy="your"), spell)
    eng2.cast_spell(p1, spell)
    eng2.resolve_until_stable()
    assert spell.zone == Zone.EXILE


@pytest.mark.parametrize("text", [
    "you may cast target instant or sorcery card from your graveyard without paying its mana cost next turn.",
    "you may cast target instant or sorcery card from your hand without paying its mana cost.",
    "you may cast target instant or sorcery card with mana value 3 or less or equal from your graveyard.",
])
def test_unknown_axes_are_not_claimed(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Arcane Heist", "Daring Waverider", "Dreadhorde Arcanist", "Efreet Flamepainter", "Goblin Dark-Dwellers",
    "Memory Plunder", "Seifer Almasy", "Sins of the Past", "The Dawning Archaic", "Vadrok, Apex of Thunder",
    "Victor Timely, Wily Tycoon",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


# -- the casting window after an exile clause ------------------------------------------------------------------


def _stock_library(eng, cards, owner="p1"):
    """Put ``cards`` on top of ``owner``'s library, first listed on top."""
    player = eng.state.player_by_id(owner)
    for card in reversed(cards):
        player.library.append(GameObject(card, owner_id=owner, zone=Zone.LIBRARY))
    return [player.library[-1 - i] for i in range(len(cards))]


def _run(eng, text, source=None, targets=None):
    source = source or _bf(eng, _creature("Source"))
    specs = parse_effect_body(text)
    assert specs, text
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, targets)
    return source


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                mana_cost_string="{1}", converted_mana_cost=1)


NARSET = ("exile the top 4 cards of your library. until end of turn, you may cast noncreature spells from among "
          "those cards without paying their mana costs.")


def test_free_window_casts_only_the_permitted_cards_and_expires_at_cleanup():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    a, b, bear, land = _stock_library(eng, [_instant("A"), _instant("B"), _bear(), Card(
        id="L", name="Island", type_line="Basic Land — Island", is_land=True)])
    _run(eng, NARSET)
    assert all(o.zone == Zone.EXILE for o in (a, b, bear, land))
    assert eng.can_cast(p1, a) and eng.can_cast(p1, b)  # an empty mana pool: the cost is waived
    assert not eng.can_cast(p1, bear)
    p1.mana_pool.add("C", 5)  # plenty of mana: only the filter may refuse the creature
    assert not eng.can_cast(p1, bear)
    eng.cast_spell(p1, a)
    eng.resolve_until_stable()
    assert a.zone == Zone.GRAVEYARD
    assert p1.mana_pool.total() == 5  # the free cast spent nothing
    eng._step_cleanup()
    assert not eng.can_cast(p1, b)  # the window ended with the turn


def test_normal_cost_window_for_the_next_turn_charges_mana_and_survives_this_cleanup():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    bear, spell = _stock_library(eng, [_bear(), _instant()])
    _run(eng, "exile the top 2 cards of your library. until the end of your next turn, you may cast creature spells "
              "from among the exiled cards.")
    assert not eng.can_cast(p1, bear)  # {1} unpaid
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, bear) and not eng.can_cast(p1, spell)
    eng._step_cleanup()
    assert eng.can_cast(p1, bear)


def test_resolution_local_one_of_the_pool_and_any_number():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    a, b = _stock_library(eng, [_instant("A"), _instant("B")])
    _run(eng, "exile the top 2 cards of your library. you may cast an instant or sorcery spell from among them "
              "without paying its mana cost.")
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    eng.play_resolution_card(p1, a)
    eng.resolve_until_stable()
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.EXILE
    assert not eng.can_cast(p1, b)  # one cast only; the offer is gone

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    a, b = _stock_library(eng, [_instant("A"), _instant("B")])
    _run(eng, "exile the top 2 cards of your library. you may cast any number of spells from among them without "
              "paying their mana costs.")
    eng.play_resolution_card(p1, a)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.play_resolution_card(p1, b)
        eng.resolve_until_stable()
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.GRAVEYARD


def test_window_from_an_opponents_library_is_held_by_the_controller():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    stolen, = _stock_library(eng, [_instant("Stolen")], owner="p2")
    _run(eng, "exile the top card of target opponent's library. you may cast that card this turn.", targets=[p2])
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, stolen)
    assert not eng.can_cast(p2, stolen)


def test_mana_of_any_type_rider_and_standing_window_after_a_targeted_exile():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    victim = _bf(eng, _bear("Victim"), "p2")
    text = ("exile another target creature or artifact until ~ leaves the battlefield. you may cast that card for as "
            "long as it remains exiled, and mana of any type can be spent to cast that spell.")
    _run(eng, text, source=_bf(eng, _creature("Taker")), targets=[victim])
    assert victim.zone == Zone.EXILE
    p1.mana_pool.add("R", 1)  # {1} paid with the wrong type of mana is fine for a generic cost anyway
    assert eng.can_cast(p1, victim)
    eng._step_cleanup()
    assert eng.can_cast(p1, victim)  # a standing window survives the turn


@pytest.mark.parametrize("text", [
    # a lone card cannot name a two-card exile
    "exile the top 2 cards of your library. you may play that card this turn.",
    # "a spell" from a window could not be limited to one cast
    "exile the top 3 cards of your library. until end of turn, you may cast a spell from among them.",
    "exile the top 3 cards of your library. until end of turn, you may cast spells from among them and then die.",
    # the pronoun must follow an exile, not a mill
    "mill 3 cards. until end of turn, you may cast spells from among them.",
    "exile the top 3 cards of your library face down. you may cast spells from among them this turn.",
])
def test_cast_window_refuses_what_it_cannot_express(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Narset, Enlightened Master", "Eager Flameguide", "Golos, Tireless Pilgrim", "Hostage Taker",
    "Korvold and the Noble Thief", "Oracle's Vault", "Stolen Strategy",
])
def test_real_window_cards_are_modeled(name):
    result = parse_oracle(_cached(name))
    if name == 'Eager Flameguide':
        assert result.never_supported
        assert result.unsupported_reason == "digital_only"
        assert not result.specs
    else:
        assert result.modeled


@pytest.mark.full_cache
def test_a_conditioned_window_stays_unmodeled():
    # "...you may play it if you control a Kavu" would gate the exile itself under the shared condition peel
    assert not parse_oracle(_cached("Possibility Technician")).modeled


# -- the free cast from hand / graveyard, with every mana-value cap axis ------------------------------------------


def _in_hand(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    eng.state.player_by_id(owner).hand.append(obj)
    return obj


def _sorcery(name="Burn", mv=3):
    return _instant(name, "{" + str(mv) + "}", mv, sorcery=True)


def test_hand_cast_capped_by_the_damage_the_trigger_dealt():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    ok = _in_hand(eng, _sorcery("Fits", 3))
    too_dear = _in_hand(eng, _sorcery("Dear", 4))
    wrong_type = _in_hand(eng, _instant("Instant", "{1}", 1))
    eng.rules.context.trigger_event = {"amount": 3}
    _run(eng, "you may cast a sorcery spell from your hand with mana value less than or equal to that damage "
              "without paying its mana cost.")
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    assert eng.state.pending_choice["instance_ids"] == [ok.instance_id]
    with pytest.raises(ValueError):
        eng.play_resolution_card(p1, too_dear)
    eng.play_resolution_card(p1, ok)
    eng.resolve_until_stable()
    assert ok.zone == Zone.GRAVEYARD and too_dear.zone == Zone.HAND and wrong_type.zone == Zone.HAND
    assert p1.mana_pool.total() == 0


def test_hand_cast_exactly_equal_to_a_counter_count_on_the_source():
    eng = _engine()
    source = _bf(eng, _creature("Jar"))
    source.counters["charge"] = 2
    two = _in_hand(eng, _instant("Two", "{1}{1}", 2))
    one = _in_hand(eng, _instant("One", "{1}", 1))
    _run(eng, "you may cast an instant or sorcery spell with mana value equal to the number of charge counters on ~ "
              "from your hand without paying its mana cost.", source=source)
    assert eng.state.pending_choice["instance_ids"] == [two.instance_id]


def test_hand_cast_cap_from_a_where_x_tail():
    eng = _engine()
    source = _bf(eng, _creature("Gandalf"))
    wizard = Card(id="Wiz", name="Wiz", type_line="Legendary Creature — Wizard", is_creature=True,
                  is_legendary=True, power=1, toughness=1)
    _bf(eng, wizard)
    two = _in_hand(eng, _instant("Two", "{1}{1}", 2))
    three = _in_hand(eng, _instant("Three", "{3}", 3))
    _run(eng, "you may cast an instant or sorcery spell with mana value x or less from your hand without paying its "
              "mana cost, where x is twice the number of legendary wizards you control.", source=source)
    assert eng.state.pending_choice["instance_ids"] == [two.instance_id]
    assert three.instance_id not in eng.state.pending_choice["instance_ids"]


def test_any_number_of_coloured_cards_from_the_graveyard_are_all_castable_free():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    r1 = _in_graveyard(eng, _instant("Bolt", "{R}", 1, identity={"R"}))
    r2 = _in_graveyard(eng, _instant("Shock", "{R}", 1, identity={"R"}))
    blue = _in_graveyard(eng, _instant("Opt", "{U}", 1, identity={"U"}))
    creature = _in_graveyard(eng, _bear())
    _run(eng, "cast any number of red instant and/or sorcery cards from your graveyard without paying their mana costs.")
    offered = set(eng.state.pending_choice["instance_ids"])
    assert offered == {r1.instance_id, r2.instance_id}
    eng.play_resolution_card(p1, r1)
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice["kind"] == "play_during_resolution"
    eng.play_resolution_card(p1, r2)
    eng.resolve_until_stable()
    assert blue.zone == Zone.GRAVEYARD and creature.zone == Zone.GRAVEYARD
    assert p1.mana_pool.total() == 0


@pytest.mark.parametrize("text", [
    "you may cast a spell from your hand with mana value less than or equal to that damage without paying its mana cost, "
    "where x is the moon.",
    "you may cast a sorcery spells from your hand without paying its mana cost.",
    "you may cast any number of sorcery spell from your hand without paying its mana cost.",
    "you may cast a sorcery spell from your graveyard with mana value equal to the phase of the moon without paying "
    "its mana cost.",
])
def test_free_cast_zone_refuses_unreadable_axes(text):
    assert not parse_effect_body(text)


def test_that_damage_is_not_claimed_outside_a_damage_trigger():
    text = "you may cast a sorcery spell from your hand with mana value less than or equal to that damage without paying its mana cost."
    for line in (text, "{t}: " + text):
        result = parse_oracle(Card(id="X", name="Test Relic", type_line="Artifact", oracle_text=line.capitalize()))
        assert not result.modeled, line


@pytest.mark.full_cache
@pytest.mark.parametrize("name", ["Aisha of Sparks and Smoke", "Buster Sword", "Gandalf, Party Guest", "Brain in a Jar"])
def test_real_capped_hand_casters_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


# -- the turn-long graveyard play window ------------------------------------------------------------------------


GAEA = "you may play lands and cast spells from your graveyard until end of turn."
REDIRECT = "if a card would be put into your graveyard from anywhere this turn, exile that card instead."


def test_graveyard_play_window_permits_spells_and_lands_until_cleanup_and_redirects_new_cards():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _in_graveyard(eng, _instant())
    land = _in_graveyard(eng, Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True))
    assert not eng.can_cast(p1, spell) and not eng.can_play_land(p1, land)
    _run(eng, GAEA)
    _run(eng, REDIRECT)
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, spell) and eng.can_play_land(p1, land)
    fresh = _in_hand(eng, _instant("Fresh"))
    p1.hand.remove(fresh)
    eng.rules.put_into_graveyard(fresh)
    assert fresh.zone == Zone.EXILE  # RULE 614.1: exiled instead of reaching the graveyard
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE  # the replacement caught the cast spell as well
    eng.state.internal_turn.number += 1
    other = _in_graveyard(eng, _instant("Later"))
    p1.mana_pool.add("C", 1)
    assert not eng.can_cast(p1, other)


def test_graveyard_play_window_needs_exactly_one_window_phrase():
    assert parse_effect_body("until end of turn, you may play lands and cast spells from your graveyard")
    assert not parse_effect_body("you may play lands and cast spells from your graveyard")
    assert not parse_effect_body("until end of turn, you may play lands and cast spells from your graveyard until end of turn")


@pytest.mark.full_cache
@pytest.mark.parametrize("name", ["Gaea's Will", "Magus of the Will"])
def test_real_graveyard_window_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


# -- the exile-until dig and its free cast ----------------------------------------------------------------------


def _land(name="Island"):
    return Card(id=name, name=name, type_line="Basic Land — Island", is_land=True)


DIG_OWN = ("exile cards from the top of your library until you exile a nonland card. you may cast that card without "
           "paying its mana cost.")


def test_own_dig_offers_the_nonland_hit_for_a_free_cast_during_resolution_and_keeps_the_rest_exiled():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    l1, l2, hit, below = _stock_library(eng, [_land("A"), _land("B"), _instant("Hit"), _instant("Below")])
    _run(eng, DIG_OWN)
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    assert eng.state.pending_choice["instance_ids"] == [hit.instance_id]
    eng.play_resolution_card(p1, hit)
    eng.resolve_until_stable()
    assert hit.zone == Zone.GRAVEYARD and l1.zone == l2.zone == Zone.EXILE and below.zone == Zone.LIBRARY
    assert p1.mana_pool.total() == 0


def test_declined_dig_hit_stays_exiled():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    hit, = _stock_library(eng, [_instant("Hit")])
    _run(eng, DIG_OWN)
    eng.resolve_pending_choice("decline")
    assert hit.zone == Zone.EXILE and not eng.can_cast(p1, hit)


def test_opponents_dig_hands_the_controller_a_free_window_for_the_turn():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _, hit = _stock_library(eng, [_land("X"), _instant("TheirSpell")], owner="p2")
    _run(eng, "target opponent exiles cards from the top of their library until they exile a nonland card. until end "
              "of turn, you may cast that card without paying its mana cost.", targets=[p2])
    assert hit.zone == Zone.EXILE
    assert eng.can_cast(p1, hit) and not eng.can_cast(p2, hit)
    eng.cast_spell(p1, hit)
    eng.resolve_until_stable()
    assert hit.zone == Zone.GRAVEYARD
    assert p1.mana_pool.total() == 0


@pytest.mark.parametrize("text", [
    "exile cards from the top of your library until you exile a nonland card. you may cast that card this turn.",
    "exile cards from the top of your library until you exile a nonland card. until end of turn, you may cast that "
    "card without paying its mana cost.",
    "exile cards from the top of your library until you exile a nonland card. you may cast that card without paying "
    "its mana cost. then put the exiled cards that weren't cast this way on the bottom of your library.",
])
def test_dig_cast_refuses_what_it_cannot_express(text):
    assert not parse_effect_body(text) or all(s.type != "dig_until" for s in parse_effect_body(text))


@pytest.mark.full_cache
@pytest.mark.parametrize("name", ["Nico Minoru, Runaway", "Wanda's Vision", "Stolen Goods"])
def test_real_dig_cast_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


@pytest.mark.full_cache
def test_sins_of_the_past_end_to_end_free_window_with_exile_rider():
    from test_mec106_gift import _hand

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    target = _in_graveyard(eng, _instant("Insight", "{1}", 1))
    sins = _hand(eng, _cached("Sins of the Past"))
    p1.mana_pool.add("U", 2)
    p1.mana_pool.add("B", 4)
    eng.cast_spell(p1, sins, [target])
    eng.resolve_until_stable()
    assert sins.zone == Zone.EXILE  # "Exile Sins of the Past."
    spent = p1.mana_pool.total()
    assert eng.can_cast(p1, target)
    eng.cast_spell(p1, target)
    eng.resolve_until_stable()
    assert target.zone == Zone.EXILE  # the rider
    assert p1.mana_pool.total() == spent  # free
    eng._step_cleanup()


def test_paired_window_does_not_inherit_an_earlier_independent_exile():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    earlier = _bf(eng, _bear('Earlier'))
    _run(eng, 'exile target creature.', targets=[earlier])
    hit, = _stock_library(eng, [_instant('Latest')])
    _run(eng, 'exile the top card of your library. until end of turn, you may cast spells from among them without paying their mana costs.')
    assert eng.can_cast(p1, hit)
    assert earlier.instance_id not in eng.state.temp_play_permissions
    assert earlier.instance_id not in eng.state.free_cast_instance_ids


def test_empty_paired_exile_cannot_reuse_an_earlier_receipt():
    eng = _engine()
    earlier, = _stock_library(eng, [_instant('Earlier')])
    _run(eng, 'exile the top card of your library.')
    _run(eng, 'exile the top card of your library. until end of turn, you may cast spells from among them without paying their mana costs.')
    assert earlier.instance_id not in eng.state.temp_play_permissions


def test_window_clone_survives_source_new_visit_and_expires_independently():
    from mtg_analyzer.game.game_engine import GameEngine

    eng = _engine()
    hit, = _stock_library(eng, [_instant('CloneHit')])
    source = _run(eng, 'exile the top card of your library. until end of turn, you may cast spells from among them without paying their mana costs.')
    eng.rules.exile(source)
    eng.rules._put_searched_card(eng.state.player_by_id('p1'), source, 'battlefield')
    clone = GameEngine(eng.state.clone())
    cloned_hit = clone.state.find_object(hit.instance_id)
    p1 = clone.state.player_by_id('p1')
    assert clone.can_cast(p1, cloned_hit)
    clone.cast_spell(p1, cloned_hit)
    clone.resolve_until_stable()
    assert cloned_hit.zone == Zone.GRAVEYARD and hit.zone == Zone.EXILE
    eng._step_cleanup()
    assert not eng.can_cast(eng.state.player_by_id('p1'), hit)


@pytest.mark.full_cache
@pytest.mark.parametrize('name,fragment', [
    ('Jin-Gitaxias // The Great Synthesis', 'you may cast any number'),
    ('Urabrask // The Great Work', 'until end of turn, you may cast'),
    ('Ral, Monsoon Mage // Ral, Leyline Prodigy', 'exile the top'),
])
def test_real_back_face_casting_bodies_parse(name, fragment):
    from mtg_analyzer.parser.oracle.normalize import normalize

    back = _cached(name).back_face()
    line = next(line for line in normalize(back.oracle_text, back.name).splitlines() if fragment in line)
    # Chapter/loyalty heads are not part of the effect body.
    body = line.split('—', 1)[-1].strip() if '—' in line else line.split(':', 1)[-1].strip()
    if fragment == 'you may cast any number':
        body = body[:body.index('. exile') + 1] if '. exile' in body else body
    assert parse_effect_body(body), body


URABRASK = ('until end of turn, you may cast instant and sorcery spells from any graveyard. '
            'if a spell cast this way would be put into a graveyard, exile it instead.')


def test_dynamic_graveyard_pool_includes_later_arrivals_survives_source_return_and_clones():
    from mtg_analyzer.game.game_engine import GameEngine

    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    own = _in_graveyard(eng, _instant('Own'))
    other = _in_graveyard(eng, _instant('Theirs'), owner='p2')
    bear = _in_graveyard(eng, _bear())
    source = _run(eng, URABRASK)
    assert not eng.can_cast(p1, own)  # permission does not waive mana
    eng.rules.exile(source)
    eng.rules._put_searched_card(p1, source, 'battlefield')
    p1.mana_pool.add('C', 4)
    later = _in_graveyard(eng, _instant('Later'), owner='p2')
    assert all(eng.can_cast(p1, obj) for obj in [own, other, later])
    assert not eng.can_cast(p1, bear)
    clone = GameEngine(eng.state.clone())
    cloned_later = clone.state.find_object(later.instance_id)
    clone.cast_spell(clone.state.player_by_id('p1'), cloned_later)
    clone.resolve_until_stable()
    assert cloned_later.zone == Zone.EXILE and later.zone == Zone.GRAVEYARD
    eng.cast_spell(p1, other)
    eng.resolve_until_stable()
    assert other.zone == Zone.EXILE and p1.mana_pool.total() == 3
    eng._step_cleanup()
    assert not eng.can_cast(p1, own) and not eng.can_cast(p1, later)


@pytest.mark.parametrize('text', [
    'until end of turn, you may cast instant spells from any graveyard without paying their mana costs.',
    'you may cast instant and sorcery spells from any graveyard.',
    'until end of turn, you may cast green cheese spells from any graveyard.',
])
def test_dynamic_graveyard_pool_fails_closed(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
@pytest.mark.parametrize('name,fragment', [
    ('Jin-Gitaxias // The Great Synthesis', 'You may cast any number'),
    ('Urabrask // The Great Work', 'Until end of turn, you may cast'),
    ('Ral, Monsoon Mage // Ral, Leyline Prodigy', 'Exile the top'),
])
def test_actual_back_casting_body_also_executes_from_a_front_face(name, fragment):
    from mtg_analyzer.parser.oracle.normalize import normalize

    back = _cached(name).back_face()
    raw = next(line for line in back.oracle_text.splitlines() if fragment in line)
    raw = raw.split('—', 1)[-1].strip() if '—' in raw else raw.split(':', 1)[-1].strip()
    raw = raw.split(' Exile this Saga,')[0]
    body = normalize(raw, back.name)
    for transformed in [False, True]:
        eng = _engine()
        p1 = eng.state.player_by_id('p1')
        card = Card(id='axis', name='Axis Front', type_line='Creature', is_creature=True, power=2, toughness=2,
                    back_name='Axis Back', back_type_line='Enchantment', back_oracle_text=raw, oracle_text=raw)
        source = _bf(eng, card)
        source.transformed = transformed
        if 'hand' in body:
            a = _in_hand(eng, _instant('A'))
            b = _in_hand(eng, _instant('B'))
            _run(eng, body, source=source)
            eng.play_resolution_card(p1, a)
            eng.resolve_until_stable()
            assert eng.state.pending_choice
            eng.play_resolution_card(p1, b)
            eng.resolve_until_stable()
            assert a.zone == b.zone == Zone.GRAVEYARD
        elif 'any graveyard' in body:
            a = _in_graveyard(eng, _instant('A'), 'p2')
            _run(eng, body, source=source)
            p1.mana_pool.add('C', 1)
            eng.cast_spell(p1, a)
            eng.resolve_until_stable()
            assert a.zone == Zone.EXILE
        else:
            a, bear = _stock_library(eng, [_instant('A'), _bear()])
            _run(eng, body, source=source)
            assert eng.can_cast(p1, a) and not eng.can_cast(p1, bear)
            eng.cast_spell(p1, a)
            eng.resolve_until_stable()
            assert a.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('free', [False, True])
def test_exile_copy_cast_reuses_the_target_at_normal_or_free_cost(free):
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    original = _in_graveyard(eng, _instant('Original', '{2}', 2), owner='p2')
    source = _bf(eng, _creature('Copy Maker'))
    text = ('exile target instant or sorcery card from a graveyard. copy it. you may cast the copy'
            + (' without paying its mana cost.' if free else '.'))
    specs = parse_effect_body(text)
    assert specs
    _apply_effects_partitioned(build_effects(specs, source), eng.rules.context, [original], None, source=source)
    assert original.zone == Zone.EXILE
    offered = eng.state.find_object(eng.state.pending_choice['instance_ids'][0])
    assert offered is not original and offered.card.name == original.card.name
    if not free:
        with pytest.raises(ValueError):
            eng.play_resolution_card(p1, offered)
        p1.mana_pool.add('C', 2)
    eng.play_resolution_card(p1, offered)
    eng.resolve_until_stable()
    assert p1.mana_pool.total() == 0 and original.zone == Zone.EXILE


@pytest.mark.parametrize('text', [
    'exile target creature. copy it. you may cast the copy tomorrow.',
    'exile the top 2 cards of your library. copy it. you may cast the copy.',
    'exile target card from a graveyard. copy it. you may cast the copy with twice its power.',
])
def test_exile_copy_cast_does_not_claim_unrepresented_riders(text):
    assert not parse_effect_body(text)


@pytest.mark.parametrize('zone,noun', [('hand', 'spells'), ('graveyard', 'cards')])
def test_unquantified_plural_free_cast_does_not_become_a_single_cast(zone, noun):
    assert not parse_effect_body(f'you may cast {noun} from your {zone} without paying their mana costs.')


def test_latest_mill_free_cast_uses_only_that_mill_batch_from_the_opponents_graveyard():
    eng = _engine()
    p1 = eng.state.player_by_id('p1')
    p2 = eng.state.player_by_id('p2')
    stale = _in_graveyard(eng, _instant('Old'), 'p2')
    hit, bear = _stock_library(eng, [_instant('Hit'), _bear()], owner='p2')
    _run(eng, 'target opponent mills 2 cards. you may cast an instant or sorcery spell from among them without paying its mana cost.', targets=[p2])
    assert eng.state.pending_choice['instance_ids'] == [hit.instance_id]
    eng.play_resolution_card(p1, hit)
    eng.resolve_until_stable()
    assert hit.zone == Zone.GRAVEYARD and stale.zone == bear.zone == Zone.GRAVEYARD
    assert p1.mana_pool.total() == 0 and not eng.can_cast(p1, hit)


def test_latest_mill_x_cap_survives_pending_choice_clone_and_only_one_card_is_cast():
    from mtg_analyzer.game.game_engine import GameEngine

    eng = _engine()
    source = _bf(eng, _creature('X Source'))
    source.x_paid = 3
    hit, second, dear = _stock_library(eng, [_instant('Hit', '{2}', 2), _instant('Second', '{1}', 1),
                                         _instant('Dear', '{4}', 4)])
    _run(eng, 'mill x cards. you may cast an instant or sorcery spell with mana value x or less from among them without paying its mana cost.', source=source)
    assert set(eng.state.pending_choice['instance_ids']) == {hit.instance_id, second.instance_id}
    clone = GameEngine(eng.state.clone())
    copy_hit = clone.state.find_object(hit.instance_id)
    clone.play_resolution_card(clone.state.player_by_id('p1'), copy_hit)
    clone.resolve_until_stable()
    assert copy_hit.zone == Zone.GRAVEYARD and not clone.state.pending_choice
    eng.resolve_pending_choice('decline')
    assert not eng.can_cast(eng.state.player_by_id('p1'), hit)


@pytest.mark.full_cache
@pytest.mark.parametrize('name', ["Jace's Mindseeker"])
def test_real_mill_cast_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


@pytest.mark.full_cache
def test_summons_of_saruman_real_casting_body_is_composed_but_amass_x_stays_unclaimed():
    card = _cached("Summons of Saruman")
    from mtg_analyzer.parser.oracle.normalize import normalize
    body = normalize(card.oracle_text, card.name).split("amass orcs x. ", 1)[1].split("\n", 1)[0]
    specs = parse_effect_body(body)
    assert [spec.type for spec in specs] == ["mill", "cast_window_exiled_pool"]
    assert specs[1].params["card_filter"]["max_mana_value"] == "x"
    assert not parse_oracle(card).modeled  # unrelated Amass X remains fail-closed


def test_latest_mill_window_cannot_follow_a_card_that_leaves_and_returns_to_graveyard():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    hit, = _stock_library(eng, [_instant("Hit")])
    source = _bf(eng, _creature("Grantor"))
    effects = build_effects(parse_effect_body(
        "mill 1 card. you may cast an instant or sorcery spell from among them without paying its mana cost."
    ), source)
    effects[0].apply(eng.rules.context)
    eng.rules.exile(hit)
    p1.exile.remove(hit)
    hit.zone = Zone.GRAVEYARD
    p1.graveyard.append(hit)
    effects[1].apply(eng.rules.context)
    assert eng.state.pending_choice is None
    assert not eng.can_cast(p1, hit)


def test_mill_cast_trigger_with_unbound_x_cap_stays_unmodeled():
    card = _creature("Unbound")
    card.oracle_text = ("When Unbound enters, target opponent mills five cards. "
                        "You may cast an instant or sorcery spell with mana value X or less "
                        "from among them without paying its mana cost.")
    assert not parse_oracle(card).modeled


@pytest.mark.parametrize("verb", ["exile the top 2 cards of your library", "mill 2 cards"])
def test_resolution_local_bare_plural_pool_cast_offers_both_cards(verb):
    eng = _engine()
    player = eng.state.player_by_id("p1")
    first, second = _stock_library(eng, [_instant("First"), _instant("Second")])
    _run(eng, verb + ". you may cast instant or sorcery spells from among them without paying their mana costs.")
    eng.play_resolution_card(player, first)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["instance_ids"] == [second.instance_id]
    eng.play_resolution_card(player, second)
    eng.resolve_until_stable()
    assert first.zone == second.zone == Zone.GRAVEYARD
    assert player.mana_pool.total() == 0


@pytest.mark.parametrize("who,expected", [("target opponent", {"p2"}), ("target player", {"p1", "p2"})])
def test_mill_cast_actual_target_menu_preserves_the_milled_player_restriction(who, expected):
    eng = _engine()
    source = _bf(eng, _creature("Grantor"))
    effects = build_effects(parse_effect_body(
        who + " mills 2 cards. you may cast an instant or sorcery spell from among them without paying its mana cost."
    ), source)
    offered = targeting.legal_targets(eng.state, "p1", effects[0].target_spec, source=source)
    assert {option["player_id"] for option in offered} == expected
    _stock_library(eng, [_instant("Their Spell")], owner="p2")
    effects[0].apply(eng.rules.context, [eng.state.player_by_id("p2")])
    effects[1].apply(eng.rules.context)
    assert eng.state.pending_choice["player_id"] == "p1"


@pytest.mark.parametrize("zone", ["hand", "exile"])
def test_permanent_casting_filter_includes_battle_spells(zone):
    from test_mec106_gift import _hand

    eng = _engine()
    player = eng.state.player_by_id("p1")
    battle = Card(id="Battle", name="Battle", type_line="Battle", mana_cost_string="{2}",
                  converted_mana_cost=2, oracle_text="")
    if zone == "hand":
        obj = _hand(eng, battle)
        _run(eng, "you may cast a permanent spell from your hand without paying its mana cost.")
    else:
        obj, = _stock_library(eng, [battle])
        _run(eng, "exile the top card of your library. you may cast a permanent spell from among them without paying its mana cost.")
    assert eng.state.pending_choice["instance_ids"] == [obj.instance_id]
    eng.play_resolution_card(player, obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert player.mana_pool.total() == 0
