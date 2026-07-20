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
  ordinary ability line (`segmenter.segment_line`) and, when it comes back a
  plain self-scoped trigger on ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS,
  wrapped as a `grant_triggered_ability`. A DAMAGE/phase-scoped trigger
  inside the quotes must still stay unclaimed (fail-closed — a pre-existing
  controller-scoped phase-trigger gap, not special to grants).
* A quoted **activated**-ability grant (Umbral Mantle/Squirrel Nest-shaped
  "`<host>` has '`{cost}`: `<effect>`.'") was fail-closed as of Batch 3
  (needed a real "grant an activated ability" engine primitive that didn't
  exist — ToDo_EdgeCases #35) and stayed that way through two further
  deferrals (Batch 7, and again in this codebase's own `ToDo_Backend.md`)
  before finally shipping here: `GameObject._granted_activated_abilities`/
  `granted_activated_abilities` (mirrors `_granted_triggered_abilities`
  exactly), a `grant_activated_ability` `EffectSpec`/`StaticAbility`, and a
  matching layer-6 branch in `continuous.recompute` building a real
  `ActivatedAbility` per affected object (cached the same way, keyed
  ``(id(ability), obj.instance_id, "activated")`` so it can't collide with
  the triggered-ability cache dict it shares). `GameEngine.can_activate`/
  `activate_ability`/`legal_actions` all now read `activated_abilities +
  granted_activated_abilities` together. Getting a real card end-to-end also
  surfaced and fixed a **pre-existing, unrelated segmenter bug**: the
  top-level `<cost>: <effect>` check (`_ACTIVATED_RE`) is quote-blind, so a
  quoted grant whose *inner* ability itself contains a cost-colon
  ("has '`{3}`, `{Q}`: ...'") was being misparsed as if that inner colon
  were the outer line's own cost/effect boundary — invisible until now
  since no other handler had ever tried to recognize a quote-containing
  activated-ability shape (`segmenter.py`'s `_ACTIVATED_RE` cost group now
  excludes `"`).

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


def test_quoted_activated_ability_grant_is_modeled():
    card = _aura(
        "Archery Training",
        'Enchant creature\nEnchanted creature has "{t}: ~ deals 1 damage to '
        'target attacking or blocking creature."',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_umbral_mantle_grants_a_real_activated_ability_that_pumps_the_host():
    """End-to-end (not parse-only, per this file's own standing lesson):
    Umbral Mantle equips a creature, `continuous.recompute` builds a real
    `ActivatedAbility` from the quoted grant, and actually activating it
    (paying no real cost here — resolving the granted effect directly, the
    same way this file's other granted-ability tests skip cost payment and
    fire the *effect* to prove the wiring) pumps the host."""
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"), controller="p1")
    mantle = _bf(
        state,
        _aura(
            "Umbral Mantle",
            'Equipped creature has "{3}, {Q}: This creature gets +2/+2 '
            'until end of turn."\nEquip {0}',
            type_line="Artifact — Equipment",
        ),
        controller="p1",
    )
    mantle.attached_to = host.instance_id
    continuous.recompute(state)

    granted = host.granted_activated_abilities
    assert len(granted) == 1
    ability = granted[0]
    assert ability.cost.mana.converted_mana_cost == 3
    assert ability.cost.untaps_self is True

    ability.apply(engine.context)
    continuous.recompute(state)
    assert host.power == 4 and host.toughness == 4, "the granted pump actually resolved"


def test_squirrel_nest_grants_a_real_activated_ability_that_creates_a_token():
    engine, state, p1, p2 = _rules()
    land = _bf(state, Card(id="L", name="Land", type_line="Basic Land — Forest", is_land=True))
    nest = _bf(
        state,
        _aura(
            "Squirrel Nest",
            'Enchant land\nEnchanted land has "{t}: Create a 1/1 green '
            'Squirrel creature token."',
        ),
        controller="p1",
    )
    nest.attached_to = land.instance_id
    continuous.recompute(state)

    granted = land.granted_activated_abilities
    assert len(granted) == 1
    assert granted[0].cost.taps_self is True

    tokens_before = sum(1 for o in state.battlefield if "Squirrel" in o.name)
    granted[0].apply(engine.context)
    tokens_after = sum(1 for o in state.battlefield if "Squirrel" in o.name)
    assert tokens_after == tokens_before + 1


def test_granted_activated_ability_reachable_through_game_engine():
    """Unlike the two tests above (direct `ActivatedAbility.apply`, proving
    the grant/binding/effect wiring), this drives the *real* activation path
    a player uses — `GameEngine.legal_actions`/`can_activate`/
    `activate_ability`, which now read `activated_abilities +
    granted_activated_abilities` together (`game_engine.py`). Both call
    sites must enumerate the identical concatenation or an index offered by
    `legal_actions` wouldn't address the same ability `activate_ability`
    resolves — this is the regression guard for that."""
    from mtg_analyzer.game.game_engine import GameEngine

    eng = GameEngine.new_game([("p1", "Alice", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(_creature("Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    host.tapped = True  # so the granted "{Q}" (untap) cost is payable
    eng.state.add_to_battlefield(host)

    mantle = GameObject(
        _aura(
            "Umbral Mantle",
            'Equipped creature has "{3}, {Q}: This creature gets +2/+2 '
            'until end of turn."\nEquip {0}',
            type_line="Artifact — Equipment",
        ),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(mantle)
    eng.state.add_to_battlefield(mantle)
    mantle.attached_to = host.instance_id
    eng.recompute_continuous_effects()

    granted = host.granted_activated_abilities
    assert len(granted) == 1
    ability = granted[0]
    assert ability in host.activated_abilities + host.granted_activated_abilities

    p1.mana_pool.add_many({"C": 3})
    actions = eng.legal_actions(p1)
    offered = [
        a for a in actions
        if a.get("type") == "activate_ability" and a.get("instance_id") == host.instance_id
    ]
    assert len(offered) == 1, f"granted ability not offered: {actions}"

    assert eng.can_activate(p1, host, ability)
    eng.activate_ability(p1, host, offered[0]["ability_index"])
    eng.resolve_until_stable()

    assert not host.tapped, "the granted {Q} cost untapped the host"
    assert host.power == 4 and host.toughness == 4


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
