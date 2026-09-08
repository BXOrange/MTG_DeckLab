"""A triggered ability's own target, chosen interactively (RULE 115 / 603.3c).

Follow-up to the `become_copy` work: `put_triggers_on_stack` used to place a
`TriggeredAbility` on the stack with no `targets` at all, so any targeting
trigger (`become_copy`, or a parsed "when ~ enters, destroy target creature")
silently no-op'd. This is the fix: a target-needing trigger now opens a
`trigger_target` `pending_choice` (mirroring search/cascade/discover/
order_triggers) instead of resolving blind.
"""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import CounterSpellEffect, DestroyEffect, TriggeredAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSessionManager


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def creature(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _destroy_trigger(source, optional=False):
    return TriggeredAbility(
        trigger_event=EventType.DRAW,
        effects=[DestroyEffect(source=source)],
        controller_id=source.controller_id,
        source=source,
        optional=optional,
        description="destroy target permanent",
    )


def test_targeting_trigger_opens_a_pending_choice_instead_of_resolving_blind():
    eng = make_engine()
    eng.begin_turn()
    victim = put(eng.state, creature("Victim"))
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_destroy_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    assert not eng.state.stack  # not placed yet — awaiting the target
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    ids = {o.get("instance_id") for o in choice["options"]}
    assert victim.instance_id in ids
    assert source.instance_id not in ids  # a permanent can't target itself


def test_choosing_a_target_places_the_trigger_and_it_resolves():
    eng = make_engine()
    eng.begin_turn()
    victim = put(eng.state, creature("Victim"))
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_destroy_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    victim_option = next(o for o in choice["options"] if o["instance_id"] == victim.instance_id)

    eng.rules.resolve_trigger_target_choice(victim_option["id"])
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1
    assert eng.state.stack[0].targets == [victim]

    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield  # destroyed
    assert source in eng.state.battlefield


def test_declining_an_optional_targeting_trigger_never_places_it():
    eng = make_engine()
    eng.begin_turn()
    victim = put(eng.state, creature("Victim"))
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_destroy_trigger(source, optional=True), None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert any(o["id"] == "decline" for o in choice["options"])

    eng.rules.resolve_trigger_target_choice("decline")
    assert eng.state.pending_choice is None
    assert not eng.state.stack
    eng.resolve_until_stable()
    assert victim in eng.state.battlefield  # never happened


def test_mandatory_targeting_trigger_with_no_legal_target_is_dropped():
    # RULE 603.3c: a required target with nothing legal never goes on the
    # stack at all — it doesn't linger as a pending choice either.
    eng = make_engine()
    eng.begin_turn()
    source = put(eng.state, creature("Lone Source"))

    # "target spell" with nothing on the stack: zero legal options.
    trigger = TriggeredAbility(
        trigger_event=EventType.DRAW,
        effects=[CounterSpellEffect(source=source)],
        controller_id="p1", source=source,
        description="counter target spell",
    )
    assert not eng.state.stack  # nothing to target

    eng.rules.pending_triggers = [(trigger, None)]
    eng.rules.put_triggers_on_stack()

    assert eng.state.pending_choice is None
    assert not eng.state.stack


def test_non_targeting_triggers_are_unaffected():
    # The overwhelming common case (draw/create_token/etc. triggers) must
    # keep placing immediately, exactly as before this change.
    eng = make_engine()
    eng.begin_turn()
    source = put(eng.state, creature("Source"))
    trigger = TriggeredAbility(
        trigger_event=EventType.DRAW, effects=[], controller_id="p1",
        source=source, description="no target",
    )
    eng.rules.pending_triggers = [(trigger, None)]
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1


def _optional_no_target_trigger(source):
    return TriggeredAbility(
        trigger_event=EventType.DRAW, effects=[], controller_id="p1",
        source=source, optional=True, description="you may do a thing",
    )


def test_optional_targetless_trigger_opens_a_do_or_decline_choice():
    # RULE 603.5: even a "you may" with nothing to target must offer the
    # choice of whether to do it at all — it can't just always happen.
    eng = make_engine()
    eng.begin_turn()
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_optional_no_target_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    assert not eng.state.stack
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    assert {o["id"] for o in choice["options"]} == {"do", "decline"}


def test_optional_targetless_trigger_do_places_it():
    eng = make_engine()
    eng.begin_turn()
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_optional_no_target_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_target_choice("do")

    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1


def test_optional_targetless_trigger_decline_skips_it():
    eng = make_engine()
    eng.begin_turn()
    source = put(eng.state, creature("Source"))

    eng.rules.pending_triggers = [(_optional_no_target_trigger(source), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_target_choice("decline")

    assert eng.state.pending_choice is None
    assert not eng.state.stack


def test_become_copy_end_to_end_through_the_session_choice_api():
    # The real payoff: Clever Impersonator's "enter as a copy" choice is
    # genuinely interactively playable, through real RULE 614.1c/614.12
    # replacement timing (not the old ENTERS_BATTLEFIELD-trigger modeling) —
    # answered through the same generic choose/decline session path as
    # search/cascade/discover.
    impersonator_card = Card(id="CI", name="Clever Impersonator",
                              type_line="Creature — Illusion",
                              mana_cost_string="{5}{U}{U}", converted_mana_cost=7,
                              is_creature=True, power=3, toughness=3)  # real printed stats
    mgr = GameSessionManager()
    session = mgr.create_goldfish(library=[impersonator_card], starting_hand=1)
    session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
    state = session.engine.state
    state.current_step = "main1"

    target = put(state, creature("Grave Titan", power=6, toughness=6))
    p1 = state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 5})
    impersonator = p1.hand[0]

    session.apply_action({"type": "cast_spell", "instance_id": impersonator.instance_id})
    session.apply_action({"type": "pass_priority"})

    choice = state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    assert impersonator not in state.battlefield  # paused before entering as itself
    opt = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    session.apply_action({"type": "choose", "option_id": opt["id"]})

    assert impersonator in state.battlefield
    assert impersonator.card.name == "Grave Titan"
    assert (impersonator.power, impersonator.toughness) == (6, 6)
