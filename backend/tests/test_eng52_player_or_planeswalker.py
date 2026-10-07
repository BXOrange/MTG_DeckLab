"""ENG-52: "target player or planeswalker" is a real target kind (a planeswalker can be chosen, the
controller's own seat is a legal player), and a later clause's "any other target" / "another target …"
is kept distinct from what an earlier clause of the same spell chose (RULE 109.5 / 115.3)."""

from __future__ import annotations

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])
    engine = GameEngine(state)
    state.current_step = "main1"
    return engine, state, state.players[0], state.players[1]


def _permanent(state, name, type_line, controller="p1", **kw):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, converted_mana_cost=2,
             is_creature="Creature" in type_line, **kw),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _spell(player, name, oracle, mana_cost="{R}{R}"):
    spell = GameObject(
        Card(id=name, name=name, type_line="Sorcery", mana_cost_string=mana_cost, converted_mana_cost=2,
             is_sorcery=True, oracle_text=oracle),
        owner_id=player.id, zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    return spell


def _ids(options):
    return {o.get("player_id") or o.get("instance_id") for o in options}


# -- the kind ------------------------------------------------------------------


def test_kind_offers_every_player_and_every_planeswalker_but_no_creature():
    engine, state, p1, p2 = _engine()
    jace = _permanent(state, "Jace", "Legendary Planeswalker — Jace", controller="p2", loyalty=3)
    bear = _permanent(state, "Bear", "Creature — Bear", power=2, toughness=2)
    options = targeting.legal_targets(state, "p1", targeting.TargetSpec(kind="player_or_planeswalker"))
    assert _ids(options) == {"p1", "p2", jace.instance_id}
    assert bear.instance_id not in _ids(options)
    assert targeting.TargetSpec(kind="player_or_planeswalker").label() == "Spieler oder Planeswalker"


def test_opponent_or_planeswalker_still_excludes_the_controller():
    engine, state, p1, p2 = _engine()
    options = targeting.legal_targets(state, "p1", targeting.TargetSpec(kind="opponent_or_planeswalker"))
    assert _ids(options) == {"p2"}


# -- the parser ----------------------------------------------------------------


def test_player_or_planeswalker_phrase_resolves_to_the_new_kind():
    specs = parse_effect_body("~ deals 3 damage to target player or planeswalker.")
    assert specs is not None and specs[0].params["target_kind"] == "player_or_planeswalker"


def test_compound_damage_stamps_the_second_target_distinct():
    specs = parse_effect_body("~ deals 2 damage to any target and 1 damage to any other target.")
    assert [s.params.get("distinct_from_others") for s in specs] == [None, True]
    specs = parse_effect_body("~ deals 3 damage to target creature and 2 damage to target player or planeswalker.")
    assert [s.params["target_kind"] for s in specs] == ["creature", "player_or_planeswalker"]
    assert all("distinct_from_others" not in s.params for s in specs)


def test_a_later_sentence_naming_another_target_is_distinct():
    specs = parse_effect_body(
        "return target creature to its owner's hand. ~ deals 2 damage to another target creature."
    )
    assert specs[-1].params.get("distinct_from_others") is True


def test_a_single_clause_other_target_is_unchanged():
    specs = parse_effect_body("~ deals 3 damage to any other target.")
    assert specs is not None and "distinct_from_others" not in specs[0].params


def test_other_target_of_an_effect_without_the_parameter_stays_unclaimed():
    # "any other target" lost its meaning silently before; a verb that cannot carry the flag still refuses.
    assert parse_effect_body("you gain 2 life and 1 life to any other target.") is None


# -- the engine ----------------------------------------------------------------


def test_hungry_flames_hits_a_creature_and_a_planeswalker():
    engine, state, p1, p2 = _engine()
    jace = _permanent(state, "Jace", "Legendary Planeswalker — Jace", controller="p2", loyalty=5)
    bear = _permanent(state, "Bear", "Creature — Bear", controller="p2", power=2, toughness=2)
    flames = _spell(
        p1, "Hungry Flames",
        "Hungry Flames deals 3 damage to target creature and 2 damage to target player or planeswalker.",
    )
    p1.mana_pool.add("R", 2)
    engine.cast_spell(p1, flames, targets=[bear, jace])
    engine.resolve_until_stable()
    assert bear not in state.battlefield
    assert jace.loyalty == 3  # RULE 120.3c: damage to a planeswalker removes loyalty counters


def test_arc_trail_requirements_mark_the_second_target_distinct_and_hit_two_players():
    engine, state, p1, p2 = _engine()
    trail = _spell(p1, "Arc Trail", "Arc Trail deals 2 damage to any target and 1 damage to any other target.")
    rounds = targeting.requirements_with_targets(state, "p1", trail)
    assert [r["distinct_from_others"] for r in rounds] == [False, True]
    p1.mana_pool.add("R", 2)
    engine.cast_spell(p1, trail, targets=[p2, p1])
    engine.resolve_until_stable()
    assert (p2.life, p1.life) == (18, 19)


def test_a_pump_clause_naming_another_target_is_distinct_for_any_verb():
    # The binder stamps the flag on the effect's own requirement, so verbs whose factory never read it work too.
    engine, state, p1, p2 = _engine()
    a = _permanent(state, "A", "Creature — Bear", power=3, toughness=3)
    b = _permanent(state, "B", "Creature — Bear", controller="p2", power=3, toughness=3)
    spell = _spell(
        p1, "Rites of Reaping",
        "Target creature gets +3/+3 until end of turn. Another target creature gets -3/-3 until end of turn.",
        mana_cost="{B}{G}",
    )
    rounds = targeting.requirements_with_targets(state, "p1", spell)
    assert [r["distinct_from_others"] for r in rounds] == [False, True]
    p1.mana_pool.add_many({"B": 1, "G": 1})
    engine.cast_spell(p1, spell, targets=[a, b])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (a.power, b.power) == (6, 0)
