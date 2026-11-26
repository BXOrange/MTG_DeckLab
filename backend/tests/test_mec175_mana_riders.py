"""MEC-175 (RULE 605.1a / 605.3b / 608.2c / 603.7 / 106.6): the shared rider shapes after a mana ability's Add clause.

Each shape is a `ManaAbility` field read through `parser/oracle/mana_riders.py` (the parser claims it exactly when the
engine runs it), applied by `GameEngine.tap_for_mana`: an "if ..., add ... instead" production, a life gain, an
immediate or delayed draw, a counter-exhaustion sacrifice, a wider "Activate only if" condition, and the payoffs of
mana spent on a matching spell.
"""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, PARSER_VERSION, parse_oracle
from mtg_analyzer.parser.oracle.mana_riders import (
    instead_rider, is_executed_rider, life_rider, mana_condition_dict,
)
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, filler, game, main_phase, step

_PROVENANCE = ParserProvenance(version=PARSER_VERSION, source="test")


def _claimed(line):
    return segment_line(line, allow_spell_effect=True, provenance=_PROVENANCE).claimed


def _real(name):
    return CardDatabase(DB_PATH).get_card(name)


def _tap(eng, source, **kw):
    return eng.tap_for_mana(eng.state.player_by_id("p1"), source, **kw)


# --- "If <condition>, add <mana> instead." ------------------------------------------------------------------------


def test_the_urza_lands_add_two_colorless_only_with_their_two_siblings():
    eng = game()
    mine = card(eng, "Urza's Mine")
    assert _tap(eng, mine) == {"C": 1}
    eng = game()
    mine = card(eng, "Urza's Mine")
    card(eng, "Urza's Tower")
    assert _tap(eng, mine) == {"C": 1}  # the Power-Plant is missing
    eng = game()
    mine = card(eng, "Urza's Mine")
    card(eng, "Urza's Tower")
    card(eng, "Urza's Power Plant")  # printed without the hyphen the oracle text uses
    assert _tap(eng, mine) == {"C": 2}


def test_urza_s_tower_adds_three_with_the_mine_and_the_power_plant():
    eng = game()
    tower = card(eng, "Urza's Tower")
    card(eng, "Urza's Mine")
    card(eng, "Urza's Power Plant")
    assert _tap(eng, tower) == {"C": 3}


def test_a_creature_count_condition_doubles_the_druids_mana():
    eng = game()
    druid = card(eng, "Leafkin Druid")
    assert _tap(eng, druid) == {"G": 1}
    eng = game()
    druid = card(eng, "Leafkin Druid")
    for index in range(3):
        filler(eng, f"Bear {index}", power=2, toughness=2)
    assert _tap(eng, druid) == {"G": 2}  # the druid and three bears: four creatures


def test_a_power_condition_chooses_two_mana_of_one_color():
    eng = game()
    caryatid = card(eng, "Ilysian Caryatid")
    assert [list(o.values()) for o in mana_abilities_for(caryatid, eng.state)[0].options] == [[1]] * 5
    filler(eng, "Big", power=4, toughness=4)
    assert _tap(eng, caryatid, option_index=2) == {"B": 2}


def test_the_instead_clause_may_change_the_color_and_the_option_count():
    eng = game()
    river = card(eng, "River of Tears")
    assert _tap(eng, river) == {"U": 1}
    eng = game()
    river = card(eng, "River of Tears")
    eng.state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id="p1", controller_id="p1"))
    assert _tap(eng, river) == {"B": 1}
    eng = game()
    caverns = card(eng, "Gemstone Caverns")
    assert [o for o in mana_abilities_for(caverns, eng.state)[0].options] == [{"C": 1}]
    caverns.counters["luck"] = 1
    assert len(mana_abilities_for(caverns, eng.state)[0].options) == 5  # "instead add one mana of any color"
    assert _tap(eng, caverns, option_index=3) == {"R": 1}


def test_named_creatures_condition_reads_each_name():
    eng = game()
    worker = card(eng, "Tower Worker")
    filler(eng, "Mine Worker", power=1, toughness=1)
    assert _tap(eng, worker) == {"C": 1}
    eng = game()
    worker = card(eng, "Tower Worker")
    filler(eng, "Mine Worker", power=1, toughness=1)
    filler(eng, "Power Plant Worker", power=1, toughness=1)
    assert _tap(eng, worker) == {"C": 3}


def test_the_commanders_color_identity_override_reads_its_count():
    ability = parse_mana_abilities(_real("Command Mine"))[0]
    assert ability.instead.color_selector == "colors_in_commanders_color_identity"
    assert ability.instead.amount_selector == {"kind": "literal", "n": 2}
    assert ability.instead_when["kind"] == "all"


def test_an_unreadable_override_condition_or_clause_is_not_claimed():
    assert instead_rider("if the moon is full, add {g}{g} instead.") is None
    assert instead_rider("if you control 4 or more creatures, add 3 mana of that type instead.") is None
    assert instead_rider("if you control 4 or more creatures, add {g}{g} instead.") is not None
    assert not is_executed_rider("if you control a flurb, add {g}{g} instead.")
    assert not _claimed("{t}: add {g}. if the moon is full, add {g}{g} instead.")
    assert _claimed("{t}: add {g}. if you control 4 or more creatures, add {g}{g} instead.")


# --- life, draws, exhaustion -------------------------------------------------------------------------------------


def test_a_life_gain_rider_gains_life_as_the_ability_resolves():
    eng = game()
    talisman = card(eng, "Pristine Talisman")
    assert _tap(eng, talisman) == {"C": 1}
    assert eng.state.player_by_id("p1").life == 21
    assert not eng.state.stack  # RULE 605.3b: no stack
    eng = game()
    henge = card(eng, "The Great Henge")
    assert _tap(eng, henge) == {"G": 2}
    assert eng.state.player_by_id("p1").life == 22


def test_a_conditional_life_gain_needs_its_condition():
    eng = game()
    tom = card(eng, "Black Tom Cassidy")
    _tap(eng, tom)
    assert eng.state.player_by_id("p1").life == 20  # no other Mutant
    eng = game()
    tom = card(eng, "Black Tom Cassidy")
    filler(eng, "Other Mutant", type_line="Creature — Mutant", power=1, toughness=1)
    _tap(eng, tom)
    assert eng.state.player_by_id("p1").life == 21
    eng = game()
    reclaimer = card(eng, "Avid Reclaimer")
    _tap(eng, reclaimer)
    assert eng.state.player_by_id("p1").life == 20
    filler(eng, "Nissa", type_line="Legendary Planeswalker — Nissa", loyalty=3)
    reclaimer.tapped = False
    _tap(eng, reclaimer)
    assert eng.state.player_by_id("p1").life == 22


def test_an_unreadable_life_condition_is_not_claimed():
    assert life_rider("if you control a god, a demigod, or a legendary enchantment, you gain 1 life.") is None
    assert life_rider("you gain 1 life.").amount == 1
    assert not _claimed("{t}: add one mana of any color. if you control a flurb, you gain 1 life.")


def test_a_draw_rider_draws_with_the_mana_and_uses_no_stack():
    eng = game()
    player = eng.state.player_by_id("p1")
    sphere = card(eng, "Chromatic Sphere")
    player.mana_pool.add_many({"C": 1})
    hand = len(player.hand)
    _tap(eng, sphere)
    assert len(player.hand) == hand + 1
    assert sphere.zone == Zone.GRAVEYARD  # the sacrifice is its cost
    assert not eng.state.stack


def test_a_delayed_draw_uses_the_stack_at_the_next_turns_upkeep():
    eng = game()
    player = eng.state.player_by_id("p1")
    astrolabe = card(eng, "Astrolabe")
    player.mana_pool.add_many({"C": 1})
    hand = len(player.hand)
    assert _tap(eng, astrolabe) == {"W": 2}
    assert len(player.hand) == hand and not eng.state.stack
    assert len(eng.state.delayed_triggers) == 1
    step(eng, "upkeep")  # this turn's own upkeep (already past in real play) does not draw
    assert len(player.hand) == hand
    eng.state.internal_turn.number += 1
    eng._fire_delayed_triggers("upkeep")
    assert len(eng.state.stack) == 1  # RULE 603.7: a delayed triggered ability on the stack
    eng.resolve_until_stable()
    assert len(player.hand) == hand + 1 and not eng.state.delayed_triggers


def test_a_depleted_land_sacrifices_itself_after_its_last_counter():
    eng = game()
    bog = card(eng, "Peat Bog")
    bog.counters["depletion"] = 2
    assert _tap(eng, bog) == {"B": 2}
    assert bog.counters["depletion"] == 1 and bog.zone == Zone.BATTLEFIELD
    bog.tapped = False
    assert _tap(eng, bog) == {"B": 2}
    assert bog.zone == Zone.GRAVEYARD  # "If there are no depletion counters on this land, sacrifice it."


def test_gemstone_mine_counts_its_own_counter_kind():
    eng = game()
    mine = card(eng, "Gemstone Mine")
    mine.counters["mining"] = 1
    _tap(eng, mine)
    assert mine.zone == Zone.GRAVEYARD  # "If there are no mining counters on this land, sacrifice it."


# --- "Activate only if" conditions --------------------------------------------------------------------------------


def test_activate_only_if_entered_this_turn_or_you_control_a_basic_land():
    fortress_ability = parse_mana_abilities(_real("Dark Fortress"))[1]
    assert fortress_ability.cost.activation_condition["kind"] == "any"
    eng = game()
    fortress = card(eng, "Dark Fortress")
    eng.state.internal_turn.number += 3  # the fortress did not arrive this turn
    with pytest.raises(ValueError):
        _tap(eng, fortress, ability_index=1)
    card(eng, "Swamp")
    assert _tap(eng, fortress, ability_index=1, option_index=1) == {"R": 1}


def test_three_lands_with_the_same_name_unlock_the_sceptre():
    eng = game()
    sceptre = card(eng, "Sceptre of Eternal Glory")
    with pytest.raises(ValueError):
        _tap(eng, sceptre, ability_index=1)
    for _ in range(3):
        card(eng, "Forest")
    assert _tap(eng, sceptre, ability_index=1, option_index=4) == {"G": 3}


def test_a_compound_condition_that_names_an_unread_part_is_not_claimed():
    assert mana_condition_dict("~ entered this turn or if you control a basic land") is not None
    assert mana_condition_dict("~ entered this turn or if the moon is full") is None
    assert mana_condition_dict("you control a flurb and a quux") is not None  # two names read as card names
    assert mana_condition_dict("you control a flurb") is None  # a lone unread noun is a vocabulary gap


# --- mana-spend payoffs ------------------------------------------------------------------------------------------


def _cast_creature(eng, subtype, cost="{G}", mv=1):
    main_phase(eng)
    spell = filler(eng, "Test spell", type_line="Creature — " + subtype, zone=Zone.HAND, mv=mv, power=2, toughness=2,
                   mana_cost_string=cost)
    eng.cast_spell(eng.state.player_by_id("p1"), spell)
    eng.rules.check_state_based_actions()
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    return spell


def test_a_dragon_spell_paid_with_the_mana_gains_the_controller_life():
    eng = game()
    main_phase(eng)
    _tap(eng, card(eng, "Scaled Nurturer"))
    _cast_creature(eng, "Dragon")
    assert eng.state.player_by_id("p1").life == 22


def test_a_non_dragon_spell_does_not_pay_the_dragon_payoff():
    eng = game()
    main_phase(eng)
    _tap(eng, card(eng, "Scaled Nurturer"))
    _cast_creature(eng, "Bear")
    assert eng.state.player_by_id("p1").life == 20


def test_big_spells_paid_with_gilanras_mana_draw_a_card():
    eng = game()
    main_phase(eng)
    player = eng.state.player_by_id("p1")
    _tap(eng, card(eng, "Gilanra, Caller of Wirewood"))
    hand = len(player.hand)
    _cast_creature(eng, "Bear", mv=6)
    assert len(player.hand) == hand + 1
    eng = game()
    main_phase(eng)
    player = eng.state.player_by_id("p1")
    _tap(eng, card(eng, "Gilanra, Caller of Wirewood"))
    hand = len(player.hand)
    _cast_creature(eng, "Bear", mv=1)
    assert len(player.hand) == hand


def test_exerted_arena_of_glory_gives_a_creature_spell_haste_this_turn():
    eng = game()
    main_phase(eng)
    player = eng.state.player_by_id("p1")
    arena = card(eng, "Arena of Glory")
    player.mana_pool.add_many({"R": 1})
    _tap(eng, arena, ability_index=1)
    spell = _cast_creature(eng, "Bear", cost="{R}")
    eng.recompute_continuous_effects()
    assert "haste" in spell.granted_keywords


def test_the_unspent_arena_mana_grants_nothing_to_a_noncreature_spell():
    ability = parse_mana_abilities(_real("Arena of Glory"))[1]
    assert ability.spend_rider == {"kind": "grant_keyword", "keyword": "haste", "duration": "end_of_turn",
                                   "creature": True}


def test_scry_and_commander_payoffs_are_read():
    lapis = parse_mana_abilities(_real("Lapis Orb of Dragonkind"))[0]
    assert lapis.spend_rider == {"kind": "scry", "count": 2, "creature": True, "subtype": "Dragon", "triggered": True}
    hall = parse_mana_abilities(_real("Study Hall"))[1]
    assert hall.spend_rider == {"kind": "scry", "count": "commander_casts", "commander": True, "triggered": True}


def test_brass_infiniscope_pays_a_card_and_half_x_for_the_next_x_spell():
    eng = game()
    main_phase(eng)
    player = eng.state.player_by_id("p1")
    scope = card(eng, "Brass Infiniscope")
    _tap(eng, scope)
    hand = len(player.hand)
    spell = filler(eng, "X spell", type_line="Sorcery", zone=Zone.HAND, mana_cost_string="{X}{G}")
    player.mana_pool.add_many({"G": 5})
    eng.cast_spell(player, spell, x=3)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert len(player.hand) == hand + 1
    assert player.life == 21  # half of X=3, rounded down


# --- claims -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Urza's Mine", "Urza's Tower", "Urza's Power Plant", "Leafkin Druid", "Raucous Audience", "Ilysian Caryatid",
    "River of Tears", "Gemstone Caverns", "Command Mine", "Pristine Talisman", "Black Tom Cassidy", "Avid Reclaimer",
    "Chromatic Sphere", "Darkwater Egg", "Astrolabe", "Barbed Sextant", "Peat Bog", "Gemstone Mine",
    "Sandstone Needle", "Hickory Woodlot", "Dark Fortress", "Gathering Place", "Scaled Nurturer",
    "Gilanra, Caller of Wirewood", "Brass Infiniscope", "Lapis Orb of Dragonkind", "Carnelian Orb of Dragonkind",
])
def test_cards_whose_riders_the_engine_now_runs_are_modeled(name):
    printed = _real(name)
    if printed is None:
        pytest.skip(f"{name} is not in this cache")
    assert parse_oracle(printed).coverage == MODELED


def test_a_fresh_arrival_unlocks_the_dual_land_without_a_basic():
    eng = game()
    fortress = card(eng, "Dark Fortress")
    assert _tap(eng, fortress, ability_index=1) == {"B": 1}  # "entered this turn"


def test_path_of_ancestry_pays_off_only_for_a_creature_sharing_a_commander_type():
    path = parse_mana_abilities(_real("Path of Ancestry"))[0]
    assert path.spend_rider == {
        "kind": "scry", "count": 1, "creature": True, "shares_type_with_commander": True, "triggered": True,
    }
    assert parse_oracle(_real("Path of Ancestry")).coverage == MODELED


def test_hall_of_the_bandit_lord_haste_lasts_the_rest_of_the_game():
    hall = parse_mana_abilities(_real("Hall of the Bandit Lord"))[0]
    assert hall.spend_rider["duration"] == "rest_of_game"
