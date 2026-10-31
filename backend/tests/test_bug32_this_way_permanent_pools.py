"""BUG-32 -- "permanent card" in typed "this way" pools (RULE 110.4 / 608.2c).

`permanent` is a marker for "has a permanent type", never a card type itself, so a plain type-set membership test
counted a milled creature as zero. Amounts, conditions and the discard / sacrifice event pools share the one matcher.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import effect_amounts, effect_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

MILL = "Mill 3 cards. You gain 2 life for each permanent card milled this way."
MILL_IF = "Mill 3 cards. If a permanent card was milled this way, you gain 5 life."
DISCARD = "Discard 2 cards. You gain 3 life for each permanent card discarded this way."
STARTING_LIFE = 20

CREATURE = ("Creature — Bear", {"is_creature": True, "power": 2, "toughness": 2})
INSTANT = ("Instant", {"is_instant": True})
LAND = ("Basic Land — Forest", {"is_land": True})


def _obj(i, spec, zone, owner="p1"):
    type_line, kw = spec
    card = Card(id=f"c{i}", name=f"Card {i}", type_line=type_line, **kw)
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    return obj


def _engine():
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Instant", is_instant=True) for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=STARTING_LIFE,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def _cast(text, top=(), hand=(), picks=()):
    eng, p1 = _engine()
    for i, spec in enumerate(top):
        p1.add_to_zone(_obj(i, spec, Zone.LIBRARY), Zone.LIBRARY)
    cards = [_obj(50 + i, s, Zone.HAND) for i, s in enumerate(hand)]
    p1.hand.extend(cards)
    card = Card(id="t", name="Tester", type_line="Sorcery", is_sorcery=True, oracle_text=text,
                mana_cost_string="{0}", converted_mana_cost=0)
    assert parse_oracle(card).coverage != UNMODELED
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    for index in picks:
        choice = eng.state.pending_choice
        assert choice, "the discard must ask the player"
        eng.rules.resolve_choice(str(cards[index].instance_id))
        eng.resolve_until_stable()
    return p1


def test_mixed_milled_pool_counts_creature_and_land_but_not_instant():
    p1 = _cast(MILL, top=[CREATURE, INSTANT, LAND])
    assert p1.life == STARTING_LIFE + 2 * 2


def test_milled_pool_of_only_nonpermanents_counts_zero():
    p1 = _cast(MILL, top=[INSTANT, INSTANT, INSTANT])
    assert p1.life == STARTING_LIFE


def test_condition_variant_fires_on_a_milled_creature_only_pool_member():
    assert _cast(MILL_IF, top=[INSTANT, CREATURE, INSTANT]).life == STARTING_LIFE + 5
    assert _cast(MILL_IF, top=[INSTANT, INSTANT, INSTANT]).life == STARTING_LIFE


def test_discard_event_pool_matches_permanent_cards():
    p1 = _cast(DISCARD, hand=[CREATURE, INSTANT, LAND], picks=[0, 1])
    assert p1.life == STARTING_LIFE + 3


@pytest.mark.parametrize("marker,types,expected", [
    ("permanent", {"creature"}, True), ("permanent", {"instant"}, False), ("permanent", {"battle"}, True),
    ("permanent", {"artifact", "creature"}, True), ("nonland_permanent", {"land"}, False),
    ("nonland_permanent", {"artifact", "land"}, False), ("nonland_permanent", {"enchantment"}, True),
    ("creature", {"creature"}, True), ("creature", {"land"}, False),
])
def test_marker_matcher(marker, types, expected):
    assert effect_amounts.type_marker_matches(types, marker) is expected


def test_pool_amount_and_condition_handles_with_negate():
    eng, _ = _engine()
    ctx = GameContext(eng.state, eng.rules)
    ctx.milled_objects = [_obj(1, CREATURE, Zone.GRAVEYARD), _obj(2, INSTANT, Zone.GRAVEYARD), _obj(3, LAND, Zone.GRAVEYARD)]
    count = lambda **kw: effect_amounts.amount_of({"kind": "this_way_count", "pool": "milled", **kw}, ctx, None, None)
    assert count(card_type="permanent") == 2
    assert count(card_type="permanent", negate=True) == 1
    assert count(card_type="nonland_permanent") == 1
    cond = effect_conditions.condition_state(
        {"kind": "this_way_pool", "pool": "milled", "card_type": "permanent", "negate": True}, ctx, None, None)
    assert cond is True
