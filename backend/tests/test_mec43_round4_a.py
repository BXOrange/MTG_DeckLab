"""MEC-43 round 4A: combat/equipment/damage/lifegain cluster A.

Eight cards, five new engine primitives:

* `costs.SACRIFICE_COUNT_X` -- the `sacrifice_count` sibling of
  `REMOVE_COUNTERS_X` (Grim Hireling's "Sacrifice X Treasures").
* `GainLifeEffect.amount_from_trigger_source_toughness` /
  `DiscardEffect.player_from_trigger_event` -- reading the firing DAMAGE
  event's own source/recipient (Ikra Shidiqi, Sword of Feast and Famine),
  plus `TapEffect`'s "lands_you_control" selector.
* RULE 700.2 modal choice on an *activated* ability (`ActivatedAbility.
  modes`, `GameEngine.activate_ability`'s new `mode` param) -- previously
  spell/triggered only (Umezawa's Jitte).
* `continuous.commander_color_identity` + `grant_protection_static`'s
  `protection_from_colors_not_in_commanders_identity`, plus a second,
  target-*filtered* Equip ability (`AttachEffect.creature_filter`, a new
  "is_commander" `combat.matches_object_filter` key) for "Equip
  commander {N}" (Commander's Plate) -- which also surfaced and fixed a
  real parser bug: the "equip" keyword's cost regex was swallowing "Equip
  commander {3}" as if it were the plain Equip cost.
* `continuous.split_second_active` (RULE 702.61b, wired into `can_cast`/
  `can_activate`) and the `GrantUntilEffect`/`PumpEffect` "previous_
  subject" pronoun chain onto a granted `grant_triggered_ability`
  (Legolas's Quick Reflexes).
* `GameState.damage_dealt_to_players_this_turn` + `LoseLifeEffect.
  amount_from_damage_dealt_this_turn` (Final Punishment).
* `ManaCost.with_x_colored` (RULE 605.3a scoped to just the announced
  {X}, not the whole cost) + a new atomic `DamageAndDrainCappedEffect`
  (Drain Life) -- which also widened `targeting.legal_targets`'s "any
  target" (RULE 115.4) to include planeswalkers/battles, a stale gap from
  before either card type was modeled.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1", obj=None, **extra):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD, **extra)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _catalogue_obj(name, controller="p1", zone=Zone.BATTLEFIELD, **extra):
    obj = GameObject(_named(name), owner_id=controller, zone=zone, **extra)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# Grim Hireling
# ---------------------------------------------------------------------------


def test_grim_hireling_is_registered():
    assert is_registered("Grim Hireling")


def test_grim_hireling_creates_two_treasures_on_combat_damage():
    engine, state, p1, p2 = _engine()
    hireling = _catalogue_obj("Grim Hireling")
    state.add_to_battlefield(hireling)
    attacker = _bf(state, _card("Bear", power=3))
    before = [o for o in state.battlefield if o.controller_id == "p1"]

    engine.begin_turn()
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [attacker])
    engine.state.current_step = "combat_damage"
    engine._step_combat_damage()
    engine.resolve_until_stable()

    treasures = [
        o for o in state.battlefield
        if o.controller_id == "p1" and o not in before
        and "treasure" in o.card.type_line.lower()
    ]
    assert len(treasures) == 2


def test_grim_hireling_sacrifice_x_treasures_shrinks_target_by_x():
    engine, state, p1, p2 = _engine()
    hireling = _catalogue_obj("Grim Hireling")
    state.add_to_battlefield(hireling)
    t1 = _bf(state, _card("Treasure 1", "Artifact — Treasure", "{0}", 0))
    t2 = _bf(state, _card("Treasure 2", "Artifact — Treasure", "{0}", 0))
    victim = _bf(state, _card("Victim", power=4, toughness=4), controller="p2")
    p1.mana_pool.add("B", 1)

    engine.activate_ability(p1, hireling, 0, targets=[victim], x=2)
    engine.resolve_until_stable()

    assert t1 not in state.battlefield
    assert t2 not in state.battlefield
    engine.recompute_continuous_effects()
    assert victim.power == 2 and victim.toughness == 2


# ---------------------------------------------------------------------------
# Ikra Shidiqi, the Usurper
# ---------------------------------------------------------------------------


def test_ikra_shidiqi_is_registered():
    assert is_registered("Ikra Shidiqi, the Usurper")


def test_ikra_shidiqi_gains_life_equal_to_dealers_toughness():
    engine, state, p1, p2 = _engine()
    ikra = _catalogue_obj("Ikra Shidiqi, the Usurper")
    state.add_to_battlefield(ikra)
    dealer = _bf(state, _card("Big Dealer", power=2, toughness=5))
    p1.life = 20

    engine.rules.deal_damage(p2, 2, source=dealer, combat=True)
    engine.resolve_until_stable()

    assert p1.life == 25  # +5, the dealer's toughness -- not the 2 damage dealt


# ---------------------------------------------------------------------------
# Sword of Feast and Famine
# ---------------------------------------------------------------------------


def test_sword_of_feast_and_famine_is_registered():
    assert is_registered("Sword of Feast and Famine")


def test_sword_of_feast_and_famine_discards_and_untaps_lands_on_combat_damage():
    engine, state, p1, p2 = _engine()
    sword = _catalogue_obj("Sword of Feast and Famine")
    state.add_to_battlefield(sword)
    bearer = _bf(state, _card("Bearer", power=2, toughness=2))
    engine.rules.attach_to_target(sword, bearer)
    land = _bf(state, _card("Forest", "Basic Land — Forest", "", 0))
    land.tapped = True
    p2.add_to_zone(GameObject(_card("Card in Hand"), owner_id="p2", zone=Zone.HAND), Zone.HAND)
    assert len(p2.hand) == 1

    engine.recompute_continuous_effects()
    assert bearer.power == 4 and bearer.toughness == 4  # +2/+2 from the sword

    engine.rules.deal_damage(p2, 4, source=bearer, combat=True)
    engine.resolve_until_stable()

    assert len(p2.hand) == 0
    assert land.tapped is False


# ---------------------------------------------------------------------------
# Umezawa's Jitte
# ---------------------------------------------------------------------------


def test_umezawas_jitte_is_registered():
    assert is_registered("Umezawa's Jitte")


def test_umezawas_jitte_gains_two_charge_counters_on_combat_damage():
    engine, state, p1, p2 = _engine()
    jitte = _catalogue_obj("Umezawa's Jitte")
    state.add_to_battlefield(jitte)
    bearer = _bf(state, _card("Bearer", power=2, toughness=2))
    engine.rules.attach_to_target(jitte, bearer)

    engine.rules.deal_damage(p2, 2, source=bearer, combat=True)
    engine.resolve_until_stable()

    assert jitte.counters.get("charge", 0) == 2


def test_umezawas_jitte_modal_ability_offers_all_three_modes():
    engine, state, p1, p2 = _engine()
    jitte = _catalogue_obj("Umezawa's Jitte")
    state.add_to_battlefield(jitte)
    bearer = _bf(state, _card("Bearer", power=2, toughness=2))
    engine.rules.attach_to_target(jitte, bearer)
    victim = _bf(state, _card("Victim", power=3, toughness=3), controller="p2")
    jitte.counters["charge"] = 3
    p1.life = 20

    engine.activate_ability(p1, jitte, 0, mode=0)  # equipped creature +2/+2
    engine.activate_ability(p1, jitte, 0, mode=1, targets=[victim])  # target -1/-1
    engine.activate_ability(p1, jitte, 0, mode=2)  # gain 2 life
    engine.resolve_until_stable()

    engine.recompute_continuous_effects()
    assert bearer.power == 4 and bearer.toughness == 4
    assert victim.power == 2 and victim.toughness == 2
    assert p1.life == 22
    assert jitte.counters.get("charge", 0) == 0


# ---------------------------------------------------------------------------
# Commander's Plate
# ---------------------------------------------------------------------------


def test_commanders_plate_is_registered():
    assert is_registered("Commander's Plate")


def test_commanders_plate_grants_protection_from_colors_outside_commander_identity():
    engine, state, p1, p2 = _engine()
    commander_card = _card(
        "Test Commander", "Legendary Creature — Human", "{B}", 1,
        color_identity={"B"},
    )
    commander = _bf(state, commander_card, obj=GameObject(
        commander_card, owner_id="p1", zone=Zone.BATTLEFIELD, is_commander=True,
    ))
    plate = _catalogue_obj("Commander's Plate")
    state.add_to_battlefield(plate)
    other_creature = _bf(state, _card("Other Creature", power=2, toughness=2))

    engine.rules.attach_to_target(plate, other_creature)
    engine.recompute_continuous_effects()

    assert other_creature.power == 5 and other_creature.toughness == 5  # +3/+3
    assert other_creature._granted_protections == {"W", "U", "R", "G"}  # not black


def test_commanders_plate_equip_commander_only_targets_a_commander():
    engine, state, p1, p2 = _engine()
    commander_card = _card(
        "Test Commander", "Legendary Creature — Human", "{B}", 1,
        color_identity={"B"},
    )
    commander = _bf(state, commander_card, obj=GameObject(
        commander_card, owner_id="p1", zone=Zone.BATTLEFIELD, is_commander=True,
    ))
    plate = _catalogue_obj("Commander's Plate")
    state.add_to_battlefield(plate)
    ordinary = _bf(state, _card("Ordinary Creature", power=2, toughness=2))

    equip_commander = plate.activated_abilities[0]
    assert equip_commander.cost.mana.raw == "{3}"
    spec = equip_commander.effects[0].target_spec
    options = {
        o["instance_id"] for o in legal_targets(state, "p1", spec, source=plate)
    }
    assert commander.instance_id in options
    assert ordinary.instance_id not in options


# ---------------------------------------------------------------------------
# Legolas's Quick Reflexes
# ---------------------------------------------------------------------------


def test_legolass_quick_reflexes_is_registered():
    assert is_registered("Legolas's Quick Reflexes")


def test_legolass_quick_reflexes_untaps_and_grants_keywords_and_a_trigger():
    engine, state, p1, p2 = _engine()
    target_creature = _bf(state, _card("Target Creature", power=3, toughness=3))
    target_creature.tapped = True
    spell = _catalogue_obj("Legolas's Quick Reflexes", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 1)

    engine.cast_spell(p1, spell, targets=[target_creature])
    engine.resolve_until_stable()

    assert target_creature.tapped is False
    engine.recompute_continuous_effects()
    assert "hexproof" in target_creature.granted_keywords
    assert "reach" in target_creature.granted_keywords
    assert len(target_creature._granted_triggered_abilities) == 1

    victim = _bf(state, _card("Victim", power=1, toughness=5), controller="p2")
    engine.rules.set_tapped(target_creature, True)
    engine.resolve_until_stable()

    # "damage equal to its power to up to one target creature" -- power 3,
    # RULE 115.1a's own "up to one" opens an interactive choice even with
    # only one legal candidate (`victim`), the same `trigger_target`
    # pending_choice any granted triggered ability's own target uses.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "trigger_target"
    engine.rules.resolve_trigger_target_choice(str(victim.instance_id))
    engine.resolve_until_stable()

    assert victim.damage_marked == 3


def test_split_second_blocks_casting_while_on_the_stack():
    engine, state, p1, p2 = _engine()
    target_creature = _bf(state, _card("Target Creature", power=1, toughness=1))
    spell = _catalogue_obj("Legolas's Quick Reflexes", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 1)

    engine.cast_spell(p1, spell, targets=[target_creature])
    assert continuous.split_second_active(state) is True

    bolt_card = _card("Shock", "Instant", "{R}", 1)
    bolt = GameObject(bolt_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(bolt, Zone.HAND)
    p1.mana_pool.add("R", 1)
    assert engine.can_cast(p1, bolt) is False

    engine.resolve_until_stable()
    assert continuous.split_second_active(state) is False
    assert engine.can_cast(p1, bolt) is True


# ---------------------------------------------------------------------------
# Final Punishment
# ---------------------------------------------------------------------------


def test_final_punishment_is_registered():
    assert is_registered("Final Punishment")


def test_final_punishment_drains_life_equal_to_damage_already_dealt_this_turn():
    engine, state, p1, p2 = _engine()
    engine.begin_turn()
    dealer = _bf(state, _card("Dealer", power=5, toughness=5))
    p2.life = 20

    engine.rules.deal_damage(p2, 5, source=dealer, combat=True)
    engine.rules.deal_damage(p2, 3, source=dealer, combat=False)
    assert state.damage_dealt_to_players_this_turn.get("p2") == 8

    spell = _catalogue_obj("Final Punishment", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 5)

    engine.cast_spell(p1, spell, targets=[p2])
    engine.resolve_until_stable()

    assert p2.life == 20 - 8 - 8  # damage already taken, then the drain


def test_final_punishment_tracker_resets_next_turn():
    engine, state, p1, p2 = _engine()
    engine.begin_turn()
    dealer = _bf(state, _card("Dealer", power=5, toughness=5))
    engine.rules.deal_damage(p2, 4, source=dealer, combat=True)
    assert state.damage_dealt_to_players_this_turn.get("p2") == 4

    engine.begin_turn()
    assert state.damage_dealt_to_players_this_turn.get("p2", 0) == 0


# ---------------------------------------------------------------------------
# Drain Life
# ---------------------------------------------------------------------------


def test_drain_life_is_registered():
    assert is_registered("Drain Life")


def test_drain_life_deals_x_damage_and_gains_life_capped_by_toughness():
    engine, state, p1, p2 = _engine()
    spell = _catalogue_obj("Drain Life", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 5)  # {X}{1}{B} with X = 3: 3 for X, 1 generic, 1 for {B}
    p1.life = 10
    victim = _bf(state, _card("Small Toughness", power=1, toughness=2), controller="p2")

    engine.cast_spell(p1, spell, targets=[victim], x=3)
    engine.resolve_until_stable()

    # 3 damage dealt, but life gained is capped at the victim's own
    # pre-damage toughness (2), not the full 3 damage.
    assert p1.life == 12


def test_drain_life_x_must_be_paid_with_black_mana():
    engine, state, p1, p2 = _engine()
    spell = _catalogue_obj("Drain Life", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    # Enough total mana, but only 1 black -- not enough to cover X=3 black
    # pips plus the printed {B}, even though the generic {1} could be paid
    # by anything.
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("R", 4)
    victim = _bf(state, _card("Victim", power=1, toughness=2), controller="p2")

    assert engine.can_cast(p1, spell, x=3, targets=[victim]) is False

    p1.mana_pool.add("B", 3)
    assert engine.can_cast(p1, spell, x=3, targets=[victim]) is True
