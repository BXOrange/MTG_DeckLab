"""Batch 3 (docs/implementation-state/BACKLOG.md): Aura/
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
  wrapped as a `grant_triggered_ability`. DAMAGE followed later; the
  RULE 500.7 **phase**-scoped trigger ("… has 'At the beginning of your
  upkeep, …'" — Commander's Authority/Clawing Torment/Aura Flux) followed
  after that, and is the one grantable event with no object subject at all:
  what makes it safe to regrant is threading the segmenter's
  ``phase_relation`` through to `continuous._granted_trigger_condition`,
  which resolves "your" against the **granted-to** permanent's controller.
  The un-scoped "at the beginning of *each* upkeep" form stays unclaimed.
* A quoted **mana**-ability grant ("Elves you control have '`{T}`: Add
  `{B}`.'" — Tyvar Kell; "Enchanted land has '`{T}`: Add 1 mana of any
  color.'" — Abundant Growth) can't go through the recursive
  `segment_line` parse at all: a plain top-level mana ability is
  claimed-*without*-a-spec by the segmenter (mana production is recognized
  directly off printed text by `game/mana_abilities.py`, not via the
  `EffectRegistry` pipeline), so the nested parse returns nothing to
  re-emit. `static_handlers._granted_mana_options` recognizes the bare
  "`{T}`: Add `<mana>`" body itself and emits the existing
  `grant_mana_ability` primitive. `{T}`-only: any other cost component
  ("`{T}`, Sacrifice a creature: …") isn't expressible as a bare production
  list and stays unclaimed.
* A quoted **activated**-ability grant (Umbral Mantle/Squirrel Nest-shaped
  "`<host>` has '`{cost}`: `<effect>`.'") was fail-closed as of Batch 3
  (needed a real "grant an activated ability" engine primitive that didn't
  exist — ToDo_EdgeCases #35) and stayed that way through two further
  deferrals (Batch 7, and again in this codebase's own `BACKLOG.md`)
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
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
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


def test_quoted_phase_trigger_grant_is_modeled():
    # Was fail-closed until the phase/upkeep grant shipped: a RULE 500.7
    # `STEP_BEGIN` trigger has no object subject to re-scope, so the grant
    # threads the segmenter's `phase_relation` through instead and
    # `continuous._granted_trigger_condition` resolves "your" against the
    # *granted-to* permanent's controller (see `test_phase_and_damage_
    # triggers.py`, which owns this family).
    card = _aura(
        "Cement Shoes",
        'Equipped creature gets +3/+3 and has "at the beginning of your end '
        'step, tap ~."\nEquip {2}',
        type_line="Artifact — Equipment",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_quoted_unscoped_phase_trigger_grant_stays_unclaimed():
    # Fail-closed: "at the beginning of *each* upkeep" carries no
    # `phase_relation`, so a regranted copy would have no way to say whose
    # upkeep it means — only the "your"/"each opponent's" forms are claimed.
    card = _aura(
        "Cement Boots",
        'Equipped creature gets +3/+3 and has "at the beginning of each end '
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

    from mtg_analyzer.models.game.events import EventType, GameEvent

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

    from mtg_analyzer.models.game.events import EventType, GameEvent

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


# -- granted mana abilities (RULE 613.7f, `grant_mana_ability`) ---------------


def test_quoted_mana_ability_grant_is_modeled():
    card = _aura(
        "Abundant Growth",
        'Enchant land\nWhen this Aura enters, draw a card.\n'
        'Enchanted land has "{T}: Add one mana of any color."',
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_quoted_mana_ability_grant_with_a_second_cost_component_stays_unclaimed():
    # Animal Boneyard-shaped: "{T}, Sacrifice a creature: …" isn't a bare
    # production list, so the whole clause fails closed.
    card = _aura(
        "Animal Boneyard Clone",
        'Enchant land\nEnchanted land has "{T}, Sacrifice a creature: Add {G}."',
    )
    assert parse_oracle(card).coverage == UNMODELED


def test_granted_fixed_pip_mana_ability_reaches_mana_options():
    from mtg_analyzer.game import mana_abilities

    engine, state, p1, p2 = _rules()
    elf = _bf(state, _creature("Llanowar Elf"), controller="p1")
    elf.card.type_line = "Creature — Elf Druid"
    lord = _bf(
        state,
        _aura(
            "Tyvar Clone",
            'Elves you control have "{T}: Add {B}."',
            type_line="Legendary Planeswalker — Tyvar",
        ),
        controller="p1",
    )
    continuous.recompute(state)

    assert elf.granted_mana_options == [{"B": 1}]
    assert {"B": 1} in mana_abilities.mana_options_for(elf, state)

    # RULE 613.6: the grant disappears on its own once its source leaves.
    state.battlefield.remove(lord)
    continuous.recompute(state)
    assert elf.granted_mana_options == []


def test_granted_any_color_mana_ability_fans_out_to_one_option_per_colour():
    engine, state, p1, p2 = _rules()
    land = _bf(state, _aura("Forest", "", type_line="Basic Land — Forest"), controller="p1")
    aura = _bf(
        state,
        _aura(
            "Abundant Growth",
            'Enchant land\nEnchanted land has "{T}: Add one mana of any color."',
        ),
        controller="p1",
    )
    aura.attached_to = land.instance_id
    continuous.recompute(state)

    assert land.granted_mana_options == [
        {"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}
    ]


# -- granted phase/upkeep triggers (RULE 500.7) -------------------------------


def _upkeep(state, engine):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    return engine.put_triggers_on_stack()


def test_granted_upkeep_trigger_fires_on_the_hosts_own_controllers_upkeep():
    engine, state, p1, p2 = _rules()
    host = _bf(state, _creature("Bear"), controller="p2")
    aura = _bf(
        state,
        _aura(
            "Clawing Torment",
            'Enchant artifact or creature\n'
            'Enchanted permanent has "At the beginning of your upkeep, you lose 1 life."',
        ),
        controller="p1",
    )
    aura.attached_to = host.instance_id
    continuous.recompute(state)

    # "your" is the *enchanted permanent's* controller (p2), not the Aura's
    # (p1) — that's the whole point of Clawing Torment.
    state.active_player_index = 0  # p1's turn
    assert _upkeep(state, engine) == 0

    state.active_player_index = 1  # p2's turn
    assert _upkeep(state, engine) == 1
    engine.resolve_top_of_stack()
    assert p2.life == 19
    assert p1.life == 20


def test_granted_upkeep_trigger_fires_once_per_affected_permanent():
    engine, state, p1, p2 = _rules()
    one = _bf(state, _creature("Bear One"), controller="p1")
    two = _bf(state, _creature("Bear Two"), controller="p1")
    lord = _bf(
        state,
        _aura(
            "Upkeep Lord",
            'Other creatures you control have "At the beginning of your upkeep, you lose 1 life."',
            type_line="Creature — Bear",
        ),
        controller="p1",
    )
    continuous.recompute(state)

    # "Other" — the granting creature itself is excluded, so exactly the two
    # others each get their own copy of the ability, and both fire.
    assert len(one._granted_triggered_abilities) == 1
    assert len(two._granted_triggered_abilities) == 1
    assert len(lord._granted_triggered_abilities) == 0

    state.active_player_index = 0
    assert _upkeep(state, engine) == 2
