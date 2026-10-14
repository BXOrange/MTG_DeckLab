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
