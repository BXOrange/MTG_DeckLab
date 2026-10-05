"""Tests for the mana pool and its cost-payment solver.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.6, mtg_analyzer/models/mana_pool.py.
"""

import pytest

from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.models.mana.mana_pool import ManaPool


def test_add_and_total_and_empty():
    pool = ManaPool()
    pool.add("G", 2)
    pool.add("C")
    assert pool.total() == 3
    pool.empty()
    assert pool.total() == 0


def test_add_rejects_unknown_type():
    with pytest.raises(ValueError):
        ManaPool().add("Z")


def test_pay_generic_from_any_color():
    pool = ManaPool({"R": 1, "G": 1})
    assert pool.can_pay(ManaCost.parse("{2}"))
    pool.pay(ManaCost.parse("{2}"))
    assert pool.total() == 0


def test_colored_pip_needs_that_color():
    pool = ManaPool({"R": 2})
    assert not pool.can_pay(ManaCost.parse("{G}"))
    assert pool.can_pay(ManaCost.parse("{R}"))


def test_generic_does_not_consume_needed_colored_mana():
    # {1}{G} from exactly one generic-worth + one green: the green must be
    # reserved for the {G}, the other mana pays the {1}.
    pool = ManaPool({"G": 1, "R": 1})
    assert pool.can_pay(ManaCost.parse("{1}{G}"))
    pool.pay(ManaCost.parse("{1}{G}"))
    assert pool.total() == 0


def test_generic_cannot_be_paid_by_missing_mana():
    pool = ManaPool({"G": 1})
    assert not pool.can_pay(ManaCost.parse("{1}{G}"))


def test_hybrid_pays_with_either_half():
    cost = ManaCost.parse("{W/U}")
    assert ManaPool({"W": 1}).can_pay(cost)
    assert ManaPool({"U": 1}).can_pay(cost)
    assert not ManaPool({"B": 1}).can_pay(cost)


def test_monocolored_hybrid_falls_back_to_generic():
    cost = ManaCost.parse("{2/W}")
    # No white, but two generic mana can pay {2/W}.
    assert ManaPool({"R": 2}).can_pay(cost)
    # One white pays it directly and more cheaply.
    pool = ManaPool({"W": 1})
    assert pool.can_pay(cost)
    pool.pay(cost)
    assert pool.total() == 0


def test_phyrexian_pays_with_mana_or_life():
    cost = ManaCost.parse("{B/P}")
    # With black mana, no life is spent.
    pool = ManaPool({"B": 1})
    assert pool.pay(cost, life_available=40) == 0
    # Without the color, pay 2 life instead.
    pool2 = ManaPool()
    assert pool2.can_pay(cost, life_available=40)
    assert pool2.pay(cost, life_available=40) == 2


def test_phyrexian_life_payment_must_leave_player_alive():
    cost = ManaCost.parse("{B/P}")
    # Only 2 life and no black mana: paying 2 would drop to 0, illegal.
    assert not ManaPool().can_pay(cost, life_available=2)
    assert ManaPool().can_pay(cost, life_available=3)


def test_complex_cost_solver():
    # {2}{W}{U/B}{G/P}: needs W + (U or B) + (G or 2 life) + 2 generic.
    cost = ManaCost.parse("{2}{W}{U/B}{G/P}")
    pool = ManaPool({"W": 1, "U": 1, "G": 1, "C": 2})
    assert pool.can_pay(cost, life_available=40)
    life = pool.pay(cost, life_available=40)
    assert life == 0
    assert pool.total() == 0


def test_pay_raises_when_unaffordable():
    with pytest.raises(ValueError):
        ManaPool().pay(ManaCost.parse("{R}"))
