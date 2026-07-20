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


def test_fails_closed_on_a_bare_and_combined_search():
    # Only the "and/or" phrasing the real ~50-card family actually uses
    # (`_SEARCH_ZONE_PUT_RE`) is recognized; a bare "library and graveyard"
    # combined search with the ordinary put-then-shuffle tail is a
    # different, unattempted shape.
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
# Zone axis: "library and/or graveyard" combined search (`_search_zone_put`)
# ---------------------------------------------------------------------------


def test_zone_search_named_criteria_to_hand():
    # Tower Winder/Elspeth's Devotee-shaped: "a card named <Name>" reveal +
    # hand destination.
    spec = parse_effect_body(
        "search your library and/or graveyard for a card named command "
        "tower, reveal it, and put it into your hand. if you search your "
        "library this way, shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"name": "command tower"},
        "destination": "hand",
        "zones": ["library", "graveyard"],
    }


def test_zone_search_named_criteria_no_reveal_to_battlefield():
    # Elspeth, Undaunted Hero-shaped: no reveal clause, straight to the
    # battlefield.
    spec = parse_effect_body(
        "search your library and/or graveyard for a card named sunlit "
        "hoplite and put it onto the battlefield. if you search your "
        "library this way, shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"name": "sunlit hoplite"},
        "destination": "battlefield",
        "zones": ["library", "graveyard"],
    }


def test_zone_search_type_criteria():
    spec = parse_effect_body(
        "search your library and/or graveyard for an artifact card, reveal "
        "it, and put it into your hand. if you searched your library this "
        "way, shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"type": "artifact"},
        "destination": "hand",
        "zones": ["library", "graveyard"],
    }


def test_fails_closed_on_a_comma_bearing_name():
    # Grasping Current-shaped: "a card named Jace, Ingenious Mind-Mage" — the
    # name's own internal comma is indistinguishable from the put-clause's
    # comma without a name dictionary, so this stays unclaimed.
    assert parse_effect_body(
        "search your library and/or graveyard for a card named jace, "
        "ingenious mind-mage, reveal it, and put it into your hand. if you "
        "search your library this way, shuffle"
    ) is None


# ---------------------------------------------------------------------------
# Split-destination axis: "put one X and the other Y" (`_search_split_
# destination`, Cultivate/Kodama's Reach-shaped)
# ---------------------------------------------------------------------------


def test_split_destination_battlefield_tapped_and_hand():
    spec = parse_effect_body(
        "search your library for up to 2 basic land cards, reveal those "
        "cards, put 1 onto the battlefield tapped and the other into your "
        "hand, then shuffle"
    )[0]
    assert spec.params == {
        "criteria": {"basic": True},
        "destination": "battlefield_tapped",
        "destinations": ["battlefield_tapped", "hand"],
        "count": 2,
    }


# ---------------------------------------------------------------------------
# Exile-rest axis: "search for N cards and exile the rest" (`_search_exile_
# rest`, Doomsday-shaped)
# ---------------------------------------------------------------------------


def test_exile_rest_library_and_graveyard():
    spec = parse_effect_body(
        "search your library and graveyard for 5 cards and exile the rest. "
        "put the chosen cards on top of your library in any order"
    )[0]
    assert spec.params == {
        "criteria": {},
        "destination": "library_top",
        "count": 5,
        "exile_rest": True,
        "zones": ["library", "graveyard"],
    }


def test_exile_rest_library_only():
    spec = parse_effect_body(
        "search your library for 3 cards and exile the rest. put the "
        "chosen cards on top of your library in any order"
    )[0]
    assert spec.params["zones"] == ["library"]
    assert spec.params["count"] == 3


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


def test_real_zone_search_card_finds_a_graveyard_hit():
    # Tower Winder: an ETB trigger searching both library and graveyard for
    # a card named Command Tower — proves a graveyard-only hit is found,
    # removed from the graveyard (not the library), and the library still
    # shuffles (RULE 701.19e, since "library" is among the searched zones).
    command_tower = Card(
        id="Command Tower", name="Command Tower", type_line="Land", is_land=True,
    )
    other_land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    creature_card = Card(
        id="Tower Winder", name="Tower Winder", type_line="Creature — Snake",
        is_creature=True, power=1, toughness=1,
        oracle_text="Reach, deathtouch\nWhen this creature enters, search your library "
                    "and/or graveyard for a card named Command Tower, reveal it, and put "
                    "it into your hand. If you search your library this way, shuffle.",
    )

    eng = GameEngine.new_game([("p1", "Alice", [other_land])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    tower_obj = GameObject(command_tower, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(tower_obj, Zone.GRAVEYARD)

    creature_obj = GameObject(creature_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(creature_obj)
    p1.add_to_zone(creature_obj, Zone.HAND)
    eng.cast_spell(p1, creature_obj)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    assert {e["name"] for e in choice["eligible"]} == {"Command Tower"}

    eng.rules.resolve_search_choice(tower_obj.instance_id)
    assert eng.state.pending_choice is None
    assert tower_obj in p1.hand
    assert tower_obj not in p1.graveyard
    assert any(e.type == EventType.SHUFFLE for e in eng.state.event_log)


def test_real_split_destination_card_binds_and_resolves_end_to_end():
    # Cultivate: full parse -> bind -> cast -> resolve, proving both real
    # picks land on their own distinct destination from one search.
    forest = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    mountain = Card(id="Mountain", name="Mountain", type_line="Basic Land — Mountain", is_land=True)
    spell_card = Card(
        id="Cultivate", name="Cultivate", type_line="Sorcery", is_sorcery=True,
        oracle_text="Search your library for up to two basic land cards, reveal those "
                    "cards, put one onto the battlefield tapped and the other into your "
                    "hand, then shuffle.",
    )

    eng = GameEngine.new_game([("p1", "Alice", [forest, mountain])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    obj = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(first)
    second = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(second)

    assert eng.state.pending_choice is None
    first_obj = eng.state.find_object(first)
    assert first_obj in eng.state.battlefield and first_obj.tapped
    assert any(o.instance_id == second for o in p1.hand)


def test_exile_rest_engine_moves_leftover_matches_to_exile_and_skips_shuffle():
    # Doomsday-shaped: the engine primitive directly (the parser recognition
    # is proven above; oracle-parsing Doomsday's own life-loss clause is a
    # separate, unrelated gap — this proves `RulesEngine`'s exile_rest/zones
    # behaviour against a real 5-card library, library+graveyard combined).
    cards = [Card(id=f"Card {i}", name=f"Card {i}", type_line="Instant", is_instant=True)
             for i in range(5)]
    eng = GameEngine.new_game([("p1", "Alice", cards)], starting_hand=0)
    p1 = eng.state.active_player
    # Move one card into the graveyard so both zones are actually searched.
    gy_obj = p1.library[0]
    p1.remove_from_zone(gy_obj, gy_obj.zone)
    p1.add_to_zone(gy_obj, Zone.GRAVEYARD)

    eng.rules.request_search(
        p1, "", "library_top", count=5, zones=["library", "graveyard"], exile_rest=True,
    )
    picked = []
    while eng.state.pending_choice is not None:
        cid = eng.state.pending_choice["eligible"][0]["instance_id"]
        picked.append(cid)
        eng.rules.resolve_search_choice(cid)

    assert len(picked) == 5  # every card in the 5-card library+graveyard
    assert p1.library == [] and p1.graveyard == []
    assert not any(e.type == EventType.SHUFFLE for e in eng.state.event_log)
