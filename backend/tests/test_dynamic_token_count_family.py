"""Tests for RULE 603.1's "create that many `<tokens>`" template
(Lathril, Blade of the Elves-shaped "whenever ~ deals combat damage to a
player" payoff, ~38 real cards) — `CreateTokenEffect.count_from_trigger_event`,
reading the firing event's own ``amount`` fresh at resolve time (the same
`GameContext.trigger_event` idiom `PumpEffect.amount_from_trigger_event`/
`CreateTokenEffect.pt_from_trigger_event` already use, just scaling *how
many* tokens instead of one shared magnitude or a token's own stats).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import CreateTokenEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _bear(name="Bear", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_create_that_many_tokens_is_recognized():
    (spec,) = parse_effect_body("create that many 1/1 green elf warrior creature tokens")
    assert spec.type == "create_token"
    assert spec.params["power"] == 1 and spec.params["toughness"] == 1
    assert spec.params["count_from_trigger_event"] == "amount"
    assert spec.params["subtypes"] == ["Elf", "Warrior"]


def test_lathril_is_fully_modeled():
    card = Card(
        id="Lathril, Blade of the Elves", name="Lathril, Blade of the Elves",
        type_line="Legendary Creature — Elf Warrior", is_creature=True,
        power=2, toughness=1, keywords=["Menace"],
        oracle_text="Menace\nWhenever Lathril deals combat damage to a player, "
                     "create that many 1/1 green Elf Warrior creature tokens.",
    )
    assert parse_oracle(card).coverage == MODELED


# ---------------------------------------------------------------------------
# Engine: CreateTokenEffect.count_from_trigger_event
# ---------------------------------------------------------------------------


def test_count_from_trigger_event_reads_the_firing_events_amount():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    source = GameObject(_bear("Source"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(source)
    ctx = GameContext(eng.state, eng.rules)
    ctx.trigger_event = GameEvent(EventType.DAMAGE, amount=4, is_player=True)

    effect = CreateTokenEffect(
        power=1, toughness=1, colors=["G"], subtypes=["Elf", "Warrior"],
        count_from_trigger_event="amount", source=source,
    )
    before = len(eng.state.battlefield)
    effect.apply(ctx)

    tokens = [o for o in eng.state.battlefield if "Elf" in o.card.type_line and o is not source]
    assert len(tokens) == 4
    assert len(eng.state.battlefield) == before + 4


def test_count_from_trigger_event_creates_nothing_at_zero_amount():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    source = GameObject(_bear("Source"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(source)
    ctx = GameContext(eng.state, eng.rules)
    ctx.trigger_event = GameEvent(EventType.DAMAGE, amount=0, is_player=True)

    effect = CreateTokenEffect(
        power=1, toughness=1, subtypes=["Elf"], count_from_trigger_event="amount", source=source,
    )
    before = len(eng.state.battlefield)
    effect.apply(ctx)

    assert len(eng.state.battlefield) == before


def test_lathril_end_to_end_creates_tokens_equal_to_combat_damage_dealt():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    lathril_card = Card(
        id="Lathril, Blade of the Elves", name="Lathril, Blade of the Elves",
        type_line="Legendary Creature — Elf Warrior", is_creature=True,
        power=3, toughness=2, keywords=["Menace"],
        oracle_text="Menace\nWhenever Lathril deals combat damage to a player, "
                     "create that many 1/1 green Elf Warrior creature tokens.",
    )
    lathril = GameObject(lathril_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    lathril.summoning_sick = False
    bind_from_catalogue(lathril)
    eng.state.add_to_battlefield(lathril)

    _to_declare_attackers(eng)
    p1 = eng.state.active_player
    eng.declare_attackers(p1, [lathril])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    tokens = [o for o in eng.state.battlefield if o is not lathril and "Elf" in o.card.type_line]
    assert len(tokens) == 3  # Lathril's own power
