"""Tests for the generalized "search your library for X" tutor/ramp/fetch
grammar (RULE 701.19, `parser/oracle/catalogue/handlers.py`'s
`_search_put_then_shuffle`/`_search_shuffle_then_put_top`).

The engine side (`game/effects.py`'s `SearchLibraryEffect`, arbitrary
criteria/destination/count) was already fully built and proven against 15
real popular tutors by `test_search_popular_tutors.py` — this file covers the
**parser recognition** side that was missing: turning real oracle text into
the `EffectSpec` that engine already knows how to run. Each axis (criteria
word, reveal clause, destination, pronoun, clause order) is tested alone and
in combination via real card text, plus the fail-closed boundaries this
grammar deliberately doesn't attempt.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _perm(name, text):
    return Card(id=name, name=name, type_line="Creature — Test", is_creature=True,
                power=2, toughness=2, oracle_text=text)


# ---------------------------------------------------------------------------
# Criteria axis
# ---------------------------------------------------------------------------


def test_bare_card_criteria():
    spec = parse_effect_body(
        "search your library for a card, put that card into your hand, then shuffle"
    )[0]
    assert spec.params == {"criteria": {}, "destination": "hand"}


def test_single_type_word_criteria():
    spec = parse_effect_body(
        "search your library for a creature card, put that card into your hand, then shuffle"
    )[0]
    assert spec.params == {"criteria": {"type": "creature"}, "destination": "hand"}


def test_named_basic_land_type_criteria():
    spec = parse_effect_body(
        "search your library for a forest card, put that card onto the battlefield, then shuffle"
    )[0]
    assert spec.params == {"criteria": {"type": "forest"}, "destination": "battlefield"}


def test_basic_land_sets_basic_flag_not_a_type():
    # "basic land" is its own alternative (Rampant Growth) — never combined
    # with a `type` key, matching the pre-existing basic-land fetch shape.
    spec = parse_effect_body(
        "search your library for a basic land card, put that card onto the "
        "battlefield tapped, then shuffle"
    )[0]
    assert spec.params == {"criteria": {"basic": True}, "destination": "battlefield_tapped"}


def test_two_word_or_list_criteria():
    spec = parse_effect_body(
        "search your library for an artifact or enchantment card, reveal it, "
        "then shuffle and put that card on top"
    )[0]
    assert spec.params == {
        "criteria": {"type": ["artifact", "enchantment"]}, "destination": "library_top",
    }


def test_oxford_comma_or_list_criteria():
    # Farseek-shaped: "a Plains, Island, Swamp, or Mountain card".
    spec = parse_effect_body(
        "search your library for a plains, island, swamp, or mountain card, "
        "put it onto the battlefield tapped, then shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"type": ["plains", "island", "swamp", "mountain"]},
        "destination": "battlefield_tapped",
    }


def test_up_to_n_with_type_and_plural_card():
    spec = parse_effect_body(
        "search your library for up to 3 creature cards, put them into your "
        "graveyard, then shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"type": "creature"}, "destination": "graveyard", "count": 3,
    }


# ---------------------------------------------------------------------------
# Reveal clause axis
# ---------------------------------------------------------------------------


def test_reveal_clause_is_consumed_without_becoming_its_own_effect():
    spec = parse_effect_body(
        "search your library for a creature card, reveal that card, put it "
        "into your hand, then shuffle"
    )[0]
    assert spec.type == "search"
    assert spec.params == {"criteria": {"type": "creature"}, "destination": "hand"}


def test_no_reveal_clause_still_works():
    spec = parse_effect_body(
        "search your library for a land card, put that card onto the "
        "battlefield, then shuffle"
    )[0]
    assert spec.params == {"criteria": {"type": "land"}, "destination": "battlefield"}


# ---------------------------------------------------------------------------
# Destination axis
# ---------------------------------------------------------------------------


def test_destination_battlefield_untapped_vs_tapped_are_distinct():
    untapped = parse_effect_body(
        "search your library for a forest card, put that card onto the "
        "battlefield, then shuffle"
    )[0]
    tapped = parse_effect_body(
        "search your library for a forest card, put that card onto the "
        "battlefield tapped, then shuffle"
    )[0]
    assert untapped.params["destination"] == "battlefield"
    assert tapped.params["destination"] == "battlefield_tapped"


def test_destination_graveyard():
    spec = parse_effect_body(
        "search your library for a card, put that card into your graveyard, then shuffle"
    )[0]
    assert spec.params["destination"] == "graveyard"


# ---------------------------------------------------------------------------
# Pronoun axis (every variant found in the real cache scan)
# ---------------------------------------------------------------------------


def test_pronoun_variants_all_recognized():
    for pronoun in ("it", "that card", "them", "those cards", "the card"):
        spec = parse_effect_body(
            f"search your library for a card, put {pronoun} into your hand, then shuffle"
        )[0]
        assert spec.params == {"criteria": {}, "destination": "hand"}, pronoun


# ---------------------------------------------------------------------------
# Reordered "shuffle and put ... on top" clause order
# ---------------------------------------------------------------------------


def test_reordered_shuffle_then_put_on_top():
    spec = parse_effect_body(
        "search your library for a card, then shuffle and put that card on top"
    )[0]
    assert spec.params == {"criteria": {}, "destination": "library_top"}


def test_reordered_on_top_of_your_library_phrasing():
    spec = parse_effect_body(
        "search your library for an instant or sorcery card, reveal it, then "
        "shuffle and put that card on top of your library"
    )[0]
    assert spec.params == {
        "criteria": {"type": ["instant", "sorcery"]}, "destination": "library_top",
    }


# ---------------------------------------------------------------------------
# Fail-closed boundaries (deliberately not attempted by this grammar)
# ---------------------------------------------------------------------------


def test_fails_closed_on_a_mana_value_qualifier():
    assert parse_effect_body(
        "search your library for a card with mana value 2 or less, put that "
        "card into your hand, then shuffle"
    ) is None


def test_fails_closed_on_library_and_graveyard_combined_search():
    # Doomsday/Finale of Devastation-shaped — request_search only reads
    # player.library, a real (documented) engine gap, not just unparsed.
    assert parse_effect_body(
        "search your library and graveyard for a card, put it into your "
        "hand, then shuffle"
    ) is None


def test_fails_closed_on_an_interposed_extra_clause():
    # Gamble-shaped: an extra "discard a card at random" clause between the
    # put-clause and "then shuffle" isn't this grammar's tail shape.
    assert parse_effect_body(
        "search your library for a card, put that card into your hand, "
        "discard a card at random, then shuffle"
    ) is None


# ---------------------------------------------------------------------------
# End-to-end: real card oracle text -> parse -> bind -> cast -> resolve
# ---------------------------------------------------------------------------


def test_real_tutor_card_parses_as_modeled():
    # Eladamri's Call: criteria + reveal + hand destination, all three axes
    # combined on one real card.
    card = Card(
        id="Eladamri's Call", name="Eladamri's Call", type_line="Instant", is_instant=True,
        oracle_text="Search your library for a creature card, reveal that "
                    "card, put it into your hand, then shuffle.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    (spec,) = [s for s in result.specs if s.ability_kind == "spell_effect"]
    assert spec.effects[0].params == {"criteria": {"type": "creature"}, "destination": "hand"}


def test_real_ramp_card_binds_and_resolves_end_to_end():
    # Nature's Lore: a real permanent-independent instant, full parse -> bind
    # -> cast -> resolve loop, proving the criteria reaches a real Forest.
    forest = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    other = Card(id="Island", name="Island", type_line="Basic Land — Island", is_land=True)
    spell_card = Card(
        id="Nature's Lore", name="Nature's Lore", type_line="Sorcery", is_sorcery=True,
        oracle_text="Search your library for a Forest card, put that card "
                    "onto the battlefield, then shuffle.",
    )

    eng = GameEngine.new_game([("p1", "Alice", [forest, other])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest_obj = next(o for o in p1.library if o.name == "Forest")

    obj = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    names = {e["name"] for e in choice["eligible"]}
    assert names == {"Forest"}  # criteria correctly excluded the Island

    eng.rules.resolve_search_choice(forest_obj.instance_id)
    assert forest_obj in eng.state.battlefield
    assert forest_obj.tapped is False  # Nature's Lore's untapped destination
    assert any(e.type == EventType.SHUFFLE for e in eng.state.event_log)
