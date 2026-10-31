"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import (
    DealDamageEffect,
    DrawCardEffect,
    EffectRegistry,
    ReplacementEffect,
    StaticEffect,
    TriggeredAbility,
    WinConditionEffect,
)


from engine_test_helpers import land, creature, instant, make_engine, obj_on_battlefield, _sick, _mana_dork, _mana_offered, _life_lost_events


def test_summoning_sick_creature_cannot_tap_for_mana():
    eng = make_engine([land()], hand=0)
    dork = _sick(eng.state, eng, _mana_dork())
    p1 = eng.state.active_player
    assert not _mana_offered(eng, p1, dork)  # not a legal action
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, dork)


def test_haste_lets_a_creature_tap_for_mana_the_turn_it_arrives():
    eng = make_engine([land()], hand=0)
    dork = _sick(eng.state, eng, _mana_dork(), haste=True)
    p1 = eng.state.active_player
    assert _mana_offered(eng, p1, dork)
    assert eng.tap_for_mana(p1, dork) == {"G": 1} and dork.tapped


def test_noncreature_mana_source_ignores_summoning_sickness():
    # A mana rock / land is never summoning sick for {T} (RULE 302.6 is creatures).
    eng = make_engine([land()], hand=0)
    rock = Card(id="Sol Ring", name="Sol Ring", type_line="Artifact",
                oracle_text="{T}: Add {C}{C}.")
    obj = _sick(eng.state, eng, rock)
    p1 = eng.state.active_player
    assert _mana_offered(eng, p1, obj)
    assert eng.tap_for_mana(p1, obj) == {"C": 2}


def test_summoning_sick_creature_cannot_activate_tap_ability():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng = make_engine([land()], hand=0)
    pinger = _mana_dork(name="Prodigal Pyromancer")
    pinger.oracle_text = "{T}: Prodigal Pyromancer deals 1 damage to any target."
    sick = _sick(eng.state, eng, pinger)
    bind_from_catalogue(sick)
    ability = sick.activated_abilities[0]
    p1 = eng.state.active_player
    assert not eng.can_activate(p1, sick, ability)

    hasty = _sick(eng.state, eng, pinger, haste=True)
    bind_from_catalogue(hasty)
    assert eng.can_activate(p1, hasty, hasty.activated_abilities[0])


def test_stack_is_lifo():
    eng = make_engine([land()], hand=0)
    state = eng.state
    resolved = []
    # Two abilities whose effects record their order when resolved.
    from mtg_analyzer.game.effects.core import GameEffect

    class Record(GameEffect):
        def __init__(self, tag):
            super().__init__()
            self.tag = tag

        def apply(self, context, targets=None):
            resolved.append(self.tag)

    from mtg_analyzer.models.game.game_state import StackItem

    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("first")]))
    state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[Record("second")]))
    eng.resolve_until_stable()
    assert resolved == ["second", "first"]


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
    assert bear.damage_marked == 0


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
    assert eng.state.pending_choice["kind"] == "legend_rule"  # RULE 704.5j: the controller picks
    eng.resolve_pending_choice(str(a.instance_id))
    survivors = [o for o in eng.state.battlefield if o.name == "Commander"]
    assert survivors == [a] and b not in survivors


def test_draw_from_empty_library_loses():
    eng = make_engine([land()], [land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()
    eng.rules.draw(p1, 1)
    eng.rules.check_state_based_actions()
    assert p1.has_lost
    assert p1.loss_reason == "draw_from_empty"


def test_deal_damage_to_player_reduces_life():
    eng = make_engine([land()], [land()], hand=0)
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3)
    assert p2.life == 17


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
    assert p2.life == 20


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


def test_triggered_ability_stack_item_carries_its_source():
    """A stack item for a triggered ability exposes the permanent it belongs
    to (`StackItem.source`), so the UI can show that card's image/link."""
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.player_by_id("p1")
    trigger = TriggeredAbility(
        trigger_event=EventType.SPELL_CAST,
        effects=[DrawCardEffect(count=1, player=p1)],
        controller_id="p1",
        description="draw on cast",
        source=None,  # set below, mirroring how the binder sets it
    )
    watcher = obj_on_battlefield(eng.state, eng, creature("Watcher"))
    trigger.source = watcher
    watcher.triggered_abilities.append(trigger)

    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1"))
    eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack) == 1
    assert eng.state.stack[0].source is watcher
    assert eng.state.stack[0].to_dict()["source"]["instance_id"] == watcher.instance_id


def test_skip_untap_step_leaves_permanents_tapped():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    tapped_land = obj_on_battlefield(eng.state, eng, land())
    tapped_land.tap()
    p1.player_effects.append(
        StaticEffect("skip_phase", {"phase": "untap"}, duration="permanent")
    )
    eng.run_turn()
    assert tapped_land.tapped


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
