"""Blight Curse batch C3 effect-body handlers — Dread Tiller / Village
Pillagers (the trigger conditions already parse; these are the effect
clauses that didn't).

* ``put_from_hand_onto_battlefield`` gained a ``zones`` param (default
  ``["hand"]``) so "…from your hand **or graveyard**…" (Dread Tiller) can
  pick from both; the parser row also learned the plain "…onto the
  battlefield **tapped**." tail (Arboreal Grazer, Cultivator Colossus, …).
* ``DealDamageEffect`` gained the ``each_creature_opponents_control``
  selector (Village Pillagers' ETB — opponents' creatures only, no
  players).
* ``create_named_token`` learned a leading "tapped" ("create a tapped
  Treasure token").
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# --- parse -----------------------------------------------------------------


def test_put_land_from_hand_tapped_parses():
    assert match_clause("you may put a land card from your hand onto the battlefield tapped") == [
        EffectSpec("put_from_hand_onto_battlefield", {"criteria": {"type": "land"}, "count": 1,
                                                      "tapped": True})
    ]


def test_put_land_from_hand_or_graveyard_tapped_parses():
    specs = match_clause(
        "you may put a land card from your hand or graveyard onto the battlefield tapped"
    )
    assert specs[0].params["zones"] == ["hand", "graveyard"]
    assert specs[0].params["tapped"] is True


def test_tapped_and_attacking_still_wins_over_plain_tapped():
    specs = match_clause(
        "put a creature card from your hand onto the battlefield tapped and attacking"
    )
    assert specs[0].params["attacking"] is True and specs[0].params["tapped"] is True


def test_damage_each_creature_opponents_control_parses():
    assert match_clause("~ deals 1 damage to each creature your opponents control") == [
        EffectSpec("damage", {"amount": 1, "selector": "each_creature_opponents_control"})
    ]


def test_tapped_named_token_parses():
    # match_clause is fed already-normalized (lower-cased) text, like the
    # real pipeline hands the handlers.
    assert match_clause("create a tapped treasure token") == [
        EffectSpec("create_token", {"count": 1, "token_name": "Treasure", "tapped": True})
    ]


def test_real_cards_now_modeled():
    for name, tl, text in [
        ("Dread Tiller", "Artifact Creature — Scarecrow",
         "When this creature enters, put a -1/-1 counter on target creature.\n"
         "Whenever a creature with a -1/-1 counter on it dies, you may put a land card "
         "from your hand or graveyard onto the battlefield tapped."),
        ("Village Pillagers", "Creature — Goblin Warrior",
         "Wither\nWhen this creature enters, it deals 1 damage to each creature your "
         "opponents control.\nWhenever a creature an opponent controls with a counter on "
         "it dies, you create a tapped Treasure token."),
        ("Arboreal Grazer", "Creature — Ape",
         "When Arboreal Grazer enters, you may put a land card from your hand onto the "
         "battlefield tapped."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_creature=True, power=0, toughness=1,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_each_creature_opponents_control_selector_hits_only_opponents_creatures():
    eng = _engine()
    st = eng.state

    src = GameObject(Card(id="VP", name="Village Pillagers", type_line="Creature — Goblin",
                          is_creature=True, power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    mine = GameObject(Card(id="M", name="Mine", type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    theirs = GameObject(Card(id="T", name="Theirs", type_line="Creature — Bear", is_creature=True,
                             power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    theirs.controller_id = "p2"
    st.add_to_battlefield(mine)
    st.add_to_battlefield(theirs)

    eff = build_effects([EffectSpec("damage", {
        "amount": 1, "selector": "each_creature_opponents_control",
    })], src)[0]
    from mtg_analyzer.game.effects.core import GameContext
    eff.apply(GameContext(eng.state, eng.rules))

    assert theirs.damage_marked == 1
    assert mine.damage_marked == 0
    assert src.damage_marked == 0  # not an opponent's
