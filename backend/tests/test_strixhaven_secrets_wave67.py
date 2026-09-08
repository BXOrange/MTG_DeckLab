"""Secrets of Strixhaven — playability batch, wave 67 (PAR-60).

Rootha, Mastering the Moment — new
``GameState.greatest_instant_sorcery_mv_this_turn`` tracker (bumped in
``_track_spell_cast``, reset in ``begin_turn``) + the
``greatest_instant_sorcery_mv_this_turn`` count_selector + a
``cast_instant_or_sorcery_this_turn`` trigger intervening-if predicate;
``CreateTokenEffect.pt_from_count_selector`` sizes the token.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def _rootha(eng):
    p1 = eng.state.players[0]
    r = GameObject(card=Card(id="r", name="Rootha, Mastering the Moment",
                            type_line="Legendary Creature — Orc Sorcerer", is_creature=True,
                            power=3, toughness=4),
                   owner_id=p1.id, zone=Zone.BATTLEFIELD)
    r.controller_id = p1.id
    eng.state.add_to_battlefield(r)
    bind_from_catalogue(r)
    return r


def test_rootha_makes_xx_token_from_greatest_is_mv():
    assert is_registered("Rootha, Mastering the Moment")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.players[0]
    _rootha(eng)
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=p1.id,
                                   object_types=["sorcery"], mana_value=5))
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=p1.id,
                                   object_types=["instant"], mana_value=2))
    assert eng.state.greatest_instant_sorcery_mv_this_turn[p1.id] == 5

    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat",
                                   active_player_id=p1.id, player_id=p1.id))
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].power == 5 and tokens[0].toughness == 5


def test_rootha_no_token_without_an_instant_or_sorcery_cast():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.players[0]
    _rootha(eng)
    # only a creature spell this turn -> intervening-if fails
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=p1.id,
                                   object_types=["creature"], mana_value=4))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat",
                                   active_player_id=p1.id, player_id=p1.id))
    eng.resolve_until_stable()
    assert [o for o in eng.state.battlefield if o.is_token] == []
