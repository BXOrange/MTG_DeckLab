"""PAR-285 (v979): graveyard "creature or land card" union and the counter-spell colour union / negation slots.

"return target creature or land card from your graveyard to your hand" (RULE 205.2a), "counter target red or green spell"
(RULE 105.2), "counter target nonblue / nonartifact / non-Faerie spell" and "counter target creature or Aura spell"
(RULE 303.4). Tests run parser -> binder -> `legal_targets` on the real cards' text, offering matching AND
non-matching candidates."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_spell_filter
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_counter_family import push_spell
from tests.test_mec118_opponent_choice import _engine, _put

GRAVEYARD_CARDS = ["Pulse of Murasa", "Awaken the Honored Dead", "The Binding of the Titans"]
COUNTER_CARDS = ["Frazzle", "Flashfreeze", "Nullify", "Faerie Trickery", "Revolutionary Rebuff", "Precise Redaction"]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _effects(name: str, kind: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    found = []
    for ability in result.specs:
        for effect in ability.effects or []:
            if effect.type == kind:
                found.append(effect)
            for nested in effect.params.get("then_trigger") or []:  # a reflexive "when you do, ..." body
                if nested["type"] == kind:
                    found.append(EffectSpec(nested["type"], nested["params"]))
    return found


def _card(name: str, type_line: str, colors=(), **kw) -> Card:
    """A printed card; its colours are those of its mana cost (RULE 202.2), one pip per colour."""
    cost = "".join(f"{{{c}}}" for c in colors)
    is_creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, is_creature=is_creature, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=2 if is_creature else None, toughness=2 if is_creature else None,
                mana_cost_string=cost, converted_mana_cost=len(colors), **kw)


def _offered(eng, effect, who="p1") -> set:
    return {o["instance_id"] for o in legal_targets(eng.state, who, effect.target_spec)}


@pytest.mark.parametrize("name", GRAVEYARD_CARDS)
def test_graveyard_cards_are_modeled(name):
    assert _effects(name, "return_from_graveyard")


@pytest.mark.parametrize("name", COUNTER_CARDS)
def test_counter_cards_are_modeled(name):
    assert _effects(name, "counter")


def test_parse_shapes():
    (g,) = match_clause("return target creature or land card from your graveyard to your hand")
    assert g.params["target_kind"] == "graveyard_creature_or_land"
    assert resolve_spell_filter("target red or green spell") == {"color_any": ["R", "G"]}
    assert resolve_spell_filter("target nonblue spell") == {"non_color": "U"}
    assert resolve_spell_filter("target nonartifact spell") == {"without_card_types": ["artifact"]}
    assert resolve_spell_filter("target non-faerie spell") == {"without_subtype": "Faerie"}
    assert resolve_spell_filter("target creature or aura spell") == {"card_types": ["creature", "aura"]}
    # adversarial: a stray negated word, a legendary adjective, a three-colour "or" stay unclaimed
    assert resolve_spell_filter("target nonfrobnicate spell") is None
    assert resolve_spell_filter("target legendary spell") is None
    assert match_clause("return target creature or planeswalker card from your graveyard to your hand") is not None


def test_pulse_of_murasa_offers_creature_and_land_cards_from_any_graveyard():
    eng = _engine()
    pulse = _put(eng, _real("Pulse of Murasa"), "p1")
    bear = _put(eng, _card("Bear", "Creature — Bear"), "p1", Zone.GRAVEYARD)
    land = _put(eng, _card("Forest", "Basic Land — Forest"), "p2", Zone.GRAVEYARD)
    _put(eng, _card("Ring", "Artifact"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Bolt", "Instant"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_effects("Pulse of Murasa", "return_from_graveyard"), pulse)[0]
    assert _offered(eng, effect) == {bear.instance_id, land.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [land])
    assert land.zone == Zone.HAND and land.owner_id == "p2"


def test_binding_of_the_titans_is_limited_to_your_graveyard():
    eng = _engine()
    src = _put(eng, _real("The Binding of the Titans"), "p1")
    mine = _put(eng, _card("Mine", "Creature — Bear"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Theirs", "Creature — Bear"), "p2", Zone.GRAVEYARD)
    effect = build_effects(_effects("The Binding of the Titans", "return_from_graveyard"), src)[0]
    assert _offered(eng, effect) == {mine.instance_id}


def _counter_offer(eng, name, spells):
    """Cast ``name`` as p2 would face ``spells`` (cards pushed by p1): the stack objects the counterspell may target."""
    source = _put(eng, _real(name), "p2")
    effect = build_effects(_effects(name, "counter"), source)[0]
    pushed = {label: push_spell(eng, eng.state.player_by_id("p1"), card).instance_id for label, card in spells.items()}
    offered = _offered(eng, effect, "p2")
    return {label for label, iid in pushed.items() if iid in offered}


_COLOUR_SPELLS = {
    "red": ("Instant", ["R"]), "green": ("Creature — Elf", ["G"]), "blue": ("Instant", ["U"]),
    "white": ("Instant", ["W"]), "black": ("Instant", ["B"]), "colorless": ("Artifact", []),
    "red-blue": ("Instant", ["R", "U"]),
}


@pytest.mark.parametrize("name, expected", [
    ("Frazzle", {"red", "green", "white", "black", "colorless"}),  # nonblue: no blue at all (red-blue is blue)
    ("Flashfreeze", {"red", "green", "red-blue"}),  # either colour, a multicolour spell counts
    ("Precise Redaction", {"white", "black"}),
])
def test_colour_slots_offer_exactly_the_right_spells(name, expected):
    eng = _engine()
    spells = {label: _card(label, tl, colors) for label, (tl, colors) in _COLOUR_SPELLS.items()}
    assert _counter_offer(eng, name, spells) == expected


def test_revolutionary_rebuff_skips_artifact_spells():
    eng = _engine()
    got = _counter_offer(eng, "Revolutionary Rebuff", {
        "sorcery": _card("S", "Sorcery", ["R"]), "artifact": _card("A", "Artifact"),
        "artifact creature": _card("AC", "Artifact Creature — Golem"),
    })
    assert got == {"sorcery"}


def test_faerie_trickery_skips_faerie_spells():
    eng = _engine()
    got = _counter_offer(eng, "Faerie Trickery", {
        "faerie": _card("F", "Creature — Faerie Rogue", ["U"]), "bear": _card("B", "Creature — Bear", ["G"]),
        "drake": _card("D", "Creature — Drake", ["U"]),
    })
    assert got == {"bear", "drake"}


def test_nullify_takes_creature_and_aura_spells_only():
    eng = _engine()
    got = _counter_offer(eng, "Nullify", {
        "creature": _card("C", "Creature — Bear", ["G"]), "aura": _card("Au", "Enchantment — Aura", ["W"]),
        "enchantment": _card("E", "Enchantment", ["W"]), "instant": _card("I", "Instant", ["U"]),
    })
    assert got == {"creature", "aura"}


def test_awaken_the_honored_dead_reflexive_return_offers_creature_or_land():
    eng = _engine()
    saga = _put(eng, _real("Awaken the Honored Dead"), "p1")
    bear = _put(eng, _card("Bear", "Creature — Bear"), "p1", Zone.GRAVEYARD)
    land = _put(eng, _card("Forest", "Basic Land — Forest"), "p1", Zone.GRAVEYARD)
    _put(eng, _card("Ring", "Artifact"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_effects("Awaken the Honored Dead", "return_from_graveyard"), saga)[0]
    assert _offered(eng, effect) == {bear.instance_id, land.instance_id}


def test_frazzle_counters_the_chosen_offered_spell_when_it_resolves():
    eng = _engine()
    source = _put(eng, _real("Frazzle"), "p2")
    effect = build_effects(_effects("Frazzle", "counter"), source)[0]
    red = push_spell(eng, eng.state.player_by_id("p1"), _card("Burn", "Instant", ["R"]))
    blue = push_spell(eng, eng.state.player_by_id("p1"), _card("Counter", "Instant", ["U"]))
    assert _offered(eng, effect, "p2") == {red.instance_id}
    effect.apply(GameContext(eng.state, eng.rules), [red])
    assert red.zone == Zone.GRAVEYARD and blue.zone == Zone.STACK


def test_faerie_trickery_exiles_the_countered_spell():
    eng = _engine()
    source = _put(eng, _real("Faerie Trickery"), "p2")
    effects = build_effects(_effects("Faerie Trickery", "counter"), source)
    bear = push_spell(eng, eng.state.player_by_id("p1"), _card("Bear", "Creature — Bear", ["G"]))
    assert _offered(eng, effects[0], "p2") == {bear.instance_id}
    effects[0].apply(GameContext(eng.state, eng.rules), [bear])
    assert bear.zone == Zone.EXILE
