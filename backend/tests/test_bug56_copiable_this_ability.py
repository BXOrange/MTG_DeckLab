"""BUG-56: "…except it has this ability" is part of the copy's copiable values (RULE 707.9a).

Rule 707.9a's own example: a Clone entering as a copy of an Unstable Shapeshifter that copied Quirion Elves copies the
Elves *and* the ability the Shapeshifter gave itself. Every test drives the real card text on a real `GameEngine`
(effects resolving through the stack, a real Clone cast from the hand), never the copy internals.
"""

from __future__ import annotations

from mtg_analyzer.game import copy_mechanics
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter
from tests.test_par120_count_phrase import _put
from tests.test_par123_referent import _pay
from tests.test_par253_copy_exceptions import (
    CEMETERY_PUCA, DANE, LIKENESS, RESONANCE, UNSTABLE_SHAPESHIFTER, _activate, _bear, _cycle, _resolve_pending,
)

CLONE_ORACLE = "You may have this creature enter as a copy of any creature on the battlefield."
SHIFTER_LINE = "whenever another creature enters, ~ becomes a copy of that creature, except it has this ability."
PUCA_LINE = ("whenever a creature dies, you may pay {1}. if you do, ~ becomes a copy of that creature, except it "
             "has this ability.")
DANE_LINE = "{1}, sacrifice another creature: ~ becomes a copy of the sacrificed creature, except it has this ability."
LOOTER_LINE = ("{x}: ~ becomes a copy of target creature card in your graveyard with mana value x, except it has "
               "flying and this ability. activate only as a sorcery.")
RESONANCE_LINE = ("whenever you cycle a card, you may have ~ become a copy of another target permanent until your "
                  "next turn, except it has this ability.")


def _lines(obj):
    """Printed line of every triggered/activated ability the object has (stable across copies)."""
    return [a.printed_line for a in (*obj.triggered_abilities, *obj.activated_abilities)]


def _cast_clone(engine, state, target):
    """Cast a real Clone from p1's hand and have it enter as a copy of ``target`` (RULE 707.9, 614.1c)."""
    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    state.active_player_id = "p1"
    card = Card(id="Clone", name="Clone", type_line="Creature — Shapeshifter", oracle_text=CLONE_ORACLE,
                is_creature=True, power=0, toughness=0, mana_cost_string="{3}{U}", converted_mana_cost=4)
    clone = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(clone)
    bind_from_catalogue(clone)
    p1.mana_pool.add_many({"U": 1, "C": 3})
    engine.cast_spell(p1, clone)
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    engine.resolve_pending_choice(option["id"])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert clone.zone == Zone.BATTLEFIELD
    return clone


def _shapeshifter_that_copied_elves():
    engine, state = _engine()
    shifter = _put(state, UNSTABLE_SHAPESHIFTER, name="Unstable Shapeshifter", types="Creature — Shapeshifter")
    elves = _bear(state, "Quirion Elves", "{T}: You gain 1 life.", power=1, toughness=1)
    _fire_enter(engine, state, elves)
    engine.recompute_continuous_effects()
    assert shifter.name == "Quirion Elves"
    return engine, state, shifter


# --- Unstable Shapeshifter (RULE 707.9a's own example) -------------------------------------------------------


def test_a_clone_of_the_shapeshifter_gets_the_ability_the_shapeshifter_gave_itself():
    engine, state, shifter = _shapeshifter_that_copied_elves()
    clone = _cast_clone(engine, state, shifter)
    assert clone.name == "Quirion Elves" and clone is not shifter
    assert [a.printed_line for a in clone.triggered_abilities] == [SHIFTER_LINE]
    assert len(clone.activated_abilities) == 1  # the Elves' own ability, once
    trigger, original = clone.triggered_abilities[0], shifter.triggered_abilities[0]
    # The kept ability is bound for the clone: its source is the clone, and nothing is shared with the original.
    assert trigger.source is clone and trigger is not original and trigger.effects is not original.effects
    assert all(e.source is clone for e in trigger.effects if hasattr(e, "source"))
    assert all(e is not o for e in trigger.effects for o in original.effects)


def test_the_clones_ability_works_and_each_permanent_triggers_exactly_once(monkeypatch):
    engine, state, shifter = _shapeshifter_that_copied_elves()
    clone = _cast_clone(engine, state, shifter)
    late = _bear(state, "Late Bloomer", "Flying", power=3, toughness=3)
    copies = []
    real_become_copy = copy_mechanics.become_copy
    monkeypatch.setattr(copy_mechanics, "become_copy",
                        lambda obj, *args, **kw: (copies.append(obj), real_become_copy(obj, *args, **kw))[1])
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id="p1", card_id=late.card.id,
                               object=late.name, instance_id=late.instance_id, object_types=sorted(late.type_words)))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    # One resolution for the Shapeshifter and one for the Clone: the ability exists once on each, not twice.
    assert sorted(o.instance_id for o in copies) == sorted([shifter.instance_id, clone.instance_id])
    for permanent in (shifter, clone):
        assert permanent.name == "Late Bloomer" and permanent.power == 3
        assert [a.printed_line for a in permanent.triggered_abilities] == [SHIFTER_LINE]  # replaced, not stacked up
        assert permanent.triggered_abilities[0].source is permanent


def test_a_clone_of_a_clone_still_has_the_ability_and_a_later_copy_replaces_the_copied_form():
    engine, state, shifter = _shapeshifter_that_copied_elves()
    first = _cast_clone(engine, state, shifter)
    second = _cast_clone(engine, state, first)
    assert [a.printed_line for a in second.triggered_abilities] == [SHIFTER_LINE]
    assert second.triggered_abilities[0].source is second
    late = _bear(state, "Wall", "Defender", power=0, toughness=5)
    _fire_enter(engine, state, late)
    engine.recompute_continuous_effects()
    # The third-generation copy used its inherited ability, became the Wall and kept exactly the one ability.
    assert second.name == "Wall" and second.toughness == 5 and not second.activated_abilities
    assert [a.printed_line for a in second.triggered_abilities] == [SHIFTER_LINE]
    assert first.name == "Wall" and shifter.name == "Wall"


def test_a_plain_shapeshifter_copied_before_it_changed_shape_gains_no_extra_copy_of_the_ability():
    engine, state = _engine()
    shifter = _put(state, UNSTABLE_SHAPESHIFTER, name="Unstable Shapeshifter", types="Creature — Shapeshifter")
    clone = _cast_clone(engine, state, shifter)
    assert [a.printed_line for a in clone.triggered_abilities] == [SHIFTER_LINE]  # its printed one, once
    assert clone.card.granted_ability_lines == ()


def test_copiable_values_carry_the_ability_as_plain_text():
    engine, state, shifter = _shapeshifter_that_copied_elves()
    assert shifter.card.granted_ability_lines == (SHIFTER_LINE,)
    clone = _cast_clone(engine, state, shifter)
    assert clone.card.granted_ability_lines == (SHIFTER_LINE,)
    assert clone._front_card.granted_ability_lines == (SHIFTER_LINE,)
    assert clone.card is not shifter.card  # a fresh Card, so the two permanents share no copiable state


# --- Cemetery Puca (a triggered ability, not an activated one as the ticket said) ----------------------------


def test_a_clone_of_cemetery_puca_triggers_on_a_death_and_copies_it_while_keeping_the_ability():
    engine, state = _engine()
    puca = _put(state, CEMETERY_PUCA, name="Cemetery Puca", types="Creature — Shapeshifter")
    victim = _bear(state, "Victim", "Flying", power=4, toughness=4)
    state.player_by_id("p1").mana_pool.add("C", 1)
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    _pay(engine, state)
    engine.recompute_continuous_effects()
    assert puca.name == "Victim" and _lines(puca) == [PUCA_LINE]
    clone = _cast_clone(engine, state, puca)
    assert clone.name == "Victim" and [a.printed_line for a in clone.triggered_abilities] == [PUCA_LINE]
    assert clone.triggered_abilities[0].source is clone
    # Both Pucas see the next death; the Clone's ability works with the correct source and keeps itself.
    other = _bear(state, "Other", "Trample", power=2, toughness=2)
    state.player_by_id("p1").mana_pool.add_many({"C": 2})
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    while state.pending_choice and state.pending_choice["kind"] == "pay_cost_then":
        _pay(engine, state)
    engine.recompute_continuous_effects()
    assert clone.name == "Other" and puca.name == "Other"
    assert [a.printed_line for a in clone.triggered_abilities] == [PUCA_LINE]
    assert [a.printed_line for a in puca.triggered_abilities] == [PUCA_LINE]


# --- The Ever-Changing 'Dane (activated) ---------------------------------------------------------------------


def test_a_clone_of_the_dane_has_the_activated_ability_once_and_can_use_it():
    engine, state = _engine()
    state.current_step = "main1"
    dane = _put(state, DANE, name="The Ever-Changing 'Dane", types="Creature — Shapeshifter")
    fodder = _bear(state, "Fodder", "{T}: You gain 1 life.", power=4, toughness=1)
    state.player_by_id("p1").mana_pool.add("C", 2)
    _activate(engine, state, dane, 0)
    engine.recompute_continuous_effects()
    assert dane.name == "Fodder" and fodder.zone == Zone.GRAVEYARD
    clone = _cast_clone(engine, state, dane)
    assert clone.name == "Fodder"
    lines = [a.printed_line for a in clone.activated_abilities]
    assert lines.count(DANE_LINE) == 1 and len(lines) == 2  # Fodder's own ability plus the Dane's, no duplicates
    index = lines.index(DANE_LINE)
    assert clone.activated_abilities[index].source is clone
    engine.rules.destroy(dane)  # only the new creature is left to sacrifice
    engine.resolve_until_stable()
    fodder_two = _bear(state, "Second", "Flying", power=1, toughness=1)
    state.player_by_id("p1").mana_pool.add("C", 1)
    _activate(engine, state, clone, index)
    engine.recompute_continuous_effects()
    assert clone.name == "Second" and fodder_two.zone == Zone.GRAVEYARD
    assert [a.printed_line for a in clone.activated_abilities] == [DANE_LINE]


# --- Likeness Looter ------------------------------------------------------------------------------------------


def test_a_clone_of_likeness_looter_can_copy_a_graveyard_creature_too():
    engine, state = _engine()
    state.current_step = "main1"
    looter = _put(state, LIKENESS, name="Likeness Looter", types="Creature — Faerie Shapeshifter")
    looter.card.keywords = ["Flying"]
    p1 = state.player_by_id("p1")
    dead = GameObject(Card(id="Dead", name="Dead Ogre", type_line="Creature — Ogre", is_creature=True, power=5,
                           toughness=4, converted_mana_cost=2, oracle_text="Trample"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    p1.mana_pool.add("C", 2)
    _activate(engine, state, looter, len(looter.activated_abilities) - 1, targets=[dead], x=2)
    engine.recompute_continuous_effects()
    assert looter.name == "Dead Ogre" and _lines(looter).count(LOOTER_LINE) == 1
    clone = _cast_clone(engine, state, looter)
    lines = [a.printed_line for a in clone.activated_abilities]
    assert clone.name == "Dead Ogre" and lines == [LOOTER_LINE]  # exactly one X ability (the Ogre has none)
    ability = clone.activated_abilities[0]
    assert ability.source is clone
    second = GameObject(Card(id="Imp", name="Dead Imp", type_line="Creature — Imp", is_creature=True, power=1,
                             toughness=1, converted_mana_cost=1, oracle_text="Flying"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(second)
    p1.mana_pool.add("C", 1)
    _activate(engine, state, clone, 0, targets=[second], x=1)
    engine.recompute_continuous_effects()
    assert clone.name == "Dead Imp" and [a.printed_line for a in clone.activated_abilities] == [LOOTER_LINE]
    assert looter.name == "Dead Ogre"


# --- Crystalline Resonance: a timed copy -------------------------------------------------------------------


def test_a_timed_copy_that_expires_restores_without_stranding_or_doubling_the_ability():
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "main1"
    resonance = _put(state, RESONANCE, name="Crystalline Resonance", types="Enchantment")
    _put(state, "{T}: You gain 1 life.", name="Ring", types="Artifact")
    _cycle(engine, state)
    _resolve_pending(engine, state, 0)
    engine.recompute_continuous_effects()
    assert resonance.name == "Ring"
    assert _lines(resonance).count(RESONANCE_LINE) == 1
    clone = _cast_clone_noncreature(engine, state, resonance)
    assert clone.name == "Ring" and _lines(clone).count(RESONANCE_LINE) == 1
    for _ in range(3):  # the turns pass until the Resonance's controller's next turn begins (RULE 611.2b)
        engine.begin_turn()
        engine.recompute_continuous_effects()
    assert resonance.name == "Crystalline Resonance"
    assert _lines(resonance) == [RESONANCE_LINE.replace("this ability", "this ability")]
    assert resonance.card.granted_ability_lines == ()
    # The Clone's copy is permanent, so it keeps the Ring and the ability the Resonance had given itself.
    assert clone.name == "Ring" and _lines(clone).count(RESONANCE_LINE) == 1


def _cast_clone_noncreature(engine, state, target):
    """A Clone-like permanent spell that can copy a non-creature (Phyrexian Metamorph's real wording)."""
    p1 = state.player_by_id("p1")
    state.active_player_id = "p1"
    state.current_step = "main1"
    text = ("You may have this creature enter as a copy of any artifact or creature on the battlefield, except it's "
            "an artifact in addition to its other types.")
    card = Card(id="Metamorph", name="Metamorph", type_line="Artifact Creature — Phyrexian Shapeshifter",
                oracle_text=text, is_creature=True, power=0, toughness=0, mana_cost_string="{3}{U}",
                converted_mana_cost=4)
    clone = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(clone)
    bind_from_catalogue(clone)
    p1.mana_pool.add_many({"U": 1, "C": 3})
    engine.cast_spell(p1, clone)
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    engine.resolve_pending_choice(option["id"])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    return clone


# --- Aurora Shifter: the kept ability plus a quoted one --------------------------------------------------------


def test_a_clone_of_aurora_shifter_has_both_abilities_once_each():
    from tests.test_par207_trigger_heads import _answer, _board, _engine as _eng207, _plain, _settle

    eng = _eng207()
    p1 = eng.state.player_by_id("p1")
    shifter = _board(eng, "Aurora Shifter")
    ally = _plain(eng, "Ally")
    ally.card.power, ally.card.toughness = 5, 5
    p1.add_counters("energy", 2)
    eng.state.current_step = "begin_combat"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1"))
    _settle(eng)
    _answer(eng, "pay")
    _settle(eng)
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice(ally.instance_id)
        _settle(eng)
    eng.recompute_continuous_effects()
    assert shifter.name == "Ally"
    clone = _cast_clone(eng, eng.state, shifter)
    lines = [a.printed_line for a in clone.triggered_abilities]
    assert clone.name == "Ally" and len(lines) == 2 and len(set(lines)) == 2  # the two Aurora abilities, no copies
    assert any(line.startswith("at the beginning of combat on your turn") for line in lines)
    assert any(line.startswith("whenever ~ deals combat damage to a player") for line in lines)
    assert all(a.source is clone for a in clone.triggered_abilities)


# --- Through GameSession.apply_action, with undo --------------------------------------------------------------


def test_session_clone_of_the_dane_gets_the_ability_and_rewind_restores_the_copiable_values():
    from tests.test_bug59_modal_activation_session import _act, _card, _pool, _put as _session_put, _session

    session, engine, state = _session()
    p1 = state.player_by_id("p1")
    dane = _session_put(state, _card("The Ever-Changing 'Dane", "Legendary Creature — Shapeshifter", DANE))
    _session_put(state, _card("Fodder", "Creature — Bear", "{T}: You gain 1 life.", power=4, toughness=1))
    _pool(state, 2)
    session.apply_action(_act(dane), "p1")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert dane.name == "Fodder" and dane.card.granted_ability_lines == (DANE_LINE,)

    clone_card = Card(id="Clone", name="Clone", type_line="Creature — Shapeshifter", oracle_text=CLONE_ORACLE,
                      is_creature=True, power=0, toughness=0, mana_cost_string="{3}{U}", converted_mana_cost=4)
    clone = GameObject(clone_card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(clone)
    bind_from_catalogue(clone)
    p1.mana_pool.add_many({"U": 1, "C": 3})
    cast = next(a for a in session.legal_actions("p1") if a.get("type") == "cast_spell"
                and a["instance_id"] == clone.instance_id)
    session.apply_action(cast, "p1")
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice and choice["kind"] == "enter_as_copy"
    pick = {"type": "choose", "option_id": next(o["id"] for o in choice["options"]
                                                 if o.get("instance_id") == dane.instance_id)}
    session.apply_action(pick, "p1")
    engine.resolve_until_stable()
    entered = next(o for o in session.engine.state.battlefield if o.card.name == "Fodder"
                   and o.instance_id != dane.instance_id)
    assert [a.printed_line for a in entered.activated_abilities].count(DANE_LINE) == 1

    assert entered.card.granted_ability_lines == (DANE_LINE,)
    engine.rules.destroy(dane)  # so the new creature is the only one left to sacrifice
    engine.resolve_until_stable()
    spare = _session_put(state, _card("Spare", "Creature — Bear", "Flying", power=1, toughness=1))
    state.player_by_id("p1").mana_pool.add("C", 1)
    offered = [a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
               and a["instance_id"] == entered.instance_id and a.get("description", "").lower().startswith("{1},")]
    assert len(offered) == 1  # one entry per printed ability: no duplicate in legal_actions
    session.apply_action(offered[0], "p1")
    session.engine.resolve_until_stable()
    session.engine.recompute_continuous_effects()
    assert entered.name == "Spare" and spare.zone == Zone.GRAVEYARD
    assert [a.printed_line for a in entered.activated_abilities] == [DANE_LINE]

    # Undo the Clone's copy: the restored snapshot has the Clone as a Fodder again, with the ability bound to it.
    session.rewind(1)
    state = session.engine.state
    restored = next(o for o in state.battlefield if o.instance_id == entered.instance_id)
    assert restored is not entered and restored.name == "Fodder"
    assert [a.printed_line for a in restored.activated_abilities].count(DANE_LINE) == 1
    ability = next(a for a in restored.activated_abilities if a.printed_line == DANE_LINE)
    assert ability.source is restored and restored.card.granted_ability_lines == (DANE_LINE,)
    # ... and the ability still works after the undo.
    state.player_by_id("p1").mana_pool.add("C", 1)
    again = next(a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
                 and a["instance_id"] == restored.instance_id and a.get("description", "").lower().startswith("{1},"))
    session.apply_action(again, "p1")
    session.engine.resolve_until_stable()
    session.engine.recompute_continuous_effects()
    assert restored.name == "Spare"


def test_a_second_trigger_waiting_on_the_stack_still_finds_this_ability_after_the_first_copy_rebuilt_it():
    # Cemetery Puca ruling: two creatures dying together trigger it twice; both can be paid and it ends up a copy of the
    # last one, still with its ability (the second trigger's printed ability object was replaced by the first copy).
    engine, state = _engine()
    puca = _put(state, CEMETERY_PUCA, name="Cemetery Puca", types="Creature — Shapeshifter")
    first = _bear(state, "First", "Flying", power=2, toughness=2)
    second = _bear(state, "Second", "Trample", power=3, toughness=3)
    state.player_by_id("p1").mana_pool.add_many({"C": 2})
    engine.rules.destroy(first)
    engine.rules.destroy(second)
    engine.resolve_until_stable()
    guard = 0
    while state.pending_choice and state.pending_choice["kind"] == "pay_cost_then" and guard < 4:
        guard += 1
        _pay(engine, state)
    engine.recompute_continuous_effects()
    assert guard == 2 and puca.name in {"First", "Second"}
    assert [a.printed_line for a in puca.triggered_abilities].count(PUCA_LINE) == 1
