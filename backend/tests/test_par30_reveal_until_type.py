"""PAR-30 — "reveal cards from the top of your library until you reveal a
<type> card. Put that card <onto the battlefield / into your hand> and the
rest <bottom / graveyard / shuffle>."

`RulesEngine.dig_until` / `effects.DigUntilEffect` (the generalized cascade
dig — predicate + both destinations parameterized) is the engine primitive;
only the "reveal until a *type* predicate" recognition was missing.
Documented simplification: "in any order" is modeled as `dig_until`'s only
bottoming mode, a random order. Fails closed on "onto the battlefield
**tapped**" (no tapped-entry mode).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause(
        "reveal cards from the top of your library until you reveal a land "
        "card. put that card onto the battlefield and the rest on the bottom "
        "of your library in any order"
    ) == [EffectSpec("dig_until", {
        "criteria": {"type": "land"},
        "hit_destination": "battlefield",
        "rest_destination": "library_bottom_random",
    })]
    assert match_clause(
        "reveal cards from the top of your library until you reveal a creature "
        "card. put that card into your hand and the rest into your graveyard"
    ) == [EffectSpec("dig_until", {
        "criteria": {"type": "creature"},
        "hit_destination": "hand",
        "rest_destination": "graveyard",
    })]


def test_tapped_hit_fails_closed():
    assert match_clause(
        "reveal cards from the top of your library until you reveal a land "
        "card. put that card onto the battlefield tapped and the rest on the "
        "bottom of your library in a random order"
    ) is None


def test_real_cards_modeled():
    for name, tl, text in [
        ("Recross the Paths", "Sorcery",
         "Reveal cards from the top of your library until you reveal a land "
         "card. Put that card onto the battlefield and the rest on the bottom "
         "of your library in any order. Clash with an opponent. If you win, "
         "return Recross the Paths to its owner's hand."),
        ("Atla Palani, Nest Tender", "Legendary Creature — Bird Shaman",
         "Whenever an Egg you control dies, reveal cards from the top of your "
         "library until you reveal a creature card. Put that card onto the "
         "battlefield and the rest on the bottom of your library in a random order."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_sorcery=tl == "Sorcery",
                 is_creature="Creature" in tl,
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_dig_until_land_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")
    for nm, land in [("Bolt", False), ("Bolt2", False), ("Forest", True)]:
        o = GameObject(
            Card(id=nm, name=nm,
                 type_line="Basic Land — Forest" if land else "Instant",
                 is_land=land, is_instant=not land),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        o.controller_id = "p1"
        p1.library.append(o)  # top = end of list

    src = GameObject(Card(id="RTP", name="Recross the Paths", type_line="Sorcery",
                          is_sorcery=True), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    eff = build_effects([EffectSpec("dig_until", {
        "criteria": {"type": "land"}, "hit_destination": "battlefield",
        "rest_destination": "library_bottom_random",
    })], src)[0]
    eff.apply(eng.rules.context, [])

    assert any(o.card.name == "Forest" for o in st.battlefield)
    assert len(p1.library) == 2  # the two nonlands bottomed
