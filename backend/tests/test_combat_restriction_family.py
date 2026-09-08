"""Batch 2 (docs/implementation-state/BACKLOG.md): the
combat/evasion static-restriction family.

Covers the printed self/attached-permanent statics that block RULE 508/509
combat actions outright — as opposed to the many *targeted, resolve-time*
"target creature can't block this turn" activated/triggered effects, which
are a separate, still-unmodeled family (deliberately out of scope here):

* ``~ can't attack.`` / ``~ can't block.`` / ``~ can't be blocked.`` / ``~
  can't attack or block[, and its activated abilities can't be activated].``
  / ``~ can't block and can't be blocked.`` / ``~ attacks each combat if
  able.`` — and the identical Aura/Equipment "enchanted/equipped <subject>"
  phrasings.

Modeled as synthetic layer-6 "keyword" flags (``cant_attack``/``cant_block``/
``cant_be_blocked``/``attacks_if_able`` — not real RULE 702 keywords) reusing
the existing ``grant_keyword``/``activation_prohibition`` `StaticAbility`
machinery with no new engine primitive beyond three small predicate checks
(`GameEngine._can_attack`/`can_block`/`_enforce_attacks_if_able`). Also covers
a Batch-1 regression fix: the self-reference fold ("this creature"→``~``)
left `_NO_UNTAP_RE`'s old "this <type>" wording dead, and generalizes
``no_untap`` to the attached-permanent phrasing (Paralyzing Grasp-shaped).

Each restriction test drives real oracle text through `parse_oracle`
(asserting the card is fully ``MODELED``) **and** binds + exercises it
against a real `GameEngine`/`combat.py`, per the project's "parse-only
verification has masked real runtime bugs" lesson (memory:
oracle-parser-coverage).

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/{effect_binder,effects,continuous,combat,game_engine}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text, power=2, toughness=2, keywords=None, type_line="Creature — Dragon"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _aura(name, oracle_text):
    return Card(
        id=name, name=name, type_line="Enchantment — Aura",
        oracle_text=oracle_text,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _battlefield_obj(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- parse-side coverage ------------------------------------------------------


def test_cant_attack_is_modeled():
    card = _creature("Wall of Vapor", "~ can't attack.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_cant_block_is_modeled():
    card = _creature("Rampant Beast", "~ can't block.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_cant_be_blocked_is_modeled():
    card = _creature("Slippery Rogue", "~ can't be blocked.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_cant_block_and_cant_be_blocked_is_modeled():
    card = _creature("Lone Duelist", "~ can't block and can't be blocked.")
    assert parse_oracle(card).unclaimed == []


def test_attacks_each_combat_if_able_is_modeled():
    card = _creature("Berserker", "~ attacks each combat if able.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_cant_attack_or_block_with_named_self_reference_is_modeled():
    # The card's own printed name folds to ~ too (normalize._fold_self_name).
    card = _creature("Sleeping Giant", "Sleeping Giant can't attack or block.")
    assert parse_oracle(card).unclaimed == []


def test_attached_cant_attack_or_block_with_activation_lock_is_modeled():
    card = _aura(
        "Paralyzing Grasp",
        "Enchant creature\n"
        "Enchanted creature can't attack or block, and its activated "
        "abilities can't be activated.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_no_untap_self_reference_is_modeled():
    card = Card(
        id="Basalt Monolith", name="Basalt Monolith", type_line="Artifact",
        oracle_text="{T}: Add {C}{C}{C}.\n~ doesn't untap during your untap step.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_no_untap_attached_permanent_is_modeled():
    card = _aura(
        "Paralyzing Grasp Lite",
        "Enchant creature\n"
        "Enchanted creature doesn't untap during its controller's untap step.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_qualified_variants_outside_the_vocabulary_stay_unclaimed():
    # Still fail-closed where it matters: a qualified restriction whose
    # filter or condition isn't in the closed vocabulary must leave the whole
    # clause unclaimed rather than silently drop the qualifier and claim the
    # plain restriction — that would be actively wrong, not merely missing.
    # (The recognised qualified shapes are covered in
    # `test_qualified_combat_restrictions.py`/
    # `test_combat_restriction_dynamic_thresholds.py` — the latter now
    # includes the "count of Islands you control" dynamic-threshold shape
    # this test used to cite as an *unclaimed* example, before it shipped.)
    pay_cost = _creature(
        # A cost-payment "unless" — the RULE 601-area prohibition/cost family,
        # deliberately not part of the board-state condition vocabulary.
        "Toll Beast", "~ can't attack unless its controller pays {3}."
    )
    board_count_threshold = _creature(
        # A count-selector threshold this codebase has no vocabulary for at
        # all (a *creature* count, not "you control N lands of a type") —
        # unlike Kraken of the Straits' Islands-count shape, which now ships.
        "Threshold Beast",
        "Creatures with power less than the number of creatures you control "
        "can't block ~.",
    )
    assert parse_oracle(pay_cost).coverage == UNMODELED
    assert parse_oracle(board_count_threshold).coverage == UNMODELED


# -- execute-side (bind → engine) --------------------------------------------


def test_cant_attack_flag_blocks_attack_declaration():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(state, _creature("Wall of Vapor", "~ can't attack."))
    continuous.recompute(state)

    assert combat.has(obj, "cant_attack") is True
    assert eng._can_attack(state.active_player, obj) is False


def test_cant_block_flag_blocks_declared_block():
    eng = _engine()
    state = eng.state
    attacker = _battlefield_obj(state, _creature("Raider", "", power=2, toughness=2), controller="p1")
    blocker = _battlefield_obj(
        state, _creature("Rampant Beast", "~ can't block.", power=2, toughness=2), controller="p2"
    )
    continuous.recompute(state)

    defender = state.player_by_id("p2")
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}

    assert combat.has(blocker, "cant_block") is True
    assert eng.can_block(defender, blocker, attacker) is False


def test_cant_be_blocked_flag_prevents_any_block():
    eng = _engine()
    state = eng.state
    attacker = _battlefield_obj(
        state, _creature("Slippery Rogue", "~ can't be blocked.", power=2, toughness=2), controller="p1"
    )
    blocker = _battlefield_obj(state, _creature("Bear", "", power=2, toughness=2), controller="p2")
    continuous.recompute(state)

    defender = state.player_by_id("p2")
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2", "label": "Bob"}

    assert combat.has(attacker, "cant_be_blocked") is True
    # An otherwise perfectly legal blocker still can't block it.
    assert eng.can_block(defender, blocker, attacker) is False


def test_attacks_if_able_forces_declaration_before_advancing():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(state, _creature("Berserker", "~ attacks each combat if able."))
    continuous.recompute(state)
    assert combat.has(obj, "attacks_if_able") is True

    eng.start()
    step_name = None
    while step_name != "declare_attackers":
        step_name = eng.advance_step()[1]

    # Able to attack (untapped, not sick, opponent present) but not declared.
    with pytest.raises(ValueError):
        eng.advance_step()

    # Declaring the forced attacker lets the step close normally.
    eng.declare_attackers(state.active_player, [obj])
    eng.advance_step()
    assert obj.attacking is True


def test_attached_permanent_cant_attack_or_block_and_activation_lock():
    eng = _engine()
    state = eng.state
    host = _battlefield_obj(state, _creature("Bear", "", power=2, toughness=2), controller="p1")
    aura = _battlefield_obj(
        state,
        _aura(
            "Paralyzing Grasp",
            "Enchant creature\n"
            "Enchanted creature can't attack or block, and its activated "
            "abilities can't be activated.",
        ),
        controller="p2",
    )
    aura.attached_to = host.instance_id
    continuous.recompute(state)

    assert combat.has(host, "cant_attack") is True
    assert combat.has(host, "cant_block") is True
    assert eng._can_attack(state.active_player, host) is False
    assert continuous.activation_prohibited(state, host) is True


def test_no_untap_attached_permanent_stops_untap_step():
    eng = _engine()
    state = eng.state
    host = _battlefield_obj(state, _creature("Bear", "", power=2, toughness=2), controller="p1")
    host.tapped = True
    aura = _battlefield_obj(
        state,
        _aura(
            "Paralyzing Grasp Lite",
            "Enchant creature\n"
            "Enchanted creature doesn't untap during its controller's untap step.",
        ),
        controller="p2",
    )
    aura.attached_to = host.instance_id
    continuous.recompute(state)

    assert continuous.has_no_untap_static(state, host) is True
    assert state.active_player.id == "p1"

    eng._step_untap()
    assert host.tapped is True  # stayed tapped, the static held it down
