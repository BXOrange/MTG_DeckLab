"""PAR-109 (second pass) -- the residue of the static/activated-ability batch.

* Lim-Dul's Cohort: under a block-relation head "that creature can't be regenerated this turn" is the creature on the
  other side of the block (`cant_be_regenerated` ``trigger_related``).
* Bone Shaman: "creatures dealt damage by ~ this turn can't be regenerated this turn" (`deny_regen_to_damaged`).
* Desolation of Smaug and kin: the "Spend this mana only to cast ..." sentence tags the preceding `add_mana` specs
  with a RULE 605.3a restriction dict.
* Brad Boimler: a turn-scoped `double_counters` ``plus`` replacement (`plus_counters_this_turn`).
* Atalya: a hand-authored two-mode {X},{T} body with the white-only X rider.
* Luxior: "+1/+1 for each counter on it" counts the equipped permanent's counters.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.test_par119_cast_trigger_grammar import _engine, _named
from tests.test_par120_count_phrase import _put

COHORT = "Whenever ~ blocks or becomes blocked by a creature, that creature can't be regenerated this turn."


def _creature(state, name, owner="p1", power=2, toughness=2, oracle=""):
    card = Card(id=name, name=name, type_line="Creature — Bear", oracle_text=oracle, is_creature=True,
                power=power, toughness=toughness)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _combat(state, engine, attackers, blockers):
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, attackers)
    state.current_step = "declare_blockers"
    engine.declare_blockers(
        state.player_by_id("p2"), [{"blocker": b, "attacker": a} for b, a in blockers],
    )
    engine.resolve_until_stable()


# --- Lim-Dul's Cohort ---------------------------------------------------------------------------------------------


def test_cohort_parses_and_real_card_is_modeled():
    assert parse_oracle(_named("Lim-Dûl's Cohort")).modeled is True


def test_that_creature_regen_fails_closed_under_a_head_with_no_other_side():
    # "that creature" under a plain ETB head has no referent: it must stay unclaimed rather than regenerate-deny
    # something arbitrary.
    assert not parse_oracle(_named_text("When ~ enters, that creature can't be regenerated this turn.")).modeled


def _named_text(text):
    return Card(id="T", name="T", type_line="Creature — Bear", oracle_text=text, is_creature=True, power=1, toughness=1)


@pytest.mark.parametrize("cohort_blocks", [True, False])
def test_cohort_denies_regeneration_to_the_creature_on_the_other_side(cohort_blocks):
    engine, state = _engine()
    if cohort_blocks:
        cohort = _put(state, COHORT, name="Cohort", owner="p2")
        other = _creature(state, "Raider", owner="p1")
        attackers, blockers = [other], [(cohort, other)]
    else:
        cohort = _put(state, COHORT, name="Cohort", owner="p1")
        other = _creature(state, "Wall", owner="p2")
        attackers, blockers = [cohort], [(other, cohort)]
    cohort.summoning_sick = False
    _combat(state, engine, attackers, blockers)
    assert other.temp_cant_be_regenerated is True
    assert cohort.temp_cant_be_regenerated is False


def test_cohort_denied_creature_cannot_regenerate_out_of_lethal_damage():
    engine, state = _engine()
    cohort = _put(state, COHORT, name="Cohort", owner="p2")
    cohort.summoning_sick = False
    other = _creature(state, "Raider", owner="p1", power=2, toughness=2)
    engine.rules.regenerate(other)  # a regeneration shield that would have saved it
    _combat(state, engine, [other], [(cohort, other)])
    other.damage_marked = 2
    engine.rules.check_state_based_actions()
    assert other.zone == Zone.GRAVEYARD


def test_without_the_trigger_the_same_shield_saves_it():
    engine, state = _engine()
    other = _creature(state, "Raider", owner="p1", power=2, toughness=2)
    engine.rules.regenerate(other)
    other.damage_marked = 2
    engine.rules.check_state_based_actions()
    assert other.zone == Zone.BATTLEFIELD


# --- Bone Shaman ------------------------------------------------------------------------------------------------


def _shaman(state):
    shaman = GameObject(_named("Bone Shaman"), owner_id="p1", zone=Zone.BATTLEFIELD)
    shaman.controller_id = "p1"
    shaman.summoning_sick = False
    bind_from_catalogue(shaman)
    state.add_to_battlefield(shaman)
    return shaman


def _activate(engine, state, shaman):
    state.player_by_id("p1").mana_pool.add("B", 1)
    engine.activate_ability(state.player_by_id("p1"), shaman, 0)
    engine.resolve_until_stable()


@pytest.mark.parametrize("damage_first", [True, False])
def test_bone_shaman_denies_regeneration_to_creatures_it_damaged_this_turn(damage_first):
    engine, state = _engine()
    shaman = _shaman(state)
    victim = _creature(state, "Victim", owner="p2", power=1, toughness=2)
    bystander = _creature(state, "Bystander", owner="p2", power=1, toughness=2)
    for c in (victim, bystander):
        engine.rules.regenerate(c)
    if damage_first:
        # Non-lethal damage first (lethal damage would be checked by state-based actions before anyone could act).
        engine.rules.deal_damage(victim, 1, source=shaman)
        _activate(engine, state, shaman)
        victim.damage_marked = 2
    else:
        _activate(engine, state, shaman)
        engine.rules.deal_damage(victim, 2, source=shaman)
    bystander.damage_marked = 2
    engine.rules.check_state_based_actions()
    assert victim.zone == Zone.GRAVEYARD       # the shield did not apply
    assert bystander.zone == Zone.BATTLEFIELD  # not dealt damage by the Shaman: regenerates as usual


def test_bone_shaman_without_activation_leaves_regeneration_alone():
    engine, state = _engine()
    shaman = _shaman(state)
    victim = _creature(state, "Victim", owner="p2", power=1, toughness=2)
    engine.rules.regenerate(victim)
    engine.rules.deal_damage(victim, 2, source=shaman)
    engine.rules.check_state_based_actions()
    assert victim.zone == Zone.BATTLEFIELD


def test_bone_shaman_flag_ends_at_cleanup():
    engine, state = _engine()
    shaman = _shaman(state)
    _activate(engine, state, shaman)
    assert shaman.temp_deny_regen_to_damaged is True
    engine._step_cleanup()
    assert shaman.temp_deny_regen_to_damaged is False


# --- "Spend this mana only to cast ..." (Desolation of Smaug, Geosurge, Sarkhan Fireblood, Abstract Paintmage) --------


@pytest.mark.parametrize(("text", "restriction"), [
    ("add {r}{r}{r}. spend this mana only to cast instant or sorcery spells.", {"kind": "instant_or_sorcery_spell"}),
    ("add {r}{r}. spend this mana only to cast dragon spells.",
     {"kind": "type_spell", "types": ["dragon"], "allow_ability": False}),
    ("add {r}{r}. spend this mana only to cast artifact or creature spells.",
     {"kind": "type_spell", "types": ["artifact", "creature"], "allow_ability": False}),
    ("add {g}{g}. spend this mana only to cast creature spells.", {"kind": "creature_spell", "allow_ability": False}),
    ("add {g}{g}. spend this mana only to cast spells.", {"kind": "spell"}),
])
def test_spend_only_sentence_tags_the_added_mana(text, restriction):
    specs = parse_effect_body(text)
    assert specs is not None and specs
    assert all(s.type == "add_mana" and s.params["restriction"] == restriction for s in specs)


@pytest.mark.parametrize("text", [
    "draw a card. spend this mana only to cast dragon spells.",         # no mana was added
    "add {r}{r}. spend this mana only to cast spells with flying.",     # outside the closed vocabulary
    "add {r}{r}. spend this mana only to cast three or more dragon spells.",
])
def test_spend_only_sentence_fails_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize("name", [
    "Desolation of Smaug", "Geosurge", "Sarkhan, Fireblood", "Jaya Ballard", "Abstract Paintmage",
])
def test_real_spend_only_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def _spell(name, type_line, subtypes_in_line, **kw):
    card = Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line, power=2, toughness=2,
                converted_mana_cost=2, **kw)
    return GameObject(card, owner_id="p1", zone=Zone.HAND)


def test_dragon_only_mana_pays_for_a_dragon_but_not_a_bear():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.mana_abilities import restriction_predicate_for_cast
    from mtg_analyzer.models.mana.mana_cost import ManaCost

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    source = _creature(state, "Smaug", owner="p1")
    specs = parse_effect_body("add {r}{r}. spend this mana only to cast dragon spells.")
    for effect in build_effects(specs, source):
        effect.apply(engine.rules.context)
    cost = ManaCost.parse("{R}{R}")
    dragon = _spell("Whelp", "Creature — Dragon", ())
    bear = _spell("Bear", "Creature — Bear", ())
    assert p1.mana_pool.can_pay(cost, allows_restriction=restriction_predicate_for_cast(dragon))
    assert not p1.mana_pool.can_pay(cost, allows_restriction=restriction_predicate_for_cast(bear))
    assert not p1.mana_pool.can_pay(cost)  # restricted mana never counts toward an unrestricted payment


def test_any_combination_mana_keeps_its_restriction_through_the_colour_pick():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.mana_abilities import restriction_predicate_for_cast
    from mtg_analyzer.models.mana.mana_cost import ManaCost

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    source = _creature(state, "Smaug", owner="p1")
    specs = parse_effect_body("add 2 mana in any combination of colors. spend this mana only to cast dragon spells.")
    for effect in build_effects(specs, source):
        effect.apply(engine.rules.context)
        engine.rules.resolve_choice("R")
    dragon = _spell("Whelp", "Creature — Dragon", ())
    bear = _spell("Bear", "Creature — Bear", ())
    cost = ManaCost.parse("{R}{R}")
    assert p1.mana_pool.can_pay(cost, allows_restriction=restriction_predicate_for_cast(dragon))
    assert not p1.mana_pool.can_pay(cost, allows_restriction=restriction_predicate_for_cast(bear))


# --- Brad Boimler, Eager Ensign ---------------------------------------------------------------------------------


def _brad(state):
    brad = GameObject(_named("Brad Boimler, Eager Ensign"), owner_id="p1", zone=Zone.BATTLEFIELD)
    brad.controller_id = "p1"
    brad.summoning_sick = False
    bind_from_catalogue(brad)
    state.add_to_battlefield(brad)
    return brad


def test_brad_boimler_plus_one_counter_replacement_runs_until_end_of_turn():
    engine, state = _engine()
    brad = _brad(state)
    mine = _creature(state, "Mine", owner="p1")
    theirs = _creature(state, "Theirs", owner="p2")
    engine.rules.add_counters(mine, 2)
    assert mine.plus_one_counters == 2            # before Brad taps: no bonus
    engine.rules.set_tapped(brad, True)
    engine.resolve_until_stable()
    engine.rules.add_counters(mine, 2)
    assert mine.plus_one_counters == 2 + 3        # "that many plus 1"
    engine.rules.add_counters(mine, 1, "charge")
    assert mine.counters.get("charge") == 2       # every kind is raised by one
    engine.rules.add_counters(theirs, 2)
    assert theirs.plus_one_counters == 2          # only permanents *you* control
    engine._step_cleanup()
    state.internal_turn.number += 1               # the next turn: the effect has lapsed
    engine.rules.add_counters(mine, 2)
    assert mine.plus_one_counters == 2 + 3 + 2


# --- Atalya, Samite Master ----------------------------------------------------------------------------------------


def _atalya(state):
    atalya = GameObject(_named("Atalya, Samite Master"), owner_id="p1", zone=Zone.BATTLEFIELD)
    atalya.controller_id = "p1"
    atalya.summoning_sick = False
    bind_from_catalogue(atalya)
    state.add_to_battlefield(atalya)
    return atalya


def test_atalya_has_one_activated_ability_per_mode_with_the_white_only_x():
    engine, state = _engine()
    atalya = _atalya(state)
    assert len(atalya.activated_abilities) == 2
    assert all(a.cost.x_spend_color == "W" and a.cost.taps_self for a in atalya.activated_abilities)


def test_atalya_gain_life_mode_spends_only_white_mana_on_x():
    engine, state = _engine()
    atalya = _atalya(state)
    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    p1.mana_pool.add_many({"R": 2, "W": 2})
    gain = atalya.activated_abilities[1]
    assert engine.can_activate(p1, atalya, gain, x=2)
    assert not engine.can_activate(p1, atalya, gain, x=3)        # red cannot pay X
    engine.activate_ability(p1, atalya, 1, x=2)
    engine.resolve_until_stable()
    assert p1.life == 22 and p1.mana_pool.total() == 2           # the red mana was never touched


def test_atalya_prevent_mode_shields_a_creature_for_x():
    engine, state = _engine()
    atalya = _atalya(state)
    p1 = state.player_by_id("p1")
    bear = _creature(state, "Bear", owner="p2", power=2, toughness=5)
    state.current_step = "main1"
    p1.mana_pool.add_many({"W": 2})
    engine.activate_ability(p1, atalya, 0, targets=[bear], x=2)
    engine.resolve_until_stable()
    engine.rules.deal_damage(bear, 3, source=None)
    assert bear.damage_marked == 1                               # 2 of the 3 damage were prevented


# --- Luxior: "+1/+1 for each counter on it" ----------------------------------------------------------------------


def test_luxior_bonus_clause_parses_with_the_affected_permanents_counters():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

    [spec] = static_effect_specs("equipped creature gets +1/+1 for each counter on it.")
    assert spec.params["power_count"] == "total_counters_on_affected"
    assert spec.params["toughness_count"] == "total_counters_on_affected"
    assert spec.params["affects"] == "attached_permanent"
    # the Aura/Equipment's own counters are named "on ~", never "on it"
    [own] = static_effect_specs("equipped creature gets +1/+1 for each charge counter on ~.")
    assert own.params["power_count"] == "source_charge_counters"


def test_the_bonus_counts_the_equipped_creatures_counters_of_every_kind():
    engine, state = _engine()
    gear = _put(state, "Equipped creature gets +1/+1 for each counter on it.", name="Gear",
                types="Artifact — Equipment")
    bear = _creature(state, "Bear", owner="p1")
    other = _creature(state, "Other", owner="p1")
    gear.attached_to = bear.instance_id
    engine.rules.add_counters(bear, 2)
    engine.rules.add_counters(bear, 1, "charge")
    engine.rules.add_counters(gear, 5, "charge")  # the Equipment's own counters do not count
    engine.rules.add_counters(other, 4)
    engine.recompute_continuous_effects()
    # 2/2 + two +1/+1 counters, then +1/+1 for each of its 3 counters (the Equipment's own charge counters excluded)
    assert (bear.power, bear.toughness) == (7, 7)
    assert (other.power, other.toughness) == (6, 6)  # not equipped: only its own +1/+1 counters


# --- Luxior, Giada's Gift / Luxior and Shadowspear --------------------------------------------------------------


def _mana(ability):
    return ability.cost.mana.render()


def _card_obj(state, name, controller="p1"):
    obj = GameObject(_named(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _planeswalker(state, loyalty=4, controller="p1", oracle="+1: You gain 1 life."):
    card = Card(id="Jace", name="Test Walker", type_line="Legendary Planeswalker — Test", oracle_text=oracle,
                loyalty=loyalty)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.counters["loyalty"] = loyalty
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("name", ["Luxior, Giada's Gift", "Luxior and Shadowspear"])
def test_luxior_cards_are_hand_authored_with_both_equip_abilities(name):
    engine, state = _engine()
    luxior = _card_obj(state, name)
    equips = [a for a in luxior.activated_abilities if getattr(a, "attach_kind", None) == "equip"]
    assert len(equips) == 2
    assert {_mana(a) for a in equips} == ({"{1}", "{3}"} if name.startswith("Luxior, ") else {"{3}"})


def test_equip_planeswalker_makes_it_a_creature_with_a_counter_sized_body():
    engine, state = _engine()
    luxior = _card_obj(state, "Luxior, Giada's Gift")
    walker = _planeswalker(state, loyalty=4)
    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    p1.mana_pool.add("C", 1)
    abilities = luxior.activated_abilities
    planeswalker_equip = next(a for a in abilities if _mana(a) == "{1}")
    engine.activate_ability(p1, luxior, abilities.index(planeswalker_equip), targets=[walker])
    engine.resolve_until_stable()
    assert luxior.attached_to == walker.instance_id
    engine.recompute_continuous_effects()
    assert walker.is_creature and not walker.is_planeswalker
    assert (walker.power, walker.toughness) == (4, 4)          # 0/0 + one +1/+1 for each of its 4 loyalty counters
    engine.rules.check_state_based_actions()                   # RULE 704.5n re-check: still a legal host
    assert luxior.attached_to == walker.instance_id and walker.zone == Zone.BATTLEFIELD


def test_the_equipped_planeswalker_keeps_its_loyalty_abilities_and_damage_marks_not_loyalty():
    engine, state = _engine()
    luxior = _card_obj(state, "Luxior, Giada's Gift")
    walker = _planeswalker(state, loyalty=4)
    luxior.attached_to = walker.instance_id
    engine.recompute_continuous_effects()
    state.current_step = "main1"
    assert engine._can_activate_loyalty(state.player_by_id("p1"), walker) is True  # RULE 606: printed loyalty abilities
    engine.rules.deal_damage(walker, 2, source=None)
    assert walker.loyalty == 4                                   # it is not a planeswalker: damage is marked
    assert walker.damage_marked == 2


def test_the_equipped_planeswalker_dies_to_lethal_damage_like_a_creature():
    engine, state = _engine()
    luxior = _card_obj(state, "Luxior, Giada's Gift")
    walker = _planeswalker(state, loyalty=2)
    luxior.attached_to = walker.instance_id
    engine.recompute_continuous_effects()
    walker.damage_marked = 2
    engine.rules.check_state_based_actions()
    assert walker.zone == Zone.GRAVEYARD


def test_equip_planeswalker_cannot_target_a_creature_or_an_opponents_planeswalker():
    engine, state = _engine()
    luxior = _card_obj(state, "Luxior, Giada's Gift")
    bear = _creature(state, "Bear", owner="p1")
    theirs = _planeswalker(state, controller="p2")
    mine = _planeswalker(state, controller="p1")
    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    index = next(i for i, a in enumerate(luxior.activated_abilities) if _mana(a) == "{1}")
    for illegal in (theirs, bear):
        p1.mana_pool.add("C", 1)
        with pytest.raises(ValueError):
            engine.activate_ability(p1, luxior, index, targets=[illegal])
        assert luxior.attached_to is None
    engine.activate_ability(p1, luxior, index, targets=[mine])
    engine.resolve_until_stable()
    assert luxior.attached_to == mine.instance_id


def test_luxior_equipped_creature_gets_the_counter_bonus_and_stays_a_creature():
    engine, state = _engine()
    luxior = _card_obj(state, "Luxior, Giada's Gift")
    bear = _creature(state, "Bear", owner="p1")
    engine.rules.add_counters(bear, 2)
    luxior.attached_to = bear.instance_id
    engine.recompute_continuous_effects()
    assert bear.is_creature and (bear.power, bear.toughness) == (2 + 2 + 2, 2 + 2 + 2)


def test_shadowspear_grants_trample_and_lifelink_and_a_planeswalker_equip():
    engine, state = _engine()
    spear = _card_obj(state, "Luxior and Shadowspear")
    walker = _planeswalker(state, loyalty=3)
    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    p1.mana_pool.add_many({"C": 3})
    pw_equip = [a for a in spear.activated_abilities if getattr(a, "attach_kind", None) == "equip"][1]
    engine.activate_ability(p1, spear, spear.activated_abilities.index(pw_equip), targets=[walker])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert spear.attached_to == walker.instance_id
    assert (walker.power, walker.toughness) == (3, 3)
    assert {"trample", "lifelink"} <= {str(k).lower() for k in walker.granted_keywords}
