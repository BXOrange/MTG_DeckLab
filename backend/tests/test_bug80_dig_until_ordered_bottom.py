"""BUG-80: "reveal cards from the top of your library until you reveal a <type> card. Put that card ... and the rest on
the bottom of your library in any order." is the player's own ordering of the pile (RULE 401.4), not a random shuffle;
"in a random order" stays random. `dig_until` reuses the PAR-292 M11 bottom-ordering choice."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

from tests.test_par144_dig_family import _card, _engine, _stock

ANY = ("reveal cards from the top of your library until you reveal a creature card. put that card into your hand "
       "and the rest on the bottom of your library in any order.")
RANDOM = ANY.replace("any order", "a random order")
FILLERS = ("Rest A", "Rest B", "Rest C")


def _spell_resolves(eng, player, text):
    spell = GameObject(_card("Dig Spell", "Sorcery", cost="", cmc=0, oracle_text=text), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.rules.cast_spell(player, spell)
    eng.resolve_until_stable()


def _answer_in_order(eng, names):
    """Answer the ordering choice with ``names`` (topmost of the bottom pile first)."""
    for name in names:
        choice = eng.state.pending_choice
        if choice is None:
            break
        option = next(o for o in choice["options"] if o.get("label") == name)
        eng.rules.resolve_choice(option["instance_id"])
        eng.resolve_until_stable()


def _stock_dig(player, fillers):
    deep = _card("Deep", "Sorcery", cost="", cmc=0)
    _stock(player, *[_card(n, "Sorcery", cost="", cmc=0) for n in fillers],
           _card("Hit", "Creature — Bear"), deep)


def test_in_any_order_parses_to_the_ordered_bottom_and_random_stays_random():
    assert match_clause(ANY)[0].params["rest_destination"] == "library_bottom_order"
    assert match_clause(RANDOM)[0].params["rest_destination"] == "library_bottom_random"


def test_player_orders_the_bottom_pile():
    eng, p1 = _engine()
    _stock_dig(p1, FILLERS)
    _spell_resolves(eng, p1, ANY)
    assert eng.state.pending_choice is not None and eng.state.pending_choice["kind"] == "library_bottom"
    assert [o.name for o in p1.hand] == ["Hit"]
    _answer_in_order(eng, ["Rest C", "Rest A", "Rest B"])
    assert eng.state.pending_choice is None
    # the bottom three, topmost of the pile first: library[0] is the very bottom
    assert [o.name for o in reversed(p1.library[:3])] == ["Rest C", "Rest A", "Rest B"]
    assert all(o.zone == Zone.LIBRARY for o in p1.library)
    assert not p1.exile


def test_the_pending_order_choice_survives_a_state_clone():
    eng, p1 = _engine()
    _stock_dig(p1, FILLERS)
    _spell_resolves(eng, p1, ANY)
    restored = GameEngine(eng.state.clone())
    assert restored.state.pending_choice["kind"] == "library_bottom"
    _answer_in_order(restored, ["Rest B", "Rest C", "Rest A"])
    rp1 = restored.state.players[0]
    assert [o.name for o in reversed(rp1.library[:3])] == ["Rest B", "Rest C", "Rest A"]


def test_a_single_leftover_card_needs_no_choice():
    eng, p1 = _engine()
    _stock_dig(p1, ("Only Rest",))
    _spell_resolves(eng, p1, ANY)
    assert eng.state.pending_choice is None
    assert p1.library[0].name == "Only Rest" and p1.library[0].zone == Zone.LIBRARY


def test_random_order_opens_no_choice_and_bottoms_every_card():
    eng, p1 = _engine()
    _stock_dig(p1, FILLERS)
    _spell_resolves(eng, p1, RANDOM)
    assert eng.state.pending_choice is None
    assert sorted(o.name for o in p1.library[:3]) == sorted(FILLERS)


def test_recross_the_paths_and_clifftop_lookout_parse_to_the_ordered_bottom():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

    texts = {
        "Recross the Paths": ("Sorcery", "Reveal cards from the top of your library until you reveal a land card. Put "
                              "that card onto the battlefield and the rest on the bottom of your library in any "
                              "order. Clash with an opponent. If you win, return Recross the Paths to its owner's "
                              "hand."),
        "Clifftop Lookout": ("Creature — Elf Scout", "{1}{G}, {T}: Reveal cards from the top of your library until "
                             "you reveal a land card. Put that card onto the battlefield and the rest on the bottom "
                             "of your library in any order."),
    }
    for name, (tl, text) in texts.items():
        card = Card(id=name, name=name, type_line=tl, is_sorcery=tl == "Sorcery", is_creature="Creature" in tl,
                    oracle_text=text)
        verdict = parse_oracle(card)
        assert verdict.coverage != UNMODELED, name
        assert "library_bottom_order" in repr(verdict), name
