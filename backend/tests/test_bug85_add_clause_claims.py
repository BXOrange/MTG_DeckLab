"""BUG-85 (RULE 605.1a): the segmenter claims an ``Add`` clause only when `game/mana_abilities` builds a working ability.

Before, every ``<cost>: Add ...`` line was claimed as a mana ability without a spec, so a clause the builder could not
read ("Add {T}{T}", "two mana of different colors", an X sized by removing counters, "any type that a land ... could
produce") left a MODELED card with no -- or a wrong -- mana ability. The unreadable shapes now leave the card UNMODELED,
the "any type" family and the basic-type short-circuit are read, and the full-cache parity test fails whenever a claimed
mana line yields no `ManaAbility`.
"""
import re

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import mana_abilities as M
from mtg_analyzer.parser.oracle import MODELED, PARSER_VERSION, parse_oracle
from mtg_analyzer.parser.oracle.mana_riders import add_clause_readable
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, game

_PROVENANCE = ParserProvenance(version=PARSER_VERSION, source="test")


def _claimed(line):
    return segment_line(line, allow_spell_effect=True, provenance=_PROVENANCE).claimed


def _real(name):
    return CardDatabase(DB_PATH).get_card(name)


# --- the unreadable clauses are not claimed --------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "{t}: add {t}{t}. activate only once each turn.",                           # Sole Performer
    "{t}: add {∞}.",                                                            # Mox Lotus
    "sacrifice a creature or land: add {hr}.",                                  # Mons's Goblin Waiters
    "{1}, {t}: add 2 mana of different colors. spend this mana only to cast planeswalker spells.",   # Interplanar Beacon
    "{t}: add 2 mana of different colors.",                                     # Firemind Vessel
    "{t}, remove x storage counters from ~: add x mana in any combination of colors.",   # Crucible
    "{1}, remove x storage counters from ~: add x mana in any combination of {w} and/or {u}.",   # Calciform Pools
    "{t}: add x mana in any combination of colors, where x is the number of creatures you control with defender.",
    "sacrifice a land: add one mana of any type the sacrificed land could produce.",   # Squandered Resources
])
def test_an_add_clause_the_builder_cannot_read_is_not_claimed(line):
    cost, _, effect = line.partition(":")
    assert not add_clause_readable(cost, effect.strip())
    assert not _claimed(line)


@pytest.mark.parametrize("line", [
    "{t}: add {g}.",
    "{t}: add {w} or {b}. ~ deals 1 damage to you.",
    "{t}: add 1 mana of any type that a land you control could produce.",
    "{t}: add 1 mana of any type that a gate you control could produce.",
    "{t}: add x mana in any combination of colors, where x is the greatest power among creatures you control.",
    "{t}: add x mana in any combination of colors, where x is the number of elves you control.",
    "{t}, sacrifice x goats: add x mana of any one color. you gain x life.",
])
def test_a_readable_add_clause_stays_claimed(line):
    cost, _, effect = line.partition(":")
    assert add_clause_readable(cost, effect.strip())
    assert _claimed(line)


@pytest.mark.parametrize("name", [
    "Sole Performer", "Crucible of the Spirit Dragon", "Interplanar Beacon", "Firemind Vessel", "Guild Globe",
    "Component Pouch", "Calciform Pools", "Dreadship Reef", "Fungal Reaches", "Molten Slagheap", "Saltcrusted Steppe",
    "Axebane Guardian", "Mox Lotus", "Mons's Goblin Waiters", "Squandered Resources",
])
def test_cards_with_an_unreadable_add_clause_are_unmodeled(name):
    printed = _real(name)
    if printed is None:
        pytest.skip(f"{name} is not in this cache")
    assert parse_oracle(printed).coverage != MODELED


@pytest.mark.parametrize("name", ["Reflecting Pool", "Naga Vitalist", "Plaza of Harmony", "Murmuring Bosk", "Artist Alley"])
def test_cards_whose_add_clause_is_now_read_stay_modeled(name):
    printed = _real(name)
    if printed is None:
        pytest.skip(f"{name} is not in this cache")
    assert parse_oracle(printed).coverage == MODELED


# --- the shapes the builder learned, tapped through the engine --------------------------------------------------------


def _tap(eng, land, **kw):
    return eng.tap_for_mana(eng.state.player_by_id("p1"), land, **kw)


def test_a_basic_typed_land_keeps_its_own_mana_line_next_to_the_type_ability():
    # RULE 305.6 + 605.1a: Murmuring Bosk is a Forest ({G}) that also prints "{T}: Add {W} or {B}. ... 1 damage to you."
    abilities = M.parse_mana_abilities(_real("Murmuring Bosk"))
    assert [a.options for a in abilities] == [[{"G": 1}], [{"W": 1}, {"B": 1}]]
    assert abilities[1].self_damage == 1
    eng = game()
    bosk = card(eng, "Murmuring Bosk")
    assert _tap(eng, bosk, ability_index=1, option_index=1) == {"B": 1}
    assert eng.state.player_by_id("p1").life == 19
    eng = game()
    assert _tap(eng, card(eng, "Murmuring Bosk"), ability_index=0) == {"G": 1}
    assert eng.state.player_by_id("p1").life == 20


def test_plain_basics_and_typed_duals_gain_no_extra_ability():
    for name in ("Forest", "Taiga", "Watery Grave"):
        assert len(M.parse_mana_abilities(_real(name))) == 1


def test_a_clause_without_its_closing_period_is_read():
    # Artist Alley prints "{T}: Add {C}" with no period before its next line.
    abilities = M.parse_mana_abilities(_real("Artist Alley"))
    assert [a.options for a in abilities][0] == [{"C": 1}]
    assert len(abilities) == 2


def test_reflecting_pool_makes_any_type_a_land_you_control_could_produce():
    # RULE 106.7: colourless counts as a type; the Pool alone could produce nothing (it reflects only other lands).
    eng = game()
    pool = card(eng, "Reflecting Pool")
    assert M.mana_abilities_for(pool, eng.state)[0].options == []
    card(eng, "Wastes")
    assert M.mana_abilities_for(pool, eng.state)[0].options == [{"C": 1}]
    card(eng, "Forest")
    assert M.mana_abilities_for(pool, eng.state)[0].options == [{"C": 1}, {"G": 1}]
    assert _tap(eng, pool, option_index=1) == {"G": 1}


def test_two_reflecting_pools_do_not_loop_and_ignore_opposing_lands():
    eng = game()
    a, b = card(eng, "Reflecting Pool"), card(eng, "Reflecting Pool")
    card(eng, "Island", player="p2")
    assert M.mana_abilities_for(a, eng.state)[0].options == []
    card(eng, "Swamp")
    assert M.mana_abilities_for(a, eng.state)[0].options == [{"B": 1}]
    assert M.mana_abilities_for(b, eng.state)[0].options == [{"B": 1}]


def test_plaza_of_harmony_reflects_only_gates():
    eng = game()
    plaza = card(eng, "Plaza of Harmony")
    card(eng, "Forest")
    options = lambda: [a.options for a in M.mana_abilities_for(plaza, eng.state)]  # noqa: E731
    assert options()[1] == []
    card(eng, "Boros Guildgate")
    assert options()[1] == [{"R": 1}, {"W": 1}]
    assert options()[0] == [{"C": 1}]


# --- parity: every claimed mana line yields a ManaAbility the builder built (full cache) ------------------------------


@pytest.mark.full_cache
def test_every_claimed_mana_line_yields_a_mana_ability(full_cache_parse):
    from mtg_analyzer.game.card_registry import is_registered
    from mtg_analyzer.parser.oracle.segmenter.activation_clauses import LOYALTY_LINE_RE
    from mtg_analyzer.parser.oracle.normalize import strip_reminder_text

    add_line = re.compile(r"^[^:]+:\s*add\b", re.IGNORECASE)
    missing = []
    for printed in full_cache_parse.cards:
        if is_registered(printed.name) or parse_oracle(printed).coverage != MODELED:
            continue
        for line in strip_reminder_text(printed.oracle_text or "").split("\n"):
            line = line.strip()
            if '"' in line or not add_line.match(line) or LOYALTY_LINE_RE.match(line.lower()):
                continue
            if "target" in line.lower():
                continue  # RULE 605.1a: a targeting line is never a mana ability
            built = M._parse_mana_ability_lines(line, printed.name) or M._parse_mana_ability_lines(line, printed.name, True)
            if not built:
                missing.append((printed.name, line))
    assert not missing, missing[:40]
