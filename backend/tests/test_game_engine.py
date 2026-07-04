"""Tests for the rules engine + game engine.

Reference: docs/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.effects import (
    DealDamageEffect,
    DrawCardEffect,
    EffectRegistry,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import default_turn_sequence
from mtg_analyzer.game.rules_engine import RulesEngine


# ---------------------------------------------------------------------------
# Card factories (set the type flags the Scryfall client would derive)
# ---------------------------------------------------------------------------


def land(name="Forest", produces="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2, **kw):
    return Card(
        id=name,
        name=name,
        type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        **kw,
    )


def instant(name="Shock", cost="{R}"):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine(p1_cards, p2_cards=None, life=20, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=life, starting_hand=hand)


def obj_on_battlefield(state: GameState, engine: GameEngine, card: Card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Turn structure (RULE 500)
# ---------------------------------------------------------------------------


def test_turn_structure_order():
    seq = default_turn_sequence()
    step_names = [step.name for _, step in seq.iter_steps()]
    assert step_names[:4] == ["untap", "upkeep", "draw", "main1"]
    assert step_names[-1] == "cleanup"


def test_first_player_skips_first_draw_in_multiplayer():
    eng = make_engine([land()] * 30, [land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()  # turn 1, p1 active
    # No draw on turn 1 for the starting player, but a land may be played
    # from an (empty) hand — with hand=0, library is only touched by draw.
    assert len(p1.library) == before


def test_solo_player_draws_on_turn_one():
    eng = make_engine([land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()
    assert len(p1.library) == before - 1


# ---------------------------------------------------------------------------
# Land drops & mana (RULE 305 / 504 / 505)
# ---------------------------------------------------------------------------


def test_one_land_per_turn():
    eng = make_engine([land(), land()], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    first, second = p1.hand[0], p1.hand[1]
    eng.play_land(p1, first)
    assert not eng.can_play_land(p1, second)
    with pytest.raises(ValueError):
        eng.play_land(p1, second)


def test_tap_land_for_mana():
    eng = make_engine([land("Forest")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest = eng.play_land(p1, p1.hand[0])
    produced = eng.tap_for_mana(p1, forest)
    assert produced == {"G": 1}
    assert p1.mana_pool.pool["G"] == 1
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, forest)  # already tapped


# ---------------------------------------------------------------------------
# Casting & the stack (RULE 601 / 608)
# ---------------------------------------------------------------------------


def test_cannot_cast_without_mana():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert not eng.can_cast(p1, p1.hand[0])
    with pytest.raises(ValueError):
        eng.cast_spell(p1, p1.hand[0])


def test_sorcery_speed_creature_needs_empty_stack_and_main_phase():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.state.current_step = "upkeep"
    assert not eng.can_cast(p1, p1.hand[0])  # not a main phase
    eng.state.current_step = "main1"
    assert eng.can_cast(p1, p1.hand[0])


def test_cast_creature_resolves_onto_battlefield():
    eng = make_engine([creature()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    bear = p1.hand[0]
    eng.cast_spell(p1, bear)
    assert eng.state.stack and eng.state.stack[-1].obj is bear
    eng.resolve_until_stable()
    assert bear in eng.state.battlefield
    assert bear.summoning_sick  # entered this turn (RULE 302.6)
    assert not eng.state.stack


def test_instant_can_be_cast_at_instant_speed():
    eng = make_engine([instant()], [land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # not a main phase, stack empty
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, p1.hand[0])


def test_stack_is_lifo():
    eng = make_engine([land()], hand=0)
    state = eng.state
    resolved = []
    # Two abilities whose effects record their order when resolved.
    from mtg_analyzer.game.effects import GameEffect

    class Record(GameEffect):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag

        def apply(self, context, targets=None):
            resolved.append(self.tag)

    from mtg_analyzer.models.game_state import StackItem

    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("first")]))
    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("second")]))
    eng.resolve_until_stable()
    assert resolved == ["second", "first"]  # last in, first out


# ---------------------------------------------------------------------------
# State-based actions (RULE 704)
# ---------------------------------------------------------------------------


def test_player_at_zero_life_loses():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.life = 0
    eng.rules.check_state_based_actions()
    assert p1.has_lost
    assert eng.state.game_over
    assert eng.state.winner_id == "p2"


def test_cant_lose_effect_prevents_loss():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.life = -5
    p1.player_effects.append(WinConditionEffect("prevent_loss"))
    eng.rules.check_state_based_actions()
    assert not p1.has_lost


def test_lethal_damage_destroys_creature():
    eng = make_engine([land()], hand=0)
    bear = obj_on_battlefield(eng.state, eng, creature())
    bear.damage_marked = 2  # toughness 2
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield
    assert bear.zone == Zone.GRAVEYARD
    assert bear.damage_marked == 0  # cleared on leaving play


def test_zero_toughness_creature_dies():
    eng = make_engine([land()], hand=0)
    frog = obj_on_battlefield(eng.state, eng, creature("Frog", power=1, toughness=1))
    frog.plus_one_counters = -1  # net toughness 0
    eng.rules.check_state_based_actions()
    assert frog not in eng.state.battlefield


def test_legend_rule_keeps_one():
    eng = make_engine([land()], hand=0)
    c = creature("Commander", is_legendary=True)
    a = obj_on_battlefield(eng.state, eng, c)
    b = obj_on_battlefield(eng.state, eng, c)
    eng.rules.check_state_based_actions()
    survivors = [o for o in eng.state.battlefield if o.name == "Commander"]
    assert len(survivors) == 1
    assert survivors[0] is a  # the first-seen copy is kept


def test_draw_from_empty_library_loses():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()
    eng.rules.draw(p1, 1)
    eng.rules.check_state_based_actions()
    assert p1.has_lost
    assert p1.loss_reason == "draw_from_empty"


# ---------------------------------------------------------------------------
# Damage / effects primitives
# ---------------------------------------------------------------------------


def test_deal_damage_to_player_reduces_life():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3)
    assert p2.life == 17


def test_deal_damage_effect_via_context():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    DealDamageEffect(amount=5).apply(eng.rules.context, targets=[p2])
    assert p2.life == 15


def test_effect_registry_creates_known_effects():
    effect = EffectRegistry.create("draw", {"count": 2})
    assert isinstance(effect, DrawCardEffect)
    assert effect.count == 2
    with pytest.raises(ValueError):
        EffectRegistry.create("nonexistent")


# ---------------------------------------------------------------------------
# Replacement effects (RULE 614 / 616)
# ---------------------------------------------------------------------------


def test_replacement_draw_two_instead():
    eng = make_engine([land("Forest"), land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")

    def draw_two(event, ctx):
        return event.copy_with(count=event.get("count", 1) + 1)

    source = obj_on_battlefield(eng.state, eng, creature("Tymna"))
    source.replacement_effects.append(
        ReplacementEffect(EventType.DRAW, draw_two, description="draw an extra")
    )
    before = len(p1.hand)
    eng.rules.draw(p1, 1)
    assert len(p1.hand) == before + 2


def test_replacement_can_prevent_event():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    source = obj_on_battlefield(eng.state, eng, creature("Fog Bank"))
    source.replacement_effects.append(
        ReplacementEffect(EventType.DAMAGE, lambda e, c: None, description="prevent all damage")
    )
    eng.rules.deal_damage(p2, 10)
    assert p2.life == 20  # prevented


# ---------------------------------------------------------------------------
# Triggered abilities (RULE 603)
# ---------------------------------------------------------------------------


def test_triggered_ability_goes_on_stack_and_resolves():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")
    # "Whenever you draw a card, draw a card" style trigger for testing.
    trigger = TriggeredAbility(
        trigger_event=EventType.SPELL_CAST,
        effects=[DrawCardEffect(count=1, player=p1)],
        controller_id="p1",
        description="draw on cast",
    )
    watcher = obj_on_battlefield(eng.state, eng, creature("Watcher"))
    watcher.triggered_abilities.append(trigger)

    before = len(p1.hand)
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1"))
    assert eng.rules.pending_triggers  # collected, not yet on stack
    eng.resolve_until_stable()
    assert len(p1.hand) == before + 1
    assert not eng.rules.pending_triggers


# ---------------------------------------------------------------------------
# Phase skipping (docs/07 PART 8)
# ---------------------------------------------------------------------------


def test_skip_untap_step_leaves_permanents_tapped():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    tapped_land = obj_on_battlefield(eng.state, eng, land())
    tapped_land.tap()
    p1.player_effects.append(
        StaticEffect("skip_phase", {"phase": "untap"}, duration="permanent")
    )
    eng.run_turn()
    assert tapped_land.tapped  # untap step skipped, stays tapped


# ---------------------------------------------------------------------------
# Action validation (docs/02 R4.3)
# ---------------------------------------------------------------------------


def test_legal_actions_lists_land_and_pass():
    eng = make_engine([land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    actions = eng.legal_actions(p1)
    types = {a["type"] for a in actions}
    assert "pass_priority" in types
    assert "play_land" in types


def test_legal_actions_offers_tap_for_mana():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    forest = obj_on_battlefield(eng.state, eng, land("Forest"))
    actions = eng.legal_actions(eng.state.active_player)
    assert any(a["type"] == "tap_for_mana" for a in actions)


# ---------------------------------------------------------------------------
# Combat (RULE 508 / 510)
# ---------------------------------------------------------------------------


def test_summoning_sick_creature_cannot_attack():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature())
    bear.summoning_sick = True
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [bear])


def test_attackers_deal_damage_to_opponent():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.tapped
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p2").life == 17


# ---------------------------------------------------------------------------
# Goldfish (UC3)
# ---------------------------------------------------------------------------


def test_goldfish_plays_lands_and_attacks_over_several_turns():
    lib = [land("Forest")] * 20 + [creature()] + [land("Forest")] * 6
    eng = make_engine(lib, [land("Forest")] * 40, life=20, hand=7)
    for _ in range(6):
        if eng.state.game_over:
            break
        eng.run_goldfish_turn()
    # The bear is drawn early, cast, and eventually swings for 2.
    creatures = [o.name for o in eng.state.battlefield if o.is_creature]
    assert "Grizzly Bears" in creatures
    assert eng.state.player_by_id("p2").life < 20


def test_rules_engine_can_be_constructed_standalone():
    state = GameState(players=[Player(id="p1")])
    engine = RulesEngine(state)
    assert engine.state is state
