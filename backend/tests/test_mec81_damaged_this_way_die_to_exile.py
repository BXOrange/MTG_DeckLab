"""MEC-81 — group-scoped die-to-exile arm (RULE 616).

The die-to-exile rider ("If a creature dealt damage this way would die this
turn, exile it instead.") could only arm on one previously *targeted*
creature (`GameContext.previous_targets`), so it failed closed after **mass**
or **multi-target** damage, which never populates that list with the hit set.

`GameContext.damaged_this_way` records every permanent an earlier
`deal_damage` clause of the same resolution actually hit;
`GrantDieToExileThisTurnEffect(damaged_this_way=True)` arms the RULE 616
`WOULD_DIE`→exile replacement on exactly that set.

Reference: game/effects/core.py (`GameContext.deal_damage`,
`_apply_effects_partitioned`, `GrantDieToExileThisTurnEffect`),
parser/oracle/segmenter.py (`_DIE_TO_EXILE_SENTENCE_RE` use-site).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, name, pid, power=2, toughness=2):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=power, toughness=toughness),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    o.summoning_sick = False
    state.add_to_battlefield(o)
    return o


# --- parser -------------------------------------------------------------


def test_mass_damage_rider_parses_to_damaged_this_way():
    assert parse_effect_body(
        "~ deals 3 damage to each creature. "
        "if a creature dealt damage this way would die this turn, exile it instead"
    ) == [
        EffectSpec("damage", {"amount": 3, "selector": "each_creature"}),
        EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True}),
    ]


def test_any_target_permanent_phrasing_parses():
    assert parse_effect_body(
        "~ deals 2 damage to any target. "
        "if a permanent dealt damage this way would die this turn, exile it instead"
    ) == [
        EffectSpec("damage", {"amount": 2, "target_kind": "any"}),
        EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True}),
    ]


def test_non_damage_before_still_uses_previous_subject():
    specs = parse_effect_body(
        "target creature gets -13/-13 until end of turn. "
        "if that creature would die this turn, exile it instead"
    )
    assert specs is not None
    assert specs[-1] == EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})


def test_real_mass_cards_now_modeled():
    for name in ("Anger of the Gods", "Crush the Weak", "Yamabushi's Storm",
                 "Underworld Fires", "Pillar of Flame"):
        from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
        c = CardDatabase(DEFAULT_DB_PATH).get_card(name)
        assert c is not None, name
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ----------------------------------------------------------


def test_damaged_this_way_arms_exile_on_every_hit_creature():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="src", name="Anger of the Gods", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    a = _creature(state, "A", "p1", toughness=3)
    b = _creature(state, "B", "p2", toughness=3)
    big = _creature(state, "Big", "p2", toughness=6)
    eng.recompute_continuous_effects()

    ctx = GameContext(state, eng.rules)
    dmg, grant = build_effects([
        EffectSpec("damage", {"amount": 3, "selector": "each_creature"}),
        EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True}),
    ], src)
    dmg.apply(ctx, None)
    # all three were hit and recorded
    assert set(ctx.damaged_this_way) == {a, b, big}
    grant.apply(ctx, None)

    # a and b are 3-toughness with 3 marked → they die → exiled, not graveyard
    eng.rules.check_state_based_actions()
    assert a.zone == Zone.EXILE and a not in state.battlefield
    assert b.zone == Zone.EXILE and b not in state.battlefield
    # big survived (6 toughness), and its armed replacement never fired
    assert big in state.battlefield


def test_a_creature_not_hit_this_way_is_not_armed():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="src", name="Fanged Flames", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    hit = _creature(state, "Hit", "p2", toughness=4)
    bystander = _creature(state, "Bystander", "p2", toughness=1)
    eng.recompute_continuous_effects()

    ctx = GameContext(state, eng.rules)
    dmg, grant = build_effects([
        EffectSpec("damage", {"amount": 2, "target_kind": "creature"}),
        EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True}),
    ], src)
    dmg.apply(ctx, [hit])
    grant.apply(ctx, None)
    assert ctx.damaged_this_way == [hit]

    # the bystander dies to an unrelated effect this turn → ordinary graveyard,
    # because the rider was scoped to the hit set only (RULE 616).
    eng.rules.destroy(bystander)
    eng.rules.check_state_based_actions()
    assert bystander.zone == Zone.GRAVEYARD


def test_damage_to_a_player_does_not_land_in_damaged_this_way():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="src", name="Pillar of Flame", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    p2 = state.player_by_id("p2")
    ctx = GameContext(state, eng.rules)
    ctx.deal_damage(p2, 2, src)
    assert ctx.damaged_this_way == []
