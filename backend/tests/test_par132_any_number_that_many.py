"""PAR-132 -- "<sacrifice/discard> any number of X. <body naming that many/much>" (RULE 608.2c, 701.21).

The pick is bracketed by a `mark_event_log`; the body's one printed number is bound to `sacrificed_this_way` /
`discarded_this_way`, so a body target (Landslide) is still announced on cast (RULE 601.2c).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

LANDSLIDE = "Sacrifice any number of Mountains. ~ deals that much damage to target player or planeswalker."
LAST_DITCH = "Sacrifice any number of creatures. ~ deals that much damage to any target."
SCAPESHIFT = "Sacrifice any number of lands. Search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle."
RITES = "Discard any number of cards. Search your library for up to that many basic land cards, reveal them, put them into your hand, then shuffle."


def _card(name: str, text: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text,
                mana_cost_string="{0}", converted_mana_cost=0)


def _game(mountains: int = 3, creatures: int = 0, hand: int = 0, forests_in_library: int = 0):
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    lib = [Card(id=f"fo{i}", name="Forest", type_line="Basic Land — Forest", is_land=True)
           for i in range(forests_in_library)]
    eng = GameEngine.new_game([("p1", "p1", lib + filler), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    p1 = eng.state.player_by_id("p1")
    for i in range(mountains):
        m = GameObject(Card(id=f"m{i}", name="Mountain", type_line="Basic Land — Mountain", is_land=True),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
        m.controller_id = "p1"
        eng.state.add_to_battlefield(m)
    for i in range(creatures):
        c = GameObject(Card(id=f"c{i}", name=f"Bear{i}", type_line="Creature — Bear", is_creature=True,
                            power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
        c.controller_id = "p1"
        eng.state.add_to_battlefield(c)
    for i in range(hand):
        h = GameObject(Card(id=f"h{i}", name=f"Card{i}", type_line="Creature", is_creature=True, power=1, toughness=1),
                       owner_id="p1", zone=Zone.HAND)
        h.controller_id = "p1"
        p1.hand.append(h)
    return eng, p1, eng.state.player_by_id("p2")


def _cast(eng, p1, text: str, picks: int, targets=None):
    card = _card("Tester", text)
    assert parse_oracle(card).coverage != UNMODELED, parse_oracle(card).unclaimed
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.cast_spell(p1, spell, targets=targets)
    eng.resolve_until_stable()
    for _ in range(picks):
        choice = eng.state.pending_choice
        assert choice and choice["kind"] == "choose_objects"
        eng.rules.resolve_choice(str(choice["options"][0]["id"]))
        eng.resolve_until_stable()
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "choose_objects":
        eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    found = 0
    while eng.state.pending_choice and eng.state.pending_choice["kind"] == "search":
        choice = eng.state.pending_choice
        assert choice["count"] == picks  # RULE 608.2c: "up to that many" is how many were sacrificed/discarded
        eng.rules.resolve_choice(str(choice["eligible"][0]["instance_id"]))
        eng.resolve_until_stable()
        found += 1
        assert found <= picks
    assert eng.state.pending_choice is None


def test_landslide_damages_for_each_mountain_sacrificed():
    eng, p1, p2 = _game(mountains=3, creatures=1)
    _cast(eng, p1, LANDSLIDE, picks=2, targets=[p2])
    assert p2.life == 18
    assert sum(1 for o in eng.state.battlefield if "Mountain" in o.card.type_line) == 1


def test_landslide_pool_is_only_mountains_and_declining_deals_nothing():
    eng, p1, p2 = _game(mountains=2, creatures=2)
    _cast(eng, p1, LANDSLIDE, picks=0, targets=[p2])
    assert p2.life == 20
    assert sum(1 for o in eng.state.battlefield) == 4


def test_last_ditch_effort_damage_equals_creatures_sacrificed():
    eng, p1, p2 = _game(mountains=0, creatures=3)
    _cast(eng, p1, LAST_DITCH, picks=3, targets=[p2])
    assert p2.life == 17
    assert not [o for o in eng.state.battlefield if o.is_creature]


def test_scapeshift_fetches_one_land_per_land_sacrificed():
    eng, p1, _ = _game(mountains=3, forests_in_library=5)
    before = len([o for o in eng.state.battlefield if o.is_land])
    _cast(eng, p1, SCAPESHIFT, picks=2)
    lands = [o for o in eng.state.battlefield if o.is_land]
    assert len(lands) == before  # two sacrificed, two Forests fetched
    assert sum(1 for o in lands if "Forest" in o.card.type_line) == 2


def test_rites_of_spring_discard_count_is_the_search_count():
    eng, p1, _ = _game(mountains=0, hand=3, forests_in_library=5)
    _cast(eng, p1, RITES, picks=2)
    assert len([c for c in p1.hand if c.card.name == "Forest"]) == 2
    assert len(p1.hand) == 1 + 2  # one card left uncast-discarded, plus the two fetched


def test_whole_hand_discard_then_draw_that_many():
    eng, p1, _ = _game(mountains=0, hand=3)
    _cast(eng, p1, "Discard all the cards in your hand. If you do, draw that many cards.", picks=0)
    assert len(p1.hand) == 3
    assert not [c for c in p1.hand if c.card.name.startswith("Card")]  # the original three were discarded


def test_that_many_after_a_mismatched_verb_is_unmodeled():
    card = _card("Odd", "Tap any number of untapped creatures you control. ~ deals that much damage to any target.")
    assert parse_oracle(card).coverage == UNMODELED


def test_scapeshift_declining_every_pick_searches_for_nothing():
    eng, p1, _ = _game(mountains=2, forests_in_library=3)
    _cast(eng, p1, SCAPESHIFT, picks=0)
    assert not [o for o in eng.state.battlefield if "Forest" in o.card.type_line]


def _creature_etb(text: str, hand: int):
    eng, p1, _ = _game(mountains=0, hand=hand)
    for h in p1.hand:  # lands in hand so "any number of land cards" has a pool
        h.card.type_line, h.card.is_land, h.card.is_creature = "Basic Land — Forest", True, False
    card = Card(id="Tester", name="Tester", type_line="Creature — Human", is_creature=True, power=2, toughness=2,
                oracle_text=text, mana_cost_string="{0}", converted_mana_cost=0)
    assert parse_oracle(card).coverage != UNMODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    return eng, p1, obj


def test_nantuko_cultivator_shape_counters_and_draws_per_land_discarded():
    eng, p1, obj = _creature_etb(
        "When this creature enters, you may discard any number of land cards. Put that many +1/+1 counters on "
        "this creature and draw that many cards.", hand=3)
    library_before = len(p1.library)
    eng.rules.resolve_choice("do")  # the "you may" of the whole ability
    eng.resolve_until_stable()
    for _ in range(2):
        choice = eng.state.pending_choice
        assert choice and choice["kind"] == "choose_objects"
        eng.rules.resolve_choice(str(choice["options"][0]["id"]))
        eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.rules.resolve_choice("decline")
        eng.resolve_until_stable()
    assert obj.counters.get("+1/+1", 0) == 2
    assert library_before - len(p1.library) == 2
    assert len(p1.hand) == 1 + 2  # one land left, two draws


def test_book_devourer_shape_optional_whole_hand_draws_that_many():
    text = "When this creature enters, you may discard all the cards in your hand. If you do, draw that many cards."
    eng, p1, obj = _creature_etb(text, hand=3)
    eng.rules.resolve_choice("do")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 3  # three discarded (the whole hand, no pick), three drawn
    assert not [c for c in p1.hand if c.card.name.startswith("Card")]


def test_book_devourer_shape_declined_keeps_the_hand():
    text = "When this creature enters, you may discard all the cards in your hand. If you do, draw that many cards."
    eng, p1, obj = _creature_etb(text, hand=3)
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    assert len([c for c in p1.hand if c.card.name.startswith("Card")]) == 3
