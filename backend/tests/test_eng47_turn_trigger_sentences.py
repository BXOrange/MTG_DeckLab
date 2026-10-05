"""ENG-47 — a turn-long "whenever … this turn" as a *sentence* of a larger body.

PAR-124 parsed the trigger only when it was a whole line ("Whenever a creature enters this
turn, draw a card."). It is just as often one sentence of an ability or a spell — after an
"if C," gate (Ruinous Waterbending, Warhost's Frenzy), after a first effect (Death Frenzy), or
as the body of an activated or chapter ability (Dalkovan Encampment, Basri, Showdown of the
Skalds). These execute the cards, because a parse verdict says nothing about what fires.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par124_turn_scoped_triggers import _cast, _library, _spell
from tests.test_par119_attack_batch_head import _attack, _attackers


def _permanent(state, name, types, oracle, controller="p1", **kw):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle, **kw)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _turn_trigger_effects(oracle, types="Sorcery"):
    card = Card(id="S", name="S", type_line=types, oracle_text=oracle,
                is_instant=types == "Instant", is_sorcery=types == "Sorcery")
    result = _parse(card)
    assert result.modeled, oracle
    return [e for s in result.specs for e in s.effects if e.type == "create_turn_trigger"]


def test_a_sentence_after_an_if_gate_carries_the_gate():
    (effect,) = _turn_trigger_effects(
        "Creatures you control get +2/+0 until end of turn. If this spell was kicked, whenever a "
        "creature you control dies this turn, draw a card.\nKicker {B}")
    assert effect.condition is not None and "kicked" in str(effect.condition)


def test_warhost_frenzy_draws_on_a_death_only_when_kicked():
    for kicked, expected in ((True, 1), (False, 0)):
        engine, state = _engine()
        state.current_step = "main1"
        p1 = _library(state)
        p1.mana_pool.add_many({"B": 5, "C": 5})
        victim = _attackers(state, [("Victim", "Creature — Bear", [])])[0]
        spell = _spell(state, "Creatures you control get +2/+0 until end of turn. If this spell was "
                              "kicked, whenever a creature you control dies this turn, draw a card.\n"
                              "Kicker {B}", name="Warhost's Frenzy")
        spell.kicker_count = 1 if kicked else 0
        _cast(engine, state, spell)
        before = len(p1.hand)
        engine.rules.destroy(victim)
        engine.resolve_until_stable()
        assert len(p1.hand) - before == expected, kicked


def test_a_chapter_ability_creates_a_trigger_for_the_turn():
    (effect,) = _turn_trigger_effects(
        "(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)\n"
        "I — You draw two cards and you lose 2 life.\n"
        "II, III — Whenever a creature you control enters this turn, each opponent loses 1 life and "
        "you gain 1 life.", types="Enchantment — Saga")
    assert effect.params["trigger"]["event"] == "ENTERS_BATTLEFIELD"


def test_dalkovan_encampment_makes_two_tapped_attacking_warriors_that_are_sacrificed():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    land = _permanent(
        state, "Dalkovan Encampment", "Land", (
            "This land enters tapped unless you control a Swamp or a Mountain.\n{T}: Add {W}.\n"
            "{2}{W}, {T}: Whenever you attack this turn, create two 1/1 red Warrior creature tokens "
            "that are tapped and attacking. Sacrifice them at the beginning of the next end step."),
        is_land=True)
    (bear,) = _attackers(state, [("Bear", "Creature — Bear", [])])
    index = next(i for i, a in enumerate(land.activated_abilities)
                 if any(e.__class__.__name__ == "CreateTurnTriggerEffect" for e in a.effects))
    p1.mana_pool.add_many({"W": 1, "C": 2})
    engine.activate_ability(p1, land, ability_index=index)
    engine.resolve_until_stable()
    assert len(state.turn_scoped_triggers) == 1

    state.current_phase = "combat"
    _attack(engine, state, [bear])
    warriors = [o for o in state.battlefield if o.name == "Warrior"]
    assert len(warriors) == 2
    assert all(w.tapped and w.attacking for w in warriors)

    state.current_step = "end"
    engine._fire_delayed_triggers("end")
    engine.resolve_until_stable()
    assert not [o for o in state.battlefield if o.name == "Warrior"]
    assert bear in state.battlefield                     # "them" is the tokens, not the attacker


def test_golden_guardian_returns_transformed_if_it_dies_the_turn_it_was_activated():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    guardian = _permanent(
        state, "Golden Guardian", "Creature — Golem", (
            "Defender\n{2}: This creature fights another target creature you control. When this "
            "creature dies this turn, return it to the battlefield transformed under your control."),
        is_creature=True, power=4, toughness=4, layout="transform",
        back_name="Gold-Forge Garrison", back_type_line="Land — Cave")
    (friend,) = _attackers(state, [("Friend", "Creature — Bear", [])])
    index = next(i for i, a in enumerate(guardian.activated_abilities)
                 if any(e.__class__.__name__ == "CreateTurnTriggerEffect" for e in a.effects))
    p1.mana_pool.add_many({"C": 2})
    engine.activate_ability(p1, guardian, ability_index=index, targets=[friend])
    engine.resolve_until_stable()
    assert len(state.turn_scoped_triggers) == 1
    if guardian in state.battlefield:
        engine.rules.destroy(guardian)
        engine.resolve_until_stable()
    assert guardian in state.battlefield and guardian.transformed


def test_a_targeted_body_picks_its_target_when_the_trigger_fires():
    # Showdown of the Skalds II/III: the target is chosen when the trigger goes on the stack,
    # not when the chapter ability creates it.
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    (bear,) = _attackers(state, [("Bear", "Creature — Bear", [])])
    _cast(engine, state, _spell(
        state, "Whenever you cast a spell this turn, put a +1/+1 counter on target creature you "
               "control.", name="Chapter"))
    assert len(state.turn_scoped_triggers) == 1
    _cast(engine, state, _spell(state, "You gain 1 life.", types="Instant", name="Heal"))
    if state.pending_choice:
        engine.resolve_pending_choice(str(bear.instance_id))
        engine.resolve_until_stable()
    assert bear.counters.get("+1/+1", 0) == 1
    _cast(engine, state, _spell(state, "You gain 1 life.", types="Instant", name="Heal2"))
    if state.pending_choice:
        engine.resolve_pending_choice(str(bear.instance_id))
        engine.resolve_until_stable()
    assert bear.counters.get("+1/+1", 0) == 2            # not "next": every spell this turn


# ---------------------------------------------------------------------------
# A phase trigger's leading "if `<state>`," (Celebration, descended) — RULE 603.4
# ---------------------------------------------------------------------------

from mtg_analyzer.models.game.events import EventType, GameEvent  # noqa: E402


LADY = ("Flying\nCelebration — At the beginning of your end step, if two or more nonland "
        "permanents entered the battlefield under your control this turn, draw a card.")
SCALLYWAG = ("At the beginning of your end step, if you descended this turn, create a Treasure "
             "token. (You descended if a permanent card was put into your graveyard from anywhere.)")


def _end_step(engine, state):
    state.current_step = "end"
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.resolve_until_stable()


def _enter(state, name="Thing", types="Artifact", controller="p1", token=False):
    card = Card(id=name, name=name, type_line=types, is_land="Land" in types)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.is_token = token
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=controller, object=name,
                               instance_id=obj.instance_id, object_types=sorted(obj.type_words)))
    return obj


def test_celebration_counts_nonland_permanents_that_entered_under_your_control_this_turn():
    for entered, expected in ((["Artifact", "Creature — Bear"], 1), (["Artifact"], 0),
                              (["Artifact", "Land"], 0)):
        engine, state = _engine()
        p1 = _library(state)
        _permanent(state, "Lady of Laughter", "Creature — Faerie", LADY, is_creature=True,
                   power=2, toughness=2, keywords=["Flying", "Celebration"])
        for i, types in enumerate(entered):
            _enter(state, f"E{i}", types)
        before = len(p1.hand)
        _end_step(engine, state)
        assert len(p1.hand) - before == expected, entered


def test_celebration_ignores_permanents_entering_under_an_opponents_control():
    engine, state = _engine()
    p1 = _library(state)
    _permanent(state, "Lady of Laughter", "Creature — Faerie", LADY, is_creature=True,
               power=2, toughness=2, keywords=["Flying", "Celebration"])
    _enter(state, "A", "Artifact", controller="p2")
    _enter(state, "B", "Artifact", controller="p2")
    before = len(p1.hand)
    _end_step(engine, state)
    assert len(p1.hand) == before


def test_you_descended_is_a_permanent_card_reaching_your_graveyard():
    engine, state = _engine()
    _permanent(state, "Enterprising Scallywag", "Creature — Goblin Pirate", SCALLYWAG,
               is_creature=True, power=1, toughness=1)
    _end_step(engine, state)
    assert not [o for o in state.battlefield if o.name == "Treasure"]      # nothing died

    victim = _attackers(state, [("Victim", "Creature — Bear", [])])[0]
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    _end_step(engine, state)
    assert len([o for o in state.battlefield if o.name == "Treasure"]) == 1


def test_a_dying_token_is_not_a_card_and_does_not_make_you_descend():
    engine, state = _engine()
    _permanent(state, "Enterprising Scallywag", "Creature — Goblin Pirate", SCALLYWAG,
               is_creature=True, power=1, toughness=1)
    token = _attackers(state, [("Token", "Creature — Bear", [])])[0]
    token.is_token = True
    engine.rules.destroy(token)
    engine.resolve_until_stable()
    _end_step(engine, state)
    assert not [o for o in state.battlefield if o.name == "Treasure"]


# ---------------------------------------------------------------------------
# "committed a crime this turn" (RULE 700.13) — an event fired where targets are chosen
# ---------------------------------------------------------------------------

SHOCK = "Shock deals 2 damage to any target."
SLICKSHOT = ("Vigilance\nThis creature gets +2/+0 as long as you've committed a crime this turn. "
             "(Targeting opponents, anything they control, and/or cards in their graveyards is a crime.)")


def _crimes(state):
    return [e for e in state.events_this_turn() if e.type == EventType.CRIME_COMMITTED]


def _bolt(state, controller="p1"):
    return _spell(state, SHOCK, types="Instant", name="Shock", owner=controller)


def test_targeting_an_opponents_permanent_is_a_crime():
    engine, state = _engine()
    state.current_step = "main1"
    (theirs,) = _attackers(state, [("Theirs", "Creature — Bear", [])], owner="p2")
    engine.rules.cast_spell(state.player_by_id("p1"), _bolt(state), targets=[theirs])
    assert len(_crimes(state)) == 1 and _crimes(state)[0].get("player_id") == "p1"


def test_targeting_an_opponent_is_a_crime_and_your_own_things_are_not():
    engine, state = _engine()
    state.current_step = "main1"
    (mine,) = _attackers(state, [("Mine", "Creature — Bear", [])])
    engine.rules.cast_spell(state.player_by_id("p1"), _bolt(state), targets=[mine])
    engine.rules.cast_spell(state.player_by_id("p1"), _bolt(state), targets=[state.player_by_id("p1")])
    assert not _crimes(state)
    engine.rules.cast_spell(state.player_by_id("p1"), _bolt(state), targets=[state.player_by_id("p2")])
    assert len(_crimes(state)) == 1


def test_a_card_in_an_opponents_graveyard_is_hostile_and_in_your_own_is_not():
    for owner, crimes in (("p2", 1), ("p1", 0)):
        engine, state = _engine()
        card = Card(id="G", name="G", type_line="Creature — Bear", is_creature=True, power=1, toughness=1)
        obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
        state.player_by_id(owner).graveyard.append(obj)
        from mtg_analyzer.models.game.game_state import StackItem
        engine.rules._note_crime(StackItem(kind="spell", controller_id="p1", effects=[], targets=[obj]))
        assert len(_crimes(state)) == crimes, owner


def test_an_activated_ability_that_targets_your_own_creature_is_no_crime():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    guardian = _permanent(
        state, "Golden Guardian", "Creature — Golem", (
            "Defender\n{2}: This creature fights another target creature you control. When this "
            "creature dies this turn, return it to the battlefield transformed under your control."),
        is_creature=True, power=4, toughness=4)
    (friend,) = _attackers(state, [("Friend", "Creature — Bear", [])])
    index = next(i for i, a in enumerate(guardian.activated_abilities)
                 if any(e.__class__.__name__ == "CreateTurnTriggerEffect" for e in a.effects))
    p1.mana_pool.add_many({"C": 2})
    engine.activate_ability(p1, guardian, ability_index=index, targets=[friend])
    assert not _crimes(state)


def test_slickshot_vault_buster_gets_plus_two_only_after_a_crime():
    engine, state = _engine()
    state.current_step = "main1"
    buster = _permanent(state, "Slickshot Vault-Buster", "Creature — Human Rogue", SLICKSHOT,
                        is_creature=True, power=2, toughness=2, keywords=["Vigilance"])
    engine.recompute_continuous_effects()
    assert buster.power == 2
    (theirs,) = _attackers(state, [("Theirs", "Creature — Bear", [])], owner="p2")
    engine.rules.cast_spell(state.player_by_id("p1"), _bolt(state), targets=[theirs])
    engine.recompute_continuous_effects()
    assert buster.power == 4
    state.internal_turn.number += 1                       # the next turn: a new window
    engine.recompute_continuous_effects()
    assert buster.power == 2


def test_subira_draws_only_for_a_small_creature_dealing_combat_damage_to_a_player():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    small, big = _attackers(state, [("Small", "Creature — Bear", []), ("Big", "Creature — Ogre", [])])
    big.card.power = 3
    engine.recompute_continuous_effects()
    _cast(engine, state, _spell(
        state, "Until end of turn, whenever a creature you control with power 2 or less deals "
               "combat damage to a player, draw a card.", name="Subira's Ability"))
    before = len(p1.hand)
    engine.rules.deal_damage(state.player_by_id("p2"), 3, source=big, combat=True)
    engine.resolve_until_stable()
    assert len(p1.hand) == before
    engine.rules.deal_damage(state.player_by_id("p2"), 2, source=small, combat=True)
    engine.resolve_until_stable()
    assert len(p1.hand) == before + 1
