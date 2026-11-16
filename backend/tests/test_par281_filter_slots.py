"""PAR-281: the filter-slot peeler offers "with <quality>" to a library search whose row never wrote it.

Parse shape, fail-closed refusals, and execution in the real engine (the search offers exactly the cards the
carried quality admits)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.parser.oracle.catalogue.filter_slots import peel_filter_slots, quality_criteria
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, land, make_engine

_TAIL = ", reveal it, put it into your hand, then shuffle"


def _criteria(noun: str) -> dict:
    specs = match_clause(f"search your library for {noun}{_TAIL}")
    assert specs is not None and [s.type for s in specs] == ["search"], noun
    return specs[0].params["criteria"]


def test_exact_mana_value_is_both_bounds():
    assert _criteria("an artifact card with mana value 2") == {"type": "artifact", "min_mana_value": 2, "max_mana_value": 2}


def test_mana_value_alternatives_are_an_or_of_exact_values():
    crit = _criteria("an artifact card with mana value 4 or 5")
    assert crit["or"] == [{"min_mana_value": 4, "max_mana_value": 4}, {"min_mana_value": 5, "max_mana_value": 5}]


def test_keyword_and_keyword_alternatives():
    assert _criteria("a creature card with defender") == {"type": "creature", "has_keyword": "defender"}
    assert _criteria("a creature card with eternalize or embalm")["or"] == [
        {"has_keyword": "eternalize"}, {"has_keyword": "embalm"}]


def test_power_or_toughness_is_an_either_stat_bound():
    assert _criteria("a creature card with power or toughness 6 or greater")["or"] == [{"min_power": 6}, {"min_toughness": 6}]


@pytest.mark.parametrize("quality", [
    "the same name as that card",                 # dynamic: no card_query key
    "mana value equal to the number of age counters on ~",
    "a mana ability",                              # prose is not a keyword
    "flying and haste",
])
def test_unreadable_quality_is_refused_never_dropped(quality):
    assert quality_criteria(quality) is None
    assert match_clause(f"search your library for a card with {quality}{_TAIL}") is None


def test_second_qualifier_in_the_noun_phrase_is_refused():
    assert match_clause(f"search your library for a creature card with defender with power 2 or less{_TAIL}") is None


def test_quality_colliding_with_a_row_written_key_is_refused():
    shorter = lambda _s: match_clause(f"search your library for a creature card with mana value 3 or less{_TAIL}")
    assert peel_filter_slots(f"search your library for a creature card with mana value 3 or less with mana value 2{_TAIL}", shorter) is None


def test_only_a_carrier_spec_may_take_the_quality():
    # "destroy target creature with defender" is read by its own row; the peeler never rewrites a non-search spec
    assert peel_filter_slots("destroy target creature with wibble", lambda s: match_clause(s)) is None


def test_real_cards_become_modeled():
    db = CardDatabase(DB_PATH)
    for name in ("Micromancer", "Transit Mage", "Shield-Wall Sentinel", "Rootless Yew"):
        card = db.get_card(name)
        assert card is not None and parse_oracle(card).modeled, name


def test_carried_quality_filters_the_real_search():
    crit = _criteria("an artifact card with mana value 4 or 5")
    def artifact(name, cmc):
        return creature(name, cost="{%d}" % cmc, type_line="Artifact")
    pool = [artifact("Three", 3), artifact("Four", 4), artifact("Five", 5), artifact("Six", 6)]
    assert [c.name for c in pool if card_query.matches(c, crit)] == ["Four", "Five"]
    eng = make_engine(pool)
    p1 = eng.state.player_by_id("p1")
    eng.rules._request_search(p1, crit, "hand", count=1)
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    assert sorted(o["name"] for o in choice["eligible"]) == ["Five", "Four"]


# --- milestone 2: entry counters and the source filter of a targeted stack ability -------------------------------

from mtg_analyzer.game.effects.core import GameContext  # noqa: E402
from mtg_analyzer.game.targeting import legal_targets  # noqa: E402
from mtg_analyzer.models.cards.card import Card  # noqa: E402
from mtg_analyzer.models.game.game_object import Zone  # noqa: E402
from mtg_analyzer.models.game.game_state import StackItem  # noqa: E402
from tests.test_mec118_opponent_choice import _db_card, _engine, _put  # noqa: E402


def _effect(clause: str):
    specs = match_clause(clause)
    assert specs is not None and len(specs) == 1, clause
    return specs[0]


@pytest.mark.parametrize("clause, kind, count", [
    ("return target creature card from your graveyard to the battlefield with a mannequin counter on it", "mannequin", 1),
    ("return it to the battlefield under its owner's control with 4 charge counters on it", "charge", 4),
    ("return it to the battlefield tapped under its owner's control with a finality counter on it", "finality", 1),
])
def test_entry_counters_are_carried(clause, kind, count):
    assert _effect(clause).params["extra_counters"] == {"kind": kind, "count": count}


@pytest.mark.parametrize("clause", [
    # two kinds, or a non-name word: the peel never half-reads
    "return target permanent card from your graveyard to the battlefield with a hexproof counter and an indestructible counter on it",
    "return each creature card from your graveyard to the battlefield with an additional -1/-1 counter on it",
    "return target creature card from your graveyard to your hand with a mannequin counter on it",
])
def test_entry_counters_refusals(clause):
    assert match_clause(clause) is None


@pytest.mark.parametrize("clause, flt", [
    ("counter target activated ability from an artifact source", {"card_types": ["artifact"]}),
    ("counter target activated or triggered ability from an artifact or enchantment source", {"card_types": ["artifact", "enchantment"]}),
    ("copy target activated or triggered ability you control from a colorless source", {"colorless": True}),
    ("copy target activated or triggered ability you control from a creature source", {"card_types": ["creature"]}),
])
def test_ability_source_filter_is_carried(clause, flt):
    assert _effect(clause).params["source_filter"] == flt


@pytest.mark.parametrize("clause", [
    "counter target activated ability from a legendary source",
    "copy target activated or triggered ability you control from another legendary source that's not a commander",
])
def test_ability_source_filter_refusals(clause):
    assert match_clause(clause) is None


def test_real_cards_with_new_slots_become_modeled():
    for name in ("Rust", "Brown Ouphe", "Tawnos, Urza's Apprentice", "Makeshift Mannequin", "Unstoppable Slasher"):
        assert parse_oracle(_db_card(name)).modeled, name


def _activation(eng, card, controller):
    source = _put(eng, card, controller)
    eng.activate_ability(eng.state.player_by_id(controller), source)
    return source, eng.state.stack[-1]


def test_rust_counters_only_an_artifact_sourced_ability():
    eng = _engine()
    p = eng.state.players[0]
    art, art_item = _activation(eng, Card(id="Art", name="Art", type_line="Artifact", oracle_text="{T}: Draw a card."), "p2")
    cre = _put(eng, Card(id="Cre", name="Cre", type_line="Creature — Bear", is_creature=True, power=1, toughness=1,
                         oracle_text="{T}: Draw a card."), "p2")
    cre.summoning_sick = False
    eng.activate_ability(eng.state.players[1], cre)
    cre_item = eng.state.stack[-1]
    rust = _put(eng, _db_card("Rust"), "p1", Zone.HAND)
    spec = rust.spell_effects[0].target_spec
    assert spec.stack_source_filter == {"card_types": ["artifact"]}
    assert {o["stack_id"] for o in legal_targets(eng.state, p.id, spec, source=rust)} == {art_item.stack_id}
    # RULE 608.2b: even handed the wrong item directly, the effect does nothing.
    rust.spell_effects[0].apply(GameContext(eng.state, eng.rules), [cre_item])
    assert cre_item in eng.state.stack
    p.mana_pool.add_many({"G": 2, "C": 2})
    eng.cast_spell(p, rust, targets=[art_item])
    eng.rules.resolve_top_of_stack()
    assert art_item not in eng.state.stack and cre_item in eng.state.stack


def test_copy_ability_source_filter_offers_only_colorless_sources():
    eng = _engine()
    p = eng.state.players[0]
    _, colorless_item = _activation(eng, Card(id="Rock", name="Rock", type_line="Artifact", oracle_text="{T}: Draw a card."), "p1")
    green = Card(id="Elf", name="Elf", type_line="Creature — Elf", is_creature=True, power=1, toughness=1,
                 mana_cost_string="{G}", color_identity={"G"}, oracle_text="{T}: Draw a card.")
    elf = _put(eng, green, "p1")
    elf.summoning_sick = False
    eng.activate_ability(p, elf)
    green_item = eng.state.stack[-1]
    from mtg_analyzer.game.binding.core import build_effects
    effect = build_effects([_effect("copy target activated or triggered ability you control from a colorless source")], elf)[0]
    options = legal_targets(eng.state, p.id, effect.target_spec, source=elf)
    assert {o["stack_id"] for o in options} == {colorless_item.stack_id}


def test_entry_counters_land_on_the_returned_permanent():
    eng = _engine()
    p = eng.state.players[0]
    bear = _put(eng, Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
                "p1", Zone.GRAVEYARD)
    spell = _put(eng, _db_card("Makeshift Mannequin"), "p1", Zone.HAND)
    p.mana_pool.add_many({"B": 3, "C": 3})
    eng.cast_spell(p, spell, targets=[bear])
    eng.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD
    assert bear.counters.get("mannequin") == 1


# --- graveyard type words: "nonland" / "historic" / "legendary creature" -------------------------------------------


@pytest.mark.parametrize("clause, kind", [
    ("exile target nonland card from your graveyard", "graveyard_nonland_card"),
    ("exile target historic card from your graveyard", "graveyard_historic_card"),
    ("return all legendary creature cards from your graveyard to your hand", "graveyard_legendary_creature"),
])
def test_graveyard_quality_words_resolve_to_a_target_kind(clause, kind):
    assert _effect(clause).params["target_kind"] == kind


def test_historic_graveyard_target_offers_exactly_artifact_legendary_saga_cards():
    from mtg_analyzer.game.targeting import TargetSpec
    eng = _engine()
    p = eng.state.players[0]
    cards = {
        "Rock": Card(id="Rock", name="Rock", type_line="Artifact"),
        "King": Card(id="King", name="King", type_line="Legendary Creature — Human", is_creature=True, power=1, toughness=1),
        "Tale": Card(id="Tale", name="Tale", type_line="Enchantment — Saga"),
        "Bear": Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        "Plains": land("Plains", "Plains"),
    }
    for c in cards.values():
        _put(eng, c, "p1", Zone.GRAVEYARD)
    opts = legal_targets(eng.state, p.id, TargetSpec(kind=_effect("exile target historic card from your graveyard").params["target_kind"]))
    assert sorted(o["name"] for o in opts) == ["King", "Rock", "Tale"]
    opts = legal_targets(eng.state, p.id, TargetSpec(kind="graveyard_nonland_card"))
    assert sorted(o["name"] for o in opts) == ["Bear", "King", "Rock", "Tale"]
