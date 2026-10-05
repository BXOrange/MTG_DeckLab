"""MEC-102 — RULE 614.1 "put it onto the battlefield instead of putting it into
your graveyard" replacement on a card's own discard (Loxodon Smiter, Obstinate
Baloth, Nullhide Ferox, Dodecapod).

Built on MEC-101's `cause_controller_id` provenance: `EventType.WOULD_DISCARD`
fires just before `RulesEngine.discard`/`discard_specific`/`discard_random` would
move a card to the graveyard, and `game/effects/replacements.py`'s
`_discard_to_battlefield_replacement` (registered as ``"discard_to_battlefield"``)
redirects it. Checked directly against the discarded object's own
`GameObject.replacement_effects` (`draw_discard_mixin._maybe_discard_to_battlefield`)
rather than through `RulesEngine._all_replacement_effects()`, since the card is —
necessarily — still in hand at the moment its own discard would happen, and that
scan is battlefield-only.

The card is still considered discarded either way (RULE 614.1 changes *how* the
event happens, not *whether* it happened), so `DISCARD_CARD`/`DISCARD` fire
normally regardless of which zone the card actually lands in.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _opponent_cause(controller="p2"):
    card = Card(id="Opposing Source", name="Opposing Source", type_line="Sorcery")
    obj = GameObject(card, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return obj


def _own_cause(controller="p1"):
    card = Card(id="Own Cycler", name="Own Cycler", type_line="Instant")
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    return obj


def _card(name, type_line="Creature — Beast", **kw):
    return GameObject(
        Card(id=name, name=name, type_line=type_line, is_creature=True,
             power=1, toughness=1, **kw),
        owner_id="p1", zone=Zone.HAND,
    )


# ---------------------------------------------------------------------------
# discard() — the auto-pick, count-scoped path (obj already popped off hand)
# ---------------------------------------------------------------------------


def test_discard_redirects_to_the_battlefield_when_opponent_caused():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Loxodon Smiter")
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    events = []
    orig_fire = eng.state.fire_event
    eng.state.fire_event = lambda e: (events.append(e), orig_fire(e))[1]

    eng.rules.discard(p1, 1, cause=_opponent_cause())

    assert obj in eng.state.battlefield
    assert obj not in p1.graveyard
    assert obj not in p1.hand

    discards = [e for e in events if e.type == EventType.DISCARD_CARD]
    assert len(discards) == 1, "still counts as discarded (RULE 614.1)"
    assert [e for e in events if e.type == EventType.DISCARD]
    enters = [e for e in events if e.type == EventType.ENTERS_BATTLEFIELD]
    assert len(enters) == 1 and enters[0].get("instance_id") == obj.instance_id


def test_discard_goes_to_the_graveyard_normally_with_no_cause():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Loxodon Smiter")
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard(p1, 1)  # no cause at all — mirrors RULE 514.2 cleanup

    assert obj in p1.graveyard
    assert obj not in eng.state.battlefield


def test_discard_goes_to_the_graveyard_when_the_cause_is_its_own_controller():
    """RULE 603.1's "an opponent controls" — the replacement must not fire for
    a cost the discarding player paid themself."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Loxodon Smiter")
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard(p1, 1, cause=_own_cause())

    assert obj in p1.graveyard
    assert obj not in eng.state.battlefield


# ---------------------------------------------------------------------------
# discard_specific() — the chosen-card path (obj not yet removed from hand)
# ---------------------------------------------------------------------------


def test_discard_specific_redirects_to_the_battlefield_when_opponent_caused():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Loxodon Smiter")
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard_specific(obj, cause=_opponent_cause())

    assert obj in eng.state.battlefield
    assert obj not in p1.hand
    assert obj not in p1.graveyard


def test_dodecapod_enters_with_its_two_plus_one_plus_one_counters():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Dodecapod", type_line="Artifact Creature — Golem")
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard_specific(obj, cause=_opponent_cause())

    assert obj in eng.state.battlefield
    assert obj.counters.get("+1/+1") == 2


def test_obstinate_baloths_own_etb_trigger_still_fires():
    """The redirected object is a genuine new arrival on the battlefield
    (RULE 400.7) — its own "when this creature enters" trigger must see it,
    the same as any other way it could reach the battlefield."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Obstinate Baloth")
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    life_before = p1.life

    eng.rules.discard_specific(obj, cause=_opponent_cause())
    eng.resolve_until_stable()

    assert obj in eng.state.battlefield
    assert p1.life == life_before + 4


def test_nullhide_ferox_keeps_its_other_abilities_bound():
    """Hand-authoring for the replacement is all-or-nothing per card — Hexproof
    and the cast restriction must still be there, not silently dropped."""
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj = _card("Nullhide Ferox", keywords=["Hexproof"])
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    eng.rules.discard_specific(obj, cause=_opponent_cause())
    eng.recompute_continuous_effects()

    assert obj in eng.state.battlefield
    assert combat.has_hexproof(obj)
    assert len(obj.static_effects) == 1
    assert len(obj.activated_abilities) == 1
