"""Batch 6 (docs/implementation-state/BACKLOG.md):
"cost-keyword mechanics" — landcycling/basic landcycling, megamorph,
escape, multikicker, kicker-counter variants.

Investigation showed every one of these was already fully *behaviourally*
modeled (Escape/Kicker/Multikicker cast machinery in `game_engine.py`,
Cycling's own `discard_self` hand-zone activation) — the actual gap was two
**recognition bugs** in the front-end that made the coverage gate (and, for
one of them, the keyword-spec builder itself) fail to see it:

* `keywords._resolve` only special-cased the ``<type>walk`` family
  (Islandwalk -> Landwalk). Cycling has the exact same "one keyword name per
  type" shape (Plainscycling/Mountaincycling/Forestcycling/Swampcycling/
  Islandcycling/Wizardcycling/Slivercycling/**Basic landcycling**), but
  wasn't generalized the same way — "Basic landcycling" wasn't even in the
  hand-written `_ALIASES` map, so `parse_keywords` silently skipped it
  (fail-closed skip of an unknown keyword name), never reaching cost
  extraction at all.
* `segmenter.is_keyword_line`'s two checks compounded:
  1. It only recognised `KEYWORDS`' canonical `_TABLE` display names
     ("Kicker", "Morph", "Cycling"), never the alias spellings a real card
     prints ("Multikicker", "Megamorph", "Landcycling", "Partner with", …).
  2. It blindly `line.split(",")`, so any keyword whose own parameter
     contains a comma — Escape's "{cost}, Exile N other cards from your
     graveyard", Ward/Kicker's non-mana "Pay 2 life"/"Discard a card"
     fallback costs, Partner with's "<Name>, <Epithet>" — got its own
     continuation misread as a second, unrecognized token, failing the
     line's all-tokens-must-match check.

Neither bug touched any *behavioural* code — Escape/Kicker/Multikicker
already worked once cast; this was purely the coverage gate (and, for
landcycling's variants, `parse_keywords`) failing to see a line it should
have claimed. Fixed by generalizing `_resolve` (mirroring the existing
`walk`-suffix trick) and, in `segmenter.is_keyword_line`, only rejoining a
comma-split token onto its predecessor when that predecessor starts one of a
closed list of known compound-parameter keywords (`_COMPOUND_PARAM_START_RE`
— escape/ward/kicker/multikicker/partner with/friends forever) — narrow on
purpose, so an unrelated trailing clause on an ordinary keyword line still
fails instead of being swallowed by that keyword's own greedy match.

Separately, a real **new capability**: "if ~ was kicked, it enters with N
counters on it." (Academy Drake/Baloth Gorger/Cragplate Baloth/Grunn-shaped)
and its Multikicker-scaled sibling "~ enters with N counters on it for each
time it was kicked." (Apex Hawks-shaped) reuse the existing RULE 614.1
entry-counters machinery (`counters.py`/`RulesEngine._apply_entry_counters`),
now gated/scaled by `GameObject.kicker_count` (already stamped at cast time
for the "if this spell was kicked" additional-effect shape).

Reference: mtg_analyzer/parser/oracle/catalogue/{keywords,counters}.py,
mtg_analyzer/parser/oracle/segmenter.py, mtg_analyzer/game/rules_engine.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.effect_binder import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition
from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords
from mtg_analyzer.parser.oracle.segmenter import is_keyword_line


def _card(name, oracle_text, keywords, type_line="Creature — Beast", **kw):
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text,
        keywords=list(keywords), is_creature="Creature" in type_line, **kw,
    )


# ---------------------------------------------------------------------------
# is_keyword_line — alias spellings + the smarter comma-split
# ---------------------------------------------------------------------------


def test_two_plain_keywords_still_split_on_comma():
    assert is_keyword_line("flying, vigilance")


def test_basic_landcycling_alias_line_is_recognized():
    assert is_keyword_line("basic landcycling {2}")


def test_plainscycling_type_variant_is_recognized():
    assert is_keyword_line("plainscycling {2}")


def test_megamorph_alias_line_is_recognized():
    assert is_keyword_line("megamorph {1}{g}")


def test_multikicker_alias_line_is_recognized():
    assert is_keyword_line("multikicker {2}")


def test_escapes_own_compound_cost_is_not_split_on_its_internal_comma():
    assert is_keyword_line("escape—{3}{r}{g}, exile 3 other cards from your graveyard.")


def test_two_cycling_variants_on_one_line_still_split_correctly():
    assert is_keyword_line("swampcycling {2}, mountaincycling {2}")


def test_partner_with_a_comma_containing_name_is_not_split():
    assert is_keyword_line("partner with rocksteady, mutant marauder")


def test_a_keywords_own_continuation_that_looks_like_prose_is_still_rejected():
    # Fail-closed guard: the smarter comma-split must not become so permissive
    # that a genuine non-keyword continuation gets swallowed.
    assert not is_keyword_line("flying, then draw a card")


# ---------------------------------------------------------------------------
# keywords._resolve — the <type>cycling suffix generalization
# ---------------------------------------------------------------------------


def test_basic_landcycling_keyword_is_resolved_with_its_cost():
    card = _card(
        "A.I.M. Scientists",
        "Basic landcycling {2} ({2}, Discard this card: Search your library "
        "for a basic land card, reveal it, put it into your hand, then "
        "shuffle.)",
        ["Basic landcycling"],
    )
    (spec,) = parse_keywords(card)
    assert spec.keyword == {"name": "cycling", "cost": "{2}"}


def test_islandcycling_keyword_is_resolved_with_its_cost():
    card = _card(
        "Sandsteppe Outcast",
        "Islandcycling {2} ({2}, Discard this card: Search your library for "
        "an Island card, reveal it, put it into your hand, then shuffle.)",
        ["Islandcycling"],
    )
    (spec,) = parse_keywords(card)
    assert spec.keyword == {"name": "cycling", "cost": "{2}"}


def test_megamorph_still_resolves_onto_morph():
    card = _card(
        "Ainok Survivalist",
        "Megamorph {1}{G} (You may cast this card face down as a 2/2 "
        "creature for {3}. Turn it face up any time for its megamorph cost "
        "and put a +1/+1 counter on it.)",
        ["Megamorph"],
    )
    (spec,) = parse_keywords(card)
    assert spec.keyword == {"name": "morph", "cost": "{1}{G}"}


# ---------------------------------------------------------------------------
# End-to-end card coverage
# ---------------------------------------------------------------------------


def test_basic_landcycling_only_card_is_modeled():
    card = _card(
        "Ash Barrens",
        '{T}: Add {C}.\nBasic landcycling {1} ({1}, Discard this card: '
        "Search your library for a basic land card, reveal it, put it into "
        "your hand, then shuffle.)",
        ["Basic landcycling"],
        type_line="Land",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED


def test_escape_only_card_is_modeled():
    card = _card(
        "Bloodbraid Challenger",
        "Cascade\nHaste\nEscape—{3}{R}{G}, Exile three other cards from your "
        "graveyard. (You may cast this card from your graveyard for its "
        "escape cost.)",
        ["Cascade", "Haste", "Escape"],
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED


def test_multikicker_only_card_is_modeled():
    card = _card(
        "Comet Storm",
        "Multikicker {1} (This spell may be kicked any number of times, "
        "each time paying {1}.)\n"
        "Comet Storm deals X damage divided as you choose among any number "
        "of target creatures and/or players, where X is 2 plus the amount "
        "of times this spell was kicked.",
        ["Multikicker"],
        type_line="Sorcery", is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED  # the X/divided-damage clause itself is a real, separate gap
    assert result.unclaimed == [
        "~ deals x damage divided as you choose among any number of "
        "target creatures and/or players, where x is 2 plus the amount of "
        "times this spell was kicked."
    ]


# ---------------------------------------------------------------------------
# counters.py — kicked-gated / kicked-scaled entry counters
# ---------------------------------------------------------------------------


def test_kicked_gated_fixed_amount_condition():
    line = "if ~ was kicked, it enters with 2 +1/+1 counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False, "count": 2, "counter_type": "+1/+1", "kicked_gate": True,
    }


def test_kicked_scaled_condition():
    line = "~ enters with a +1/+1 counter on it for each time it was kicked."
    assert entry_counters_condition(line) == {
        "is_x": False, "count": 1, "counter_type": "+1/+1", "kicked_scale": True,
    }


def test_kicked_gated_x_amount_is_recognized():
    # PAR-7: Kicker {X}'s own paid X (Emblazoned Golem) is a different value
    # than a plain cast-for-X's x_paid the unconditional shape resolves
    # against — kept distinct via its own `kicked_x_scale` flag rather than
    # conflated with either, and resolved against `GameObject.kicker_x_paid`
    # (see test_par7_kicker_x.py).
    line = "if ~ was kicked, it enters with x +1/+1 counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False, "counter_type": "+1/+1", "kicked_gate": True, "kicked_x_scale": True,
    }


def test_kicked_gated_compound_and_with_keyword_is_recognized():
    line = "if ~ was kicked, it enters with 2 +1/+1 counters on it and with flying."
    assert entry_counters_condition(line) == {
        "is_x": False, "count": 2, "counter_type": "+1/+1", "kicked_gate": True,
        "grant_keyword": "flying",
    }


def test_kicked_scaled_compound_and_with_keyword_is_recognized():
    line = "~ enters with a +1/+1 counter on it for each time it was kicked and with vigilance."
    assert entry_counters_condition(line) == {
        "is_x": False, "count": 1, "counter_type": "+1/+1", "kicked_scale": True,
        "grant_keyword": "vigilance",
    }


def test_unrecognized_keyword_in_compound_clause_stays_unclaimed():
    # Fail-closed: not in the closed keyword vocabulary.
    line = "if ~ was kicked, it enters with 2 +1/+1 counters on it and with banding."
    assert entry_counters_condition(line) is None


# ---------------------------------------------------------------------------
# Engine end-to-end: kicked_gate / kicked_scale actually drive the counters
# ---------------------------------------------------------------------------


def _kicker_creature(name, kicker_cost, oracle_text, multi=False, power=2, toughness=2):
    keyword_line = ("Multikicker" if multi else "Kicker") + f" {kicker_cost}"
    text = f"{keyword_line}\n{oracle_text}"
    card = Card(
        id=name, name=name, type_line="Creature — Beast",
        mana_cost_string="{1}{G}",
        converted_mana_cost=ManaCost.parse("{1}{G}").converted_mana_cost,
        is_creature=True, power=power, toughness=toughness, oracle_text=text,
    )
    card.keywords = ["Multikicker" if multi else "Kicker"]
    return card


def _make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _cast(card, kicked):
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 10, "U": 10, "G": 10, "C": 10})
    result = parse_oracle(card)
    assert result.modeled
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    eng.cast_spell(p1, obj, kicked=kicked)
    eng.resolve_until_stable()
    return next(o for o in eng.state.battlefield if o.name == card.name)


def test_unkicked_cast_skips_the_kicked_gated_counters():
    card = _kicker_creature(
        "Academy Drake", "{1}{U}", "If ~ was kicked, it enters with 2 +1/+1 counters on it.",
    )
    bf = _cast(card, kicked=0)
    assert bf.counters.get("+1/+1", 0) == 0
    assert bf.power == 2  # printed only


def test_kicked_cast_adds_the_kicked_gated_counters():
    card = _kicker_creature(
        "Academy Drake", "{1}{U}", "If ~ was kicked, it enters with 2 +1/+1 counters on it.",
    )
    bf = _cast(card, kicked=1)
    assert bf.counters.get("+1/+1", 0) == 2
    assert bf.power == 4  # 2 printed + 2 from counters


def test_multikicker_scaled_counters_multiply_by_times_kicked():
    card = _kicker_creature(
        "Apex Hawks", "{1}{W}",
        "~ enters with a +1/+1 counter on it for each time it was kicked.",
        multi=True,
    )
    bf = _cast(card, kicked=3)
    assert bf.counters.get("+1/+1", 0) == 3


def test_multikicker_scaled_counters_zero_when_never_kicked():
    card = _kicker_creature(
        "Apex Hawks", "{1}{W}",
        "~ enters with a +1/+1 counter on it for each time it was kicked.",
        multi=True,
    )
    bf = _cast(card, kicked=0)
    assert bf.counters.get("+1/+1", 0) == 0


def test_kicked_compound_clause_grants_both_counters_and_the_keyword():
    card = _kicker_creature(
        "Academy Drake", "{1}{U}",
        "If ~ was kicked, it enters with 2 +1/+1 counters on it and with vigilance.",
    )
    bf = _cast(card, kicked=1)
    assert bf.counters.get("+1/+1", 0) == 2
    assert combat.has(bf, "vigilance") is True


def test_unkicked_compound_clause_grants_neither_counters_nor_the_keyword():
    card = _kicker_creature(
        "Academy Drake", "{1}{U}",
        "If ~ was kicked, it enters with 2 +1/+1 counters on it and with vigilance.",
    )
    bf = _cast(card, kicked=0)
    assert bf.counters.get("+1/+1", 0) == 0
    assert combat.has(bf, "vigilance") is False
