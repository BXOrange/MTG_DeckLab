"""RULE 613.7c's "X is the number of `<noun phrase>` you control" general
count-amount resolver (MEC-12's own gap — 446 cards solo-blocked on this
single template, `parser_probe.py blocked "where x is the number of"`).

The engine-side primitives already existed for the common noun phrases
(`continuous.count_selector`'s ``creatures_you_control``/``attacking_
creatures_you_control``/``tapped_creatures_you_control``/``creatures_you_
control_of_type_<x>``/``legendary_creatures_you_control``, …) — the real
gap was purely parser-side: every amount-suffix handler that already knew
how to read "your devotion to `<colour>`" had no way to read the far more
common "the number of `<phrase>` you control" instead. Folding the new
reading into the *same* `subgrammars.DEVOTION` fragment (not a sibling
constant) means every handler that already embeds `{DEVOTION}` — the
target/group/negative pump family, damage-to-players, life-loss, the
devotion-scaled token count — picks it up for free with no per-handler
change; this batch adds one more embedding, the devotion-scaled sibling of
`_pump_self_subject`'s fixed-int "it gets +N/+N" self-buff-on-attack row
(Bag End Porter/Angelic Exaltation-adjacent), which previously had none.

Deliberately narrow, matching the fragment's own docstring: only the plain
noun phrases a `count_selector` entry already exists for. A qualified
phrase ("creatures you control with power 2 or less") or a two-word
subtype phrase stays unclaimed rather than guessed.
"""

from __future__ import annotations

import re

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import DEVOTION, devotion_selector
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def creature(name, power=2, toughness=2, oracle_text="", keywords=None):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- the shared fragment itself -----------------------------------------------


def _resolve(phrase: str):
    pat = re.compile(DEVOTION, re.IGNORECASE)
    m = pat.fullmatch(phrase)
    return devotion_selector(m) if m else None


def test_bare_creatures_you_control():
    assert _resolve("the number of creatures you control") == "creatures_you_control"


def test_attacking_creatures_you_control():
    assert _resolve("the number of attacking creatures you control") == "attacking_creatures_you_control"


def test_bare_attacking_creatures():
    assert _resolve("the number of attacking creatures") == "attacking_creatures"


def test_tapped_creatures_you_control():
    assert _resolve("the number of tapped creatures you control") == "tapped_creatures_you_control"


def test_a_single_subtype_word():
    assert _resolve("the number of zombies you control") == "creatures_you_control_of_type_zombie"


def test_legendary_creatures_compound():
    assert _resolve("the number of legendary creatures you control") == "legendary_creatures_you_control"


def test_qualified_phrase_stays_unresolved():
    assert _resolve("the number of creatures you control with power 2 or less") is None


def test_devotion_still_resolves_after_the_widening():
    assert _resolve("your devotion to blue") == "devotion_to_blue"


# -- an existing target-pump handler picks up the new reading for free -----


def test_target_pump_with_count_phrase_is_modeled():
    card = Card(
        id="Test Pump Spell", name="Test Pump Spell", type_line="Instant", is_instant=True,
        mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text="Target creature gets +X/+X until end of turn, where X "
                    "is the number of creatures you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- new self-subject devotion-scaled pump row -------------------------------


def test_self_subject_count_phrase_pump_parses():
    effects = parse_effect_body(
        "it gets +x/+x until end of turn, where x is the number of creatures you control",
        self_subject=True,
    )
    assert effects is not None
    assert len(effects) == 1
    assert effects[0].type == "pump"
    assert effects[0].params.get("amount_from_count_selector") == "creatures_you_control"


def test_bag_end_porter_is_modeled():
    card = creature(
        "Bag End Porter", power=3, toughness=3,
        oracle_text="Whenever this creature attacks, it gets +X/+X until end of turn, "
                    "where X is the number of legendary creatures you control.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_bag_end_porter_scales_with_legendary_creatures_you_control():
    eng = make_engine("p1", "p2")
    porter = put(eng.state, creature(
        "Bag End Porter", power=3, toughness=3,
        oracle_text="Whenever this creature attacks, it gets +X/+X until end of turn, "
                    "where X is the number of legendary creatures you control.",
    ))
    legend = creature("A Legend", power=1, toughness=1)
    legend.type_line = "Legendary Creature — Human"
    legend.is_legendary = True
    put(eng.state, legend)

    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.active_player, [porter])
    eng.resolve_until_stable()

    assert (porter.power, porter.toughness) == (4, 4)
