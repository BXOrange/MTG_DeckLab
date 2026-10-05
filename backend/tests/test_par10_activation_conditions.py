"""PAR-10: "Activate only as a sorcery and only if `<condition>`." (Cabal
Inquisitor/Dread Wanderer/Hall of Oracles/Jin-Gitaxias // The Great
Synthesis) and its bare sibling "Activate only if `<condition>`."
(Potioner's Trove) — RULE 602.5d sorcery-speed timing stacked with (or
standing in for) a board-state activation condition.

Two independent primitives shipped alongside the parser recognition itself:

* `ActivationCost.activation_condition` — a `game/static_conditions.py`
  whitelisted condition dict, checked live by `GameEngine.can_activate`
  the same way a permanent's own "as long as `<condition>`" static is.
* `static_conditions.STATIC_CONDITION_KINDS`'s new
  ``cast_instant_or_sorcery_this_turn`` kind (`GameState.
  cast_instant_or_sorcery_this_turn`, reset for *every* player each turn,
  unlike the active-player-only `spells_cast_this_turn`) — which the
  existing "as long as" conditional-static family picks up for free
  (Haunting Figment/Leapfrog/Piston-Fist Cyclops).

A third, unrelated discovery made while sizing Dread Wanderer's own SOLO
closure got its own primitive too: "Return this card from your graveyard to
the battlefield[, tapped]." was entirely unrecognized — 69+ cache cards
(`game/effects/core.py`'s `ReturnSelfFromGraveyardToBattlefieldEffect`,
`catalogue.handlers._RETURN_SELF_FROM_GRAVEYARD_RE`).

Reference: mtg_analyzer/game/{costs,static_conditions,effects,effect_binder,
engine/activation_mixin}.py, mtg_analyzer/parser/oracle/catalogue/
handlers.py, mtg_analyzer/models/game_state.py.
"""

from __future__ import annotations

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from tests import turn_history_events as history


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None):
    return Card(
        id=name, name=name, type_line="Creature — Beast", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _engine(hand=0):
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(8)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=hand)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Parse side: the compound/bare activation-condition markers
# ---------------------------------------------------------------------------


def test_sorcery_speed_and_condition_clause_is_recognized():
    specs = match_clause(
        "activate only as a sorcery and only if there are 7 or more cards in your graveyard"
    )
    types = [s.type for s in specs]
    assert "sorcery_speed_marker" in types
    assert "activation_condition_marker" in types
    (cond_spec,) = [s for s in specs if s.type == "activation_condition_marker"]
    assert cond_spec.params["condition"] == {
        "kind": "control_count", "selector": "cards_in_your_graveyard", "min": 7,
    }


def test_bare_activate_only_if_clause_is_recognized():
    (spec,) = match_clause("activate only if you have 1 or fewer cards in hand")
    assert spec.type == "activation_condition_marker"
    assert spec.params["condition"] == {"kind": "cards_in_hand_at_most", "amount": 1}


def test_activate_only_if_cast_instant_or_sorcery_is_recognized():
    (spec,) = match_clause("activate only if you've cast an instant or sorcery spell this turn")
    assert spec.params["condition"] == {"kind": "cast_instant_or_sorcery_this_turn"}


def test_activation_condition_falls_back_to_the_shared_static_vocabulary():
    # PAR-120: `_activation_condition_dict` now falls back to
    # `static_handlers.static_condition()` once its own closed table
    # declines — "you control a Plains" was never a *different* concept,
    # just a phrase this table hadn't copied by hand; it reaches the shared
    # count-phrase grammar the same way "as long as you control a Plains"
    # already did. A genuinely unmodeled phrase (`this creature is
    # attacking` — no `static_condition()` row for that exact wording
    # either) still fails closed.
    (spec,) = match_clause("activate only if you control a Plains")
    assert spec.params["condition"] == {
        "kind": "control_count", "selector": "lands_you_control_of_type_plains", "min": 1,
    }
    assert match_clause(
        "activate only as a sorcery and only if this creature is attacking"
    ) is None


def test_opponent_graveyard_condition_is_recognized():
    specs = match_clause(
        "activate only as a sorcery and only if an opponent has 8 or more cards in their graveyard"
    )
    (cond_spec,) = [s for s in specs if s.type == "activation_condition_marker"]
    assert cond_spec.params["condition"] == {
        "kind": "opponent_count", "selector": "cards_in_your_graveyard", "min": 8,
    }


# ---------------------------------------------------------------------------
# `cast_instant_or_sorcery_this_turn` — state tracking + condition kind
# ---------------------------------------------------------------------------


def test_static_condition_row_recognizes_cast_instant_or_sorcery():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
    assert static_condition("you've cast an instant or sorcery spell this turn") == {
        "kind": "cast_instant_or_sorcery_this_turn",
    }


def test_condition_holds_reads_the_new_state_flag():
    eng = _engine()
    state = eng.state
    assert static_conditions.condition_holds(
        {"kind": "cast_instant_or_sorcery_this_turn"}, state, controller_id="p1"
    ) is False
    history.cast_spell(state, "p1", types=["instant"])
    assert static_conditions.condition_holds(
        {"kind": "cast_instant_or_sorcery_this_turn"}, state, controller_id="p1"
    ) is True


def test_spell_cast_event_flips_the_flag_only_for_instants_and_sorceries():
    eng = _engine()
    state = eng.state
    state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p1", card_id="Bear0", spell="Bear0",
        instance_id=1, object_types=["creature"], mana_spent=0, from_hand=True,
    ))
    assert state.cast_instant_or_sorcery_this_turn["p1"] is False
    state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p1", card_id="Bolt", spell="Bolt",
        instance_id=2, object_types=["instant"], mana_spent=0, from_hand=True,
    ))
    assert state.cast_instant_or_sorcery_this_turn["p1"] is True


def test_flag_resets_for_every_player_at_begin_turn_not_just_the_active_one():
    eng = _engine()
    state = eng.state
    history.cast_spell(state, "p1", types=["instant"])
    history.cast_spell(state, "p2", types=["sorcery"])
    assert state.cast_instant_or_sorcery_this_turn["p1"] and state.cast_instant_or_sorcery_this_turn["p2"]
    eng.begin_turn()
    assert state.cast_instant_or_sorcery_this_turn[state.active_player.id] is False
    # game-wide reset — the *other* player's flag is cleared too, unlike
    # `spells_cast_this_turn`'s active-player-only reset.
    other = next(p for p in state.players if p.id != state.active_player.id)
    assert state.cast_instant_or_sorcery_this_turn[other.id] is False


def test_haunting_figment_shaped_as_long_as_condition_is_modeled():
    # The conditional-static family picks up the new condition kind for
    # free — no separate parser work needed for this shape.
    card = Card(
        id="Haunting Figment", name="Haunting Figment", type_line="Creature — Spirit",
        is_creature=True, power=2, toughness=1,
        oracle_text="~ can't be blocked as long as you've cast an instant or sorcery spell this turn.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# ---------------------------------------------------------------------------
# Engine: `ActivationCost.activation_condition` gating `can_activate`
# ---------------------------------------------------------------------------


def test_activation_condition_blocks_and_permits_activation():
    eng = _engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    source = _bf(eng.state, _creature("Hall of Oracles"))
    ability_cost = parse_activation_cost("{T}")
    ability_cost.sorcery_speed_only = True
    ability_cost.activation_condition = {"kind": "cast_instant_or_sorcery_this_turn"}
    from mtg_analyzer.game.effects.core import ActivatedAbility
    ability = ActivatedAbility(
        effects=[EffectRegistry.create("draw", {"count": 1})],
        cost=ability_cost, source=source,
    )
    source.activated_abilities = [ability]

    assert eng.can_activate(p1, source, ability) is False
    history.cast_spell(eng.state, "p1", types=["instant"])
    assert eng.can_activate(p1, source, ability) is True


def test_dread_wanderer_full_card_activation_condition_end_to_end():
    eng = _engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 1, "C": 2})

    card = Card(id="Dread Wanderer", name="Dread Wanderer", type_line="Creature — Zombie",
                is_creature=True, power=2, toughness=1,
                oracle_text="This creature enters tapped.\n"
                            "{2}{B}: Return this card from your graveyard to the battlefield. "
                            "Activate only as a sorcery and only if you have one or fewer cards in hand.")
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    ability = obj.activated_abilities[0]
    assert ability.cost.sorcery_speed_only is True
    assert ability.cost.activation_condition == {"kind": "cards_in_hand_at_most", "amount": 1}

    # An empty hand satisfies "1 or fewer" — activation should succeed.
    assert len(p1.hand) == 0
    assert eng.can_activate(p1, obj, ability) is True

    eng.activate_ability(p1, obj, 0)
    eng.resolve_until_stable()

    assert obj in eng.state.battlefield
    assert obj.tapped is False  # only "enters tapped" would set that — a replacement, not this ability


def test_dread_wanderer_locked_out_with_a_full_hand():
    eng = _engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 1, "C": 2})
    p1.hand.extend([
        GameObject(Card(id=f"Filler{i}", name=f"Filler{i}", type_line="Instant"),
                   owner_id="p1", zone=Zone.HAND)
        for i in range(3)
    ])

    card = Card(id="Dread Wanderer", name="Dread Wanderer", type_line="Creature — Zombie",
                is_creature=True, power=2, toughness=1,
                oracle_text="This creature enters tapped.\n"
                            "{2}{B}: Return this card from your graveyard to the battlefield. "
                            "Activate only as a sorcery and only if you have one or fewer cards in hand.")
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    ability = obj.activated_abilities[0]
    assert eng.can_activate(p1, obj, ability) is False


# ---------------------------------------------------------------------------
# "Return this card from your graveyard to the battlefield[, tapped]."
# ---------------------------------------------------------------------------


def test_return_self_from_graveyard_clause_is_recognized():
    (spec,) = match_clause("return this card from your graveyard to the battlefield")
    assert spec.type == "return_self_from_graveyard"
    assert spec.params == {"tapped": False}


def test_return_self_from_graveyard_tapped_variant_is_recognized():
    (spec,) = match_clause("return this card from your graveyard to the battlefield tapped")
    assert spec.params == {"tapped": True}


def test_reassembling_skeleton_is_fully_modeled():
    card = Card(id="Reassembling Skeleton", name="Reassembling Skeleton",
                type_line="Artifact Creature — Skeleton", is_creature=True,
                power=1, toughness=1,
                oracle_text="{1}{B}: Return this card from your graveyard to the battlefield tapped.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_return_self_from_graveyard_end_to_end_untapped():
    eng = _engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 1, "C": 1})

    card = Card(id="Cauldron Familiar", name="Cauldron Familiar", type_line="Creature — Cat",
                is_creature=True, power=1, toughness=1,
                oracle_text="Sacrifice a Food: Return this card from your graveyard to the battlefield.")
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    ability = obj.activated_abilities[0]
    assert ability.cost.discard_self is False
    assert ability.cost.sacrifice == "food"


def test_return_self_from_graveyard_end_to_end_tapped():
    eng = _engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 1, "C": 1})

    card = Card(id="Reassembling Skeleton", name="Reassembling Skeleton",
                type_line="Artifact Creature — Skeleton", is_creature=True,
                power=1, toughness=1,
                oracle_text="{1}{B}: Return this card from your graveyard to the battlefield tapped.")
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    p1.graveyard.append(obj)

    ability = obj.activated_abilities[0]
    assert eng.can_activate(p1, obj, ability) is True
    eng.activate_ability(p1, obj, 0)
    eng.resolve_until_stable()

    assert obj in eng.state.battlefield
    assert obj.tapped is True


def test_return_self_from_graveyard_is_a_noop_if_no_longer_in_the_graveyard():
    # RULE 603.3c/608.2b: something else moved it between trigger and
    # resolution (or, here, it's simply already elsewhere) — must not raise.
    from mtg_analyzer.game.effects.core import GameContext, ReturnSelfFromGraveyardToBattlefieldEffect

    eng = _engine(hand=0)
    p1 = eng.state.active_player
    obj = GameObject(Card(id="Elsewhere", name="Elsewhere", type_line="Creature",
                          is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)

    effect = ReturnSelfFromGraveyardToBattlefieldEffect(source=obj)
    effect.apply(GameContext(eng.state, eng.rules))  # must not raise
    assert obj in p1.hand
    assert obj not in eng.state.battlefield
