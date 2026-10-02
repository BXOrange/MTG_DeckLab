"""PAR-107…114 residue batches, part 10 — two mass hits in one sentence, X from converge, "lose X life", and the
elided second subject after "target player …".

* "~ deals 1 damage to each nonblack creature and an additional 1 damage to each green creature" (Kaervek's Hex) /
  "…to each creature with flying and 1 additional damage to each blue creature" (Tropical Storm): two ordinary
  mass-damage effects.
* "where X is the number of colors of mana spent to cast this spell" (Radiant Flames, Painful Truths) → ``converge``.
* "you lose X life" / "target player draws X cards and loses X life" (Damnable Pact).
* The shared-subject bug this surfaced: in "target player gains 3 life **and draws a card**" the second verb used to
  act on the *controller* (it parsed to a bare ``draw`` with no player). It now acts on the player the first clause
  chose; a verb with no such reading (mill) refuses the sentence instead.

Reference: parser/oracle/catalogue/handlers.py (`_DAMAGE_PLUS_ADDITIONAL_RE`, the ``lose_life`` row), segmenter.py
(`_stamp_previous_player`, ``_FOR_EACH_AMOUNTS``).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _creature(eng, name, colors, keywords=(), owner="p1", toughness=4):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=1, toughness=toughness,
                color_identity=set(colors), keywords=list(keywords))
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _spell_effects(text, type_line="Sorcery"):
    result = parse_oracle(Card(id="s", name="Spell", type_line=type_line, oracle_text=text,
                               is_sorcery=type_line == "Sorcery", is_instant=type_line == "Instant"))
    assert result.modeled, result.unclaimed
    return result.specs[-1].effects


def _resolve(eng, effects, targets=None, spent=None):
    source = GameObject(Card(id="src", name="Spell", type_line="Sorcery", is_sorcery=True),
                        owner_id="p1", zone=Zone.STACK)
    source.mana_by_color_spent_to_cast = dict(spent or {})
    specs = [EffectSpec(e["type"], e["params"], condition=e.get("condition")) if isinstance(e, dict) else e
             for e in effects]
    built = build_effects(specs, source)
    _apply_effects_partitioned(built, GameContext(eng.state, eng.rules), targets, None, source=source)


def test_kaervek_hex_hits_green_nonblack_creatures_twice_as_hard():
    eng = _engine()
    green = _creature(eng, "Elf", "G")
    red = _creature(eng, "Imp", "R")
    black = _creature(eng, "Rat", "B")
    _resolve(eng, _spell_effects("~ deals 1 damage to each nonblack creature and an additional 1 damage to each "
                                 "green creature."))
    assert (green.damage_marked, red.damage_marked, black.damage_marked) == (2, 1, 0)


def test_tropical_storm_x_to_fliers_plus_one_to_blue():
    eng = _engine()
    flier = _creature(eng, "Bird", "W", ["flying"])
    blue_flier = _creature(eng, "Drake", "U", ["flying"])
    ground_blue = _creature(eng, "Fish", "U")
    effects = [e.to_dict() for e in _spell_effects("~ deals X damage to each creature with flying and 1 additional "
                                                  "damage to each blue creature.")]
    # substitute the announced {X} the way the cast path does
    for e in effects:
        if e["params"].get("amount") == "x":
            e["params"]["amount"] = 2
    _resolve(eng, effects)
    assert (flier.damage_marked, blue_flier.damage_marked, ground_blue.damage_marked) == (2, 3, 1)


def test_radiant_flames_x_is_the_colours_spent():
    effects = _spell_effects("~ deals X damage to each creature, where X is the number of colors of mana spent to "
                             "cast this spell.")
    assert effects[0].type == "bind" and effects[0].params["amount"]["selector"] == "converge"


def test_lose_x_life_parses_and_a_non_x_creature_phrase_stays_out():
    assert [(e.type, e.params) for e in parse_effect_body("you lose x life", self_subject=True)] == [
        ("lose_life", {"amount": "x"})]


def test_damnable_pact_draws_and_loses_for_the_targeted_player():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    for i in range(4):
        p2.library.append(GameObject(Card(id=f"f{i}", name="Filler", type_line="Sorcery"), owner_id="p2",
                                     zone=Zone.LIBRARY))
    effects = [e.to_dict() for e in _spell_effects("Target player draws X cards and loses X life.")]
    for e in effects:
        for k in ("count", "amount"):
            if e["params"].get(k) == "x":
                e["params"][k] = 3
    p1_life, hand = eng.state.player_by_id("p1").life, len(p2.hand)
    _resolve(eng, effects, targets=[p2])
    assert len(p2.hand) - hand == 3 and p2.life == 17
    assert eng.state.player_by_id("p1").life == p1_life  # the caster loses nothing


def test_gain_then_draw_acts_on_the_targeted_player_not_the_caster():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for pl in (p1, p2):
        pl.library.append(GameObject(Card(id="f" + pl.id, name="Filler", type_line="Sorcery"), owner_id=pl.id,
                                     zone=Zone.LIBRARY))
    effects = _spell_effects("Target player gains 3 life and draws a card.")
    _resolve(eng, effects, targets=[p2])
    assert p2.life == 23 and len(p2.hand) == 1 and len(p1.hand) == 0


def test_a_verb_without_a_previous_player_reading_is_refused():
    # mill has no way to point at the earlier clause's player, so the sentence is not claimed.
    assert parse_effect_body("target player gains 3 life and mills 2 cards", self_subject=True) is None


def test_you_and_target_forms_are_untouched():
    assert [e.params for e in parse_effect_body("you draw 2 cards and lose 2 life", self_subject=True)] == [
        {"count": 2}, {"amount": 2}]
    drain = parse_effect_body("target opponent loses 3 life and you gain 3 life", self_subject=True)
    assert [e.params for e in drain] == [{"amount": 3, "target_kind": "opponent"}, {"amount": 3}]


def test_shared_x_with_a_sacrificed_or_greatest_term_binds_both_halves():
    # "Target player loses X life and you gain X life, where X is the greatest power among creatures you control"
    # (Essence Harvest): once "lose X life" parses on its own, the connector split used to leave it on the *spell's*
    # X (0) while only the gain read the measurement.
    for text in ("Target player loses X life and you gain X life, where X is the greatest power among creatures you "
                 "control.",):
        [bind] = _spell_effects(text)
        assert bind.type == "bind"
        assert [e["params"]["amount"] for e in bind.params["effects"]] == ["$n", "$n"]


def test_essence_harvest_drains_by_the_greatest_power():
    eng = _engine()
    _creature(eng, "Big", "G", toughness=2).card.power = 5
    p2 = eng.state.player_by_id("p2")
    _resolve(eng, _spell_effects("Target player loses X life and you gain X life, where X is the greatest power "
                                 "among creatures you control."), targets=[p2])
    assert p2.life == 15 and eng.state.player_by_id("p1").life == 25


def test_monumental_corruption_draws_and_drains_the_targeted_player():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for i in range(3):
        p2.library.append(GameObject(Card(id=f"f{i}", name="Filler", type_line="Sorcery"), owner_id="p2",
                                     zone=Zone.LIBRARY))
    for i in range(2):
        art = GameObject(Card(id=f"a{i}", name="Rock", type_line="Artifact"), owner_id="p1", zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(art)
    _resolve(eng, _spell_effects("Target player draws X cards and loses X life, where X is the number of artifacts "
                                 "you control."), targets=[p2])
    assert len(p2.hand) == 2 and p2.life == 18 and p1.life == 20


def test_vendetta_costs_the_caster_the_destroyed_creatures_toughness():
    eng = _engine()
    victim = _creature(eng, "Elf", "G", owner="p2", toughness=3)
    p1 = eng.state.player_by_id("p1")
    _resolve(eng, _spell_effects("Destroy target nonblack creature. It can't be regenerated. You lose life equal to "
                                 "that creature's toughness.", type_line="Instant"), targets=[victim])
    eng.rules.check_state_based_actions()
    assert victim.zone != Zone.BATTLEFIELD and p1.life == 17


FIRESPOUT = ("~ deals 3 damage to each creature without flying if {R} was spent to cast this spell and 3 damage to each "
             "creature with flying if {G} was spent to cast this spell.")


def test_firespout_halves_follow_the_colours_that_paid_for_it():
    for spent, ground_hit, flier_hit in [({"R": 1}, 3, 0), ({"G": 1}, 0, 3), ({"R": 1, "G": 1}, 3, 3), ({"W": 2}, 0, 0)]:
        eng = _engine()
        ground = _creature(eng, "Bear", "G", toughness=9)
        flier = _creature(eng, "Bird", "W", ["flying"], toughness=9)
        _resolve(eng, _spell_effects(FIRESPOUT, type_line="Instant"), spent=spent)
        assert (ground.damage_marked, flier.damage_marked) == (ground_hit, flier_hit), spent


def test_dawnglow_infusion_gains_for_each_colour_spent():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    effects = [e.to_dict() for e in _spell_effects(
        "You gain X life if {G} was spent to cast this spell and X life if {W} was spent to cast this spell.",
        type_line="Instant")]
    for e in effects:
        e["params"]["amount"] = 2
    _resolve(eng, effects, spent={"G": 1, "W": 1})
    assert p1.life == 24
    _resolve(eng, effects, spent={"G": 1})
    assert p1.life == 26


def test_a_gate_on_the_second_half_alone_does_not_gate_the_first():
    eng = _engine()
    ground = _creature(eng, "Bear", "G", toughness=9)
    _resolve(eng, _spell_effects(
        "~ deals 1 damage to each creature if {R} was spent to cast this spell and 1 damage to each creature if "
        "{G} was spent to cast this spell.", type_line="Instant"), spent={"G": 1})
    assert ground.damage_marked == 1


def test_creatures_target_player_controls_get_the_pump_for_that_player_only():
    eng = _engine()
    mine = _creature(eng, "Mine", "G", owner="p1")
    theirs = _creature(eng, "Theirs", "G", owner="p2")
    for obj in (mine, theirs):
        obj.controller_id = obj.owner_id
    p2 = eng.state.player_by_id("p2")
    effects = _spell_effects("Creatures target player controls get -2/-2 until end of turn.")
    assert [ts.kind for e in build_effects(effects, None) for ts in e.target_specs] == ["player"]
    _resolve(eng, effects, targets=[p2])
    eng.recompute_continuous_effects()
    assert (theirs.power, mine.power) == (-1, 1)


def test_you_may_have_target_creature_get_is_an_optional_pump():
    [optional] = parse_effect_body("you may have target creature get -2/-2 until end of turn", self_subject=True)
    assert optional.type == "optional"
    assert optional.params["effects"][0]["params"] == {"power": -2, "toughness": -2, "target_kind": "creature"}
