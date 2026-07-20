"""Batch 3 (docs/implementation-state/ToDo_Backend.md): Aura/
Equipment attached-permanent grants — the "you control enchanted X"
control-change family and the "<subject> has \"<ability>\"" quoted
full-ability-grant family.

* ``you control enchanted creature/permanent.`` (Control Magic/Mind
  Control-shaped) — the existing `control_change` `StaticAbility` already
  defaults to ``affects="attached_permanent"``; only parser recognition was
  missing.
* ``<subject> [gets +N/+N and] has "<ability>"`` (Sword-cycle/Assassin
  Gauntlet/Candlestick-shaped) — the quoted body is recursively parsed as an
  ordinary ability line (`segmenter.segment_line`) and, only when it comes
  back a plain self-scoped trigger on ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS,
  wrapped as a `grant_triggered_ability`. An activated-ability grant or a
  DAMAGE/phase-scoped trigger inside the quotes must stay unclaimed
  (fail-closed) — those need engine primitives this batch doesn't build
  (ToDo_EdgeCases #35/Umbral Mantle; a pre-existing controller-scoped
  phase-trigger gap).

Each restriction test drives real oracle text through `parse_oracle`
(asserting MODELED) **and** binds + exercises it against a real
`RulesEngine`/`continuous.recompute`, per the project's "parse-only
verification has masked real runtime bugs" lesson.

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/{effect_binder,effects,continuous,rules_engine}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _aura(name, oracle_text, type_line="Enchantment — Aura"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _creature(name, power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness,
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


# -- parse-side coverage ------------------------------------------------------


def test_control_grant_creature_is_modeled():
    card = _aura("Control Magic", "Enchant creature\nYou control enchanted creature.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_control_grant_permanent_is_modeled():
    card = _aura("Confiscate", "Enchant permanent\nYou control enchanted permanent.")
    assert parse_oracle(card).unclaimed == []


def test_quoted_attack_trigger_grant_is_modeled():
    card = _aura(
        "Animal Friend",
        'Enchant creature\nEnchanted creature has "whenever ~ attacks, '
        'create a 1/1 green squirrel creature token."',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_quoted_dies_trigger_grant_on_equipment_is_modeled():
    card = _aura(
        "Doom Blade Blade",
        'Equipped creature has "when ~ dies, draw a card."\nEquip {2}',
        type_line="Artifact — Equipment",
    )
    assert parse_oracle(card).unclaimed == []


def test_anthem_plus_quoted_trigger_grant_is_modeled():
    card = _aura(
        "Candlestick",
        'Equipped creature gets +1/+1 and has "whenever ~ attacks, surveil 2."\nEquip {1}',
        type_line="Artifact — Equipment",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_quoted_activated_ability_grant_stays_unclaimed():
    # Fail-closed: granting an *activated* ability needs a real engine
    # primitive this batch doesn't build (ToDo_EdgeCases #35/Umbral Mantle).
    card = _aura(
        "Archery Training",
        'Enchant creature\nEnchanted creature has "{t}: ~ deals 1 damage to '
        'target attacking or blocking creature."',
    )
    assert parse_oracle(card).coverage == UNMODELED


def test_quoted_damage_trigger_grant_is_modeled():
    # Was fail-closed as of Batch 3 ("deals combat damage to a player" wasn't
    # in the oracle parser's trigger-event vocabulary at all); Batch 4 added
    # that recognition *and* extended `grant_triggered_ability`/`continuous.
    # _granted_trigger_condition` to DAMAGE events, so this now models fully
    # (see `test_phase_and_damage_triggers.py`, which owns this family).
    card = _aura(
        "Assassin Gauntlet",
        'Equipped creature gets +1/+1 and has "whenever ~ deals combat '
        'damage to a player, draw a card, then discard a card."\nEquip {2}',
        type_line="Artifact — Equipment",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_quoted_upkeep_trigger_grant_stays_unclaimed():
    # Fail-closed: controller-scoped phase triggers ("at the beginning of
    # your end step") are a pre-existing gap for even a top-level card.
    card = _aura(
        "Cement Shoes",
        'Equipped creature gets +3/+3 and has "at the beginning of your end '
        'step, tap ~."\nEquip {2}',
        type_line="Artifact — Equipment",
    )
    assert parse_oracle(card).coverage == UNMODELED


# -- execute-side (bind → engine) --------------------------------------------


def test_control_change_grant_flips_control_of_the_host():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Stolen Bear"), controller="p2")
    aura = _bf(
        state,
        _aura("Control Magic", "Enchant creature\nYou control enchanted creature."),
        controller="p1",
    )
    aura.attached_to = host.instance_id

    continuous.recompute(state)

    assert host.controller_id == "p1"


def test_control_change_grant_reverts_when_aura_leaves():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Stolen Bear"), controller="p2")
    aura = _bf(
        state,
        _aura("Control Magic", "Enchant creature\nYou control enchanted creature."),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    continuous.recompute(state)
    assert host.controller_id == "p1"

    engine._detach_attachments_from(host)
    engine._move_to_graveyard(aura)
    continuous.recompute(state)

    assert host.controller_id == "p2"


def test_quoted_attack_trigger_grant_fires_when_the_host_attacks():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"), controller="p1")
    aura = _bf(
        state,
        _aura(
            "Animal Friend",
            'Enchant creature\nEnchanted creature has "whenever ~ attacks, '
            'draw a card."',
        ),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    p1.library.append(GameObject(_creature("Library Bear"), owner_id="p1", zone=Zone.LIBRARY))
    continuous.recompute(state)

    assert len(host._granted_triggered_abilities) == 1

    from mtg_analyzer.models.events import EventType, GameEvent

    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=host.name, player_id="p1",
            instance_id=host.instance_id, object_types=sorted(host.type_words),
        )
    )
    placed = engine.put_triggers_on_stack()
    assert placed == 1
    engine.resolve_top_of_stack()
    assert len(p1.hand) == 1


def test_quoted_trigger_grant_does_not_fire_for_a_different_permanent():
    # Same-shaped Aura on a *different* host must not also fire for this one
    # — the whole point of granting a fresh, self-scoped `TriggeredAbility`
    # per affected object (`continuous._granted_trigger_condition`).
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"), controller="p1")
    bystander = _bf(state, _creature("Bystander"), controller="p1")
    aura = _bf(
        state,
        _aura(
            "Animal Friend",
            'Enchant creature\nEnchanted creature has "whenever ~ attacks, '
            'draw a card."',
        ),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    p1.library.append(GameObject(_creature("Library Bear"), owner_id="p1", zone=Zone.LIBRARY))
    continuous.recompute(state)

    from mtg_analyzer.models.events import EventType, GameEvent

    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=bystander.name, player_id="p1",
            instance_id=bystander.instance_id, object_types=sorted(bystander.type_words),
        )
    )
    placed = engine.put_triggers_on_stack()
    assert placed == 0


def test_quoted_trigger_grant_disappears_once_unattached():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"), controller="p1")
    aura = _bf(
        state,
        _aura(
            "Animal Friend",
            'Enchant creature\nEnchanted creature has "whenever ~ attacks, '
            'draw a card."',
        ),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    continuous.recompute(state)
    assert len(host._granted_triggered_abilities) == 1

    aura.attached_to = None
    continuous.recompute(state)
    assert len(host._granted_triggered_abilities) == 0
