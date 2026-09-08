"""PAR-30 — Clash win-branch residue batch 8 (two small bodies).

- "untap all <basic land subtype> you control" (Woodland Guidance) → a new
  `continuous.group_selector_objects` `lands_you_control_of_type_<x>`
  branch + `_is_valid_tap_selector` widen.
- "~ deals N damage to each creature blocking it" (Fire Juggler, 4 cards) →
  a new `DealDamageEffect.each_creature_blocking_source` selector.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause("untap all forests you control") == [
        EffectSpec("tap", {"selector": "lands_you_control_of_type_forest", "untap": True})
    ]
    assert match_clause("untap all plains you control")[0].params["selector"] == (
        "lands_you_control_of_type_plains"
    )
    assert match_clause("~ deals 4 damage to each creature blocking it") == [
        EffectSpec("damage", {"amount": 4, "selector": "each_creature_blocking_source"})
    ]


def test_real_cards_modeled():
    for name, tl, text in [
        ("Woodland Guidance", "Sorcery",
         "Return target card from your graveyard to your hand. Clash with an "
         "opponent. If you win, untap all Forests you control."),
        ("Fire Juggler", "Creature — Human",
         "Whenever Fire Juggler becomes blocked, clash with an opponent. If "
         "you win, Fire Juggler deals 4 damage to each creature blocking it."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_sorcery=tl == "Sorcery",
                 is_creature="Creature" in tl,
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_untap_lands_of_type_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    forests = []
    for i in range(3):
        f = GameObject(Card(id=f"F{i}", name="Forest", type_line="Basic Land — Forest",
                            is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
        f.controller_id = "p1"
        f.tapped = True
        st.add_to_battlefield(f)
        forests.append(f)
    isl = GameObject(Card(id="I", name="Island", type_line="Basic Land — Island",
                          is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    isl.controller_id = "p1"
    isl.tapped = True
    st.add_to_battlefield(isl)

    src = GameObject(Card(id="S", name="WG", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    build_effects([EffectSpec("tap", {
        "selector": "lands_you_control_of_type_forest", "untap": True,
    })], src)[0].apply(eng.rules.context, [])

    assert all(not f.tapped for f in forests)
    assert isl.tapped is True  # not a Forest


def test_damage_each_blocker_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    fj = GameObject(Card(id="FJ", name="Fire Juggler", type_line="Creature",
                         is_creature=True, power=1, toughness=1),
                    owner_id="p1", zone=Zone.BATTLEFIELD)
    fj.controller_id = "p1"
    st.add_to_battlefield(fj)
    tough = GameObject(Card(id="T", name="Wall", type_line="Creature", is_creature=True,
                            power=1, toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
    tough.controller_id = "p2"
    tough.blocking = fj.instance_id
    st.add_to_battlefield(tough)
    frail = GameObject(Card(id="Fr", name="Frog", type_line="Creature", is_creature=True,
                            power=1, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    frail.controller_id = "p2"
    frail.blocking = fj.instance_id
    st.add_to_battlefield(frail)

    build_effects([EffectSpec("damage", {
        "amount": 4, "selector": "each_creature_blocking_source",
    })], fj)[0].apply(eng.rules.context, [])
    eng.rules.check_state_based_actions()

    assert tough in st.battlefield        # 4 < 5
    assert frail not in st.battlefield    # 4 >= 2
