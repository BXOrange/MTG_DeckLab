"""BUG-72 - RULE 102.3 / 115.1: a parsed "target opponent" never offers or accepts its own controller.

`resolve_target_kind("target opponent")` used to collapse to the plain `player` pool; it is now the engine's
`opponent` pool, so triggers, spells and bot offers exclude the controller (and include every other seat).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.targeting import legal_targets, spell_target_specs, target_meets_restrictions
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.game_session import GameSession
from tests.test_mec118_opponent_choice import _db_card, _engine, _put

BURN = Card(id="Opp Burn", name="Opp Burn", type_line="Sorcery", is_sorcery=True, mana_cost={"R": 1},
            oracle_text="Opp Burn deals 3 damage to target opponent.")


def _upkeep_trigger(eng):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", active_player_id="p1"))
    eng.rules.put_triggers_on_stack()


def test_phrase_resolves_to_the_opponent_pool():
    assert resolve_target_kind("target opponent") == "opponent"
    assert resolve_target_kind("target player") == "player"


def test_bulwark_trigger_refuses_the_controller():
    eng = _engine(2)
    _put(eng, _db_card("Bulwark"), "p1")
    _upkeep_trigger(eng)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "trigger_target"
    offered = {o["id"] for o in choice["options"]}
    assert offered == {"p2"}
    try:
        eng.resolve_pending_choice("p1")  # the controller is not a legal pick: refused, or the choice stays open
    except Exception:
        pass
    # An answer outside the offered options never targets the controller: nothing aimed at p1 is on the stack.
    assert not any("p1" in repr(getattr(item, "targets", "")) for item in eng.state.stack)
    assert eng.state.player_by_id("p1").life == 20 and eng.state.player_by_id("p2").life == 20


def _cast_burn(players):
    eng = _engine(players)
    spell = _put(eng, BURN, "p1", Zone.HAND)
    caster = eng.state.player_by_id("p1")
    caster.mana_pool.add_many({"R": 1})
    return eng, spell, caster


def test_damage_spell_offers_every_opponent_but_not_the_caster():
    eng, spell, _caster = _cast_burn(3)
    (spec,) = spell_target_specs(spell)
    offered = {t["player_id"] for t in legal_targets(eng.state, "p1", spec, source=spell)}
    assert offered == {"p2", "p3"}


def test_damage_spell_refuses_the_caster_as_target():
    eng, spell, caster = _cast_burn(2)
    (spec,) = spell_target_specs(spell)
    assert not target_meets_restrictions(eng.state, "p1", spec, caster, source=spell)
    assert target_meets_restrictions(eng.state, "p1", spec, eng.state.player_by_id("p2"), source=spell)
    # RULE 608.2b: even a client that announces the caster anyway gets no effect (illegal on resolution).
    eng.cast_spell(caster, spell, targets=[caster])
    eng.resolve_until_stable()
    assert caster.life == 20


def test_damage_spell_hits_the_chosen_opponent_in_three_players():
    eng, spell, caster = _cast_burn(3)
    eng.cast_spell(caster, spell, targets=[eng.state.player_by_id("p3")])
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p3").life == 17
    assert eng.state.player_by_id("p2").life == 20 and caster.life == 20


def test_bot_decisions_never_pick_the_controller():
    from mtg_analyzer.services.bots import create_bot
    eng = _engine(2)
    _put(eng, _db_card("Bulwark"), "p1")
    _upkeep_trigger(eng)
    eng.resolve_until_stable()
    session = GameSession(eng)
    bot = create_bot("smart", "p1", "Bot")
    bot.prepare(session)
    view = session.view(perspective="p1")
    actions = session.legal_actions(perspective="p1")
    assert actions
    for action in actions:
        assert action.get("player_id") != "p1" and action.get("answer") != "p1"
    action = bot.decide(view, actions)
    assert action is None or "p1" not in {action.get("player_id"), action.get("answer"), action.get("target")}


@pytest.mark.parametrize("name", ["Bulwark", "Brash Taunter", "Hedron Detonator", "Hired Claw"])
def test_corrected_cards_stay_modeled_with_the_opponent_kind(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed
    assert '"target_kind": "opponent"' in repr(result.specs).replace("'", '"')


