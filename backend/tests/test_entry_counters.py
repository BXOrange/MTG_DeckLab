"""Engine-side behaviour tests for the RULE 614.1-style "enters with N
counters" clause (`parser/oracle/catalogue/counters.py`,
`game/ability_catalogue.entry_counters`, `RulesEngine._apply_entry_counters`).
Clause-shape recognition itself is covered by `test_oracle_counters.py`.
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine


def creature(name, cost, oracle_text, power=1, toughness=1):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Beast",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        oracle_text=oracle_text,
    )


def make_engine(p1_cards, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    return GameEngine.new_game(libs, starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# Fixed amount
# ---------------------------------------------------------------------------


def test_fixed_amount_creature_enters_with_counters():
    card = creature(
        "Steady Beast", "{2}{G}",
        "This creature enters with 3 +1/+1 counters on it.", power=1, toughness=1,
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 2})
    obj = p1.hand[0]
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Steady Beast")
    assert battlefield_obj.counters.get("+1/+1") == 3
    assert battlefield_obj.power == 4  # 1 printed + 3 from counters


def test_fixed_amount_bare_word_counter_type():
    card = creature("Ice Beast", "{2}{U}", "This creature enters with 4 ice counters on it.")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 1, "C": 2})
    obj = p1.hand[0]
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Ice Beast")
    assert battlefield_obj.counters.get("ice") == 4


# ---------------------------------------------------------------------------
# X amount (RULE 107.3c)
# ---------------------------------------------------------------------------


def test_x_amount_uses_the_paid_x_value():
    card = creature("X Beast", "{X}{G}", "This creature enters with X +1/+1 counters on it.")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 5})
    obj = p1.hand[0]
    eng.cast_spell(p1, obj, x=5)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "X Beast")
    assert battlefield_obj.counters.get("+1/+1") == 5


def test_x_zero_puts_no_counters():
    card = creature("X Beast", "{X}{G}", "This creature enters with X +1/+1 counters on it.")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add("G", 1)
    obj = p1.hand[0]
    eng.cast_spell(p1, obj)  # X defaults to 0
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "X Beast")
    assert "+1/+1" not in battlefield_obj.counters


# ---------------------------------------------------------------------------
# A card with no entry-counters clause is unaffected
# ---------------------------------------------------------------------------


def test_ordinary_creature_gets_no_counters():
    card = creature("Grizzly Bears", "{1}{G}", "", power=2, toughness=2)
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})
    obj = p1.hand[0]
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Grizzly Bears")
    assert battlefield_obj.counters == {}


# ---------------------------------------------------------------------------
# Sunburst (RULE 702.43a) — "for each color of mana spent to cast it"
# ---------------------------------------------------------------------------


def test_sunburst_condition_is_recognized():
    from mtg_analyzer.game import ability_catalogue

    card = creature(
        "Prism Beast", "{4}",
        "Prism Beast enters with a +1/+1 counter on it for each color of mana spent to cast it.",
    )
    assert ability_catalogue.entry_counters(card) == {
        "is_x": False, "count": 1, "counter_type": "+1/+1", "colors_spent_scale": True,
    }


def test_sunburst_counts_distinct_colors_spent():
    card = creature(
        "Prism Beast", "{2}",
        "Prism Beast enters with a +1/+1 counter on it for each color of mana spent to cast it.",
        power=0, toughness=1,
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "U": 1})  # {2} paid with W + U → 2 colors
    eng.cast_spell(p1, p1.hand[0])
    eng.resolve_until_stable()
    obj = next(o for o in eng.state.battlefield if o.name == "Prism Beast")
    assert obj.counters.get("+1/+1") == 2
    assert obj.power == 2


def test_sunburst_with_only_colorless_mana_gets_no_counters():
    card = creature(
        "Prism Beast", "{2}",
        "Prism Beast enters with a +1/+1 counter on it for each color of mana spent to cast it.",
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 2})
    eng.cast_spell(p1, p1.hand[0])
    eng.resolve_until_stable()
    obj = next(o for o in eng.state.battlefield if o.name == "Prism Beast")
    assert "+1/+1" not in obj.counters
