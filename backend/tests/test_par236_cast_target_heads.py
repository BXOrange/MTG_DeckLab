"""PAR-236 -- cast-head restrictions and "becomes the target of ..." heads.

* RULE 601.2 / 603.2: "other than your first spell each turn" counts that player's casts this turn; the typed form counts
  only spells of that type (Ichneumon Druid: "it tracks the instant count for each player separately").
* RULE 601.2a: the zone a spell is cast from ("from anywhere other than their hand", "your first ... spell from your
  graveyard each turn", Neerdiv's graveyard ability, Shadow of the Goblin's land plays).
* RULE 601.2c / 115.1: "a spell that targets ..." reads the spell's chosen targets once per cast (Danitha's ruling).
* RULE 115 / 603.2: "becomes the target of ..." fires once per target; "you" is the player, not a permanent you control.
* RULE 707.10: a copied spell is never cast, so Curse of Shaken Faith has its own `SPELL_COPIED` ability.

Parse tests pin the grammar and what it refuses; execute tests run real cards on a real `GameEngine`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.models.game.game_state import GameState, StackItem
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.catalogue.spell_phrase import SPELL_TARGET_CLAUSE_KEY, parse_spell_phrase

from tests.test_par119_object_trigger_head import _named

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_other_than_first_spell_is_the_second_or_later_cast():
    assert parse_spell_phrase("a spell other than your first spell each turn") == {"spells_cast_this_turn_at_least": 2}
    assert parse_spell_phrase("a spell other than the first spell they cast each turn") == {
        "spells_cast_this_turn_at_least": 2}


def test_typed_other_than_first_counts_only_that_type():
    assert parse_spell_phrase("an instant spell other than the first instant spell that player casts each turn") == {
        "matching_spells_cast_this_turn_at_least": 2, "spell_filter": {"card_type": "instant"}}


@pytest.mark.parametrize("phrase", [
    "an instant spell other than the first creature spell that player casts each turn",  # counts another type
    "a spell other than your second spell each turn",
    "a spell other than your first spell",
])
def test_other_than_first_near_misses_are_refused(phrase):
    assert parse_spell_phrase(phrase) is None


def test_origin_tails():
    assert parse_spell_phrase("a spell from anywhere other than their hand") == {"spell_not_cast_from_hand": True}
    assert parse_spell_phrase("your first instant or sorcery spell from your graveyard each turn") == {
        "is_nth_matching_spell_cast_this_turn": 1, "spell_cast_from": ["graveyard"],
        "spell_filter": {"card_type_any": ["instant", "sorcery"]}}
    assert parse_spell_phrase("a spell from anywhere other than their library") is None


def test_targets_clause():
    assert parse_spell_phrase("an aura spell that targets ~") == {
        "requires_spell_targets_source": True, "spell_filter": {"subtype": "aura"}}
    assert parse_spell_phrase("a spell that targets a creature you control")["spell_targets"]["you_control"] is True
    clause = parse_spell_phrase("a spell that targets an opponent or a creature an opponent controls")[SPELL_TARGET_CLAUSE_KEY]
    assert clause["only"] is False
    assert clause["alternatives"][0] == {"kind": "player", "relation": "opponent"}
    assert clause["alternatives"][1]["controller"] == "opponent"
    only = parse_spell_phrase("an instant or sorcery spell that targets only a single creature you control")
    assert only[SPELL_TARGET_CLAUSE_KEY]["only"] is True
    assert parse_spell_phrase("a spell that targets a creature you don't control")[SPELL_TARGET_CLAUSE_KEY][
        "alternatives"][0]["controller"] == "not_you"


@pytest.mark.parametrize("phrase", [
    "a spell that targets a banana",
    "a spell that targets",
    "a spell that targets only",
    "a spell that targets you or",
])
def test_targets_near_misses_are_refused(phrase):
    assert parse_spell_phrase(phrase) is None


@pytest.mark.parametrize("cond, filt, subject", [
    ("you become the target of a spell", {"is_player": True, "item_kind": "spell"}, {"subject": "you", "recipient": True}),
    ("you become the target of a spell or ability an opponent controls", {"is_player": True},
     {"subject": "you", "recipient": True}),
    ("~ becomes the target of an aura spell", {"item_kind": "spell"}, {"subject": "self"}),
])
def test_becomes_target_heads(cond, filt, subject):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "BECOMES_TARGET"
    assert head.condition == subject
    assert head.trigger["filter"] == filt


@pytest.mark.parametrize("cond", [
    "you become the target of a banana spell",
    "you become the target of",
    "you becomes the target of a spell or ability an opponent controls and you draw",
])
def test_becomes_target_near_misses_are_refused(cond):
    assert parse_object_trigger_head(cond) is None


MODELED = [
    "Arcbound Tracker", "Ichneumon Druid", "Curse of Shaken Faith", "Sevinne, the Chronoclasm", "Ghostly Pilferer",
    "Shadow of the Goblin", "The Lost and the Damned", "Neerdiv, Devious Diver", "Danitha, Spear of Agony",
    "Druid of Horns", "Grakk the Pacifist", "Leyline of Resonance", "Reflective Golem", "Reparations",
    "Legolas, Master Archer", "Amulet of Safekeeping", "Dormant Gomazoa", "Unsettled Mariner",
    "Rayne, Academy Chancellor", "Brine Comber // Brinebound Gift", "Fugitive Druid", "Silverfur Partisan",
    "Wild Defiance", "Faldorn, Dread Wolf Herald",
]


@pytest.mark.parametrize("name", MODELED)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize("name", [
    "Leyline of Combustion",  # "you and/or at least one permanent": once per spell, not per target
    "Danitha, Sword of Hope",  # "an Equipment spell or a spell that targets ...": a disjunction over the spell itself
    "Leovold, Emissary of Trest",  # its draw cap is another clause
])
def test_cards_with_another_gap_stay_unmodeled(name):
    assert parse_oracle(_named(name)).modeled is False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _game():
    players = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in (1, 2)]
    state = GameState(players=players)
    engine = GameEngine(state)
    for player in players:
        for i in range(12):
            player.library.append(GameObject(Card(id=f"{player.id}L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id=player.id, zone=Zone.LIBRARY))
    state.internal_turn.number = 1
    return engine, state


def _real(state, name, owner="p1", counters=0):
    obj = GameObject(_named(name), owner_id=owner, zone=Zone.BATTLEFIELD)
    if counters:
        obj.counters["+1/+1"] = counters  # keeps a 0/0 body alive past state-based actions
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _custom(state, name, type_line, oracle="", owner="p1", power=2, toughness=2, **kw):
    is_creature = "Creature" in type_line
    card = Card(id=name + owner, name=name, type_line=type_line, oracle_text=oracle, is_creature=is_creature,
                power=power if is_creature else None, toughness=toughness if is_creature else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    if oracle:
        bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _settle(engine, state):
    engine.resolve_until_stable()
    for _ in range(10):
        choice = state.pending_choice
        if not choice:
            return
        options = choice.get("options") or []
        if choice.get("kind") == "trigger_target" and options:
            engine.resolve_pending_choice(options[0]["id"])
        elif choice.get("kind") == "pay_cost_then":
            can_pay = state.player_by_id(choice["player_id"]).mana_pool.total() >= 2
            engine.rules.resolve_choice("pay" if can_pay else "decline")
        elif choice.get("kind") == "copy_targets":
            engine.rules.resolve_choice("keep")  # RULE 707.10c: keep the copy's targets as they are
        else:
            engine.rules.resolve_choice("do")
        engine.resolve_until_stable()


def _cast(engine, state, name, type_line="Instant", oracle="", pid="p1", targets=(), zone=Zone.HAND):
    """Cast a custom spell. A hand cast goes through the real `cast_spell`; another origin (which `can_cast` only allows
    under a permission this file does not model) puts the spell on the stack and fires the `SPELL_CAST` event itself
    with the same fields `cast_spell` stamps (RULE 601.2a), so the trigger machinery under test is the real one."""
    card = Card(id=f"{name}-{pid}", name=name, type_line=type_line, oracle_text=oracle,
                is_instant="Instant" in type_line, is_creature="Creature" in type_line, converted_mana_cost=0)
    spell = GameObject(card, owner_id=pid, zone=zone)
    player = state.player_by_id(pid)
    player.add_to_zone(spell, zone)
    bind_from_catalogue(spell)
    state.active_player_index = state.players.index(player)
    state.current_step = "main1"
    if zone == Zone.HAND:
        engine.cast_spell(player, spell, targets=list(targets))
    else:
        player.remove_from_zone(spell, zone)
        spell.zone = Zone.STACK
        state.stack.append(StackItem(kind="spell", controller_id=pid, effects=[], obj=spell, description=name,
                                     targets=list(targets)))
        state.fire_event(GameEvent(
            EventType.SPELL_CAST, player_id=pid, card_id=spell.card.id, spell=name, instance_id=spell.instance_id,
            object_types=sorted(spell.type_words), from_hand=False, from_zone=zone.value,
            target_instance_ids=frozenset(), target_player_ids=frozenset(), target_count=0))
    _settle(engine, state)
    return spell


def _counters(obj):
    return obj.counters.get("+1/+1", 0)


def _life(state, pid="p1"):
    return state.player_by_id(pid).life


def _hand(state, pid="p1"):
    return len(state.player_by_id(pid).hand)


# -- ordinal -----------------------------------------------------------------


def test_arcbound_tracker_counts_only_spells_after_the_first_each_turn():
    engine, state = _game()
    tracker = _real(state, "Arcbound Tracker", counters=1)
    base = _counters(tracker)
    _cast(engine, state, "One")
    assert _counters(tracker) == base
    _cast(engine, state, "Two")
    assert _counters(tracker) == base + 1
    _cast(engine, state, "Three")
    assert _counters(tracker) == base + 2
    _cast(engine, state, "Theirs", pid="p2")  # "you cast": an opponent's spell is not counted
    assert _counters(tracker) == base + 2
    engine.begin_turn()  # RULE 500: a new turn resets the per-turn tally
    _cast(engine, state, "Next turn one")
    assert _counters(tracker) == base + 2
    _cast(engine, state, "Next turn two")
    assert _counters(tracker) == base + 3


def test_arcbound_tracker_considers_spells_cast_before_it_was_on_the_battlefield():
    engine, state = _game()
    _cast(engine, state, "Early")
    tracker = _real(state, "Arcbound Tracker", counters=1)  # its ruling: earlier casts this turn already count
    _cast(engine, state, "Late")
    assert _counters(tracker) == 2


def test_ichneumon_druid_tracks_the_instant_count_for_each_player_separately():
    engine, state = _game()
    _real(state, "Ichneumon Druid")
    _cast(engine, state, "Their first instant", pid="p2")
    assert _life(state, "p2") == 20
    _cast(engine, state, "Their sorcery", "Sorcery", pid="p2")  # not an instant
    assert _life(state, "p2") == 20
    _cast(engine, state, "Their second instant", pid="p2")
    assert _life(state, "p2") == 16
    _cast(engine, state, "My second instant")  # "an opponent casts"
    _cast(engine, state, "My third instant")
    assert _life(state, "p1") == 20
    _cast(engine, state, "Their third instant", pid="p2")
    assert _life(state, "p2") == 12
    engine.begin_turn()
    _cast(engine, state, "Their next-turn first", pid="p2")
    assert _life(state, "p2") == 12


def test_curse_of_shaken_faith_fires_on_later_casts_and_on_any_copy():
    engine, state = _game()
    curse = _real(state, "Curse of Shaken Faith")
    curse.attached_to = "p2"
    _cast(engine, state, "First", pid="p2")
    assert _life(state, "p2") == 20
    _cast(engine, state, "Second", pid="p2")
    assert _life(state, "p2") == 18
    _cast(engine, state, "Mine", pid="p1")  # only the enchanted player
    assert _life(state, "p2") == 18
    state.fire_event(GameEvent(EventType.SPELL_COPIED, player_id="p2", controller_id="p2"))
    _settle(engine, state)
    assert _life(state, "p2") == 16  # RULE 707.10: a copy is not "cast", so the ordinal never gates it
    state.fire_event(GameEvent(EventType.SPELL_COPIED, player_id="p1", controller_id="p1"))
    _settle(engine, state)
    assert _life(state, "p2") == 16


# -- origin ------------------------------------------------------------------


def test_ghostly_pilferer_draws_for_an_opponents_non_hand_casts_only():
    engine, state = _game()
    _real(state, "Ghostly Pilferer")
    _cast(engine, state, "From hand", pid="p2")
    assert _hand(state) == 0
    _cast(engine, state, "From graveyard", pid="p2", zone=Zone.GRAVEYARD)
    assert _hand(state) == 1
    _cast(engine, state, "My own graveyard cast", pid="p1", zone=Zone.GRAVEYARD)
    assert _hand(state) == 1  # "an opponent casts"


def test_sevinne_counts_only_graveyard_casts_for_its_first_each_turn():
    engine, state = _game()
    _real(state, "Sevinne, the Chronoclasm")
    _cast(engine, state, "From hand")  # a hand cast neither triggers nor counts
    _cast(engine, state, "Graveyard one", zone=Zone.GRAVEYARD)
    _cast(engine, state, "Graveyard two", zone=Zone.GRAVEYARD)
    copies = [e for e in state.event_log if e.type == EventType.SPELL_COPIED]
    assert len(copies) == 1
    engine.begin_turn()
    _cast(engine, state, "Graveyard next turn", zone=Zone.GRAVEYARD)
    copies = [e for e in state.event_log if e.type == EventType.SPELL_COPIED]
    assert len(copies) == 2


def test_shadow_of_the_goblin_pings_for_lands_and_spells_not_from_hand():
    engine, state = _game()
    _real(state, "Shadow of the Goblin")

    def played(from_hand):
        state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id="p1", controller_id="p1", from_hand=from_hand))
        _settle(engine, state)

    played(True)
    assert _life(state, "p2") == 20
    played(False)
    assert _life(state, "p2") == 19
    _cast(engine, state, "From hand")
    assert _life(state, "p2") == 19
    _cast(engine, state, "From graveyard", zone=Zone.GRAVEYARD)
    assert _life(state, "p2") == 18


def test_the_lost_and_the_damned_makes_a_spawn_for_nonhand_lands_and_spells():
    engine, state = _game()
    _real(state, "The Lost and the Damned")

    def tokens():
        return sum(1 for o in state.battlefield if o.name == "Spawn")

    def land_enters(from_zone, controller="p1"):
        land = _custom(state, f"Land {from_zone}", "Land", owner=controller)
        state.fire_event(GameEvent(
            EventType.ENTERS_BATTLEFIELD, controller_id=controller, instance_id=land.instance_id,
            object_types=["land"], from_zone=from_zone))
        _settle(engine, state)

    land_enters("hand")
    assert tokens() == 0
    land_enters("library")
    assert tokens() == 1
    land_enters("graveyard", controller="p2")  # "a land you control"
    assert tokens() == 1
    _cast(engine, state, "From hand")
    assert tokens() == 1
    _cast(engine, state, "From graveyard", zone=Zone.GRAVEYARD)
    assert tokens() == 2


def test_neerdiv_triggers_on_graveyard_spells_and_graveyard_abilities():
    engine, state = _game()
    neerdiv = _real(state, "Neerdiv, Devious Diver")
    _cast(engine, state, "From hand")
    assert _counters(neerdiv) == 0
    _cast(engine, state, "From graveyard", zone=Zone.GRAVEYARD)
    assert _counters(neerdiv) == 1 and _hand(state) == 1

    def activated(from_zone, owner):
        state.fire_event(GameEvent(
            EventType.ACTIVATED_ABILITY, player_id="p1", controller_id="p1", from_zone=from_zone,
            source_owner_id=owner))
        _settle(engine, state)

    activated("battlefield", "p1")
    assert _counters(neerdiv) == 1
    activated("graveyard", "p2")  # a card in an opponent's graveyard is not "your graveyard"
    assert _counters(neerdiv) == 1
    activated("graveyard", "p1")
    assert _counters(neerdiv) == 2


# -- "that targets" ------------------------------------------------------------


def test_danitha_triggers_once_per_spell_that_targets_an_opponent_or_their_creature():
    engine, state = _game()
    danitha = _real(state, "Danitha, Spear of Agony")
    mine = _custom(state, "Mine", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    oracle = "Target creature gets +1/+1 until end of turn."
    _cast(engine, state, "On mine", "Instant", oracle, targets=[mine])
    assert _counters(danitha) == 0
    _cast(engine, state, "On theirs", "Instant", oracle, targets=[theirs])
    assert _counters(danitha) == 1
    _cast(engine, state, "At them", "Instant", "Target player loses 1 life.", targets=[state.player_by_id("p2")])
    assert _counters(danitha) == 2
    _cast(engine, state, "At me", "Instant", "Target player gains 1 life.", targets=[state.player_by_id("p1")])
    assert _counters(danitha) == 2
    # Both an opponent and their creature: one spell, one trigger (the ruling).
    _cast(engine, state, "Both", "Instant", "Target player loses 1 life. Target creature gets +1/+1 until end of turn.",
          targets=[state.player_by_id("p2"), theirs])
    assert _counters(danitha) == 3


def test_leyline_of_resonance_copies_only_a_spell_targeting_only_one_creature_you_control():
    engine, state = _game()
    _real(state, "Leyline of Resonance")
    bear = _custom(state, "Bear", "Creature — Bear")
    other = _custom(state, "Other", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    oracle = "Target creature gets +1/+1 until end of turn."

    def copies():
        return sum(1 for e in state.event_log if e.type == EventType.SPELL_COPIED)

    _cast(engine, state, "On theirs", "Instant", oracle, targets=[theirs])
    assert copies() == 0
    _cast(engine, state, "On mine", "Instant", oracle, targets=[bear])
    assert copies() == 1
    _cast(engine, state, "Sorcery on mine", "Sorcery", oracle, targets=[bear])
    assert copies() == 2
    _cast(engine, state, "Two targets", "Instant", "Target creature gets +1/+1 until end of turn. Target creature "
          "gets +1/+1 until end of turn.", targets=[bear, other])
    assert copies() == 2  # not "only a single creature"
    _cast(engine, state, "Creature", "Creature — Bear", "Flying")  # not an instant or sorcery
    assert copies() == 2


def test_reparations_triggers_for_an_opponents_spell_that_targets_you_or_your_creature():
    engine, state = _game()
    _real(state, "Reparations")
    mine = _custom(state, "Mine", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    oracle = "Target creature gets +1/+1 until end of turn."
    _cast(engine, state, "Theirs on theirs", "Instant", oracle, pid="p2", targets=[theirs])
    assert _hand(state) == 0
    _cast(engine, state, "Theirs on mine", "Instant", oracle, pid="p2", targets=[mine])
    assert _hand(state) == 1
    _cast(engine, state, "Theirs at me", "Instant", "Target player loses 1 life.", pid="p2",
          targets=[state.player_by_id("p1")])
    assert _hand(state) == 2
    _cast(engine, state, "Mine on mine", "Instant", oracle, pid="p1", targets=[mine])
    assert _hand(state) == 2  # "an opponent casts"


def test_druid_of_horns_wants_an_aura_spell_that_targets_it():
    engine, state = _game()
    druid = _real(state, "Druid of Horns")
    other = _custom(state, "Other", "Creature — Bear")
    aura = "Enchant creature"
    _cast(engine, state, "Aura on other", "Enchantment — Aura", aura, targets=[other])
    assert sum(1 for o in state.battlefield if o.name == "Beast") == 0
    _cast(engine, state, "Aura on druid", "Enchantment — Aura", aura, targets=[druid])
    assert sum(1 for o in state.battlefield if o.name == "Beast") == 1
    _cast(engine, state, "Instant on druid", "Instant", "Target creature gets +1/+1 until end of turn.", targets=[druid])
    assert sum(1 for o in state.battlefield if o.name == "Beast") == 1  # an Aura spell


def test_grakk_wants_an_aura_spell_that_targets_an_opponents_creature():
    engine, state = _game()
    _real(state, "Grakk the Pacifist")
    mine = _custom(state, "Mine", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    aura = "Enchant creature"
    _cast(engine, state, "Aura on mine", "Enchantment — Aura", aura, targets=[mine])
    assert _hand(state) == 0
    _cast(engine, state, "Aura on theirs", "Enchantment — Aura", aura, targets=[theirs])
    assert _hand(state) == 1


# -- becomes the target -----------------------------------------------------------


def _target_event(state, target, caster="p2", item_kind="spell", item=None):
    is_player = isinstance(target, Player)
    state.fire_event(GameEvent(
        EventType.BECOMES_TARGET, instance_id=None if is_player else target.instance_id,
        target_controller_id=None if is_player else target.controller_id,
        target_player_id=target.id if is_player else None, is_player=is_player,
        controller_id=caster, player_id=caster, item_kind=item_kind,
        item_instance_id=item.instance_id if item is not None else None))


def test_dormant_gomazoa_untaps_only_when_you_the_player_become_the_target_of_a_spell():
    engine, state = _game()
    gomazoa = _real(state, "Dormant Gomazoa")
    mine = _custom(state, "Mine", "Creature — Bear")
    gomazoa.tapped = True
    _target_event(state, mine)  # a permanent you control is not "you"
    _settle(engine, state)
    assert gomazoa.tapped is True
    _target_event(state, state.player_by_id("p2"))  # the opponent becoming the target
    _settle(engine, state)
    assert gomazoa.tapped is True
    _target_event(state, state.player_by_id("p1"), item_kind="ability")  # an ability, not a spell
    _settle(engine, state)
    assert gomazoa.tapped is True
    _target_event(state, state.player_by_id("p1"), caster="p1")  # "any spell, including one you control"
    _settle(engine, state)
    assert gomazoa.tapped is False


def test_rayne_triggers_once_per_target_you_or_your_permanents_by_an_opponent():
    engine, state = _game()
    rayne = _real(state, "Rayne, Academy Chancellor")
    mine = _custom(state, "Mine", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    _target_event(state, mine)
    _settle(engine, state)
    assert _hand(state) == 1
    _target_event(state, state.player_by_id("p1"))
    _settle(engine, state)
    assert _hand(state) == 2  # the ruling: once for each such target
    _target_event(state, theirs)
    _target_event(state, mine, caster="p1")  # "an opponent controls"
    _settle(engine, state)
    assert _hand(state) == 2
    rayne.attached_to = None


def test_amulet_of_safekeeping_counters_unless_its_controller_pays():
    engine, state = _game()
    _real(state, "Amulet of Safekeeping")
    spell = _cast(engine, state, "Burn", "Instant", "Target player loses 3 life.", pid="p2",
                  targets=[state.player_by_id("p1")])
    assert _life(state, "p1") == 20  # the opponent had no mana to pay {1}: countered
    assert spell.zone == Zone.GRAVEYARD


def test_brine_comber_triggers_for_an_aura_spell_not_another_spell():
    engine, state = _game()
    comber = _real(state, "Brine Comber // Brinebound Gift")
    other = _custom(state, "Other", "Creature — Bear")

    def spirits():
        return sum(1 for o in state.battlefield if o.name == "Spirit")

    _cast(engine, state, "Pump", "Instant", "Target creature gets +1/+1 until end of turn.", targets=[comber])
    assert spirits() == 0
    _cast(engine, state, "Aura", "Enchantment — Aura", "Enchant creature", targets=[comber])
    assert spirits() == 1
    _cast(engine, state, "Aura on other", "Enchantment — Aura", "Enchant creature", targets=[other])
    assert spirits() == 1


def test_wild_defiance_pumps_the_targeted_creature_for_instants_and_sorceries_only():
    engine, state = _game()
    _real(state, "Wild Defiance")
    bear = _custom(state, "Bear", "Creature — Bear")
    _cast(engine, state, "Aura", "Enchantment — Aura", "Enchant creature", targets=[bear])
    engine.recompute_continuous_effects()
    assert bear.power == 2
    _cast(engine, state, "Pump", "Instant", "Target creature gets +0/+0 until end of turn.", targets=[bear])
    engine.recompute_continuous_effects()
    assert bear.power == 5


def test_silverfur_partisan_makes_a_wolf_for_instants_and_sorceries_on_wolves():
    engine, state = _game()
    _real(state, "Silverfur Partisan")
    wolf = _custom(state, "Wolf", "Creature — Wolf")
    bear = _custom(state, "Bear", "Creature — Bear")

    def wolves():
        return sum(1 for o in state.battlefield if o.name == "Wolf" and o.is_token)

    _cast(engine, state, "On bear", "Instant", "Target creature gets +1/+1 until end of turn.", targets=[bear])
    assert wolves() == 0
    _cast(engine, state, "On wolf", "Instant", "Target creature gets +1/+1 until end of turn.", targets=[wolf])
    assert wolves() == 1


def test_faldorn_triggers_for_exile_casts_and_lands_entering_from_exile():
    engine, state = _game()
    _real(state, "Faldorn, Dread Wolf Herald")

    def wolves():
        return sum(1 for o in state.battlefield if o.name == "Wolf" and o.is_token)

    _cast(engine, state, "From hand")
    assert wolves() == 0
    _cast(engine, state, "From exile", zone=Zone.EXILE)
    assert wolves() == 1
    land = _custom(state, "Exiled land", "Land")
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=land.instance_id,
                               object_types=["land"], from_zone="exile"))
    _settle(engine, state)
    assert wolves() == 2


def test_reflective_golem_copies_only_a_spell_targeting_only_it_and_only_when_paid():
    engine, state = _game()
    golem = _real(state, "Reflective Golem")
    other = _custom(state, "Other", "Creature — Bear")
    oracle = "Target creature gets +1/+1 until end of turn."

    def copies():
        return sum(1 for e in state.event_log if e.type == EventType.SPELL_COPIED)

    state.player_by_id("p1").mana_pool.add_many({"C": 2})
    _cast(engine, state, "On other", "Instant", oracle, targets=[other])
    assert copies() == 0 and state.player_by_id("p1").mana_pool.total() == 2
    _cast(engine, state, "On golem", "Instant", oracle, targets=[golem])
    assert copies() == 1 and state.player_by_id("p1").mana_pool.total() == 0  # paid {2}
    _cast(engine, state, "On golem again", "Instant", oracle, targets=[golem])
    assert copies() == 1  # nothing left to pay with


def test_fugitive_druid_draws_for_an_aura_spell_that_targets_it():
    engine, state = _game()
    druid = _real(state, "Fugitive Druid")
    other = _custom(state, "Other", "Creature — Bear")
    _cast(engine, state, "Pump", "Instant", "Target creature gets +1/+1 until end of turn.", targets=[druid])
    assert _hand(state) == 0
    _cast(engine, state, "Aura on other", "Enchantment — Aura", "Enchant creature", targets=[other])
    assert _hand(state) == 0
    _cast(engine, state, "Aura", "Enchantment — Aura", "Enchant creature", targets=[druid])
    assert _hand(state) == 1


def test_unsettled_mariner_taxes_targeting_of_you_or_your_permanents_by_an_opponent_only():
    engine, state = _game()
    _real(state, "Unsettled Mariner")
    mine = _custom(state, "Mine", "Creature — Bear")
    oracle = "Target creature gets +1/+1 until end of turn."
    own = _cast(engine, state, "Own spell", "Instant", oracle, pid="p1", targets=[mine])
    assert own.zone != Zone.STACK and own.zone == Zone.GRAVEYARD  # resolved: no tax on your own spell
    countered = _cast(engine, state, "Their spell", "Instant", oracle, pid="p2", targets=[mine])
    assert countered.zone == Zone.GRAVEYARD
    assert any(e.type == EventType.SPELL_COUNTERED and e.get("spell") == "Their spell" for e in state.event_log)
    assert not any(e.type == EventType.SPELL_COUNTERED and e.get("spell") == "Own spell" for e in state.event_log)


def test_legolas_triggers_for_a_spell_that_targets_a_creature_you_dont_control():
    engine, state = _game()
    legolas = _real(state, "Legolas, Master Archer", counters=1)
    mine = _custom(state, "Mine", "Creature — Bear")
    theirs = _custom(state, "Theirs", "Creature — Bear", owner="p2")
    oracle = "Target creature gets +1/+1 until end of turn."

    def pings():
        return sum(1 for e in state.event_log if e.type == EventType.DAMAGE and e.get("source_id") == legolas.instance_id)

    _cast(engine, state, "On mine", "Instant", oracle, targets=[mine])
    assert pings() == 0
    _cast(engine, state, "On theirs", "Instant", oracle, targets=[theirs])
    assert pings() == 1
