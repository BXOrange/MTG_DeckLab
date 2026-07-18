"""Tests for {X} cost threading (RULE 107.3c/601.2b): `StackItem.x`, set at
cast/activate time, substituted into a resolving one-shot effect's
``"x"``-sentinel ``amount``/``count`` by `RulesEngine._substitute_x`
(`game/rules_engine.py`'s `resolve_top_of_stack`).
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects import DealDamageEffect, DrawCardEffect, TriggeredAbility
from mtg_analyzer.models.events import EventType


def make_engine(p1_cards, p2_cards=None, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=20, starting_hand=hand)


def _banefire_like(owner_id="p1"):
    """A hand `GameObject` for a bare "~ deals X damage to any target" instant."""
    card = Card(
        id="Banefire", name="Banefire", type_line="Sorcery",
        mana_cost_string="{X}{R}", converted_mana_cost=1,
        is_sorcery=True,
    )
    spell = GameObject(card, owner_id=owner_id, zone=Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount="x", target_kind="any")]
    return spell


def _stroke_of_genius_like(owner_id="p1"):
    """A hand `GameObject` for a bare "target player draws X cards" instant."""
    card = Card(
        id="Stroke of Genius", name="Stroke of Genius", type_line="Instant",
        mana_cost_string="{X}{U}{U}", converted_mana_cost=2,
        is_instant=True,
    )
    spell = GameObject(card, owner_id=owner_id, zone=Zone.HAND)
    spell.spell_effects = [DrawCardEffect(count="x", target_kind="player")]
    return spell


# ---------------------------------------------------------------------------
# Direct stack-resolution substitution (unit level)
# ---------------------------------------------------------------------------


def test_substitute_x_replaces_amount_on_a_flat_effect():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    opponent = eng.state.players[1] if len(eng.state.players) > 1 else p1
    eng.state.stack.append(
        StackItem(
            kind="ability", controller_id="p1",
            effects=[DealDamageEffect(amount="x", target_kind="any")],
            targets=[opponent], x=7,
        )
    )
    life_before = opponent.life
    eng.rules.resolve_top_of_stack()
    assert opponent.life == life_before - 7


def test_substitute_x_replaces_count_on_a_flat_effect():
    eng = make_engine([Card(id="Bear", name="Bear", type_line="Creature", is_creature=True)] * 6, hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.stack.append(
        StackItem(
            kind="ability", controller_id="p1",
            effects=[DrawCardEffect(count="x", player=p1)],
            x=3,
        )
    )
    hand_before = len(p1.hand)
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == hand_before + 3


def test_substitute_x_zero_leaves_effect_inert():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    opponent = eng.state.players[1] if len(eng.state.players) > 1 else p1
    eng.state.stack.append(
        StackItem(
            kind="ability", controller_id="p1",
            effects=[DealDamageEffect(amount="x", target_kind="any")],
            targets=[opponent], x=0,
        )
    )
    life_before = opponent.life
    eng.rules.resolve_top_of_stack()
    assert opponent.life == life_before


def test_substitute_x_reaches_into_a_wrapped_triggered_ability():
    # `TriggeredAbility`/`ActivatedAbility` own a *nested* effects list
    # (invisible to the outer stack loop) — confirm `_substitute_x` walks
    # one level down into it too, not just the flat spell-effect case.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    opponent = eng.state.players[1] if len(eng.state.players) > 1 else p1
    ability = TriggeredAbility(
        trigger_event=EventType.DAMAGE,
        effects=[DealDamageEffect(amount="x", target_kind="any")],
    )
    eng.state.stack.append(
        StackItem(kind="ability", controller_id="p1", effects=[ability], targets=[opponent], x=4)
    )
    life_before = opponent.life
    eng.rules.resolve_top_of_stack()
    assert opponent.life == life_before - 4


# ---------------------------------------------------------------------------
# Full cast pipeline (announced {X} -> StackItem.x -> substitution)
# ---------------------------------------------------------------------------


def test_cast_x_damage_spell_deals_the_announced_x():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    opponent = next(p for p in eng.state.players if p is not p1)
    p1.mana_pool.add_many({"R": 1, "C": 5})
    spell = _banefire_like()
    p1.add_to_zone(spell, Zone.HAND)
    life_before = opponent.life
    eng.cast_spell(p1, spell, x=5, targets=[opponent])
    eng.resolve_until_stable()
    assert opponent.life == life_before - 5


def test_cast_x_draw_spell_draws_the_announced_x():
    eng = make_engine([Card(id="Bear", name="Bear", type_line="Creature", is_creature=True)] * 6,
                       [Card(id="Elephant", name="Elephant", type_line="Creature", is_creature=True)] * 6,
                       hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    opponent = next(p for p in eng.state.players if p is not p1)
    p1.mana_pool.add_many({"U": 2, "C": 3})
    spell = _stroke_of_genius_like()
    p1.add_to_zone(spell, Zone.HAND)
    hand_before = len(opponent.hand)
    eng.cast_spell(p1, spell, x=3, targets=[opponent])
    eng.resolve_until_stable()
    assert len(opponent.hand) == hand_before + 3
