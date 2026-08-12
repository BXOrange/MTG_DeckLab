"""RULE 603.4's "if it's the first combat phase of the turn, `<effect>`."
intervening-if (MEC-12's own "intervening if" trigger-condition family gap —
Karlach, Fury of Avernus/Finest Hour/Genji Glove/Raiyuu-shaped, every one of
them an extra-combat-granting trigger that must not re-trigger itself in the
extra phase it just made).

Modeled the same way Exert's `not_already_exerted` guards its own self-loop:
a new `GameState.combats_this_turn` counter (incremented once per
``begin_combat`` step, game-wide, reset each real turn) consulted by
`ConditionalEffect`'s new ``"is_first_combat_phase"`` key, wired in via the
same "wrap the rest, tag the condition" `parse_effect_body` idiom every
other intervening-if shape already uses (`_KICKED_CONDITION_RE`/
`_TARGET_IS_CONTROLLER_RE`/the Ring-bearer rows).

Genji Glove itself (the equipment-shaped card in this family) hits a
*separate*, pre-existing gap this batch didn't touch: an "attached_permanent"
-subject trigger's "it" doesn't retarget a self-acting effect (`TapEffect`'s
``target_kind=None`` mode) onto the equipped creature — it silently acts on
the Equipment itself instead, since `parse_effect_body`'s generic trigger
dispatch only special-cases a bare "self" subject
(`condition == {"subject": "self"}`), not "attached_permanent" too. Filed as
its own ticket (BACKLOG.md) rather than fixed here. This file validates the
primitive itself against a plain self-subject creature instead, where
``target_kind=None`` already correctly means "this creature".
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


FIRST_COMBAT_TEXT = (
    "Whenever this creature attacks, if it's the first combat phase of the "
    "turn, untap it. After this phase, there is an additional combat phase."
)


def attacker_card(name="Vanguard"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=2, toughness=2, oracle_text=FIRST_COMBAT_TEXT,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_first_combat_phase_card_is_modeled():
    result = parse_oracle(attacker_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


def test_first_combat_phase_grants_untap_and_extra_combat():
    eng = make_engine("p1", "p2")
    vanguard = put(eng.state, attacker_card())
    _to_declare_attackers(eng)
    eng.state.combats_this_turn = 1  # the (first) real combat phase this turn

    eng.declare_attackers(eng.state.active_player, [vanguard])
    eng.resolve_until_stable()

    assert vanguard.tapped is False  # untapped by the trigger
    assert len(eng.state.pending_extra_combats) == 1


def test_second_combat_phase_does_not_grant_a_third():
    eng = make_engine("p1", "p2")
    vanguard = put(eng.state, attacker_card())
    _to_declare_attackers(eng)
    eng.state.combats_this_turn = 2  # simulate: already in the granted extra combat

    eng.declare_attackers(eng.state.active_player, [vanguard])
    eng.resolve_until_stable()

    assert vanguard.tapped is True  # NOT untapped — the guard held
    assert len(eng.state.pending_extra_combats) == 0


def test_combats_this_turn_increments_on_begin_combat_step():
    eng = make_engine("p1", "p2")
    eng.begin_turn()
    assert eng.state.combats_this_turn == 0

    from mtg_analyzer.game.phases import GamePhase, GameStep
    eng._run_step(GamePhase("combat", []), GameStep("begin_combat", rule="507"))

    assert eng.state.combats_this_turn == 1


def test_combats_this_turn_resets_on_a_new_turn():
    eng = make_engine("p1", "p2")
    eng.begin_turn()
    eng.state.combats_this_turn = 3
    eng.begin_turn()
    assert eng.state.combats_this_turn == 0
