"""PAR-111 (small residue batch — ETB/dies/leaves triggers): Exploit as a real mechanic and its trigger head,
"you may have that player lose N life" under a group trigger, "attach it to target legendary creature you
control", and "manifest dread, then attach ~ to that creature".

Exploit (RULE 702.110): the keyword is an ETB "you may sacrifice a creature" (`ExploitEffect`, the ``exploit``
choose-action), and the sacrifice fires `EventType.EXPLOITS` — what "when ~ exploits a creature" reads.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.game.binding.core import bind_from_catalogue

EXPLOITER = "Exploit\nWhen this creature exploits a creature, draw a card."


def _card(name, type_line="Creature — Bear", oracle="", power=2, toughness=2):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                is_legendary="Legendary" in type_line, is_land="Land" in type_line,
                power=power if creature else None, toughness=toughness if creature else None,
                converted_mana_cost=0,
                # Scryfall's own `keywords` array is what `parse_keywords` reads (as for a cached card).
                keywords=(["Exploit"] if oracle.startswith("Exploit") else [])
                + (["Equip"] if "Equip {" in oracle else []))


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _enter(eng, card, controller="p1"):
    """Put ``card`` onto the battlefield the way a resolving permanent spell does (fires ENTERS_BATTLEFIELD)."""
    player = eng.state.player_by_id(controller)
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    player.remove_from_zone(obj, Zone.HAND)
    eng.rules._put_searched_card(player, obj, "battlefield")
    eng.resolve_until_stable()
    return obj


def _stock_library(eng, controller="p1", n=3):
    player = eng.state.player_by_id(controller)
    for i in range(n):
        obj = GameObject(_card(f"Filler {i}", "Creature — Bear"), owner_id=controller, zone=Zone.LIBRARY)
        player.library.append(obj)
    return player


# --- Exploit: parse ---------------------------------------------------------


def test_exploit_trigger_heads():
    own = parse_object_trigger_head("~ exploits a creature")
    assert (own.event, own.condition, own.trigger) == ("EXPLOITS", {"subject": "self"}, {})
    group = parse_object_trigger_head("a creature you control exploits a non-human creature")
    assert group.event == "EXPLOITS"
    assert group.condition["subject"] == "group" and group.condition["controller"] == "you"
    assert group.trigger["related_filter"]  # the sacrificed creature must not be a Human


@pytest.mark.parametrize("text", [
    "~ exploits",                                 # no object: not the printed trigger
    "~ or another creature you control exploits a creature",   # a self-or-group exploit head is not printed
])
def test_exploit_head_refuses_unprinted_shapes(text):
    assert parse_object_trigger_head(text) is None


def test_a_real_exploit_card_is_modeled_and_a_grant_of_exploit_is_not():
    assert parse_oracle(_card("Stitched Assistant", "Creature — Zombie",
                              "Exploit (When this creature enters, you may sacrifice a creature.)\n"
                              "When this creature exploits a creature, scry 1, then draw a card.")).modeled
    # a granted flag keyword would add the slug and none of the ETB trigger
    colonel = _card("Colonel Autumn", "Legendary Creature — Dragon",
                    "Exploit\nOther legendary creatures you control have exploit.")
    assert not parse_oracle(colonel).modeled


# --- Exploit: execute -------------------------------------------------------


def _exploit_answer(eng, victim):
    choice = eng.state.pending_choice
    assert choice is not None and any(
        opt.get("instance_id") == victim.instance_id for opt in choice["options"]
    ), choice
    eng.resolve_pending_choice(victim.instance_id)


def test_sacrificing_a_creature_exploits_it_and_the_trigger_resolves():
    eng = _engine()
    p1 = _stock_library(eng)
    victim = _put(eng, _card("Fodder"))
    hand = len(p1.hand)
    _enter(eng, _card("Exploiter", "Creature — Zombie", EXPLOITER))
    _exploit_answer(eng, victim)
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert len(p1.hand) == hand + 1


def test_declining_the_exploit_sacrifices_nothing_and_does_not_trigger():
    eng = _engine()
    p1 = _stock_library(eng)
    victim = _put(eng, _card("Fodder"))
    hand = len(p1.hand)
    _enter(eng, _card("Exploiter", "Creature — Zombie", EXPLOITER))
    eng.resolve_pending_choice(None)
    eng.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD
    assert len(p1.hand) == hand


def test_the_exploiter_may_sacrifice_itself():
    eng = _engine()
    p1 = _stock_library(eng)
    hand = len(p1.hand)
    exploiter = _enter(eng, _card("Exploiter", "Creature — Zombie", EXPLOITER))
    _exploit_answer(eng, exploiter)
    eng.resolve_until_stable()
    assert exploiter.zone == Zone.GRAVEYARD
    assert len(p1.hand) == hand + 1  # RULE 702.110b: sacrificing itself is exploiting a creature


def test_exploit_only_offers_creatures_its_controller_controls():
    eng = _engine()
    mine = _put(eng, _card("Mine"))
    theirs = _put(eng, _card("Theirs"), controller="p2")
    land = _put(eng, _card("Forest", "Basic Land — Forest"))
    _enter(eng, _card("Exploiter", "Creature — Zombie", "Exploit"))
    ids = {opt.get("instance_id") for opt in eng.state.pending_choice["options"]}
    assert mine.instance_id in ids
    assert theirs.instance_id not in ids and land.instance_id not in ids


def test_a_group_exploit_trigger_reads_the_sacrificed_creature():
    text = "Whenever a creature you control exploits a non-Human creature, draw a card."
    for victim_type, expect in (("Creature — Human", 0), ("Creature — Zombie", 1)):
        eng = _engine()
        p1 = _stock_library(eng)
        _put(eng, _card("Watcher", "Creature — Zombie", text))
        victim = _put(eng, _card("Fodder", victim_type))
        hand = len(p1.hand)
        _enter(eng, _card("Exploiter", "Creature — Zombie", "Exploit"))
        _exploit_answer(eng, victim)
        eng.resolve_until_stable()
        assert len(p1.hand) == hand + expect, victim_type


def test_exploits_event_names_the_exploiter_and_the_victim():
    eng = _engine()
    victim = _put(eng, _card("Fodder"))
    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.EXPLOITS else None)
    exploiter = _enter(eng, _card("Exploiter", "Creature — Zombie", "Exploit"))
    _exploit_answer(eng, victim)
    assert len(seen) == 1
    assert seen[0].get("instance_id") == exploiter.instance_id
    assert seen[0].get("related_ids") == [victim.instance_id]


# --- "you may have that player lose N life" ---------------------------------

BLOOD_SEEKER = "Whenever a creature an opponent controls enters, you may have that player lose 1 life."


def test_blood_seeker_is_modeled():
    assert parse_oracle(_card("Blood Seeker", "Creature — Vampire Shaman", BLOOD_SEEKER, 1, 1)).modeled


def test_the_entering_creatures_controller_loses_the_life_when_you_say_yes():
    eng = _engine()
    _put(eng, _card("Blood Seeker", "Creature — Vampire Shaman", BLOOD_SEEKER, 1, 1))
    _enter(eng, _card("Wanderer"), controller="p2")
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 19
    assert eng.state.player_by_id("p1").life == 20


def test_declining_costs_nobody_life_and_your_own_creatures_do_not_trigger_it():
    eng = _engine()
    _put(eng, _card("Blood Seeker", "Creature — Vampire Shaman", BLOOD_SEEKER, 1, 1))
    _enter(eng, _card("Wanderer"), controller="p2")
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 20
    _enter(eng, _card("Mine"), controller="p1")
    assert eng.state.pending_choice is None
    assert eng.state.player_by_id("p1").life == 20 and eng.state.player_by_id("p2").life == 20


# --- "attach it to target legendary creature you control" -------------------

MITHRIL = ("Flash\nIndestructible\nWhen Mithril Coat enters, attach it to target legendary creature you control.\n"
           "Equipped creature has indestructible.\nEquip {3}")


def test_mithril_coat_is_modeled():
    assert parse_oracle(_card("Mithril Coat", "Legendary Artifact — Equipment", MITHRIL)).modeled


def test_the_etb_attach_only_offers_legendary_creatures_you_control():
    eng = _engine()
    plain = _put(eng, _card("Bear"))
    legend = _put(eng, _card("Hero", "Legendary Creature — Human"))
    _put(eng, _card("Villain", "Legendary Creature — Human"), controller="p2")
    coat = _enter(eng, _card("Mithril Coat", "Legendary Artifact — Equipment", MITHRIL))
    # the plain Bear and the opponent's legend are not options
    assert [o["instance_id"] for o in eng.state.pending_choice["options"]] == [legend.instance_id]
    eng.resolve_pending_choice(str(legend.instance_id))
    eng.resolve_until_stable()
    assert coat.attached_to == legend.instance_id
    assert plain.instance_id != coat.attached_to


HALBERD = ("When this Equipment enters, attach it to target non-Human creature you control.\n"
           "Equipped creature gets +2/+1.\nEquip {5}")


def test_a_non_human_destination_excludes_humans():
    eng = _engine()
    _put(eng, _card("Soldier", "Creature — Human Soldier"))
    elf = _put(eng, _card("Elf", "Creature — Elf"))
    halberd = _enter(eng, _card("Rosethorn Halberd", "Artifact — Equipment", HALBERD))
    assert [o["instance_id"] for o in eng.state.pending_choice["options"]] == [elf.instance_id]
    eng.resolve_pending_choice(str(elf.instance_id))
    eng.resolve_until_stable()
    assert halberd.attached_to == elf.instance_id


# --- "manifest dread, then attach ~ to that creature" -----------------------

MACHETE = ("When this Equipment enters, manifest dread, then attach this Equipment to that creature.\n"
           "Equipped creature gets +2/+1.\nEquip {4}")


def test_the_manifest_dread_equipment_cycle_is_modeled():
    assert parse_oracle(_card("Conductive Machete", "Artifact — Equipment", MACHETE)).modeled


def test_the_equipment_attaches_to_the_card_you_chose_to_manifest():
    eng = _engine()
    p1 = _stock_library(eng, n=3)
    top, second = p1.library[-1], p1.library[-2]
    machete = _enter(eng, _card("Conductive Machete", "Artifact — Equipment", MACHETE))
    choice = eng.state.pending_choice
    assert choice["kind"] == "manifest_dread"
    eng.resolve_pending_choice(second.instance_id)
    eng.resolve_until_stable()
    assert second.zone == Zone.BATTLEFIELD and second.face_down
    assert machete.attached_to == second.instance_id
    assert top.zone == Zone.GRAVEYARD


def test_a_one_card_library_manifests_and_attaches_without_asking():
    eng = _engine()
    p1 = _stock_library(eng, n=1)
    only = p1.library[-1]
    machete = _enter(eng, _card("Conductive Machete", "Artifact — Equipment", MACHETE))
    assert eng.state.pending_choice is None
    assert only.zone == Zone.BATTLEFIELD
    assert machete.attached_to == only.instance_id
