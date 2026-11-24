"""PAR-285 (v981): stacked negations and the designation / supertype negations on object filters.

* a comma list of negations ("target nonwhite, nonblack creature", Seize the Soul) -- RULE 105.2 / 205.2a, both exclusions apply;
* "nonsnow" (RULE 205.4g supertype, `without_snow`) on targets and on a mass pump ("all nonsnow creatures get -X/-X");
* "noncommander" (RULE 903.3 designation, `is_commander: False`) -- it used to become a creature subtype called
  "Commander", a filter that excludes nothing;
* "nonblocking" (RULE 509.1, `blocking: False`) -- it used to become a subtype called "Blocking";
* the mass "<adjective> creatures can't block this turn" row (Ruthless Invasion).

Tests run parser -> binder -> targeting -> engine on the real cards' text with matching AND non-matching candidates; each
behaviour test fails when the filter key it relies on is not read."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, targeting
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _hand, _put, _session

NEW_CARDS = [
    "Seize the Soul", "Hallowed Ground", "Dead of Winter", "Subjugate the Hobbits", "Ruthless Invasion",
    "Power Word Kill", "Victim of Night", "Unlikely Alliance", "Shoot the Sheriff",
]
CHANGED_CARDS = ["Terror", "Doom Blade", "Ritual of the Machine", "Nekrataal"]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _body(name: str, cost: str, type_line: str = "Creature — Bear", power: int = 2, toughness: int = 2,
          cmc: int = 1, **kw) -> Card:
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=cmc,
                is_creature="Creature" in type_line, is_land="Land" in type_line, power=power, toughness=toughness, **kw)


def _offered(state, spell) -> set:
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    return {o["instance_id"] for o in entry["options"]}


@pytest.mark.parametrize("name", NEW_CARDS + CHANGED_CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shapes():
    (spec,) = match_clause("destroy target nonwhite, nonblack creature")
    assert spec.params["creature_filter"] == {"without_color": ["W", "B"]}
    (spec,) = match_clause("destroy target noncommander creature")
    assert spec.params["creature_filter"] == {"is_commander": False}
    (spec,) = match_clause("target nonattacking, nonblocking creature gets +0/+2 until end of turn")
    assert spec.params["creature_filter"] == {"attacking": False, "blocking": False}
    (spec,) = match_clause("nonartifact creatures can't block this turn")
    # RULE 611.2c: the floating restriction, not a marking of the creatures present
    assert spec.type == "grant_until"
    assert spec.params["static"]["params"]["keywords"] == ["cant_block"]
    assert spec.params["static"]["params"]["affects"]["filter"] == {"card_type": "creature", "without_card_type": "artifact"}
    # adversarial: an unknown "non<word>" must not become a subtype nobody has; a comma not followed by a negation
    assert match_clause("destroy target nonfrobnicated creature") is None
    assert match_clause("nonfrobnicated creatures can't block this turn") is None


def test_seize_the_soul_offers_only_creatures_that_are_neither_white_nor_black():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _real("Seize the Soul"))
    white = _put(state, _body("White", "{W}"), "p2")
    black = _put(state, _body("Black", "{B}"), "p2")
    red = _put(state, _body("Red", "{R}"), "p2")
    colorless = _put(state, _body("Golem", "{2}", type_line="Artifact Creature — Golem", cmc=2), "p2")
    assert _offered(state, spell) == {red.instance_id, colorless.instance_id}
    p1.mana_pool.add_many({"B": 2, "C": 2})
    engine.cast_spell(p1, spell, targets=[red])
    engine.rules.resolve_top_of_stack()
    assert red.zone == Zone.GRAVEYARD and white.zone == Zone.BATTLEFIELD and black.zone == Zone.BATTLEFIELD
    assert any(o.name == "Spirit" for o in state.battlefield)  # the second sentence still resolves


def test_terror_keeps_excluding_artifact_and_black_creatures():
    _, _engine, state = _session()
    spell = _hand(state, _real("Terror"))
    art = _put(state, _body("Golem", "{2}", type_line="Artifact Creature — Golem", cmc=2), "p2")
    black = _put(state, _body("Black", "{B}"), "p2")
    red = _put(state, _body("Red", "{R}"), "p2")
    assert _offered(state, spell) == {red.instance_id}
    assert art.instance_id not in _offered(state, spell) and black.instance_id not in _offered(state, spell)


def test_hallowed_ground_offers_only_your_nonsnow_lands():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    ground = _put(state, _real("Hallowed Ground"), "p1")
    plain = _put(state, Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), "p1")
    snow = _put(state, Card(id="SF", name="Snow-Covered Forest", type_line="Basic Snow Land — Forest", is_land=True), "p1")
    theirs = _put(state, Card(id="M", name="Mountain", type_line="Basic Land — Mountain", is_land=True), "p2")
    engine.recompute_continuous_effects()
    p1.mana_pool.add_many({"W": 4})
    for illegal in (snow, theirs):  # RULE 601.2c: a snow land / an opponent's land is no legal target
        with pytest.raises(ValueError):
            engine.activate_ability(p1, ground, 0, targets=[illegal])
    assert snow.zone == Zone.BATTLEFIELD and theirs.zone == Zone.BATTLEFIELD
    engine.activate_ability(p1, ground, 0, targets=[plain])
    engine.rules.resolve_top_of_stack()
    assert plain.zone == Zone.HAND and snow.zone == Zone.BATTLEFIELD


def test_dead_of_winter_shrinks_nonsnow_creatures_by_the_snow_permanents_you_control():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _real("Dead of Winter"))
    _put(state, Card(id="S1", name="Snow Land", type_line="Basic Snow Land — Forest", is_land=True), "p1")
    _put(state, Card(id="S2", name="Snow Land 2", type_line="Basic Snow Land — Forest", is_land=True), "p1")
    _put(state, Card(id="S3", name="Their Snow", type_line="Basic Snow Land — Island", is_land=True), "p2")  # not counted
    plain = _put(state, _body("Plain", "{G}", power=4, toughness=4), "p2")
    snowy = _put(state, _body("Snowy", "{G}", type_line="Snow Creature — Bear", power=4, toughness=4), "p2")
    frail = _put(state, _body("Frail", "{G}", power=1, toughness=2), "p1")
    p1.mana_pool.add_many({"B": 1, "C": 4})
    engine.cast_spell(p1, spell)
    engine.rules.resolve_top_of_stack()
    engine.recompute_continuous_effects()
    assert (plain.power, plain.toughness) == (2, 2)  # X = 2 snow permanents you control
    assert (snowy.power, snowy.toughness) == (4, 4)
    assert frail.zone == Zone.GRAVEYARD or frail.toughness <= 0


def test_subjugate_the_hobbits_takes_only_cheap_noncommander_creatures():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _real("Subjugate the Hobbits"))
    cheap = _put(state, _body("Cheap", "{1}{R}", cmc=2), "p2")
    costly = _put(state, _body("Costly", "{3}{R}", cmc=4), "p2")
    commander = _put(state, _body("General", "{1}{R}", cmc=2), "p2")
    commander.is_commander = True
    p1.mana_pool.add_many({"U": 2, "C": 5})
    engine.cast_spell(p1, spell)
    engine.rules.resolve_top_of_stack()
    assert cheap.controller_id == "p1"
    assert costly.controller_id == "p2" and commander.controller_id == "p2"


def test_ruthless_invasion_stops_only_nonartifact_creatures_from_blocking():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _real("Ruthless Invasion"))
    bear = _put(state, _body("Bear", "{G}"), "p2")
    golem = _put(state, _body("Golem", "{2}", type_line="Artifact Creature — Golem", cmc=2), "p2")
    p1.mana_pool.add_many({"R": 1, "C": 3})
    engine.cast_spell(p1, spell)
    engine.rules.resolve_top_of_stack()
    engine.recompute_continuous_effects()
    assert combat.has(bear, "cant_block")
    assert not combat.has(golem, "cant_block")


def test_victim_of_night_and_power_word_kill_exclude_every_listed_type():
    _, _engine, state = _session()
    victim = _hand(state, _real("Victim of Night"))
    pwk = _hand(state, _real("Power Word Kill"))
    vamp = _put(state, _body("Vamp", "{B}", type_line="Creature — Vampire"), "p2")
    zombie = _put(state, _body("Zed", "{B}", type_line="Creature — Zombie"), "p2")
    dragon = _put(state, _body("Drake", "{R}", type_line="Creature — Dragon"), "p2")
    bear = _put(state, _body("Bear", "{G}"), "p2")
    assert _offered(state, victim) == {dragon.instance_id, bear.instance_id}
    assert _offered(state, pwk) == {vamp.instance_id, zombie.instance_id, bear.instance_id}


def test_nonblocking_filter_reads_the_blocking_state():
    _, _engine, state = _session()
    attacker = _put(state, _body("Attacker", "{R}"), "p1")
    blocker = _put(state, _body("Blocker", "{G}"), "p2")
    idle = _put(state, _body("Idle", "{G}"), "p2")
    blocker.blocking = attacker.instance_id
    filt = {"attacking": False, "blocking": False}
    assert not combat.matches_object_filter(blocker, filt, state=state)
    assert combat.matches_object_filter(idle, filt, state=state)
    assert combat.matches_object_filter(blocker, {"blocking": True}, state=state)


def test_shoot_the_sheriff_excludes_every_outlaw_type():
    """"non-outlaw" used to become a subtype named "Outlaw" (no creature has it), so every creature was a legal target."""
    _, _engine, state = _session()
    spell = _hand(state, _real("Shoot the Sheriff"))
    pirate = _put(state, _body("Pirate", "{U}", type_line="Creature — Human Pirate"), "p2")
    rogue = _put(state, _body("Rogue", "{B}", type_line="Creature — Elf Rogue"), "p2")
    bear = _put(state, _body("Bear", "{G}"), "p2")
    assert _offered(state, spell) == {bear.instance_id}
    assert pirate.instance_id not in _offered(state, spell) and rogue.instance_id not in _offered(state, spell)
