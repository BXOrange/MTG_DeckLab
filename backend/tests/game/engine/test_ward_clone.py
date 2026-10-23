"""Open Ward payments retain their resolution frame across clone/undo."""

import pytest

from mtg_analyzer.game.effects.core import DealDamageEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.services.game_session import GameSession
from tests.support.game import creature, instant, make_engine, obj_on_battlefield


def _pending_ward(*, cost="{3}", targets=1):
    engine = make_engine([], [], hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    caster = engine.state.active_player
    caster.mana_pool.add_many({"R": 1, "C": 8})
    warded = []
    for _ in range(targets):
        target = obj_on_battlefield(
            engine.state, engine, creature(power=7, toughness=7), controller="p2"
        )
        target.parametric_keywords = {"ward": {"cost": cost}}
        warded.append(target)
    spell = GameObject(instant(), owner_id=caster.id, zone=Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]
    caster.hand.append(spell)
    engine.cast_spell(caster, spell, targets=[warded[0]])
    if targets > 1:
        # A second targeted Ward permanent produces its own real Ward trigger.
        item = engine.state.stack[0]
        item.targets = warded
        item.target_incarnations = [target.zone_incarnation for target in warded]
        engine.state.stack[1:] = []
        engine.rules.check_ward(item, caster)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "ward"
    return engine, warded, spell


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_open_ward_clone_resumes_and_isolates_original(answer):
    original, targets, spell = _pending_ward()
    clone = GameEngine(original.state.clone())
    frame = clone.state.pending_ward
    original_frame = original.state.pending_ward
    assert frame["item"] is clone.state.stack[0]
    assert frame["item"] is not original_frame["item"]
    assert frame["cost"] is not original_frame["cost"]
    clone.resolve_pending_choice(answer)
    assert clone.state.pending_ward is None
    assert clone.state.find_object(targets[0].instance_id).damage_marked == (3 if answer == "pay" else 0)
    assert clone.state.player_by_id("p1").mana_pool.total() == (5 if answer == "pay" else 8)
    assert spell.instance_id in [obj.instance_id for obj in clone.state.player_by_id("p1").graveyard]
    assert original.state.pending_ward is original_frame
    assert original.state.pending_choice["kind"] == "ward"
    assert targets[0].damage_marked == 0
    assert original.state.player_by_id("p1").mana_pool.total() == 8
    # The original can still independently take the opposite branch.
    original.resolve_pending_choice("decline" if answer == "pay" else "pay")
    assert targets[0].damage_marked == (0 if answer == "pay" else 3)


def test_ward_clone_keeps_resolved_x_cost_after_board_changes():
    original, _, _ = _pending_ward(cost="Pay {X}, where X is the number of creatures you control.")
    clone = GameEngine(original.state.clone())
    assert clone.state.pending_ward["cost"].mana.resolved_value == 1
    obj_on_battlefield(clone.state, clone, creature(), controller="p2")
    clone.resolve_pending_choice("pay")
    assert clone.state.player_by_id("p1").mana_pool.total() == 7
    assert original.state.pending_ward["cost"].mana.resolved_value == 1


@pytest.mark.parametrize("answer", ["pay", "decline"])
@pytest.mark.parametrize("replacement", [False, True])
def test_stale_ward_item_never_charges_or_counters_replacement(answer, replacement):
    original, _, _ = _pending_ward()
    clone = GameEngine(original.state.clone())
    item = clone.state.stack.pop()
    if replacement:
        # Even the same spell object/stack ID must not redirect the old frame.
        new_item = StackItem("spell", item.controller_id, obj=item.obj)
        new_item.stack_id = item.stack_id
        clone.state.stack.append(new_item)
    clone.rules.resolve_choice(answer)
    assert clone.state.pending_ward is None
    assert clone.state.player_by_id("p1").mana_pool.total() == 8
    assert clone.state.stack == ([new_item] if replacement else [])


@pytest.mark.parametrize("answers", [("pay", "pay"), ("pay", "decline"), ("decline",)])
def test_multiple_wards_continue_after_cloning_open_prompt(answers):
    original, targets, _ = _pending_ward(cost="{2}", targets=2)
    clone = GameEngine(original.state.clone())
    for answer in answers:
        assert clone.state.pending_choice["kind"] == "ward"
        clone.resolve_pending_choice(answer)
    assert clone.state.pending_choice is None
    assert clone.state.pending_ward is None
    assert not clone.state.stack
    assert clone.state.player_by_id("p1").mana_pool.total() == 8 - 2 * answers.count("pay")
    assert clone.state.find_object(targets[0].instance_id).damage_marked == (3 if answers == ("pay", "pay") else 0)
    assert original.state.pending_choice["kind"] == "ward"


@pytest.mark.parametrize("first", ["pay", "decline"])
def test_session_rewind_open_ward_then_choose_other_answer(first):
    engine, targets, _ = _pending_ward()
    session = GameSession(engine)
    session.apply_action({"type": "choose", "option_id": first})
    session.rewind(1)
    assert session.engine.state.pending_choice["kind"] == "ward"
    assert session.engine.state.pending_ward["item"] is session.engine.state.stack[0]
    second = "decline" if first == "pay" else "pay"
    session.apply_action({"type": "choose", "option_id": second})
    assert session.engine.state.pending_ward is None
    assert session.engine.state.find_object(targets[0].instance_id).damage_marked == (3 if second == "pay" else 0)
    assert session.engine.state.player_by_id("p1").mana_pool.total() == (5 if second == "pay" else 8)
