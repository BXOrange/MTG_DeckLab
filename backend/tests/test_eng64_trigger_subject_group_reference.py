"""ENG-64: a group effect under a trigger compares "it" / "that creature" with the object the trigger names.

RULE 603.2 / 608.2c: "Whenever a creature enters, destroy all other creatures that share a color with it" compares with the
creature that entered, never with the ability's source. RULE 608.2h: a trigger subject that already left the battlefield is
read as last known information. Real cards from the cache (Spreading Plague, Eye of Singularity, Martyr's Bond, Faces of the
Past) with near misses and bystanders; the source's own characteristics differ from the subject's in every test.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

PLAGUE = "Spreading Plague"  # an Enchantment whose own color is black ({4}{B})
EYE = "Eye of Singularity"
BOND = "Martyr's Bond"
FACES = "Faces of the Past"
MANA = {"C": 5, "R": 3, "G": 3, "U": 3, "B": 3, "W": 3}  # a mana pool that pays any cost these tests cast


def _real(name):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    return card


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _creature(name, cost, types="Bear"):
    return Card(id=name, name=name, type_line=f"Creature — {types}", is_creature=True, power=2, toughness=2,
                mana_cost_string=cost, converted_mana_cost=1)


def _enter(eng, card, controller="p1"):
    """A real cast and resolution, so the enters trigger fires from the real event."""
    player = eng.state.player_by_id(controller)
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    player.mana_pool.add_many(dict(MANA))
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    return obj


def _names(eng):
    return sorted(o.name for o in eng.state.battlefield)


def _kill(eng, obj):
    eng.rules.destroy(obj)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


# -- Spreading Plague -----------------------------------------------------------------------------------------------


def test_spreading_plague_is_modeled_with_a_trigger_subject_reference():
    result = parse_oracle(_real(PLAGUE))
    assert result.modeled, result.unclaimed
    group = result.specs[0].effects[0].params["group"]
    assert group["reference"] == "trigger_subject"
    assert group["filter"]["shares_color_with_reference"] and group["filter"]["not_reference"]


def test_plague_destroys_creatures_sharing_a_color_with_the_entering_one_not_with_the_source():
    eng = _engine()
    _put(eng, _real(PLAGUE))  # black: a black bystander must survive a red creature entering
    red = _put(eng, _creature("Red Bear", "{R}"))
    red_green = _put(eng, _creature("Red Green Bear", "{R}{G}"), "p2")
    blue = _put(eng, _creature("Blue Bear", "{U}"), "p2")
    black = _put(eng, _creature("Black Bear", "{B}"), "p2")
    _enter(eng, _creature("Entering Red Bear", "{R}"))
    # Shares red: destroyed (either controller, either of its colors). Blue/black do not; black is the source's color.
    assert red not in eng.state.battlefield and red_green not in eng.state.battlefield
    assert blue in eng.state.battlefield and black in eng.state.battlefield
    assert "Entering Red Bear" in _names(eng)  # "other": the creature that entered is not destroyed


def test_plague_a_colorless_creature_entering_destroys_nothing():
    eng = _engine()
    _put(eng, _real(PLAGUE))
    red = _put(eng, _creature("Red Bear", "{R}"))
    colorless = _put(eng, _creature("Colorless Bear", ""), "p2")
    _enter(eng, _creature("Entering Colorless Bear", ""))
    assert red in eng.state.battlefield and colorless in eng.state.battlefield  # RULE 105.2c: no color to share


def test_plague_destroyed_creatures_cannot_regenerate():
    spec = parse_oracle(_real(PLAGUE)).specs[0].effects[0]
    assert spec.params["can_be_regenerated"] is False


def test_a_self_trigger_with_the_same_clause_is_not_claimed():
    # "it" under a self trigger is the source itself, which this reference cannot express: the clause stays unclaimed.
    card = Card(id="Probe", name="Probe", type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1,
                oracle_text="When this enchantment enters, destroy all other creatures that share a color with it.")
    assert not parse_oracle(card).modeled


def test_a_modal_option_with_an_unreferenced_relative_group_is_not_claimed():
    card = Card(id="Probe", name="Probe", type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1,
                oracle_text="Whenever a creature dies, choose one —\n• Tap all untapped creatures that share a creature "
                            "type with it.\n• Untap all tapped creatures that share a creature type with it.")
    assert not parse_oracle(card).modeled  # it would compare with the enchantment, not the creature that died


# -- Eye of Singularity -----------------------------------------------------------------------------------------------


def test_eye_is_modeled():
    assert parse_oracle(_real(EYE)).modeled


def test_eye_entering_destroys_every_nonbasic_permanent_whose_name_another_permanent_shares():
    eng = _engine()
    twin_a = _put(eng, _creature("Twin", "{G}"))
    twin_b = _put(eng, _creature("Twin", "{G}"), "p2")
    single = _put(eng, _creature("Single", "{G}"))
    forest_a = _put(eng, Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True))
    forest_b = _put(eng, Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True), "p2")
    _enter(eng, _real(EYE))
    assert twin_a not in eng.state.battlefield and twin_b not in eng.state.battlefield
    assert single in eng.state.battlefield
    assert forest_a in eng.state.battlefield and forest_b in eng.state.battlefield  # "except for basic lands"
    assert EYE in _names(eng)  # no other permanent shares the Eye's own name


def test_eye_a_permanent_entering_destroys_the_others_with_its_name_but_not_itself():
    eng = _engine()
    _put(eng, _real(EYE))
    old_a = _put(eng, _creature("Wolf", "{G}"))
    old_b = _put(eng, _creature("Wolf", "{G}"), "p2")
    other = _put(eng, _creature("Bear", "{G}"), "p2")
    arrived = _enter(eng, _creature("Wolf", "{G}"))
    assert old_a not in eng.state.battlefield and old_b not in eng.state.battlefield
    assert other in eng.state.battlefield and arrived in eng.state.battlefield


def test_eye_a_basic_land_entering_does_not_trigger():
    eng = _engine()
    _put(eng, _real(EYE))
    plains = _put(eng, Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True))
    player = eng.state.player_by_id("p1")
    second = GameObject(Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True), owner_id="p1", zone=Zone.HAND)
    player.hand.append(second)
    eng.play_land(player, second)
    eng.resolve_until_stable()
    assert plains in eng.state.battlefield and second in eng.state.battlefield


# -- Martyr's Bond ------------------------------------------------------------------------------------------------------


def test_martyrs_bond_is_modeled_with_the_shared_type_reference():
    result = parse_oracle(_real(BOND))
    assert result.modeled, result.unclaimed
    assert result.specs[0].effects[0].params["shares_type_with"] == "trigger_subject"


def test_martyrs_bond_the_opponent_sacrifices_a_permanent_sharing_a_type_with_the_dying_one():
    eng = _engine()
    _put(eng, _real(BOND))  # an Enchantment: an enchantment of the opponent's must NOT be a candidate for a dying creature
    dying = _put(eng, _creature("Dying Bear", "{G}"))
    victim = _put(eng, _creature("Opposing Bear", "{R}"), "p2")
    ench = _put(eng, Card(id="Opp Aura", name="Opp Aura", type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1), "p2")
    artifact = _put(eng, Card(id="Opp Rock", name="Opp Rock", type_line="Artifact", mana_cost_string="{1}", converted_mana_cost=1), "p2")
    _kill(eng, dying)
    # The creature is the only opposing permanent sharing a type with the dead creature, so it is the only candidate.
    assert victim not in eng.state.battlefield
    assert ench in eng.state.battlefield and artifact in eng.state.battlefield


def test_martyrs_bond_a_real_choice_among_several_sharing_permanents():
    eng = _engine()
    _put(eng, _real(BOND))
    dying = _put(eng, _creature("Dying Bear", "{G}"))
    first = _put(eng, _creature("Opposing Bear A", "{R}"), "p2")
    second = _put(eng, _creature("Opposing Bear B", "{R}"), "p2")
    land = _put(eng, Card(id="Opp Land", name="Opp Land", type_line="Land", is_land=True), "p2")
    _kill(eng, dying)
    choice = eng.state.pending_choice
    assert choice is not None, "no silent auto-pick between two eligible creatures"
    assert choice["player_id"] == "p2"
    assert {o["instance_id"] for o in choice["options"]} == {first.instance_id, second.instance_id}  # never the land
    eng.rules.resolve_choice(str(second.instance_id))
    eng.resolve_until_stable()
    assert second not in eng.state.battlefield and first in eng.state.battlefield and land in eng.state.battlefield


def test_martyrs_bond_a_dying_artifact_creature_shares_either_type():
    eng = _engine()
    _put(eng, _real(BOND))
    dying = _put(eng, Card(id="Golem", name="Golem", type_line="Artifact Creature — Golem", is_creature=True,
                           power=1, toughness=1, mana_cost_string="{2}", converted_mana_cost=2))
    rock = _put(eng, Card(id="Opp Rock", name="Opp Rock", type_line="Artifact", mana_cost_string="{1}", converted_mana_cost=1), "p2")
    _kill(eng, dying)
    assert rock not in eng.state.battlefield  # shares "artifact" with the dead Golem


# -- Faces of the Past (hand-authored; last known information of a token that ceased to exist) -------------------------


def test_faces_of_the_past_taps_only_creatures_sharing_a_type_with_the_creature_that_died():
    eng = _engine()
    _put(eng, _real(FACES))
    dying = _put(eng, _creature("Elf One", "{G}", "Elf Warrior"))
    elf = _put(eng, _creature("Elf Two", "{G}", "Elf"), "p2")
    goblin = _put(eng, _creature("Goblin", "{R}", "Goblin"), "p2")
    _kill(eng, dying)
    assert eng.state.pending_choice["kind"] == "effect_option"  # the controller picks tap or untap as it resolves
    eng.rules.resolve_choice("0")
    eng.resolve_until_stable()
    assert elf.tapped and not goblin.tapped


def test_faces_of_the_past_untap_mode_untaps_only_the_matching_tapped_creatures():
    eng = _engine()
    _put(eng, _real(FACES))
    dying = _put(eng, _creature("Elf One", "{G}", "Elf Warrior"))
    elf = _put(eng, _creature("Elf Two", "{G}", "Elf"), "p2")
    goblin = _put(eng, _creature("Goblin", "{R}", "Goblin"), "p2")
    elf.tapped = goblin.tapped = True
    _kill(eng, dying)
    eng.rules.resolve_choice("1")
    eng.resolve_until_stable()
    assert not elf.tapped and goblin.tapped


def test_faces_of_the_past_reads_the_types_of_a_token_that_ceased_to_exist():
    eng = _engine()
    _put(eng, _real(FACES))
    token = _put(eng, _creature("Elf Token", "{G}", "Elf Shaman"))
    token.is_token = True
    elf = _put(eng, _creature("Elf Two", "{G}", "Elf"), "p2")
    goblin = _put(eng, _creature("Goblin", "{R}", "Goblin"), "p2")
    _kill(eng, token)
    # RULE 111.7: by the time the choice is open the token has ceased to exist; only its last-known snapshot remains.
    assert eng.state.pending_choice["kind"] == "effect_option"
    assert eng.state.find_object(token.instance_id) is None
    eng.rules.resolve_choice("0")
    eng.resolve_until_stable()
    assert elf.tapped and not goblin.tapped  # last known information (RULE 608.2h) still names its creature types


# -- the other group verbs (exile, bounce) carry the same reference; no real card is modeled by them yet -------------------


def _probe(oracle):
    card = Card(id="Probe", name="Probe", type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1, oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return card


def test_dual_natures_exile_line_exiles_tokens_named_like_the_creature_that_left():
    eng = _engine()
    _put(eng, _probe("Whenever a nontoken creature leaves the battlefield, exile all tokens with the same name as that creature."))
    leaving = _put(eng, _creature("Wolf", "{G}"))
    same_token = _put(eng, _creature("Wolf", "{G}"), "p2")
    same_token.is_token = True
    other_token = _put(eng, _creature("Bear", "{G}"), "p2")
    other_token.is_token = True
    same_name_card = _put(eng, _creature("Wolf", "{G}"), "p2")  # a nontoken: "all tokens" leaves it alone
    _kill(eng, leaving)
    assert same_token not in eng.state.battlefield
    assert other_token in eng.state.battlefield and same_name_card in eng.state.battlefield
    assert same_token.zone == Zone.EXILE


def test_bounce_group_compares_with_the_entering_creature():
    eng = _engine()
    _put(eng, _probe("Whenever a creature enters, return all other creatures that share a color with it to their owners' hands."))
    red = _put(eng, _creature("Red Bear", "{R}"), "p2")
    blue = _put(eng, _creature("Blue Bear", "{U}"), "p2")
    _enter(eng, _creature("Entering Red Bear", "{R}"))
    assert red.zone == Zone.HAND and blue in eng.state.battlefield


def test_tap_group_compares_with_the_creature_that_died_not_the_source():
    eng = _engine()
    # The source is itself a Cleric: a Cleric bystander must not be tapped when an Elf dies.
    source = _put(eng, Card(id="Probe", name="Probe", type_line="Creature — Cleric", is_creature=True, power=1, toughness=3,
                            mana_cost_string="{1}", converted_mana_cost=1,
                            oracle_text="Whenever a creature dies, tap all untapped creatures that share a creature type with it."))
    assert parse_oracle(source.card).modeled
    dying = _put(eng, _creature("Elf One", "{G}", "Elf"))
    elf = _put(eng, _creature("Elf Two", "{G}", "Elf"), "p2")
    cleric = _put(eng, _creature("Cleric Two", "{W}", "Cleric"), "p2")
    _kill(eng, dying)
    assert elf.tapped and not cleric.tapped and not source.tapped


def test_a_creature_that_died_is_compared_by_the_colors_it_had_on_the_battlefield():
    eng = _engine()
    _put(eng, _probe("Creatures you control are red."))
    _put(eng, Card(id="Reaper", name="Reaper", type_line="Enchantment", mana_cost_string="{1}", converted_mana_cost=1,
                   oracle_text="Whenever a creature dies, destroy all creatures that share a color with it."))
    dying = _put(eng, _creature("Blue Bear", "{U}"))  # printed blue, red while the first enchantment's effect applies
    eng.recompute_continuous_effects()
    assert dying.colors == {"R"}
    printed_blue = _put(eng, _creature("Opposing Blue Bear", "{U}"), "p2")
    printed_red = _put(eng, _creature("Opposing Red Bear", "{R}"), "p2")
    _kill(eng, dying)
    # RULE 608.2h: last known information says red; the card in the graveyard is printed blue and must not be used.
    assert printed_red not in eng.state.battlefield and printed_blue in eng.state.battlefield


def _dying_elf_world():
    eng = _engine()
    _put(eng, _real(FACES))
    dying = _put(eng, _creature("Elf One", "{G}", "Elf Warrior"))
    elf = _put(eng, _creature("Elf Two", "{G}", "Elf"), "p2")
    goblin = _put(eng, _creature("Goblin", "{R}", "Goblin"), "p2")
    return eng, dying, elf, goblin


def test_faces_of_the_past_choice_opens_at_resolution_not_when_the_trigger_is_put_on_the_stack():
    eng, dying, elf, goblin = _dying_elf_world()
    eng.rules.destroy(dying)
    eng.rules.put_triggers_on_stack()
    assert eng.state.stack and eng.state.pending_choice is None  # RULE 608.2d: nothing is asked yet (not a RULE 700.2 mode)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "effect_option" and choice["player_id"] == "p1"
    assert len(choice["options"]) == 2  # no auto-pick


def test_faces_of_the_past_judges_the_group_by_the_board_at_resolution():
    eng, dying, elf, goblin = _dying_elf_world()
    eng.rules.destroy(dying)
    eng.rules.put_triggers_on_stack()
    elf.tapped = True  # becomes tapped after the trigger went on the stack, before it resolves
    eng.resolve_until_stable()
    eng.rules.resolve_choice("0")  # "tap all untapped ...": the already tapped Elf is no longer a member, goblin never was
    eng.resolve_until_stable()
    assert elf.tapped and not goblin.tapped
    eng2, dying2, elf2, goblin2 = _dying_elf_world()
    eng2.rules.destroy(dying2)
    eng2.rules.put_triggers_on_stack()
    elf2.tapped = True
    eng2.resolve_until_stable()
    eng2.rules.resolve_choice("1")  # "untap all tapped ...": the Elf tapped in the meantime is untapped
    eng2.resolve_until_stable()
    assert not elf2.tapped


def test_effect_option_choice_survives_clone_and_undo_and_rejects_an_unlisted_answer():
    import copy

    eng, dying, elf, goblin = _dying_elf_world()
    _kill(eng, dying)
    choice = eng.state.pending_choice
    assert choice["kind"] == "effect_option"
    assert copy.deepcopy(choice) == choice  # plain data: the whole choice (specs, event scalars) round-trips a clone/undo
    clone = eng.state.clone() if hasattr(eng.state, "clone") else None
    if clone is not None:
        assert clone.pending_choice["effect_lists"] == choice["effect_lists"]
        assert clone.pending_choice["event_data"] == choice["event_data"]
    with pytest.raises(ValueError):
        eng.rules.resolve_choice("7")
    assert eng.state.pending_choice is not None  # still asking after a bad answer
