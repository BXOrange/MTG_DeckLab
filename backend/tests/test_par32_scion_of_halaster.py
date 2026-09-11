"""PAR-32 / MEC-57 — Scion of Halaster's granted *replacement* body:

    Commander creatures you own have "The first time you would draw a card
    each turn, instead look at the top two cards of your library. Put one
    of them into your graveyard and the other back on top of your library.
    Then draw a card."

Hand-authored (`ability_catalogue.special_mechanics._scion_of_halaster`): a
granted `ReplacementEffect` (`effects._first_draw_look_two_replacement`),
which the existing `grant_static_ability` ``static_specs`` plumbing now
also recognises alongside a granted `StaticAbility`
(`continuous._apply_layer_6_ability`, `GameObject._granted_replacement_
effects`, `RulesEngine._all_replacement_effects`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue


def test_scion_of_halaster_registered_as_granted_replacement():
    specs = ability_catalogue.specs_for(
        Card(id="soh", name="Scion of Halaster",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    (grant,) = specs[0].effects
    assert grant.type == "grant_static_ability"
    assert grant.params["affects"] == "commander_creatures_you_own"
    (inner,) = grant.params["static_specs"]
    assert inner["type"] == "first_draw_look_two"


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _bf(st, card, controller="p1", commander=False):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.is_commander = commander
    st.add_to_battlefield(o)
    return o


def _lib_card(name):
    return GameObject(
        Card(id=name.lower(), name=name, type_line="Creature — Bear",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.LIBRARY,
    )


def test_first_draw_each_turn_looks_at_two_bins_one_keeps_other_draws():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="soh", name="Scion of Halaster",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Illithid",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()  # settle the granted replacement

    p1 = st.player_by_id("p1")
    card_a, card_b, card_c = _lib_card("CardA"), _lib_card("CardB"), _lib_card("CardC")
    p1.library.extend([card_a, card_b, card_c])  # bottom-first: C is on top

    eng.rules.draw(p1, 1)

    # C (the top card) is kept and drawn; B (second from top) is binned;
    # A is untouched at the bottom.
    assert [o.card.name for o in p1.hand] == ["CardC"]
    assert [o.card.name for o in p1.graveyard] == ["CardB"]
    assert [o.card.name for o in p1.library] == ["CardA"]
    assert "p1" in st.first_draw_replaced_this_turn


def test_second_draw_same_turn_is_not_replaced_again():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="soh", name="Scion of Halaster",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Illithid",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    card_a, card_b, card_c = _lib_card("CardA"), _lib_card("CardB"), _lib_card("CardC")
    p1.library.extend([card_a, card_b, card_c])

    eng.rules.draw(p1, 1)  # first draw this turn: replaced
    eng.rules.draw(p1, 1)  # second draw this turn: ordinary

    assert sorted(o.card.name for o in p1.hand) == ["CardA", "CardC"]
    assert [o.card.name for o in p1.graveyard] == ["CardB"]
    assert p1.library == []


def test_opponent_draw_is_unaffected():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="soh", name="Scion of Halaster",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Illithid",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p2 = st.player_by_id("p2")
    p2.library.extend([_lib_card("O1"), _lib_card("O2")])

    eng.rules.draw(p2, 1)

    assert [o.card.name for o in p2.hand] == ["O2"]
    assert p2.graveyard == []
    assert "p2" not in st.first_draw_replaced_this_turn
