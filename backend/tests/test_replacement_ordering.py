"""Interactive ordering of simultaneous replacement effects (RULE 616.1).

Covers both the general pause/resume mechanism (`RulesEngine.apply_
replacements`/`resolve_replacement_order_choice`, mirroring RULE 603.3b's
trigger-ordering pattern in `test_ordering.py`) and the four real-card
replacement families it was built to exercise: token/counter doubling
(Doubling Season, Parallel Lives — order-invariant, RULE 616.1e still
requires the choice) and damage doubling vs. additive damage (Furnace of
Rath, Torbran, Thane of Red Fell — order genuinely changes the total).
"""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import ReplacementEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _bound(state, name, controller="p1", **card_kwargs):
    """A hand-authored-catalogue card, bound and on the battlefield."""
    card = Card(id=name, name=name, type_line=card_kwargs.pop("type_line", "Enchantment"), **card_kwargs)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _torbran(state, controller="p1"):
    return _bound(
        state, "Torbran, Thane of Red Fell", controller,
        type_line="Legendary Creature — Dwarf Berserker",
        is_creature=True, power=3, toughness=3, color_identity={"R"},
    )


def _token_card(name="Spirit"):
    return Card(id=name, name=name, type_line="Token Creature — Spirit",
                is_creature=True, power=1, toughness=1)


# ---------------------------------------------------------------------------
# General pause/resume mechanism
# ---------------------------------------------------------------------------


def test_apply_replacements_without_callback_stays_synchronous_and_deterministic():
    """Back-compat: a direct caller with no continuation never sees a choice."""
    eng = make_engine()
    state = eng.state
    obj = GameObject(Card(id="x", name="X", type_line="Enchantment"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(obj)
    obj.replacement_effects.append(
        ReplacementEffect(EventType.DRAW, lambda e, c: e.copy_with(count=e.get("count", 1) + 1), description="A")
    )
    obj.replacement_effects.append(
        ReplacementEffect(EventType.DRAW, lambda e, c: e.copy_with(count=e.get("count", 1) + 1), description="B")
    )
    resolved = eng.rules.apply_replacements(GameEvent(EventType.DRAW, player_id="p1", count=1))
    assert state.pending_choice is None
    assert resolved.get("count") == 3


def test_second_ambiguous_event_falls_back_while_a_choice_is_pending():
    """A choice already open isn't clobbered by a second ambiguous event
    resolving synchronously in the same batch (e.g. two combat-damage
    assignments) — that second one resolves deterministically instead."""
    eng = make_engine()
    state = eng.state
    _bound(state, "Furnace of Rath")
    torbran = _torbran(state)
    p2 = state.player_by_id("p2")

    eng.rules.deal_damage(p2, 5, source=torbran)
    first_choice = state.pending_choice
    assert first_choice is not None and first_choice["kind"] == "replacement_order"

    eng.rules.deal_damage(p2, 3, source=torbran)
    assert state.pending_choice is first_choice  # untouched by the second call

    eng.rules.resolve_replacement_order_choice(0)
    assert state.pending_choice is None
    # Second call: deterministic discovery order, double-then-add: 3*2+2=8.
    # First call, resolved via the choice at index 0 (discovery order too,
    # since both cards were bound in the same order): 5*2+2=12.
    assert p2.life == 20 - 8 - 12


def test_game_engine_dispatches_replacement_order_choice():
    """The `resolve_pending_choice` dispatch table (game_engine.py) routes
    the ``replacement_order`` kind end to end, not just the rules-engine
    method directly."""
    eng = make_engine()
    state = eng.state
    _bound(state, "Doubling Season")
    _bound(state, "Parallel Lives")
    eng.rules.create_token("p1", _token_card(), count=1)
    assert state.pending_choice["kind"] == "replacement_order"
    eng.resolve_pending_choice("0")
    assert state.pending_choice is None
    assert len([o for o in state.battlefield if o.is_token]) == 4


# ---------------------------------------------------------------------------
# Doubling Season + Parallel Lives (order-invariant — still must ask)
# ---------------------------------------------------------------------------


def test_two_token_doublers_prompt_for_order():
    eng = make_engine()
    state = eng.state
    _bound(state, "Doubling Season")
    _bound(state, "Parallel Lives")

    created = eng.rules.create_token("p1", _token_card(), count=1)
    assert created == []  # paused: awaiting the RULE 616.1 choice
    choice = state.pending_choice
    assert choice["kind"] == "replacement_order"
    assert choice["player_id"] == "p1"
    assert len(choice["options"]) == 2

    eng.rules.resolve_replacement_order_choice(0)
    assert state.pending_choice is None
    assert len([o for o in state.battlefield if o.is_token]) == 4  # 1 -> 2 -> 4


def test_token_doubler_order_does_not_change_the_final_count():
    for first_pick in (0, 1):
        eng = make_engine()
        state = eng.state
        _bound(state, "Doubling Season")
        _bound(state, "Parallel Lives")
        eng.rules.create_token("p1", _token_card(), count=1)
        eng.rules.resolve_replacement_order_choice(first_pick)
        assert len([o for o in state.battlefield if o.is_token]) == 4


def test_doubling_season_alone_doubles_plus_one_counters():
    eng = make_engine()
    state = eng.state
    _bound(state, "Doubling Season")
    bear = GameObject(
        Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(bear)
    eng.rules.add_counters(bear, 2, kind="+1/+1")
    assert state.pending_choice is None  # only one applicable effect — no ambiguity
    assert bear.plus_one_counters == 4


# ---------------------------------------------------------------------------
# Furnace of Rath + Torbran (order genuinely changes the total)
# ---------------------------------------------------------------------------


def test_damage_doubler_and_adder_order_changes_the_total():
    # (5 * 2) + 2 = 12 when doubling is applied first.
    eng = make_engine()
    state = eng.state
    _bound(state, "Furnace of Rath")
    torbran = _torbran(state)
    p2 = state.player_by_id("p2")

    eng.rules.deal_damage(p2, 5, source=torbran)
    choice = state.pending_choice
    assert choice["kind"] == "replacement_order"
    double_idx = next(i for i, o in enumerate(choice["options"]) if o["label"] == "Furnace of Rath")

    eng.rules.resolve_replacement_order_choice(double_idx)
    assert state.pending_choice is None
    assert p2.life == 20 - 12


def test_damage_adder_then_doubler_gives_a_different_total():
    # (5 + 2) * 2 = 14 when the additional-damage effect is applied first —
    # a different number than the reverse order above, the reason RULE
    # 616.1's choice is meaningful (not just formally required) here.
    eng = make_engine()
    state = eng.state
    _bound(state, "Furnace of Rath")
    torbran = _torbran(state)
    p2 = state.player_by_id("p2")

    eng.rules.deal_damage(p2, 5, source=torbran)
    choice = state.pending_choice
    add_idx = next(i for i, o in enumerate(choice["options"]) if o["label"] == "Torbran, Thane of Red Fell")

    eng.rules.resolve_replacement_order_choice(add_idx)
    assert state.pending_choice is None
    assert p2.life == 20 - 14


def test_gratuitous_violence_only_doubles_your_own_creature_damage():
    # RULE 616.1: the real printed text ("if a creature you control would
    # deal damage...") has no "combat" restriction at all — any damage
    # (combat or not) from a creature you control is doubled; a non-creature
    # source you control, or anyone's damage you don't control, isn't.
    eng = make_engine()
    state = eng.state
    _bound(state, "Gratuitous Violence")
    attacker = GameObject(
        Card(id="atk", name="Attacker", type_line="Creature — Human", is_creature=True, power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(attacker)
    p2 = state.player_by_id("p2")

    # Combat damage from your own creature: doubled, no ambiguity (only one
    # replacement is registered at all).
    eng.rules.deal_damage(p2, 3, source=attacker, combat=True)
    assert state.pending_choice is None
    assert p2.life == 20 - 6

    # Non-combat damage from the same creature (e.g. a damage-dealing
    # activated/triggered ability): also doubled — no "combat" restriction.
    p2.life = 20
    eng.rules.deal_damage(p2, 3, source=attacker, combat=False)
    assert p2.life == 20 - 6

    # A non-creature permanent you control (an artifact source): untouched
    # — `creature_only` is the whole reason this differs from Furnace of
    # Rath's unscoped version.
    artifact = GameObject(
        Card(id="art", name="Artifact Pinger", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(artifact)
    p2.life = 20
    eng.rules.deal_damage(p2, 3, source=artifact, combat=False)
    assert p2.life == 20 - 3
