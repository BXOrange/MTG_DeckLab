"""Bug report, 2026-09-04: Frodo, Adventurous Hobbit's "whenever Frodo
attacks" trigger fired 953 times in one game instead of once.

Root cause: `_can_attack`/the `legal_actions` "attack" offer never excluded
a creature that was *already* declared as an attacker this combat. RULE
508.1a declares attackers once per combat — but a vigilant creature stays
untapped after attacking, so it kept satisfying `_can_attack` and showing
back up in `legal_actions` on every subsequent poll. `GreedyBot.play`
unconditionally takes any offered "attack" action, so it kept re-declaring
the same already-attacking creature every single decision cycle, re-firing
its `ATTACKS` trigger each time — `run_bots`'s own `MAX_BOT_ACTIONS` (200)
caps one call, but the multiplayer sweeper (`api/multiplayer_ws.sweep_once`,
1/s) re-invokes `run_bots` every second, so the count climbs without bound
while the game looks "stuck" (the reported symptom: buttons locked, a loop
visibly still running server-side).

Fix: `legal_actions` drops an already-``attacking`` creature from the
"attack" offer (mirroring `declare_blockers`'s existing exclusion of an
already-blocking creature), and `declare_attackers` itself now raises if
asked to redeclare one anyway (defense in depth against a stale offer).

Reference: `game/engine/legal_actions_mixin.py`, `game/engine/
combat_mixin.py` (`declare_attackers`), `services/bots.py` (`GreedyBot`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.bots import GreedyBot


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _vigilant_attacker(state, controller="p1"):
    card = Card(
        id="Frodo, Adventurous Hobbit", name="Frodo, Adventurous Hobbit",
        type_line="Legendary Creature — Halfling", is_creature=True, power=1, toughness=1,
        keywords=["Vigilance"],
        oracle_text=(
            "Partner with Sam, Loyal Attendant\nVigilance\nWhenever Frodo attacks, if you "
            "gained 3 or more life this turn, the Ring tempts you. Then if Frodo is your "
            "Ring-bearer and the Ring has tempted you two or more times this game, draw a card."
        ),
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_an_already_attacking_vigilant_creature_is_not_reoffered():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    frodo = _vigilant_attacker(eng.state, controller=p1.id)

    eng.state.current_step = "declare_attackers"
    assert any(a["type"] == "attack" for a in eng.legal_actions(p1))

    eng.declare_attackers(p1, [frodo])
    assert frodo.attacking is True
    assert frodo.tapped is False  # vigilance

    # RULE 508.1a: declared once — must not still be offered as attackable.
    assert not any(a["type"] == "attack" for a in eng.legal_actions(p1))


def test_redeclaring_an_already_attacking_creature_raises():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    frodo = _vigilant_attacker(eng.state, controller=p1.id)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [frodo])

    with pytest.raises(ValueError, match="already attacking"):
        eng.declare_attackers(p1, [frodo])


def test_frodos_attack_trigger_fires_exactly_once_per_combat():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    frodo = _vigilant_attacker(eng.state, controller=p1.id)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [frodo])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    # A second poll of legal_actions/play must not offer Frodo again — a
    # GreedyBot-shaped caller that takes every "attack" offer would
    # otherwise re-declare it and refire the trigger indefinitely.
    assert not any(a["type"] == "attack" for a in eng.legal_actions(p1))


def test_greedy_bot_does_not_loop_redeclaring_a_vigilant_attacker():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    frodo = _vigilant_attacker(eng.state, controller=p1.id)

    eng.state.current_step = "declare_attackers"

    class _View:
        """Minimal stand-in for `GameSession.view()` — just enough of the
        shape `GreedyBot.play` reads (`state.current_step`/`stack`,
        `legal_defenders`/`instance_id` on each offered action)."""

        def __init__(self, engine, player):
            self.engine = engine
            self.player = player

        def as_dict(self):
            return {
                "state": {
                    "current_step": self.engine.state.current_step,
                    "stack": [],
                    "players": [{"id": self.player.id, "life": 20}],
                },
            }

    bot = GreedyBot(player_id=p1.id)
    view = _View(eng, p1).as_dict()

    actions = eng.legal_actions(p1)
    action = bot.play(view, actions)
    assert action is not None and action["type"] == "attack"
    eng.declare_attackers(p1, [frodo])

    # A second call, same board: with the fix, Frodo is no longer offered,
    # so the bot has nothing left to attack with (before the fix, this
    # returned another "attack" action for the same creature).
    actions = eng.legal_actions(p1)
    action = bot.play(view, actions)
    assert action is None or action["type"] != "attack"
