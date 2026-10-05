"""MEC-101 — "a spell or ability an opponent controls causes you to discard `<X>`"
(RULE 603.1) event provenance.

`RulesEngine.discard`/`discard_random`/`discard_specific`/`discard_matching` gained a
``cause`` param (the responsible spell/ability's own `GameObject`) stamped onto
`EventType.DISCARD_CARD` as ``cause_controller_id``, and `binding.core` gained a
``requires_opponent_caused_discard`` trigger-condition predicate reading it. Two new
collection paths consume it: an ordinary battlefield permanent's player-subject
"whenever a spell/ability an opponent controls causes you to discard a card, …" (the
existing main `_collect_triggers` loop, unchanged), and a hand-zone card's own
self-subject "when a spell/ability an opponent controls causes you to discard **this
card**, …" — which needed a new `triggers_mixin._collect_discarded_triggers` scan,
since `DISCARD_CARD` fires only after the card has already landed in the graveyard and
the main loop is battlefield-only.

Pure Intentions is the first (and, so far, only parser-front-end-unclaimed) card hand-
authored onto this primitive (`game/card_catalogue/p/pure_intentions.py`) — both of its
abilities are exercised end to end here, not just the cause provenance in isolation.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _opponent_cause(eng, controller="p2"):
    """A stand-in for "a spell or ability an opponent controls" — any `GameObject`
    with the right `controller_id` is enough for `cause_controller_id` provenance;
    nothing reads its card identity."""
    card = Card(id="Opposing Source", name="Opposing Source", type_line="Sorcery")
    obj = GameObject(card, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return obj


# ---------------------------------------------------------------------------
# Engine: cause_controller_id provenance
# ---------------------------------------------------------------------------


def test_discard_specific_stamps_the_causing_controller():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    victim = GameObject(Card(id="Victim", name="Victim", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim)
    cause = _opponent_cause(eng)

    events = []
    orig_fire = eng.state.fire_event
    eng.state.fire_event = lambda e: (events.append(e), orig_fire(e))[1]

    eng.rules.discard_specific(victim, cause=cause)

    discards = [e for e in events if e.type == EventType.DISCARD_CARD]
    assert len(discards) == 1
    assert discards[0].get("cause_controller_id") == "p2"


def test_cleanup_hand_size_discard_carries_no_cause():
    """RULE 514.2's own hand-size discard is not caused by any spell/ability —
    `GameEngine._step_cleanup` calls `rules.discard(active, excess)` with no
    ``cause``, so it must not be mistaken for an opponent-caused one."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        p1.hand.append(GameObject(
            Card(id=f"Card{i}", name=f"Card{i}", type_line="Instant"),
            owner_id="p1", zone=Zone.HAND,
        ))

    events = []
    orig_fire = eng.state.fire_event
    eng.state.fire_event = lambda e: (events.append(e), orig_fire(e))[1]

    eng.rules.discard(p1, 2)  # no cause= — mirrors the cleanup call site

    discards = [e for e in events if e.type == EventType.DISCARD_CARD]
    assert len(discards) == 2
    assert all(e.get("cause_controller_id") is None for e in discards)


def test_own_cost_payment_discard_carries_the_payer_as_cause_not_an_opponent():
    """Cycling/Channel's "Discard this card" cost passes the activated
    ability's own source as ``cause`` — correct provenance (RULE 603.1 does
    ask "what spell/ability", just not one an opponent controls), but the
    ``requires_opponent_caused_discard`` predicate must still reject it since
    the cause's controller equals the discarding player themself."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    own_ability_source = GameObject(
        Card(id="Own Cycler", name="Own Cycler", type_line="Instant"),
        owner_id="p1", zone=Zone.HAND,
    )
    own_ability_source.controller_id = "p1"
    victim = GameObject(Card(id="Victim2", name="Victim2", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim)

    events = []
    orig_fire = eng.state.fire_event
    eng.state.fire_event = lambda e: (events.append(e), orig_fire(e))[1]

    eng.rules.discard_specific(victim, cause=own_ability_source)

    discards = [e for e in events if e.type == EventType.DISCARD_CARD]
    assert discards[0].get("cause_controller_id") == "p1"


# ---------------------------------------------------------------------------
# Pure Intentions — end to end
# ---------------------------------------------------------------------------


def test_pure_intentions_second_ability_returns_itself_at_next_end_step():
    """"When a spell or ability an opponent controls causes you to discard this
    card, return this card from your graveyard to your hand at the beginning
    of the next end step." — fired while the card is still in hand (the
    triggered ability's own source), resolved via `_collect_discarded_
    triggers` once the discard has already moved it to the graveyard."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    card = Card(id="Pure Intentions", name="Pure Intentions", type_line="Instant — Arcane")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    cause = _opponent_cause(eng)

    eng.rules.discard_specific(obj, cause=cause)
    eng.resolve_until_stable()

    assert obj in p1.graveyard, "not returned yet — only armed a delayed trigger"
    assert len(eng.state.delayed_triggers) == 1

    eng.state.current_step = "end"
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()

    assert obj in p1.hand
    assert obj not in p1.graveyard
    assert eng.state.delayed_triggers == []


def test_pure_intentions_second_ability_does_not_fire_on_an_uncaused_discard():
    """The same discard with no opponent-controlled cause (e.g. paid as the
    card's own cost, or RULE 514.2 cleanup) must not arm the delayed return —
    `requires_opponent_caused_discard` gating the trigger, not just its body."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    card = Card(id="Pure Intentions", name="Pure Intentions", type_line="Instant — Arcane")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard_specific(obj)  # no cause at all
    eng.resolve_until_stable()

    assert obj in p1.graveyard
    assert eng.state.delayed_triggers == []


def test_pure_intentions_first_ability_returns_a_discarded_card_this_turn():
    """The instant's own resolution effect: a RULE 603.7a `create_turn_
    trigger` that, for the rest of the turn, returns whatever card an
    opponent's spell/ability next causes this player to discard — read off
    the firing `DISCARD_CARD` event via `ReturnToHandEffect`'s existing
    ``target_kind="trigger_subject"`` (PAR-123), not a fresh RULE 115 target."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")

    spell = GameObject(
        Card(id="Pure Intentions", name="Pure Intentions", type_line="Instant — Arcane"),
        owner_id="p1", zone=Zone.STACK,
    )
    bind_from_catalogue(spell)
    eng.state.stack.append(StackItem(
        kind="spell", controller_id="p1", obj=spell, description=spell.card.name,
        effects=eng.rules._effects_for_spell(spell),
    ))
    eng.rules.resolve_top_of_stack()
    assert len(eng.state.turn_scoped_triggers) == 1

    victim = GameObject(Card(id="Victim3", name="Victim3", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim)
    cause = _opponent_cause(eng)

    eng.rules.discard_specific(victim, cause=cause)
    eng.resolve_until_stable()

    assert victim in p1.hand, "returned the same resolution the discard happened in"
    assert victim not in p1.graveyard


def test_pure_intentions_first_ability_ignores_an_opponents_own_uncaused_discard():
    """A discard with no opponent cause must not be swept up by the same-turn
    floating trigger either."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")

    spell = GameObject(
        Card(id="Pure Intentions", name="Pure Intentions", type_line="Instant — Arcane"),
        owner_id="p1", zone=Zone.STACK,
    )
    bind_from_catalogue(spell)
    eng.state.stack.append(StackItem(
        kind="spell", controller_id="p1", obj=spell, description=spell.card.name,
        effects=eng.rules._effects_for_spell(spell),
    ))
    eng.rules.resolve_top_of_stack()

    victim = GameObject(Card(id="Victim4", name="Victim4", type_line="Instant"),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(victim)

    eng.rules.discard(p1, 1)  # auto-picks `victim`, the only hand card — no cause
    eng.resolve_until_stable()

    assert victim in p1.graveyard
    assert victim not in p1.hand
