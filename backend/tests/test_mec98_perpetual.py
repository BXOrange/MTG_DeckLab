"""MEC-98 — Alchemy "perpetually gets +N/+N / gains <keyword>".

A perpetual change is an until-end-of-turn pump in every respect but its
duration: it survives cleanup (RULE 514.2) *and* every zone change (the one
exception to RULE 400.7's "effects are not retained"), reaches cards in hand/
library/graveyard, and is carried onto a copy. Engine: `GameObject.
perpetual_*` + `PumpEffect.perpetual`/``card_zones``; parser: `handlers.
_perpetual_pump_specs`, which reuses the pump table via an "until end of
turn" rewrite.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def bear(name="Bear", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def to_zone(state, card, zone_name, controller="p1"):
    zone = {"hand": Zone.HAND, "library": Zone.LIBRARY, "graveyard": Zone.GRAVEYARD}[zone_name]
    obj = GameObject(card, owner_id=controller, zone=zone)
    getattr(state.player_by_id(controller), zone_name).append(obj)
    return obj


def pump(engine, params, source, targets=None):
    effect = EffectRegistry.create("pump", params)
    effect.source = source
    effect.apply(GameContext(engine.state, engine.rules), targets)
    engine.recompute_continuous_effects()


# -- parse --------------------------------------------------------------------


def test_parse_targeted_perpetual_debuff():
    specs = match_clause("target creature an opponent controls perpetually gets -1/-2")
    assert [s.type for s in specs] == ["pump"]
    p = specs[0].params
    assert (p["power"], p["toughness"], p["perpetual"]) == (-1, -2, True)
    assert p["target_kind"] == "creature_you_dont_control"


def test_parse_keyword_and_pronoun():
    specs = match_clause("it perpetually gets +1/+1", previous_subject=True)
    assert specs[0].params["previous_subject"] is True
    assert specs[0].params["perpetual"] is True
    kw = match_clause("target creature you control perpetually gains lifelink")
    assert kw[0].params["keywords"] == ["lifelink"]


def test_parse_zone_group():
    specs = match_clause(
        "creatures you control and creature cards in your hand, library, and graveyard "
        "perpetually get +1/+1"
    )
    p = specs[0].params
    assert p["card_zones"] == ["hand", "library", "graveyard"]
    assert p["selector"] == "creatures_you_control"
    assert p["card_type"] == "creature"


def test_parse_refuses_quoted_ability_grant():
    # A granted quoted ability has no perpetual primitive yet — fail closed.
    assert match_clause('target creature perpetually gains "this spell costs {1} less to cast."') is None


def test_parse_refuses_pronoun_without_referent():
    assert match_clause("it perpetually gets +1/+1") is None


def test_begin_anew_is_modeled():
    card = Card(
        id="Begin Anew", name="Begin Anew", type_line="Sorcery", is_sorcery=True,
        oracle_text="Destroy all creatures. Creature cards in your hand perpetually get +1/+1.",
    )
    assert parse_oracle(card).modeled is True


# -- execute ------------------------------------------------------------------


def test_perpetual_pump_survives_cleanup_and_zone_change():
    engine = make_engine("p1", "p2")
    target = put(engine.state, bear())
    pump(engine, {"power": 1, "toughness": 1, "keywords": ["flying"], "perpetual": True,
                  "target_kind": "creature"}, target, [target])
    assert (target.power, target.toughness) == (3, 3)
    assert "flying" in target.granted_keywords
    assert target.temp_power == 0

    # Bounce and replay: RULE 400.7 would forget an until-EOT pump; not this.
    engine.rules.return_to_hand(target)
    assert target.zone == Zone.HAND
    assert (target.power, target.toughness) == (3, 3)  # off-battlefield fallback
    player = engine.state.player_by_id("p1")
    player.hand.remove(target)
    target.reset_as_new_object()
    target.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(target)
    engine.recompute_continuous_effects()
    assert (target.power, target.toughness) == (3, 3)
    assert "flying" in target.granted_keywords


def test_until_eot_pump_is_still_forgotten():
    # Negative control: the ordinary pump is unchanged.
    engine = make_engine("p1", "p2")
    target = put(engine.state, bear())
    pump(engine, {"power": 1, "toughness": 1, "target_kind": "creature"}, target, [target])
    assert target.power == 3
    target.reset_as_new_object()
    engine.recompute_continuous_effects()
    assert target.power == 2


def test_zone_group_reaches_hand_library_graveyard_and_battlefield():
    engine = make_engine("p1", "p2")
    state = engine.state
    source = put(state, bear("Source"))
    in_hand = to_zone(state, bear("H"), "hand")
    in_library = to_zone(state, bear("L"), "library")
    in_gy = to_zone(state, bear("G"), "graveyard")
    not_creature = to_zone(state, Card(id="Bolt", name="Bolt", type_line="Instant", is_instant=True), "hand")
    theirs = to_zone(state, bear("Theirs"), "hand", controller="p2")
    pump(engine, {"power": 1, "toughness": 1, "perpetual": True,
                  "card_zones": ["hand", "library", "graveyard"], "card_type": "creature",
                  "selector": "creatures_you_control"}, source)
    assert (source.power, in_hand.power, in_library.power, in_gy.power) == (3, 3, 3, 3)
    assert not_creature.perpetual_power == 0
    assert theirs.power == 2


def test_token_copy_carries_perpetual_changes():
    engine = make_engine("p1", "p2")
    original = put(engine.state, bear())
    original.perpetual_power = 2
    original.perpetual_toughness = 2
    tokens = engine.rules.copy_permanent("p1", original)
    engine.recompute_continuous_effects()
    assert (tokens[0].power, tokens[0].toughness) == (4, 4)


def test_stalwart_speartail_enrage_reaches_hand_and_library_dinosaurs():
    engine = make_engine("p1", "p2")
    state = engine.state
    speartail = put(state, Card(
        id="Stalwart Speartail", name="Stalwart Speartail",
        type_line="Creature — Dinosaur", is_creature=True, power=3, toughness=3,
    ))
    other_dino = put(state, Card(id="Rex", name="Rex", type_line="Creature — Dinosaur",
                                 is_creature=True, power=2, toughness=2))
    bystander = put(state, bear())
    dino_in_hand = to_zone(state, Card(id="Raptor", name="Raptor", type_line="Creature — Dinosaur",
                                       is_creature=True, power=1, toughness=1), "hand")
    enrage = [a for a in speartail.triggered_abilities
              if any(getattr(e, "perpetual", False) for e in a.effects)]
    assert len(enrage) == 1
    for effect in enrage[0].effects:
        effect.source = speartail
        effect.apply(GameContext(state, engine.rules), None)
    engine.recompute_continuous_effects()
    assert (other_dino.power, dino_in_hand.power) == (3, 2)
    assert speartail.power == 3  # "other" Dinosaurs
    assert bystander.power == 2
