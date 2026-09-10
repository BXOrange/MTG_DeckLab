"""MEC-75 — Rolling a die (RULE 706).

`RulesEngine.roll_die(player, sides, count, ignore_lowest, ignore_highest)`
is `coin_flip`'s RULE 706 sibling: it rolls off the same reproducible
game-state RNG (`random_int`), fires a pre-roll `EventType.ROLL_DICE`
(replaceable — advantage/disadvantage) and then `EventType.DICE_ROLLED`
once per instruction (RULE 706.3b), carrying the kept results, every rolled
result, their total and RULE 706.5's ``doubles`` flag.

`effects.RollDieEffect` (registered ``roll_die``) wraps it, stashes the
result on `GameContext.die_result`/``die_results``/``rolled_doubles`` and
applies a RULE 706.3a ``outcomes`` results table. `_roll_dice_modifier_`
`replacement` (``roll_dice_modifier``) is the "roll that many dice plus one
and ignore the lowest roll" advantage rider (Pixie Guide / Barbarian
Class).

Parser: `handlers._roll_die` claims a bare "roll a d20."; `gate.
_split_dice_table_block` claims a roll + "<range> | <effect>" table (bare
or trigger-wrapped); `segmenter` recognises "whenever you roll one or more
dice" → `DICE_ROLLED`; `replacements._ROLL_DICE_MODIFIER_RE` claims the
advantage/disadvantage line.

Reference: game/rules/mana_counters_mixin.py (`roll_die`),
game/effects/core.py (`RollDieEffect`, `_roll_dice_modifier_replacement`),
parser/oracle/{segmenter,gate}.py, parser/oracle/catalogue/{handlers,
replacements}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, RollDieEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.state.current_step = "main1"
    return eng


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- primitive -------------------------------------------------------------


def test_roll_die_is_in_range_and_reproducible():
    eng = _engine()
    eng.state.rng_seed = 4242
    p1 = eng.state.player_by_id("p1")
    first = [eng.rules.roll_die(p1, sides=20)[0] for _ in range(30)]
    assert all(1 <= v <= 20 for v in first)

    eng2 = _engine()
    eng2.state.rng_seed = 4242
    p2 = eng2.state.player_by_id("p1")
    again = [eng2.rules.roll_die(p2, sides=20)[0] for _ in range(30)]
    assert first == again  # same seed → same sequence (survives clone/undo)


def test_roll_die_fires_dice_rolled_once_with_payload():
    eng = _engine()
    eng.state.rng_seed = 7
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.DICE_ROLLED else None
    )
    eng.rules.roll_die(eng.state.player_by_id("p1"), sides=6, count=2)
    assert len(fired) == 1  # RULE 706.3b — one event for the whole instruction
    data = fired[0].data
    assert data["player_id"] == "p1"
    assert len(data["results"]) == 2 and len(data["natural_results"]) == 2
    assert data["total"] == sum(data["results"])
    assert data["sides"] == 6


def test_ignore_lowest_drops_the_smallest_natural_result():
    eng = _engine()
    eng.state.rng_seed = 99
    p1 = eng.state.player_by_id("p1")
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.DICE_ROLLED else None
    )
    kept = eng.rules.roll_die(p1, sides=6, count=4, ignore_lowest=1)
    natural = fired[0].data["natural_results"]
    assert len(natural) == 4 and len(kept) == 3
    # exactly one instance of the minimum was removed; the rest are untouched
    dropped = list(natural)
    dropped.remove(min(natural))
    assert sorted(kept) == sorted(dropped)


def test_ignore_never_empties_the_result():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    # asking to ignore more dice than were rolled keeps one (RULE 706.3 is a
    # rider on a real roll, never a no-roll)
    assert len(eng.rules.roll_die(p1, sides=6, count=2, ignore_lowest=5)) == 1


def test_doubles_flag_matches_rule_706_5():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.DICE_ROLLED else None
    )
    saw_true = saw_false = False
    for seed in range(60):
        eng.state.rng_seed = seed
        fired.clear()
        eng.rules.roll_die(p1, sides=2, count=2)
        d = fired[0].data
        assert d["doubles"] is (d["results"][0] == d["results"][1])
        saw_true |= d["doubles"]
        saw_false |= not d["doubles"]
    assert saw_true and saw_false  # both outcomes exercised

    fired.clear()
    eng.rules.roll_die(p1, sides=20, count=1)
    assert fired[0].data["doubles"] is False  # a single die is never doubles


# --- RollDieEffect + results table ---------------------------------------


def _ctx(eng):
    return eng.rules.context


def test_effect_stashes_result_on_context():
    eng = _engine()
    eng.state.rng_seed = 3
    src = _put(eng.state, Card(id="S", name="S", type_line="Enchantment"))
    RollDieEffect(sides=20).apply(_ctx(eng))
    assert _ctx(eng).die_result == _ctx(eng).die_results[0]
    assert 1 <= _ctx(eng).die_result <= 20


def test_results_table_runs_the_row_whose_range_contains_the_total():
    eng = _engine()
    src = _put(eng.state, Card(id="S", name="S", type_line="Enchantment"))
    p1 = eng.state.player_by_id("p1")
    # d2, two rows: 1 -> gain 3 life, 2+ -> gain 100 life. Force each result
    # by seeding, then assert the right branch ran.
    outcomes = [
        {"min": 1, "max": 1, "effects": [{"type": "gain_life", "params": {"amount": 3}}]},
        {"min": 2, "effects": [{"type": "gain_life", "params": {"amount": 100}}]},
    ]
    seen = set()
    for seed in range(40):
        eng.state.rng_seed = seed
        p1.life = 20
        RollDieEffect(sides=2, outcomes=outcomes).apply(_ctx(eng))
        rolled = _ctx(eng).die_result
        seen.add(rolled)
        assert p1.life == (23 if rolled == 1 else 120)
    assert seen == {1, 2}  # both branches were actually exercised


# --- advantage / disadvantage replacement -------------------------------


def test_pixie_guide_advantage_bumps_count_and_ignores_lowest():
    eng = _engine()
    eng.state.rng_seed = 11
    guide = _put(
        eng.state,
        Card(
            id="PG", name="Pixie Guide", type_line="Creature — Faerie",
            is_creature=True, power=1, toughness=3,
            oracle_text=(
                "Flying\nGrant an Advantage — If you would roll one or more "
                "dice, instead roll that many dice plus one and ignore the "
                "lowest roll."
            ),
        ),
    )
    assert parse_oracle(guide.card).coverage != UNMODELED

    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.DICE_ROLLED else None
    )
    kept = eng.rules.roll_die(eng.state.player_by_id("p1"), sides=20, count=1)
    # asked for one die; advantage → rolled two, kept the higher one
    assert len(fired[0].data["natural_results"]) == 2
    assert len(kept) == 1
    assert kept[0] == max(fired[0].data["natural_results"])


def test_advantage_only_helps_its_own_controller():
    eng = _engine()
    eng.state.rng_seed = 5
    _put(
        eng.state,
        Card(
            id="PG", name="Pixie Guide", type_line="Creature — Faerie",
            is_creature=True, power=1, toughness=3,
            oracle_text=(
                "Grant an Advantage — If you would roll one or more dice, "
                "instead roll that many dice plus one and ignore the lowest roll."
            ),
        ),
        controller="p1",
    )
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.DICE_ROLLED else None
    )
    eng.rules.roll_die(eng.state.player_by_id("p2"), sides=20, count=1)
    assert len(fired[0].data["natural_results"]) == 1  # opponent gets no advantage


# --- parser --------------------------------------------------------------


def test_bare_roll_clause_parses():
    assert match_clause("roll a d20") == [EffectSpec("roll_die", {"sides": 20})]
    assert match_clause("roll a 6-sided die") == [EffectSpec("roll_die", {"sides": 6})]
    assert match_clause("roll 2 d6") == [EffectSpec("roll_die", {"sides": 6, "count": 2})]
    assert match_clause("roll a die") is None  # RULE 706.1 needs a face count


def test_whenever_you_roll_trigger_condition():
    card = Card(
        id="RT", name="Roll Trigger", type_line="Enchantment",
        oracle_text="Whenever you roll one or more dice, draw a card.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    trig = next(s for s in result.specs if s.ability_kind == "triggered")
    assert trig.trigger["event"] == "DICE_ROLLED"
    assert [e.type for e in trig.effects] == ["draw"]


def test_contact_other_plane_modeled_with_results_table():
    card = _db().get_card("Contact Other Plane")
    assert card is not None
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    roll = next(e for s in result.specs for e in s.effects if e.type == "roll_die")
    outcomes = roll.params["outcomes"]
    assert [o["min"] for o in outcomes] == [1, 10, 20]
    assert outcomes[0]["max"] == 9 and outcomes[-1].get("max") == 20


def test_barbarian_class_and_pixie_guide_modeled():
    for name in ("Barbarian Class", "Pixie Guide"):
        card = _db().get_card(name)
        assert card is not None, name
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, name
        assert any(
            e.type == "roll_dice_modifier" for s in result.specs for e in s.effects
        ), name


def test_dice_table_row_that_wont_parse_fails_closed():
    # a synthetic d2 card whose second row body is gibberish → UNMODELED
    card = Card(
        id="X", name="Junk Die", type_line="Sorcery", is_sorcery=True,
        oracle_text="Roll a d2.\n1 | Draw a card.\n2 | Glorble the frobnicator.",
    )
    assert parse_oracle(card).coverage == UNMODELED


# --- Vrondiss end to end -----------------------------------------------


def test_vrondiss_dice_trigger_deals_self_damage():
    card = _db().get_card("Vrondiss, Rage of Ancients")
    assert card is not None
    eng = _engine()
    eng.state.rng_seed = 2
    vrondiss = _put(eng.state, card)
    assert any(
        a.trigger_event == "DICE_ROLLED" for a in vrondiss.triggered_abilities
    )

    eng.rules.roll_die(eng.state.player_by_id("p1"), sides=20)
    eng.rules.put_triggers_on_stack()  # RULE 603.3 — after the action
    # "you may have Vrondiss deal 1 damage to itself" — RULE 603.5 pauses on
    # the may; take it, then let the ability resolve.
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    assert vrondiss.damage_marked == 1  # 5/4 — survives the 1
