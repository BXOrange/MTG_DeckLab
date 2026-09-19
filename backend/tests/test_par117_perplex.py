"""PAR-117 — Perplex's non-mana counterspell tax."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None, f"{name!r} missing from local card cache"
    return card


def _in_hand(engine, name: str, player_id: str) -> GameObject:
    obj = GameObject(_card(name), owner_id=player_id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player_id).hand.append(obj)
    return obj


def test_perplex_is_modeled_as_a_targeted_counter_with_discard_hand_cost():
    result = parse_oracle(_card("Perplex"))
    assert result.modeled, result.unclaimed
    spec = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spec.effects[0].type == "counter_unless_pay"
    assert spec.effects[0].params == {"cost": "discard your hand", "target_kind": "spell"}


def test_perplex_target_controller_can_discard_their_hand_to_save_spell():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1, p2 = eng.state.players
    bolt = _in_hand(eng, "Lightning Bolt", p2.id)
    retained = _in_hand(eng, "Opt", p2.id)
    perplex = _in_hand(eng, "Perplex", p1.id)
    p2.mana_pool.add("R", 1)
    p1.mana_pool.add_many({"U": 1, "B": 1, "C": 1})

    eng.cast_spell(p2, bolt, targets=[p1])
    target_spell = eng.state.stack[-1]
    eng.cast_spell(p1, perplex, targets=[target_spell])
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "ward"
    eng.resolve_pending_choice("pay")
    assert p2.hand == []  # includes every card then in hand, not merely one.
    assert retained in p2.graveyard

    eng.resolve_until_stable()
    assert bolt in p2.graveyard  # saved spell resolves, then goes to its owner's graveyard
    assert p1.life == 17
