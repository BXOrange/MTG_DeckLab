"""PAR-40 — the "If that creature would die this turn, exile it instead."
damage / pump / fight rider.

`segmenter._DIE_TO_EXILE_SENTENCE_RE` splits the trailing sentence off the
same way `_NO_REGEN_SENTENCE_RE` handles "It can't be regenerated." — the
"before" clause is parsed on its own, and (only if it announces a
creature/permanent target) a `grant_die_to_exile_this_turn` spec with
`previous_subject=True` is appended. `GrantDieToExileThisTurnEffect` gained
the matching `previous_subject` mode: no RULE 115 target of its own, it arms
its `WOULD_DIE` -> exile `ReplacementEffect` on every
`GameContext.previous_targets` entry.

Real cards: Magma Spray / Feed the Flames / Bot Bashing Time / Elspeth's
Smite / Puncturing Blow (damage), Bleed Dry (-13/-13 pump), Mawloc / Suplex
(fight).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, pid, toughness=2):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=2, toughness=toughness),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_damage_rider_splits_into_two_specs():
    assert parse_effect_body(
        "~ deals 2 damage to target creature. if that creature would die this turn, exile it instead"
    ) == [
        EffectSpec("damage", {"amount": 2, "target_kind": "creature"}),
        EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True}),
    ]


def test_pump_rider_splits_into_two_specs():
    specs = parse_effect_body(
        "target creature gets -13/-13 until end of turn. "
        "if that creature would die this turn, exile it instead"
    )
    assert specs is not None
    assert specs[-1] == EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})
    assert specs[0].type == "pump"


def test_rider_fails_closed_without_a_creature_antecedent():
    # "you draw a card" chooses nothing — the rider has no referent.
    assert parse_effect_body(
        "you draw a card. if that creature would die this turn, exile it instead"
    ) is None


def test_real_cards_modeled():
    for name, text in [
        ("Magma Spray",
         "Magma Spray deals 2 damage to target creature. "
         "If that creature would die this turn, exile it instead."),
        ("Bleed Dry",
         "Target creature gets -13/-13 until end of turn. "
         "If that creature would die this turn, exile it instead."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Instant", is_instant=True,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_previous_subject_grant_exiles_the_creature_on_a_later_death():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Magma Spray", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    victim = _creature(state, "Their Bear", "p2", toughness=4)
    eng.recompute_continuous_effects()

    ctx = GameContext(state, eng.rules)
    dmg, grant = build_effects([
        EffectSpec("damage", {"amount": 2, "target_kind": "creature"}),
        EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True}),
    ], src)
    dmg.apply(ctx, [victim])
    ctx.previous_targets = [victim]
    grant.apply(ctx, None)

    # Not dead yet (2 marked on a 2/4) — replacement is armed, waiting.
    eng.rules.check_state_based_actions()
    assert victim in state.battlefield

    # More damage this turn brings it to lethal → it's exiled, not milled to the graveyard.
    victim.damage_marked = 4
    eng.rules.check_state_based_actions()
    assert victim not in state.battlefield
    assert victim.zone == Zone.EXILE
    assert victim not in state.player_by_id("p2").graveyard


def test_grant_expires_when_the_turn_moves_on():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Magma Spray", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    victim = _creature(state, "Sturdy Bear", "p2", toughness=4)
    eng.recompute_continuous_effects()

    ctx = GameContext(state, eng.rules)
    grant = build_effects(
        [EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})], src
    )[0]
    ctx.previous_targets = [victim]
    grant.apply(ctx, None)

    state.internal_turn.number += 2  # a later turn — the baked-in condition no longer matches
    victim.damage_marked = 9
    eng.rules.check_state_based_actions()
    assert victim.zone == Zone.GRAVEYARD  # ordinary death, no redirect
