"""BUG-75 (RULE 702): a keyword line is claimed only when the engine does something with the keyword.

The RULE 702 catalogue is recognition only: `parse_keywords` attaches a flag or parameter for every keyword it knows, and a
keyword line used to be claimed whole, so a card whose only unusual text was ``Extort`` or ``Echo {1}{R}`` was MODELED while
the keyword did nothing. `KEYWORDS_WITHOUT_BEHAVIOUR` lists the keywords with no consumer anywhere in the engine; this file
keeps that list honest in both directions.
"""
import re
from pathlib import Path

import pytest

import mtg_analyzer
from mtg_analyzer.game.binding.core import _KEYWORD_TRIGGERED_BUILDERS
from mtg_analyzer.game.continuous import GRANTED_TRIGGERED_FLAG_KEYWORDS
from mtg_analyzer.models import Card
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_primitives import GRANTABLE_PARAMETRIC_KEYWORDS, grantable_flag_slug
from mtg_analyzer.parser.oracle.catalogue.keywords import (
    KEYWORDS, KEYWORDS_WITHOUT_BEHAVIOUR, UNGRANTABLE_FLAG_KEYWORDS, KeywordShape,
)
from mtg_analyzer.parser.oracle.segmenter import is_keyword_line

#: A printed line per shape, so each refused keyword is tried the way a real card prints it.
_SAMPLE_PARAMETER = {
    KeywordShape.FLAG: "",
    KeywordShape.NUMBER: " 2",
    KeywordShape.COST: " {1}{r}",
    KeywordShape.NUMBER_COST: " 2—{1}{r}",
    KeywordShape.QUALITY: " creature",
}


def _line(slug: str) -> str:
    kdef = KEYWORDS[slug]
    if slug == "offering":
        return "fox offering"
    return kdef.display.lower() + _SAMPLE_PARAMETER[kdef.shape]


def _creature(text: str, keyword: str) -> Card:
    return Card(id="K", name="Kw Bench", type_line="Creature — Human", is_creature=True, power=1, toughness=1,
                oracle_text=text, keywords=[keyword])


# --- the refused keywords ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", sorted(KEYWORDS_WITHOUT_BEHAVIOUR))
def test_a_keyword_without_behaviour_is_not_a_keyword_line(slug):
    assert slug in KEYWORDS
    assert not is_keyword_line(_line(slug))
    # ... also inside a list of keywords that are fine on their own.
    assert not is_keyword_line("flying, " + _line(slug))


@pytest.mark.parametrize("slug", sorted(KEYWORDS_WITHOUT_BEHAVIOUR))
def test_a_card_whose_text_is_such_a_keyword_is_unmodeled(slug):
    line = _line(slug).capitalize()
    result = parse_oracle(_creature(line, KEYWORDS[slug].display))
    assert result.coverage == UNMODELED, line


def test_the_keyword_flag_is_still_attached_to_the_object():
    # Refusing the claim does not drop the recognised keyword: the object keeps it (RULE 702 recognition) and the card is UNMODELED.
    result = parse_oracle(_creature("Extort", "Extort"))
    assert result.coverage == UNMODELED
    assert [s.keyword["name"] for s in result.specs if s.ability_kind == "keyword"] == ["extort"]


def test_a_refused_keyword_beside_a_working_one_leaves_the_card_unmodeled():
    card = Card(id="K", name="Kw Bench", type_line="Creature — Human", is_creature=True, power=1, toughness=1,
                oracle_text="Flying\nExtort", keywords=["Flying", "Extort"])
    assert parse_oracle(card).coverage == UNMODELED


@pytest.mark.parametrize("slug", sorted(s for s in KEYWORDS_WITHOUT_BEHAVIOUR if KEYWORDS[s].shape is KeywordShape.FLAG))
def test_a_flag_keyword_without_behaviour_cannot_be_granted(slug):
    assert slug in UNGRANTABLE_FLAG_KEYWORDS
    assert grantable_flag_slug(KEYWORDS[slug].display.lower()) is None


@pytest.mark.parametrize("line", [
    "recover\u2014pay half your life, rounded up.", "squad\u2014{1}, discard a card.", "casualty 2", "craft with artifact {2}{r}",
    "companion \u2014 your starting deck contains no cards with a silver, gold, orange, or purple expansion symbol.",
    "artifact offering",
])
def test_compound_and_labelled_shapes_of_a_refused_keyword_are_refused_too(line):
    assert not is_keyword_line(line)


def test_a_comma_inside_the_parameter_of_partner_with_does_not_start_a_second_keyword():
    # "Champion" opens a refused keyword, but here it is the epithet of the partner's name (Silvar, Devourer of the Free).
    assert is_keyword_line("partner with trynn, champion of freedom")


# --- the keywords that keep their claim -------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "flying", "first strike", "deathtouch", "trample", "haste", "vigilance", "menace", "defender", "lifelink", "reach",
    "kicker {2}{r}", "flashback {3}{u}", "cycling {2}", "storm", "cascade", "convoke", "delve", "persist", "undying",
    "exalted", "prowess", "annihilator 2", "ward {2}", "equip {3}", "crew 2", "suspend 4—{1}{u}", "madness {1}{b}",
    "evoke {2}{u}", "buyback {3}", "morph {3}{u}", "ninjutsu {1}{u}", "dredge 3", "partner", "choose a background",
    "outlast {w}", "modular 2", "fabricate 2", "afterlife 2", "frenzy 1", "poisonous 1", "scavenge {2}{g}", "encore {5}{b}",
])
def test_verified_keywords_stay_keyword_lines(line):
    assert is_keyword_line(line)


@pytest.mark.parametrize("keyword,text", [("Flying", "Flying"), ("Prowess", "Prowess"), ("Kicker", "Kicker {1}{r}")])
def test_a_card_of_verified_keywords_stays_modeled(keyword, text):
    assert parse_oracle(_creature(text, keyword)).coverage == MODELED


# --- the set cannot go stale ------------------------------------------------------------------------------------

_ENGINE_ROOTS = ("game", "services", "models")
#: The only quoted mentions of a refused slug in engine code, none of which gives the keyword behaviour: Disturb is a "creatures
#: with <keyword>" filter vocabulary entry (`combat._PRINTED_ONLY_KEYWORDS`), and the sunburst *rider* grants a spell Sunburst
#: through the separate "gains sunburst" path, not the printed keyword.
_NOT_A_CONSUMER = {("disturb", "game/combat.py"), ("sunburst", "game/mana_spend_riders.py")}


def _engine_sources() -> dict[str, list[str]]:
    base = Path(mtg_analyzer.__file__).parent
    sources = {}
    for root in _ENGINE_ROOTS:
        for path in (base / root).rglob("*.py"):
            rel = path.relative_to(base)
            if "card_catalogue" in rel.parts:
                continue
            sources[str(rel)] = [ln for ln in path.read_text(errors="ignore").splitlines() if not ln.lstrip().startswith("#")]
    return sources


def test_no_refused_keyword_has_a_consumer_in_the_engine():
    """Wire a keyword (a binder builder, a casting / combat read, a grant) and this fails until its slug leaves the set."""
    sources = _engine_sources()
    consumers = []
    for slug in sorted(KEYWORDS_WITHOUT_BEHAVIOUR):
        quoted = re.compile(r"""["']""" + re.escape(slug) + r"""["']""")
        for rel, lines in sources.items():
            if (slug, rel) not in _NOT_A_CONSUMER and any(quoted.search(ln) for ln in lines):
                consumers.append((slug, rel))
    assert not consumers, f"keywords in KEYWORDS_WITHOUT_BEHAVIOUR that the engine reads: {consumers}"


def test_no_refused_keyword_has_a_binder_or_grant_builder():
    refused = set(KEYWORDS_WITHOUT_BEHAVIOUR)
    assert not refused & set(_KEYWORD_TRIGGERED_BUILDERS)
    assert not refused & set(GRANTED_TRIGGERED_FLAG_KEYWORDS)
    assert not refused & set(GRANTABLE_PARAMETRIC_KEYWORDS)
    assert not refused & {"fabricate", "afterlife", "modular", "frenzy", "poisonous", "outlast", "cycling", "transmute", "crew",
                          "saddle", "station", "unearth", "embalm", "eternalize", "encore", "scavenge", "equip", "fortify",
                          "reconfigure", "tribute", "ninjutsu", "miracle", "madness", "dash", "absorb"}


def test_the_refused_set_does_not_overlap_the_permanent_non_goals_or_the_deckbuilding_keywords():
    # Partner / Choose a Background / Doctor's companion are read by services/commander_legality.py, and Hidden / Double
    # agenda cards are already Unsupported (`support_policy`, draft_matters), so neither belongs in this set.
    assert not KEYWORDS_WITHOUT_BEHAVIOUR & {"partner", "choose_a_background", "doctor_s_companion", "hidden_agenda", "visit"}
