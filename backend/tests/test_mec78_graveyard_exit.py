"""MEC-78 — RULE 603.3f batch triggers for cards leaving graveyards."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine_with_quintorius():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    p1 = eng.state.players[0]
    quintorius = GameObject(_db().get_card("Quintorius, Field Historian"), p1.id, Zone.BATTLEFIELD)
    quintorius.controller_id = p1.id
    eng.state.add_to_battlefield(quintorius)
    bind_from_catalogue(quintorius)
    return eng, p1


def _graveyard_card(eng, player, name):
    card = GameObject(_db().get_card(name), player.id, Zone.GRAVEYARD)
    player.graveyard.append(card)
    return card


def test_quintorius_is_modeled_as_a_graveyard_exit_batch_trigger():
    parsed = parse_oracle(_db().get_card("Quintorius, Field Historian"))
    assert parsed.coverage != UNMODELED
    trigger = next(spec.trigger for spec in parsed.specs if spec.ability_kind == "triggered")
    assert trigger == {"event": "CARDS_LEFT_GRAVEYARD", "graveyard_owner": "you"}


def test_single_graveyard_exit_triggers_quintorius_once():
    eng, p1 = _engine_with_quintorius()
    card = _graveyard_card(eng, p1, "Lightning Bolt")
    eng.rules.return_from_graveyard(card, "hand")
    eng.resolve_until_stable()
    spirits = [o for o in eng.state.battlefield if o.name == "Spirit"]
    assert len(spirits) == 1


def test_mass_graveyard_exit_is_one_batch_trigger():
    eng, p1 = _engine_with_quintorius()
    first = _graveyard_card(eng, p1, "Lightning Bolt")
    second = _graveyard_card(eng, p1, "Opt")
    with eng.rules.graveyard_exit_batch():
        eng.rules.return_from_graveyard(first, "hand")
        eng.rules.return_from_graveyard(second, "hand")
    events = [e for e in eng.state.event_log if e.type == "CARDS_LEFT_GRAVEYARD"]
    assert len(events) == 1
    assert [c["instance_id"] for c in events[0]["cards"]] == [first.instance_id, second.instance_id]
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.name == "Spirit"]) == 1
