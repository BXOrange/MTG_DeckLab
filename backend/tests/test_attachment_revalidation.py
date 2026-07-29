"""RULE 704.5m/n: a permanent still attached to a *legal* host when it was
attached can become illegally attached later — the host gaining protection
from the attachment's quality is the common case (RULE 702.16c/d). Only
"host left the battlefield" was previously checked
(`RulesEngine._detach_attachments_from`); this covers the other half,
re-validated every SBA pass (`RulesEngine._revalidate_attachments`).

Reference: mtg_analyzer/game/rules_engine.py (`_attachment_legal`,
`_revalidate_attachments`).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _creature(name="Bear", power=2, toughness=2, color_identity=None):
    return Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness,
        color_identity=set(color_identity or ()),
    )


def _aura(name, oracle_text="Enchant creature", color_identity=None):
    return Card(
        id=name, name=name, type_line="Enchantment — Aura",
        oracle_text=oracle_text, color_identity=set(color_identity or ()),
    )


def _equipment(name, oracle_text="Equip {1}", keywords=None, color_identity=None):
    return Card(
        id=name, name=name, type_line="Artifact — Equipment",
        oracle_text=oracle_text, keywords=list(keywords or ["Equip"]),
        color_identity=set(color_identity or ()),
    )


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_aura_stays_attached_when_nothing_changed():
    engine, state, p1, _ = _rules()
    host = _bf(state, _creature("Bear"))
    aura = _bf(state, _aura("Rancor"))
    engine.attach_to_target(aura, host)

    assert engine.check_state_based_actions() is False
    assert aura.attached_to == host.instance_id
    assert aura in state.battlefield


def test_aura_goes_to_graveyard_when_host_gains_protection_from_its_color():
    # RULE 702.16c / 704.5m: an Aura still attached to a host that has since
    # gained protection from the Aura's colour is put into its owner's
    # graveyard as a state-based action.
    engine, state, p1, _ = _rules()
    host = _bf(state, _creature("Bear"))
    aura = _bf(state, _aura("Rancor", color_identity={"G"}))
    engine.attach_to_target(aura, host)
    assert aura.attached_to == host.instance_id

    host.temp_protections = {"G"}

    assert engine.check_state_based_actions() is True
    assert aura.attached_to is None
    assert aura not in state.battlefield
    assert aura in p1.graveyard


def test_equipment_unattaches_but_stays_on_battlefield_when_host_gains_protection():
    # RULE 702.16d / 704.5n: an Equipment (unlike an Aura) merely becomes
    # unattached — it isn't put anywhere, it just stops being attached.
    engine, state, p1, _ = _rules()
    host = _bf(state, _creature("Bear"))
    equipment = _bf(state, _equipment("Bonesplitter", color_identity={"R"}))
    engine.attach_to_target(equipment, host)
    assert equipment.attached_to == host.instance_id

    host.temp_protections = {"R"}

    assert engine.check_state_based_actions() is True
    assert equipment.attached_to is None
    assert equipment in state.battlefield


def test_equipment_unattaches_when_the_host_changes_control():
    # RULE 301.5c: Equipment stays attached across an *ordinary* board
    # change, but "target creature you control" (RULE 301.5b) is re-checked
    # continuously — a host that's no longer the Equipment's controller's
    # creature is an illegal attachment.
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"))
    equipment = _bf(state, _equipment("Bonesplitter"))
    engine.attach_to_target(equipment, host)

    host.controller_id = "p2"

    assert engine.check_state_based_actions() is True
    assert equipment.attached_to is None
    assert equipment in state.battlefield


def test_revalidation_leaves_a_host_that_left_the_battlefield_to_the_other_path():
    # `_detach_attachments_from` already owns the host-left case — the new
    # SBA sweep must not double-handle (or crash on) an attachment whose
    # host is simply gone.
    engine, state, p1, _ = _rules()
    host = _bf(state, _creature("Bear"))
    aura = _bf(state, _aura("Rancor"))
    engine.attach_to_target(aura, host)

    engine.destroy(host)

    assert aura.attached_to is None
    assert aura in p1.graveyard
