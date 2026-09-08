"""PAR-30 — Waterbend (RULE 701.67) residue, first pass (PARSER_VERSION 215).

Shared parser/engine wins the residue cards were blocked on:

* "Whenever you / an opponent draws their **second** card each turn, …"
  (`segmenter._DRAW_CARD_TRIGGER_NTH_RE` → the engine's existing
  `is_nth_draw_this_turn` predicate). Closes The Unagi of Kyoshi Island.
* "[another] target permanent you control" → the `permanent_you_control`
  target kind. Closes North Pole Patrol.
* "up to one **other** target nonland permanent" → a new `_TARGET_ROWS`
  row. Closes Invasion Submersible's ETB.
* "waterbend {X}" mandatory additional cost → `{"waterbend": "x"}` +
  `legal_actions` `has_x`/`max_x` off a mandatory variable additional cost.
"""

from __future__ import annotations

from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _card(name, type_line, text, mc="{1}{U}", **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=mc,
        converted_mana_cost=2, oracle_text=text, **kw,
    )


# --- "draws their second card each turn" trigger ----------------------

def test_nth_draw_trigger_parses_you_and_opponent():
    you = _card("D1", "Creature — Fish", "Whenever you draw your second card each "
                "turn, put a +1/+1 counter on D1.", is_creature=True, power=1, toughness=1)
    r = parse_oracle(you)
    assert r.modeled
    trg = next(s for s in r.specs if s.trigger)
    assert trg.trigger["event"] == "DRAW"
    assert trg.trigger["is_nth_draw_this_turn"] == 2
    assert trg.trigger["condition"] == {"subject": "you"}

    opp = _card("D2", "Creature — Fish", "Whenever an opponent draws their second "
                "card each turn, you draw a card.", is_creature=True, power=1, toughness=1)
    r2 = parse_oracle(opp)
    assert r2.modeled
    trg2 = next(s for s in r2.specs if s.trigger)
    assert trg2.trigger["is_nth_draw_this_turn"] == 2
    assert trg2.trigger["condition"] == {"subject": "group", "controller": "not_you"}


def test_the_unagi_modeled():
    c = Card(
        id="unagi", name="The Unagi of Kyoshi Island",
        type_line="Creature — Fish Serpent", mana_cost_string="{3}{U}{U}",
        converted_mana_cost=5, is_creature=True, power=5, toughness=5,
        keywords=["Flash", "Ward"],
        oracle_text=(
            "Flash\nWard—Waterbend {4}. (Whenever this creature becomes the "
            "target of a spell or ability an opponent controls, counter it "
            "unless that player pays {4}.)\nWhenever an opponent draws their "
            "second card each turn, you draw two cards."
        ),
    )
    r = parse_oracle(c)
    assert r.modeled
    # Ward—Waterbend {4} resolves to a plain {4} ward via the text-cost
    # fallback (the waterbend helper is the documented-simplification drop).
    kw = [s.keyword for s in r.specs if s.keyword]
    assert {"name": "ward", "cost": "{4}"} in kw


def test_nth_draw_trigger_fires_on_second_draw_only():
    eng = make_engine([creature("F")] * 20, [creature("B")] * 20, hand=0)
    p1 = eng.state.player_by_id("p1")
    watcher = obj_on_battlefield(
        eng.state, eng,
        creature("Watcher", oracle_text="Whenever you draw your second card each "
                 "turn, put a +1/+1 counter on Watcher.", keywords=[]),
        controller="p1",
    )
    bind_from_catalogue(watcher)
    eng.begin_turn()
    eng.rules.draw(p1, 1)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert watcher.counters.get("+1/+1", 0) == 0  # first draw — no trigger
    eng.rules.draw(p1, 1)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert watcher.counters.get("+1/+1", 0) == 1  # second draw — fired once
    eng.rules.draw(p1, 1)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert watcher.counters.get("+1/+1", 0) == 1  # third draw — not again


# --- "another target permanent you control" --------------------------

def test_untap_another_target_permanent_you_control():
    got = match_clause("untap another target permanent you control")
    assert got and got[0].type == "tap"
    assert got[0].params["target_kind"] == "permanent_you_control"
    assert got[0].params["untap"] is True


def test_north_pole_patrol_modeled():
    c = Card(
        id="npp", name="North Pole Patrol", type_line="Creature — Human Soldier Ally",
        mana_cost_string="{2}{U}", converted_mana_cost=3, is_creature=True,
        power=2, toughness=3,
        oracle_text=(
            "{T}: Untap another target permanent you control.\n"
            "Waterbend {3}, {T}: Tap target creature an opponent controls."
        ),
    )
    assert parse_oracle(c).modeled


# --- "up to one other target nonland permanent" ---------------------

def test_return_up_to_one_other_target_nonland_permanent():
    got = match_clause(
        "return up to 1 other target nonland permanent to its owner's hand"
    )
    assert got and got[0].type == "return_to_hand"
    assert got[0].params["target_kind"] == "nonland_permanent"
    assert got[0].params["optional"] is True


# --- waterbend {X} mandatory additional cost -----------------------

def test_waterbend_x_additional_cost_parses():
    c = _card("WBX", "Sorcery",
              "As an additional cost to cast this spell, waterbend {X}.\nDraw X cards.",
              mc="{U}{U}", is_sorcery=True)
    r = parse_oracle(c)
    assert r.modeled
    assert any(s.additional_cost == {"waterbend": "x"} for s in r.specs)


def test_waterbend_x_announced_and_paid_and_read_by_body():
    txt = "As an additional cost to cast this spell, waterbend {X}.\nDraw X cards."
    c = Card(id="wbx", name="WBX Test", type_line="Sorcery", mana_cost_string="{U}{U}",
             converted_mana_cost=2, is_sorcery=True, oracle_text=txt)
    eng = GameEngine.new_game(
        [("p1", "A", [c] * 15), ("p2", "B", [c] * 15)],
        starting_life=20, starting_hand=1,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    for o in p1.hand + p1.library:
        bind_from_catalogue(o)
    obj = p1.hand[0]
    p1.mana_pool.add("U", 12)

    action = next(a for a in eng.legal_actions(p1) if a.get("instance_id") == obj.instance_id)
    assert action.get("has_x") is True
    assert action.get("max_x", 0) >= 3

    before = len(p1.hand)
    eng.cast_spell(p1, obj, x=3)
    eng.resolve_until_stable()
    assert len(p1.hand) - before == 2          # -1 cast, +3 drawn
    assert p1.mana_pool.pool.get("U") == 7     # {U}{U} printed + {3} waterbend
    assert obj.x_paid == 3
