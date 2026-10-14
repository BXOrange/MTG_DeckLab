"""MEC-117 - "ignore one" flip / roll / planar-die replacements (RULE 705.3, 706).

Krark's Thumb (`flip 2 coins and ignore 1`), Krark's Other Thumb (`roll 2 of
those dice and ignore 1 of those results`) and Ichor Elixir (planar dice plus
1, ignore 1) all lower to the `ignore_one` replacement; the pre-events
`FLIP_COIN` / `ROLL_DICE` / `PLANAR_DIE_ROLL` carry the rewritten counts and
only the kept result is ever seen by triggers.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effects.registry import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

THUMB = "If you would flip a coin, instead flip two coins and ignore one."
OTHER_THUMB = "If you would roll a die, instead roll two of those dice and ignore one of those results."
ELIXIR = "If you would roll one or more planar dice, instead roll that many planar dice plus one and ignore one.\n{T}: Add {C}{C}."


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, name, text, controller="p1"):
    obj = GameObject(Card(id=name, name=name, type_line="Artifact", oracle_text=text), owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _spy(eng, wanted):
    seen = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == wanted else None)
    return seen


def _count_rng(eng):
    before = eng.state.rng_counter
    return lambda: eng.state.rng_counter - before


def test_real_cards_are_modeled():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Krark's Thumb", "Krark's Other Thumb", "Ichor Elixir"):
        assert parse_oracle(db.get_card(name)).coverage == MODELED, name


def test_unrelated_text_stays_unclaimed():
    card = Card(id="x", name="X", type_line="Artifact",
                oracle_text="If you would flip a coin, instead flip three coins and ignore one.")
    assert parse_oracle(card).coverage == UNMODELED


@pytest.mark.parametrize("thumbs,expected_flips", [(0, 1), (1, 2), (2, 4)])
def test_thumbs_stack_coin_flips(thumbs, expected_flips):
    eng = _engine()
    for i in range(thumbs):
        _put(eng, f"Krark's Thumb {i}", THUMB)
    used = _count_rng(eng)
    fired = _spy(eng, EventType.COIN_FLIP)
    eng.rules.coin_flip(eng.state.player_by_id("p1"))
    assert used() == expected_flips
    assert len(fired) == 1  # ignored flips never happened


def test_kept_result_is_a_win_when_any_flip_wins():
    wins = losses = 0
    for seed in range(200):
        eng = _engine()
        eng.state.rng_seed = seed
        _put(eng, "Krark's Thumb", THUMB)
        raw = _engine()
        raw.state.rng_seed = seed
        first, second = raw.rules.random_int(2) == 0, raw.rules.random_int(2) == 0
        won = eng.rules.coin_flip(eng.state.player_by_id("p1"))
        assert won == (first or second)
        wins += won
        losses += not won
    assert wins > losses  # 3/4 vs 1/4


def test_thumb_only_affects_its_controller():
    eng = _engine()
    _put(eng, "Krark's Thumb", THUMB, controller="p1")
    used = _count_rng(eng)
    eng.rules.coin_flip(eng.state.player_by_id("p2"))
    assert used() == 1


def test_coin_flip_effect_uses_kept_result():
    eng = _engine()
    _put(eng, "Krark's Thumb", THUMB)
    src = _put(eng, "Flipper", "")
    effect = EffectRegistry.create("coin_flip", {})
    effect.source = src
    ctx = GameContext(eng.state, eng.rules)
    eng.rules.context.acting_player_id = "p1"
    effect.apply(ctx)
    assert ctx.coin_outcome["wins"] + ctx.coin_outcome["losses"] == 1


@pytest.mark.parametrize("thumbs,group", [(0, 1), (1, 2), (2, 4)])
def test_other_thumb_rolls_groups_and_keeps_highest(thumbs, group):
    eng = _engine()
    for i in range(thumbs):
        _put(eng, f"Krark's Other Thumb {i}", OTHER_THUMB)
    fired = _spy(eng, EventType.DICE_ROLLED)
    kept = eng.rules.roll_die(eng.state.player_by_id("p1"), sides=20, count=1)
    natural = fired[0].data["natural_results"]
    assert len(natural) == group and len(kept) == 1
    assert kept[0] == max(natural)
    assert fired[0].data["die_result"] == kept[0]


def test_other_thumb_pairs_each_die_of_a_multi_die_roll():
    eng = _engine()
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    fired = _spy(eng, EventType.DICE_ROLLED)
    kept = eng.rules.roll_die(eng.state.player_by_id("p1"), sides=6, count=2)
    natural = fired[0].data["natural_results"]
    assert len(natural) == 4 and len(kept) == 2
    assert kept == [max(natural[0:2]), max(natural[2:4])]


def test_other_thumb_only_the_kept_die_fires_die_result():
    eng = _engine()
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    fired = _spy(eng, EventType.DIE_RESULT)
    eng.rules.roll_die(eng.state.player_by_id("p1"), sides=20, count=1)
    assert len(fired) == 1


def test_ichor_elixir_rolls_two_planar_dice_keeps_one():
    eng = _engine()
    _put(eng, "Ichor Elixir", ELIXIR)
    used = _count_rng(eng)
    fired = _spy(eng, EventType.PLANAR_DIE_ROLLED)
    face = eng.rules.roll_planar_die(eng.state.player_by_id("p1"))
    assert used() == 2 and len(fired) == 1
    assert face in ("chaos", "planeswalk", "blank")


# --- the roller's interactive pick (milestone 2) -----------------------------


from mtg_analyzer.game.rules_engine import RulesEngine  # noqa: E402
from mtg_analyzer.services.bot_policies.base import Bot  # noqa: E402
from mtg_analyzer.services.game_session import GameSession  # noqa: E402
from tests.support.game import make_engine  # noqa: E402


@pytest.fixture
def script_dice(monkeypatch):
    """``script_dice(3, 5)``: the next dice show these faces (``random_int`` is 0-based)."""
    real = RulesEngine.random_int
    queue: list[int] = []

    def fake(self, n):
        return queue.pop(0) - 1 if queue else real(self, n)

    monkeypatch.setattr(RulesEngine, "random_int", fake)

    def feed(*faces):
        queue[:] = list(faces)

    return feed


def _session():
    eng = make_engine(
        [Card(id=f"F{i}", name=f"F{i}", type_line="Land") for i in range(5)],
        [Card(id=f"G{i}", name=f"G{i}", type_line="Land") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return GameSession(eng)


def _cast_roller(session, text="Roll a d20. You gain life equal to the result."):
    eng = session.engine
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(Card(id="Roller", name="Roller", type_line="Sorcery", oracle_text=text, is_sorcery=True),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 10, "R": 5, "G": 5, "U": 5, "B": 5, "W": 5})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()


def _answer(session, label):
    pending = session.engine.state.pending_choice
    option = next(o for o in pending["options"] if o["label"] == str(label))
    session.apply_action({"type": "choose", "option_id": option["id"]})


def test_human_picks_the_low_die_and_the_low_result_is_used(script_dice):
    session = _session()
    eng = session.engine
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    fired = _spy(eng, EventType.DIE_RESULT)
    script_dice(15, 4)
    life = eng.state.player_by_id("p1").life
    _cast_roller(session)
    pending = eng.state.pending_choice
    assert pending["kind"] == "choose_die_group" and pending["player_id"] == "p1"
    assert sorted(o["label"] for o in pending["options"]) == ["15", "4"]  # the player sees every result
    assert not fired  # nothing announced before the pick
    _answer(session, 4)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert [e.data["natural_result"] for e in fired] == [4]  # only the kept die ever happened
    assert eng.state.player_by_id("p1").life == life + 4


def test_bot_takes_the_automatic_default_pick(script_dice):
    session = _session()
    eng = session.engine
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    script_dice(4, 15)
    life = eng.state.player_by_id("p1").life
    _cast_roller(session)
    answers = [a for a in session.legal_actions() if a["type"] in ("choose", "decline")]
    bot = Bot("p1")
    session.apply_action(bot.answer_choice({"pending_choice": eng.state.pending_choice}, answers))
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == life + 15  # highest die, the milestone-1 default


def test_bare_engine_keeps_the_automatic_pick(script_dice):
    eng = _engine()
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    script_dice(4, 15)
    assert eng.rules.roll_die(eng.state.player_by_id("p1"), sides=20, count=1) == [15]
    assert eng.state.pending_choice is None


def test_identical_dice_need_no_pick(script_dice):
    session = _session()
    eng = session.engine
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    script_dice(9, 9)
    life = eng.state.player_by_id("p1").life
    _cast_roller(session)
    assert eng.state.pending_choice is None
    assert eng.state.player_by_id("p1").life == life + 9


def test_each_die_of_a_multi_die_roll_is_its_own_pick(script_dice):
    session = _session()
    eng = session.engine
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    script_dice(2, 6, 1, 5)  # pair one: 2 / 6, pair two: 1 / 5
    life = eng.state.player_by_id("p1").life
    _cast_roller(session, "Roll two d6. You gain life equal to the result.")
    pending = eng.state.pending_choice
    assert pending["group"] == 0 and pending["groups"] == 2
    _answer(session, 2)
    pending = eng.state.pending_choice
    assert pending["group"] == 1 and sorted(o["label"] for o in pending["options"]) == ["1", "5"]
    _answer(session, 5)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == life + 2 + 5


def test_low_pick_selects_the_results_table_row(script_dice):
    session = _session()
    eng = session.engine
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    script_dice(18, 3)
    life = eng.state.player_by_id("p1").life
    _cast_roller(session, "Roll a d20.\n1-5 | You gain 7 life.\n6-20 | You lose 7 life.")
    _answer(session, 3)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == life + 7


def test_pending_pick_survives_undo_snapshot_flag(script_dice):
    session = _session()
    assert session.engine.state.interactive_roll_picks is True
    assert session.engine.state.clone().interactive_roll_picks is True


def test_ichor_elixir_human_chooses_the_planar_face(monkeypatch):
    session = _session()
    eng = session.engine
    _put(eng, "Ichor Elixir", ELIXIR)
    faces = iter(["blank", "chaos"])
    monkeypatch.setattr(RulesEngine, "random_choice", lambda self, options: next(faces))
    fired = _spy(eng, EventType.PLANAR_DIE_ROLLED)
    assert eng.rules.roll_planar_die(eng.state.player_by_id("p1")) is None
    pending = eng.state.pending_choice
    assert pending["kind"] == "choose_planar_face"
    assert [o["id"] for o in pending["options"]] == ["chaos", "blank"]  # default (chaos) first
    assert not fired
    session.apply_action({"type": "choose", "option_id": "blank"})  # the human prefers a blank
    assert [e.data["face"] for e in fired] == ["blank"]


def test_ichor_elixir_bot_default_is_chaos(monkeypatch):
    session = _session()
    eng = session.engine
    _put(eng, "Ichor Elixir", ELIXIR)
    faces = iter(["blank", "chaos"])
    monkeypatch.setattr(RulesEngine, "random_choice", lambda self, options: next(faces))
    fired = _spy(eng, EventType.PLANAR_DIE_ROLLED)
    eng.rules.roll_planar_die(eng.state.player_by_id("p1"))
    answers = [a for a in session.legal_actions() if a["type"] in ("choose", "decline")]
    session.apply_action(Bot("p1").answer_choice({"pending_choice": eng.state.pending_choice}, answers))
    assert [e.data["face"] for e in fired] == ["chaos"]
