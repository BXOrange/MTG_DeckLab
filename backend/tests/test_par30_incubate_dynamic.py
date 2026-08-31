"""PAR-30 — "Incubate X, where X is `<count>`" dynamic amount.

`_incubate` (RULE 701.53, PAR-29) only handled a literal "incubate N". The
"…where X is …" forms real cards print resolve X fresh at incubate time:

- a board count (`continuous.count_selector`) — "the number of lands you
  control" (Glistening Dawn), "the number of creature cards in your
  graveyard" (Blight Titan). New `count_from_count_selector` key on
  `CreateTokenEffect.extra_counters`; `creature_cards_in_your_graveyard`
  added to `continuous.count_selector`.
- the firing spell's mana value — "…where X is that spell's mana value"
  (Chrome Host Seedshark). New `count_from_trigger_event` key.
- "incubate X **twice**" — two Incubator tokens, each with X counters,
  which is just `create_token`'s own `count=2`.

"…where X is its power" (a dying creature's own power) and "…that many
times" (a search count) stay UNMODELED, fail-closed.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )


def _bear(name="Bear"):
    return Card(id=name[:6], name=name, type_line="Creature — Bear",
               is_creature=True, power=2, toughness=2)


# --- parse ------------------------------------------------------------------


def test_incubate_x_board_count_selector_parses():
    card = Card(id="gld", name="Glistening Dawn", type_line="Sorcery",
                is_sorcery=True, mana_cost_string="{5}{G}{G}",
                oracle_text="Incubate X twice, where X is the number of lands you control.")
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    spec = r.specs[0].effects[0]
    assert spec.type == "create_token"
    assert spec.params["count"] == 2
    assert spec.params["extra_counters"] == {
        "kind": "+1/+1", "count_from_count_selector": "lands_you_control",
    }


def test_incubate_x_creature_cards_in_graveyard_parses():
    card = Card(id="bt", name="Blight Titan",
                type_line="Creature — Phyrexian Horror", is_creature=True,
                power=5, toughness=5, mana_cost_string="{4}{B}{B}",
                oracle_text=("Whenever Blight Titan enters or attacks, mill two "
                             "cards, then incubate X, where X is the number of "
                             "creature cards in your graveyard."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    types = [e.type for e in r.specs[0].effects]
    assert types == ["mill", "create_token"]
    assert r.specs[0].effects[1].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_count_selector": "creature_cards_in_your_graveyard",
    }


def test_incubate_x_that_spells_mana_value_parses():
    card = Card(id="chs", name="Chrome Host Seedshark",
                type_line="Creature — Phyrexian", is_creature=True,
                power=1, toughness=4, mana_cost_string="{2}{U}",
                oracle_text=("Whenever you cast a noncreature spell, incubate X, "
                             "where X is that spell's mana value."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    assert r.specs[0].effects[0].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_trigger_event": "mana_value",
    }


def test_incubate_x_its_power_stays_unmodeled():
    card = Card(id="bp", name="Bloated Processor",
                type_line="Creature — Phyrexian Insect", is_creature=True,
                power=3, toughness=3, mana_cost_string="{3}{B}",
                oracle_text="When Bloated Processor dies, incubate X, where X is its power.")
    assert parse_oracle(card).coverage == UNMODELED


# --- execute --------------------------------------------------------------


def test_incubate_x_places_a_live_graveyard_count_of_counters():
    eng = _engine()
    st = eng.state
    for i in range(3):
        st.players[0].graveyard.append(
            GameObject(_bear(f"GY{i}"), owner_id="p1", zone=Zone.GRAVEYARD)
        )
    # a noncreature card in the graveyard must not be counted
    st.players[0].graveyard.append(
        GameObject(Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
                   owner_id="p1", zone=Zone.GRAVEYARD)
    )

    src = GameObject(Card(id="bt", name="Blight Titan", type_line="Creature — Phyrexian",
                          is_creature=True, power=5, toughness=5),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    build_effects([EffectSpec("create_token", {
        "count": 1, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1",
                           "count_from_count_selector": "creature_cards_in_your_graveyard"},
    })], src)[0].apply(GameContext(st, eng.rules), None)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].counters.get("+1/+1") == 3


def test_incubate_x_twice_makes_two_tokens_each_sized_to_the_count():
    eng = _engine()
    st = eng.state
    # give p1 four lands
    for i in range(4):
        land = GameObject(Card(id=f"F{i}", name="Forest", type_line="Basic Land — Forest",
                               is_land=True),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
        land.controller_id = "p1"
        st.add_to_battlefield(land)

    src = GameObject(Card(id="gld", name="Glistening Dawn", type_line="Sorcery",
                          is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("create_token", {
        "count": 2, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count_from_count_selector": "lands_you_control"},
    })], src)[0].apply(GameContext(st, eng.rules), None)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 2
    assert all(t.counters.get("+1/+1") == 4 for t in tokens)
