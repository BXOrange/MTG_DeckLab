"""Tests for Dethrone (RULE 702.107): "Whenever this creature attacks the
player with the most life or tied for most life, put a +1/+1 counter on it."

Built as a per-firing procedural check (`RulesEngine.check_dethrone`, called
from `GameEngine.declare_attackers`) rather than a bind-on-load
`TriggeredAbility` — the same "per-firing dynamic" reason `check_rampage`
isn't one either — since Dethrone must also fire off a *dynamically granted*
keyword (Marchesa, the Black Rose's "Other creatures you control have
dethrone.", a layer-6 static that never runs the bind-on-load machinery on
the creatures it affects).
"""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.models.game.game_object import GameObject, Zone


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def creature(name="Fighter", power=2, toughness=2, **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Human"),
        is_creature=True, power=power, toughness=toughness, **kw,
    )


def dethrone_creature(name="Dethroner", power=2, toughness=2):
    return creature(name, power=power, toughness=toughness, keywords=["Dethrone"])


def planeswalker(name="Test Walker", loyalty=5):
    return Card(id=name, name=name, type_line="Legendary Planeswalker — Test", loyalty=loyalty)


def make_engine(*player_ids):
    libs = [(pid, pid, [land()]) for pid in player_ids]
    return GameEngine.new_game(libs, starting_life=20, starting_hand=0)


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


def _counters(obj):
    return obj.counters.get("+1/+1", 0)


def test_dethrone_puts_a_counter_when_the_defender_has_the_most_life():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p1").life = 15
    eng.state.player_by_id("p2").life = 20
    _to_declare_attackers(eng)
    attacker = put(eng.state, dethrone_creature())

    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.resolve_until_stable()

    assert _counters(attacker) == 1


def test_dethrone_does_nothing_when_the_defender_lacks_the_most_life():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p1").life = 25
    eng.state.player_by_id("p2").life = 20
    _to_declare_attackers(eng)
    attacker = put(eng.state, dethrone_creature())

    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.resolve_until_stable()

    assert _counters(attacker) == 0


def test_dethrone_triggers_on_a_tie_for_most_life():
    eng = make_engine("p1", "p2", "p3")
    eng.state.player_by_id("p1").life = 20
    eng.state.player_by_id("p2").life = 20
    eng.state.player_by_id("p3").life = 10
    _to_declare_attackers(eng)
    attacker = put(eng.state, dethrone_creature())

    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": attacker, "defender": {"kind": "player", "id": "p2", "label": "p2"}}],
    )
    eng.resolve_until_stable()

    assert _counters(attacker) == 1


def test_dethrone_checks_the_planeswalkers_controller_not_a_second_target():
    # RULE 702.107a ruling: attacking a planeswalker/battle a player controls
    # still dethrones off *that player's* life total.
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p1").life = 10
    eng.state.player_by_id("p2").life = 20
    _to_declare_attackers(eng)
    walker = put(eng.state, planeswalker(), controller="p2")
    attacker = put(eng.state, dethrone_creature())

    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": attacker, "defender": {"kind": "planeswalker", "instance_id": walker.instance_id}}],
    )
    eng.resolve_until_stable()

    assert _counters(attacker) == 1


def test_non_dethrone_attacker_never_triggers_it():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p2").life = 30
    _to_declare_attackers(eng)
    attacker = put(eng.state, creature())

    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.resolve_until_stable()

    assert _counters(attacker) == 0


# ---------------------------------------------------------------------------
# Marchesa, the Black Rose — "Other creatures you control have dethrone."
# ---------------------------------------------------------------------------


def marchesa():
    return Card(
        id="Marchesa, the Black Rose", name="Marchesa, the Black Rose",
        type_line="Legendary Creature — Human Warrior", is_creature=True,
        power=3, toughness=4, keywords=["Dethrone"],
    )


def test_marchesa_grants_dethrone_to_other_creatures_you_control():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p2").life = 30
    _to_declare_attackers(eng)
    m = put(eng.state, marchesa())
    bind_from_catalogue(m)
    bear = put(eng.state, creature("Bear"))
    eng.recompute_continuous_effects()

    eng.declare_attackers(eng.state.active_player, [bear])
    eng.resolve_until_stable()

    assert _counters(bear) == 1


def test_marchesa_does_not_grant_dethrone_to_an_opponents_creature():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p1").life = 30
    _to_declare_attackers(eng)
    m = put(eng.state, marchesa())
    bind_from_catalogue(m)
    opposing_bear = put(eng.state, creature("Opposing Bear"), controller="p2")
    eng.recompute_continuous_effects()

    # p2 attacks p1 (who has the most life) with a creature Marchesa's
    # controller (p1) doesn't control — "other creatures *you* control"
    # must not reach across the table.
    eng.state.active_player_index = 1
    eng.declare_attackers(eng.state.active_player, [opposing_bear])
    eng.resolve_until_stable()

    assert _counters(opposing_bear) == 0


def test_marchesa_herself_still_dethrones_off_her_own_printed_keyword():
    eng = make_engine("p1", "p2")
    eng.state.player_by_id("p2").life = 30
    _to_declare_attackers(eng)
    m = put(eng.state, marchesa())
    bind_from_catalogue(m)
    eng.recompute_continuous_effects()

    eng.declare_attackers(eng.state.active_player, [m])
    eng.resolve_until_stable()

    assert _counters(m) == 1
