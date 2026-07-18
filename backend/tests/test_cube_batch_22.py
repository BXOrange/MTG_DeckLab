"""cEDH staples cube — batch 22: the delayed-triggered-ability primitive
(RULE 603.7).

New core capability: a resolving spell/ability can *arm* a trigger that fires
at a future step — "at the beginning of your next upkeep/main phase/end step,
<effect>." `GameState.delayed_triggers` holds `DelayedTrigger`s; the
`create_delayed_trigger` effect (`CreateDelayedTriggerEffect`) builds one at
resolution (its inner effects go through the ordinary `build_effects`
whitelist); `GameEngine._fire_delayed_triggers` places due ones on the stack at
STEP_BEGIN and drops them (they fire once). ``scope`` is "controller" (your
next such step) or "any" (the very next one); ``capture="target_mana_value"``
bakes a countered spell's mana value into the delayed effect before the spell
is gone.

Registers Mana Drain (counter + "add {C} equal to that spell's mana value at
your next main phase"). The Pacts (interactive "pay {cost} or lose the game")
and Corpse Dance (Buyback + reanimation + baked delayed exile) reuse this
primitive but carry a second gap and stay deferred.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import (
    AddManaEffect, CreateDelayedTriggerEffect, LoseLifeEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import DelayedTrigger, StackItem
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


def _src(controller="p1") -> GameObject:
    obj = GameObject(Card(id="s", name="Source", type_line="Instant"),
                     owner_id=controller, zone=Zone.GRAVEYARD)
    obj.controller_id = controller
    return obj


# ---------------------------------------------------------------------------
# 1. Firing a DelayedTrigger placed directly on the state
# ---------------------------------------------------------------------------


def test_delayed_trigger_fires_at_matching_step_for_its_controller():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    eff = AddManaEffect(amount=3, color="C", source=_src("p1"))
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p1", step="upkeep", effects=[eff], scope="controller")
    )

    eng._fire_delayed_triggers("upkeep")   # active player is p1
    assert eng.state.delayed_triggers == [], "the trigger fires once and is dropped"
    eng.resolve_until_stable()
    assert p1.mana_pool.total() == 3


def test_delayed_trigger_waits_for_the_right_step():
    eng = _engine()
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p1", step="upkeep",
                       effects=[AddManaEffect(amount=1, source=_src())], scope="controller")
    )
    eng._fire_delayed_triggers("draw")     # wrong step
    assert len(eng.state.delayed_triggers) == 1, "still pending"
    assert len(eng.state.stack) == 0


def test_controller_scoped_trigger_skips_another_players_step():
    eng = _engine()
    # active player is p1; a p2-controlled "your next upkeep" must not fire now.
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p2", step="upkeep",
                       effects=[AddManaEffect(amount=1, source=_src("p2"))], scope="controller")
    )
    eng._fire_delayed_triggers("upkeep")
    assert len(eng.state.delayed_triggers) == 1, "not p2's turn — stays pending"


def test_any_scope_fires_regardless_of_active_player():
    eng = _engine()
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p2", step="end",
                       effects=[AddManaEffect(amount=1, source=_src("p2"))], scope="any")
    )
    eng._fire_delayed_triggers("end")      # p1's turn, but scope "any"
    assert eng.state.delayed_triggers == []


# ---------------------------------------------------------------------------
# 2. CreateDelayedTriggerEffect arms one at resolution
# ---------------------------------------------------------------------------


def test_create_delayed_trigger_effect_arms_and_captures_mana_value():
    eng = _engine()
    src = _src("p1")
    effect = CreateDelayedTriggerEffect(
        step="main", scope="controller", capture="target_mana_value",
        effects=[{"type": "add_mana", "params": {"color": "C", "amount": "x"}}],
        source=src,
    )
    # A fake countered spell of mana value 5 as the target.
    spell = GameObject(Card(id="big", name="Big", type_line="Sorcery", converted_mana_cost=5),
                       owner_id="p2", zone=Zone.GRAVEYARD)
    effect.apply(eng.rules.context, [spell])

    assert len(eng.state.delayed_triggers) == 1
    dt = eng.state.delayed_triggers[0]
    assert dt.controller_id == "p1" and dt.step == "main"
    inner = dt.effects[0]
    assert isinstance(inner, AddManaEffect)
    assert inner.amount == 5, "captured the countered spell's mana value"


# ---------------------------------------------------------------------------
# 3. Full turn-loop integration (life persists across step-end mana empty)
# ---------------------------------------------------------------------------


def test_delayed_trigger_fires_through_the_real_step_loop():
    eng = GameEngine.new_game([("p1", "Alice", [])], starting_life=40, starting_hand=0)
    eng.start()  # positioned before turn 1's first step
    p1 = eng.state.player_by_id("p1")
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p1", step="end",
                       effects=[LoseLifeEffect(amount=4, source=_src("p1"))], scope="controller")
    )
    # Walk steps until the end step has run.
    for _ in range(12):
        ran = eng.advance_step()
        if ran and ran[1] == "end":
            break
    assert p1.life == 36, "the delayed 'lose 4 life at end step' fired"
    assert eng.state.delayed_triggers == []


# ---------------------------------------------------------------------------
# 4. Mana Drain
# ---------------------------------------------------------------------------


@pytestmark_db
def test_mana_drain_registered_and_playable():
    assert "mana drain" in ac._REGISTRY
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Mana Drain")
    if card is not None:
        assert ac.specs_for(card)


@pytestmark_db
def test_mana_drain_counters_then_adds_c_equal_to_mv_next_main_phase():
    eng = _engine()
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Mana Drain")
    if card is None:
        pytest.skip("Mana Drain not cached")
    p1 = eng.state.player_by_id("p1")

    # A target spell of mana value 4 on the stack (a fake 4-drop).
    victim_card = Card(id="v", name="Victim", type_line="Creature", is_creature=True, converted_mana_cost=4)
    victim = GameObject(victim_card, owner_id="p2", zone=Zone.STACK)
    eng.state.stack.append(StackItem(kind="spell", controller_id="p2", obj=victim,
                                     description="Victim", effects=[]))

    drain = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(drain)
    eng.state.stack.append(StackItem(
        kind="spell", controller_id="p1", obj=drain, description="Mana Drain",
        effects=eng.rules._effects_for_spell(drain), targets=[victim],
    ))
    eng.rules.resolve_top_of_stack()  # resolve Mana Drain

    assert victim in eng.state.player_by_id("p2").graveyard, "target countered"
    assert len(eng.state.delayed_triggers) == 1, "delayed mana armed"

    # Reach the controller's next main phase and let it resolve.
    eng._fire_delayed_triggers("main1")
    eng.resolve_until_stable()
    assert p1.mana_pool.total() == 4, "added {C} equal to the countered spell's MV"
