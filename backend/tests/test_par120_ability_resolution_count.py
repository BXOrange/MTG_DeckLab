"""PAR-120: "if this is the Nth time this ability has resolved this turn".

The count lives on the ability's source (`GameObject.ability_resolutions`,
stamped with the turn), is bumped by `RulesEngine.resolve_top_of_stack` for the
ability now resolving and read through `GameContext.ability_resolution_count`
by the effect-only ``ability_resolution_count`` condition. The rulings the
tests pin (Ashling the Pilgrim, Omnath, Locus of Creation): resolutions count,
not activations; the resolving one is included ("the third time" is exactly
the third); a new object starts over.

Also covers the two smaller PAR-120 pieces shipped alongside: the single
"this spell costs {N} less to cast for each `<count phrase>`" row, and the
emphatic "all creatures you control" group subject.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.continuous import self_cost_reduction_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

#: A mana-free activated ability, so a test can resolve it any number of times.
_SECOND_TIME_DRAWS = (
    "{0}: You gain 1 life. If this is the second time this ability has "
    "resolved this turn, draw a card."
)


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    engine.begin_turn()
    state = engine.state
    for index in range(10):
        state.player_by_id("p1").library.append(GameObject(
            Card(id=f"lib-{index}", name=f"Library Card {index}", type_line="Land"),
            owner_id="p1", zone=Zone.LIBRARY,
        ))
    return engine, state


def _permanent(state, name, text, type_line="Artifact", **card_kwargs):
    card = Card(id=name.lower().replace(" ", "-"), name=name, type_line=type_line,
                oracle_text=text, **card_kwargs)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _activate_and_resolve(engine, state, source):
    engine.activate_ability(state.player_by_id("p1"), source, 0)
    engine.resolve_until_stable()


# -- parse -------------------------------------------------------------------


def test_ordinal_phrases_become_resolution_count_bounds():
    card = Card(
        id="ladder", name="Ladder", type_line="Artifact",
        oracle_text=(
            "{0}: You gain 4 life if this is the first time this ability has resolved "
            "this turn. If it's the second time, draw a card. If it's the third time, "
            "each opponent loses 2 life."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    conditions = [effect.condition for spec in result.specs for effect in spec.effects]
    assert conditions == [
        {"kind": "ability_resolution_count", "min": 1, "max": 1},
        {"kind": "ability_resolution_count", "min": 2, "max": 2},
        {"kind": "ability_resolution_count", "min": 3, "max": 3},
    ]


def test_first_or_second_time_is_a_range():
    card = Card(id="range", name="Range", type_line="Artifact",
                oracle_text=("{0}: Draw a card if this is the first or second time this "
                             "ability has resolved this turn."))
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    [effect] = [e for spec in result.specs for e in spec.effects]
    assert effect.condition == {"kind": "ability_resolution_count", "min": 1, "max": 2}


def test_a_static_can_not_claim_the_effect_only_gate():
    # Only a resolving ability has a resolution count; an "as long as"
    # static naming it must stay unmodeled rather than bind a gate that is
    # never answerable.
    card = Card(id="static", name="Static", type_line="Enchantment",
                oracle_text=("Creatures you control get +1/+1 as long as this is the second "
                             "time this ability has resolved this turn."))
    assert not parse_oracle(card).modeled


# -- execute -----------------------------------------------------------------


def test_only_the_second_resolution_draws():
    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    hand = state.player_by_id("p1").hand
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 0
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 1
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 1  # the third resolution is not "the second time"
    assert state.player_by_id("p1").life == 23


def test_abilities_still_on_the_stack_do_not_count():
    # Ashling the Pilgrim's ruling: resolutions count, not activations.
    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    p1 = state.player_by_id("p1")
    engine.activate_ability(p1, source, 0)
    engine.activate_ability(p1, source, 0)
    assert len(state.stack) == 2
    engine.rules.resolve_top_of_stack()
    assert len(p1.hand) == 0  # first resolution; the other is still waiting
    engine.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1


def test_the_count_starts_over_each_turn():
    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    hand = state.player_by_id("p1").hand
    _activate_and_resolve(engine, state, source)
    state.turn_nr += 1  # a stale turn stamp reads as zero resolutions
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 0
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 1


def test_a_new_object_starts_over():
    # RULE 400.7: a permanent that changed zones is a new object whose
    # abilities have never resolved.
    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    hand = state.player_by_id("p1").hand
    _activate_and_resolve(engine, state, source)
    source.reset_as_new_object()
    _activate_and_resolve(engine, state, source)
    assert len(hand) == 0


def test_the_count_survives_the_undo_copy():
    # Keyed by the ability's text rather than an ``id()``, so the deep copy an
    # undo snapshot takes still finds its own entry.
    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    _activate_and_resolve(engine, state, source)
    clone = state.clone()
    copied = clone.find_object(source.instance_id)
    assert copied.ability_resolutions == source.ability_resolutions


def test_an_unanswerable_count_does_not_fire_outside_a_resolution():
    from mtg_analyzer.game.effect_conditions import condition_holds

    engine, state = _engine()
    source = _permanent(state, "Second Timer", _SECOND_TIME_DRAWS)
    condition = {"kind": "ability_resolution_count", "min": 1, "max": 1}
    assert engine.rules.context.ability_resolution_count is None
    assert not condition_holds(condition, engine.rules.context, source, None)


# -- the other two PAR-120 pieces --------------------------------------------


def test_cost_reduction_for_each_counts_through_the_shared_grammar():
    engine, state = _engine()
    card = Card(id="protector", name="Protector", type_line="Creature — Avatar",
                is_creature=True, power=3, toughness=4, mana_cost_string="{7}{W}",
                oracle_text="This spell costs {1} less to cast for each creature your opponents control.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    [effect] = [e for spec in result.specs for e in spec.effects]
    assert effect.params["per"] == {
        "zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature"},
    }
    source = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(source)
    for index in range(3):
        bear = GameObject(Card(id=f"bear-{index}", name="Bear", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(bear)
    _permanent(state, "My Bear", "", type_line="Creature — Bear", is_creature=True,
               power=2, toughness=2)
    engine.recompute_continuous_effects()
    assert self_cost_reduction_for(source, state, caster_id="p1")[0] == 3


def test_previously_named_cost_phrases_keep_their_exact_selector():
    # The per-phrase rows this replaced emitted named selectors; the table
    # keeps them so no already-covered card's spec changed.
    card = Card(id="party", name="Party", type_line="Sorcery", is_sorcery=True,
                oracle_text=("This spell costs {1} less to cast for each creature in your party.\n"
                             "Draw a card."))
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    per = [e.params.get("per") for spec in result.specs for e in spec.effects
           if e.type == "cost_reduction"]
    assert per == ["creatures_in_your_party"]


def test_all_creatures_you_control_is_the_controllers_group():
    engine, state = _engine()
    source = _permanent(state, "Venom Test",
                        "{0}: All creatures you control gain deathtouch until end of turn.")
    mine = _permanent(state, "My Bear", "", type_line="Creature — Bear",
                      is_creature=True, power=2, toughness=2)
    theirs = GameObject(Card(id="their-bear", name="Their Bear", type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(theirs)
    _activate_and_resolve(engine, state, source)
    engine.recompute_continuous_effects()
    from mtg_analyzer.game import combat

    assert combat.has(mine, "deathtouch")
    assert not combat.has(theirs, "deathtouch")


def test_a_triggered_ability_counts_its_own_resolutions():
    # The triggered path keys its stack item separately from activation.
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, state = _engine()
    _permanent(state, "Gatherer",
               ("Whenever another creature you control enters, you gain 1 life. If this is "
                "the second time this ability has resolved this turn, draw a card."),
               type_line="Creature — Human", is_creature=True, power=1, toughness=1)
    hand = state.player_by_id("p1").hand
    for index in range(3):
        bear = GameObject(Card(id=f"entering-{index}", name="Bear", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(bear)
        state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=bear.instance_id,
                                   controller_id="p1"))
        engine.resolve_until_stable()
        assert len(hand) == (1 if index >= 1 else 0)
    assert state.player_by_id("p1").life == 23
