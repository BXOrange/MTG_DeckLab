"""PAR-117 — Torment of Venom's prior-target-controller payment clause."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
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


def test_torment_of_venom_is_modeled_with_a_prior_target_controller_cost():
    result = parse_oracle(_card("Torment of Venom"))
    assert result.modeled, result.unclaimed
    effects = result.specs[0].effects
    assert [effect.type for effect in effects] == ["add_counters", "pay_cost_then"]
    assert effects[1].params["payer"] == "previous_target_controller"
    assert effects[1].params["sacrifice_or_discard"] is True


def test_torment_declining_cost_loses_life_for_the_target_creatures_controller():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1, p2 = eng.state.players
    torment = _in_hand(eng, "Torment of Venom", p1.id)
    victim = GameObject(
        Card(id="victim", name="Victim", type_line="Creature — Human", is_creature=True,
             power=4, toughness=4),
        owner_id=p2.id, zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = p2.id
    eng.state.add_to_battlefield(victim)
    # A card in hand makes the printed sacrifice-or-discard cost payable,
    # therefore a real decline choice opens instead of auto-taking damage.
    retained = _in_hand(eng, "Opt", p2.id)
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.state.active_player_index = 0
    p1.mana_pool.add_many({"B": 2, "C": 2})

    eng.cast_spell(p1, torment, targets=[victim])
    eng.resolve_until_stable()
    assert victim.counters.get("-1/-1") == 3
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == p2.id

    eng.resolve_pending_choice("decline")
    assert p2.life == 17
    assert retained in p2.hand
