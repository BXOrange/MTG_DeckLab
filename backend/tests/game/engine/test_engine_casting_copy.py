"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.effects.core import ActivatedAbility

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.game.binding.core import bind_from_catalogue


from engine_test_helpers import creature, make_engine, obj_on_battlefield


def test_stale_card_without_cost_string_still_requires_mana():
    # Regression: a card cached before mana_cost_string existed (empty raw
    # cost, but a non-zero mana value) must not be castable for free.
    stale_sol_ring = Card(
        id="Sol Ring", name="Sol Ring", type_line="Artifact", converted_mana_cost=1
    )
    eng = make_engine([stale_sol_ring], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert not eng.can_cast(p1, p1.hand[0])  # empty pool -> not castable
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, p1.hand[0])


def test_cannot_cast_without_mana():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert not eng.can_cast(p1, p1.hand[0])
    with pytest.raises(ValueError):
        eng.cast_spell(p1, p1.hand[0])


def test_sorcery_speed_creature_needs_empty_stack_and_main_phase():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.state.current_step = "upkeep"
    assert not eng.can_cast(p1, p1.hand[0])  # not a main phase
    eng.state.current_step = "main1"
    assert eng.can_cast(p1, p1.hand[0])


def test_cast_creature_resolves_onto_battlefield():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    bear = p1.hand[0]
    eng.cast_spell(p1, bear)
    assert eng.state.stack and eng.state.stack[-1].obj is bear
    eng.resolve_until_stable()
    assert bear in eng.state.battlefield
    assert bear.summoning_sick  # entered this turn (RULE 302.6)
    assert not eng.state.stack


def test_commander_can_be_cast_from_the_command_zone():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    assert eng.can_cast(p1, commander)
    eng.cast_spell(p1, commander)
    assert commander not in p1.command
    assert eng.state.stack[-1].obj is commander
    eng.resolve_until_stable()
    assert commander in eng.state.battlefield


def test_aura_attaches_to_target_when_permanent_spell_resolves():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura_card = Card(
        id="Aura",
        name="Aura",
        type_line="Enchantment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
    )
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(aura, Zone.HAND)
    aura.parametric_keywords = {"enchant": {"quality": "creature"}}
    eng.cast_spell(p1, aura, targets=[host])
    eng.resolve_until_stable()

    assert aura.attached_to == host.instance_id
    assert aura in eng.state.battlefield


def test_armadillo_cloak_end_to_end_buffs_the_enchanted_creature():
    # Catalogue-registered Aura ("Enchant creature. Enchanted creature gets
    # +2/+2 and has trample and lifelink.") through the full pipeline: cast →
    # keyword catalogue's "enchant" attach (RULE 303.4f) → the hand-authored
    # static buff scoped to "attached_permanent" (docs/11 §6) → continuous
    # recompute → combat honouring the granted keywords.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "W": 1, "C": 2})

    host = GameObject(creature(name="Host", cost="{1}", power=2, toughness=2),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    cloak_card = Card(
        id="AC",
        name="Armadillo Cloak",
        type_line="Enchantment — Aura",
        mana_cost_string="{2}{G}{W}",
        converted_mana_cost=ManaCost.parse("{2}{G}{W}").converted_mana_cost,
        oracle_text="Enchant creature\nEnchanted creature gets +2/+2 and has trample and lifelink.",
    )
    cloak = GameObject(cloak_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(cloak, Zone.HAND)
    bind_from_catalogue(cloak)

    eng.cast_spell(p1, cloak, targets=[host])
    eng.resolve_until_stable()

    assert cloak.attached_to == host.instance_id
    assert (host.power, host.toughness) == (4, 4)
    from mtg_analyzer.game import combat
    assert combat.has_trample(host)
    assert combat.has_lifelink(host)

    # The buff disappears once the Aura itself leaves (it falls off to the
    # graveyard, RULE 704.5m) — nothing lingers once it's not on the battlefield.
    eng.rules.destroy(host)
    eng.resolve_until_stable()
    assert cloak in eng.state.player_by_id("p1").graveyard


def test_become_copy_mutates_the_object_and_rebinds_its_abilities():
    # RULE 706/707 "become a copy of target permanent": the object's own
    # copiable characteristics (name, P/T, type line, oracle-derived
    # keywords/abilities) become the target's, replacing whatever it had —
    # while its own instance identity, zone and controller are untouched.
    from mtg_analyzer.game.effects.core import ActivatedAbility

    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"

    target_card = creature(name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
                           keywords=["Deathtouch"], oracle_text="Deathtouch")
    target = obj_on_battlefield(eng.state, eng, target_card)

    clone_card = creature(name="Clone", cost="{3}{U}", power=0, toughness=0)
    clone = obj_on_battlefield(eng.state, eng, clone_card)
    # A placeholder ability the pre-copy object had — must be discarded, since
    # a copy replaces its own copiable-derived abilities wholesale (706.2).
    clone.activated_abilities.append(ActivatedAbility(effects=[], source=clone))

    eng.rules.become_copy(clone, target)
    eng.recompute_continuous_effects()

    assert clone.card.name == "Grave Titan"
    assert (clone.power, clone.toughness) == (6, 6)
    assert "deathtouch" in clone.intrinsic_keywords
    assert clone.activated_abilities == []  # Grave Titan has none of its own
    assert clone.instance_id != target.instance_id  # still its own object
    assert clone in eng.state.battlefield and target in eng.state.battlefield


def test_become_copy_applies_except_clause_overrides():
    # Phantasmal Image-style "except it's an Illusion in addition to its
    # other types."
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"

    target = obj_on_battlefield(eng.state, eng, creature(name="Bear", cost="{1}{G}"))
    image = obj_on_battlefield(eng.state, eng, creature(name="Phantasmal Image", cost="{1}{U}"))

    eng.rules.become_copy(image, target, add_subtypes=["Illusion"])

    assert image.card.type_line == "Creature — Bear Illusion"


def test_become_copy_end_to_end_via_registered_catalogue_entry():
    # RULE 614.1c/614.12: casting Clever Impersonator opens a real `enter_
    # as_copy` replacement choice *before* it's added to the battlefield —
    # it's never observably "itself" first, unlike the old ENTERS_
    # BATTLEFIELD-trigger modeling this replaces.
    impersonator_card = Card(id="CI", name="Clever Impersonator",
                              type_line="Creature — Illusion",
                              mana_cost_string="{5}{U}{U}", converted_mana_cost=7,
                              is_creature=True, power=3, toughness=3)  # real printed stats
    eng = make_engine([impersonator_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 5})

    target = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
        keywords=["Deathtouch"], oracle_text="Deathtouch",
    ))
    impersonator = p1.hand[0]
    bind_from_catalogue(impersonator)  # bind-on-load, done here as in production
    eng.cast_spell(p1, impersonator)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    assert impersonator not in eng.state.battlefield  # paused before entering as itself
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert impersonator in eng.state.battlefield
    assert impersonator.card.name == "Grave Titan"
    assert (impersonator.power, impersonator.toughness) == (6, 6)
    assert "deathtouch" in impersonator.intrinsic_keywords


def test_become_copy_declining_enters_as_itself():
    impersonator_card = Card(id="CI", name="Clever Impersonator",
                              type_line="Creature — Illusion",
                              mana_cost_string="{5}{U}{U}", converted_mana_cost=7,
                              is_creature=True, power=3, toughness=3)
    eng = make_engine([impersonator_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 5})

    obj_on_battlefield(eng.state, eng, creature(name="Grave Titan", power=6, toughness=6))
    impersonator = p1.hand[0]
    bind_from_catalogue(impersonator)
    eng.cast_spell(p1, impersonator)
    eng.resolve_until_stable()

    assert eng.state.pending_choice["kind"] == "enter_as_copy"
    eng.resolve_pending_choice("decline")

    assert impersonator in eng.state.battlefield
    assert impersonator.card.name == "Clever Impersonator"
    assert (impersonator.power, impersonator.toughness) == (3, 3)


def test_become_copy_with_no_legal_target_enters_as_itself_without_pausing():
    # RULE 603.3c-style: nothing to offer, so it never opens a pending
    # choice at all — it just enters as itself, same turn, no pause.
    impersonator_card = Card(id="CI", name="Clever Impersonator",
                              type_line="Creature — Illusion",
                              mana_cost_string="{5}{U}{U}", converted_mana_cost=7,
                              is_creature=True, power=3, toughness=3)
    eng = make_engine([impersonator_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 5})

    impersonator = p1.hand[0]
    bind_from_catalogue(impersonator)
    eng.cast_spell(p1, impersonator)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None
    assert impersonator in eng.state.battlefield
    assert impersonator.card.name == "Clever Impersonator"


def test_cursed_mirror_copies_only_on_entering_until_end_of_turn():
    # Real text: "As this artifact enters, you may have it become a copy of any
    # creature on the battlefield until end of turn, except it has haste."
    # The copy is an enter replacement (RULE 614.1c) reverted at cleanup
    # (RULE 514.2) — tapping it never copies anything.
    mirror_card = Card(id="CM", name="Cursed Mirror", type_line="Artifact",
                       mana_cost_string="{2}{R}", converted_mana_cost=3,
                       oracle_text="{T}: Add {R}.\nAs this artifact enters, you may have it become a copy of any "
                                   "creature on the battlefield until end of turn, except it has haste.")
    eng = make_engine([mirror_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})

    obj_on_battlefield(eng.state, eng, creature(name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6))
    mirror = p1.hand[0]
    bind_from_catalogue(mirror)
    assert not mirror.activated_abilities  # no "{T}: become a copy" ability any more
    eng.cast_spell(p1, mirror)
    eng.resolve_until_stable()

    assert eng.state.pending_choice["kind"] == "enter_as_copy"
    titan_id = next(o["id"] for o in eng.state.pending_choice["options"] if o["label"] == "Grave Titan")
    eng.resolve_pending_choice(titan_id)
    eng.recompute_continuous_effects()
    assert mirror in eng.state.battlefield
    assert mirror.card.name == "Grave Titan"
    assert (mirror.power, mirror.toughness) == (6, 6)
    assert "haste" in {k.lower() for k in mirror.granted_keywords} | {k.lower() for k in mirror.intrinsic_keywords}

    eng._step_cleanup()
    assert mirror.card.name == "Cursed Mirror"
    assert mirror._copy_until_eot_base is None


def test_cursed_mirror_declined_stays_a_mirror():
    mirror_card = Card(id="CM", name="Cursed Mirror", type_line="Artifact",
                       mana_cost_string="{2}{R}", converted_mana_cost=3)
    eng = make_engine([mirror_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    obj_on_battlefield(eng.state, eng, creature(name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6))
    mirror = p1.hand[0]
    bind_from_catalogue(mirror)
    eng.cast_spell(p1, mirror)
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    assert mirror in eng.state.battlefield and mirror.card.name == "Cursed Mirror"
    assert mirror._copy_until_eot_base is None
