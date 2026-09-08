"""cEDH staples cube — batch 19: the divided-damage primitive (RULE 601.2d).

New core capability: `DealDamageEffect(divided=True)` splits its total pool
(typically {X}) across the chosen targets instead of dealing the full amount
to each. ``double_at`` doubles the pool once the resolved amount reaches a
threshold (RULE 107.3, Shatterskull's "if X is 6 or more … twice X instead").
The "as you choose" split is UI-less: distributed as evenly as possible (an
explicit ``division`` wins) — the total dealt and which permanents take it are
exact; only lumping it unevenly is auto-made.

Registers Shatterskull Smashing (the sorcery front face of the MDFC — casts
normally) and Fire Covenant (divided damage + the Toxic-Deluge
``pay_life: "x"`` additional cost).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DealDamageEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark_db = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present"
)


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _creature(eng, name, tough=10, owner="p2") -> GameObject:
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear",
             is_creature=True, power=1, toughness=tough),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# 1. The divided primitive itself
# ---------------------------------------------------------------------------


def test_divided_splits_the_pool_evenly():
    eng = _engine()
    a, b, c = _creature(eng, "A"), _creature(eng, "B"), _creature(eng, "C")
    eff = DealDamageEffect(amount=7, target_kind="creature", count=3, divided=True)
    eff.apply(eng.rules.context, [a, b, c])
    # 7 across 3: 3 + 2 + 2 (remainder to the front).
    assert (a.damage_marked, b.damage_marked, c.damage_marked) == (3, 2, 2)


def test_divided_explicit_division_wins():
    eng = _engine()
    a, b = _creature(eng, "A"), _creature(eng, "B")
    eff = DealDamageEffect(amount=5, target_kind="creature", count=2, divided=True)
    eff.division = [4, 1]
    eff.apply(eng.rules.context, [a, b])
    assert (a.damage_marked, b.damage_marked) == (4, 1)


def test_divided_doubles_at_threshold():
    eng = _engine()
    a, b = _creature(eng, "A"), _creature(eng, "B")
    eff = DealDamageEffect(amount=6, target_kind="creature", count=2, divided=True, double_at=6)
    eff.apply(eng.rules.context, [a, b])
    # X=6 hits the threshold: pool becomes 12, split 6/6.
    assert (a.damage_marked, b.damage_marked) == (6, 6)


def test_divided_below_threshold_not_doubled():
    eng = _engine()
    a, b = _creature(eng, "A"), _creature(eng, "B")
    eff = DealDamageEffect(amount=5, target_kind="creature", count=2, divided=True, double_at=6)
    eff.apply(eng.rules.context, [a, b])
    assert (a.damage_marked, b.damage_marked) == (3, 2)


def test_divided_no_targets_is_a_noop():
    eng = _engine()
    eff = DealDamageEffect(amount=5, target_kind="creature", count=2, divided=True)
    eff.apply(eng.rules.context, [])  # no crash, nothing happens


# ---------------------------------------------------------------------------
# 2. Registered cards
# ---------------------------------------------------------------------------


@pytestmark_db
@pytest.mark.parametrize("name", ["Shatterskull Smashing", "Fire Covenant"])
def test_registered_and_playable(name):
    assert name.strip().lower() in ac._REGISTRY
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is not None:
        assert ac.specs_for(card), f"{name} produced no specs"


@pytestmark_db
def test_shatterskull_resolves_divided_and_doubles_with_x_substitution():
    """Build Shatterskull on the stack with X and resolve — the {X} sentinel
    is substituted and the pool split/doubled at resolution."""
    eng = _engine()
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Shatterskull Smashing")
    if card is None:
        pytest.skip("Shatterskull Smashing not cached")
    a = _creature(eng, "Aa", tough=10)
    b = _creature(eng, "Bb", tough=10)

    spell = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(spell)
    item = StackItem(
        kind="spell", controller_id="p1", obj=spell,
        description=card.name, effects=eng.rules._effects_for_spell(spell),
        targets=[a, b], x=6,
    )
    eng.state.stack.append(item)
    eng.rules.resolve_top_of_stack()

    # X=6 → doubled to 12 → 6/6.
    assert (a.damage_marked, b.damage_marked) == (6, 6)


@pytestmark_db
def test_fire_covenant_has_the_pay_x_life_additional_cost():
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Fire Covenant")
    if card is None:
        pytest.skip("Fire Covenant not cached")
    obj = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    cost = getattr(obj, "additional_cast_cost", None)
    assert cost is not None and cost.pay_life != 0, "Fire Covenant should carry pay-X-life"
