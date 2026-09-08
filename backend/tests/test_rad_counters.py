"""RULE 728 — Rad Counters (deprioritized in `10_COMPLETION_ROADMAP.md` M6
until a deck needed them; see `docs/implementation-state/BACKLOG.md`).

Rad counters are a kind of player counter (RULE 122) with an inherent,
source-less triggered ability controlled by the active player (RULE 113.8
exception): "At the beginning of each player's precombat main phase, if that
player has one or more rad counters, that player mills a number of cards
equal to the number of rad counters they have. For each nonland card milled
this way, that player loses 1 life and removes one rad counter from
themselves." (RULE 728.1)

Modeled the same way as Monarch/Initiative (`RulesEngine.
_collect_inherent_triggers`, `game/effects/core.py`'s `RadiationMillEffect`):
built fresh off live state each time a matching `STEP_BEGIN`/"main1" event
fires, rather than attached to any permanent — nothing hosts this ability.
Reuses the existing generic `Player.counters["rad"]` slot (the same one
energy/experience already use) and `RulesEngine.add_player_counters`/`mill`/
`lose_life`, so RULE 728.1a's "life lost 'from radiation'" is tagged via
`lose_life(..., cause="radiation")`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _creature(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=power, toughness=toughness)


def _land(name):
    return Card(id=name, name=name, type_line="Land", is_land=True)


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _fill_library(player, nonland_count, land_count):
    for i in range(nonland_count):
        player.library.append(GameObject(_creature(f"Nonland {i}"), owner_id=player.id, zone=Zone.LIBRARY))
    for i in range(land_count):
        player.library.append(GameObject(_land(f"Land {i}"), owner_id=player.id, zone=Zone.LIBRARY))


def test_rad_counters_mill_and_lose_life_for_nonland_cards():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _fill_library(p1, nonland_count=2, land_count=1)
    p1.counters["rad"] = 3
    life_before = p1.life

    state.active_player_index = 0
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", phase="precombat_main"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(p1.graveyard) == 3
    assert p1.life == life_before - 2
    assert p1.counters.get("rad", 0) == 1


def test_rad_counters_all_land_milled_removes_no_counters_or_life():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _fill_library(p1, nonland_count=0, land_count=2)
    p1.counters["rad"] = 2
    life_before = p1.life

    state.active_player_index = 0
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", phase="precombat_main"))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert len(p1.graveyard) == 2
    assert p1.life == life_before
    assert p1.counters.get("rad", 0) == 2


def test_no_rad_counters_does_not_trigger():
    eng = _engine()
    state = eng.state
    state.active_player_index = 0
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", phase="precombat_main"))
    assert eng.rules.put_triggers_on_stack() == 0


def test_only_active_players_rad_counters_trigger():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    p2.counters["rad"] = 5

    state.active_player_index = 0  # p1's own precombat main — p2 has rad counters, not p1
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", phase="precombat_main"))
    assert eng.rules.put_triggers_on_stack() == 0
    assert p2.counters.get("rad", 0) == 5


def test_life_lost_from_rad_counters_is_tagged_radiation():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _fill_library(p1, nonland_count=1, land_count=0)
    p1.counters["rad"] = 1

    seen = []
    state.subscribe(lambda e: seen.append(e) if e.type == EventType.LIFE_LOST else None)

    state.active_player_index = 0
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", phase="precombat_main"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert len(seen) == 1
    assert seen[0].get("cause") == "radiation"


def test_full_turn_loop_fires_rad_trigger_on_own_precombat_main():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _fill_library(p1, nonland_count=1, land_count=0)
    p1.counters["rad"] = 1
    life_before = p1.life

    # Advance through the whole turn structure rather than firing the event
    # by hand, to confirm the phase loop itself reaches "main1" and drives
    # the trigger through the ordinary resolve_until_stable pipeline.
    state.active_player_index = 0
    while state.current_step != "main1" or state.current_phase != "precombat_main":
        eng.advance_step()

    assert p1.life == life_before - 1
    assert p1.counters.get("rad", 0) == 0


# ---------------------------------------------------------------------------
# Granting rad counters — oracle-text handlers (`add_player_counters`/
# `lose_all_player_counters`/`dies_grants_rad_counters_equal_power`/
# `radiation_life_gain`) and the hand-authored combat-damage marker
# (Glowing One/Infesting Radroach-shaped). ~23 real Fallout-set cards use
# "rad counter" oracle text (`backend/cache/db/cards.db`); most of these
# clauses now parse correctly even where the card as a whole stays
# UNMODELED because of an unrelated gap (a mill-triggered draw, a compound
# "enters or attacks" trigger, etc.) — see `docs/implementation-state/BACKLOG.md`.
# ---------------------------------------------------------------------------


def _sorcery(name, oracle_text, mana="{1}{U}"):
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=oracle_text,
                mana_cost_string=mana, converted_mana_cost=2, is_sorcery=True)


def test_oracle_text_you_get_n_rad_counters():
    result = parse_oracle(_sorcery("iso1", "You get two rad counters."))
    assert result.modeled
    assert result.specs[0].effects[0].type == "add_player_counters"
    assert result.specs[0].effects[0].params == {"amount": 2, "kind": "rad"}


def test_oracle_text_target_player_gets_n_rad_counters():
    result = parse_oracle(_sorcery("iso2", "Target player gets four rad counters."))
    assert result.modeled
    params = result.specs[0].effects[0].params
    assert params == {"amount": 4, "kind": "rad", "target_kind": "player"}


def test_oracle_text_each_opponent_gets_x_rad_counters():
    result = parse_oracle(_sorcery("iso3", "Each opponent gets X rad counters.", mana="{X}{U}"))
    assert result.modeled
    params = result.specs[0].effects[0].params
    assert params == {"amount": "x", "kind": "rad", "selector": "each_opponent"}


def test_oracle_text_lose_all_rad_counters():
    result = parse_oracle(_sorcery("iso4", "Target player loses all rad counters."))
    assert result.modeled
    assert result.specs[0].effects[0].type == "lose_all_player_counters"
    assert result.specs[0].effects[0].params == {"kind": "rad", "target_kind": "player"}


def test_oracle_text_radiation_life_gain_static():
    result = parse_oracle(Card(
        id="iso5", name="iso5", type_line="Enchantment",
        oracle_text="You gain life rather than lose life from radiation.",
        mana_cost_string="{1}{W}", converted_mana_cost=2,
    ))
    assert result.modeled
    assert result.specs[0].effects[0].type == "radiation_life_gain"


def test_add_player_counters_effect_selectors_and_defending_player():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    from mtg_analyzer.game.effects.core import AddPlayerCountersEffect

    # Untargeted (self/controller).
    obj = GameObject(_creature("Src"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(obj)
    AddPlayerCountersEffect(amount=2, kind="rad", source=obj).apply(eng.rules.context)
    assert p1.counters.get("rad", 0) == 2

    # each_opponent selector, controlled by p1.
    AddPlayerCountersEffect(amount=1, kind="rad", selector="each_opponent", source=obj).apply(eng.rules.context)
    assert p2.counters.get("rad", 0) == 1
    assert p1.counters.get("rad", 0) == 2  # unaffected — p1 is the controller

    # each_player selector.
    AddPlayerCountersEffect(amount=1, kind="rad", selector="each_player", source=obj).apply(eng.rules.context)
    assert p1.counters.get("rad", 0) == 3
    assert p2.counters.get("rad", 0) == 2


def test_lose_all_player_counters_effect():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    p1.counters["rad"] = 5

    from mtg_analyzer.game.effects.core import LoseAllPlayerCountersEffect

    LoseAllPlayerCountersEffect(kind="rad", player=p1).apply(eng.rules.context)
    assert p1.counters.get("rad", 0) == 0


def test_dies_grants_rad_counters_equal_power_end_to_end():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    card = _creature("Feral Ghoul Test", power=3, toughness=3)
    card.oracle_text = "When this creature dies, each opponent gets a number of rad counters equal to its power."
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()

    eng.rules.destroy(obj)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert p2.counters.get("rad", 0) == 3
    assert p1.counters.get("rad", 0) == 0


def test_hand_authored_glowing_one_grants_flat_rad_counters_on_combat_damage():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")

    obj = GameObject(_creature("Glowing One", power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    eng.rules.deal_damage(p2, 2, obj, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert p2.counters.get("rad", 0) == 4


def test_hand_authored_infesting_radroach_grants_rad_counters_equal_to_damage():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")

    obj = GameObject(_creature("Infesting Radroach", power=3, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()

    assert "cant_block" in obj.granted_keywords

    eng.rules.deal_damage(p2, 3, obj, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    assert p2.counters.get("rad", 0) == 3


def test_radiation_life_gain_redirects_lose_life():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    life_before = p1.life

    obj = GameObject(_creature("Radiation Static Source"), owner_id="p1", zone=Zone.BATTLEFIELD)
    attach_to_object(obj, [AbilitySpec("static", [EffectSpec("radiation_life_gain", {})])])
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()

    eng.rules.lose_life(p1, 3, cause="radiation")
    assert p1.life == life_before + 3


def test_radiation_life_gain_does_not_affect_ordinary_life_loss():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    life_before = p1.life

    obj = GameObject(_creature("Radiation Static Source"), owner_id="p1", zone=Zone.BATTLEFIELD)
    attach_to_object(obj, [AbilitySpec("static", [EffectSpec("radiation_life_gain", {})])])
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()

    eng.rules.lose_life(p1, 3, cause="effect")
    assert p1.life == life_before - 3
