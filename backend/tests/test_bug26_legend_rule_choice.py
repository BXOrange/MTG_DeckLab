"""BUG-26: RULE 704.5j -- the legendary permanents' controller chooses which copy survives.

The choice is a resumable `legend_rule` pending choice per conflicting group (APNAP, RULE 101.4);
the sweep applies nothing until every group is answered, then the chosen departures land in the
same RULE 704.3 batch as every other state-based action.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.bot_policies.base import Bot
from mtg_analyzer.services.game_session import GameSession


def _legend(name: str) -> Card:
    return Card(id=name, name=name, type_line="Legendary Creature — Bear", is_creature=True,
                is_legendary=True, power=2, toughness=2)


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card: Card, controller: str) -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _names(eng, name: str) -> list[GameObject]:
    return [o for o in eng.state.battlefield if o.name == name]


def test_controller_keeps_the_later_copy_with_more_counters():
    eng = _engine()
    first = _put(eng, _legend("Lg"), "p1")
    second = _put(eng, _legend("Lg"), "p1")
    second.add_counters("+1/+1", 2)

    eng.rules.check_state_based_actions()

    choice = eng.state.pending_choice
    assert choice["kind"] == "legend_rule" and choice["player_id"] == "p1"
    assert {o["instance_id"] for o in choice["options"]} == {first.instance_id, second.instance_id}
    assert _names(eng, "Lg") == [first, second], "nothing is applied while the choice is open"

    eng.resolve_pending_choice(str(second.instance_id))

    assert _names(eng, "Lg") == [second]
    assert eng.state.legend_rule_picks == {}
    assert eng.state.pending_choice is None


def test_two_groups_for_two_players_are_asked_in_apnap_order():
    eng = _engine()
    a1, a2 = _put(eng, _legend("A"), "p1"), _put(eng, _legend("A"), "p1")
    b1, b2 = _put(eng, _legend("B"), "p2"), _put(eng, _legend("B"), "p2")

    eng.rules.check_state_based_actions()
    assert eng.state.active_player.id == "p1"
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(a2.instance_id))

    # Nothing left the battlefield yet: the second player's group is still open.
    assert eng.state.pending_choice["player_id"] == "p2"
    assert len(eng.state.battlefield) == 4
    eng.resolve_pending_choice(str(b1.instance_id))

    assert _names(eng, "A") == [a2] and _names(eng, "B") == [b1]
    del a1, b2


def test_legend_choice_and_zero_toughness_death_apply_as_one_batch():
    eng = _engine()
    first, second = _put(eng, _legend("Lg"), "p1"), _put(eng, _legend("Lg"), "p1")
    doomed = _put(eng, Card(id="D", name="D", type_line="Creature — Bear", is_creature=True,
                            power=0, toughness=1), "p1")
    doomed.add_counters("-1/-1", 1)

    eng.rules.check_state_based_actions()
    assert doomed in eng.state.battlefield, "the zero-toughness death waits for the whole batch"
    eng.resolve_pending_choice(str(second.instance_id))

    assert _names(eng, "Lg") == [second] and doomed not in eng.state.battlefield
    assert first.zone == Zone.GRAVEYARD and doomed.zone == Zone.GRAVEYARD


def test_a_copy_another_action_removes_needs_no_choice():
    eng = _engine()
    first, second = _put(eng, _legend("Lg"), "p1"), _put(eng, _legend("Lg"), "p1")
    first.add_counters("-1/-1", 2)  # toughness 0: RULE 704.5f removes it anyway

    eng.rules.check_state_based_actions()

    assert eng.state.pending_choice is None
    assert _names(eng, "Lg") == [second]


def test_clone_while_the_choice_is_open_keeps_choice_and_answered_picks():
    eng = _engine()
    a1, a2 = _put(eng, _legend("A"), "p1"), _put(eng, _legend("A"), "p1")
    b1, b2 = _put(eng, _legend("B"), "p2"), _put(eng, _legend("B"), "p2")
    eng.rules.check_state_based_actions()
    eng.resolve_pending_choice(str(a2.instance_id))  # p1 answered, p2 pending

    restored = GameEngine(eng.state.clone())
    assert restored.state.pending_choice["kind"] == "legend_rule"
    assert restored.state.legend_rule_picks == {f"p1\x1fA": a2.instance_id}
    restored.resolve_pending_choice(str(b2.instance_id))

    assert [o.instance_id for o in _names(restored, "A")] == [a2.instance_id]
    assert [o.instance_id for o in _names(restored, "B")] == [b2.instance_id]
    del a1, b1


def test_session_rewind_over_an_open_choice_reasks_it():
    eng = _engine()
    session = GameSession(eng)
    first, second = _put(eng, _legend("Lg"), "p1"), _put(eng, _legend("Lg"), "p1")
    eng.rules.check_state_based_actions()
    actions = [a for a in session.legal_actions("p1") if a["type"] == "choose"]
    assert {a["instance_id"] for a in actions} == {first.instance_id, second.instance_id}
    assert session.legal_actions("p2") == []
    session.apply_action({"type": "choose", "option_id": str(second.instance_id)}, "p1")
    assert [o.instance_id for o in _names(session.engine, "Lg")] == [second.instance_id]


def test_bot_answers_through_legal_actions_and_keeps_the_stronger_copy():
    eng = _engine()
    first, second = _put(eng, _legend("Lg"), "p1"), _put(eng, _legend("Lg"), "p1")
    second.add_counters("+1/+1", 3)
    session = GameSession(eng)
    eng.rules.check_state_based_actions()
    eng.recompute_continuous_effects()

    view = session.view("p1")
    answer = Bot("p1").answer_choice(view, session.legal_actions("p1"))
    session.apply_action(answer, "p1")

    assert [o.instance_id for o in _names(session.engine, "Lg")] == [second.instance_id]
    del first


def test_unchosen_legend_and_zero_toughness_death_share_one_dies_batch():
    # RULE 603.10a: both deaths are members of the same DIES batch, so a dies trigger sees both.
    eng = _engine()
    doomed = _put(eng, _legend("D"), "p1")
    doomed.add_counters("-1/-1", 2)
    _put(eng, _legend("Lg"), "p1")
    second = _put(eng, _legend("Lg"), "p1")

    eng.rules.check_state_based_actions()
    eng.resolve_pending_choice(str(second.instance_id))

    dies = [e for e in eng.state.event_log if e.type == "EVENT_BATCH" and e.data["batch_of"] == "DIES"]
    assert len(dies) == 1 and sorted(m.data["object"] for m in dies[0].data["members"]) == ["D", "Lg"]
