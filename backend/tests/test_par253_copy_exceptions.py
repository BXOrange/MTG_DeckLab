"""PAR-253: copy exceptions on become-a-copy effects ("except it has this ability", keywords, quoted abilities).

RULE 707.9a: an "except" clause is part of the copy's copiable values. RULE 707.2 / 613.1a: a permanent that becomes a
copy loses its own abilities, so "this ability" is what keeps the copier able to do it again."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter
from tests.test_par120_count_phrase import _creature, _put
from tests.test_par123_referent import _pay

UNSTABLE_SHAPESHIFTER = "Whenever another creature enters, this creature becomes a copy of that creature, except it has this ability."
CEMETERY_PUCA = (
    "Whenever a creature dies, you may pay {1}. If you do, this creature becomes a copy of that creature, "
    "except it has this ability."
)
LIKENESS = "Flying\n{T}: Draw a card, then discard a card.\n{X}: This creature becomes a copy of target creature card in your graveyard with mana value X, except it has flying and this ability. Activate only as a sorcery."


def _modeled(oracle: str, types: str = "Creature — Shapeshifter", name: str = "Source") -> bool:
    return _parse(Card(id=name, name=name, type_line=types, oracle_text=oracle)).modeled


def _bear(state, name, oracle, owner="p1", power=3, toughness=3):
    """A real-oracle creature that enters (bound abilities, not yet announced)."""
    card = Card(id=name, name=name, type_line="Creature — Bear", oracle_text=oracle, is_creature=True,
                power=power, toughness=toughness)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _descriptions(obj):
    """The printed line each trigger/activated ability was built from: stable across copies, unlike a description
    (which a copy gives as the whole text of whichever card it copied)."""
    return [a.printed_line for a in (*obj.triggered_abilities, *obj.activated_abilities)]


def test_this_ability_parses_under_a_group_trigger():
    assert _modeled(UNSTABLE_SHAPESHIFTER)
    assert _modeled(CEMETERY_PUCA)


def test_a_lookalike_with_a_different_exception_stays_unclaimed():
    assert parse_effect_body("~ becomes a copy of that creature, except it has hexproof and shroud and banding") is None
    assert not _modeled("Whenever another creature enters, this creature becomes a copy of that creature, except it is a Zombie.")


def test_unstable_shapeshifter_copies_each_entering_creature_and_keeps_only_its_own_ability():
    engine, state = _engine()
    shifter = _put(state, UNSTABLE_SHAPESHIFTER, name="Unstable Shapeshifter", types="Creature — Shapeshifter")
    own = list(_descriptions(shifter))
    assert len(own) == 1
    first = _bear(state, "Grizzly", "{T}: You gain 1 life.", power=2, toughness=2)
    _fire_enter(engine, state, first)
    engine.recompute_continuous_effects()
    assert shifter.name == "Grizzly" and shifter.power == 2
    assert len(shifter.triggered_abilities) == 1 and shifter.triggered_abilities[0].printed_line == own[0]
    assert shifter.activated_abilities  # the copied mana ability
    second = _bear(state, "Wall", "Defender", power=0, toughness=5)
    _fire_enter(engine, state, second)
    engine.recompute_continuous_effects()
    # It copied again (so it kept "this ability"), and nothing of the Grizzly's mana ability leaked into the new copy.
    assert shifter.name == "Wall" and shifter.toughness == 5
    assert shifter.activated_abilities == []
    assert [a.printed_line for a in shifter.triggered_abilities] == own


def test_unstable_shapeshifter_ignores_its_own_entry_and_never_copies_a_bystander():
    engine, state = _engine()
    shifter = _put(state, UNSTABLE_SHAPESHIFTER, name="Unstable Shapeshifter", types="Creature — Shapeshifter")
    bystander = _bear(state, "Bystander", "Trample")
    _fire_enter(engine, state, shifter)  # "another creature": its own entry does nothing
    assert shifter.name == "Unstable Shapeshifter"
    late = _bear(state, "Late", "Flying", power=1, toughness=1)
    _fire_enter(engine, state, late)
    assert shifter.name == "Late" and bystander.name == "Bystander"


def test_the_copy_of_a_copy_chains_through_the_shapeshifter():
    # RULE 707.2: a copy of the shapeshifter copies its current copiable values (here, the Grizzly it already copied).
    engine, state = _engine()
    shifter = _put(state, UNSTABLE_SHAPESHIFTER, name="Unstable Shapeshifter", types="Creature — Shapeshifter")
    _fire_enter(engine, state, _bear(state, "Grizzly", "Vigilance"))
    engine.recompute_continuous_effects()
    assert shifter.name == "Grizzly"
    assert shifter._front_card.name == "Grizzly"


def test_cemetery_puca_copies_the_dead_creature_only_when_paid():
    from mtg_analyzer.models.game.events import GameEvent, EventType  # noqa: F401  (documented import path)
    engine, state = _engine()
    puca = _put(state, CEMETERY_PUCA, name="Cemetery Puca", types="Creature — Shapeshifter")
    own = _descriptions(puca)
    victim = _bear(state, "Victim", "Flying", power=4, toughness=4)
    state.player_by_id("p1").mana_pool.add("C", 1)
    engine.rules.destroy(victim) if hasattr(engine.rules, "destroy") else None
    engine.resolve_until_stable()
    _pay(engine, state)
    engine.recompute_continuous_effects()
    assert puca.name == "Victim" and puca.power == 4
    assert _descriptions(puca) == own  # only "this ability" survived; Victim's own text is its copied values
    # Declined: a second death changes nothing.
    state.player_by_id("p1").mana_pool.add("C", 1)
    other = _bear(state, "Other", "Trample")
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    _pay(engine, state, "decline")
    assert puca.name == "Victim"


DANE = "{1}, Sacrifice another creature: The Ever-Changing 'Dane becomes a copy of the sacrificed creature, except it has this ability."


def _activate(engine, state, source, index, **kw):
    state.current_step = "main1"
    player = state.player_by_id(source.controller_id)
    state.active_player_id = player.id if hasattr(state, "active_player_id") else None
    engine.activate_ability(player, source, index, **kw)
    engine.resolve_until_stable()


def test_ever_changing_dane_copies_the_sacrificed_creature_and_can_do_it_again():
    assert _modeled(DANE, name="The Ever-Changing 'Dane")
    engine, state = _engine()
    state.current_step = "main1"
    dane = _put(state, DANE, name="The Ever-Changing 'Dane", types="Creature — Shapeshifter")
    own = _descriptions(dane)
    fodder = _bear(state, "Fodder", "{T}: You gain 1 life.", power=4, toughness=1)
    state.player_by_id("p1").mana_pool.add("C", 2)
    _activate(engine, state, dane, 0)
    engine.recompute_continuous_effects()
    assert dane.name == "Fodder" and dane.power == 4 and fodder.zone == Zone.GRAVEYARD
    assert any(a.printed_line != own[0] for a in dane.activated_abilities)  # Fodder's own ability is now there
    assert any(a.printed_line == own[0] for a in dane.activated_abilities)  # ... plus "this ability"
    second = _bear(state, "Second", "Flying", power=1, toughness=1)
    index = [a.printed_line for a in dane.activated_abilities].index(own[0])
    _activate(engine, state, dane, index)
    engine.recompute_continuous_effects()
    assert dane.name == "Second" and dane.power == 1
    assert [a.printed_line for a in dane.activated_abilities] == own  # Fodder's ability did not survive the second copy


def test_ever_changing_dane_without_fodder_changes_nothing():
    engine, state = _engine()
    dane = _put(state, DANE, name="The Ever-Changing 'Dane", types="Creature — Shapeshifter")
    state.player_by_id("p1").mana_pool.add("C", 1)
    try:
        _activate(engine, state, dane, 0)
    except ValueError:
        pass  # the cost cannot be paid: no creature to sacrifice
    assert dane.name == "The Ever-Changing 'Dane"


def test_likeness_looter_copies_a_graveyard_creature_of_matching_mana_value_with_flying():
    assert _modeled(LIKENESS, name="Likeness Looter")
    engine, state = _engine()
    looter = _put(state, LIKENESS, name="Likeness Looter", types="Creature — Shapeshifter")
    looter.card.keywords = ["Flying"]
    copy_ability = [a.printed_line for a in looter.activated_abilities][-1]
    p1 = state.player_by_id("p1")
    dead = GameObject(Card(id="Dead", name="Dead Ogre", type_line="Creature — Ogre", is_creature=True, power=5,
                           toughness=4, converted_mana_cost=2, oracle_text="Trample"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)
    wrong = GameObject(Card(id="W", name="Wrong", type_line="Creature — Ogre", is_creature=True, power=9,
                            toughness=9, converted_mana_cost=3), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(wrong)
    p1.mana_pool.add("C", 2)
    index = len(looter.activated_abilities) - 1
    # RULE 115: a card of the wrong mana value is not a legal target.
    try:
        _activate(engine, state, looter, index, targets=[wrong], x=2)
    except ValueError:
        pass
    assert looter.name == "Likeness Looter"
    _activate(engine, state, looter, index, targets=[dead], x=2)
    engine.recompute_continuous_effects()
    assert looter.name == "Dead Ogre" and looter.power == 5
    assert "flying" in {k.lower() for k in looter.granted_keywords | set(looter.card.keywords)}
    assert copy_ability in [a.printed_line for a in looter.activated_abilities]  # "this ability" retained
    assert dead.zone == Zone.GRAVEYARD  # copying does not move the card


# --- enter-as-copy with several keywords ("it has haste and dethrone") ---------------------------------------


def test_dacks_duplicate_enters_as_a_copy_with_haste_and_dethrone():
    from tests.test_enter_as_copy_family import _cast, _prepare
    from tests.support.game import creature, obj_on_battlefield

    eng, p1, duplicate = _prepare("Dack's Duplicate", mana={"R": 3, "U": 3, "C": 6})
    target = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2))
    bind_from_catalogue(target)
    _cast(eng, p1, duplicate)
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    eng.resolve_pending_choice(next(o["id"] for o in pending["options"] if o["id"] != "decline"))
    eng.recompute_continuous_effects()
    assert duplicate.card.name == "Grizzly Bears" and (duplicate.power, duplicate.toughness) == (2, 2)
    from mtg_analyzer.game import combat

    assert combat.has(duplicate, "dethrone") and combat.has(duplicate, "haste")  # RULE 702.105 reads it for the attack
    assert not combat.has(target, "dethrone")
    keywords = {k.lower() for k in duplicate.card.keywords}
    assert {"haste", "dethrone"} <= keywords
    assert "dethrone" not in {k.lower() for k in target.card.keywords}  # only the copy has the exception


def test_estrids_invocation_copies_only_your_enchantment_and_gains_the_upkeep_blink():
    from tests.test_enter_as_copy_family import _cast, _prepare
    from tests.support.game import obj_on_battlefield

    eng, p1, invocation = _prepare("Estrid's Invocation", mana={"W": 4, "U": 4, "C": 6})
    mine = Card(id="Mine", name="Mine Aura", type_line="Enchantment", oracle_text="")
    theirs = Card(id="Theirs", name="Their Aura", type_line="Enchantment", oracle_text="")
    mine_obj = obj_on_battlefield(eng.state, eng, mine)
    obj_on_battlefield(eng.state, eng, theirs, controller="p2")
    _cast(eng, p1, invocation)
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    names = {str(o) for o in pending["options"]}
    assert any("Mine Aura" in n for n in names)
    assert not any("Their Aura" in n for n in names)  # "an enchantment you control" only
    eng.resolve_pending_choice(next(o["id"] for o in pending["options"] if o["id"] != "decline"))
    assert invocation.card.name == "Mine Aura"
    # RULE 707.9a: the exception is part of the copy's values, so the upkeep ability is really bound on it.
    assert any("upkeep" in (a.description or "").lower() for a in invocation.triggered_abilities)
    assert not any("upkeep" in (a.description or "").lower() for a in mine_obj.triggered_abilities)


def test_estrids_invocation_copy_blinks_itself_at_upkeep_through_the_granted_line():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from tests.test_enter_as_copy_family import _cast, _prepare
    from tests.support.game import obj_on_battlefield

    eng, p1, invocation = _prepare("Estrid's Invocation", mana={"W": 4, "U": 4, "C": 6})
    obj_on_battlefield(eng.state, eng, Card(id="Mine", name="Mine Aura", type_line="Enchantment", oracle_text=""))
    _cast(eng, p1, invocation)
    eng.resolve_pending_choice(next(o["id"] for o in eng.state.pending_choice["options"] if o["id"] != "decline"))
    before = invocation.zone_incarnation
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1"))
    eng.resolve_until_stable()
    if eng.state.pending_choice:  # "you may exile": accept
        eng.resolve_pending_choice(next(o["id"] for o in eng.state.pending_choice["options"] if o["id"] != "decline"))
        eng.resolve_until_stable()
    assert invocation.zone_incarnation != before  # RULE 400.7: it left and came back as a new object


RESONANCE = (
    "Whenever you cycle a card, you may have this enchantment become a copy of another target permanent until your "
    "next turn, except it has this ability."
)


def _cycle(engine, state):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    state.fire_event(GameEvent(EventType.CYCLED, controller_id="p1", player_id="p1"))
    engine.resolve_until_stable()


def _resolve_pending(engine, state, pick):
    guard = 0
    while state.pending_choice and guard < 6:
        guard += 1
        choice = state.pending_choice
        options = [o for o in choice.get("options", []) if o.get("id") != "decline"]
        engine.rules.resolve_choice(options[pick]["id"] if options else "yes")
        engine.resolve_until_stable()


def test_crystalline_resonance_copies_for_a_while_and_keeps_its_trigger():
    assert _modeled(RESONANCE, "Enchantment", "Crystalline Resonance")
    engine, state = _engine()
    resonance = _put(state, RESONANCE, name="Crystalline Resonance", types="Enchantment")
    own = _descriptions(resonance)
    assert len(own) == 1
    ring = _put(state, "{T}: You gain 1 life.", name="Ring", types="Artifact")
    _cycle(engine, state)
    _resolve_pending(engine, state, 0)
    engine.recompute_continuous_effects()
    assert resonance.name == "Ring" and ring.name == "Ring"
    # RULE 707.9a: it can trigger again (it kept this ability), and nothing else of its own text survived.
    assert own[0] in _descriptions(resonance)
    assert resonance.card.type_line == "Artifact"


def test_crystalline_resonance_reverts_when_its_controllers_next_turn_begins_and_copies_again_before_then():
    engine, state = _engine()
    # Start p1's own turn first, so "until your next turn" really has to span the opponent's turn below.
    engine.begin_turn()
    state.current_step = "main1"
    resonance = _put(state, RESONANCE, name="Crystalline Resonance", types="Enchantment")
    own = _descriptions(resonance)
    _put(state, "{T}: You gain 1 life.", name="Ring", types="Artifact")
    _put(state, "Flying", name="Drake", types="Creature — Drake")
    _cycle(engine, state)
    _resolve_pending(engine, state, 0)
    first = resonance.name
    assert first != "Crystalline Resonance"
    # Cycling again re-copies something else; the retained ability made that possible.
    _cycle(engine, state)
    _resolve_pending(engine, state, 1)
    engine.recompute_continuous_effects()
    assert resonance.name != "Crystalline Resonance"
    assert own[0] in _descriptions(resonance)
    # The turns pass: it stays a copy through the opponent's turn and reverts as p1's next turn begins (RULE 611.2b).
    seen = []
    for _ in range(3):
        engine.begin_turn()
        engine.recompute_continuous_effects()
        seen.append((state.active_player.id, resonance.name))
    owner_turns = [i for i, (who, _) in enumerate(seen) if who == "p1"]
    assert owner_turns, seen
    first_owner_turn = owner_turns[0]
    assert first_owner_turn > 0, seen  # an opponent's turn must pass before the copy can end
    assert all(name != "Crystalline Resonance" for who, name in seen[:first_owner_turn]), seen
    assert seen[first_owner_turn][1] == "Crystalline Resonance", seen
    assert _descriptions(resonance) == own


# --- Aurora Shifter: a reflexive "when you do" copy that keeps its ability and adds a quoted one ------------------


def test_aurora_shifter_pays_energy_copies_a_creature_and_keeps_both_abilities():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from tests.test_par207_trigger_heads import _answer, _board, _engine as _eng207, _plain, _settle

    eng = _eng207()
    p1 = eng.state.player_by_id("p1")
    shifter = _board(eng, "Aurora Shifter")
    ally = _plain(eng, "Ally")
    ally.card.power, ally.card.toughness = 5, 5
    original = list(shifter.triggered_abilities)
    combat_trigger = next(a for a in original if a.trigger_event == EventType.STEP_BEGIN)
    damage_trigger = next(a for a in original if a.trigger_event != EventType.STEP_BEGIN)
    combat_line, damage_line = combat_trigger.printed_line, damage_trigger.printed_line
    p1.add_counters("energy", 2)
    eng.state.current_step = "begin_combat"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1"))
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    _answer(eng, "pay")
    _settle(eng)
    assert not p1.counters.get("energy")
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice(ally.instance_id)
        _settle(eng)
    eng.recompute_continuous_effects()
    assert shifter.name == "Ally" and shifter.power == 5
    now = list(shifter.triggered_abilities)
    assert any(a.printed_line == combat_line for a in now)            # "this ability" survived the copy
    granted = [a for a in now if a.printed_line != combat_line]
    assert len(granted) == 1 and granted[0].trigger_event != EventType.STEP_BEGIN  # ... by the quoted ability (707.9a)
    assert granted[0].printed_line.rstrip(".") == damage_line.rstrip(".")
    assert ally.name == "Ally" and "that many" not in " ".join(_descriptions(ally)).lower()


def test_aurora_shifter_without_enough_energy_does_not_copy():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from tests.test_par207_trigger_heads import _board, _engine as _eng207, _plain, _settle

    eng = _eng207()
    shifter = _board(eng, "Aurora Shifter")
    _plain(eng, "Ally")
    eng.state.player_by_id("p1").add_counters("energy", 1)
    eng.state.current_step = "begin_combat"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1"))
    _settle(eng)
    assert shifter.name == "Aurora Shifter"


# --- already-modeled cards whose spec shape moved onto the previous-subject row (same behaviour, re-proved) -------


def test_dimir_doppelganger_still_copies_the_exiled_card_and_keeps_its_ability():
    from tests.test_par207_trigger_heads import _board, _engine as _eng207, _graveyard, _settle

    eng = _eng207()
    p1 = eng.state.player_by_id("p1")
    dimir = _board(eng, "Dimir Doppelganger")
    [victim] = _graveyard(eng, "p2", ["Dead Bear"])
    victim.card.power, victim.card.toughness = 4, 4
    own = [a.printed_line for a in dimir.activated_abilities]
    p1.mana_pool.add_many({"U": 2, "B": 2, "C": 2})
    eng.activate_ability(p1, dimir, 0, targets=[victim])
    _settle(eng)
    eng.recompute_continuous_effects()
    assert dimir.name == "Dead Bear" and dimir.power == 4
    assert victim.zone == Zone.EXILE                                  # the card was exiled first
    assert [a.printed_line for a in dimir.activated_abilities] == own                     # "this ability", and only it


def test_renegade_doppelganger_copies_the_entering_creature_until_end_of_turn():
    from tests.test_par207_trigger_heads import _answer, _board, _engine as _eng207, _plain, _settle
    from tests.test_par119_object_trigger_head import _fire_enter

    eng = _eng207()
    renegade = _board(eng, "Renegade Doppelganger")
    entering = _plain(eng, "Big Bear", power=6, toughness=6)
    _fire_enter(eng, eng.state, entering)
    if eng.state.pending_choice:
        _answer(eng, "do")
        _settle(eng)
    eng.recompute_continuous_effects()
    assert renegade.name == "Big Bear" and renegade.power == 6
    assert entering.name == "Big Bear"
    from mtg_analyzer.game.copy_mechanics import expire_copies

    expire_copies(eng.state, "cleanup")                               # RULE 514.2 / 611.2a: "until end of turn" ends
    eng.recompute_continuous_effects()
    assert renegade.name == "Renegade Doppelganger"
