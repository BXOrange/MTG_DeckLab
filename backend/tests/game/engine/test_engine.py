"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import (
    DealDamageEffect,
    DrawCardEffect,
    EffectRegistry,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import default_turn_sequence
from mtg_analyzer.game.rules_engine import RulesEngine


# ---------------------------------------------------------------------------
# Card factories (set the type flags the Scryfall client would derive)
# ---------------------------------------------------------------------------


def land(name="Forest", produces="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2, **kw):
    return Card(
        id=name,
        name=name,
        type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        **kw,
    )


def instant(name="Shock", cost="{R}"):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine(p1_cards, p2_cards=None, life=20, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=life, starting_hand=hand)


def obj_on_battlefield(state: GameState, engine: GameEngine, card: Card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Turn structure (RULE 500)
# ---------------------------------------------------------------------------


def test_turn_structure_order():
    seq = default_turn_sequence()
    step_names = [step.name for _, step in seq.iter_steps()]
    assert step_names[:4] == ["untap", "upkeep", "draw", "main1"]
    assert step_names[-1] == "cleanup"


def test_first_player_skips_first_draw_in_multiplayer():
    eng = make_engine([land()] * 30, [land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()  # turn 1, p1 active
    # No draw on turn 1 for the starting player, but a land may be played
    # from an (empty) hand — with hand=0, library is only touched by draw.
    assert len(p1.library) == before


def test_solo_player_draws_on_turn_one():
    eng = make_engine([land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()
    assert len(p1.library) == before - 1


# ---------------------------------------------------------------------------
# Land drops & mana (RULE 305 / 504 / 505)
# ---------------------------------------------------------------------------


def test_one_land_per_turn():
    eng = make_engine([land(), land()], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    first, second = p1.hand[0], p1.hand[1]
    eng.play_land(p1, first)
    assert not eng.can_play_land(p1, second)
    with pytest.raises(ValueError):
        eng.play_land(p1, second)


def test_tap_land_for_mana():
    eng = make_engine([land("Forest")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest = eng.play_land(p1, p1.hand[0])
    produced = eng.tap_for_mana(p1, forest)
    assert produced == {"G": 1}
    assert p1.mana_pool.pool["G"] == 1
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, forest)  # already tapped


def _dual_land():
    return Card(
        id="Tundra",
        name="Tundra",
        type_line="Land — Plains Island",
        is_land=True,
        oracle_text="{T}: Add {W} or {U}.",
    )


def test_dual_land_taps_for_only_the_chosen_color():
    # Regression: tapping a WU dual must add ONE colour, not both.
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    p1 = eng.state.active_player
    produced = eng.tap_for_mana(p1, dual, option_index=1)  # choose U
    assert produced == {"U": 1}
    assert p1.mana_pool.pool == {"C": 0, "W": 0, "U": 1, "B": 0, "R": 0, "G": 0}


def test_tap_rejects_out_of_range_option():
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    with pytest.raises(ValueError):
        eng.tap_for_mana(eng.state.active_player, dual, option_index=5)


def test_legal_actions_lists_tap_options_per_source():
    eng = make_engine([land("Forest")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj_on_battlefield(eng.state, eng, _dual_land())
    tap = next(a for a in eng.legal_actions(eng.state.active_player) if a["type"] == "tap_for_mana")
    mana = [opt["mana"] for opt in tap["options"]]
    assert mana == [{"W": 1}, {"U": 1}]


# ---------------------------------------------------------------------------
# Casting & the stack (RULE 601 / 608)
# ---------------------------------------------------------------------------


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
    assert eng.can_cast(p1, p1.hand[0])  # one mana -> castable


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


def test_commander_tax_adds_two_per_previous_cast():
    # RULE 903.8: {2} more per previous cast from the command zone.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Cmdr", cost="{G}"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    # First cast: no tax → costs {G}.
    assert eng.commander_tax(p1, commander) == 0
    p1.mana_pool.add_many({"G": 1})
    eng.cast_spell(p1, commander)
    eng.resolve_until_stable()


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


def test_cursed_mirror_end_to_end_via_registered_catalogue_entry():
    # Cursed Mirror's "{T}: ~ becomes a copy of target creature until end of
    # turn", fully bound from the catalogue — a third copy mechanism (see
    # `test_become_copy_*` for the permanent ETB one, and
    # `test_continuous.py`'s conditional-copy tests for the continuous one),
    # reverted automatically at cleanup (RULE 514.2).
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"

    target = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
    ))
    mirror = obj_on_battlefield(eng.state, eng, Card(
        id="CM", name="Cursed Mirror", type_line="Artifact"))
    bind_from_catalogue(mirror)

    [ability] = mirror.activated_abilities
    ability.apply(eng.rules.context, targets=[target])
    eng.recompute_continuous_effects()
    assert mirror.card.name == "Grave Titan"
    assert (mirror.power, mirror.toughness) == (6, 6)

    eng._step_cleanup()
    assert mirror.card.name == "Cursed Mirror"

    # Activating again next turn copies again (a fresh snapshot each time).
    ability.apply(eng.rules.context, targets=[target])
    eng.recompute_continuous_effects()
    assert mirror.card.name == "Grave Titan"


def test_enchant_creature_oracle_text_follows_aura_logic():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura_card = Card(
        id="AuraText",
        name="AuraText",
        type_line="Enchantment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
        oracle_text="Enchant creature",
    )
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(aura, Zone.HAND)
    bind_from_catalogue(aura)

    eng.cast_spell(p1, aura, targets=[host])
    eng.resolve_until_stable()

    assert aura.attached_to == host.instance_id
    assert aura in eng.state.battlefield


def test_enchant_creature_recognised_even_with_other_scryfall_keywords():
    # Scryfall's keywords array can list other keywords (e.g. Flash) while
    # omitting "Enchant" itself — oracle text must still be cross-checked.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura_card = Card(
        id="AuraFlash",
        name="AuraFlash",
        type_line="Enchantment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
        oracle_text="Flash\nEnchant creature",
        keywords=["Flash"],
    )
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(aura, Zone.HAND)
    bind_from_catalogue(aura)

    eng.cast_spell(p1, aura, targets=[host])
    eng.resolve_until_stable()

    assert aura.attached_to == host.instance_id
    assert aura in eng.state.battlefield


def test_equipment_ability_only_offers_legal_attachment_targets():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    illegal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    options = requirements[0]["options"]
    option_ids = {opt["instance_id"] for opt in options}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids


def test_equipment_spell_enters_the_battlefield_instead_of_the_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    equipment = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(equipment, Zone.HAND)
    bind_from_catalogue(equipment)

    eng.cast_spell(p1, equipment)
    eng.resolve_until_stable()

    assert equipment in eng.state.battlefield
    assert equipment not in p1.graveyard


def test_attached_aura_moves_to_graveyard_when_host_leaves_the_battlefield():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura = GameObject(Card(id="Aura", name="Aura", type_line="Enchantment"), owner_id="p1")
    aura.parametric_keywords = {"enchant": {"quality": "creature"}}
    eng.state.add_to_battlefield(aura)
    eng.rules.attach_to_target(aura, host)

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert aura in p1.graveyard


def test_attached_equipment_stays_on_battlefield_unattached_when_host_leaves():
    # RULE 704.5n: unlike an Aura (704.5m), an Equipment left attached to
    # nothing just becomes unattached — it doesn't go to the graveyard.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    equipment = GameObject(
        Card(id="Equipment", name="Equipment", type_line="Artifact — Equipment"),
        owner_id="p1",
    )
    equipment.parametric_keywords = {"equip": {}}
    eng.state.add_to_battlefield(equipment)
    eng.rules.attach_to_target(equipment, host)

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert equipment in eng.state.battlefield
    assert equipment not in p1.graveyard
    assert equipment.attached_to is None


def test_equip_only_offers_and_attaches_creatures_you_control():
    """RULE 301.5b/702.6a: "target creature you control" — not an opponent's.

    Control matters both when the ability is activated (offer time) and
    when it resolves (`_attachment_legal`), so both are checked here.
    """
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_creature = obj_on_battlefield(eng.state, eng, creature(name="Own"), controller="p1")
    opponents_creature = obj_on_battlefield(
        eng.state, eng, creature(name="Theirs"), controller="p2"
    )

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_creature.instance_id in option_ids
    assert opponents_creature.instance_id not in option_ids

    assert eng.rules.attach_to_target(source, own_creature)
    source.attached_to = None
    assert not eng.rules._attachment_legal(source, opponents_creature)


def test_reconfigure_only_offers_creatures_you_control():
    """RULE 702.151a: "another target creature you control" — same restriction."""
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_creature = obj_on_battlefield(eng.state, eng, creature(name="Own"), controller="p1")
    opponents_creature = obj_on_battlefield(
        eng.state, eng, creature(name="Theirs"), controller="p2"
    )

    card = Card(
        id="Reconfigurable",
        name="Reconfigurable",
        type_line="Artifact Creature — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
    )
    card.keywords = ["Reconfigure"]
    card.oracle_text = "Reconfigure {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_creature.instance_id in option_ids
    assert opponents_creature.instance_id not in option_ids


def test_fortify_only_offers_lands_you_control():
    """RULE 702.67a: "target land you control" — same restriction."""
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_land = obj_on_battlefield(
        eng.state, eng, land(name="Own Mountain", produces="Mountain"), controller="p1"
    )
    opponents_land = obj_on_battlefield(
        eng.state, eng, land(name="Their Mountain", produces="Mountain"), controller="p2"
    )

    card = Card(
        id="Fortification",
        name="Fortification",
        type_line="Artifact — Fortification",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Fortify"]
    card.oracle_text = "Fortify {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_land.instance_id in option_ids
    assert opponents_land.instance_id not in option_ids


def test_reconfigure_ability_only_offers_creature_attachment_targets():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    illegal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))

    card = Card(
        id="Reconfigurable",
        name="Reconfigurable",
        type_line="Artifact Creature — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
    )
    card.keywords = ["Reconfigure"]
    card.oracle_text = "Reconfigure {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids


def test_fortify_ability_only_offers_land_attachment_targets():
    # RULE 702.151b/301.5c: Fortify attaches to a land, not a creature —
    # unlike Equip/Reconfigure above, offering (and resolving) it against
    # any permanent was a real gap until targeting.py/_attachment_legal
    # gained an explicit "fortify" case.
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))
    illegal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))

    card = Card(
        id="Fortification",
        name="Fortification",
        type_line="Artifact — Fortification",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Fortify"]
    card.oracle_text = "Fortify {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids

    assert eng.rules.attach_to_target(source, legal_host)
    assert source.attached_to == legal_host.instance_id
    source.attached_to = None
    assert not eng.rules._attachment_legal(source, illegal_host)


def test_reconfigure_permanent_stops_being_a_creature_while_attached():
    # RULE 702.151b: attaching a Reconfigure permanent to another creature
    # turns it into a (non-creature) Equipment until it becomes unattached —
    # including automatically, when its host leaves the battlefield.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    reconfigurable = GameObject(
        creature(name="Reconfigurable", cost="{1}", power=1, toughness=1),
        owner_id="p1",
    )
    reconfigurable.parametric_keywords = {"reconfigure": {"cost": "{2}"}}
    eng.state.add_to_battlefield(reconfigurable)

    eng.recompute_continuous_effects()
    assert reconfigurable.is_creature

    eng.rules.attach_to_target(reconfigurable, host)
    eng.recompute_continuous_effects()
    assert not reconfigurable.is_creature

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert reconfigurable in eng.state.battlefield
    assert reconfigurable.attached_to is None
    assert reconfigurable.is_creature


def test_commander_tax_adds_two_per_previous_cast():
    # RULE 903.8: {2} more per previous cast from the command zone.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Cmdr", cost="{G}"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    # First cast: no tax → costs {G}.
    assert eng.commander_tax(p1, commander) == 0
    p1.mana_pool.add_many({"G": 1})
    eng.cast_spell(p1, commander)
    eng.resolve_until_stable()

    # Send it back to the command zone and cast again: now taxed {2}.
    eng.state.remove_from_battlefield(commander)
    p1.add_to_zone(commander, Zone.COMMAND)
    assert eng.commander_tax(p1, commander) == 2
    assert eng.effective_cast_cost(p1, commander).converted_mana_cost == 3  # {2}{G}
    p1.mana_pool.add_many({"G": 1, "C": 2})
    assert eng.can_cast(p1, commander)
    eng.cast_spell(p1, commander)
    eng.state.remove_from_battlefield(commander)
    p1.add_to_zone(commander, Zone.COMMAND)
    assert eng.commander_tax(p1, commander) == 4


def test_commander_dying_offers_command_zone_choice_and_can_move_there():
    # RULE 903.9a: a commander that dies actually reaches the graveyard —
    # unlike a non-commander, its owner is then offered a one-time SBA
    # choice to move it to the command zone instead of leaving it there.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.deal_damage(commander, 1)
    eng.rules.check_state_based_actions()

    assert commander not in eng.state.battlefield
    assert commander in p1.graveyard
    assert commander not in p1.command
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    assert choice["instance_id"] == commander.instance_id

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.graveyard
    assert eng.state.pending_choice is None


def test_commander_moved_to_the_command_zone_forgets_its_battlefield_state():
    # RULE 400.7 (bug report, 2026-09-04): moving into the command zone is
    # a zone change like any other — the commander must not carry
    # combat/counter state from its previous life on the battlefield into
    # its next one. A commander that died mid-attack once carried a stale
    # `attacking`/`combat_defender` all the way through a same-turn recast,
    # corrupting `attackers()`/every per-attacker aggregate built from it.
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [commander])
    assert commander.attacking is True
    assert commander.combat_defender is not None
    commander.counters["+1/+1"] = 3  # toughness 1 -> 4; deal_damage below must match

    eng.rules.deal_damage(commander, 4)
    eng.rules.check_state_based_actions()
    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander.attacking is False
    assert commander.combat_defender is None
    assert commander.counters == {}
    assert commander.damage_marked == 0
    assert commander.summoning_sick is False  # only meaningful on the battlefield


def test_commander_dying_choice_declined_stays_in_graveyard():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.deal_damage(commander, 1)
    eng.rules.check_state_based_actions()
    eng.rules.resolve_choice("decline")

    assert commander in p1.graveyard
    assert commander not in p1.command
    assert eng.state.pending_choice is None


def test_countered_commander_spell_offers_command_zone_choice():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, commander)

    eng.rules.counter_spell(commander)

    assert commander in p1.graveyard
    assert commander not in p1.command
    choice = eng.state.pending_choice
    assert choice is None  # counter_spell doesn't itself check SBAs

    eng.rules.check_state_based_actions()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.graveyard


def test_exiled_commander_offers_command_zone_choice():
    # RULE 903.9a covers exile identically to graveyard.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.exile(commander)
    eng.rules.check_state_based_actions()

    assert commander in p1.exile
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.exile


def test_bounced_commander_offers_command_zone_choice():
    # RULE 903.9b: hand (unlike graveyard/exile) is a replacement effect —
    # the choice opens immediately, not on the next SBA check.
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.return_to_hand(commander)

    assert commander in p1.hand
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "commander_zone"
    assert choice["instance_id"] == commander.instance_id

    eng.rules.resolve_choice("command")

    assert commander in p1.command
    assert commander not in p1.hand


def test_bounced_commander_choice_declined_stays_in_hand():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.return_to_hand(commander)
    eng.rules.resolve_choice("decline")

    assert commander in p1.hand
    assert commander not in p1.command


def test_non_commander_permanent_never_offers_command_zone_choice():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    bear = GameObject(creature(name="Plain Bear", toughness=1), owner_id="p1")
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    eng.rules.deal_damage(bear, 1)
    eng.rules.check_state_based_actions()

    assert bear in p1.graveyard
    assert eng.state.pending_choice is None


def test_instant_can_be_cast_at_instant_speed():
    eng = make_engine([instant()], [land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # not a main phase, stack empty
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, p1.hand[0])


def test_phyrexian_mana_payment_drains_life():
    # Regression: ManaPool.pay computes the life spent on a Phyrexian pip
    # but cast_spell used to discard it, so paying {R/P} with life never
    # actually cost anything (RULE 119.4).
    eng = make_engine([instant(name="Gut Shot", cost="{R/P}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert p1.life == 20
    eng.cast_spell(p1, p1.hand[0])  # empty pool -> must pay 2 life instead
    assert p1.life == 18


def test_x_spell_defaults_to_x_zero():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)  # only enough for X=0
    assert eng.can_cast(p1, p1.hand[0])  # X=0 is always a legal announcement
    eng.cast_spell(p1, p1.hand[0])
    assert eng.state.stack[-1].x == 0
    assert p1.mana_pool.pool["R"] == 0


def test_x_spell_pays_the_announced_value():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    assert not eng.can_cast(p1, p1.hand[0], x=4)  # only 3 generic available
    assert eng.can_cast(p1, p1.hand[0], x=3)
    eng.cast_spell(p1, p1.hand[0], x=3)
    assert eng.state.stack[-1].x == 3
    assert p1.mana_pool.total() == 0  # R + 3 generic all spent


def test_x_spell_legal_action_reports_max_affordable_x():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    [cast_action] = [
        a for a in eng.legal_actions(p1) if a["type"] == "cast_spell"
    ]
    assert cast_action["has_x"] is True
    assert cast_action["max_x"] == 3


# ---------------------------------------------------------------------------
# Summoning sickness and {T} costs (RULE 302.6 / 602.5e)
# ---------------------------------------------------------------------------


def _sick(state, engine, card, controller="p1", haste=False):
    """Put a *summoning-sick* permanent on the battlefield (no obj_on_battlefield
    here, which clears sickness)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = True
    if haste:
        obj.intrinsic_keywords.add("haste")
    state.add_to_battlefield(obj)
    return obj


def _mana_dork(name="Llanowar Elves"):
    return creature(name=name, cost="{G}", power=1, toughness=1,
                    type_line="Creature — Elf Druid", oracle_text="{T}: Add {G}.")


def _mana_offered(engine, player, obj):
    return any(
        a.get("type") == "tap_for_mana" and a.get("instance_id") == obj.instance_id
        for a in engine.legal_actions(player)
    )


def test_summoning_sick_creature_cannot_tap_for_mana():
    eng = make_engine([land()], hand=0)
    dork = _sick(eng.state, eng, _mana_dork())
    p1 = eng.state.active_player
    assert not _mana_offered(eng, p1, dork)  # not a legal action
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, dork)  # and refused if forced


def test_haste_lets_a_creature_tap_for_mana_the_turn_it_arrives():
    eng = make_engine([land()], hand=0)
    dork = _sick(eng.state, eng, _mana_dork(), haste=True)
    p1 = eng.state.active_player
    assert _mana_offered(eng, p1, dork)
    assert eng.tap_for_mana(p1, dork) == {"G": 1} and dork.tapped


def test_noncreature_mana_source_ignores_summoning_sickness():
    # A mana rock / land is never summoning sick for {T} (RULE 302.6 is creatures).
    eng = make_engine([land()], hand=0)
    rock = Card(id="Sol Ring", name="Sol Ring", type_line="Artifact",
                oracle_text="{T}: Add {C}{C}.")
    obj = _sick(eng.state, eng, rock)
    p1 = eng.state.active_player
    assert _mana_offered(eng, p1, obj)
    assert eng.tap_for_mana(p1, obj) == {"C": 2}


def test_summoning_sick_creature_cannot_activate_tap_ability():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = make_engine([land()], hand=0)
    pinger = _mana_dork(name="Prodigal Pyromancer")
    pinger.oracle_text = "{T}: Prodigal Pyromancer deals 1 damage to any target."
    sick = _sick(eng.state, eng, pinger)
    bind_from_catalogue(sick)
    ability = sick.activated_abilities[0]
    p1 = eng.state.active_player
    assert not eng.can_activate(p1, sick, ability)

    hasty = _sick(eng.state, eng, pinger, haste=True)
    bind_from_catalogue(hasty)
    assert eng.can_activate(p1, hasty, hasty.activated_abilities[0])


def test_stack_is_lifo():
    eng = make_engine([land()], hand=0)
    state = eng.state
    resolved = []
    # Two abilities whose effects record their order when resolved.
    from mtg_analyzer.game.effects.core import GameEffect

    class Record(GameEffect):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag

        def apply(self, context, targets=None):
            resolved.append(self.tag)

    from mtg_analyzer.models.game.game_state import StackItem

    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("first")]))
    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("second")]))
    eng.resolve_until_stable()
    assert resolved == ["second", "first"]  # last in, first out


# ---------------------------------------------------------------------------
# State-based actions (RULE 704)
# ---------------------------------------------------------------------------


def test_player_at_zero_life_loses():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.life = 0
    eng.rules.check_state_based_actions()
    assert p1.has_lost
    assert eng.state.game_over
    assert eng.state.winner_id == "p2"


def test_cant_lose_effect_prevents_loss():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.life = -5
    p1.player_effects.append(WinConditionEffect("prevent_loss"))
    eng.rules.check_state_based_actions()
    assert not p1.has_lost


def test_lethal_damage_destroys_creature():
    eng = make_engine([land()], hand=0)
    bear = obj_on_battlefield(eng.state, eng, creature())
    bear.damage_marked = 2  # toughness 2
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield
    assert bear.zone == Zone.GRAVEYARD
    assert bear.damage_marked == 0  # cleared on leaving play


def test_zero_toughness_creature_dies():
    eng = make_engine([land()], hand=0)
    frog = obj_on_battlefield(eng.state, eng, creature("Frog", power=1, toughness=1))
    frog.plus_one_counters = -1  # net toughness 0
    eng.rules.check_state_based_actions()
    assert frog not in eng.state.battlefield


def test_legend_rule_keeps_one():
    eng = make_engine([land()], hand=0)
    c = creature("Commander", is_legendary=True)
    a = obj_on_battlefield(eng.state, eng, c)
    b = obj_on_battlefield(eng.state, eng, c)
    eng.rules.check_state_based_actions()
    survivors = [o for o in eng.state.battlefield if o.name == "Commander"]
    assert len(survivors) == 1
    assert survivors[0] is a  # the first-seen copy is kept


def test_draw_from_empty_library_loses():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()
    eng.rules.draw(p1, 1)
    eng.rules.check_state_based_actions()
    assert p1.has_lost
    assert p1.loss_reason == "draw_from_empty"


# ---------------------------------------------------------------------------
# Damage / effects primitives
# ---------------------------------------------------------------------------


def test_deal_damage_to_player_reduces_life():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3)
    assert p2.life == 17


def _life_lost_events(eng):
    events = []
    eng.state.subscribe(lambda e: events.append(e) if e.type == EventType.LIFE_LOST else None)
    return events


def test_deal_damage_fires_life_lost_with_damage_cause():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    events = _life_lost_events(eng)
    eng.rules.deal_damage(p2, 3)
    assert [(e["amount"], e["cause"]) for e in events] == [(3, "damage")]


def test_phyrexian_mana_payment_fires_life_lost_with_cost_cause():
    eng = make_engine([instant(name="Gut Shot", cost="{R/P}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    events = _life_lost_events(eng)
    eng.cast_spell(p1, p1.hand[0])
    assert [(e["amount"], e["cause"]) for e in events] == [(2, "cost")]


def test_rules_engine_lose_life_is_the_shared_choke_point():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    events = _life_lost_events(eng)
    eng.rules.lose_life(p1, 4)  # default cause, e.g. a direct life-loss effect
    assert p1.life == 16
    assert [(e["amount"], e["cause"]) for e in events] == [(4, "effect")]
    # A non-positive amount is a no-op (mirrors gain_life's guard) — no event.
    eng.rules.lose_life(p1, 0)
    assert len(events) == 1


def test_deal_damage_effect_via_context():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    DealDamageEffect(amount=5).apply(eng.rules.context, targets=[p2])
    assert p2.life == 15


def test_effect_registry_creates_known_effects():
    effect = EffectRegistry.create("draw", {"count": 2})
    assert isinstance(effect, DrawCardEffect)
    assert effect.count == 2
    with pytest.raises(ValueError):
        EffectRegistry.create("nonexistent")


# ---------------------------------------------------------------------------
# Replacement effects (RULE 614 / 616)
# ---------------------------------------------------------------------------


def test_replacement_draw_two_instead():
    eng = make_engine([land("Forest"), land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")

    def draw_two(event, ctx):
        return event.copy_with(count=event.get("count", 1) + 1)

    source = obj_on_battlefield(eng.state, eng, creature("Tymna"))
    source.replacement_effects.append(
        ReplacementEffect(EventType.DRAW, draw_two, description="draw an extra")
    )
    before = len(p1.hand)
    eng.rules.draw(p1, 1)
    assert len(p1.hand) == before + 2


def test_replacement_can_prevent_event():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    source = obj_on_battlefield(eng.state, eng, creature("Fog Bank"))
    source.replacement_effects.append(
        ReplacementEffect(EventType.DAMAGE, lambda e, c: None, description="prevent all damage")
    )
    eng.rules.deal_damage(p2, 10)
    assert p2.life == 20  # prevented


# ---------------------------------------------------------------------------
# Triggered abilities (RULE 603)
# ---------------------------------------------------------------------------


def test_triggered_ability_goes_on_stack_and_resolves():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")
    # "Whenever you draw a card, draw a card" style trigger for testing.
    trigger = TriggeredAbility(
        trigger_event=EventType.SPELL_CAST,
        effects=[DrawCardEffect(count=1, player=p1)],
        controller_id="p1",
        description="draw on cast",
    )
    watcher = obj_on_battlefield(eng.state, eng, creature("Watcher"))
    watcher.triggered_abilities.append(trigger)

    before = len(p1.hand)
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1"))
    assert eng.rules.pending_triggers  # collected, not yet on stack
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1
    assert not eng.rules.pending_triggers


def test_triggered_ability_stack_item_carries_its_source():
    """A stack item for a triggered ability exposes the permanent it belongs
    to (`StackItem.source`), so the UI can show that card's image/link."""
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")
    trigger = TriggeredAbility(
        trigger_event=EventType.SPELL_CAST,
        effects=[DrawCardEffect(count=1, player=p1)],
        controller_id="p1",
        description="draw on cast",
        source=None,  # set below, mirroring how the binder sets it
    )
    watcher = obj_on_battlefield(eng.state, eng, creature("Watcher"))
    trigger.source = watcher
    watcher.triggered_abilities.append(trigger)

    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1"))
    eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack) == 1
    assert eng.state.stack[0].source is watcher
    assert eng.state.stack[0].to_dict()["source"]["instance_id"] == watcher.instance_id


# ---------------------------------------------------------------------------
# Phase skipping (docs/07 PART 8)
# ---------------------------------------------------------------------------


def test_skip_untap_step_leaves_permanents_tapped():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    tapped_land = obj_on_battlefield(eng.state, eng, land())
    tapped_land.tap()
    p1.player_effects.append(
        StaticEffect("skip_phase", {"phase": "untap"}, duration="permanent")
    )
    eng.run_turn()
    assert tapped_land.tapped  # untap step skipped, stays tapped


# ---------------------------------------------------------------------------
# Action validation (docs/02 R4.3)
# ---------------------------------------------------------------------------


def test_legal_actions_lists_land_and_pass():
    eng = make_engine([land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    actions = eng.legal_actions(p1)
    types = {a["type"] for a in actions}
    assert "pass_priority" in types
    assert "play_land" in types


def test_legal_actions_offers_tap_for_mana():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    forest = obj_on_battlefield(eng.state, eng, land("Forest"))
    actions = eng.legal_actions(eng.state.active_player)
    assert any(a["type"] == "tap_for_mana" for a in actions)


# ---------------------------------------------------------------------------
# Combat (RULE 508 / 510)
# ---------------------------------------------------------------------------


def test_summoning_sick_creature_cannot_attack():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature())
    bear.summoning_sick = True
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [bear])


def test_attackers_deal_damage_to_opponent():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.tapped
    assert bear.attacking
    # The sole opponent is auto-assigned as the defender (no ambiguity).
    assert bear.combat_defender == {"kind": "player", "id": "p2", "label": "Bob"}
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p2").life == 17


def planeswalker(name="Test Walker", controller="p2", loyalty=5):
    return Card(id=name, name=name, type_line="Legendary Planeswalker — Test", loyalty=loyalty)


def test_solo_goldfish_swing_has_no_defender_and_deals_no_damage():
    eng = make_engine([land()], hand=0)  # one player, no opponent
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    assert eng.legal_defenders_for(eng.state.active_player) == []
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.attacking and bear.tapped
    assert bear.combat_defender is None  # bare swing
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()  # nothing to damage → no crash, no life change


def test_ambiguous_defender_requires_explicit_choice():
    # Two opponents → the engine won't guess; a bare declaration is illegal.
    libs = [("p1", "A", [land()]), ("p2", "B", [land()]), ("p3", "C", [land()])]
    eng = GameEngine.new_game(libs, starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [bear])
    # Naming a defender resolves it; that opponent takes the damage.
    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": bear, "defender": {"kind": "player", "id": "p3", "label": "C"}}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p3").life == 17
    assert eng.state.player_by_id("p2").life == 20


def test_attack_planeswalker_removes_loyalty():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    walker = obj_on_battlefield(eng.state, eng, planeswalker(loyalty=5), controller="p2")
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    defenders = eng.legal_defenders_for(eng.state.active_player)
    # The opponent AND their planeswalker are both legal defenders.
    assert {d["kind"] for d in defenders} == {"player", "planeswalker"}
    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": bear, "defender": {"kind": "planeswalker", "instance_id": walker.instance_id}}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # RULE 306.9: 3 combat damage removes 3 loyalty counters (5 → 2).
    assert walker.loyalty == 2
    assert eng.state.player_by_id("p2").life == 20  # player untouched


def test_blocked_attacker_hits_blocker_not_player():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=3))
    blocker = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    eng.declare_attackers(eng.state.active_player, [attacker])

    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    assert blocker.blocking == attacker.instance_id
    assert attacker.blocked_by == [blocker.instance_id]

    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # Player took no damage; the 2/2 blocker died to 3 damage; the 3/3
    # attacker survived with 2 marked.
    assert eng.state.player_by_id("p2").life == 20
    assert blocker not in eng.state.battlefield
    assert attacker in eng.state.battlefield
    assert attacker.damage_marked == 2


def test_blockers_can_gang_up_and_trade():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=4, toughness=4))
    b1 = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    b2 = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    eng.declare_blockers(
        p2,
        [{"blocker": b1, "attacker": attacker}, {"blocker": b2, "attacker": attacker}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 4 power split 2+2 kills both blockers; 4 toughness takes 4 → attacker dies too.
    assert b1 not in eng.state.battlefield
    assert b2 not in eng.state.battlefield
    assert attacker not in eng.state.battlefield


def test_attacking_player_cannot_declare_blockers():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2))
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p1")
    with pytest.raises(ValueError):
        # p1 is the attacker; it can't block its own attack.
        eng.declare_blockers(eng.state.active_player, [{"blocker": blocker, "attacker": attacker}])


def test_counters_annihilate_via_sba():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    frog = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2))
    frog.add_counters("+1/+1", 2)
    frog.add_counters("-1/-1", 1)
    eng.rules.check_state_based_actions()
    # 704.5q removes one of each → net +1/+1; a 3/3 survivor.
    assert frog.counters == {"+1/+1": 1}
    assert frog.power == 3 and frog.toughness == 3


def test_minus_counters_can_be_lethal():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    frog = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2))
    frog.add_counters("-1/-1", 2)  # 0 toughness
    eng.rules.check_state_based_actions()
    assert frog not in eng.state.battlefield  # 704.5f


def test_commander_combat_damage_is_tracked_and_21_is_lethal():
    eng = make_engine([land()], [land()], life=40, hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    cmdr = obj_on_battlefield(eng.state, eng, creature(name="Cmdr", power=7, toughness=7))
    cmdr.is_commander = True
    p2 = eng.state.player_by_id("p2")
    # Three 7-damage swings = 21 commander damage → p2 loses to commander
    # damage while still at 19 life (nowhere near dead on life alone).
    for _ in range(3):
        cmdr.tapped = False
        # RULE 511.3: end the previous fake "combat" before starting the
        # next one — `declare_attackers` (2026-09-04 fix) now refuses to
        # redeclare a creature still marked `attacking` from an uncleared
        # combat, same as the real engine's own `_clear_combat` would have
        # done between two genuine combats.
        cmdr.attacking = False
        eng.state.current_step = "declare_attackers"
        eng.declare_attackers(eng.state.active_player, [cmdr])
        eng.state.current_step = "combat_damage"
        eng._step_combat_damage()
    entry = next(iter(p2.commander_damage.values()))
    assert entry["amount"] == 21 and entry["name"] == "Cmdr"
    assert p2.has_lost and p2.loss_reason == "commander_damage"


def test_noncombat_damage_is_not_commander_damage():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    cmdr = obj_on_battlefield(eng.state, eng, creature(name="Cmdr", power=3))
    cmdr.is_commander = True
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 5, source=cmdr, combat=False)  # a burn spell, say
    assert p2.commander_damage == {}
    assert p2.life == 15


def test_first_turn_draw_can_be_toggled():
    # Two players (so 103.7a applies); default skip, then opt onto the draw.
    eng = make_engine([land("Forest")] * 5, [land("Forest")] * 5, hand=0)
    eng.state.skip_first_draw = True
    eng.start()
    for _ in range(3):  # untap, upkeep, draw (skipped)
        eng.advance_step()
    assert len(eng.state.player_by_id("p1").hand) == 0

    eng2 = make_engine([land("Forest")] * 5, [land("Forest")] * 5, hand=0)
    eng2.state.skip_first_draw = False
    eng2.start()
    for _ in range(3):  # untap, upkeep, draw (happens)
        eng2.advance_step()
    assert len(eng2.state.player_by_id("p1").hand) == 1


def test_end_combat_removes_creatures_from_combat():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert eng.attackers == [bear]
    eng._step_end_combat()
    assert eng.attackers == []
    assert not bear.attacking and bear.combat_defender is None


# ---------------------------------------------------------------------------
# Goldfish (UC3)
# ---------------------------------------------------------------------------


def test_goldfish_plays_lands_and_attacks_over_several_turns():
    lib = [land("Forest")] * 20 + [creature()] + [land("Forest")] * 6
    eng = make_engine(lib, [land("Forest")] * 40, life=20, hand=7)
    for _ in range(6):
        if eng.state.game_over:
            break
        eng.run_goldfish_turn()
    # The bear is drawn early, cast, and eventually swings for 2.
    creatures = [o.name for o in eng.state.battlefield if o.is_creature]
    assert "Grizzly Bears" in creatures
    assert eng.state.player_by_id("p2").life < 20


def test_rules_engine_can_be_constructed_standalone():
    state = GameState(players=[Player(id="p1")])
    engine = RulesEngine(state)
    assert engine.state is state


# ---------------------------------------------------------------------------
# Library search (RULE 701.19) + the pending-choice mechanism
# ---------------------------------------------------------------------------


def test_search_opens_a_choice_then_moves_the_chosen_card():
    lib = [land("Forest"), creature("Bear A"), land("Forest"), creature("Bear B")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player

    eng.rules._request_search(p1, "Creature", "hand")
    choice = eng.state.pending_choice
    assert choice["kind"] == "search"
    assert {e["name"] for e in choice["eligible"]} == {"Bear A", "Bear B"}

    chosen = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    assert eng.state.pending_choice is None
    assert any(o.instance_id == chosen for o in p1.hand)
    assert len(p1.library) == 3  # one card left the library


def test_search_with_no_match_just_shuffles_no_choice():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand")  # no creatures in library
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_search_can_be_declined():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand")
    eng.rules.resolve_choice(None)  # decline
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_resolve_until_stable_stops_on_pending_choice():
    from mtg_analyzer.game.effects.core import SearchLibraryEffect
    from mtg_analyzer.models.game.game_state import StackItem

    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    ability = SearchLibraryEffect(type_restriction="Creature", player=p1)
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[ability]))

    eng.resolve_until_stable()
    # Resolving the ability opened a search — the loop paused for the choice.
    assert eng.state.pending_choice is not None
    assert not eng.state.stack


# -- Parameterized criteria (search "what") ---------------------------------


def test_search_for_a_basic_land():
    lib = [creature("Bear"), land("Forest"), land("Island", produces="Island")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Forest", "Island"}


def test_search_for_a_subtype_or_list_like_farseek():
    lib = [land("Forest"), land("Island", produces="Island"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"type": ["Plains", "Island"]}, "battlefield_tapped")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Island"}  # only the Island subtype matches


def test_search_for_any_card():
    lib = [land("Forest"), creature("Bear"), instant("Shock")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "", "hand")  # "search for a card"
    assert len(eng.state.pending_choice["eligible"]) == 3


def test_search_bounded_by_mana_value():
    lib = [creature("Bear", cost="{1}{G}"), creature("Dragon", cost="{4}{R}{R}")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"type": "Creature", "max_mana_value": 3}, "battlefield")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Bear"}


# -- Destinations (search "where") ------------------------------------------


def _search_one(eng, player, criteria, destination):
    eng.rules._request_search(player, criteria, destination)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    return chosen


def test_search_to_battlefield_tapped():
    eng = make_engine([land("Forest")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, {"basic": True}, "battlefield_tapped")
    obj = eng.state.find_object(chosen)
    assert obj in eng.state.battlefield and obj.tapped


def test_search_to_top_of_library_shuffles_first_then_places():
    lib = [land("Forest"), land("Forest"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "library_top")
    assert p1.library[-1].instance_id == chosen  # end of list == top of deck
    assert len(p1.library) == 3


def test_search_to_bottom_of_library():
    lib = [land("Forest"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "library_bottom")
    assert p1.library[0].instance_id == chosen  # index 0 == bottom


def test_search_to_graveyard_like_entomb():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "graveyard")
    assert any(o.instance_id == chosen for o in p1.graveyard)


def test_search_to_exile():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "exile")
    assert any(o.instance_id == chosen for o in p1.exile)


# -- Count: search for up to N, one pick at a time --------------------------


def test_search_for_up_to_two_cards_reopens_the_choice():
    lib = [land("Forest"), land("Island", produces="Island"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand", count=2)

    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(first)
    # Still one to go: the choice re-opened, excluding the first pick.
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["remaining"] == 1
    assert first not in {e["instance_id"] for e in eng.state.pending_choice["eligible"]}

    second = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(second)
    assert eng.state.pending_choice is None
    hand_ids = {o.instance_id for o in p1.hand}
    assert {first, second} <= hand_ids


def test_up_to_n_can_stop_early_by_declining():
    lib = [land("Forest"), land("Island", produces="Island")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand", count=2)
    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(first)
    eng.rules.resolve_choice(None)  # stop after one
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 1


def test_search_reopen_stops_when_library_exhausted():
    eng = make_engine([creature("Bear")], hand=0)  # only one match
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand", count=3)
    only = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(only)
    # No further eligible cards, so the search finishes rather than looping.
    assert eng.state.pending_choice is None
    assert any(o.instance_id == only for o in p1.hand)


# -- Shuffle as a first-class, announced action -----------------------------


def test_shuffle_library_fires_a_shuffle_event():
    eng = make_engine([land("Forest")] * 5, hand=0)
    p1 = eng.state.active_player
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.type))
    eng.rules.shuffle_library(p1)
    assert EventType.SHUFFLE in seen


def test_search_announces_and_shuffles():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.type))
    eng.rules._request_search(p1, "Creature", "hand")  # nothing matches
    assert EventType.LIBRARY_SEARCHED in seen
    assert EventType.SHUFFLE in seen  # a failed search still shuffles


# ---------------------------------------------------------------------------
# Gain life / counter (RULE 119 / 701.5)
# ---------------------------------------------------------------------------


def test_gain_life_effect():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    before = p1.life
    eng.rules.gain_life(p1, 5)
    assert p1.life == before + 5


def test_counter_spell_removes_it_from_the_stack():
    from mtg_analyzer.models.game.game_state import StackItem

    eng = make_engine([land()], hand=0)
    bear = GameObject(creature(), owner_id="p1", zone=Zone.STACK)
    item = StackItem(kind="spell", controller_id="p1", obj=bear, description="Grizzly Bears")
    eng.state.stack.append(item)

    eng.rules.counter_spell(bear)
    assert item not in eng.state.stack
    assert bear in eng.state.player_by_id("p1").graveyard


# ---------------------------------------------------------------------------
# Stack interaction (RULE 608): cast leaves it on the stack; pass resolves one
# ---------------------------------------------------------------------------


def test_pass_priority_resolves_one_stack_object_at_a_time():
    from mtg_analyzer.models.game.game_state import StackItem
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))

    assert eng.pass_priority() is True  # resolves the top one
    assert len(eng.state.stack) == 1
    assert eng.pass_priority() is True
    assert len(eng.state.stack) == 0
    assert eng.pass_priority() is False  # nothing left


# ---------------------------------------------------------------------------
# Combat & evasion keywords (RULE 702.* / 509 / 510)
# ---------------------------------------------------------------------------

from mtg_analyzer.game import combat


def _combat_creature(name="Fighter", power=2, toughness=2, controller="p1", **kw):
    """A non-summoning-sick creature already in play, for combat tests."""
    return name, power, toughness, controller, kw


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# -- Recognition -------------------------------------------------------------


def test_recognizes_keywords_from_scryfall_list():
    card = creature(keywords=["Flying", "First strike", "Trample"])
    assert combat.keywords_of(card) == {"flying", "first_strike", "trample"}


def test_recognizes_keywords_from_oracle_text_clause():
    card = creature(oracle_text="Vigilance, lifelink\nDeathtouch")
    assert {"vigilance", "lifelink", "deathtouch"} <= combat.keywords_of(card)


def test_granting_a_keyword_is_not_a_false_positive():
    # "gains flying" is an *effect*, not the card having flying itself.
    card = creature(oracle_text="Target creature gains flying until end of turn.")
    assert "flying" not in combat.keywords_of(card)


def test_recognizes_protection_qualities():
    card = creature(oracle_text="Protection from red\nProtection from creatures")
    assert combat.protections_of(card) == {"R", "creatures"}
    assert "protection" in combat.keywords_of(card)


def test_display_keywords_expands_protection():
    card = creature(keywords=["Flying"], oracle_text="Protection from black")
    labels = combat.display_keywords(card)
    assert "Flying" in labels
    assert "Protection: B" in labels


def test_station_bracket_keyword_does_not_leak_unconditionally():
    # RULE 721.2a: "8+ | Flying, deathtouch" only grants those keywords at
    # 8+ charge counters (via the layer-6 grant `catalogue.station` feeds
    # `continuous.recompute`) — `keywords_of` must not also treat the
    # bracket line as unconditional text, the same leak `is_leveler`
    # already guards against for "LEVEL 7+" blocks. Regression test for a
    # real bug found live on Entropic Battlecruiser: "deathtouch" (comma-
    # anchored right after "8+ | ") matched the oracle-text fallback
    # unconditionally before `station_base_text` existed.
    card = creature(
        type_line="Artifact — Spacecraft",
        keywords=["Station"],
        oracle_text=(
            "Station (Tap another creature you control: Put charge counters "
            "equal to its power on this Spacecraft. Station only as a "
            "sorcery. It's an artifact creature at 8+.)\n"
            "1+ | Whenever an opponent discards a card, they lose 3 life.\n"
            "8+ | Flying, deathtouch\n"
            "Whenever this Spacecraft attacks, each opponent discards a card."
        ),
    )
    assert combat.keywords_of(card) == frozenset()


def test_station_unconditional_line_after_brackets_still_recognized():
    # RULE 721.4 allows an ordinary (bracket-less) line *after* the tier
    # brackets too — unlike Leveler's strict preamble-only shape. A real
    # unconditional keyword printed there must still be found, so the fix
    # above must filter bracket lines rather than truncate at the first one.
    card = creature(
        type_line="Artifact — Spacecraft",
        keywords=["Station"],
        oracle_text=(
            "Station (Tap another creature you control: Put charge counters "
            "equal to its power on this Spacecraft. Station only as a "
            "sorcery.)\n"
            "1+ | Flying\n"
            "Vigilance"
        ),
    )
    assert combat.keywords_of(card) == {"vigilance"}


def test_recognizes_multiple_protections_joined_by_and_from():
    # Official templating for a multi-quality protection repeats "from" per
    # quality (the Sword-of-X-and-Y equipment cycle: "Protection from red
    # and from blue"), rather than a bare "and".
    card = creature(oracle_text="Protection from red and from blue")
    assert combat.protections_of(card) == {"R", "U"}


def test_recognizes_protection_from_card_type():
    card = creature(oracle_text="Protection from artifacts")
    assert combat.protections_of(card) == {"artifacts"}


def test_protection_from_card_type_stops_damage_from_that_type():
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from artifacts")
    )
    artifact_source = obj_on_battlefield(
        eng.state,
        eng,
        Card(id="Blaster", name="Blaster", type_line="Artifact Creature — Golem",
             is_creature=True, power=3, toughness=3),
        controller="p2",
    )
    eng.rules.deal_damage(target, 3, source=artifact_source)
    assert target.damage_marked == 0


def test_protection_from_creature_type_stops_damage_from_that_type():
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from Dragons")
    )
    dragon = obj_on_battlefield(
        eng.state,
        eng,
        creature(name="Dragon", type_line="Creature — Dragon", power=5, toughness=5),
        controller="p2",
    )
    eng.rules.deal_damage(target, 5, source=dragon)
    assert target.damage_marked == 0


def test_noncombat_damage_prevented_by_protection():
    # RULE 702.16c: protection prevents *all* damage from a source of the
    # stated quality, not just combat damage — a burn spell fizzles too.
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from red")
    )
    red_source = obj_on_battlefield(
        eng.state,
        eng,
        Card(
            id="Bolt",
            name="Bolt",
            type_line="Instant",
            mana_cost_string="{R}",
            converted_mana_cost=1,
            is_instant=True,
            color_identity={"R"},
        ),
        controller="p2",
    )
    eng.rules.deal_damage(target, 5, source=red_source)
    assert target.damage_marked == 0


def test_equipment_target_options_exclude_protected_creature():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    protected_host = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from artifacts")
    )

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert protected_host.instance_id not in option_ids


# -- Attacking ---------------------------------------------------------------


def test_vigilance_attacker_does_not_tap():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    bear = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Vigilance"]))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.attacking and not bear.tapped


def test_haste_creature_can_attack_when_summoning_sick():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    hasty = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Haste"]))
    hasty.summoning_sick = True
    eng.declare_attackers(eng.state.active_player, [hasty])  # no raise
    assert hasty.attacking


def test_defender_cannot_attack():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=4, keywords=["Defender"]))
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [wall])


# -- Blocking evasion --------------------------------------------------------


def _attack_then_blockers_step(eng, attacker):
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    return eng.state.player_by_id("p2")


def test_flyer_cannot_be_blocked_by_ground_creature():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    flyer = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Flying"]))
    ground = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, flyer)
    assert not eng.can_block(p2, ground, flyer)
    with pytest.raises(ValueError):
        eng.declare_blockers(p2, [{"blocker": ground, "attacker": flyer}])


def test_flyer_can_be_blocked_by_flyer_or_reach():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    flyer = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Flying"]))
    other_flyer = obj_on_battlefield(eng.state, eng, creature(keywords=["Flying"]), controller="p2")
    spider = obj_on_battlefield(eng.state, eng, creature(keywords=["Reach"]), controller="p2")
    p2 = _attack_then_blockers_step(eng, flyer)
    assert eng.can_block(p2, other_flyer, flyer)
    assert eng.can_block(p2, spider, flyer)


def test_protection_from_color_stops_that_color_blocking():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, oracle_text="Protection from red")
    )
    red_blocker = obj_on_battlefield(
        eng.state, eng, creature(color_identity={"R"}), controller="p2"
    )
    white_blocker = obj_on_battlefield(
        eng.state, eng, creature(color_identity={"W"}), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, attacker)
    assert not eng.can_block(p2, red_blocker, attacker)
    assert eng.can_block(p2, white_blocker, attacker)


def test_islandwalk_is_unblockable_while_defender_controls_an_island():
    # RULE 702.14b: an islandwalker can't be blocked while the defending
    # player controls an Island.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    walker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Islandwalk"]))
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    obj_on_battlefield(eng.state, eng, land(produces="Island"), controller="p2")
    p2 = _attack_then_blockers_step(eng, walker)
    assert not eng.can_block(p2, blocker, walker)
    with pytest.raises(ValueError):
        eng.declare_blockers(p2, [{"blocker": blocker, "attacker": walker}])


def test_islandwalk_is_blockable_when_defender_has_no_island():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    walker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Islandwalk"]))
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    obj_on_battlefield(eng.state, eng, land(produces="Forest"), controller="p2")
    p2 = _attack_then_blockers_step(eng, walker)
    assert eng.can_block(p2, blocker, walker)


def test_menace_requires_two_blockers():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    menacer = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Menace"]))
    b1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    b2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    eng.declare_attackers(eng.state.active_player, [menacer])
    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    with pytest.raises(ValueError):  # a single blocker is illegal
        eng.declare_blockers(p2, [{"blocker": b1, "attacker": menacer}])
    assert menacer.blocked_by == []  # nothing mutated on the failed attempt
    eng.declare_blockers(
        p2,
        [{"blocker": b1, "attacker": menacer}, {"blocker": b2, "attacker": menacer}],
    )
    assert set(menacer.blocked_by) == {b1.instance_id, b2.instance_id}


# -- Damage keywords ---------------------------------------------------------


def test_first_strike_kills_blocker_before_it_strikes_back():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, toughness=2, keywords=["First strike"])
    )
    blocker = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # First strike deals 2 first → the 2/2 blocker dies before it can hit back.
    assert blocker not in eng.state.battlefield
    assert attacker in eng.state.battlefield
    assert attacker.damage_marked == 0


def test_double_strike_deals_damage_twice():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, toughness=2, keywords=["Double strike"])
    )
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # An unblocked 2-power double striker deals 2 + 2 = 4 to the opponent.
    assert eng.state.player_by_id("p2").life == 16


def test_deathtouch_makes_any_damage_lethal():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    deathtoucher = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Deathtouch"])
    )
    big = obj_on_battlefield(eng.state, eng, creature(power=1, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, deathtoucher)
    eng.declare_blockers(p2, [{"blocker": big, "attacker": deathtoucher}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert big not in eng.state.battlefield  # 1 deathtouch damage was lethal


def test_trample_spills_excess_onto_defender():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    trampler = obj_on_battlefield(
        eng.state, eng, creature(power=5, toughness=5, keywords=["Trample"])
    )
    chump = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=2), controller="p2")
    p2 = _attack_then_blockers_step(eng, trampler)
    eng.declare_blockers(p2, [{"blocker": chump, "attacker": trampler}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 2 lethal to the 0/2 chump, 3 tramples over to the player.
    assert chump not in eng.state.battlefield
    assert eng.state.player_by_id("p2").life == 17


def test_deathtouch_trample_assigns_one_then_tramples():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=5, toughness=5, keywords=["Trample", "Deathtouch"])
    )
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=4), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # Deathtouch → 1 damage is lethal, so only 1 need go to the wall; 4 tramples.
    assert wall not in eng.state.battlefield
    assert eng.state.player_by_id("p2").life == 16


def test_lifelink_gains_life_on_combat_damage():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Lifelink"]))
    p1 = eng.state.active_player
    start = p1.life
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p2").life == 17
    assert p1.life == start + 3  # controller gained life equal to damage dealt


def test_infect_combat_damage_to_player_is_poison_not_life_loss():
    # RULE 702.90c: an infect source's combat damage to a player becomes
    # poison counters, with no life loss at all.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Infect"]))
    p1 = eng.state.active_player
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    p2 = eng.state.player_by_id("p2")
    assert p2.poison == 3
    assert p2.life == 20


def test_infect_combat_damage_to_creature_is_minus_counters_not_marked():
    # RULE 702.90b: an infect source's damage to a creature is -1/-1
    # counters, not marked damage (so it isn't cleared at cleanup — it's a
    # permanent P/T reduction, unlike ordinary combat damage).
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Infect"]))
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert wall.damage_marked == 0
    assert wall.counters.get("-1/-1") == 2


def test_wither_damage_to_creature_is_minus_counters_but_player_still_loses_life():
    # RULE 702.91a: wither is the creature-only half of infect's damage
    # substitution — a wither source's damage to a *player* is ordinary
    # life loss.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Wither"]))
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert wall.damage_marked == 0
    assert wall.counters.get("-1/-1") == 2

    eng2 = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng2)
    attacker2 = obj_on_battlefield(eng2.state, eng2, creature(power=3, keywords=["Wither"]))
    p1 = eng2.state.active_player
    eng2.declare_attackers(p1, [attacker2])
    eng2.state.current_step = "combat_damage"
    eng2._step_combat_damage()
    p2b = eng2.state.player_by_id("p2")
    assert p2b.poison == 0
    assert p2b.life == 17


def _goblin_guide_card():
    return Card(
        id="Goblin Guide", name="Goblin Guide", type_line="Creature — Goblin Scout",
        is_creature=True, power=2, toughness=2, mana_cost_string="{R}",
        converted_mana_cost=1, keywords=["Haste"],
        oracle_text="Haste\nWhenever this creature attacks, defending player "
                     "reveals the top card of their library. If it's a land "
                     "card, that player puts it into their hand.",
    )


def test_goblin_guide_puts_a_revealed_land_into_the_defenders_hand():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    guide = obj_on_battlefield(eng.state, eng, _goblin_guide_card())
    bind_from_catalogue(guide)
    p2 = eng.state.player_by_id("p2")
    top_land = land("Island")
    top_land_obj = GameObject(top_land, owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top_land_obj)  # top of deck is the list end
    hand_before = len(p2.hand)

    eng.declare_attackers(eng.state.active_player, [guide])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert top_land_obj in p2.hand
    assert top_land_obj not in p2.library
    assert len(p2.hand) == hand_before + 1


def test_goblin_guide_leaves_a_revealed_nonland_card_on_top():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    guide = obj_on_battlefield(eng.state, eng, _goblin_guide_card())
    bind_from_catalogue(guide)
    p2 = eng.state.player_by_id("p2")
    top_spell = creature(name="Not A Land")
    top_spell_obj = GameObject(top_spell, owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top_spell_obj)
    library_count_before = len(p2.library)

    eng.declare_attackers(eng.state.active_player, [guide])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert top_spell_obj in p2.library
    assert top_spell_obj not in p2.hand
    assert len(p2.library) == library_count_before


def test_protection_prevents_combat_damage():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=3, toughness=3, oracle_text="Protection from red")
    )
    # A red blocker: it can't block (protection), so force the reverse — a red
    # attacker blocked by our protected creature to check damage prevention.
    eng2 = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng2)
    red_attacker = obj_on_battlefield(
        eng2.state, eng2, creature(power=3, toughness=3, color_identity={"R"})
    )
    protector = obj_on_battlefield(
        eng2.state,
        eng2,
        creature(power=1, toughness=3, oracle_text="Protection from red"),
        controller="p2",
    )
    eng2.declare_attackers(eng2.state.active_player, [red_attacker])
    eng2.state.current_step = "declare_blockers"
    p2 = eng2.state.player_by_id("p2")
    eng2.declare_blockers(p2, [{"blocker": protector, "attacker": red_attacker}])
    eng2.state.current_step = "combat_damage"
    eng2._step_combat_damage()
    # The red attacker's damage to the protected blocker is prevented; the
    # blocker still deals its 1 back.
    assert protector in eng2.state.battlefield
    assert protector.damage_marked == 0
    assert red_attacker.damage_marked == 1


def test_indestructible_survives_lethal_and_deathtouch():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    tough = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Indestructible"])
    )
    killer = obj_on_battlefield(
        eng.state, eng, creature(power=6, toughness=1, keywords=["Deathtouch"]), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, tough)
    eng.declare_blockers(p2, [{"blocker": killer, "attacker": tough}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 6 damage from a deathtouch source, but indestructible → it survives.
    assert tough in eng.state.battlefield


def test_deathtouch_flag_cleared_at_end_of_combat():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    survivor = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Indestructible"])
    )
    dt = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Deathtouch"]), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, survivor)
    eng.declare_blockers(p2, [{"blocker": dt, "attacker": survivor}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert survivor.dealt_deathtouch_damage is True  # marked during combat
    eng._step_end_combat()
    assert survivor.dealt_deathtouch_damage is False  # cleared when combat ends


# -- Combat-math keywords (RULE 702.86/702.130/702.45) + hexproof (702.11) --

from mtg_analyzer.game.targeting import TargetSpec, legal_targets


def test_annihilator_makes_defending_player_sacrifice_permanents():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Annihilator"],
            oracle_text="Annihilator 2 (Whenever this creature attacks, "
            "defending player sacrifices two permanents.)",
        ),
    )
    bind_from_catalogue(attacker)
    for _ in range(3):
        obj_on_battlefield(eng.state, eng, creature(), controller="p2")

    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.resolve_until_stable()

    # RULE 601.2c-style choice (ENG-2): three permanents, only two must be
    # sacrificed, so the defending player picks rather than the engine
    # auto-choosing.
    choice = eng.state.pending_choice
    assert choice is not None and choice["action"] == "sacrifice"
    first_pick = choice["options"][0]["instance_id"]
    eng.rules.resolve_choice(first_pick)
    assert eng.state.pending_choice is not None  # one more to pick
    second_pick = eng.state.pending_choice["options"][0]["instance_id"]
    eng.rules.resolve_choice(second_pick)
    eng.resolve_until_stable()

    remaining = [o for o in eng.state.battlefield if o.controller_id == "p2"]
    assert len(remaining) == 1


def test_afflict_causes_defending_player_to_lose_life_on_block():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Afflict"],
            oracle_text="Afflict 3 (Whenever this creature becomes blocked, "
            "defending player loses 3 life.)",
        ),
    )
    bind_from_catalogue(attacker)
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert eng.state.player_by_id("p2").life == 17


def test_bushido_pumps_the_blocker_when_it_blocks():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=3))
    blocker = obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=1,
            toughness=1,
            keywords=["Bushido"],
            oracle_text="Bushido 1 (Whenever this creature blocks or becomes "
            "blocked, it gets +1/+1 until end of turn.)",
        ),
        controller="p2",
    )
    bind_from_catalogue(blocker)
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert blocker.power == 2
    assert blocker.toughness == 2


def _rampage_attacker(eng, n=2):
    return obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Rampage"],
            oracle_text=f"Rampage {n} (Whenever this creature becomes blocked, it gets "
            f"+{n}/+{n} until end of turn for each creature blocking it beyond the first.)",
        ),
    )


def test_rampage_does_not_trigger_with_only_one_blocker():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng)
    bind_from_catalogue(attacker)
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.resolve_until_stable()

    assert attacker.power == 2  # "beyond the first" — a single blocker adds nothing
    assert attacker.toughness == 2


def test_rampage_pumps_once_per_blocker_beyond_the_first():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng, n=2)
    bind_from_catalogue(attacker)
    blocker1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker3 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(
        p2,
        [
            {"blocker": blocker1, "attacker": attacker},
            {"blocker": blocker2, "attacker": attacker},
            {"blocker": blocker3, "attacker": attacker},
        ],
    )
    eng.resolve_until_stable()

    # Three blockers, two "beyond the first" — +2/+2 twice.
    assert attacker.power == 6
    assert attacker.toughness == 6


def test_rampage_goes_on_the_stack_as_a_real_triggered_ability():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = _rampage_attacker(eng)
    bind_from_catalogue(attacker)
    blocker1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    blocker2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(
        p2,
        [
            {"blocker": blocker1, "attacker": attacker},
            {"blocker": blocker2, "attacker": attacker},
        ],
    )

    assert len(eng.state.stack) == 1  # a real stack object, not an inline effect
    top = eng.state.stack[-1]
    assert top.controller_id == "p1"  # RULE 603.3a: the attacker's own controller
    assert attacker.power == 2  # not yet resolved

    eng.resolve_until_stable()
    assert attacker.power == 4


def test_hexproof_creature_cannot_be_targeted_by_an_opponent():
    eng = make_engine([land()], [land()], hand=0)
    hex_creature = obj_on_battlefield(
        eng.state, eng, creature(keywords=["Hexproof"]), controller="p2"
    )
    bind_from_catalogue(hex_creature)
    plain = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    opponent_source = obj_on_battlefield(eng.state, eng, creature(), controller="p1")

    spec = TargetSpec(kind="creature")
    options = legal_targets(eng.state, "p1", spec, source=opponent_source)
    ids = {o["instance_id"] for o in options}
    assert hex_creature.instance_id not in ids
    assert plain.instance_id in ids

    # Hexproof doesn't stop the controller's own spells/abilities.
    own_source = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    own_options = legal_targets(eng.state, "p2", spec, source=own_source)
    assert hex_creature.instance_id in {o["instance_id"] for o in own_options}


# -- Ward (RULE 702.21) ------------------------------------------------------


def _shock_spell(p1):
    """A hand `GameObject` for a bare "deal 3 damage to target creature" instant."""
    from mtg_analyzer.game.effects.core import DealDamageEffect

    card = Card(
        id="Shock",
        name="Shock",
        type_line="Instant",
        mana_cost_string="{R}",
        converted_mana_cost=1,
        is_instant=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]
    return spell


def test_ward_pushes_a_real_stack_item_above_the_spell():
    # RULE 603.3: ward is a triggered ability that becomes its own object on
    # the stack — not an inline choice — so both players get a normal
    # priority window to respond to it before it resolves.
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])

    assert eng.state.pending_choice is None  # nothing resolved yet
    assert len(eng.state.stack) == 2
    assert eng.state.stack[0].obj is spell  # the spell sits underneath
    top = eng.state.stack[1]
    assert top.category == "triggered_ability"
    assert top.controller_id == "p2"  # RULE 603.3a: the warded permanent's controller
    assert "Ward" in top.description


def test_ward_paid_lets_the_spell_resolve():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # resolves the ward ability, opening its choice
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"
    assert choice["player_id"] == "p1"  # the caster decides, not p2

    eng.resolve_pending_choice("pay")
    assert warded not in eng.state.battlefield  # 3 damage killed the 2/2
    assert p1.mana_pool.total() == 0  # the {2} ward cost was paid too


def test_ward_declined_counters_the_spell():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")

    assert warded in eng.state.battlefield  # never took the damage
    assert warded.damage_marked == 0
    assert not eng.state.stack  # the spell was countered, not resolved
    assert spell in p1.graveyard


def test_ward_uncastable_cost_counters_the_spell_without_a_choice():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})  # nothing left over for ward's {2}
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # no real decision — the ward ability auto-counters

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_does_not_trigger_against_its_own_controller():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p1")
    warded.parametric_keywords = {"ward": {"cost": "{2}"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])

    assert len(eng.state.stack) == 1  # no ward ability was pushed at all
    eng.resolve_until_stable()
    assert warded not in eng.state.battlefield  # the spell resolved normally


def test_ward_triggers_on_a_targeted_activated_ability():
    from mtg_analyzer.game.costs import parse_activation_cost
    from mtg_analyzer.game.effects.core import ActivatedAbility, DealDamageEffect

    eng = make_engine([land()], [], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "{1}"}}
    source = obj_on_battlefield(eng.state, eng, creature(name="Zapper", cost="{1}"))
    source.summoning_sick = False
    source.activated_abilities.append(
        ActivatedAbility(
            effects=[DealDamageEffect(amount=3, target_kind="creature")],
            cost=parse_activation_cost("{T}:"),
            source=source,
        )
    )
    p1.mana_pool.add_many({"C": 1})

    eng.activate_ability(p1, source, 0, targets=[warded])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("decline")
    assert warded in eng.state.battlefield
    assert not eng.state.stack


def test_ward_pay_life_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    start_life = p1.life
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Pay 3 life"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("pay")
    assert p1.life == start_life - 3
    assert warded not in eng.state.battlefield  # the spell went on to resolve


def test_ward_x_cost_selector_is_recognized_from_the_where_x_is_clause():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("Pay {X}, where X is the number of creatures you control.")
    assert cost.mana.has_variable
    assert cost.x_selector == "creatures_you_control"


def test_ward_x_cost_unrecognized_selector_leaves_x_unset():
    # RULE 107.3c fallback: an unrecognized "where X is …" phrase (no real
    # card uses this vocabulary word) leaves `x_selector` unset rather than
    # guessed — X then stays 0 at resolution time.
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("Pay {X}, where X is the number of Zombies you control.")
    assert cost.mana.has_variable
    assert cost.x_selector is None


def test_ward_x_cost_resolves_against_the_board_at_resolution_time_not_trigger_time():
    # RULE 702.21b: "This value is determined at the time the ability
    # resolves, not locked in as the ability triggers" — p2 gains a second
    # creature *after* the ward ability is placed on the stack but *before*
    # it resolves; X must reflect the board at resolution (2), not however
    # many creatures p2 controlled when the spell was cast (1).
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 2})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {
        "ward": {"cost": "Pay {X}, where X is the number of creatures you control."}
    }
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    assert len(eng.state.stack) == 2  # the ward ability sits on top of the spell

    obj_on_battlefield(eng.state, eng, creature(power=1, toughness=1), controller="p2")

    eng.rules.resolve_top_of_stack()  # resolves the ward ability itself
    choice = eng.state.pending_choice
    assert choice["kind"] == "ward"

    eng.resolve_pending_choice("pay")
    assert p1.mana_pool.total() == 0  # {R} for Shock + {2} generic for X=2


def test_ward_x_cost_uncastable_counters_the_spell_without_a_choice():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})  # nothing left over for ward's X
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {
        "ward": {"cost": "Pay {X}, where X is the number of creatures you control."}
    }
    obj_on_battlefield(eng.state, eng, creature(power=1, toughness=1), controller="p2")
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()  # no real decision — X=1 isn't payable, auto-countered

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_discard_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    filler = GameObject(creature(name="Filler"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(filler, Zone.HAND)
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Discard a card"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    hand_before_discard = len(p1.hand)  # the spell itself already left the hand
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay")

    assert len(p1.hand) == hand_before_discard - 1
    assert filler in p1.graveyard
    assert warded not in eng.state.battlefield


def test_ward_sacrifice_cost():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    fodder = obj_on_battlefield(eng.state, eng, creature(name="Fodder"))
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Sacrifice a creature"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay")

    assert fodder not in eng.state.battlefield
    assert warded not in eng.state.battlefield


def test_ward_sacrifice_cost_unpayable_counters_without_a_choice():
    # p1 controls no creature at all, so "Sacrifice a creature" can't be paid.
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})
    warded = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    warded.parametric_keywords = {"ward": {"cost": "Sacrifice a creature"}}
    spell = _shock_spell(p1)

    eng.cast_spell(p1, spell, targets=[warded])
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert warded in eng.state.battlefield


def test_ward_two_simultaneous_wards_each_ask_in_turn():
    # RULE 702.21c: an item targeting two warded permanents triggers two
    # independent ward abilities, each its own stack object, asked one at a
    # time as the stack resolves. Built via `RulesEngine.cast_spell` directly
    # with two targets so `check_ward` sees both, independent of whether the
    # spell's own one-shot effect happens to read more than `targets[0]`.
    from mtg_analyzer.game.effects.core import DealDamageEffect

    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    a = obj_on_battlefield(eng.state, eng, creature(name="A", power=2, toughness=2), controller="p2")
    a.parametric_keywords = {"ward": {"cost": "{1}"}}
    b = obj_on_battlefield(eng.state, eng, creature(name="B", power=2, toughness=2), controller="p2")
    b.parametric_keywords = {"ward": {"cost": "{2}"}}
    card = Card(
        id="Fake Bolt", name="Fake Bolt", type_line="Sorcery",
        mana_cost_string="{R}", converted_mana_cost=1, is_sorcery=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]

    eng.rules.cast_spell(p1, spell, targets=[a, b])
    assert len(eng.state.stack) == 3  # the spell + a's ward + b's ward

    eng.resolve_until_stable()
    first = eng.state.pending_choice
    assert first["kind"] == "ward"
    eng.resolve_pending_choice("pay")

    second = eng.state.pending_choice
    assert second["kind"] == "ward"
    assert second is not first
    eng.resolve_pending_choice("pay")

    assert not eng.state.stack  # both wards paid — the spell resolved
    assert a not in eng.state.battlefield  # took the 3 damage (targets[0])
    assert b in eng.state.battlefield  # ward paid, but never actually damaged


def test_ward_one_of_two_simultaneous_wards_declined_counters_the_spell():
    # RULE 702.21c/608.2b: once the spell is countered by the first ward,
    # the second ward's own resolution finds nothing left to counter and
    # simply does nothing — it never asks the caster to pay again.
    from mtg_analyzer.game.effects.core import DealDamageEffect

    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    a = obj_on_battlefield(eng.state, eng, creature(name="A", power=2, toughness=2), controller="p2")
    a.parametric_keywords = {"ward": {"cost": "{1}"}}
    b = obj_on_battlefield(eng.state, eng, creature(name="B", power=2, toughness=2), controller="p2")
    b.parametric_keywords = {"ward": {"cost": "{2}"}}
    card = Card(
        id="Fake Bolt", name="Fake Bolt", type_line="Sorcery",
        mana_cost_string="{R}", converted_mana_cost=1, is_sorcery=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]

    eng.rules.cast_spell(p1, spell, targets=[a, b])
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "ward"
    eng.resolve_pending_choice("decline")  # counters the spell right away

    assert not eng.state.stack  # the second ward found nothing to counter
    assert eng.state.pending_choice is None
    assert a in eng.state.battlefield
    assert b in eng.state.battlefield
    assert spell in p1.graveyard


# ---------------------------------------------------------------------------
# Activated abilities & costs (RULE 602)
# ---------------------------------------------------------------------------

from mtg_analyzer.game.costs import ActivationCost, parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility


def _with_ability(eng, card, cost_text, effects, controller="p1"):
    """Put a permanent with one activated ability on the battlefield."""
    obj = obj_on_battlefield(eng.state, eng, card, controller=controller)
    ability = ActivatedAbility(
        effects=effects, cost=parse_activation_cost(cost_text), source=obj
    )
    obj.activated_abilities.append(ability)
    return obj, ability


def test_activate_pays_mana_and_taps_source_then_stacks():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()] * 3, hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{1}, {T}: Draw a card.", [DrawCardEffect(1, player=p1)])
    p1.mana_pool.add_many({"C": 1})
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert obj.tapped
    assert p1.mana_pool.total() == 0  # the {1} was paid
    assert len(eng.state.stack) == 1  # ability waits on the stack
    assert eng.state.stack[0].source is obj
    eng.resolve_until_stable()
    assert len(p1.hand) == 1  # it resolved and drew


def test_cannot_activate_without_mana():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()] * 3, hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{3}: Draw a card.", [DrawCardEffect(1, player=p1)])
    assert not eng.can_activate(p1, obj, ability)
    with pytest.raises(ValueError):
        eng.activate_ability(p1, obj)


def test_tap_ability_blocked_by_summoning_sickness():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)])
    obj.summoning_sick = True
    assert not eng.can_activate(p1, obj, ability)


def test_sacrifice_self_cost_sends_source_to_graveyard():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "Sacrifice ~: Draw a card.", [DrawCardEffect(1, player=p1)])
    eng.activate_ability(p1, obj)
    assert obj not in eng.state.battlefield  # sacrificed as a cost


def test_sacrifice_a_creature_cost_offers_a_choice_when_2plus_candidates():
    """RULE 602.1: "Sacrifice a creature" is a cost *choice*, not an engine
    auto-pick — `legal_actions` must offer every legal victim, and an
    explicit `sacrifice_choice` must be honoured over the first match."""
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    fodder_a = obj_on_battlefield(eng.state, eng, creature("Fodder A"), controller="p1")
    fodder_b = obj_on_battlefield(eng.state, eng, creature("Fodder B"), controller="p1")

    action = next(
        a for a in eng.legal_actions(p1) if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id
    )
    offered_ids = {o["instance_id"] for o in action["sacrifice_cost"]["options"]}
    # Every creature is a legal candidate, including the ability's own
    # source — no choice is silently narrowed to "not the source".
    assert offered_ids == {source.instance_id, fodder_a.instance_id, fodder_b.instance_id}

    eng.activate_ability(p1, source, sacrifice_choice=fodder_b.instance_id)
    assert fodder_b not in eng.state.battlefield
    assert fodder_a in eng.state.battlefield
    assert source in eng.state.battlefield


def test_sacrifice_a_creature_cost_auto_picks_when_no_choice_given():
    """Non-interactive callers (tests, the goldfish auto-player) keep working
    unchanged: omitting `sacrifice_choice` falls back to the first legal
    candidate, exactly as before this became a real choice."""
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    fodder = obj_on_battlefield(eng.state, eng, creature("Fodder"), controller="p1")
    eng.activate_ability(p1, source)
    assert source not in eng.state.battlefield  # first candidate, auto-picked
    assert fodder in eng.state.battlefield


def test_sacrifice_a_creature_cost_rejects_an_invalid_choice():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    source, ability = _with_ability(
        eng, creature("Altar"), "Sacrifice a creature: Draw a card.", [DrawCardEffect(1, player=p1)]
    )
    obj_on_battlefield(eng.state, eng, creature("Fodder"), controller="p1")
    with pytest.raises(ValueError):
        eng.activate_ability(p1, source, sacrifice_choice=999999)


def test_pay_life_cost_reduces_life():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    start = p1.life
    obj, ability = _with_ability(eng, creature(), "Pay 4 life: Draw a card.", [DrawCardEffect(1, player=p1)])
    eng.activate_ability(p1, obj)
    assert p1.life == start - 4


def test_untap_cost_requires_a_tapped_source():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(eng, creature(), "{Q}: Draw a card.", [DrawCardEffect(1, player=p1)])
    assert not eng.can_activate(p1, obj, ability)  # untapped → {Q} unpayable
    obj.tap()
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert not obj.tapped  # {Q} untapped it


def test_remove_counters_cost():
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj, ability = _with_ability(
        eng, creature(), "Remove two +1/+1 counters from ~: Draw.", [DrawCardEffect(1, player=p1)]
    )
    assert not eng.can_activate(p1, obj, ability)  # no counters yet
    obj.add_counters("+1/+1", 3)
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj)
    assert obj.counters.get("+1/+1") == 1  # two removed to pay the cost


def test_bound_activated_ability_carries_full_cost():
    from mtg_analyzer.game.binding.core import bind_ability
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    spec = AbilitySpec(
        "activated",
        [EffectSpec("draw", {"count": 1})],
        cost={"mana": "{2}", "taps_self": True, "text": "{2}, {T}, Pay 1 life"},
    )
    bound = bind_ability(spec)
    assert isinstance(bound, ActivatedAbility)
    assert bound.taps_source is True  # back-compat property still works
    assert bound.cost.mana.converted_mana_cost == 2
    assert bound.cost.pay_life == 1  # parsed from the cost text


def test_activated_attach_ability_attaches_to_target_on_resolution():
    from mtg_analyzer.game.effects.core import AttachEffect

    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    host.summoning_sick = False

    source = obj_on_battlefield(eng.state, eng, creature(name="Equipment", cost="{1}"))
    source.summoning_sick = False
    source.parametric_keywords = {"equip": {}}
    source.activated_abilities.append(
        ActivatedAbility(
            effects=[AttachEffect(target_kind="permanent")],
            cost=parse_activation_cost("{1}, {T}:"),
            source=source,
        )
    )

    p1.mana_pool.add_many({"C": 1})
    eng.activate_ability(p1, source, 0, targets=[host])
    eng.resolve_until_stable()

    assert source.attached_to == host.instance_id


# -- Kicker / Multikicker (RULE 702.33) --------------------------------------


def test_kicker_can_be_declined_and_pays_only_the_printed_cost():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 1})

    assert eng.can_cast(p1, spell)  # unkicked is always legal if affordable
    eng.cast_spell(p1, spell)

    assert p1.mana_pool.total() == 0
    assert eng.state.stack[-1].obj.kicker_count == 0


def test_kicker_paid_adds_its_own_cost_and_is_recorded():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 2, "C": 1})

    assert eng.can_cast(p1, spell, kicked=1)
    eng.cast_spell(p1, spell, kicked=1)

    assert p1.mana_pool.total() == 0  # {R} printed + {1}{R} kicker == RR + 1 generic
    assert eng.state.stack[-1].obj.kicker_count == 1


def test_kicker_cannot_be_paid_without_enough_mana():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}"}}
    p1.mana_pool.add_many({"R": 1})  # only enough for the printed cost

    assert not eng.can_cast(p1, spell, kicked=1)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, kicked=1)


def test_plain_kicker_rejects_paying_it_twice():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{R}"}}  # no "multi" flag
    p1.mana_pool.add_many({"R": 3})

    assert not eng.can_cast(p1, spell, kicked=2)


def test_multikicker_allows_paying_it_repeatedly():
    eng = make_engine([instant(name="Kicked Many", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{R}", "multi": True}}
    p1.mana_pool.add_many({"R": 4})  # {R} printed + 3x{R} multikicker

    assert eng.can_cast(p1, spell, kicked=3)
    eng.cast_spell(p1, spell, kicked=3)

    assert p1.mana_pool.total() == 0
    assert eng.state.stack[-1].obj.kicker_count == 3


def test_multikicker_keyword_parsing_marks_the_repeatable_flag():
    from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords

    card = Card(
        id="Rousing Read",
        name="Rousing Read",
        type_line="Sorcery",
        mana_cost_string="{2}{U}",
        converted_mana_cost=3,
        is_sorcery=True,
        keywords=["Multikicker"],
        oracle_text="Multikicker {1}\nDraw a card.",
    )
    specs = parse_keywords(card)
    assert len(specs) == 1
    assert specs[0].keyword == {"name": "kicker", "cost": "{1}", "multi": True}


def test_legal_actions_surfaces_kicker_offer():
    eng = make_engine([instant(name="Kicked One", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"kicker": {"cost": "{1}{R}", "multi": True}}
    p1.mana_pool.add_many({"R": 3, "C": 2})

    actions = eng.legal_actions(p1)
    cast_action = next(a for a in actions if a.get("type") == "cast_spell")
    assert cast_action["has_kicker"] is True
    assert cast_action["kicker_cost"] == "{1}{R}"
    assert cast_action["kicker_multi"] is True
    assert cast_action["max_kicker"] >= 1


def test_legal_actions_surfaces_a_distinct_bargain_cast_offer():
    eng = make_engine([instant(name="Bargaining Bolt", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.intrinsic_keywords.add("bargain")
    p1.mana_pool.add("R")
    obj_on_battlefield(
        eng.state, eng,
        Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure"),
    ).is_token = True

    casts = [
        action for action in eng.legal_actions(p1)
        if action["type"] == "cast_spell" and action["instance_id"] == spell.instance_id
    ]

    assert any(not action.get("bargained") for action in casts)
    assert any(action.get("bargained") for action in casts)


# -- Buyback (RULE 702.27) ----------------------------------------------------


def test_buyback_declined_resolves_to_the_graveyard_as_normal():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1})

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    assert spell in p1.graveyard
    assert spell not in p1.hand
    assert spell.buyback_paid is False


def test_buyback_paid_returns_the_spell_to_hand_instead_of_the_graveyard():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1, "U": 1, "C": 2})

    assert eng.can_cast(p1, spell, buyback=True)
    eng.cast_spell(p1, spell, buyback=True)
    assert p1.mana_pool.total() == 0  # {R} printed + {2}{U} buyback all spent

    eng.resolve_until_stable()

    assert spell in p1.hand
    assert spell not in p1.graveyard
    assert spell.buyback_paid is False  # cleared once consumed


def test_buyback_cannot_be_paid_without_enough_mana():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1})  # nothing left over for buyback

    assert not eng.can_cast(p1, spell, buyback=True)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, spell, buyback=True)


def test_buyback_rejected_on_a_spell_without_the_keyword():
    eng = make_engine([instant(name="Plain Spell", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    p1.mana_pool.add_many({"R": 5, "U": 5, "C": 5})

    assert not eng.can_cast(p1, spell, buyback=True)


def test_legal_actions_surfaces_buyback_offer():
    eng = make_engine([instant(name="Bought Back", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    spell.parametric_keywords = {"buyback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"R": 1, "U": 1, "C": 2})

    actions = eng.legal_actions(p1)
    cast_action = next(a for a in actions if a.get("type") == "cast_spell")
    assert cast_action["has_buyback"] is True
    assert cast_action["buyback_cost"] == "{2}{U}"
    assert cast_action["buyback_affordable"] is True


# -- Flashback (RULE 702.34) --------------------------------------------------


def _in_graveyard(player, card):
    """A `GameObject` for ``card`` sitting directly in ``player``'s graveyard,
    as if it had already been cast and resolved there some previous turn."""
    obj = GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD)
    player.add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def test_flashback_not_castable_from_hand_or_without_the_keyword():
    eng = make_engine([instant(name="Plain Spell", cost="{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    spell = p1.hand[0]
    p1.mana_pool.add_many({"R": 5, "U": 5, "C": 5})
    p1.hand.remove(spell)
    grave_spell = _in_graveyard(p1, spell.card)

    assert not eng.can_cast(p1, grave_spell)  # no flashback keyword at all


def test_flashback_castable_from_the_graveyard_for_its_own_cost():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})  # not enough for the printed {3}{R}

    assert eng.can_cast(p1, grave_spell)  # affordable via the flashback cost
    eng.cast_spell(p1, grave_spell)

    assert p1.mana_pool.total() == 0
    assert grave_spell not in p1.graveyard
    assert eng.state.stack[-1].obj is grave_spell


def test_flashback_cast_spell_is_exiled_instead_of_returning_to_the_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})

    eng.cast_spell(p1, grave_spell)
    eng.resolve_until_stable()

    assert grave_spell in p1.exile
    assert grave_spell not in p1.graveyard
    assert grave_spell.cast_via_flashback is False  # cleared once consumed


def test_flashback_cannot_be_paid_without_enough_mana():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{2}{U}"}}
    p1.mana_pool.add_many({"U": 1})  # not enough for {2}{U}

    assert not eng.can_cast(p1, grave_spell)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, grave_spell)


def test_legal_actions_surfaces_flashback_cast_from_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = instant(name="Flashed Back", cost="{3}{R}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"flashback": {"cost": "{U}"}}
    p1.mana_pool.add_many({"U": 1})

    actions = eng.legal_actions(p1)
    cast_action = next(
        a for a in actions
        if a.get("type") == "cast_spell" and a.get("instance_id") == grave_spell.instance_id
    )
    assert cast_action["cast_from_graveyard"] == "flashback"
    assert cast_action["base_cost"] == "{3}{R}"
    assert cast_action["effective_cost"] == "{U}"


# -- Escape (RULE 702.138) ----------------------------------------------------


def test_escape_not_castable_without_enough_other_graveyard_cards():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    p1.mana_pool.add_many({"B": 2, "C": 1})
    # No other cards in the graveyard yet — only the escaping card itself.

    assert not eng.can_cast(p1, grave_spell)


def test_escape_castable_once_enough_other_cards_are_present():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    _in_graveyard(p1, instant(name="Filler 1"))
    _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})  # not enough for the printed {2}{B}

    assert eng.can_cast(p1, grave_spell)  # affordable via the escape cost


def test_escape_exiles_the_announced_other_cards_and_pays_its_own_cost():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    filler1 = _in_graveyard(p1, instant(name="Filler 1"))
    filler2 = _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    eng.cast_spell(p1, grave_spell)

    assert p1.mana_pool.total() == 1  # {1}{B} escape cost spent, {B}{C} pool - 2 leaves 1
    assert grave_spell not in p1.graveyard
    assert filler1 in p1.exile
    assert filler2 in p1.exile
    assert filler1 not in p1.graveyard
    assert filler2 not in p1.graveyard


def test_escape_cast_creature_resolves_onto_the_battlefield():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {"escape": {"cost": "{1}{B}"}}  # no exile component
    p1.mana_pool.add_many({"B": 2, "C": 1})

    eng.cast_spell(p1, grave_spell)
    eng.resolve_until_stable()

    assert grave_spell in eng.state.battlefield
    assert grave_spell not in p1.graveyard
    assert grave_spell not in p1.exile  # unlike Flashback, Escape doesn't exile after resolving


def test_legal_actions_surfaces_escape_offer():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = creature(name="Escaped Thing", cost="{2}{B}")
    grave_spell = _in_graveyard(p1, card)
    grave_spell.parametric_keywords = {
        "escape": {"cost": "{1}{B}, Exile two other cards from your graveyard"}
    }
    _in_graveyard(p1, instant(name="Filler 1"))
    _in_graveyard(p1, instant(name="Filler 2"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    actions = eng.legal_actions(p1)
    cast_action = next(
        a for a in actions
        if a.get("type") == "cast_spell" and a.get("instance_id") == grave_spell.instance_id
    )
    assert cast_action["cast_from_graveyard"] == "escape"
    assert cast_action["escape_exile_count"] == 2
    assert cast_action["effective_cost"] == "{1}{B}"


def test_bind_from_catalogue_creates_equipment_ability_from_keyword():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    # RULE 702.6c: Equip is sorcery-speed only — a real main phase, not just
    # "some point in the turn" (`begin_turn` alone lands in untap/upkeep).
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    host.summoning_sick = False

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    assert source.activated_abilities
    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, source, 0, targets=[host])
    eng.resolve_until_stable()

    assert source.attached_to == host.instance_id
