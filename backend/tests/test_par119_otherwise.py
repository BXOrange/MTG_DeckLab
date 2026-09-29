"""PAR-119: optional targeted payments and the milled-land otherwise rider."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.targeting import spell_target_specs
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.support.game import creature, obj_on_battlefield


def _spell(state, name):
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.players[0].hand.append(obj)
    return obj


@pytest.mark.parametrize("name,paid,unpaid", [
    ("Insatiable Appetite", 5, 3), ("Pippin's Bravery", 4, 2),
])
@pytest.mark.parametrize("answer", ["pay", "decline", "unpayable"])
def test_food_pump_targets_original_spell_and_resolves_either_branch(name, paid, unpaid, answer):
    engine, state = _engine()
    player = state.players[0]
    state.current_phase = "precombat_main"
    state.current_step = "main1"
    target = obj_on_battlefield(state, engine, creature(), "p2")
    food = None
    if answer != "unpayable":
        food = obj_on_battlefield(state, engine, Card(id="food", name="Food", type_line="Artifact — Food"))
    spell = _spell(state, name)
    assert parse_oracle(spell.card).modeled
    assert [spec.kind for spec in spell_target_specs(spell)] == ["creature"]
    player.mana_pool.add("G", 2)
    player.mana_pool.add("C", 2)
    engine.cast_spell(player, spell, targets=[target])
    assert food is None or food.zone == Zone.BATTLEFIELD
    engine.resolve_until_stable()
    if answer != "unpayable":
        assert state.pending_choice["kind"] == "pay_cost_then"
        engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()
    assert state.pending_choice is None
    assert not state.stack and not engine.rules.pending_triggers
    assert target.power == target.toughness == 2 + (paid if answer == "pay" else unpaid)
    if food is not None:
        assert food.zone == (Zone.GRAVEYARD if answer == "pay" else Zone.BATTLEFIELD)
    assert spell.zone == Zone.GRAVEYARD


def test_food_payment_is_not_offered_if_original_target_is_illegal():
    engine, state = _engine()
    state.current_phase = "precombat_main"
    state.current_step = "main1"
    target = obj_on_battlefield(state, engine, creature(), "p2")
    food = obj_on_battlefield(state, engine, Card(id="food", name="Food", type_line="Artifact — Food"))
    spell = _spell(state, "Pippin's Bravery")
    state.players[0].mana_pool.add("G", 1)
    engine.cast_spell(state.players[0], spell, targets=[target])
    engine.rules.exile(target)
    engine.resolve_until_stable()
    assert state.pending_choice is None
    assert food.zone == Zone.BATTLEFIELD
    assert target.power == 2
    assert spell.zone == Zone.GRAVEYARD


def test_if_and_when_do_not_share_target_announcement():
    for link, field in [("if", "effects"), ("when", "then_trigger")]:
        specs = parse_effect_body(f"you may pay {{1}}. {link} you do, destroy target creature")
        assert specs[0].type == "pay_cost_then"
        assert field in specs[0].params
        assert specs[0].params[field][0]["params"]["target_kind"] == "creature"


@pytest.mark.parametrize("top,expected", [
    ("land", (21, 20)), ("nonland", (20, 19)), ("empty", (20, 19)),
])
@pytest.mark.parametrize("active", [0, 1])
def test_lorehold_excavation_branches_on_actual_mill_and_only_own_end_step(top, expected, active):
    engine, state = _engine()
    source = obj_on_battlefield(state, engine, _named("Lorehold Excavation"))
    bind_from_catalogue(source)
    assert parse_oracle(source.card).modeled
    if top != "empty":
        card = Card(id="top", name="Top", type_line="Land" if top == "land" else "Instant",
                    is_land=top == "land", is_instant=top == "nonland")
        state.players[0].library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    state.active_player_index = active
    state.current_phase = "ending"
    state.current_step = "end"
    state.fire_event(GameEvent("STEP_BEGIN", step="end", player_id=state.players[active].id))
    engine.resolve_until_stable()
    assert tuple(player.life for player in state.players) == (expected if active == 0 else (20, 20))
    assert len(state.players[0].graveyard) == int(active == 0 and top != "empty")
