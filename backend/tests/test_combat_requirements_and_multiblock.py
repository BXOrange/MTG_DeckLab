"""RULE 508/509's requirement and multi-block-permission families — the
three shapes `test_qualified_combat_restrictions.py`'s batch deliberately
left open (see `ToDo_Backend.md`'s post-batch-27 "Combat statics" residue):

* **Combat requirements** (RULE 509.1c/d) — "~ must be blocked if able."/
  "All creatures able to block ~ do so." as synthetic flag keywords (the
  same `grant_keyword` plumbing `attacks_if_able` already uses), checked by
  `GameEngine._enforce_block_requirements` as the declare-blockers step
  closes; plus the resolve-time, *pairwise* siblings "target creature
  blocks ~ this turn if able."/"…can't block ~ this turn." (naming a
  specific attacker, so they ride `GrantCombatRestrictionEffect`'s
  ``restrict_to_source``) and "target creature attacks this turn if able."
  (a plain temporary keyword grant — no new engine code at all).
* **Multi-block permissions** (RULE 509.1b) — "~ can block an additional
  creature each combat."/"~ can block any number of creatures." — a
  blocker's own capacity (`GameObject.additional_blocking`, `game/combat.py`'s
  `max_blocks_for`/`has_block_capacity`), and combat damage dividing evenly
  across every attacker a multi-blocker ends up blocking
  (`GameEngine._split_blocker_damage`).

Each test drives real oracle text through `parse_oracle` (asserting the card
is fully `MODELED`) **and** binds + exercises it against a real
`GameEngine`, per the project's "parse-only verification has masked real
runtime bugs" lesson (memory: oracle-parser-coverage).

Reference: mtg_analyzer/parser/oracle/catalogue/{static_handlers,handlers}.py,
mtg_analyzer/game/{combat,continuous,effects,game_engine}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Dragon"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _modeled(card):
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    assert result.unclaimed == []
    return result


def _to_declare_attackers(eng):
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()


# -- Combat requirements: standing statics (RULE 509.1c/d) -------------------


def test_must_be_blocked_if_able_is_enforced_leaving_declare_blockers():
    card = _creature("Provoked Ogre", "~ must be blocked if able.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    blocker = _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)
    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()  # → declare_blockers
    assert state.current_step == "declare_blockers"

    with pytest.raises(ValueError):
        eng.advance_step()  # Bear could block it, but didn't

    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker}])
    eng.advance_step()
    assert attacker.blocked_by == [blocker.instance_id]


def test_must_be_blocked_if_able_is_excused_with_no_legal_blocker():
    # Flying, with only a grounded creature on defense — nothing is *able*
    # to block it, so the requirement doesn't bite at all.
    card = _creature("Provoked Drake", "~ must be blocked if able.", keywords=["Flying"])
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)
    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()
    eng.advance_step()  # no ValueError: no candidate was able to block


def test_all_must_block_forces_every_able_creature():
    card = _creature("Lured Beast", "All creatures able to block ~ do so.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    a = _put(state, _creature("Bear A"), controller="p2")
    b = _put(state, _creature("Bear B"), controller="p2")
    continuous.recompute(state)
    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()
    defender = state.player_by_id("p2")

    with pytest.raises(ValueError):
        eng.advance_step()  # neither has blocked yet

    eng.declare_blockers(defender, [{"blocker": a, "attacker": attacker}])
    with pytest.raises(ValueError):
        eng.advance_step()  # b is still able and still hasn't

    eng.declare_blockers(defender, [{"blocker": b, "attacker": attacker}])
    eng.advance_step()
    assert set(attacker.blocked_by) == {a.instance_id, b.instance_id}


def test_all_must_block_excuses_a_blocker_already_committed_elsewhere():
    # RULE 509.1c: when two requirements can't both be satisfied (one
    # shared, ordinary one-block-each blocker), the defending player's
    # actual choice is honoured rather than optimized around — no full
    # requirement-satisfaction solver, matching `_enforce_block_requirements`'s
    # docstring.
    lure_one = _creature("Lured Beast One", "All creatures able to block ~ do so.")
    lure_two = _creature("Lured Beast Two", "All creatures able to block ~ do so.")
    _modeled(lure_one)
    _modeled(lure_two)

    eng = _engine()
    state = eng.state
    attacker_one = _put(state, lure_one)
    attacker_two = _put(state, lure_two)
    only_blocker = _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)
    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker_one, attacker_two])
    eng.advance_step()
    defender = state.player_by_id("p2")

    eng.declare_blockers(defender, [{"blocker": only_blocker, "attacker": attacker_one}])
    eng.advance_step()  # attacker_two's requirement is excused: no one left to satisfy it
    assert attacker_one.blocked_by == [only_blocker.instance_id]
    assert attacker_two.blocked_by == []


def test_all_must_block_attached_form():
    # Lure itself: the aura, not the host, prints the requirement.
    aura = Card(
        id="Lure", name="Lure", type_line="Enchantment — Aura",
        oracle_text="Enchant creature\nAll creatures able to block enchanted creature do so.",
    )
    _modeled(aura)

    eng = _engine()
    state = eng.state
    host = _put(state, _creature("Bear"))
    enchantment = _put(state, aura)
    enchantment.attached_to = host.instance_id
    a = _put(state, _creature("Blocker A"), controller="p2")
    continuous.recompute(state)
    assert combat.has(host, "all_must_block") is True

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [host])
    eng.advance_step()

    with pytest.raises(ValueError):
        eng.advance_step()
    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [{"blocker": a, "attacker": host}])
    eng.advance_step()
    assert host.blocked_by == [a.instance_id]


# -- Combat requirements: resolve-time, pairwise (RULE 509.1c) ---------------


def test_target_creature_must_block_source_this_turn_if_able():
    card = _creature("Goad Master", "{1}{R}: Target creature blocks ~ this turn if able.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    # High toughness on both sides so nothing dies in combat damage — this
    # test is about the requirement/cleanup bookkeeping, not lethality.
    reluctant = _put(state, _creature("Bear", toughness=5), controller="p2")
    continuous.recompute(state)

    ability = attacker.activated_abilities[0]
    ability.effects[0].apply(eng.rules, [reluctant])
    assert combat.combat_restrictions(reluctant, "must_block_target") == [
        {"kind": "must_block_target", "filter": {"instance_id": attacker.instance_id}}
    ]

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()  # → declare_blockers
    defender = state.player_by_id("p2")

    with pytest.raises(ValueError):
        eng.advance_step()  # reluctant is able to block, but hasn't

    eng.declare_blockers(defender, [{"blocker": reluctant, "attacker": attacker}])
    eng.advance_step()
    assert attacker.blocked_by == [reluctant.instance_id]

    eng._step_cleanup()  # RULE 514.2
    assert reluctant.temp_combat_restrictions == []


def test_must_block_source_this_turn_only_binds_that_one_attacker():
    # The pairwise requirement can't be satisfied by blocking some *other*
    # attacker — it names a specific instance id, not "attack in general".
    # `reluctant` gets spare block capacity so this isn't just re-testing
    # "already committed elsewhere" (the *previous* test's shape) — it's
    # genuinely still able to block `named_attacker` too, and doesn't.
    card = _creature("Goad Master", "{1}{R}: Target creature blocks ~ this turn if able.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    named_attacker = _put(state, card)
    other_attacker = _put(state, _creature("Raider"))
    reluctant = _put(
        state, _creature("Bear", "~ can block an additional creature each combat."),
        controller="p2",
    )
    continuous.recompute(state)

    ability = named_attacker.activated_abilities[0]
    ability.effects[0].apply(eng.rules, [reluctant])

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [named_attacker, other_attacker])
    eng.advance_step()
    defender = state.player_by_id("p2")

    # Blocking the *other* attacker doesn't satisfy the pairwise requirement,
    # even with a spare block slot still open.
    eng.declare_blockers(defender, [{"blocker": reluctant, "attacker": other_attacker}])
    assert combat.has_block_capacity(reluctant) is True
    with pytest.raises(ValueError):
        eng.advance_step()


def test_target_creature_cant_block_source_this_turn():
    card = _creature("Deflector", "{1}: Target creature can't block ~ this turn.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    other_attacker = _put(state, _creature("Raider"))
    blocker = _put(state, _creature("Bear"), controller="p2")
    continuous.recompute(state)

    defender = state.player_by_id("p2")
    other_attacker.attacking = True
    other_attacker.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}
    assert eng.can_block(defender, blocker, attacker) is True
    assert eng.can_block(defender, blocker, other_attacker) is True

    ability = attacker.activated_abilities[0]
    ability.effects[0].apply(eng.rules, [blocker])

    # Barred from blocking *this* attacker specifically…
    assert eng.can_block(defender, blocker, attacker) is False
    # …but still perfectly able to block a different one.
    assert eng.can_block(defender, blocker, other_attacker) is True

    eng._step_cleanup()
    assert blocker.temp_combat_restrictions == []
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}
    assert eng.can_block(defender, blocker, attacker) is True


def test_target_creature_attacks_this_turn_if_able():
    card = Card(
        id="Goad", name="Goad", type_line="Sorcery", is_sorcery=True,
        oracle_text="Target creature attacks this turn if able.",
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    target = _put(state, _creature("Bear"))
    continuous.recompute(state)

    # The resolve-time grant is a plain `temp_keywords` addition (`PumpEffect`,
    # here applied the same direct way `test_continuous.py`'s "until end of
    # turn" tests do) — `combat.has()` already unions it in via
    # `granted_keywords`, so `_enforce_attacks_if_able` needs no new code.
    target.temp_keywords.add("attacks_if_able")
    continuous.recompute(state)
    assert combat.has(target, "attacks_if_able") is True

    eng.start()
    _to_declare_attackers(eng)
    with pytest.raises(ValueError):
        eng.advance_step()  # able to attack, but not declared

    eng.declare_attackers(state.active_player, [target])
    eng.advance_step()
    assert target.attacking is True

    eng._step_cleanup()
    continuous.recompute(state)
    assert combat.has(target, "attacks_if_able") is False


# -- Multi-block permissions (RULE 509.1b) -----------------------------------


def test_extra_blocks_lets_one_creature_block_two_attackers():
    card = _creature("Doubling Wall", "~ can block an additional creature each combat.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    attacker_one = _put(state, _creature("Raider One"))
    attacker_two = _put(state, _creature("Raider Two"))
    continuous.recompute(state)
    assert combat.max_blocks_for(blocker) == 2

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker_one, attacker_two])
    eng.advance_step()
    defender = state.player_by_id("p2")

    assert eng.can_block(defender, blocker, attacker_one) is True
    eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker_one}])
    assert eng.can_block(defender, blocker, attacker_two) is True
    eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker_two}])

    assert combat.blocking_attacker_ids(blocker) == [
        attacker_one.instance_id, attacker_two.instance_id
    ]
    # A third would be one too many — capacity is exactly 2.
    assert combat.has_block_capacity(blocker) is False


def test_extra_blocks_splits_damage_evenly_across_both_attackers():
    card = _creature(
        "Doubling Wall", "~ can block an additional creature each combat.",
        power=4, toughness=6,
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    attacker_one = _put(state, _creature("Raider One", power=2, toughness=2))
    attacker_two = _put(state, _creature("Raider Two", power=2, toughness=2))
    continuous.recompute(state)
    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker_one, attacker_two])
    eng.advance_step()
    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [
        {"blocker": blocker, "attacker": attacker_one},
        {"blocker": blocker, "attacker": attacker_two},
    ])
    eng.advance_step()  # combat damage

    # 4 power split evenly across 2 blocked attackers → 2 each, both die.
    assert attacker_one not in state.battlefield
    assert attacker_two not in state.battlefield
    # The blocker itself took 2 + 2 = 4 damage against 6 toughness — it lives.
    assert blocker in state.battlefield
    assert blocker.damage_marked == 4


def test_unlimited_blocks_has_no_capacity_cap():
    card = _creature("Wall of All", "~ can block any number of creatures.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    blocker = _put(state, card, controller="p2")
    attackers = [_put(state, _creature(f"Raider {i}")) for i in range(4)]
    continuous.recompute(state)
    assert combat.max_blocks_for(blocker) is None

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, attackers)
    eng.advance_step()
    defender = state.player_by_id("p2")
    for attacker in attackers:
        assert eng.can_block(defender, blocker, attacker) is True
        eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker}])

    assert combat.blocking_attacker_ids(blocker) == [a.instance_id for a in attackers]
    assert combat.has_block_capacity(blocker) is True


def test_ordinary_blocker_still_capped_at_one():
    eng = _engine()
    state = eng.state
    blocker = _put(state, _creature("Bear"), controller="p2")
    attacker_one = _put(state, _creature("Raider One"))
    attacker_two = _put(state, _creature("Raider Two"))
    continuous.recompute(state)
    assert combat.max_blocks_for(blocker) == 1

    eng.start()
    _to_declare_attackers(eng)
    eng.declare_attackers(state.active_player, [attacker_one, attacker_two])
    eng.advance_step()
    defender = state.player_by_id("p2")
    eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker_one}])
    assert eng.can_block(defender, blocker, attacker_two) is False
