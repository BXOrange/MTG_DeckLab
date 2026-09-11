"""PAR-32 / MEC-56 — Master Chef's twin-quoted grant body:

    Commander creatures you own have "This creature enters with an
    additional +1/+1 counter on it" and "Other creatures you control enter
    with an additional +1/+1 counter on them."

A twin-quoted body `"A" and "B"` — outside `_quoted_ability_grant_effects_
list`'s single-inner-body recursion — so this is hand-authored
(`ability_catalogue.special_mechanics._master_chef`) rather than a new parser
grammar for a shape only this card uses. Both clauses reduce to a new
``extra_etb_counter`` static (RULE 614.1 entry-counter replacement,
`continuous.extra_etb_counters_for`, consulted from `RulesEngine._apply_
granted_entry_counters` right where `_apply_entry_counters` reads a
printed entry-counter condition) granted onto every commander creature
the controller owns.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue


def test_master_chef_registered_with_both_grant_clauses():
    specs = ability_catalogue.specs_for(
        Card(id="mc", name="Master Chef", type_line="Legendary Enchantment — Background")
    )
    assert specs is not None and len(specs) == 1
    grants = specs[0].effects
    assert len(grants) == 2
    kinds = sorted(
        (g.params["static_specs"][0]["params"]["self_only"] for g in grants)
    )
    assert kinds == [False, True]
    for g in grants:
        assert g.type == "grant_static_ability"
        assert g.params["affects"] == "commander_creatures_you_own"
        inner = g.params["static_specs"][0]
        assert inner["type"] == "extra_etb_counter"
        assert inner["params"]["kind"] == "+1/+1"
        assert inner["params"]["count"] == 1


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


def test_other_creature_enters_with_extra_counter_from_commander_grant():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="mc", name="Master Chef", type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Chef",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()  # settle the commander's own granted static

    token_card = Card(id="tok", name="Soldier", type_line="Token Creature — Soldier",
                       is_creature=True, power=1, toughness=1)
    (token,) = eng.rules.create_token("p1", token_card)

    assert token.counters.get("+1/+1", 0) == 1


def test_opponents_creature_does_not_get_the_extra_counter():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="mc", name="Master Chef", type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Chef",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    token_card = Card(id="tok2", name="Bear", type_line="Token Creature — Bear",
                       is_creature=True, power=1, toughness=1)
    (token,) = eng.rules.create_token("p2", token_card)

    assert token.counters.get("+1/+1", 0) == 0
