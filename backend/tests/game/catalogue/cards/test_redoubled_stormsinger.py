"""Redoubled Stormsinger creates temporary attacking copies."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _singer_card():
    return Card(id="rs", name="Redoubled Stormsinger", type_line="Creature — Orc Wizard",
                is_creature=True, power=3, toughness=3,
                oracle_text=("First strike\nWhenever this creature attacks, for each "
                             "creature token you control that entered this turn, create "
                             "a tapped and attacking token that's a copy of that token. "
                             "At the beginning of the next end step, sacrifice those "
                             "tokens."))


def test_registered_and_binds():
    assert is_registered("Redoubled Stormsinger")
    spec = _REGISTRY["redoubled stormsinger"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "ATTACKS"
    assert [e.type for e in spec.effects] == [
        "redoubled_stormsinger_copies", "create_delayed_trigger",
    ]
    src = GameObject(_singer_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_singer_card())


def test_copies_each_just_entered_token_tapped_and_attacking():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.state.current_phase = "combat"
    eng.state.current_step = "declare_attackers"
    singer = GameObject(_singer_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    singer.controller_id = "p1"
    singer.summoning_sick = False
    eng.state.add_to_battlefield(singer)
    bind_from_catalogue(singer)

    # a creature token that entered this turn
    tok = GameObject(Card(id="elemental", name="Elemental", type_line="Creature — Elemental",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.BATTLEFIELD, is_token=True)
    tok.controller_id = "p1"
    eng.state.add_to_battlefield(tok)
    tok.turn_entered = eng.state.internal_turn.number

    # an old token (entered a previous turn) — not copied
    old = GameObject(Card(id="goblin", name="Goblin", type_line="Creature — Goblin",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.BATTLEFIELD, is_token=True)
    old.controller_id = "p1"
    eng.state.add_to_battlefield(old)
    old.turn_entered = eng.state.internal_turn.number - 2

    eng.recompute_continuous_effects()
    n_before = len([o for o in eng.state.battlefield if o.card.name == "Elemental"])
    eng.state.fire_event(GameEvent(EventType.ATTACKS, attacker="Redoubled Stormsinger",
                                   player_id="p1", instance_id=singer.instance_id))
    eng.resolve_until_stable()

    elems = [o for o in eng.state.battlefield if o.card.name == "Elemental"]
    assert len(elems) == n_before + 1  # exactly one copy of the just-entered token
    copy = next(o for o in elems if o is not tok)
    assert copy.tapped and copy.attacking
    assert not [o for o in eng.state.battlefield if o.card.name == "Goblin" and o is not old]
