"""PAR-256: scoped activated-ability cost modifiers ("<keyword> abilities [of ...] cost {N} less/more", "<keyword> costs
[you pay] cost {N} less/more", "activated abilities of <group> cost {N} less/more to activate"), through the real engine
and real cached cards. RULE 601.2f (increases, then reductions), 602.2b (an activation's cost is determined like a
spell's), 118.7 (a reduction never goes below zero generic and leaves colored requirements alone)."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import card, filler, game, main_phase

#: The fifteen solo-blocked cards this ticket claims.
CLAIMED = (
    "Fluctuator", "Catalyst Stone", "Heartstone", "Agatha of the Vile Cauldron", "Dragonkin Berserker",
    "Eidolon of Obstruction", "Boom Scholar", "Hulk, Gamma Goliath", "Embalmer's Tools", "Mutagen Man, Living Ooze",
    "Silver-Fur Master", "Memory Crystal", "Warbringer", "Inquisitive Glimmer", "Bladegraft Aspirant",
)
#: Cards whose clause needs an additional non-mana cost (sacrifice / life): a separate primitive, left unclaimed.
UNCLAIMED = ("Brutal Suppression", "Thran Portal")

#: Akroma's Vengeance's Cycling {3}; Fluctuator takes {2} off it.
CYCLING_GENERIC = 3
CYCLING_REDUCTION = 2
#: Think Twice's flashback cost, {2}{U}, and what Catalyst Stone does to it.
FLASHBACK_GENERIC = 2
STONE_AMOUNT = 2
#: Agatha's printed power, and so her X.
AGATHA_POWER = 1
#: +1/+1 counters that take her to power 4 for the first assertions.
AGATHA_COUNTERS = 3
#: Dragonkin Berserker's Boast cost {4}{R}: generic part.
BOAST_GENERIC = 4
#: Warbringer takes {1} off a dash cost's generic part, as much as the cost has ({1}{R}).
DASH_REDUCTION = 1
#: Suppression Field's tax on activated abilities.
SUPPRESSION_TAX = 2


def _db():
    return CardDatabase(DB_PATH)


def _synthetic_creature(eng, name, oracle, player="p1", **kw):
    return filler(eng, name, type_line="Creature", power=1, toughness=1, oracle_text=oracle, player=player, **kw)


def _cost_of(eng, obj, index=0):
    """The mana an activation of ``obj``'s ability ``index`` asks for right now."""
    ability = obj.activated_abilities[index]
    return eng._reduced_activation_mana(
        obj, ability.cost.mana, ability.cost, activating_player_id=obj.controller_id,
    )


def _generic(cost):
    return cost.converted_mana_cost - sum(1 for s in cost.symbols if getattr(s, "type", None) is not None and False)


# --- parse ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", CLAIMED)
def test_the_claimed_cards_are_modeled(name):
    result = parse_oracle(_db().get_card(name))
    assert result.modeled, (name, result.unclaimed)


@pytest.mark.parametrize("name", UNCLAIMED)
def test_the_additional_cost_shapes_stay_unclaimed(name):
    # Never claim a clause the engine does not execute: the extra sacrifice / life is not modeled.
    assert not parse_oracle(_db().get_card(name)).modeled


def test_the_emitted_specs_carry_kind_group_and_amount():
    specs = {
        spec.params.get("keyword") or spec.params.get("ability_kind") or "activated": spec.params
        for name in ("Fluctuator", "Catalyst Stone", "Agatha of the Vile Cauldron", "Eidolon of Obstruction")
        for s in parse_oracle(_db().get_card(name)).specs if s.ability_kind == "static"
        for spec in s.effects if spec.type == "cost_reduction"
    }
    assert specs["cycling"]["activator"] == "you"
    assert specs["loyalty"]["increase"] is True
    assert specs["loyalty"]["source_group"] == {"controller": "opponents", "card_type": "planeswalker"}
    assert specs["activated"]["per"] == "source_power" and specs["activated"]["min_total"] == 1


# --- cycling (Fluctuator) -------------------------------------------------------------------------------------

def _hand_cycling_offered(eng, obj):
    return any(a["type"] == "activate_ability" and a.get("instance_id") == obj.instance_id
               for a in eng.legal_actions(eng.state.player_by_id("p1")))


def test_fluctuator_makes_cycling_affordable_and_charges_the_reduced_cost():
    eng = game()
    vengeance = card(eng, "Akroma's Vengeance", zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", CYCLING_GENERIC - CYCLING_REDUCTION)
    assert not _hand_cycling_offered(eng, vengeance)  # RULE 601.2f: no discount yet, {1} cannot pay {3}
    card(eng, "Fluctuator")
    assert _hand_cycling_offered(eng, vengeance)
    hand_before = len(p1.hand)
    eng.activate_ability(p1, vengeance, 0)
    eng.resolve_until_stable()
    assert p1.mana_pool.total() == 0
    assert vengeance in p1.graveyard
    assert len(p1.hand) == hand_before  # discarded the vengeance, drew a card


def test_an_opponents_fluctuator_does_not_discount_my_cycling():
    eng = game()
    vengeance = card(eng, "Akroma's Vengeance", zone=Zone.HAND)
    card(eng, "Fluctuator", player="p2")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", CYCLING_GENERIC - CYCLING_REDUCTION)
    assert not _hand_cycling_offered(eng, vengeance)  # "abilities you activate": only its controller's


# --- flashback (Catalyst Stone) -------------------------------------------------------------------------------

def test_catalyst_stone_cheapens_my_flashback_and_taxes_my_opponents():
    eng = game()
    think = card(eng, "Think Twice", zone=Zone.GRAVEYARD)
    p1 = eng.state.player_by_id("p1")
    base = eng.effective_cast_cost(p1, think)
    card(eng, "Catalyst Stone", player="p1")
    mine = eng.effective_cast_cost(p1, think)
    assert mine.converted_mana_cost == base.converted_mana_cost - STONE_AMOUNT
    assert "U" in mine.raw  # RULE 118.7: the colored pip is untouched

    eng2 = game()
    think2 = card(eng2, "Think Twice", zone=Zone.GRAVEYARD)
    card(eng2, "Catalyst Stone", player="p2")
    taxed = eng2.effective_cast_cost(eng2.state.player_by_id("p1"), think2)
    assert taxed.converted_mana_cost == base.converted_mana_cost + STONE_AMOUNT  # "your opponents pay ... more"


def test_flashback_is_castable_only_with_the_reduced_mana():
    eng = game()
    think = card(eng, "Think Twice", zone=Zone.GRAVEYARD)
    card(eng, "Catalyst Stone")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("U", 1)
    assert eng.can_cast(p1, think)  # {2}{U} less {2} = {U}
    eng.cast_spell(p1, think)
    eng.resolve_until_stable()
    assert p1.mana_pool.total() == 0 and think.zone == Zone.EXILE  # RULE 702.34a: flashback exiles it


def test_catalyst_stone_does_not_touch_a_card_cast_from_hand():
    eng = game()
    think = card(eng, "Think Twice", zone=Zone.HAND)
    card(eng, "Catalyst Stone")
    assert eng.effective_cast_cost(eng.state.player_by_id("p1"), think).converted_mana_cost == FLASHBACK_GENERIC


# --- buyback (Memory Crystal), unlock (Inquisitive Glimmer), dash (Warbringer), ninjutsu (Silver-Fur Master) ----

def test_memory_crystal_cheapens_buyback_for_every_player_but_only_its_generic_part():
    eng = game()
    capsize = card(eng, "Capsize", zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    plain = eng.effective_cast_cost(p1, capsize, buyback=True)
    card(eng, "Memory Crystal", player="p2")  # "buyback costs": no payer restriction
    cheaper = eng.effective_cast_cost(p1, capsize, buyback=True)
    assert cheaper.converted_mana_cost == plain.converted_mana_cost - STONE_AMOUNT
    assert eng.effective_cast_cost(p1, capsize).converted_mana_cost == plain.converted_mana_cost - 3  # no buyback: untouched


#: Grand Entryway // Elegant Rotunda: the left half unlocks for {1}{W}, the right for {2}{W}.
ROOM = "Grand Entryway // Elegant Rotunda"
LEFT_UNLOCK_GENERIC = 1
UNLOCK_REDUCTION = 1


def test_inquisitive_glimmer_reduces_the_unlock_cost_of_my_rooms_and_the_door_opens_for_less():
    eng = game()
    room = card(eng, ROOM)
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("W", 1)
    assert not eng.can_unlock_door(p1, room, "left")  # {1}{W} against a lone {W}
    card(eng, "Inquisitive Glimmer")
    assert eng.can_unlock_door(p1, room, "left")  # {1}{W} less {1}: the colored pip stays (RULE 118.7)
    offered = [a for a in eng.legal_actions(p1) if a["type"] == "unlock_door" and a["door"] == "left"]
    assert offered and offered[0]["cost_label"].replace(" ", "") in ("{W}",)
    eng.unlock_door(p1, room, "left")
    assert "left" in room.unlocked_doors and p1.mana_pool.total() == 0


def test_warbringer_reduces_my_dash_cost_but_not_a_normal_cast():
    eng = game()
    scout = card(eng, "Mardu Scout", zone=Zone.HAND)  # Dash {1}{R}
    p1 = eng.state.player_by_id("p1")
    cost = scout.alt_cast_cost
    assert cost is not None and scout.dash
    assert eng._dash_cost_adjusted(p1, scout, cost).mana.converted_mana_cost == cost.mana.converted_mana_cost
    card(eng, "Warbringer")
    adjusted = eng._dash_cost_adjusted(p1, scout, cost)
    assert adjusted.mana.converted_mana_cost == cost.mana.converted_mana_cost - DASH_REDUCTION
    assert eng.effective_cast_cost(p1, scout).converted_mana_cost == scout.mana_value  # the mana cost is untouched
    p1.mana_pool.add("R", 1)
    main_phase(eng)
    assert eng._can_pay_alt_cast_cost(p1, scout, cost)  # {R} pays the dashed Scout


def test_silver_fur_master_cheapens_ninjutsu():
    eng = game()
    ninja = card(eng, "Ninja of the Deep Hours", zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    printed = ninja.ninjutsu_cost.converted_mana_cost
    assert eng._keyword_cost_adjusted(ninja.ninjutsu_cost, "ninjutsu", p1, ninja).converted_mana_cost == printed
    card(eng, "Silver-Fur Master")
    adjusted = eng._keyword_cost_adjusted(ninja.ninjutsu_cost, "ninjutsu", p1, ninja)
    assert adjusted.converted_mana_cost == printed - 1
    assert "U" in adjusted.raw


# --- group scope: Heartstone, Agatha, Embalmer's Tools, Mutagen Man ----------------------------------------------

def test_heartstone_reduces_every_creature_but_keeps_a_one_mana_floor():
    eng = game()
    pricey = _synthetic_creature(eng, "Pricey", "{3}: Draw a card.")
    one = _synthetic_creature(eng, "OneMana", "{1}: Draw a card.")
    tap_only = _synthetic_creature(eng, "TapOnly", "{T}: Draw a card.")
    card(eng, "Heartstone", player="p2")  # "activated abilities of creatures": every controller's
    assert _cost_of(eng, pricey).converted_mana_cost == 2
    assert _cost_of(eng, one).converted_mana_cost == 1  # "can't reduce the mana in that cost to less than 1 mana"
    assert _cost_of(eng, tap_only).converted_mana_cost == 0  # ruling: it never adds a {1} to a cost with no mana


def test_heartstone_leaves_colored_mana_and_non_creatures_alone():
    eng = game()
    colored = _synthetic_creature(eng, "Colored", "{1}{R}: Draw a card.")
    rock = filler(eng, "Rock", type_line="Artifact", oracle_text="{3}: Draw a card.")
    card(eng, "Heartstone")
    assert _cost_of(eng, colored).raw.replace(" ", "") in ("{R}", "{R}{0}")
    assert _cost_of(eng, rock).converted_mana_cost == 3


def test_agatha_reduces_by_her_power_with_a_floor_of_one():
    eng = game()
    big = _synthetic_creature(eng, "Big", "{6}: Draw a card.")
    small = _synthetic_creature(eng, "Small", "{2}: Draw a card.")
    agatha = card(eng, "Agatha of the Vile Cauldron")
    agatha.plus_one_counters += AGATHA_COUNTERS
    eng.recompute_continuous_effects()
    assert agatha.power == AGATHA_POWER + AGATHA_COUNTERS
    assert _cost_of(eng, big).converted_mana_cost == 6 - agatha.power
    assert _cost_of(eng, small).converted_mana_cost == 1  # {2} - 4 would be 0; the floor holds it at one mana
    agatha.plus_one_counters += 1
    eng.recompute_continuous_effects()
    assert _cost_of(eng, big).converted_mana_cost == 1  # X is her *current* power, 6: {6} - 6 floored to one mana


def test_agatha_does_not_reach_a_creature_card_in_the_graveyard():
    eng = game()
    card(eng, "Agatha of the Vile Cauldron")
    skeleton = card(eng, "Reassembling Skeleton", zone=Zone.GRAVEYARD)
    # ruling 2023-09-01: only abilities of creatures on the battlefield
    assert _cost_of(eng, skeleton).converted_mana_cost == skeleton.activated_abilities[0].cost.mana.converted_mana_cost


def test_embalmers_tools_discounts_a_creature_card_in_my_graveyard():
    eng = game()
    skeleton = card(eng, "Reassembling Skeleton", zone=Zone.GRAVEYARD)
    printed = skeleton.activated_abilities[0].cost.mana.converted_mana_cost
    other = card(eng, "Reassembling Skeleton", zone=Zone.GRAVEYARD, player="p2")
    card(eng, "Embalmer's Tools")
    assert _cost_of(eng, skeleton).converted_mana_cost == printed - 1
    assert _cost_of(eng, other).converted_mana_cost == printed  # "your graveyard"


def test_mutagen_man_discounts_only_my_artifact_tokens():
    eng = game()
    token = filler(eng, "Treasure Like", type_line="Artifact", oracle_text="{2}: Draw a card.")
    token.is_token = True
    real = filler(eng, "Real Rock", type_line="Artifact", oracle_text="{2}: Draw a card.")
    card(eng, "Mutagen Man, Living Ooze")
    assert _cost_of(eng, token).converted_mana_cost == 1
    assert _cost_of(eng, real).converted_mana_cost == 2


# --- ability kind: boast, loyalty -------------------------------------------------------------------------------

def test_dragonkin_berserker_discounts_boast_per_dragon():
    eng = game()
    berserker = card(eng, "Dragonkin Berserker")
    boast = next(a for a in berserker.activated_abilities if a.cost.ability_keyword == "boast")
    printed = boast.cost.mana.converted_mana_cost
    assert printed == BOAST_GENERIC + 1
    assert _cost_of_ability(eng, berserker, boast).converted_mana_cost == printed  # no Dragon: nothing
    filler(eng, "Dragon One", type_line="Creature — Dragon", power=2, toughness=2)
    assert _cost_of_ability(eng, berserker, boast).converted_mana_cost == printed - 1
    filler(eng, "Dragon Two", type_line="Creature — Dragon", power=2, toughness=2)
    assert _cost_of_ability(eng, berserker, boast).converted_mana_cost == printed - 2
    # a non-boast ability of the same permanent is never touched
    other = _synthetic_creature(eng, "Other", "{3}: Draw a card.")
    assert _cost_of(eng, other).converted_mana_cost == 3


def _cost_of_ability(eng, obj, ability):
    return eng._reduced_activation_mana(
        obj, ability.cost.mana, ability.cost, activating_player_id=obj.controller_id,
    )


def test_boom_scholar_discounts_exhaust_of_my_other_permanents_only():
    eng = game()
    scholar = card(eng, "Boom Scholar")
    own = next(a for a in scholar.activated_abilities if a.cost.ability_keyword == "exhaust")
    printed = own.cost.mana.converted_mana_cost
    assert _cost_of_ability(eng, scholar, own).converted_mana_cost == printed  # "other permanents"
    second = card(eng, "Boom Scholar")
    theirs = next(a for a in second.activated_abilities if a.cost.ability_keyword == "exhaust")
    assert _cost_of_ability(eng, second, theirs).converted_mana_cost == printed - STONE_AMOUNT


def test_eidolon_of_obstruction_taxes_opposing_loyalty_abilities_by_one_mana():
    eng = game()
    chandra = card(eng, "Jace Beleren", player="p2")
    mine = card(eng, "Jace Beleren", player="p1")
    loyalty = chandra.activated_abilities[0]
    assert loyalty.cost.is_loyalty
    assert _cost_of_ability(eng, chandra, loyalty).converted_mana_cost == 0
    card(eng, "Eidolon of Obstruction", player="p1")
    assert _cost_of_ability(eng, chandra, loyalty).converted_mana_cost == 1  # RULE 606: a mana component is added
    assert _cost_of_ability(eng, mine, mine.activated_abilities[0]).converted_mana_cost == 0  # my own is exempt


def test_eidolon_makes_a_loyalty_activation_need_the_mana():
    eng = game()
    chandra = card(eng, "Jace Beleren", player="p1")
    card(eng, "Eidolon of Obstruction", player="p2")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    ability = chandra.activated_abilities[0]
    assert not eng.can_activate(p1, chandra, ability)
    p1.mana_pool.add("C", 1)
    assert eng.can_activate(p1, chandra, ability)


# --- Bladegraft Aspirant: equipment that targets ~ ------------------------------------------------------------------

def test_bladegraft_aspirant_discounts_equip_that_targets_it_only():
    eng = game()
    aspirant = card(eng, "Bladegraft Aspirant")
    other = filler(eng, "Other Body", type_line="Creature", power=1, toughness=1)
    sword = card(eng, "Bonesplitter")
    equip = sword.activated_abilities[0]
    printed = equip.cost.mana.converted_mana_cost
    on_aspirant = eng._reduced_activation_mana(
        sword, equip.cost.mana, equip.cost, targets=[aspirant], activating_player_id="p1")
    on_other = eng._reduced_activation_mana(
        sword, equip.cost.mana, equip.cost, targets=[other], activating_player_id="p1")
    assert on_aspirant.converted_mana_cost == max(0, printed - 1)
    assert on_other.converted_mana_cost == printed


# --- RULE 601.2f order: increases, then reductions ----------------------------------------------------------------------

def test_increases_apply_before_reductions_and_the_floor_bounds_only_the_reduction():
    eng = game()
    one = _synthetic_creature(eng, "OneMana", "{1}: Draw a card.")
    card(eng, "Suppression Field", player="p2")  # activated abilities cost {2} more (non-mana abilities)
    card(eng, "Heartstone", player="p1")  # ... {1} less, never below one mana
    # RULE 601.2f: {1} + {2} = {3}, then {1} less = {2}. Reducing first ({1} -> floor {1}) would end at {3}.
    assert _cost_of(eng, one).converted_mana_cost == 1 + SUPPRESSION_TAX - 1


# --- a GameSession flow, and undo ---------------------------------------------------------------------------------

def test_cycling_with_fluctuator_through_a_session_then_undo():
    eng = game()
    vengeance = card(eng, "Akroma's Vengeance", zone=Zone.HAND)
    card(eng, "Fluctuator")
    p1 = eng.state.player_by_id("p1")
    main_phase(eng)
    p1.mana_pool.add("C", CYCLING_GENERIC - CYCLING_REDUCTION)
    session = GameSession(eng, require_setup=False)
    offered = [a for a in session.legal_actions("p1")
               if a["type"] == "activate_ability" and a.get("instance_id") == vengeance.instance_id]
    assert offered, "the discounted cycling is offered to the player (and so to bots)"
    session.apply_action(dict(offered[0]), actor_id="p1")
    session.engine.resolve_until_stable()
    assert vengeance.instance_id in [o.instance_id for o in session.engine.state.player_by_id("p1").graveyard]
    session.rewind(1)
    restored = session.engine.state.player_by_id("p1")
    assert vengeance.instance_id in [o.instance_id for o in restored.hand]
    assert restored.mana_pool.total() == CYCLING_GENERIC - CYCLING_REDUCTION
    # and the modifier still applies after the rewind
    again = [a for a in session.legal_actions("p1") if a["type"] == "activate_ability"
             and a.get("instance_id") == vengeance.instance_id]
    assert again
