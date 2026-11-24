"""BUG-81: cards that are only looked at or revealed are never exiled (RULE 701.20a, 406.1); a printed exile still is.

`search_mixin` used to peel every looked-at / revealed library card into the exile zone as a holding area and fire
``EXILE`` (``from_zone="library"``) for each. That misfired "whenever one or more cards are put into exile from your
library" (Laelia), exile-count predicates, and made a reveal-until hit "cast from among them" a cast from exile. Looked-at
and revealed cards now stay in the library until they are placed; "exile cards ... until you exile" (and cascade /
discover) still exile. Real engine; the event bus and the zones are the witnesses.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.game.catalogue.cards.test_laelia_the_blade_reforged import _laelia_on_battlefield
from tests.test_cascade_discover import engine_with_library, events_of, land, spell
from tests.test_par144_dig_family import _card, _engine, _stock

REVEAL_CAST = ("Reveal cards from the top of your library until you reveal a nonland card with mana value 3 or less. "
               "You may cast that card without paying its mana cost. Put the revealed cards that weren't cast this way "
               "on the bottom of your library in a random order.")
EXILE_CAST = ("Exile cards from the top of your library until you exile a nonland card. You may cast that card "
              "without paying its mana cost.")
REVEAL_HAND = ("Reveal cards from the top of your library until you reveal a creature card. Put that card into your "
               "hand and the rest on the bottom of your library in any order.")


def _exiles(seen):
    return [e for e in seen if e.type == EventType.EXILE]


def _resolve_spell(eng, player, text):
    obj = GameObject(_card("Dig Spell", "Sorcery", cost="", cmc=0, oracle_text=text), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    eng.rules.cast_spell(player, obj)
    eng.resolve_until_stable()


def _laelia_engine():
    eng, p1 = _engine()
    return eng, p1, _laelia_on_battlefield(eng)


def _stock_dig(p1):
    # top first: two misses, the hit, then a deeper card.
    _stock(p1, _card("Miss A", "Sorcery", cost="", cmc=9), _card("Land", "Basic Land — Forest", cost=""),
           _card("Hit", "Sorcery", cost="", cmc=2), _card("Deep", "Sorcery", cost="", cmc=1))


def test_the_verb_decides_whether_a_dig_carries_reveal():
    from mtg_analyzer.parser.oracle import parse_oracle

    def dig(text):
        card = Card(id="t", name="Probe", type_line="Sorcery", oracle_text=text, is_sorcery=True)
        return next(e for s in parse_oracle(card).specs for e in s.effects if e.type == "dig_until")

    assert dig(REVEAL_CAST).params["reveal"] is True
    assert dig(REVEAL_HAND).params["reveal"] is True
    assert "reveal" not in dig(EXILE_CAST).params


# --- look / reveal digs do not exile -----------------------------------------


def test_an_impulsive_look_fires_no_exile_and_keeps_the_cards_in_the_library():
    eng, p1, laelia = _laelia_engine()
    _stock(p1, _card("Forest", "Basic Land — Forest", is_land=True), _card("Bolt", "Instant"),
           _card("Bear", "Creature — Bear"), _card("Deep", "Sorcery"))
    seen = events_of(eng)
    eng.rules._request_impulsive_look(p1, 3, {"type": "Land"})
    assert not _exiles(seen) and not p1.exile
    assert [o.name for o in p1.library] == ["Deep", "Bear", "Bolt", "Forest"]
    eng.rules.resolve_choice(next(e["instance_id"] for e in eng.state.pending_choice["eligible"]))
    eng.resolve_until_stable()
    assert [o.name for o in p1.hand] == ["Forest"]
    assert {o.name for o in p1.graveyard} == {"Bolt", "Bear"}
    assert not _exiles(seen) and not p1.exile
    assert laelia.counters.get("+1/+1", 0) == 0


def test_the_pending_look_choice_survives_a_clone():
    eng, p1, _ = _laelia_engine()
    _stock(p1, _card("Forest", "Basic Land — Forest", is_land=True), _card("Bolt", "Instant"))
    eng.rules._request_impulsive_look(p1, 2, {"type": "Land"})
    restored = GameEngine(eng.state.clone())
    rp1 = restored.state.players[0]
    assert [o.name for o in rp1.library] == ["Bolt", "Forest"] and not rp1.exile
    restored.rules.resolve_choice(restored.state.pending_choice["eligible"][0]["instance_id"])
    assert [o.name for o in rp1.hand] == ["Forest"] and [o.name for o in rp1.graveyard] == ["Bolt"]


def test_a_reveal_until_dig_fires_reveal_not_exile_and_leaves_exile_untouched():
    eng, p1, laelia = _laelia_engine()
    _stock(p1, _card("Miss A", "Sorcery"), _card("Miss B", "Sorcery"), _card("Hit", "Creature — Bear"),
           _card("Deep", "Sorcery"))
    seen = events_of(eng)
    _resolve_spell(eng, p1, REVEAL_HAND.replace("any order", "a random order"))
    assert not _exiles(seen) and not p1.exile
    assert [e.get("object") for e in seen if e.type == EventType.REVEAL] == ["Miss A", "Miss B", "Hit"]
    assert [o.name for o in p1.hand] == ["Hit"]
    assert laelia.counters.get("+1/+1", 0) == 0
    assert sorted(o.name for o in p1.library[:2]) == ["Miss A", "Miss B"]


def test_a_reveal_until_dig_in_any_order_still_orders_the_bottom_pile():
    eng, p1 = _engine()
    _stock(p1, _card("Miss A", "Sorcery"), _card("Miss B", "Sorcery"), _card("Hit", "Creature — Bear"),
           _card("Deep", "Sorcery"))
    seen = events_of(eng)
    _resolve_spell(eng, p1, REVEAL_HAND)
    choice = eng.state.pending_choice
    assert choice["kind"] == "library_bottom" and not p1.exile and not _exiles(seen)
    option = next(o for o in choice["options"] if o.get("label") == "Miss B")
    eng.rules.resolve_choice(option["instance_id"])
    eng.resolve_until_stable()
    assert [o.name for o in reversed(p1.library[:2])] == ["Miss B", "Miss A"]
    assert all(o.zone == Zone.LIBRARY for o in p1.library)


# --- the hit "from among them" is cast from the library ----------------------


def test_a_reveal_until_hit_is_cast_from_the_library_not_from_exile():
    eng, p1, laelia = _laelia_engine()
    _stock_dig(p1)
    seen = events_of(eng)
    _resolve_spell(eng, p1, REVEAL_CAST)
    choice = eng.state.pending_choice
    assert choice["kind"] == "play_during_resolution" and choice["zone"] == "library"
    hit = eng.state.find_object(choice["instance_ids"][0])
    assert hit.name == "Hit" and hit.zone == Zone.LIBRARY and not p1.exile
    eng.play_resolution_card(p1, hit)
    cast = [e for e in seen if e.type == EventType.SPELL_CAST and e.get("spell") == "Hit"]
    assert [e.get("from_zone") for e in cast] == ["library"]  # RULE 601.2a: cast from where it was
    eng.resolve_until_stable()
    assert {o.name for o in p1.graveyard} >= {"Hit"}
    assert not p1.exile and not _exiles(seen) and laelia.counters.get("+1/+1", 0) == 0
    # The revealed cards that were not cast went to the bottom; the card below the dig stays on top.
    assert p1.library[-1].name == "Deep"
    assert sorted(o.name for o in p1.library[:2]) == ["Land", "Miss A"]


def test_the_pending_reveal_cast_window_survives_a_clone():
    eng, p1 = _engine()
    _stock_dig(p1)
    _resolve_spell(eng, p1, REVEAL_CAST)
    restored = GameEngine(eng.state.clone())
    rp1 = restored.state.players[0]
    hit = restored.state.find_object(restored.state.pending_choice["instance_ids"][0])
    assert hit.zone == Zone.LIBRARY and hit in rp1.library and not rp1.exile


# --- printed exile still exiles ----------------------------------------------


def test_an_exile_until_dig_still_exiles_and_fires_exile_events():
    eng, p1, laelia = _laelia_engine()
    _stock(p1, _card("Land A", "Basic Land — Forest", cost=""), _card("Land B", "Basic Land — Forest", cost=""),
           _card("Hit", "Sorcery", cost="", cmc=2), _card("Deep", "Sorcery", cost="", cmc=1))
    seen = events_of(eng)
    _resolve_spell(eng, p1, EXILE_CAST)
    assert [e.get("object") for e in _exiles(seen)] == ["Land A", "Land B", "Hit"]
    assert all(e.get("from_zone") == "library" for e in _exiles(seen))
    assert eng.state.pending_choice["zone"] == "exile"
    eng.rules.resolve_choice("decline")  # the observer's triggers wait behind the cast window
    eng.resolve_until_stable()
    assert laelia.counters.get("+1/+1", 0) > 0  # printed exile from the library does trigger it


def test_cascade_still_exiles_each_card_and_triggers_the_observer():
    eng, p1 = engine_with_library([land("Filler"), spell("Small", 2), spell("Big", 5), land("TopLand")])
    laelia = _laelia_on_battlefield(eng)
    seen = events_of(eng)
    eng.rules._request_cascade(p1, max_mana_value=4)
    assert [e.get("object") for e in _exiles(seen)] == ["TopLand", "Big", "Small"]
    assert len(p1.exile) == 3
    eng.rules.resolve_choice("decline")  # the observer's trigger waits behind the cast window
    eng.resolve_until_stable()
    assert laelia.counters.get("+1/+1", 0) > 0


def test_discover_still_exiles():
    eng, p1 = engine_with_library([land("Filler"), spell("Small", 2), land("TopLand")])
    seen = events_of(eng)
    eng.rules._request_discover(p1, max_mana_value=3)
    assert [e.get("object") for e in _exiles(seen)] == ["TopLand", "Small"]
    assert len(p1.exile) == 2
