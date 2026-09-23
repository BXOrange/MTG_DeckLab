"""PAR-20 — RULE 604.3 characteristic-defining P/T: "~'s power and toughness
are each equal to the number of <X>." gets its first oracle-text handler.

The engine layer (`continuous.recompute`'s 7a `pt_cda` pass, reading a
`count_selector` for power and toughness) has existed since the Ashaya batch
but was only ever hand-authored. This is the named follow-up (1) of PAR-20:
the two templates it called out ("cards in your hand", "lands you control")
plus the two adjacent phrases a real cache card prints in the exact same
shape and that already have a selector. Any other quantity phrase fails
closed.

PAR-120 (PARSER_VERSION 466) retired the small `_PT_CDA_SELECTORS` whitelist
in favour of the shared `count_phrase` noun-phrase grammar — `<X>` now
routes through `parse_count_phrase` first, emitting a structured
`{zone, of, filter}` selector instead of a named string, before falling
back to the one genuinely special selector the grammar can't express
(RULE 700.8's party count). This widened what parses far past the original
four-phrase whitelist (+58 cards cache-wide, 0 regressed) — several phrases
this file used to pin as "stays unclaimed" now correctly parse, since they
were never actually a different *kind* of gap, just outside the old
narrow table.

Reference: parser/oracle/catalogue/static_handlers.py (`_PT_CDA_RE`,
`_pt_cda_selector`), game/continuous.py (`count_selector`).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.support.game import land, make_engine, obj_on_battlefield


def _cda(selector):
    return [EffectSpec("pt_cda", {
        "affects": "self", "power_count": selector, "toughness_count": selector,
    })]


def test_each_whitelisted_phrase_parses():
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of cards in your hand."
    ) == _cda({"zone": "hand", "of": "you"})
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of lands you control."
    ) == _cda({"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}})
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of cards in your graveyard."
    ) == _cda({"zone": "graveyard", "of": "you"})
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of creatures you control."
    ) == _cda({"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}})


def test_more_quantity_phrases_now_parse_via_the_shared_grammar():
    # PAR-120: these used to be a different, unwired selector each; the
    # shared noun-phrase grammar reaches all of them generically now.
    for what, filter_ in (
        ("creature cards in your graveyard", {"card_type": "creature"}),
        ("Islands you control", {"subtype": "island"}),
        ("artifacts you control", {"card_type": "artifact"}),
    ):
        assert static_effect_specs(
            f"~'s power and toughness are each equal to the number of {what}."
        ) == _cda({"zone": "battlefield" if "control" in what else "graveyard",
                    "of": "you", "filter": filter_})
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of cards in all graveyards."
    ) == _cda({"zone": "graveyard", "of": "any"})


def test_unwhitelisted_quantity_phrases_stay_unclaimed():
    # A *compound* qualifier ("differently named") the shared grammar
    # doesn't express — a CDA reading an unmodeled quantity would silently
    # define the creature 0/0, so this must still fail closed.
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of "
        "differently named lands you control."
    ) is None


def test_real_card_maro_is_modeled_end_to_end():
    card = Card(
        id="M", name="M", type_line="Creature — Elemental", is_creature=True,
        power=0, toughness=0,
        oracle_text="M's power and toughness are each equal to the number of cards in your hand.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert [e.type for e in result.effect_specs[0].effects] == ["pt_cda"]


def test_count_selector_cards_in_your_hand():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.player_by_id("p1")
    assert continuous.count_selector(eng.state, "p1", "cards_in_your_hand") == 0
    for i in range(3):
        p1.hand.append(
            GameObject(Card(id=f"h{i}", name=f"h{i}", type_line="Instant", is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
        )
    assert continuous.count_selector(eng.state, "p1", "cards_in_your_hand") == 3


def test_pt_cda_hand_count_tracks_live():
    eng = make_engine([land()], hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    card = Card(
        id="Maroish", name="Maroish", type_line="Creature — Elemental",
        is_creature=True, power=0, toughness=0,
        oracle_text="Maroish's power and toughness are each equal to the number of cards in your hand.",
    )
    obj = obj_on_battlefield(state, eng, card, controller="p1")
    bind_from_catalogue(obj)

    for i in range(4):
        p1.hand.append(
            GameObject(Card(id=f"c{i}", name=f"c{i}", type_line="Instant", is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
        )
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (4, 4)

    p1.hand.pop()
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (3, 3)


def test_pt_cda_lands_you_control():
    eng = make_engine([land()], hand=0)
    state = eng.state
    for i in range(5):
        obj_on_battlefield(state, eng, land(name=f"L{i}"), controller="p1")
    card = Card(
        id="Molimoish", name="Molimoish", type_line="Creature — Elemental",
        is_creature=True, power=0, toughness=0,
        oracle_text="Molimoish's power and toughness are each equal to the number of lands you control.",
    )
    obj = obj_on_battlefield(state, eng, card, controller="p1")
    bind_from_catalogue(obj)
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (5, 5)
