"""BUG-3 — RULE 608.2b: every restriction of a target requirement is rechecked as the spell/ability resolves,
not just its zone and power/toughness bounds: keyword ("with flying"), tapped/untapped and attacking state.

The recheck is `targeting.target_meets_restrictions`, which reuses the announce-time predicate
(`legal_targets`) minus hexproof/shroud/protection, so there is one definition of "legal for this spec".
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.game import make_engine


def _creature(name, text="", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Test", oracle_text=text, is_creature=True,
                power=power, toughness=toughness)


def _engine():
    eng = make_engine([_creature(f"Filler {i}") for i in range(5)],
                      [_creature(f"Other {i}") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _fire(eng, text, *targets):
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, _creature("Source", f"{{R}}: {text}", 1, 1))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, src, targets=list(targets))
    return src


def _lose_flying(obj):
    obj.suppressed_keywords = {"flying"}
    obj.temp_removed_keywords = {"flying"}


def test_target_that_lost_flying_is_not_destroyed():
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    _fire(eng, "Destroy target creature with flying.", flyer)
    _lose_flying(flyer)
    eng.recompute_continuous_effects()
    eng.resolve_until_stable()
    assert flyer.zone == Zone.BATTLEFIELD


def test_target_that_keeps_flying_is_destroyed():
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    _fire(eng, "Destroy target creature with flying.", flyer)
    eng.resolve_until_stable()
    assert flyer.zone == Zone.GRAVEYARD


def test_target_that_untapped_is_not_affected_by_a_tapped_requirement():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    victim.tapped = True
    _fire(eng, "Destroy target tapped creature.", victim)
    victim.tapped = False
    eng.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD


def test_target_that_left_combat_is_not_affected_by_an_attacking_requirement():
    eng = _engine()
    attacker = _put(eng, _creature("Attacker"), controller="p2")
    attacker.attacking = True
    _fire(eng, "Destroy target attacking creature.", attacker)
    attacker.attacking = False  # removed from combat in response (RULE 506.4)
    eng.resolve_until_stable()
    assert attacker.zone == Zone.BATTLEFIELD


def test_target_still_attacking_is_destroyed():
    eng = _engine()
    attacker = _put(eng, _creature("Attacker"), controller="p2")
    attacker.attacking = True
    _fire(eng, "Destroy target attacking creature.", attacker)
    eng.resolve_until_stable()
    assert attacker.zone == Zone.GRAVEYARD


def test_target_that_gains_hexproof_in_response_to_an_opponents_ability_is_illegal():
    # RULE 608.2b + 702.11b: legality includes targetability, so hexproof gained after targeting fizzles it.
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    _fire(eng, "Destroy target creature with flying.", flyer)
    flyer.intrinsic_keywords = set(flyer.intrinsic_keywords) | {"hexproof"}
    eng.resolve_until_stable()
    assert flyer.zone == Zone.BATTLEFIELD


def test_own_ability_still_hits_own_creature_that_gains_hexproof():
    # RULE 702.11b: hexproof only stops the opponents of its controller.
    eng = _engine()
    mine = _put(eng, _creature("Mine", "Flying"), controller="p1")
    _fire(eng, "Destroy target creature with flying.", mine)
    mine.intrinsic_keywords = set(mine.intrinsic_keywords) | {"hexproof"}
    eng.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD


def test_shroud_gained_in_response_stops_even_the_controllers_own_ability():
    eng = _engine()
    mine = _put(eng, _creature("Mine", "Flying"), controller="p1")
    _fire(eng, "Destroy target creature with flying.", mine)
    mine.intrinsic_keywords = set(mine.intrinsic_keywords) | {"shroud"}
    eng.resolve_until_stable()
    assert mine.zone == Zone.BATTLEFIELD


def test_protection_from_the_sources_colour_gained_in_response_is_illegal():
    # RULE 702.16b; the source's colour is read from the still-existing object (RULE 113.7a).
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    src = _fire(eng, "Destroy target creature with flying.", flyer)
    src.card.color_identity = ["R"]
    assert "R" in src.colors, "fixture: the source must be red for protection from red to apply"
    flyer.temp_protections = {"R"}
    eng.resolve_until_stable()
    assert flyer.zone == Zone.BATTLEFIELD


def _cast_instant(eng, text, *targets, colors=("R",)):
    card = Card(id="Bolt-ish", name="Test Instant", type_line="Instant", oracle_text=text, is_instant=True,
                converted_mana_cost=0, color_identity=list(colors))
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    eng.state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    bind_from_catalogue(spell)
    eng.cast_spell(eng.state.player_by_id("p1"), spell, targets=list(targets))
    return spell


def test_spell_whose_only_target_lost_flying_fizzles_to_the_graveyard():
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    spell = _cast_instant(eng, "Destroy target creature with flying.", flyer)
    _lose_flying(flyer)
    eng.recompute_continuous_effects()
    eng.resolve_until_stable()
    assert flyer.zone == Zone.BATTLEFIELD
    assert spell.zone == Zone.GRAVEYARD


def test_spell_whose_target_keeps_flying_destroys_it():
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    _cast_instant(eng, "Destroy target creature with flying.", flyer)
    eng.resolve_until_stable()
    assert flyer.zone == Zone.GRAVEYARD


def test_spell_fizzles_when_the_target_gains_hexproof_in_response():
    eng = _engine()
    flyer = _put(eng, _creature("Flyer", "Flying"), controller="p2")
    _cast_instant(eng, "Destroy target creature with flying.", flyer)
    flyer.intrinsic_keywords = set(flyer.intrinsic_keywords) | {"hexproof"}
    eng.resolve_until_stable()
    assert flyer.zone == Zone.BATTLEFIELD


def test_one_illegal_target_among_several_does_not_fizzle_the_other():
    # RULE 608.2b: the ability is countered only if *all* its targets are illegal; the legal one is still affected.
    eng = _engine()
    a = _put(eng, _creature("A", "Flying"), controller="p2")
    b = _put(eng, _creature("B"), controller="p2")
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, _creature("Source", "{R}: Destroy target creature with flying and tap target creature.", 1, 1))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, src, targets=[a, b], target_groups=[[a], [b]])
    _lose_flying(a)
    eng.recompute_continuous_effects()
    eng.resolve_until_stable()
    assert a.zone == Zone.BATTLEFIELD  # destroy skipped: no longer a flier
    assert b.tapped and b.zone == Zone.BATTLEFIELD  # the other clause still happened


def _aura(eng):
    card = Card(id="Test Aura", name="Test Aura", type_line="Enchantment — Aura", oracle_text="Enchant creature\nEnchanted creature gets +1/+1.",
                converted_mana_cost=0)
    aura = GameObject(card, owner_id="p1", zone=Zone.HAND)
    eng.state.player_by_id("p1").add_to_zone(aura, Zone.HAND)
    bind_from_catalogue(aura)
    return aura


def test_aura_spell_whose_target_gains_hexproof_goes_to_the_graveyard():
    # RULE 608.3b / 303.4: an Aura spell with an illegal target doesn't resolve onto the battlefield.
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    aura = _aura(eng)
    eng.cast_spell(eng.state.player_by_id("p1"), aura, targets=[victim])
    victim.intrinsic_keywords = set(victim.intrinsic_keywords) | {"hexproof"}
    eng.resolve_until_stable()
    assert aura.zone == Zone.GRAVEYARD


def test_aura_spell_with_a_legal_target_still_attaches():
    eng = _engine()
    victim = _put(eng, _creature("Victim"), controller="p2")
    aura = _aura(eng)
    eng.cast_spell(eng.state.player_by_id("p1"), aura, targets=[victim])
    eng.resolve_until_stable()
    assert aura.zone == Zone.BATTLEFIELD and aura.attached_to == victim.instance_id


def test_equip_does_not_attach_to_a_creature_that_gained_shroud():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    mine = _put(eng, _creature("Mine"))
    card = Card(id="Test Blade", name="Test Blade", type_line="Artifact — Equipment",
                oracle_text="Equipped creature gets +1/+1.\nEquip {0}", converted_mana_cost=0)
    card.keywords = ["Equip"]
    blade = _put(eng, card)
    eng.activate_ability(p1, blade, targets=[mine])
    mine.intrinsic_keywords = set(mine.intrinsic_keywords) | {"shroud"}
    eng.resolve_until_stable()
    assert blade.attached_to is None


def test_equip_attaches_to_a_creature_that_stays_legal():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    mine = _put(eng, _creature("Mine"))
    card = Card(id="Test Blade", name="Test Blade", type_line="Artifact — Equipment",
                oracle_text="Equipped creature gets +1/+1.\nEquip {0}", converted_mana_cost=0)
    card.keywords = ["Equip"]
    blade = _put(eng, card)
    eng.activate_ability(p1, blade, targets=[mine])
    eng.resolve_until_stable()
    assert blade.attached_to == mine.instance_id
