"""MEC-12 (cEDH staples/staples 2) — Defense Grid / Suppression Field /
Tithe Taker's "costs {N} more" tax family, on both a spell's cast cost and
an activated ability's own activation cost.

New primitives:
  * `continuous.cost_reduction_for` gained the ordinary ability-source-
    relative ``active_if`` check it had never consulted (a latent gap —
    `cost_floor_for`, the very next function in the same file, already had
    it) plus a genuinely new ``except_caster_own_turn`` rider — "except
    during **its controller's** turn" (Defense Grid) means the *taxed
    spell's own caster*, not the tax's own controller, so it's checked
    directly against `cost_reduction_for`'s own ``player`` argument rather
    than routed through the source-relative vocabulary.
  * `continuous.activation_cost_reduction_for` widened from "reduction
    only, three named scopes" to a signed net (a real tax, not just a
    discount) across five scopes (adding unscoped ``all_permanents`` and
    ``opponents_permanents``), an ``is_mana_ability``/``except_mana_
    abilities`` carve-out mirroring `activation_prohibited`'s own, and the
    same ``active_if`` gate.
  * `GameEngine._reduced_activation_mana` now actually applies a negative
    net as `ManaCost.increase_generic` instead of silently discarding it
    (`if reduction <= 0: return mana` used to eat every tax outright) —
    `is_mana_ability` threaded through `_can_pay_activation_cost`/
    `_pay_activation_cost`/`tap_for_mana` so the carve-out reaches a real
    mana ability's own payment, not just its legality check.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import ActivatedAbility, DrawCardEffect

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _with_ability(eng, card, cost_text, effects, controller="p1"):
    obj = obj_on_battlefield(eng.state, eng, card, controller=controller)
    ability = ActivatedAbility(effects=effects, cost=parse_activation_cost(cost_text), source=obj)
    obj.activated_abilities.append(ability)
    return obj, ability


# ---------------------------------------------------------------------------
# Defense Grid — spell tax, exempt on the *caster's own* turn
# ---------------------------------------------------------------------------


def test_defense_grid_taxes_a_spell_off_the_casters_own_turn():
    eng = make_engine([], [creature("Bear")], hand=0)
    grid = obj_on_battlefield(eng.state, eng, _named("Defense Grid"), controller="p1")
    bind_from_catalogue(grid)
    eng.begin_turn()  # p1's turn
    p2 = eng.state.player_by_id("p2")
    bear = p2.library.pop()
    p2.hand.append(bear)

    net, _ = continuous.cost_reduction_for(eng.state, p2, bear)
    assert net == -3  # taxed: it isn't p2's own turn


def test_defense_grid_exempts_the_casters_own_turn():
    eng = make_engine([creature("Bear")], [], hand=0)
    grid = obj_on_battlefield(eng.state, eng, _named("Defense Grid"), controller="p2")
    bind_from_catalogue(grid)
    eng.begin_turn()  # p1's turn
    p1 = eng.state.player_by_id("p1")
    bear = p1.library.pop()
    p1.hand.append(bear)

    net, _ = continuous.cost_reduction_for(eng.state, p1, bear)
    assert net == 0  # p1's own turn — exempt, even though p2 owns the Grid


# ---------------------------------------------------------------------------
# Suppression Field — unscoped activation tax, mana-ability carve-out
# ---------------------------------------------------------------------------


def test_suppression_field_taxes_a_non_mana_activated_ability():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    field = obj_on_battlefield(eng.state, eng, _named("Suppression Field"), controller="p1")
    bind_from_catalogue(field)
    bear, ability = _with_ability(
        eng, creature("Bear"), "{T}: Draw a card.", [DrawCardEffect(1, player=p1)], controller="p1",
    )
    p1.mana_pool.add_many({"C": 2})

    eng.activate_ability(p1, bear)
    assert p1.mana_pool.total() == 0  # {0} base + {2} tax, all spent


def test_suppression_field_leaves_mana_abilities_alone():
    eng = make_engine([], [], hand=0)
    field = obj_on_battlefield(eng.state, eng, _named("Suppression Field"), controller="p1")
    bind_from_catalogue(field)
    elves = obj_on_battlefield(eng.state, eng, _named("Llanowar Elves"), controller="p1")
    bind_from_catalogue(elves)

    produced = eng.tap_for_mana(eng.state.player_by_id("p1"), elves)
    assert produced.get("G") == 1  # no {2} tax charged — it's a mana ability


# ---------------------------------------------------------------------------
# Tithe Taker — opponents-only, gated by the controller's own turn
# ---------------------------------------------------------------------------


def test_tithe_taker_taxes_opponents_spells_only_during_its_controllers_turn():
    eng = make_engine([], [creature("Bear")], hand=0)
    tithe = obj_on_battlefield(eng.state, eng, _named("Tithe Taker"), controller="p1")
    bind_from_catalogue(tithe)
    eng.begin_turn()  # p1's own turn — the tax is on
    p2 = eng.state.player_by_id("p2")
    bear = p2.library.pop()
    p2.hand.append(bear)

    net, _ = continuous.cost_reduction_for(eng.state, p2, bear)
    assert net == -1

    # p1's own spells are never taxed by their own Tithe Taker.
    p1 = eng.state.player_by_id("p1")
    net_own, _ = continuous.cost_reduction_for(eng.state, p1, bear)
    assert net_own == 0


def test_tithe_taker_tax_turns_off_outside_its_controllers_turn():
    eng = make_engine([creature("Bear")], [], hand=0)
    tithe = obj_on_battlefield(eng.state, eng, _named("Tithe Taker"), controller="p2")
    bind_from_catalogue(tithe)
    eng.begin_turn()  # p1's turn, not the Tithe Taker controller's
    p1 = eng.state.player_by_id("p1")
    bear = p1.library.pop()
    p1.hand.append(bear)

    net, _ = continuous.cost_reduction_for(eng.state, p1, bear)
    assert net == 0  # p1 is p2's opponent, but it isn't p2's turn


def test_tithe_taker_taxes_an_opponents_non_mana_ability_during_its_controllers_turn():
    eng = make_engine([], [], hand=0)
    tithe = obj_on_battlefield(eng.state, eng, _named("Tithe Taker"), controller="p1")
    bind_from_catalogue(tithe)
    eng.begin_turn()  # p1's own turn
    p2 = eng.state.player_by_id("p2")
    bear, ability = _with_ability(
        eng, creature("Bear"), "{T}: Draw a card.", [DrawCardEffect(1, player=p2)], controller="p2",
    )
    p2.mana_pool.add_many({"C": 1})

    eng.activate_ability(p2, bear)
    assert p2.mana_pool.total() == 0  # {0} base + {1} tax, all spent
