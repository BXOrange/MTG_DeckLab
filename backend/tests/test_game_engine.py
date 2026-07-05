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


def _dual_land():
    return Card(
        id="Tundra",
        name="Tundra",
        type_line="Land — Plains Island",
        is_land=True,
        oracle_text="{T}: Add {W} or {U}.",
    )


def test_dual_land_taps_for_only_the_chosen_color():
    # Regression: tapping a WU dual must add ONE colour, not both.
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    p1 = eng.state.active_player
    produced = eng.tap_for_mana(p1, dual, option_index=1)  # choose U
    assert produced == {"U": 1}
    assert p1.mana_pool.pool == {"C": 0, "W": 0, "U": 1, "B": 0, "R": 0, "G": 0}


def test_tap_rejects_out_of_range_option():
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    with pytest.raises(ValueError):
        eng.tap_for_mana(eng.state.active_player, dual, option_index=5)


def test_legal_actions_lists_tap_options_per_source():
    eng = make_engine([land("Forest")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj_on_battlefield(eng.state, eng, _dual_land())
    tap = next(a for a in eng.legal_actions(eng.state.active_player) if a["type"] == "tap_for_mana")
    mana = [opt["mana"] for opt in tap["options"]]
    assert mana == [{"W": 1}, {"U": 1}]


# ---------------------------------------------------------------------------
# Casting & the stack (RULE 601 / 608)
# ---------------------------------------------------------------------------


def test_stale_card_without_cost_string_still_requires_mana():
    # Regression: a card cached before mana_cost_string existed (empty raw
    # cost, but a non-zero mana value) must not be castable for free.
    stale_sol_ring = Card(
        id="Sol Ring", name="Sol Ring", type_line="Artifact", converted_mana_cost=1
    )
    eng = make_engine([stale_sol_ring], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert not eng.can_cast(p1, p1.hand[0])  # empty pool -> not castable
    p1.mana_pool.add("C", 1)
    assert eng.can_cast(p1, p1.hand[0])  # one mana -> castable


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


def test_commander_can_be_cast_from_the_command_zone():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)

    assert eng.can_cast(p1, commander)
    eng.cast_spell(p1, commander)
    assert commander not in p1.command
    assert eng.state.stack[-1].obj is commander
    eng.resolve_until_stable()
    assert commander in eng.state.battlefield


def test_commander_returns_to_command_zone_when_it_dies():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(
        creature(name="Commander Bear", toughness=1), owner_id="p1", is_commander=True
    )
    commander.summoning_sick = False
    eng.state.add_to_battlefield(commander)

    eng.rules.deal_damage(commander, 1)
    eng.rules.check_state_based_actions()

    assert commander not in eng.state.battlefield
    assert commander in p1.command
    assert commander not in p1.graveyard


def test_countered_commander_spell_returns_to_command_zone_not_graveyard():
    eng = make_engine([], hand=0)
    p1 = eng.state.active_player
    commander = GameObject(creature(name="Commander Bear"), owner_id="p1", is_commander=True)
    p1.add_to_zone(commander, Zone.COMMAND)
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, commander)

    eng.rules.counter_spell(commander)

    assert commander in p1.command
    assert commander not in p1.graveyard


def test_instant_can_be_cast_at_instant_speed():
    eng = make_engine([instant()], [land()], hand=1)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # not a main phase, stack empty
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, p1.hand[0])


def test_phyrexian_mana_payment_drains_life():
    # Regression: ManaPool.pay computes the life spent on a Phyrexian pip
    # but cast_spell used to discard it, so paying {R/P} with life never
    # actually cost anything (RULE 119.4).
    eng = make_engine([instant(name="Gut Shot", cost="{R/P}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    assert p1.life == 20
    eng.cast_spell(p1, p1.hand[0])  # empty pool -> must pay 2 life instead
    assert p1.life == 18


def test_x_spell_defaults_to_x_zero():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add("R", 1)  # only enough for X=0
    assert eng.can_cast(p1, p1.hand[0])  # X=0 is always a legal announcement
    eng.cast_spell(p1, p1.hand[0])
    assert eng.state.stack[-1].x == 0
    assert p1.mana_pool.pool["R"] == 0


def test_x_spell_pays_the_announced_value():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    assert not eng.can_cast(p1, p1.hand[0], x=4)  # only 3 generic available
    assert eng.can_cast(p1, p1.hand[0], x=3)
    eng.cast_spell(p1, p1.hand[0], x=3)
    assert eng.state.stack[-1].x == 3
    assert p1.mana_pool.total() == 0  # R + 3 generic all spent


def test_x_spell_legal_action_reports_max_affordable_x():
    eng = make_engine([instant(name="Fireball", cost="{X}{R}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    [cast_action] = [
        a for a in eng.legal_actions(p1) if a["type"] == "cast_spell"
    ]
    assert cast_action["has_x"] is True
    assert cast_action["max_x"] == 3


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


def _life_lost_events(eng):
    events = []
    eng.state.subscribe(lambda e: events.append(e) if e.type == EventType.LIFE_LOST else None)
    return events


def test_deal_damage_fires_life_lost_with_damage_cause():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    events = _life_lost_events(eng)
    eng.rules.deal_damage(p2, 3)
    assert [(e["amount"], e["cause"]) for e in events] == [(3, "damage")]


def test_phyrexian_mana_payment_fires_life_lost_with_cost_cause():
    eng = make_engine([instant(name="Gut Shot", cost="{R/P}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    events = _life_lost_events(eng)
    eng.cast_spell(p1, p1.hand[0])
    assert [(e["amount"], e["cause"]) for e in events] == [(2, "cost")]


def test_rules_engine_lose_life_is_the_shared_choke_point():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    events = _life_lost_events(eng)
    eng.rules.lose_life(p1, 4)  # default cause, e.g. a direct life-loss effect
    assert p1.life == 16
    assert [(e["amount"], e["cause"]) for e in events] == [(4, "effect")]
    # A non-positive amount is a no-op (mirrors gain_life's guard) — no event.
    eng.rules.lose_life(p1, 0)
    assert len(events) == 1


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


# ---------------------------------------------------------------------------
# Library search (RULE 701.19) + the pending-choice mechanism
# ---------------------------------------------------------------------------


def test_search_opens_a_choice_then_moves_the_chosen_card():
    lib = [land("Forest"), creature("Bear A"), land("Forest"), creature("Bear B")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player

    eng.rules.request_search(p1, "Creature", "hand")
    choice = eng.state.pending_choice
    assert choice["kind"] == "search"
    assert {e["name"] for e in choice["eligible"]} == {"Bear A", "Bear B"}

    chosen = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(chosen)
    assert eng.state.pending_choice is None
    assert any(o.instance_id == chosen for o in p1.hand)
    assert len(p1.library) == 3  # one card left the library


def test_search_with_no_match_just_shuffles_no_choice():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.rules.request_search(p1, "Creature", "hand")  # no creatures in library
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_search_can_be_declined():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    eng.rules.request_search(p1, "Creature", "hand")
    eng.rules.resolve_search_choice(None)  # decline
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_resolve_until_stable_stops_on_pending_choice():
    from mtg_analyzer.game.effects import SearchLibraryEffect
    from mtg_analyzer.models.game_state import StackItem

    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    ability = SearchLibraryEffect(type_restriction="Creature", player=p1)
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[ability]))

    eng.resolve_until_stable()
    # Resolving the ability opened a search — the loop paused for the choice.
    assert eng.state.pending_choice is not None
    assert not eng.state.stack


# ---------------------------------------------------------------------------
# Gain life / counter (RULE 119 / 701.5)
# ---------------------------------------------------------------------------


def test_gain_life_effect():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    before = p1.life
    eng.rules.gain_life(p1, 5)
    assert p1.life == before + 5


def test_counter_spell_removes_it_from_the_stack():
    from mtg_analyzer.models.game_state import StackItem

    eng = make_engine([land()], hand=0)
    bear = GameObject(creature(), owner_id="p1", zone=Zone.STACK)
    item = StackItem(kind="spell", controller_id="p1", obj=bear, description="Grizzly Bears")
    eng.state.stack.append(item)

    eng.rules.counter_spell(bear)
    assert item not in eng.state.stack
    assert bear in eng.state.player_by_id("p1").graveyard


# ---------------------------------------------------------------------------
# Stack interaction (RULE 608): cast leaves it on the stack; pass resolves one
# ---------------------------------------------------------------------------


def test_pass_priority_resolves_one_stack_object_at_a_time():
    from mtg_analyzer.models.game_state import StackItem
    from mtg_analyzer.game.effects import DrawCardEffect

    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))

    assert eng.pass_priority() is True  # resolves the top one
    assert len(eng.state.stack) == 1
    assert eng.pass_priority() is True
    assert len(eng.state.stack) == 0
    assert eng.pass_priority() is False  # nothing left
