"""Real gameplay for Golgari Brownscale and Dredging Claw."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, card, cast, filler, game


def test_brownscale_raised_from_graveyard_gains_two_life():
    engine = game()
    brownscale = card(engine, "Golgari Brownscale", zone=Zone.GRAVEYARD)
    spell = card(engine, "Raise Dead", zone=Zone.HAND)
    a, b = specs_for(brownscale.card), specs_for(brownscale.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cast(engine, spell, targets=[brownscale])
    assert brownscale.zone == Zone.HAND and engine.state.player_by_id("p1").life == 22


def test_brownscale_dredge_mills_two_returns_it_and_triggers_life_gain():
    engine = game()
    player = engine.state.player_by_id("p1")
    brownscale = card(engine, "Golgari Brownscale", zone=Zone.GRAVEYARD)
    engine.state.resync_graveyard_watch()
    size = len(player.library)
    engine.rules.draw(player)
    assert engine.state.pending_choice["kind"] == "dredge"
    engine.resolve_pending_choice(str(brownscale.instance_id))
    engine.resolve_until_stable()
    assert len(player.library) == size - 2 and brownscale in player.hand
    assert player.life == 22


@pytest.mark.parametrize("origin", [Zone.BATTLEFIELD, Zone.EXILE])
def test_brownscale_does_not_gain_life_when_returned_from_another_zone(origin):
    engine = game()
    brownscale = card(engine, "Golgari Brownscale", zone=origin)
    engine.rules.return_to_hand(brownscale)
    engine.resolve_until_stable()
    assert brownscale.zone == Zone.HAND and engine.state.player_by_id("p1").life == 20


def test_brownscale_return_trigger_survives_clone_and_only_gains_life_for_its_owner():
    engine = game()
    brownscale = card(engine, "Golgari Brownscale", player="p2", zone=Zone.GRAVEYARD)
    engine.state.resync_graveyard_watch()
    with engine.state.simultaneous():
        engine.rules.return_to_hand(brownscale)
    engine.rules.put_triggers_on_stack()
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.player_by_id("p2").life == 22
    assert clone.state.player_by_id("p1").life == 20
    assert engine.state.player_by_id("p2").life == 20


def _claw_entry(owner="p1", controller="p1", type_line="Creature — Bear"):
    engine = game()
    claw = card(engine, "Dredging Claw")
    creature = filler(engine, "Returning", player=owner, type_line=type_line,
                      power=2 if "Creature" in type_line else None,
                      toughness=2 if "Creature" in type_line else None, zone=Zone.GRAVEYARD)
    engine.rules.return_from_graveyard(creature, controller_id=controller)
    engine.resolve_until_stable()
    return engine, claw, creature


@pytest.mark.parametrize("controller", ["p1", "p2"])
def test_claw_attaches_to_creature_from_your_graveyard_even_under_opponents_control(controller):
    engine, claw, creature = _claw_entry(controller=controller)
    a, b = specs_for(claw.card), specs_for(claw.card)
    assert a[0] is not b[0]
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target" and choice["player_id"] == "p1"
    engine.resolve_pending_choice("do")
    engine.resolve_until_stable()
    assert claw.attached_to == creature.instance_id
    assert creature.power == 3 and creature.toughness == 2 and combat.has(creature, "menace")


def test_claw_may_decline_attachment():
    engine, claw, creature = _claw_entry()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert claw.attached_to is None and creature.power == 2


@pytest.mark.parametrize("owner,controller,type_line", [
    ("p2", "p1", "Creature — Bear"), ("p1", "p1", "Artifact"),
])
def test_claw_ignores_opponents_graveyard_and_noncreature_entry(owner, controller, type_line):
    engine, claw, creature = _claw_entry(owner, controller, type_line)
    assert not engine.state.pending_choice and claw.attached_to is None


def test_claw_normal_equip_still_pays_one_black_and_one_generic():
    engine = game()
    claw = card(engine, "Dredging Claw")
    creature = filler(engine, "Host", power=2, toughness=2)
    player = engine.state.player_by_id("p1")
    player.mana_pool.add_many({"B": 1, "C": 1})
    activate(engine, claw, targets=[creature])
    assert claw.attached_to == creature.instance_id and player.mana_pool.total() == 0
    assert creature.power == 3 and combat.has(creature, "menace")


def test_claw_does_not_trigger_when_creature_is_cast_from_hand():
    engine = game()
    claw = card(engine, "Dredging Claw")
    creature = card(engine, "Grizzly Bears", zone=Zone.HAND)
    cast(engine, creature)
    assert not engine.state.pending_choice and claw.attached_to is None


def test_claw_attachment_is_untargeted_and_choice_survives_clone():
    engine, claw, creature = _claw_entry()
    creature.temp_keywords.add("shroud")
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("do")
    clone.resolve_until_stable()
    assert clone.state.find_object(claw.instance_id).attached_to == creature.instance_id
    assert claw.attached_to is None
