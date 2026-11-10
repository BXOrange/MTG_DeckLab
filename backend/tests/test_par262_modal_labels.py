"""PAR-262: flavor-labelled modal bullets (RULE 207.2c), modal-trigger mode memory and escalation (RULE 700.2).

Real cached cards on a real engine: parse verdicts first, then each newly MODELED card is executed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.modal import conditional_modal_override
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import cast, game, on_battlefield, stock_library, vanilla

FLIPPED = [
    "Dathon and Picard at El-Adrel", "Kobayashi Maru Scenario", "Set Phasers to . . .", "Stray from History",
    "Resistance Is Futile", "Emergency Holographic Crew", "Captain James T. Kirk", 'Dr. Leonard "Bones" McCoy',
]

#: Index of each Kobayashi Maru Scenario mode, in printed order.
HAIL, SENSORS, TRANSPORT, ABANDON_SHIP = "0", "1", "2", "3"


def _card(name):
    card = get_cached_card(name)
    assert card is not None, name
    return card


@pytest.mark.parametrize("name", FLIPPED)
def test_flipped_cards_are_modeled(name):
    assert parse_oracle(_card(name)).modeled


def test_rules_of_acquisition_stays_unmodeled():
    # Mode 2 ("target opponent gains control of target permanent you control") has no engine effect yet.
    assert not parse_oracle(_card("Rules of Acquisition")).modeled


def test_mode_flavor_names_stay_in_the_description_but_not_in_the_effects():
    # RULE 207.2c: "Hail — ..." is a flavor word; `gate._parse_mode_body` reads the text after it.
    modal = next(spec for spec in parse_oracle(_card("Kobayashi Maru Scenario")).specs if spec.modes)
    assert modal.modes["descriptions"][1].startswith("sensors — ")
    assert [e.type for e in modal.modes["options"][1]] == ["draw"]


def test_hand_empty_condition_is_trigger_only():
    assert conditional_modal_override("you have no cards in hand", "1 or more") is None
    assert conditional_modal_override("you have no cards in hand", "1 or more", triggered=True) == {
        "condition": {"kind": "hand_empty"}, "at_least": True, "choose": 1,
    }


def _answer(engine, option_id):
    choice = engine.state.pending_choice
    assert choice is not None and any(o["id"] == option_id for o in choice["options"]), choice
    engine.resolve_pending_choice(option_id)
    engine.resolve_until_stable()


# --- Dathon and Picard at El-Adrel -----------------------------------------------------------------------------------

def test_dathon_temba_pumps_and_grants_trample():
    engine, p1, p2 = game("Dathon and Picard at El-Adrel")
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert (bear.power, bear.toughness) == (5, 5) and combat.has(bear, "trample")


def test_dathon_shaka_makes_the_opponent_sacrifice_a_nontoken_artifact_or_enchantment():
    engine, p1, p2 = game("Dathon and Picard at El-Adrel")
    wanted = GameObject(Card(id="E1", name="Ench", type_line="Enchantment"), owner_id="p2",
                        zone=Zone.BATTLEFIELD)
    token = GameObject(Card(id="A1", name="Rock", type_line="Artifact"), owner_id="p2",
                       zone=Zone.BATTLEFIELD, is_token=True)
    creature = vanilla(engine, "p2")
    for obj in (wanted, token):
        obj.controller_id = "p2"
        engine.state.add_to_battlefield(obj)
    cast(engine, p1, p1.hand[0], mode=1)
    if engine.state.pending_choice:  # a single legal pick may be taken without asking
        _answer(engine, engine.state.pending_choice["options"][0]["id"])
    assert wanted not in engine.state.battlefield
    assert token in engine.state.battlefield and creature in engine.state.battlefield  # token and creature stay


# --- Set Phasers to . . . --------------------------------------------------------------------------------------------

def test_set_phasers_kill_deals_three_to_an_attacking_creature():
    engine, p1, p2 = game("Set Phasers to . . .")
    foe = vanilla(engine, "p2", "Foe", 2, 3)
    foe.attacking = True
    cast(engine, p1, p1.hand[0], targets=[foe], mode=1)
    assert foe not in engine.state.battlefield


def test_set_phasers_stun_taps_and_stuns():
    engine, p1, p2 = game("Set Phasers to . . .")
    foe = vanilla(engine, "p2", "Foe", 2, 3)
    cast(engine, p1, p1.hand[0], targets=[foe], mode=0)
    assert foe.tapped and foe.counters.get("stun") == 1


# --- Resistance Is Futile / Emergency Holographic Crew / Stray from History ------------------------------------------

def _graveyard_card(engine, player_id, card):
    obj = GameObject(card, owner_id=player_id, zone=Zone.GRAVEYARD)
    engine.state.player_by_id(player_id).graveyard.append(obj)
    return obj


def test_resistance_reanimates_an_artifact_creature_with_mana_value_three_or_less():
    engine, p1, p2 = game("Resistance Is Futile")
    small = _graveyard_card(engine, "p1", Card(id="AC", name="Gizmo", type_line="Artifact Creature — Construct",
                                               is_creature=True, power=1, toughness=1, converted_mana_cost=3))
    big = _graveyard_card(engine, "p1", Card(id="AB", name="Big Gizmo", type_line="Artifact Creature — Construct",
                                             is_creature=True, power=4, toughness=4, converted_mana_cost=4))
    plain = _graveyard_card(engine, "p1", Card(id="CR", name="Plain", type_line="Creature — Bear",
                                               is_creature=True, power=2, toughness=2, converted_mana_cost=2))
    cast(engine, p1, p1.hand[0], targets=[small], mode=1)
    assert small in engine.state.battlefield
    assert big not in engine.state.battlefield and plain not in engine.state.battlefield


def test_resistance_destroys_a_nonartifact_creature():
    engine, p1, p2 = game("Resistance Is Futile")
    foe = vanilla(engine, "p2")
    cast(engine, p1, p1.hand[0], targets=[foe], mode=0)
    assert foe not in engine.state.battlefield


def test_emergency_holographic_crew_returns_a_spacecraft_card():
    engine, p1, p2 = game("Emergency Holographic Crew")
    ship = _graveyard_card(engine, "p1", Card(id="SC", name="Ship", type_line="Artifact — Spacecraft",
                                              converted_mana_cost=3))
    bear = _graveyard_card(engine, "p1", Card(id="CR", name="Plain", type_line="Creature — Bear",
                                              is_creature=True, power=2, toughness=2, converted_mana_cost=2))
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice and engine.state.pending_choice["kind"] == "trigger_mode":
        _answer(engine, "0")
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        _answer(engine, choice["options"][0]["id"])
    assert ship in p1.hand and bear not in p1.hand


def test_stray_from_history_returns_up_to_two_creature_or_spacecraft_cards():
    engine, p1, p2 = game("Stray from History")
    ship = _graveyard_card(engine, "p1", Card(id="SC", name="Ship", type_line="Artifact — Spacecraft",
                                              converted_mana_cost=3))
    bear = _graveyard_card(engine, "p1", Card(id="CR", name="Plain", type_line="Creature — Bear",
                                              is_creature=True, power=2, toughness=2, converted_mana_cost=2))
    land = _graveyard_card(engine, "p1", Card(id="LD", name="Forest", type_line="Land", is_land=True))
    cast(engine, p1, p1.hand[0], targets=[ship, bear], mode=0)
    assert ship in p1.hand and bear in p1.hand and land not in p1.hand


def test_stray_from_history_repair_the_timeline_exiles_a_nonland_card_from_their_hand():
    engine, p1, p2 = game("Stray from History")
    spell = GameObject(Card(id="SP", name="Spell", type_line="Sorcery", is_sorcery=True, converted_mana_cost=2), owner_id="p2",
                       zone=Zone.HAND)
    land = GameObject(Card(id="LD", name="Forest", type_line="Land", is_land=True), owner_id="p2", zone=Zone.HAND)
    p2.hand.extend([spell, land])
    cast(engine, p1, p1.hand[0], targets=[p2], mode=1)
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        pick = next((o["id"] for o in choice["options"] if str(spell.instance_id) == str(o["id"])),
                    choice["options"][0]["id"])
        _answer(engine, pick)
    assert spell not in p2.hand and land in p2.hand
    assert spell.zone == Zone.EXILE


# --- Kobayashi Maru Scenario -----------------------------------------------------------------------------------------

def _to_own_upkeep(engine, pid="p1"):
    for _ in range(40):
        engine.advance_step()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == pid:
            return
    raise AssertionError("never reached the upkeep")


def _kobayashi():
    engine, p1, p2 = game(via_steps=True)
    kms = on_battlefield(engine, "p1", "Kobayashi Maru Scenario")
    _to_own_upkeep(engine)
    return engine, p1, p2, kms


def test_kobayashi_offers_all_four_modes_and_sensors_draws_two():
    engine, p1, p2, kms = _kobayashi()
    assert [o["id"] for o in engine.state.pending_choice["options"]] == [HAIL, SENSORS, TRANSPORT, ABANDON_SHIP]
    before = len(p1.hand)
    _answer(engine, SENSORS)
    assert len(p1.hand) == before + 2


def test_kobayashi_a_chosen_mode_is_gone_next_upkeep_and_the_memory_survives_clone():
    engine, p1, p2, kms = _kobayashi()
    _answer(engine, TRANSPORT)
    tokens = [o for o in engine.state.battlefield if o.name == "Officer"]
    assert len(tokens) == 2
    ability = kms.triggered_abilities[0]
    assert ability._chosen_modes_permanent == {int(TRANSPORT)}
    clone = engine.state.clone()
    cloned = next(o for o in clone.battlefield if o.name == "Kobayashi Maru Scenario")
    assert cloned.triggered_abilities[0]._chosen_modes_permanent == {int(TRANSPORT)}
    # The next upkeep of p1 no longer offers Transport.
    for stock in ("p1", "p2"):
        stock_library(engine, stock, 6)
    _to_own_upkeep(engine)
    assert [o["id"] for o in engine.state.pending_choice["options"]] == [HAIL, SENSORS, ABANDON_SHIP]


def test_kobayashi_hail_bounces_an_opponents_cheap_creature():
    engine, p1, p2, kms = _kobayashi()
    foe = vanilla(engine, "p2", "Foe", 2, 2)
    engine.resolve_pending_choice(HAIL)
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        engine.resolve_pending_choice(choice["options"][0]["id"])
    engine.resolve_until_stable()
    assert foe not in engine.state.battlefield and foe in p2.hand


def test_kobayashi_modes_start_over_for_a_new_object():
    engine, p1, p2, kms = _kobayashi()
    ability = kms.triggered_abilities[0]
    ability._chosen_modes_permanent = {0, 1, 2}
    kms.reset_as_new_object()  # RULE 400.7: leaving and re-entering makes a new object
    assert ability._chosen_modes_permanent == set()


def test_kobayashi_last_remaining_mode_is_abandon_ship():
    engine, p1, p2 = game(via_steps=True)
    kms = on_battlefield(engine, "p1", "Kobayashi Maru Scenario")
    kms.triggered_abilities[0]._chosen_modes_permanent = {0, 1, 2}
    _to_own_upkeep(engine)
    assert [o["id"] for o in engine.state.pending_choice["options"]] == [ABANDON_SHIP]
    _answer(engine, ABANDON_SHIP)
    assert p1.has_lost


# --- Captain James T. Kirk -------------------------------------------------------------------------------------------

def _kirk_enters(hand_extra):
    engine, p1, p2 = game("Captain James T. Kirk")
    for i in range(hand_extra):
        p1.hand.append(GameObject(Card(id=f"H{i}", name=f"Filler {i}", type_line="Land", is_land=True),
                                  owner_id="p1", zone=Zone.HAND))
    stock_library(engine, "p1", 3)
    cast(engine, p1, p1.hand[0])
    return engine, p1


def test_kirk_with_cards_in_hand_chooses_exactly_one_mode():
    engine, p1 = _kirk_enters(hand_extra=1)
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    _answer(engine, "1")  # create an Officer token
    assert engine.state.pending_choice is None
    assert len([o for o in engine.state.battlefield if o.name == "Officer"]) == 1


def test_kirk_with_an_empty_hand_may_choose_one_or_more_modes():
    engine, p1 = _kirk_enters(hand_extra=0)
    assert not p1.hand
    _answer(engine, "1")
    choice = engine.state.pending_choice
    assert choice is not None and any(o["id"] == "done" for o in choice["options"])
    _answer(engine, "2")  # the +1/+0 anthem as well; all but the picked ones remain, so "done" is offered
    if engine.state.pending_choice:
        _answer(engine, "done")
    assert len([o for o in engine.state.battlefield if o.name == "Officer"]) == 1


# --- Dr. Leonard "Bones" McCoy ---------------------------------------------------------------------------------------

def test_mccoy_returns_a_non_doctor_permanent_card_from_the_graveyard():
    engine, p1, p2 = game('Dr. Leonard "Bones" McCoy')
    doctor = _graveyard_card(engine, "p1", Card(id="DR", name="Doc", type_line="Creature — Human Doctor",
                                                is_creature=True, power=1, toughness=1, converted_mana_cost=1))
    bear = _graveyard_card(engine, "p1", Card(id="CR", name="Plain", type_line="Creature — Bear",
                                              is_creature=True, power=2, toughness=2, converted_mana_cost=2))
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice and engine.state.pending_choice["kind"] == "trigger_mode":
        _answer(engine, "0")
    while engine.state.pending_choice:
        _answer(engine, engine.state.pending_choice["options"][0]["id"])
    assert bear in p1.hand and doctor not in p1.hand


def test_mccoy_second_mode_returns_the_creature_with_a_counter_at_the_next_end_step():
    engine, p1, p2 = game('Dr. Leonard "Bones" McCoy', via_steps=True)
    ally = vanilla(engine, "p1", "Ally", 1, 1)
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice and engine.state.pending_choice["kind"] == "trigger_mode":
        _answer(engine, "1")
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        pick = next((o["id"] for o in choice["options"] if str(ally.instance_id) == str(o["id"])),
                    choice["options"][0]["id"])
        _answer(engine, pick)
    engine.rules.destroy(ally)
    engine.resolve_until_stable()
    assert ally not in engine.state.battlefield
    for _ in range(12):
        if engine.state.current_step == "end":
            break
        engine.advance_step()
    engine.resolve_until_stable()
    back = [o for o in engine.state.battlefield if o.name == "Ally"]
    assert len(back) == 1 and back[0].counters.get("+1/+1") == 1


# --- Cards that flipped through the shared pieces (label peeling, "you lose the game", permanence memory, ...) -------

def _upkeep_game(card_name):
    engine, p1, p2 = game(via_steps=True)
    permanent = on_battlefield(engine, "p1", card_name)
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    _to_own_upkeep(engine)
    return engine, p1, p2, permanent


def test_demonic_pact_modes_are_spent_one_by_one_and_the_last_loses_the_game():
    engine, p1, p2, pact = _upkeep_game("Demonic Pact")
    assert [o["id"] for o in engine.state.pending_choice["options"]] == ["0", "1", "2", "3"]
    before = len(p1.hand)
    _answer(engine, "2")  # draw two cards
    assert len(p1.hand) == before + 2
    ability = pact.triggered_abilities[0]
    ability._chosen_modes_permanent = {0, 1, 2}
    engine.state.pending_choice = None
    _to_own_upkeep(engine)
    assert [o["id"] for o in engine.state.pending_choice["options"]] == ["3"]
    _answer(engine, "3")
    assert p1.has_lost


def test_demonic_pact_with_every_mode_spent_creates_no_trigger():
    engine, p1, p2 = game(via_steps=True)
    pact = on_battlefield(engine, "p1", "Demonic Pact")
    pact.triggered_abilities[0]._chosen_modes_permanent = {0, 1, 2, 3}
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    _to_own_upkeep(engine)
    assert engine.state.pending_choice is None and not p1.has_lost


def test_kimoyo_beads_prime_bead_makes_a_new_object_that_forgets_its_modes():
    engine, p1, p2 = game(via_steps=True)
    beads = on_battlefield(engine, "p1", "Kimoyo Beads")
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    while not (engine.state.current_step == "end" and engine.state.pending_choice):
        engine.advance_step()
    assert [o["id"] for o in engine.state.pending_choice["options"]] == ["0", "1", "2"]
    _answer(engine, "2")  # Prime Bead: gain 3, exile and return it
    returned = next(o for o in engine.state.battlefield if o.name == "Kimoyo Beads")
    assert p1.life == 23
    assert returned.triggered_abilities[0]._chosen_modes_permanent == set()


def test_labelled_spell_modes_choose_your_weapon_and_you_hear_something_on_watch():
    engine, p1, p2 = game("Choose Your Weapon", "You Hear Something on Watch")
    bear = vanilla(engine, "p1", "Bear", 2, 2)
    in_hand = {o.name: o for o in p1.hand}
    cast(engine, p1, in_hand["Choose Your Weapon"], targets=[bear], mode=0)  # Two-Weapon Fighting
    assert (bear.power, bear.toughness) == (4, 4)
    cast(engine, p1, in_hand["You Hear Something on Watch"], mode=0)  # Rouse the Party
    assert (bear.power, bear.toughness) == (5, 5)


def test_one_with_death_loses_the_game():
    engine, p1, p2 = game("One with Death")
    cast(engine, p1, p1.hand[0])
    assert p1.has_lost and not p2.has_lost


def test_archfiend_of_the_dross_last_oil_counter_loses_the_game():
    engine, p1, p2 = game(via_steps=True)
    fiend = on_battlefield(engine, "p1", "Archfiend of the Dross")
    fiend.counters["oil"] = 1
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    _to_own_upkeep(engine)
    engine.resolve_until_stable()
    assert p1.has_lost


def test_tribute_to_the_wild_makes_each_opponent_sacrifice_an_artifact_or_enchantment():
    engine, p1, p2 = game("Tribute to the Wild")
    art = GameObject(Card(id="A1", name="Rock", type_line="Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
    art.controller_id = "p2"
    engine.state.add_to_battlefield(art)
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        _answer(engine, engine.state.pending_choice["options"][0]["id"])
    assert art not in engine.state.battlefield


def test_first_stage_of_magic_design_this_spell_deals_damage():
    engine, p1, p2 = game("First Stage of Magic Design")
    bear = vanilla(engine, "p1", "Bear", 2, 2)
    stock_library(engine, "p1", 5)
    cast(engine, p1, p1.hand[0], targets=[p2, bear])
    assert (p1.life, p2.life, (bear.power, bear.toughness)) == (23, 17, (5, 5))


@pytest.mark.parametrize("name", ["Gandalf the Grey", "Silent Hallcreeper", "MagicConsecrated Sphinx", "Demonic Pact"])
def test_unbounded_choose_one_that_hasnt_been_chosen_cards_carry_permanent_memory(name):
    result = parse_oracle(_card(name))
    modal = next(spec for spec in result.specs if spec.modes)
    assert modal.modes["exhaust_permanent"] is True and modal.modes["exhaust_per_turn"] is False


def test_spell_header_with_unbounded_exhaust_stays_unclaimed():
    from mtg_analyzer.parser.oracle.catalogue.modal import split_modal_block
    lines = ["choose 1 that hasn't been chosen —", "• draw 2 cards.", "• gain 3 life."]
    assert split_modal_block(lines, 0) is None
