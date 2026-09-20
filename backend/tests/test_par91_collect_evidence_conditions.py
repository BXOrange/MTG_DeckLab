"""PAR-91 — optional collect-evidence costs and their conditional riders."""

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_bite_down_on_crime_binds_optional_evidence_cost_and_discount():
    card = _db().get_card("Bite Down on Crime")
    result = parse_oracle(card)
    assert result.modeled
    cost, discount = result.specs[:2]
    assert cost.additional_cost == {"collect_evidence": 6}
    assert cost.additional_cost_optional is True
    assert discount.effects[0].params == {
        "affects": "self", "generic": 2,
        "active_if": {"kind": "flag", "flag": "additional_cost_paid"},
    }

    engine = _engine()
    source = GameObject(card, owner_id="p1", zone=Zone.HAND)
    source.controller_id = "p1"
    bind_from_catalogue(source)
    engine.state.player_by_id("p1").add_to_zone(source, Zone.HAND)
    base_cost = engine.effective_cast_cost(engine.state.player_by_id("p1"), source)
    source.additional_cost_paid = True
    reduced_cost = engine.effective_cast_cost(engine.state.player_by_id("p1"), source)
    assert reduced_cost.converted_mana_cost == base_cost.converted_mana_cost - 2


def test_lamplight_phoenix_returns_only_after_evidence_is_collected():
    engine = _engine()
    card = _db().get_card("Lamplight Phoenix")
    result = parse_oracle(card)
    assert result.modeled
    effect_spec = result.specs[1].effects[0]

    source = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    source.controller_id = "p1"
    evidence = GameObject(_db().get_card("Air Elemental"), owner_id="p1", zone=Zone.GRAVEYARD)
    player = engine.state.player_by_id("p1")
    player.add_to_zone(source, Zone.GRAVEYARD)
    player.add_to_zone(evidence, Zone.GRAVEYARD)
    _apply_effects_partitioned(build_effects([effect_spec], source), engine.rules.context,
                               None, None, source=source)
    assert source.zone == Zone.BATTLEFIELD and source.tapped is True
    assert evidence.zone == Zone.EXILE
