"""PAR-30 "Tapped and attacking" — put-from-hand card filters.

* "with lesser power" (Shadowfax, Lord of Horses) →
  `PutFromHandOntoBattlefieldEffect.power_less_than_source`, a `max_power`
  cap vs the effect's source resolved at `apply` time.
* "with mana value X or less … where X is the number of attacking creatures
  you control" (Kinscaer Sentry) → `max_mana_value_selector`, folded into
  `criteria["max_mana_value"]` via `continuous.count_selector` at `apply`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse ----------------------------------------------------------------


def test_lesser_power_parses():
    assert match_clause(
        "put a creature card with lesser power from your hand onto the "
        "battlefield tapped and attacking"
    ) == [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "creature"}, "count": 1,
        "power_less_than_source": True, "tapped": True, "attacking": True,
    })]


def test_fixed_mv_cap_parses():
    specs = match_clause(
        "put a creature card with mana value 3 or less from your hand onto "
        "the battlefield tapped and attacking"
    )
    assert specs == [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "creature", "max_mana_value": 3}, "count": 1,
        "tapped": True, "attacking": True,
    })]


def test_dynamic_mv_cap_needs_the_where_clause():
    ok = match_clause(
        "put a creature card with mana value x or less from your hand onto "
        "the battlefield tapped and attacking, where x is the number of "
        "attacking creatures you control"
    )
    assert ok == [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "creature"}, "count": 1,
        "max_mana_value_selector": "attacking_creatures_you_control",
        "tapped": True, "attacking": True,
    })]
    # no "where X is …" → X unresolvable → fail closed
    assert match_clause(
        "put a creature card with mana value x or less from your hand onto "
        "the battlefield tapped and attacking"
    ) is None


# --- real cards ---------------------------------------------------------


def test_shadowfax_modeled():
    c = Card(id="sf", name="Shadowfax, Lord of Horses",
             type_line="Legendary Creature — Horse", is_creature=True,
             oracle_text=("Horses you control have haste.\n"
                          "Whenever Shadowfax attacks, you may put a creature card "
                          "with lesser power from your hand onto the battlefield "
                          "tapped and attacking."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_kinscaer_sentry_modeled():
    c = Card(id="ks", name="Kinscaer Sentry", type_line="Creature — Human Soldier",
             is_creature=True, oracle_text=(
                 "First strike, lifelink\n"
                 "Whenever this creature attacks, you may put a creature card with "
                 "mana value X or less from your hand onto the battlefield tapped "
                 "and attacking, where X is the number of attacking creatures you "
                 "control."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute ----------------------------------------------------------


def test_lesser_power_only_offers_smaller_creatures():
    eng, st = _engine()
    src = GameObject(Card(id="s", name="Shadowfax", type_line="Creature — Horse",
                          is_creature=True, power=4, toughness=4),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    p1 = st.player_by_id("p1")
    big = GameObject(Card(id="b", name="Big", type_line="Creature", is_creature=True,
                          power=6, toughness=6), owner_id="p1", zone=Zone.HAND)
    small = GameObject(Card(id="sm", name="Small", type_line="Creature", is_creature=True,
                            power=2, toughness=2), owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([big, small])

    build_effects([EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "creature"}, "count": 1,
        "power_less_than_source": True, "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(st, eng.rules), [])

    pc = st.pending_choice
    assert pc and pc["kind"] == "search"
    labels = [o.get("label") for o in pc["options"]]
    assert "Small" in labels
    assert "Big" not in labels


def test_no_source_power_fails_closed():
    eng, st = _engine()
    src = GameObject(Card(id="s", name="Enchantment", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    p1 = st.player_by_id("p1")
    c = GameObject(Card(id="c", name="Bear", type_line="Creature", is_creature=True,
                        power=2, toughness=2), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(c)

    build_effects([EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "creature"}, "count": 1,
        "power_less_than_source": True, "attacking": True,
    })], src)[0].apply(GameContext(st, eng.rules), [])

    # source has no power → max_power = -1 → nothing qualifies → no choice opens
    assert st.pending_choice is None
    assert not any(o.name == "Bear" for o in st.battlefield)
