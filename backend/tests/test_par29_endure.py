"""PAR-29 — RULE 701.63 "Endure N" (Bloomburrow).

The permanent's controller either puts N +1/+1 counters on it, or creates an
N/N white Spirit creature token. `RulesEngine.endure` owns the modal `endure`
`pending_choice`; `effects.EndureEffect` resolves which permanent endures
(self / previous-clause / target, mirroring `explore`).

Reference: game/rules/misc_mixin.py (`endure` / `resolve_endure_choice`),
game/effects.py (`EndureEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_endure_subject_shapes_parse():
    assert match_clause("~ endures 3") == [EffectSpec("endure", {"amount": 3})]
    assert match_clause("it endures 3") is None
    assert match_clause("it endures 3", self_subject=True) == [
        EffectSpec("endure", {"amount": 3})
    ]
    assert match_clause("that creature endures 2", previous_subject=True) == [
        EffectSpec("endure", {"amount": 2, "previous_subject": True})
    ]
    assert match_clause("target creature you control endures 1") == [
        EffectSpec("endure", {"amount": 1, "target_kind": "creature_you_control"})
    ]
    assert match_clause("it endures x", self_subject=True) is None


def test_real_endure_card_modeled_end_to_end():
    dusyut = Card(id="DE", name="Dusyut Earthcarver",
                  type_line="Creature — Elephant Druid", is_creature=True,
                  power=0, toughness=0, keywords=["Reach"],
                  oracle_text="Reach\nWhen this creature enters, it endures 3. "
                              "(Put three +1/+1 counters on it or create a 3/3 "
                              "white Spirit creature token.)")
    assert parse_oracle(dusyut).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state, eng.state.player_by_id("p1")


def _creature(name="C", power=2, tough=2):
    card = Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=tough)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    return obj


def test_endure_opens_modal_choice_counters_branch():
    eng, state, p1 = _engine()
    c = _creature()
    state.add_to_battlefield(c)

    eng.rules.endure(c, 3)
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "endure"
    assert {o["id"] for o in choice["options"]} == {"counters", "token"}

    eng.resolve_pending_choice("counters")
    assert state.pending_choice is None
    assert c.plus_one_counters == 3
    assert not any(o.name == "Spirit" for o in state.battlefield)


def test_endure_token_branch_makes_n_by_n_white_spirit():
    eng, state, p1 = _engine()
    c = _creature()
    state.add_to_battlefield(c)

    eng.rules.endure(c, 2)
    eng.resolve_pending_choice("token")

    spirits = [o for o in state.battlefield if o.name == "Spirit"]
    assert len(spirits) == 1
    sp = spirits[0]
    assert (sp.power, sp.toughness) == (2, 2)
    assert sp.is_creature and sp.is_token
    assert sp.colors == {"W"}
    assert c.plus_one_counters == 0


def test_endure_default_answer_is_counters():
    eng, state, p1 = _engine()
    c = _creature()
    state.add_to_battlefield(c)

    eng.rules.endure(c, 1)
    eng.resolve_pending_choice(None)

    assert c.plus_one_counters == 1
    assert not any(o.name == "Spirit" for o in state.battlefield)


def test_endure_no_choice_when_permanent_is_gone():
    eng, state, p1 = _engine()
    c = _creature()
    # not on the battlefield → only the token option is possible (RULE 608.2b)
    eng.rules.endure(c, 4, player=p1)

    assert state.pending_choice is None
    spirits = [o for o in state.battlefield if o.name == "Spirit"]
    assert len(spirits) == 1
    assert (spirits[0].power, spirits[0].toughness) == (4, 4)


def test_endure_via_binder_on_etb():
    eng, state, p1 = _engine()
    card = Card(id="DE", name="Dusyut Earthcarver",
                type_line="Creature — Elephant Druid", is_creature=True,
                power=3, toughness=3, keywords=["Reach"],
                oracle_text="Reach\nWhen this creature enters, it endures 3.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "endure"
