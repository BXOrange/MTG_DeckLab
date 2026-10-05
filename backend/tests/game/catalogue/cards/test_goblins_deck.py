"""Hand-authored cards of the saved "Goblins" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.game.events import EventType
from tests.support.catalogue import battlefield_object, two_player_game


def _apply(engine, source, spec):
    context = GameContext(state=engine.state, engine=engine.rules)
    for effect in build_effects(spec.effects, source):
        effect.apply(context, [])
    return context


def test_goblin_rabblemaster_forces_only_other_goblins_to_attack():
    engine, player = two_player_game()
    master = battlefield_object(
        engine, player.id, "Goblin Rabblemaster", "Creature — Goblin Warrior",
        is_creature=True, power=2, toughness=2,
    )
    goblin = battlefield_object(
        engine, player.id, "Goblin Token", "Creature — Goblin", is_creature=True, power=1, toughness=1,
    )
    bear = battlefield_object(
        engine, player.id, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2,
    )
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    bind_from_catalogue(master)
    engine.recompute_continuous_effects()
    assert "attacks_if_able" in goblin.granted_keywords
    assert "attacks_if_able" not in master.granted_keywords  # "other"
    assert "attacks_if_able" not in bear.granted_keywords  # Goblins only


def test_goblin_matron_and_wort_register_with_optional_flags():
    assert is_registered("Goblin Matron") and is_registered("Wort, Boggart Auntie")
    (matron,) = _REGISTRY["goblin matron"]()
    assert matron.optional and matron.effects[0].params["criteria"] == {"type": "Goblin"}
    (wort,) = _REGISTRY["wort, boggart auntie"]()
    assert wort.trigger["event"] == EventType.STEP_BEGIN
    assert wort.trigger["filter"] == {"step": "upkeep"} and wort.trigger["phase_relation"] == "you"
    assert wort.effects[0].params["subtype"] == "goblin"


def test_krenko_tin_street_kingpin_counter_then_tokens_equal_to_new_power():
    engine, player = two_player_game()
    krenko = battlefield_object(
        engine, player.id, "Krenko, Tin Street Kingpin", "Legendary Creature — Goblin",
        is_creature=True, power=1, toughness=2,
    )
    (spec,) = _REGISTRY["krenko, tin street kingpin"]()
    _apply(engine, krenko, spec)
    engine.recompute_continuous_effects()
    goblins = [o for o in engine.state.battlefield if o.name == "Goblin"]
    assert krenko.power == 2
    assert len(goblins) == 2  # power *after* the +1/+1 counter


def _declare_attack(engine, attackers):
    state = engine.state
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, attackers)
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    state.current_step = "declare_blockers"


def _loyalist_board(extra_attackers):
    engine, player = two_player_game()
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    loyalist = battlefield_object(
        engine, player.id, "Legion Loyalist", "Creature — Goblin Soldier",
        is_creature=True, power=1, toughness=1,
    )
    bind_from_catalogue(loyalist)
    others = [
        battlefield_object(engine, player.id, f"Bear {i}", "Creature — Bear",
                           is_creature=True, power=2, toughness=2)
        for i in range(extra_attackers)
    ]
    token = battlefield_object(
        engine, "p2", "Spirit", "Creature — Spirit", is_creature=True, power=1, toughness=1,
    )
    token.is_token = True
    real = battlefield_object(
        engine, "p2", "Wall", "Creature — Wall", is_creature=True, power=0, toughness=4,
    )
    for obj in (loyalist, *others):
        obj.summoning_sick = False
    return engine, player, loyalist, others, token, real


def test_legion_loyalist_battalion_grants_and_bars_token_blockers():
    engine, player, loyalist, others, token, real = _loyalist_board(extra_attackers=2)
    _declare_attack(engine, [loyalist, *others])
    engine.recompute_continuous_effects()
    defender = engine.state.player_by_id("p2")
    for obj in (loyalist, *others):
        assert {"first_strike", "trample"} <= set(obj.granted_keywords)
        assert not engine.can_block(defender, token, obj)  # creature tokens can't block
        assert engine.can_block(defender, real, obj)  # a real card still can


def test_legion_loyalist_needs_two_other_attackers():
    engine, player, loyalist, others, token, real = _loyalist_board(extra_attackers=2)
    _declare_attack(engine, [loyalist, others[0]])
    engine.recompute_continuous_effects()
    assert "first_strike" not in loyalist.granted_keywords
    assert engine.can_block(engine.state.player_by_id("p2"), token, loyalist)


def test_coat_of_arms_counts_shared_creature_types_per_recipient():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, player = two_player_game()
    coat = battlefield_object(engine, player.id, "Coat of Arms", "Artifact")
    bind_from_catalogue(coat)
    goblin_a = battlefield_object(engine, player.id, "Goblin A", "Creature — Goblin Warrior",
                                  is_creature=True, power=1, toughness=1)
    goblin_b = battlefield_object(engine, "p2", "Goblin B", "Creature — Goblin Shaman",
                                  is_creature=True, power=1, toughness=1)
    warrior = battlefield_object(engine, player.id, "Warrior", "Creature — Human Warrior",
                                 is_creature=True, power=1, toughness=1)
    bear = battlefield_object(engine, player.id, "Bear", "Creature — Bear",
                              is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()
    # Goblin A shares Goblin with B and Warrior with Warrior; the Coat itself is no creature.
    assert (goblin_a.power, goblin_a.toughness) == (3, 3)
    assert (goblin_b.power, goblin_b.toughness) == (2, 2)  # only Goblin A (an opponent's board counts)
    assert (warrior.power, warrior.toughness) == (2, 2)  # only Goblin A
    assert (bear.power, bear.toughness) == (2, 2)  # shares nothing
