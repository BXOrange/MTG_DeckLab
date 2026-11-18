"""PAR-285: the single-card graveyard pick's subtype slot and "tapped under your control".

"return target knight card from your graveyard to your hand" (RULE 205.3), "<A> or <B> creature card" and "put target
creature card from a graveyard onto the battlefield tapped under your control" (RULE 110.5b). Tests run parser ->
binder -> `legal_targets` -> effect on the real cards' text."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_mec118_opponent_choice import _engine, _put

NEWLY_COVERED = [
    "Angel of Flight Alabaster", "Atzocan Seer", "Barrow Witches", "Bladewing the Risen", "Bloodline Necromancer",
    "Boggart Birth Rite", "Bruna, the Fading Light", "Demon of Dark Schemes", "Mirkwood Elk", "Spawnbed Protector",
]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _returns(name: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    return [e for ab in result.specs if ab.effects for e in ab.effects if e.type == "return_from_graveyard"]


def _card(name: str, type_line: str, **kw) -> Card:
    return Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
                power=2, toughness=2, **kw)


def _offered(eng, effect, who="p1") -> set:
    return {o["instance_id"] for o in legal_targets(eng.state, who, effect.target_spec)}


@pytest.mark.parametrize("name", NEWLY_COVERED)
def test_real_cards_are_modeled(name):
    assert _returns(name)


def test_parse_shapes():
    (one,) = match_clause("return target knight card from your graveyard to your hand")
    assert one.params == {"target_kind": "graveyard_card", "destination": "hand", "subtype": "Knight"}
    (two,) = match_clause("return target angel or human creature card from your graveyard to the battlefield")
    assert two.params["target_kind"] == "graveyard_creature"
    assert two.params["creature_filter"] == {"subtype_any": ["Angel", "Human"]}
    (perm,) = match_clause("return target dragon permanent card from your graveyard to the battlefield")
    assert perm.params["target_kind"] == "graveyard_permanent" and perm.params["subtype"] == "Dragon"
    (steal,) = match_clause("put target creature card from a graveyard onto the battlefield tapped under your control")
    assert steal.params["tapped"] is True and steal.params["under_your_control"] is True
    # adversarial: a stray word is not a subtype, and a noncreature subtype names no creature card
    assert match_clause("return target frobnicate card from your graveyard to your hand") is None
    assert match_clause("return target equipment creature card from your graveyard to your hand") is None
    # the colour / supertype / type words keep their own slots
    (colour,) = match_clause("return target white creature card from your graveyard to the battlefield")
    assert "subtype" not in colour.params and colour.params["colors"] == ["W"]


def test_barrow_witches_offers_only_your_knight_cards():
    eng = _engine()
    witches = _put(eng, _real("Barrow Witches"), "p1")
    knight = _put(eng, _card("Knight A", "Creature — Human Knight"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Wizard", "Creature — Human Wizard"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Knight Theirs", "Creature — Human Knight"), "p2", Zone.GRAVEYARD)
    effect = build_effects(_returns("Barrow Witches"), witches)[0]
    assert effect.target_spec.subtype == "Knight"
    assert _offered(eng, effect) == {knight.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [knight])
    assert knight.zone == Zone.HAND


def test_angel_of_flight_alabaster_takes_any_spirit_card():
    eng = _engine()
    angel = _put(eng, _real("Angel of Flight Alabaster"), "p1")
    spirit = _put(eng, _card("Spirit Enchantment", "Enchantment Creature — Spirit"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Bear", "Creature — Bear"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_returns("Angel of Flight Alabaster"), angel)[0]
    assert _offered(eng, effect) == {spirit.instance_id}


def test_bladewing_returns_a_dragon_permanent_card_but_not_a_dragon_instant():
    eng = _engine()
    blade = _put(eng, _real("Bladewing the Risen"), "p1")
    dragon = _put(eng, _card("Whelp", "Creature — Dragon"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Not a Dragon", "Creature — Drake"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_returns("Bladewing the Risen"), blade)[0]
    assert _offered(eng, effect) == {dragon.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [dragon])
    eng.resolve_until_stable()
    assert dragon.zone == Zone.BATTLEFIELD


def test_bruna_takes_either_subtype():
    eng = _engine()
    bruna = _put(eng, _real("Bruna, the Fading Light"), "p1")
    angel = _put(eng, _card("Angel", "Creature — Angel"), "p1", Zone.GRAVEYARD)
    human = _put(eng, _card("Human", "Creature — Human Soldier"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Bear", "Creature — Bear"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_returns("Bruna, the Fading Light"), bruna)[0]
    assert _offered(eng, effect) == {angel.instance_id, human.instance_id}


def test_demon_of_dark_schemes_steals_a_creature_tapped():
    eng = _engine()
    demon = _put(eng, _real("Demon of Dark Schemes"), "p1")
    theirs = _put(eng, _card("Victim", "Creature — Bear"), "p2", Zone.GRAVEYARD)
    (effect,) = build_effects(_returns("Demon of Dark Schemes"), demon)
    assert _offered(eng, effect) == {theirs.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [theirs])
    eng.resolve_until_stable()
    assert theirs.zone == Zone.BATTLEFIELD and theirs.tapped and theirs.controller_id == "p1"
