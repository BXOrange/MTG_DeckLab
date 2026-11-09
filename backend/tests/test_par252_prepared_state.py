"""PAR-252: the prepared designation beyond the self form (RULE 722.3a-c).

Target and each-creature "becomes prepared", "becomes unprepared", and the intervening-if "if ~ isn't prepared"
(RULE 603.4: checked when the trigger would go on the stack *and* again on resolution). Every card text below is the
real Oracle text; each test runs the real engine, not just the parser."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter

HEXHAVEN = (
    "{T}: Add {C}.\n"
    "{2}, {T}: Target creature that attacked this turn becomes prepared. Activate only as a sorcery. "
    "(Only creatures with prepare spells can become prepared.)\n"
    "{4}, {T}: Target creature becomes prepared."
)
SKYCOACH = (
    "{T}: Add {C}.\n"
    "{3}, {T}: Target creature becomes prepared. (Only creatures with prepare spells can become prepared.)"
)
CODIE = (
    "Whenever you cast a prepared spell, copy it. You may choose new targets for the copy.\n"
    "{W}{U}{B}{R}{G}, {T}: Each creature you control becomes prepared. "
    "(Only creatures with prepare spells can become prepared.)"
)
CODIE_ACTIVATION = "{W}{U}{B}{R}{G}, {T}: Each creature you control becomes prepared."
TOMEKEEPER = (
    "When this creature enters, choose up to one —\n"
    "• Target creature becomes prepared. (Only creatures with prepare spells can become prepared.)\n"
    "• Target creature becomes unprepared."
)
COURSEWORK = (
    "Enchant creature\n"
    "When this Aura enters, tap enchanted creature. It becomes unprepared.\n"
    "Enchanted creature loses all abilities and doesn't untap during its controller's untap step."
)
COURSEWORK_ETB = "Enchant creature\nWhen this Aura enters, tap enchanted creature. It becomes unprepared."
PARADOX = (
    "At the beginning of your upkeep, if this creature isn't prepared, it becomes prepared.\n"
    "{2}: Put target card from your graveyard on the bottom of your library."
)
STINGERQUILL = (
    "At the beginning of your upkeep, if this creature isn't prepared, it becomes prepared. "
    "(While it's prepared, you may cast a copy of its spell. Doing so unprepares it.)"
)
JOINED = (
    "First strike\n"
    "At the beginning of each end step, if an opponent has more cards in hand than you, this creature becomes "
    "prepared. (While it's prepared, you may cast a copy of its spell. Doing so unprepares it.)"
)


def _card(name: str, oracle: str, types: str = "Creature — Bear", **kw) -> Card:
    creature = "Creature" in types
    return Card(
        id=name, name=name, type_line=types, oracle_text=oracle, is_creature=creature,
        power=2 if creature else None, toughness=2 if creature else None, **kw,
    )


def _prepare_card(name: str = "Prep", oracle: str = "", owner_kw: dict | None = None) -> Card:
    """A creature with a prepare spell (RULE 722.2a)."""
    return _card(
        name, oracle, layout="prepare", back_name=f"{name} Spell", back_type_line="Sorcery",
        back_mana_cost_string="{1}{B}", back_oracle_text="You gain 1 life.", **(owner_kw or {}),
    )


def _put(state, card: Card, owner: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _vanilla_prepare(state, name: str = "Prep", owner: str = "p1") -> GameObject:
    return _put(state, _prepare_card(name), owner)


def _plain(state, name: str = "Plain", owner: str = "p1") -> GameObject:
    return _put(state, _card(name, ""), owner)


def _exile_copies(state, source: GameObject) -> list[GameObject]:
    return [o for p in state.players for o in p.exile if o.prepared_source_id == source.instance_id]


def _ability_index(obj: GameObject, mana_cost: str) -> int:
    """The activated ability whose mana cost is ``mana_cost`` (every ability of a card shares its full description)."""
    for i, ability in enumerate(obj.activated_abilities):
        if f"'{mana_cost}'" in str(ability.cost.mana).lower():
            return i
    raise AssertionError(f"no ability costing {mana_cost}: {[str(a.cost.mana) for a in obj.activated_abilities]}")


def _pay(state, player_id: str, **mana: int) -> None:
    pool = state.player_by_id(player_id).mana_pool
    for colour, amount in mana.items():
        pool.add(colour.upper(), amount)


def _activate(engine, state, source: GameObject, mana_cost: str, targets=None, **mana: int) -> None:
    _pay(state, "p1", **mana)
    source.summoning_sick = False  # the {T} in these costs needs a creature that has been under control since the turn began
    engine.activate_ability(state.player_by_id("p1"), source, _ability_index(source, mana_cost), targets=targets)
    engine.resolve_until_stable()


def _upkeep(engine, state) -> None:
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1"))
    engine.rules.put_triggers_on_stack()


def _modeled(oracle: str, types: str = "Creature — Bear") -> bool:
    return parse_oracle(_card("Probe", oracle, types)).modeled


# --------------------------------------------------------------------------------------------------------------
# Parsing: every named card, and the near-misses that must stay unclaimed.
# --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name, oracle, types", [
    ("Skycoach Waypoint", SKYCOACH, "Land"),
    ("Hexhaven Dueling Arena", HEXHAVEN, "Land"),
    ("Biblioplex Tomekeeper", TOMEKEEPER, "Artifact Creature — Construct"),
    ("Paradox Shaper", PARADOX, "Creature — Octopus Wizard"),
    ("Stingerquill Voxmancer", STINGERQUILL, "Creature — Goblin Sorcerer"),
    ("Joined Researchers", JOINED, "Creature — Human Cleric Wizard"),
])
def test_named_cards_parse_as_modeled(name, oracle, types):
    assert parse_oracle(_card(name, oracle, types)).modeled


def test_codie_activation_parses_but_the_whole_card_stays_unmodeled():
    # "Whenever you cast a prepared spell, copy it." (a spell-cast-via-prepare-spell predicate) is a separate gap.
    assert not parse_oracle(_card("Codie", CODIE, "Legendary Artifact Creature — Book Construct")).modeled
    only_activation = parse_oracle(_card("Codie", CODIE_ACTIVATION, "Legendary Artifact Creature — Book Construct"))
    assert only_activation.modeled
    assert [(e.type, e.params) for s in only_activation.specs for e in s.effects] == [
        ("become_prepared", {"selector": "creatures_you_control"})
    ]


def test_infinite_coursework_unprepare_clause_parses_but_the_whole_card_stays_unmodeled():
    # "Enchanted creature loses all abilities and doesn't untap ..." is a separate gap.
    assert not parse_oracle(_card("Infinite Coursework", COURSEWORK, "Enchantment — Aura")).modeled
    etb = parse_oracle(_card("Infinite Coursework", COURSEWORK_ETB, "Enchantment — Aura"))
    triggered = [s for s in etb.specs if s.ability_kind == "triggered"]
    assert [e.type for e in triggered[0].effects] == ["tap", "become_unprepared"]
    assert triggered[0].effects[1].params == {"previous_subject": True}


@pytest.mark.parametrize("oracle", [
    "{3}, {T}: Target creature becomes prepared with a flourish.",   # trailing words left over
    "{3}, {T}: Target permanent becomes prepared.",               # only creatures have prepare spells
])
def test_lookalike_prepared_clauses_stay_unclaimed(oracle):
    assert not _modeled(oracle, "Land")


def test_the_intervening_if_is_not_claimed_for_a_different_subject_or_state():
    assert not _modeled("At the beginning of your upkeep, if target creature isn't prepared, it becomes prepared.")
    assert not _modeled("At the beginning of your upkeep, if this creature isn't unprepared, it becomes prepared.")


def test_choose_up_to_one_is_only_claimed_for_a_triggered_ability():
    spec = parse_oracle(_card("Tomekeeper", TOMEKEEPER, "Artifact Creature — Construct")).specs[0]
    assert spec.modes["optional"] is True and spec.modes["choose"] == 1
    # A modal *spell* has no optional-mode path in the engine, so the header must not be silently reread as "choose one".
    assert not _modeled("Choose up to one —\n• Draw a card.\n• You gain 2 life.", "Sorcery")


# --------------------------------------------------------------------------------------------------------------
# Engine behaviour.
# --------------------------------------------------------------------------------------------------------------

def test_skycoach_waypoint_prepares_the_target_and_puts_the_copy_in_its_controllers_exile():
    engine, state = _engine()
    waypoint = _put(state, _card("Skycoach Waypoint", SKYCOACH, "Land"))
    bear = _vanilla_prepare(state, "Foe Bear", owner="p2")
    _activate(engine, state, waypoint, "{3}", targets=[bear], c=3)
    assert bear.prepared is True
    (copy,) = _exile_copies(state, bear)
    assert copy.card.name == "Foe Bear Spell"
    assert copy in state.player_by_id("p2").exile  # RULE 722.3c: the permanent's controller holds the copy


def test_a_creature_without_a_prepare_spell_cannot_become_prepared():
    # RULE 722.3a: "A permanent can't gain this designation unless it has a prepare spell."
    engine, state = _engine()
    waypoint = _put(state, _card("Skycoach Waypoint", SKYCOACH, "Land"))
    plain = _plain(state)
    _activate(engine, state, waypoint, "{3}", targets=[plain], c=3)
    assert plain.prepared is False
    assert not any(p.exile for p in state.players)


def test_preparing_an_already_prepared_creature_makes_no_second_copy():
    engine, state = _engine()
    waypoint = _put(state, _card("Skycoach Waypoint", SKYCOACH, "Land"))
    bear = _vanilla_prepare(state)
    engine.rules.make_prepared(bear)
    _activate(engine, state, waypoint, "{3}", targets=[bear], c=3)
    assert len(_exile_copies(state, bear)) == 1


def test_hexhaven_second_ability_prepares_any_creature():
    engine, state = _engine()
    arena = _put(state, _card("Hexhaven Dueling Arena", HEXHAVEN, "Land"))
    bear = _vanilla_prepare(state)
    _activate(engine, state, arena, "{4}", targets=[bear], c=4)
    assert bear.prepared is True


def test_hexhaven_attacked_this_turn_ability_only_targets_creatures_that_attacked():
    engine, state = _engine()
    state.current_step = "main1"
    arena = _put(state, _card("Hexhaven Dueling Arena", HEXHAVEN, "Land"))
    attacker = _vanilla_prepare(state, "Attacker")
    idle = _vanilla_prepare(state, "Idle")
    attacker.attacked_this_turn = True
    from mtg_analyzer.game.targeting import legal_targets

    ability = arena.activated_abilities[_ability_index(arena, "{2}")]
    legal = {o.get("instance_id") for o in legal_targets(state, "p1", ability.effects[0].target_spec, source=arena)}
    assert attacker.instance_id in legal and idle.instance_id not in legal
    _activate(engine, state, arena, "{2}", targets=[attacker], c=2)
    assert attacker.prepared is True and idle.prepared is False


def test_codie_prepares_every_creature_you_control_and_only_those_with_a_prepare_spell():
    engine, state = _engine()
    codie = _put(state, _card("Codie", CODIE_ACTIVATION, "Legendary Artifact Creature — Book Construct"))
    mine_a = _vanilla_prepare(state, "Mine A")
    mine_b = _vanilla_prepare(state, "Mine B")
    plain = _plain(state)
    theirs = _vanilla_prepare(state, "Theirs", owner="p2")
    _activate(engine, state, codie, "{w}{u}{b}{r}{g}", w=1, u=1, b=1, r=1, g=1)
    assert mine_a.prepared and mine_b.prepared
    assert not plain.prepared and not theirs.prepared
    assert len(_exile_copies(state, mine_a)) == 1 and len(_exile_copies(state, mine_b)) == 1
    assert _exile_copies(state, theirs) == []


def test_tomekeeper_prepares_a_target_when_that_mode_is_chosen():
    engine, state = _engine()
    bear = _vanilla_prepare(state)
    keeper = _put(state, _card("Biblioplex Tomekeeper", TOMEKEEPER, "Artifact Creature — Construct"))
    _fire_enter(engine, state, keeper)
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_mode"
    engine.rules.resolve_choice("0")
    _finish_targeting(engine, state, bear)
    assert bear.prepared is True and len(_exile_copies(state, bear)) == 1


def test_tomekeeper_unprepares_a_target_when_that_mode_is_chosen():
    engine, state = _engine()
    bear = _vanilla_prepare(state)
    engine.rules.make_prepared(bear)
    assert len(_exile_copies(state, bear)) == 1
    keeper = _put(state, _card("Biblioplex Tomekeeper", TOMEKEEPER, "Artifact Creature — Construct"))
    _fire_enter(engine, state, keeper)
    engine.rules.resolve_choice("1")
    _finish_targeting(engine, state, bear)
    assert bear.prepared is False
    # RULE 722.3c: the exiled copy lived only while the designation did.
    assert _exile_copies(state, bear) == []


def test_tomekeeper_may_choose_nothing():
    engine, state = _engine()
    bear = _vanilla_prepare(state)
    keeper = _put(state, _card("Biblioplex Tomekeeper", TOMEKEEPER, "Artifact Creature — Construct"))
    _fire_enter(engine, state, keeper)
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert bear.prepared is False and _exile_copies(state, bear) == []


def test_unpreparing_a_creature_that_is_not_prepared_does_nothing():
    engine, state = _engine()
    land = _put(state, _card("Unprepare Land", "{3}, {T}: Target creature becomes unprepared.", "Land"))
    bear = _vanilla_prepare(state)
    _activate(engine, state, land, "{3}", targets=[bear], c=3)
    assert bear.prepared is False and _exile_copies(state, bear) == []


def test_unpreparing_a_prepared_creature_removes_the_designation_and_its_exiled_copy():
    engine, state = _engine()
    land = _put(state, _card("Unprepare Land", "{3}, {T}: Target creature becomes unprepared.", "Land"))
    bear = _vanilla_prepare(state)
    engine.rules.make_prepared(bear)
    _activate(engine, state, land, "{3}", targets=[bear], c=3)
    assert bear.prepared is False and _exile_copies(state, bear) == []


def test_casting_the_exiled_copy_still_unprepares_the_source():
    # The pre-existing self-form path (RULE 722.3c) must keep working next to the new unprepare primitive.
    engine, state = _engine()
    bear = _vanilla_prepare(state)
    engine.rules.make_prepared(bear)
    (copy,) = _exile_copies(state, bear)
    player = state.player_by_id("p1")
    for colour in "WUBRGC":
        player.mana_pool.add(colour, 5)
    state.current_step = "main1"
    state.active_player_id = "p1"
    engine.cast_spell(player, copy, targets=None)
    engine.resolve_until_stable()
    assert bear.prepared is False


def test_infinite_coursework_taps_the_host_and_unprepares_it():
    engine, state = _engine()
    host = _vanilla_prepare(state, "Host")
    engine.rules.make_prepared(host)
    aura_card = _card("Infinite Coursework", COURSEWORK_ETB, "Enchantment — Aura")
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    bind_from_catalogue(aura)
    state.add_to_battlefield(aura)
    aura.attached_to = host.instance_id
    _fire_enter(engine, state, aura)
    assert host.tapped is True
    assert host.prepared is False
    assert _exile_copies(state, host) == []


def test_infinite_coursework_leaves_an_unprepared_host_alone():
    engine, state = _engine()
    host = _vanilla_prepare(state, "Host")
    aura = GameObject(_card("Infinite Coursework", COURSEWORK_ETB, "Enchantment — Aura"), owner_id="p1",
                      zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    bind_from_catalogue(aura)
    state.add_to_battlefield(aura)
    aura.attached_to = host.instance_id
    _fire_enter(engine, state, aura)
    assert host.tapped is True and host.prepared is False


# --------------------------------------------------------------------------------------------------------------
# The intervening-if (RULE 603.4): checked when the trigger would be put on the stack, and again on resolution.
# --------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("oracle", [PARADOX, STINGERQUILL])
def test_upkeep_trigger_prepares_an_unprepared_creature(oracle):
    engine, state = _engine()
    shaper = _put(state, _prepare_card("Shaper", oracle))
    _upkeep(engine, state)
    assert len(state.stack) == 1
    engine.resolve_until_stable()
    assert shaper.prepared is True and len(_exile_copies(state, shaper)) == 1


@pytest.mark.parametrize("oracle", [PARADOX, STINGERQUILL])
def test_intervening_if_fails_at_trigger_time_when_already_prepared(oracle):
    engine, state = _engine()
    shaper = _put(state, _prepare_card("Shaper", oracle))
    engine.rules.make_prepared(shaper)
    _upkeep(engine, state)
    assert state.stack == []  # never put on the stack, so nothing to resolve
    engine.resolve_until_stable()
    assert shaper.prepared is True and len(_exile_copies(state, shaper)) == 1


def test_intervening_if_is_rechecked_on_resolution_for_the_isnt_prepared_form():
    engine, state = _engine()
    shaper = _put(state, _prepare_card("Shaper", PARADOX))
    _upkeep(engine, state)
    assert len(state.stack) == 1  # it was unprepared when the trigger was put on the stack ...
    engine.rules.make_prepared(shaper)  # ... and got prepared in response
    engine.resolve_until_stable()
    # Resolution saw "isn't prepared" fail: no second designation, no second copy.
    assert shaper.prepared is True and len(_exile_copies(state, shaper)) == 1


def test_a_prepared_upkeep_trigger_resolves_with_nothing_if_the_source_left_the_battlefield():
    engine, state = _engine()
    shaper = _put(state, _prepare_card("Shaper", STINGERQUILL))
    _upkeep(engine, state)
    state.battlefield.remove(shaper)
    shaper.zone = Zone.GRAVEYARD
    state.player_by_id("p1").graveyard.append(shaper)
    engine.resolve_until_stable()
    assert shaper.prepared is False and not any(p.exile for p in state.players)


def _fill_hand(state, player_id: str, count: int) -> None:
    hand = state.player_by_id(player_id).hand
    for n in range(count):
        hand.append(GameObject(_card(f"Filler {player_id}{n}", "", "Sorcery"), owner_id=player_id, zone=Zone.HAND))


def _end_step(engine, state) -> None:
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1"))
    engine.rules.put_triggers_on_stack()


def test_joined_researchers_prepares_when_an_opponent_holds_more_cards():
    engine, state = _engine()
    researcher = _put(state, _prepare_card("Researcher", JOINED))
    _fill_hand(state, "p2", 2)
    _end_step(engine, state)
    assert len(state.stack) == 1
    engine.resolve_until_stable()
    assert researcher.prepared is True


def test_joined_researchers_does_not_trigger_when_no_opponent_has_more_cards():
    engine, state = _engine()
    researcher = _put(state, _prepare_card("Researcher", JOINED))
    _fill_hand(state, "p1", 2)
    _fill_hand(state, "p2", 2)  # equal is not "more"
    _end_step(engine, state)
    assert state.stack == []  # trigger-time check failed
    engine.resolve_until_stable()
    assert researcher.prepared is False


def test_joined_researchers_rechecks_the_condition_on_resolution():
    engine, state = _engine()
    researcher = _put(state, _prepare_card("Researcher", JOINED))
    _fill_hand(state, "p2", 2)
    _end_step(engine, state)
    assert len(state.stack) == 1  # condition held when the trigger was put on the stack ...
    state.player_by_id("p2").hand.clear()  # ... and no longer does when it resolves
    engine.resolve_until_stable()
    assert researcher.prepared is False and _exile_copies(state, researcher) == []


def _finish_targeting(engine, state, target: GameObject) -> None:
    """Answer the target prompt a chosen mode opens, then let the stack resolve."""
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target", choice
    option = next(o for o in choice["options"] if o.get("instance_id") == target.instance_id)
    engine.rules.resolve_choice(option["id"])
    engine.resolve_until_stable()


def test_the_composition_layer_fans_an_unqualified_each_creature_form_over_both_players():
    # "Each creature becomes prepared/unprepared" (no "you control") is claimed by the generic for-each fan-out; the
    # effect must honour it per creature, and still skip a creature with no prepare spell.
    engine, state = _engine()
    prepare = _put(state, _card("Mass Prepare", "{3}, {T}: Each creature becomes prepared.", "Land"))
    unprepare = _put(state, _card("Mass Unprepare", "{3}, {T}: Each creature becomes unprepared.", "Land"))
    mine, theirs, plain = _vanilla_prepare(state, "Mine"), _vanilla_prepare(state, "Theirs", owner="p2"), _plain(state)
    _activate(engine, state, prepare, "{3}", c=3)
    assert mine.prepared and theirs.prepared and not plain.prepared
    _activate(engine, state, unprepare, "{3}", c=3)
    assert not mine.prepared and not theirs.prepared
    assert _exile_copies(state, mine) == [] and _exile_copies(state, theirs) == []


# The hand-size comparison also unlocked Sunset Revelry's last line and Dreamshackle Geist's "choose up to one"
# header; run each through the engine so they are not merely parsed.
SUNSET_HAND_LINE = "If an opponent has more cards in hand than you, draw a card."
DREAMSHACKLE = (
    "Flying\nAt the beginning of combat on your turn, choose up to one —\n• Tap target creature.\n"
    "• Target creature doesn't untap during its controller's next untap step."
)


def _cast_instant_draw(engine, state, opponent_cards: int, own_cards: int) -> int:
    _fill_hand(state, "p1", own_cards)
    _fill_hand(state, "p2", opponent_cards)
    spell = GameObject(
        _card("Hand Check", SUNSET_HAND_LINE, "Instant", is_instant=True), owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    player = state.player_by_id("p1")
    player.hand.append(spell)
    library_before = len(player.library)
    engine.cast_spell(player, spell, targets=None)
    engine.resolve_until_stable()
    return library_before - len(player.library)


@pytest.mark.parametrize("opponent_cards, own_cards, drawn", [(3, 1, 1), (1, 1, 0), (0, 2, 0)])
def test_opponent_has_more_cards_in_hand_gates_the_draw(opponent_cards, own_cards, drawn):
    engine, state = _engine()
    player = state.player_by_id("p1")
    for n in range(3):
        player.library.append(GameObject(_card(f"Lib{n}", "", "Sorcery"), owner_id="p1", zone=Zone.LIBRARY))
    state.current_step = "main1"
    assert _cast_instant_draw(engine, state, opponent_cards, own_cards) == drawn


def test_optional_modal_header_taps_the_chosen_target_or_does_nothing_when_declined():
    assert parse_oracle(_card("Dreamshackle Geist", DREAMSHACKLE, "Creature — Spirit")).modeled
    for answer, expect_tapped in (("0", True), ("decline", False)):
        engine, state = _engine()
        victim = _plain(state, "Victim", owner="p2")
        geist = _put(state, _card("Dreamshackle Geist", DREAMSHACKLE, "Creature — Spirit"))
        engine.begin_turn()
        state.current_step = "begin_combat"
        state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
        engine.rules.put_triggers_on_stack()
        assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_mode"
        engine.rules.resolve_choice(answer)
        if answer == "0":
            _finish_targeting(engine, state, victim)
        engine.resolve_until_stable()
        assert victim.tapped is expect_tapped
