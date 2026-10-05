"""PAR-119: entry origins describe the actual move, not the casting origin."""

import ast
from pathlib import Path

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from tests.support.game import creature
from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par120_count_phrase import _put


@pytest.mark.parametrize("subject", ["~", "a creature you control", "another nontoken creature"])
@pytest.mark.parametrize("origin", ["a graveyard", "exile"])
def test_composed_entry_origin(subject, origin):
    head = parse_object_trigger_head(f"{subject} enters from {origin}")
    assert head.event == "ENTERS_BATTLEFIELD"
    assert head.trigger["filter"] == {"from_zone": origin.removeprefix("a ")}


@pytest.mark.parametrize("head", [
    "a creature dies from exile", "a creature enters from mars",
    "a creature enters from a graveyard from exile",
])
def test_invalid_origins_fail_closed(head):
    assert parse_object_trigger_head(head) is None


@pytest.mark.parametrize("origin", [Zone.GRAVEYARD, Zone.EXILE, Zone.LIBRARY, Zone.HAND])
def test_entry_scope_fires_only_for_the_actual_origin(origin):
    engine, state = _engine()
    _put(state, "Whenever a creature enters from a graveyard, you gain 1 life.",
         name="Graveyard watcher", types="Enchantment")
    _put(state, "Whenever a creature enters from exile, you gain 2 life.",
         name="Exile watcher", types="Enchantment")
    entrant = GameObject(creature(), owner_id="p1", zone=origin)
    state.players[0].add_to_zone(entrant, origin)
    if origin == Zone.GRAVEYARD:
        engine.rules.return_from_graveyard(entrant)
    else:
        state.players[0].remove_from_zone(entrant, origin)
        engine.rules._put_searched_card(state.players[0], entrant, "battlefield")
    event = next(event for event in reversed(state.event_log) if event.type == EventType.ENTERS_BATTLEFIELD)
    assert event.get("from_zone") == origin.value
    engine.resolve_until_stable()
    assert state.players[0].life == 20 + {Zone.GRAVEYARD: 1, Zone.EXILE: 2}.get(origin, 0)


def test_blink_reads_exile_and_self_reanimation_reads_graveyard():
    engine, state = _engine()
    card = creature(name="Returning creature", oracle_text=(
        "When this creature enters from a graveyard, you gain 1 life.\n"
        "When this creature enters from exile, you gain 2 life."
    ))
    assert parse_oracle(card).modeled
    entrant = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(entrant)
    state.players[0].graveyard.append(entrant)
    engine.rules.return_from_graveyard(entrant)
    engine.resolve_until_stable()
    assert state.players[0].life == 21
    engine.rules.blink(entrant)
    engine.resolve_until_stable()
    assert state.players[0].life == 23


def test_cast_from_graveyard_enters_from_stack_not_graveyard():
    engine, state = _engine()
    state.current_phase = "precombat_main"
    state.current_step = "main1"
    _put(state, "Whenever a creature enters from a graveyard, you gain 1 life.",
         name="Watcher", types="Enchantment")
    entrant = GameObject(creature(cost="{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    player = state.players[0]
    player.graveyard.append(entrant)
    player.graveyard_play_permission_until_turn = state.turn_nr
    player.mana_pool.add("G", 1)
    engine.cast_spell(player, entrant)
    engine.resolve_until_stable()
    assert entrant.zone == Zone.BATTLEFIELD
    assert player.life == 20
    assert next(event for event in reversed(state.event_log)
                if event.type == EventType.ENTERS_BATTLEFIELD).get("from_zone") == "stack"


def test_every_entry_emitter_explicitly_supplies_an_origin():
    # An AST guard covers uncommon entry paths too (ninjutsu, discard
    # replacement, commander entry, revealed-card moves, token creation).
    game = Path(__file__).parents[1] / "mtg_analyzer" / "game"
    emitters = []
    for path in game.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            event = node.args[0]
            if (isinstance(node.func, ast.Name) and node.func.id == "GameEvent"
                    and isinstance(event, ast.Attribute) and event.attr == "ENTERS_BATTLEFIELD"):
                emitters.append((path, node.lineno))
                assert "from_zone" in {keyword.arg for keyword in node.keywords}, (path, node.lineno)
    assert emitters
