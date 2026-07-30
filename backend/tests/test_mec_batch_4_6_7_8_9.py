"""Tests for BACKLOG MEC-4, MEC-6, MEC-7, MEC-8, MEC-9.

MEC-4 (Strive — not a RULE 702 keyword at all, no CR entry defines it):
``AbilitySpec.strive_cost`` rides on a spec the same "own oracle-text line"
way ``conditional_flash``/``free_cast_condition`` do; `game/effect_binder.py`
parses it into a real `ManaCost` on ``obj.strive_cost``, and
`GameEngine.effective_cast_cost` adds one copy per target beyond the first
using the caster's actual chosen ``targets`` (RULE 601.2c precedes 601.2f).
The segmenter recognizes the exact clause template too. No real cached card
reaches full `MODELED` from this alone — every one also needs "any number of
target creatures" targeting (a separate, ~64-card family, not part of this
ticket) — so these are engine-primitive-level tests, not an end-to-end real
card.

MEC-6 (Embercleave's own cost reduction): `continuous.count_selector` grows
``attacking_creatures_you_control``/``attacking_creatures``, read live at
cast time by the existing `self_cost_reduction_for`/`_cost_static_amount`
"per" mechanism (previously built for Delve/Affinity but never exercised).
The segmenter^H^Hstatic_handlers.py parser handler also unlocks Ancient Stone
Idol's bare "for each attacking creature" (no "you control") for free.

MEC-7 (Timely Ward's conditional flash): ``"targets_a_commander"`` joins
`ALLOWED_CAST_CONDITION_KEYS`; `condition_query.conditional_flash_holds`
checks it against the caster's actual chosen targets when known (the real
cast, threaded through `can_cast`/`effective_cast_cost`'s new ``targets``
param) and answers optimistically (any commander in play/command) when not
(the offer-time preview, before targets are chosen).

MEC-8 (an emblem's own activated ability): `RulesEngine.create_emblem`
previously filed only `TriggeredAbility`/`StaticAbility`, silently dropping
an `ActivatedAbility`. `models/emblem.py` gained `activated_abilities`/
`granted_activated_abilities`/`instance_id`/`name` so an emblem can be
activated exactly like a permanent — `can_activate`/`activate_ability`/
`legal_actions`/`GameState.find_object` all treat it as a legal source.

MEC-9 (designation inheritance, RULE 725.4/726.4): `RulesEngine.
remove_player_from_game` (the RULE 800.4a leave-the-game cleanup) now passes
a departing Monarch/Initiative-holder's designation to the active player —
already guaranteed live and non-departing by the time this runs, since
`GameState.next_active_index` skips `has_lost` players during the rotation
that happens earlier in the same `begin_turn` call.
"""

from __future__ import annotations

from mtg_analyzer.game import condition_query
from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line, ParserProvenance
from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state


def _creature(name="Bear", power=2, toughness=2, **kw):
    card = Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=kw.pop("mana_cost_string", "{1}{G}"),
        converted_mana_cost=kw.pop("converted_mana_cost", 2),
        is_creature=True, power=power, toughness=toughness, **kw,
    )
    return card


def _bf(state, card, controller="p1", is_commander=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD, is_commander=is_commander)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def _segment(raw, allow_spell_effect=True):
    return segment_line(
        raw, allow_spell_effect=allow_spell_effect,
        provenance=ParserProvenance(version="test", source="rule:oracle"),
    )


# ---------------------------------------------------------------------------
# MEC-6: Embercleave's own attacking-creature-count cost reduction
# ---------------------------------------------------------------------------


def test_embercleave_costs_less_per_attacking_creature_you_control():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    embercleave = _hand(
        p1,
        Card(
            id="Embercleave", name="Embercleave", type_line="Legendary Artifact — Equipment",
            mana_cost_string="{4}{R}{R}", converted_mana_cost=6,
        ),
    )
    # `_hand` already binds — Embercleave's cost-reduction static comes from
    # the hand-authored catalogue entry (`game/ability_catalogue.py`).
    assert engine.effective_cast_cost(p1, embercleave).converted_mana_cost == 6

    a1 = _bf(state, _creature("Attacker1"))
    a2 = _bf(state, _creature("Attacker2"))
    _bf(state, _creature("NonAttacker"))  # doesn't attack — must not count
    _bf(state, _creature("OpponentAttacker"), controller="p2")

    # No one is attacking yet.
    assert engine.effective_cast_cost(p1, embercleave).converted_mana_cost == 6

    a1.attacking = True
    a2.attacking = True
    state.battlefield[-1].attacking = True  # p2's creature — must not discount p1's cast
    assert engine.effective_cast_cost(p1, embercleave).converted_mana_cost == 4


def test_attacking_creatures_count_selector_unscoped_variant():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    a1 = _bf(state, _creature("A1"))
    a2 = _bf(state, _creature("A2"), controller="p2")
    a1.attacking = True
    a2.attacking = True
    from mtg_analyzer.game import continuous

    assert continuous.count_selector(state, "p1", "attacking_creatures_you_control") == 1
    assert continuous.count_selector(state, "p1", "attacking_creatures") == 2


def test_ancient_stone_idol_parses_bare_attacking_creature_reduction():
    card = Card(
        id="Ancient Stone Idol", name="Ancient Stone Idol",
        type_line="Creature — Construct", mana_cost_string="{7}", converted_mana_cost=7,
        is_creature=True, power=6, toughness=6,
        oracle_text=(
            "Flash\n"
            "This spell costs {1} less to cast for each attacking creature.\n"
            "Trample\n"
            "When this creature dies, create a 6/12 colorless Construct "
            "artifact creature token with trample."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled is True


# ---------------------------------------------------------------------------
# MEC-7: Timely Ward's conditional flash — "targets a commander"
# ---------------------------------------------------------------------------


def test_conditional_flash_targets_a_commander_engine_primitive():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    ward = _hand(
        p1,
        Card(
            id="Timely Ward", name="Timely Ward", type_line="Enchantment — Aura",
            mana_cost_string="{2}{W}", converted_mana_cost=3,
        ),
    )
    # `_hand` already binds — Timely Ward's conditional_flash comes from
    # the hand-authored catalogue entry (`game/ability_catalogue.py`).
    assert ward.conditional_flash == {"targets_a_commander": True}

    engine.state.current_step = "combat_damage"  # not a main phase, stack empty — instant speed needed
    p1.mana_pool.add("W", 1)
    p1.mana_pool.add("C", 2)

    # No commander anywhere: even the optimistic offer-time check refuses.
    assert engine.can_cast(p1, ward) is False

    commander = _bf(state, _creature("General Bob"), is_commander=True)
    non_commander = _bf(state, _creature("Nobody"))

    # Optimistic (targets not yet known): a commander exists somewhere, so
    # the flash-speed cast is offered.
    assert engine.can_cast(p1, ward) is True
    # Enforced (real chosen target): actually targeting the commander is legal...
    assert engine.can_cast(p1, ward, targets=[commander]) is True
    # ...but targeting a non-commander at instant speed is not.
    assert engine.can_cast(p1, ward, targets=[non_commander]) is False

    # Sorcery speed never cares about the target at all.
    engine.state.current_step = "main1"
    assert engine.can_cast(p1, ward, targets=[non_commander]) is True


def test_conditional_flash_holds_directly():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    commander = _bf(state, _creature("Cmd"), is_commander=True)
    non_commander = _bf(state, _creature("Nobody"))
    ward = _hand(p1, Card(id="Timely Ward", name="Timely Ward", type_line="Enchantment", mana_cost_string="{2}{W}", converted_mana_cost=3))

    cond = {"targets_a_commander": True}
    assert condition_query.conditional_flash_holds(cond, ward, state, targets=[commander]) is True
    assert condition_query.conditional_flash_holds(cond, ward, state, targets=[non_commander]) is False
    assert condition_query.conditional_flash_holds(cond, ward, state, targets=None) is True  # optimistic


def test_strive_line_parses_but_targets_a_commander_key_validates():
    spec = AbilitySpec("spell_effect", effects=[], conditional_flash={"targets_a_commander": True})
    spec.validate()  # must not raise
    bad = AbilitySpec("spell_effect", effects=[], conditional_flash={"targets_a_commander": "yes"})
    try:
        bad.validate()
        assert False, "expected SpecValidationError"
    except SpecValidationError:
        pass


def test_segmenter_recognizes_conditional_flash_targets_a_commander_clause():
    seg = _segment("You may cast this spell as though it had flash if it targets a commander.")
    assert seg.claimed is True
    assert seg.spec.conditional_flash == {"targets_a_commander": True}


# ---------------------------------------------------------------------------
# MEC-4: Strive — a per-extra-target cost escalation
# ---------------------------------------------------------------------------


def test_strive_cost_escalates_per_target_beyond_the_first():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    spell = Card(
        id="Test Strive Spell", name="Test Strive Spell", type_line="Instant",
        mana_cost_string="{1}{G}", converted_mana_cost=2, is_instant=True,
    )
    obj = _hand(p1, spell)
    spec = AbilitySpec("spell_effect", effects=[], strive_cost="{2}{U}", raw_text="Strive test")
    attach_to_object(obj, [spec])
    assert obj.strive_cost == ManaCost.parse("{2}{U}")

    c1 = _bf(state, _creature("C1"))
    c2 = _bf(state, _creature("C2"))
    c3 = _bf(state, _creature("C3"))

    assert engine.effective_cast_cost(p1, obj).converted_mana_cost == 2  # no targets known yet: base cost
    assert engine.effective_cast_cost(p1, obj, targets=[c1]).converted_mana_cost == 2
    assert engine.effective_cast_cost(p1, obj, targets=[c1, c2]).converted_mana_cost == 5
    assert engine.effective_cast_cost(p1, obj, targets=[c1, c2, c3]).converted_mana_cost == 8


def test_strive_cast_actually_charges_the_escalated_cost():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    spell = Card(
        id="Test Strive Bolt", name="Test Strive Bolt", type_line="Instant",
        mana_cost_string="{R}", converted_mana_cost=1, is_instant=True,
    )
    obj = _hand(p1, spell)
    spec = AbilitySpec("spell_effect", effects=[], strive_cost="{1}", raw_text="Strive test")
    attach_to_object(obj, [spec])

    c1 = _bf(state, _creature("C1"))
    c2 = _bf(state, _creature("C2"))

    p1.mana_pool.add("R", 1)
    # Base {R} is affordable with just the one red mana; {R} + one extra {1}
    # for the second target needs a second mana this pool doesn't have.
    assert engine.can_cast(p1, obj, targets=[c1]) is True
    assert engine.can_cast(p1, obj, targets=[c1, c2]) is False

    p1.mana_pool.add("C", 1)
    assert engine.can_cast(p1, obj, targets=[c1, c2]) is True


def test_strive_cost_spec_validation_rejects_malformed_cost():
    spec = AbilitySpec("spell_effect", effects=[], strive_cost="not a cost")
    try:
        spec.validate()
        assert False, "expected SpecValidationError"
    except SpecValidationError:
        pass


def test_segmenter_recognizes_strive_line():
    seg = _segment("Strive — This spell costs {2}{U} more to cast for each target beyond the first.")
    assert seg.claimed is True
    assert seg.spec.strive_cost == "{2}{U}"


# ---------------------------------------------------------------------------
# MEC-8: an emblem's own activated ability
# ---------------------------------------------------------------------------


_DRAW_EMBLEM_ABILITY = {
    "ability_kind": "activated",
    "effects": [{"type": "draw", "params": {"count": 1}}],
    "trigger": None,
    "cost": {"text": "{1}"},
    "target": None,
    "keyword": None,
    "modes": None,
    "additional_cost": None,
    "conditional_flash": None,
    "free_cast_condition": None,
    "optional": False,
    "raw_text": "{1}: Draw a card.",
}


def test_create_emblem_stores_activated_ability_instead_of_dropping_it():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    engine.rules.create_emblem(p1, _DRAW_EMBLEM_ABILITY)
    assert len(p1.emblems) == 1
    emblem = p1.emblems[0]
    assert len(emblem.activated_abilities) == 1
    assert emblem.triggered_abilities == []
    assert emblem.static_effects == []


def test_emblem_activated_ability_is_offered_and_playable_end_to_end():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    library_card = _creature("Forest-ish")
    p1.library.append(GameObject(library_card, owner_id="p1", zone=Zone.LIBRARY))

    engine.rules.create_emblem(p1, _DRAW_EMBLEM_ABILITY)
    emblem = p1.emblems[0]
    ability = emblem.activated_abilities[0]

    assert engine.can_activate(p1, emblem, ability) is False  # no mana yet
    p1.mana_pool.add("C", 1)
    assert engine.can_activate(p1, emblem, ability) is True

    actions = engine.legal_actions(p1)
    offered = [
        a for a in actions
        if a.get("type") == "activate_ability" and a.get("instance_id") == emblem.instance_id
    ]
    assert len(offered) == 1
    assert offered[0]["name"] == "Emblem"

    assert state.find_object(emblem.instance_id) is emblem

    before = len(p1.hand)
    engine.activate_ability(p1, emblem, 0)
    assert len(state.stack) == 1
    engine.rules.resolve_top_of_stack()
    assert len(p1.hand) == before + 1


def test_emblem_activated_ability_only_activatable_by_its_controller():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    engine.rules.create_emblem(p1, _DRAW_EMBLEM_ABILITY)
    emblem = p1.emblems[0]
    ability = emblem.activated_abilities[0]
    p2.mana_pool.add("C", 1)
    assert engine.can_activate(p2, emblem, ability) is False


# ---------------------------------------------------------------------------
# MEC-9: designation inheritance (RULE 725.4/726.4)
# ---------------------------------------------------------------------------


def test_monarch_and_initiative_pass_to_active_player_on_concede():
    engine, state = _engine("p1", "p2", "p3")
    engine.begin_turn()  # turn 1: p1 active
    p1, p2, p3 = state.players
    assert state.active_player.id == "p1"

    state.monarch_id = "p2"
    state.initiative_id = "p2"
    engine.rules.concede(p2)
    assert p2.has_lost is True
    assert "p2" in state.pending_leave_ids
    # Deferred: not swept yet.
    assert state.monarch_id == "p2"

    engine.begin_turn()  # rotates past p2 (has_lost), sweeps the departure
    assert state.active_player.id == "p3"
    assert state.monarch_id == "p3"
    assert state.initiative_id == "p3"


def test_designation_untouched_when_holder_stays():
    engine, state = _engine("p1", "p2", "p3")
    engine.begin_turn()
    p1, p2, p3 = state.players
    state.monarch_id = "p1"
    state.initiative_id = "p1"
    engine.rules.concede(p2)
    engine.begin_turn()
    assert state.monarch_id == "p1"
    assert state.initiative_id == "p1"


def test_no_designation_untouched_when_nobody_holds_one():
    engine, state = _engine("p1", "p2")
    engine.begin_turn()
    p1, p2 = state.players
    assert state.monarch_id is None
    engine.rules.concede(p2)
    # Only one living player left — concede already ends the game, so the
    # sweep (and any designation-inheritance logic) never runs.
    assert state.game_over is True


def test_taking_initiative_via_succession_fires_took_initiative_event():
    """RULE 726.4 says the active player *takes* the initiative — this must
    go through `RulesEngine.take_initiative` (which fires `TOOK_INITIATIVE`,
    RULE 726.2's third inherent trigger), not a bare field assignment."""
    from mtg_analyzer.models.events import EventType

    engine, state = _engine("p1", "p2", "p3")
    engine.begin_turn()
    p1, p2, p3 = state.players
    state.initiative_id = "p2"

    engine.rules.concede(p2)
    engine.begin_turn()
    assert state.initiative_id == "p3"

    took = [e for e in state.event_log if e.type == EventType.TOOK_INITIATIVE]
    assert len(took) == 1
    assert took[0].get("player_id") == "p3"
