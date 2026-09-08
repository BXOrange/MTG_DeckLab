"""Secrets of Strixhaven — playability batch, wave 10.

Wave 10: two modal-mode sub-clauses that were blocking Prismari Command.
- "target player creates a <named> token" — `CreateTokenEffect.
  creators="target"` + a player `target_kind`.
- "target player draws N cards, then discards M cards" —
  `handlers._TARGET_PLAYER_LOOT_RE` emits the `previous_subject` discard link.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_prismari_command_fully_modeled():
    r = parse_oracle(_db().get_card("Prismari Command"))
    assert r.coverage != UNMODELED, r.unclaimed
    modes = [s for s in r.specs if s.modes][0].modes
    opt_types = [[e.type for e in opt] for opt in modes["options"]]
    assert ["draw", "discard"] in opt_types
    assert ["create_token"] in opt_types


def test_target_player_loot_clause():
    specs = match_clause("target player draws 2 cards, then discards 2 cards")
    assert specs[0].type == "draw" and specs[0].params["target_kind"] == "player"
    assert specs[1].type == "discard"
    assert specs[1].params["previous_subject"] is True
    assert specs[1].params["count"] == 2


def test_target_player_creates_named_token_clause():
    specs = match_clause("target player creates a treasure token")
    assert specs == [type(specs[0])("create_token", {
        "count": 1, "token_name": "Treasure", "creators": "target", "target_kind": "player",
    })]


def test_each_opponent_creates_named_token_clause():
    specs = match_clause("each opponent creates a clue token")
    assert specs[0].params.get("creators") == "each_opponent"


def test_target_creator_makes_token_for_chosen_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    src = GameObject(Card(id="s", name="S", type_line="Instant", is_instant=True),
                     owner_id=p1.id, zone=Zone.STACK)
    eff = EffectRegistry.create(
        "create_token", {"token_name": "Treasure", "creators": "target", "target_kind": "player"}
    )
    eff.source = src
    eff.apply(eng.rules.context, targets=[p2])
    treasures = [o for o in eng.state.battlefield
                 if getattr(o, "is_token", False) and "Treasure" in (o.name or "")]
    assert len(treasures) == 1
    assert treasures[0].controller_id == p2.id
