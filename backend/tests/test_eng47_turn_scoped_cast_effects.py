"""ENG-47 — "when you next cast …" and "can't be countered this turn" without `spell_watchers`.

Two different things had shared one hand-rolled mechanism (`GameState.spell_watchers`):

* "When you next cast an instant or sorcery spell with mana value 4 or less this turn, copy
  that spell" (Dual Strike, Thunderclap Drake) is a *triggered* ability (RULE 603.7a), now the
  one-shot `create_turn_trigger` — so the copy goes on the stack above the spell.
* "Spells you control can't be countered this turn" (Veil of Summer, Domri, Mistrise Village,
  Insist) is a *continuous effect* (RULE 101.2/611.2a), now an `UncounterableGrant` that
  `RulesEngine._is_cant_be_countered` reads. Modelled as a trigger it would have given the
  opponent a window to counter the spell before the marker landed.
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par124_turn_scoped_triggers import _cast, _library, _spell


def _bear(state, *, controller="p1", types="Creature — Bear", name="Bear", mv=0):
    card = Card(id=name, name=name, type_line=types, is_creature="Creature" in types,
                is_instant=types == "Instant", converted_mana_cost=mv,
                **({"power": 2, "toughness": 2} if "Creature" in types else {}))
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    state.player_by_id(controller).hand.append(obj)
    return obj


def _cast_plain(engine, state, obj):
    engine.rules.cast_spell(state.player_by_id(obj.controller_id), obj)
    return obj


# ---------------------------------------------------------------------------
# Dual Strike is now plain parser output
# ---------------------------------------------------------------------------


DUAL_STRIKE = ("When you next cast an instant or sorcery spell with mana value 4 or less this "
               "turn, copy that spell. You may choose new targets for the copy.")


def test_dual_strike_has_no_hand_authored_entry_and_parses():
    assert "dual strike" not in _REGISTRY
    card = Card(id="D", name="Dual Strike", type_line="Instant", is_instant=True,
                oracle_text=DUAL_STRIKE + "\nForetell {R}")
    assert _parse(card).modeled


def test_dual_strike_copies_only_a_cheap_instant_or_sorcery():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    _cast(engine, state, _spell(state, DUAL_STRIKE, types="Instant", name="Dual Strike"))
    p1.mana_pool.add_many({"C": 12})
    life = p1.life
    expensive = _spell(state, "You gain 3 life.", types="Instant", name="Big Heal")
    expensive.card.converted_mana_cost = 5
    _cast(engine, state, expensive)
    assert p1.life == life + 3            # mana value 5: not copied, and "next" is not used up
    cheap = _spell(state, "You gain 3 life.", types="Instant", name="Small Heal")
    cheap.card.converted_mana_cost = 4
    _cast(engine, state, cheap)
    assert p1.life == life + 9            # the spell and its copy


# ---------------------------------------------------------------------------
# "Can't be countered this turn" is a rule, not a trigger
# ---------------------------------------------------------------------------


def test_parse_shapes():
    def specs(text):
        card = Card(id="S", name="S", type_line="Instant", is_instant=True, oracle_text=text)
        result = _parse(card)
        assert result.modeled, text
        return [(e.type, e.params) for s in result.specs for e in s.effects]

    assert specs("Spells you control can't be countered this turn.") == [
        ("cant_be_countered_this_turn", {})]
    assert specs("Creature spells you cast this turn can't be countered.") == [
        ("cant_be_countered_this_turn", {"card_types": ["creature"]})]
    assert specs("The next spell you cast this turn can't be countered.") == [
        ("cant_be_countered_this_turn", {"next_only": True})]
    assert specs("The next instant or sorcery spell you cast this turn can't be countered.") == [
        ("cant_be_countered_this_turn", {"card_types": ["instant", "sorcery"], "next_only": True})]


def test_a_permanents_own_static_line_is_not_taken_for_a_this_turn_grant():
    card = Card(id="S", name="S", type_line="Creature — Sphinx", is_creature=True, power=1,
                toughness=1, oracle_text="Instant and sorcery spells you control can't be countered.")
    for spec in _parse(card).specs:
        assert all(e.type != "cant_be_countered_this_turn" for e in spec.effects)


def _grant(engine, state, text):
    _cast(engine, state, _spell(state, text, types="Instant", name="Veil"))


def test_the_grant_covers_a_spell_already_on_the_stack_and_every_later_one():
    engine, state = _engine()
    state.current_step = "main1"
    early = _cast_plain(engine, state, _bear(state, name="Early"))
    assert not engine.rules._is_cant_be_countered(early)
    _grant(engine, state, "Spells you control can't be countered this turn.")
    assert engine.rules._is_cant_be_countered(early)
    later = _cast_plain(engine, state, _bear(state, name="Later"))
    assert engine.rules._is_cant_be_countered(later)


def test_the_grant_is_the_casters_alone():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "Spells you control can't be countered this turn.")
    mine = _bear(state, name="Mine")
    theirs = _bear(state, controller="p2", name="Theirs")
    assert engine.rules._is_cant_be_countered(mine)
    assert not engine.rules._is_cant_be_countered(theirs)


def test_the_grant_ends_with_the_turn():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "Spells you control can't be countered this turn.")
    bear = _bear(state)
    assert engine.rules._is_cant_be_countered(bear)
    state.internal_turn.number += 1
    assert not engine.rules._is_cant_be_countered(bear)


def test_a_type_qualified_grant_leaves_other_types_counterable():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "Creature spells you cast this turn can't be countered.")
    assert engine.rules._is_cant_be_countered(_bear(state))
    assert not engine.rules._is_cant_be_countered(_bear(state, types="Instant", name="Bolt"))


def test_the_next_spell_grant_protects_exactly_the_next_one():
    engine, state = _engine()
    state.current_step = "main1"
    before = _cast_plain(engine, state, _bear(state, name="Before"))
    _grant(engine, state, "The next spell you cast this turn can't be countered.")
    first = _cast_plain(engine, state, _bear(state, name="First"))
    second = _cast_plain(engine, state, _bear(state, name="Second"))
    assert not engine.rules._is_cant_be_countered(before)
    assert engine.rules._is_cant_be_countered(first)
    assert not engine.rules._is_cant_be_countered(second)


def test_the_next_creature_spell_skips_a_noncreature_cast_first():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "The next creature spell you cast this turn can't be countered.")
    bolt = _cast_plain(engine, state, _bear(state, types="Instant", name="Bolt"))
    bear = _cast_plain(engine, state, _bear(state, name="Bear"))
    other = _cast_plain(engine, state, _bear(state, name="Other"))
    assert not engine.rules._is_cant_be_countered(bolt)
    assert engine.rules._is_cant_be_countered(bear)
    assert not engine.rules._is_cant_be_countered(other)


def test_a_real_counterspell_fails_against_a_protected_spell():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "Spells you control can't be countered this turn.")
    bear = _cast_plain(engine, state, _bear(state, name="Bear"))
    item = next(i for i in state.stack if i.obj is bear)
    engine.rules.counter_unless_pays(item, None)
    assert item in state.stack
    engine.resolve_until_stable()
    assert bear in state.battlefield


def test_the_grant_survives_an_undo_snapshot():
    engine, state = _engine()
    state.current_step = "main1"
    _grant(engine, state, "Spells you control can't be countered this turn.")
    clone = state.clone()
    assert len(clone.uncounterable_grants) == 1
