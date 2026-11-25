"""BUG-88 / RULE 115.1 + 102.3: "target opponent <verb>" announces an *opponent*, never any player.

The older sacrifice edict row emitted `target_kind: player` for "target opponent sacrifices ...", so the caster could
target themselves (Tribute to Hunger). The shared grammar now carries the opponent restriction; the full-cache guard
proves no MODELED card keeps an unrestricted player target for a "target opponent" clause."""
import re

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.engine.casting_mixin import spell_target_specs
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

from test_mec171_reflexive_referents import make, to_hand

from mtg_analyzer.game.game_engine import GameEngine

TRIBUTE = "Target opponent sacrifices a creature of their choice. You gain life equal to that creature's toughness."
# Flare of Malice-shaped greatest-mana-value edict (second row that emitted `player`).
GREATEST = "Target opponent sacrifices a creature with the greatest power among creatures they control."


def board(players=2):
    eng = GameEngine.new_game([(f"p{i + 1}", f"P{i + 1}", [make("Filler")] * 3) for i in range(players)],
                              starting_life=20, starting_hand=0)
    eng.begin_turn()
    return eng, eng.state.active_player


def offered_players(oracle, players=2):
    eng, p1 = board(players)
    spell = to_hand(p1, make("Tribute to Hunger", "Instant", "{2}{B}", oracle=oracle, is_instant=True))
    assert parse_oracle(spell.card).modeled
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(spell)
    (spec,) = spell_target_specs(spell)
    return {o["player_id"] for o in legal_targets(eng.state, p1.id, spec, source=spell)}


OTHER_ROWS = [
    "Target opponent draws a card.",
    "Target opponent exiles two cards from their hand.",
    "Exchange life totals with target opponent.",
    "Target opponent sacrifices a creature of their choice. If they can't, they lose 2 life.",
]


@pytest.mark.parametrize("oracle", OTHER_ROWS)
def test_every_target_opponent_row_excludes_the_caster(oracle):
    assert offered_players(oracle) == {"p2"}
    assert offered_players(oracle, players=3) == {"p2", "p3"}


@pytest.mark.parametrize("oracle", [TRIBUTE, GREATEST])
def test_two_player_edict_offers_only_the_opponent(oracle):
    assert offered_players(oracle) == {"p2"}


@pytest.mark.parametrize("oracle", [TRIBUTE, GREATEST])
def test_three_player_edict_offers_either_opponent_not_the_caster(oracle):
    assert offered_players(oracle, players=3) == {"p2", "p3"}


@pytest.mark.parametrize("oracle", ["Target player sacrifices a creature of their choice."])
def test_target_player_edict_still_offers_everyone(oracle):
    assert offered_players(oracle) == {"p1", "p2"}


FULL_CACHE_TIMEOUT_SECONDS = 600
_TARGET_OPPONENT = re.compile(r"\btarget opponent\b(?!'s)")


def _own_effects(effects):
    """Effects an ability announces itself: its own list, `seq` members and mode options. Nested referent / rider
    effects (`trigger_subject_referent`, `unable_effects`, villainous options) name an already-chosen player, not a
    target."""
    for e in effects:
        yield e
        if e["type"] == "seq":
            yield from _own_effects(e["params"].get("effects", []))


def _unrestricted_player_targets(spec):
    effects = list(_own_effects([e.to_dict() for e in spec.effects or []]))
    for option in (spec.modes["options"] if spec.modes else []):
        effects += list(_own_effects([e.to_dict() if hasattr(e, "to_dict") else e for e in option]))
    return [e["type"] for e in effects if e["params"].get("target_kind") == "player"]


@pytest.mark.full_cache
@pytest.mark.timeout(FULL_CACHE_TIMEOUT_SECONDS)
def test_no_modeled_card_with_a_target_opponent_clause_emits_an_unrestricted_player_target():
    offenders = {}
    for card in CardDatabase(DB_PATH).list_cards():
        text = (card.oracle_text or "").lower()
        if "target opponent" not in text or "target player" in text:
            continue  # a card that also says "target player" legitimately carries a player target
        result = parse_oracle(card)
        if not result.modeled:
            continue
        bad = [t for spec in result.specs for t in _unrestricted_player_targets(spec)]
        if bad:
            offenders[card.name] = bad
    assert not offenders, offenders
