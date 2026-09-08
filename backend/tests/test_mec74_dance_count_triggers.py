"""MEC-74 — Dance of the Elements count-sensitive trigger package."""

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _card(name, type_line, *, power=None, toughness=None, oracle_text=""):
    return Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
                is_land="Land" in type_line,
                power=power, toughness=toughness, oracle_text=oracle_text)


def _put(eng, card, controller="p1", bind=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _resolve_event(eng, event):
    eng.state.fire_event(event)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


def test_avenger_counts_lands_for_plants_then_landfall_counters_only_plants():
    eng = _engine()
    avenger = _put(eng, _card("Avenger of Zendikar", "Creature — Elemental", power=5, toughness=5), bind=True)
    for name in ("Forest", "Island"):
        _put(eng, _card(name, "Basic Land — " + name))

    _resolve_event(eng, GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=avenger.instance_id,
                                  controller_id="p1", object_types=["creature"]))
    plants = [o for o in eng.state.battlefield if "Plant" in o.card.type_line]
    assert len(plants) == 2

    land = _put(eng, _card("Mountain", "Basic Land — Mountain"))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=land.instance_id,
                                   controller_id="p1", object_types=["land"]))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    assert [plant.counters.get("+1/+1") for plant in plants] == [1, 1]


def test_omnath_and_vernal_use_live_elemental_and_creature_counts():
    eng = _engine()
    omnath = _put(eng, _card("Omnath, Locus of the Roil", "Legendary Creature — Elemental", power=3, toughness=3), bind=True)
    _put(eng, _card("Other Elemental", "Creature — Elemental", power=1, toughness=1))
    damage = specs_for(omnath.card)[0].effects[0]
    build_effects([damage], omnath)[0].apply(eng.rules.context, targets=[eng.state.player_by_id("p2")])
    assert eng.state.player_by_id("p2").life == 18

    vernal = _put(eng, _card("Vernal Sovereign", "Creature — Elemental Elk", power=4, toughness=4), bind=True)
    etb = specs_for(vernal.card)[0].effects[0]
    build_effects([etb], vernal)[0].apply(eng.rules.context)
    token = next(o for o in eng.state.battlefield if o.is_token and "Elemental" in o.card.type_line)
    # The token sees itself after entering, so its CDA includes all four creatures.
    eng.recompute_continuous_effects()
    assert (token.power, token.toughness) == (4, 4)


def test_omnath_eight_land_draw_gate_and_garruk_static_threshold_are_live():
    eng = _engine()
    omnath = _put(eng, _card("Omnath, Locus of the Roil", "Legendary Creature — Elemental", power=3, toughness=3), bind=True)
    for n in range(8):
        _put(eng, _card(f"Land {n}", "Land"))
    eng.state.player_by_id("p1").library.append(GameObject(_card("Draw", "Sorcery"), "p1", Zone.LIBRARY))
    landfall = specs_for(omnath.card)[1].effects
    for effect in build_effects(landfall, omnath):
        effect.apply(eng.rules.context)
    assert omnath.counters.get("+1/+1") == 1
    assert len(eng.state.player_by_id("p1").hand) == 1

    garruk = _put(eng, _card("Garruk's Uprising", "Enchantment"), bind=True)
    beast = _put(eng, _card("Beast", "Creature — Beast", power=4, toughness=4))
    eng.recompute_continuous_effects()
    assert "trample" in beast.granted_keywords
    eng.state.player_by_id("p1").library.append(GameObject(_card("Draw 2", "Sorcery"), "p1", Zone.LIBRARY))
    draw = specs_for(garruk.card)[0].effects[0]
    build_effects([draw], garruk)[0].apply(eng.rules.context)
    assert len(eng.state.player_by_id("p1").hand) == 2
