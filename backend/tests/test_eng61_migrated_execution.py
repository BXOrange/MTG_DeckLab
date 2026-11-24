"""ENG-61: the migrated emitters, parsed from real Oracle clauses and executed on the real engine.

Each test parses the clause, builds the effects the binder builds, resolves them against a real `GameEngine` board
and checks who was (and was not) affected: damage to each creature and each player, counters on each creature you
control, goad of every suspected creature, a command-zone emblem static, and a resolution-locked group grant.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effects.game_status import CreateEmblemEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.emblem_statics import emblem_static_effect_specs
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec

SELF_NAME = "Source"


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _creature(state, name, pid, power=2, toughness=3, **attrs):
    obj = GameObject(Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                          power=power, toughness=toughness), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    for key, value in attrs.items():
        setattr(obj, key, value)
    state.add_to_battlefield(obj)
    return obj


def _source(state, pid="p1"):
    src = GameObject(Card(id="src", name=SELF_NAME, type_line="Sorcery", is_sorcery=True),
                     owner_id=pid, zone=Zone.STACK)
    src.controller_id = pid
    return src


def _resolve(eng, text, src):
    eng.recompute_continuous_effects()
    for effect in build_effects(parse_effect_body(text), src):
        effect.apply(GameContext(eng.state, eng.rules), None)
    eng.recompute_continuous_effects()


def test_damage_to_each_creature_and_each_player_hits_both_sides_once():
    eng, state = _engine()
    mine = _creature(state, "Mine", "p1", toughness=5)
    theirs = _creature(state, "Theirs", "p2", toughness=5)
    _resolve(eng, "~ deals 2 damage to each creature and each player", _source(state))
    assert (mine.damage_marked, theirs.damage_marked) == (2, 2)
    assert (state.player_by_id("p1").life, state.player_by_id("p2").life) == (18, 18)


def test_damage_to_each_creature_alone_leaves_players_alone():
    eng, state = _engine()
    mine = _creature(state, "Mine", "p1", toughness=5)
    theirs = _creature(state, "Theirs", "p2", toughness=5)
    _resolve(eng, "~ deals 2 damage to each creature", _source(state))
    assert (mine.damage_marked, theirs.damage_marked) == (2, 2)
    assert (state.player_by_id("p1").life, state.player_by_id("p2").life) == (20, 20)


def test_counters_on_each_creature_you_control_skip_the_opponents_creatures():
    eng, state = _engine()
    a = _creature(state, "A", "p1")
    b = _creature(state, "B", "p1")
    foe = _creature(state, "Foe", "p2")
    _resolve(eng, "Put a +1/+1 counter on each creature you control", _source(state))
    assert (a.counters.get("+1/+1"), b.counters.get("+1/+1")) == (1, 1)
    assert not foe.counters.get("+1/+1")


def test_goad_of_all_suspected_creatures_reaches_only_the_suspected_ones():
    eng, state = _engine()
    suspect = _creature(state, "Suspect", "p2", is_suspected=True)
    plain = _creature(state, "Plain", "p2")
    mine = _creature(state, "Mine", "p1", is_suspected=True)
    _resolve(eng, "Goad all suspected creatures", _source(state))
    assert combat.is_goaded(suspect) and combat.is_goaded(mine)
    assert not combat.is_goaded(plain)


def test_a_command_zone_emblem_static_applies_to_its_controllers_creatures_only():
    eng, state = _engine()
    text = "Creatures you control have trample and haste and get +2/+2 for each differently named dungeon you've completed"
    effects = emblem_static_effect_specs(text)
    assert effects
    payload = AbilitySpec("static", effects=effects, raw_text=text)
    payload.validate()
    holder = GameObject(Card(id="pw", name="Walker", type_line="Planeswalker", loyalty=5),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(holder)
    bind_from_catalogue(holder)
    CreateEmblemEffect(ability=payload.to_dict(), source=holder).apply(eng.rules.context)
    mine = _creature(state, "Mine", "p1")
    foe = _creature(state, "Foe", "p2")
    eng.recompute_continuous_effects()
    assert combat.has(mine, "haste") and combat.has(mine, "trample")
    assert not combat.has(foe, "haste") and not combat.has(foe, "trample")


def test_a_locked_group_grant_does_not_reach_creatures_that_arrive_after_resolution():
    eng, state = _engine()
    early = _creature(state, "Early", "p1")
    foe = _creature(state, "Foe", "p2")
    _resolve(eng, "Creatures you control get +1/+1 and gain flying until end of turn", _source(state))
    late = _creature(state, "Late", "p1")
    eng.recompute_continuous_effects()
    assert combat.has(early, "flying")
    assert not combat.has(foe, "flying")
    assert not combat.has(late, "flying")  # RULE 611.2c: the set is fixed when the spell resolves
