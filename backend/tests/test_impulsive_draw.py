"""Tests for "exile the top N cards, you may play them until the end of
your next turn" (RULE 601.3b analogue, Light Up the Stage-shaped
"impulsive draw") — distinct from `ImpulsiveLookEffect` (gap 3: a filtered
choice-and-route shape) since every card exiled here becomes playable,
unfiltered, with no routing.

Engine side: `game/effects.py`'s `ImpulsiveDrawEffect` +
`RulesEngine.exile_with_play_permission`, `GameState.temp_play_permissions`,
`GameEngine.can_cast`/`can_play_land`/`_step_cleanup` (`game/game_engine.py`).
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effects import ImpulsiveDrawEffect
from mtg_analyzer.game.game_engine import GameEngine


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [_card("Filler", "Instant", is_instant=True)])],
        starting_life=20, starting_hand=0,
    )


def _stock_library(p1, cards):
    p1.library.clear()
    for card in cards:
        p1.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))


# ---------------------------------------------------------------------------
# RulesEngine.exile_with_play_permission
# ---------------------------------------------------------------------------


def test_exiles_exactly_n_and_grants_permission_to_all_of_them():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [
        _card("Bolt", "Instant", is_instant=True),
        _card("Bear", "Creature", is_creature=True),
    ])

    exiled = eng.rules.exile_with_play_permission(p1, 2)

    assert {o.name for o in exiled} == {"Bolt", "Bear"}
    assert len(p1.library) == 0
    assert len(p1.exile) == 2
    for obj in exiled:
        assert eng.state.temp_play_permissions[obj.instance_id] == eng.state.turn_number


def test_stops_early_if_the_library_runs_out():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", is_instant=True)])
    exiled = eng.rules.exile_with_play_permission(p1, 2)
    assert len(exiled) == 1


# ---------------------------------------------------------------------------
# can_cast / can_play_land honour the permission window
# ---------------------------------------------------------------------------


def test_can_cast_an_exiled_card_with_the_permission():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", mana_cost_string="{R}",
                               converted_mana_cost=1, is_instant=True)])
    p1.mana_pool.add("R", 1)

    [bolt] = eng.rules.exile_with_play_permission(p1, 1)
    assert eng.can_cast(p1, bolt) is True


def test_cannot_cast_an_exiled_card_without_the_permission():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    card = _card("Bolt", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.EXILE)
    p1.exile.append(obj)
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, obj) is False


def test_can_play_a_land_exiled_with_the_permission():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Forest", "Basic Land — Forest", is_land=True)])
    [forest] = eng.rules.exile_with_play_permission(p1, 1)
    assert eng.can_play_land(p1, forest) is True
    eng.play_land(p1, forest)
    assert forest in eng.state.battlefield


def test_permission_survives_into_the_next_turn():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", mana_cost_string="{R}",
                               converted_mana_cost=1, is_instant=True)])
    [bolt] = eng.rules.exile_with_play_permission(p1, 1)

    eng.state.current_step = "cleanup"
    eng._step_cleanup()
    assert bolt.instance_id in eng.state.temp_play_permissions  # survives its own turn's cleanup

    eng.begin_turn()  # next turn
    eng.state.current_step = "main1"
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, bolt) is True


def test_permission_lapses_after_the_next_turns_cleanup():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", mana_cost_string="{R}",
                               converted_mana_cost=1, is_instant=True)])
    [bolt] = eng.rules.exile_with_play_permission(p1, 1)

    eng.state.current_step = "cleanup"
    eng._step_cleanup()  # end of the granting turn: still valid
    eng.begin_turn()  # "your next turn" begins
    eng.state.current_step = "cleanup"
    eng._step_cleanup()  # end of "your next turn": permission lapses here

    assert bolt.instance_id not in eng.state.temp_play_permissions
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add("R", 1)
    assert eng.can_cast(p1, bolt) is False


# ---------------------------------------------------------------------------
# temp_play_permission_source — "why is this castable" for the board
# ---------------------------------------------------------------------------


def test_exile_with_play_permission_records_the_source_name():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", is_instant=True)])

    [bolt] = eng.rules.exile_with_play_permission(p1, 1, source_name="Light Up the Stage")

    assert eng.state.temp_play_permission_source[bolt.instance_id] == "Light Up the Stage"


def test_source_name_is_absent_when_not_given():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", is_instant=True)])

    [bolt] = eng.rules.exile_with_play_permission(p1, 1)

    assert bolt.instance_id not in eng.state.temp_play_permission_source


def test_source_name_is_pruned_in_lockstep_with_the_permission():
    eng = make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", is_instant=True)])
    [bolt] = eng.rules.exile_with_play_permission(p1, 1, source_name="Light Up the Stage")

    eng.state.current_step = "cleanup"
    eng._step_cleanup()  # end of the granting turn: still valid
    eng.begin_turn()
    eng.state.current_step = "cleanup"
    eng._step_cleanup()  # end of "your next turn": permission lapses here

    assert bolt.instance_id not in eng.state.temp_play_permissions
    assert bolt.instance_id not in eng.state.temp_play_permission_source


def test_impulsive_draw_effect_records_the_spells_own_name_as_source():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _stock_library(p1, [_card("Bolt", "Instant", is_instant=True)])

    spell = GameObject(
        Card(id="Light Up the Stage", name="Light Up the Stage", type_line="Sorcery",
             mana_cost_string="{1}{R}", converted_mana_cost=2, is_sorcery=True),
        owner_id="p1", zone=Zone.HAND,
    )
    # A hand-built fixture mirrors what the real oracle-text binder does
    # (`effect_binder.build_effects` sets `effect.source = source` after
    # constructing it via the registry) rather than going through the
    # binder itself.
    spell.spell_effects = [ImpulsiveDrawEffect(count=1, source=spell)]
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"R": 2})

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    bolt = next(o for o in p1.exile if o.name == "Bolt")
    assert eng.state.temp_play_permission_source[bolt.instance_id] == "Light Up the Stage"


# ---------------------------------------------------------------------------
# Full cast pipeline via the `impulsive_draw` EffectRegistry entry
# ---------------------------------------------------------------------------


def test_cast_a_light_up_the_stage_like_spell():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    _stock_library(p1, [
        _card("Bear", "Creature", is_creature=True),
        _card("Bolt", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True),
    ])
    p1.mana_pool.add_many({"R": 3})

    spell = GameObject(
        Card(id="Light Up the Stage", name="Light Up the Stage", type_line="Sorcery",
             mana_cost_string="{1}{R}", converted_mana_cost=2, is_sorcery=True),
        owner_id="p1", zone=Zone.HAND,
    )
    spell.spell_effects = [ImpulsiveDrawEffect(count=2)]
    p1.add_to_zone(spell, Zone.HAND)

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    assert len(p1.exile) == 2
    bolt = next(o for o in p1.exile if o.name == "Bolt")
    assert eng.can_cast(p1, bolt) is True
    eng.cast_spell(p1, bolt)
    eng.resolve_until_stable()
    assert bolt not in p1.exile
