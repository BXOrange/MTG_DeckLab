"""PAR-119 — the composed object-event trigger head (`object_trigger_head`), the
shared noun-phrase grammar (`characteristic_phrase.parse_object_phrase`), the
binder's `filter` condition key and the "X and whenever Y" compound split.

Parse tests pin the grammar and that it fails closed; execute tests build real
listeners from oracle text and fire real engine events (destroy, declare
attackers, a resolving creature spell) and watch the life total.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import (
    parse_characteristic_phrase,
    parse_object_phrase,
)
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.catalogue.subtype_vocabulary import SUBTYPES
from mtg_analyzer.services.card_database import CardDatabase

from tests.test_par119_cast_trigger_grammar import _engine, _listener

GAIN = "you gain 1 life."


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("creature", ({"card_type": "creature"}, None)),
        ("nontoken creature you control", ({"nontoken": True, "card_type": "creature"}, "you")),
        ("creature you control with power 4 or greater",
         ({"card_type": "creature", "min_power": 4}, "you")),
        ("creature with shadow", ({"card_type": "creature", "keyword": "shadow"}, None)),
        ("creature you control with a +1/+1 counter on it",
         ({"card_type": "creature", "has_counter_kind": "+1/+1"}, "you")),
        ("creature you control with a counter on it",
         ({"card_type": "creature", "has_counter": True}, "you")),
        ("goblin", ({"subtype": "goblin"}, None)),
        ("goblin or wizard you control", ({"subtype_any": ["goblin", "wizard"]}, "you")),
        ("artifact creature", ({"card_type_all": ["artifact", "creature"]}, None)),
        ("non-human creature you control",
         ({"without_subtype": "human", "card_type": "creature"}, "you")),
        ("permanent you control", ({}, "you")),
        ("nonland permanent an opponent controls", ({"without_card_type": "land"}, "not_you")),
        ("creature you control of the chosen type",
         ({"card_type": "creature", "subtype_from_source": True}, "you")),
        ("villain and/or artifact", ({"any_of": [{"subtype": "villain"}, {"card_type": "artifact"}]}, None)),
    ],
)
def test_object_phrase_parses(phrase, expected):
    assert parse_object_phrase(phrase) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        "frobnicator",                                   # unknown word
        "creature you control you control",              # repeated controller
        "nontoken artifact creature or vehicle you control",  # adjective distribution is ambiguous
        "creature with power 4 or greater with power 5 or less",  # repeated key
        "creature with an unknown ability",
    ],
)
def test_object_phrase_fails_closed(phrase):
    assert parse_object_phrase(phrase) is None


def test_subtype_vocabulary_comes_from_the_card_cache():
    assert {"wizard", "elf", "beast", "lesson", "aura", "equipment"} <= SUBTYPES
    assert "legendary" not in SUBTYPES and "token" not in SUBTYPES


@pytest.mark.parametrize(
    "cond, event, condition, trigger",
    [
        ("another nontoken creature dies", "DIES",
         {"subject": "group", "controller": "any", "other": True,
          "filter": {"nontoken": True, "card_type": "creature"}}, {}),
        ("a creature you control with toughness 4 or greater dies", "DIES",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"card_type": "creature", "min_toughness": 4}}, {}),
        ("~ or another legendary creature you control enters", "ENTERS_BATTLEFIELD",
         {"subject": "self_or_group", "controller": "you", "other": True,
          "filter": {"legendary": True, "card_type": "creature"}}, {}),
        ("your commander enters or attacks", ["ENTERS_BATTLEFIELD", "ATTACKS"],
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"is_commander": True}}, {}),
        ("a land enters during your turn", "ENTERS_BATTLEFIELD",
         {"subject": "group", "controller": "any", "other": False,
          "filter": {"card_type": "land"}}, {"phase_relation": "you"}),
        ("a creature you control attacks alone", "ATTACKS_ALONE",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"card_type": "creature"}}, {}),
        ("a creature attacks you", "ATTACKS",
         {"subject": "group", "controller": "any", "other": False,
          "filter": {"card_type": "creature"}, "attacks_you": True}, {}),
        ("another artifact you control enters or leaves the battlefield",
         ["ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD"],
         {"subject": "group", "controller": "you", "other": True,
          "filter": {"card_type": "artifact"}}, {}),
        ("you sacrifice another permanent", "SACRIFICE",
         {"subject": "group", "controller": "you", "other": True}, {}),
        ("you sacrifice ~", "SACRIFICE", {"subject": "self"}, {}),
        ("you sacrifice ~ or another creature", "SACRIFICE",
         {"subject": "self_or_group", "controller": "you", "other": True,
          "filter": {"card_type": "creature"}}, {}),
        ("an opponent sacrifices an artifact", "SACRIFICE",
         {"subject": "group", "controller": "not_you", "other": False,
          "filter": {"card_type": "artifact"}}, {}),
        ("you sacrifice a blood token", "SACRIFICE",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"subtype": "blood", "token": True}}, {}),
        ("you sacrifice a permanent during your turn", "SACRIFICE",
         {"subject": "group", "controller": "you", "other": False}, {"phase_relation": "you"}),
        ("a player discards a permanent card", "DISCARD_CARD",
         {"subject": "group", "controller": "any", "other": False,
          "filter": {"card_type_any": ["creature", "artifact", "enchantment", "land",
                                       "planeswalker", "battle"]}}, {}),
        ("an opponent discards a creature card", "DISCARD_CARD",
         {"subject": "group", "controller": "not_you", "other": False,
          "filter": {"card_type": "creature"}}, {}),
        ("a nontoken creature enters the battlefield under your control", "ENTERS_BATTLEFIELD",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"nontoken": True, "card_type": "creature"}}, {}),
    ],
)
def test_object_head_parses(cond, event, condition, trigger):
    head = parse_object_trigger_head(cond)
    assert head is not None
    assert (head.event, head.condition, head.trigger) == (event, condition, trigger)


@pytest.mark.parametrize(
    "cond",
    [
        "a frobnicator dies",
        "another creature you control dies during frobnication",
        "a creature you control enters tapped and untapped",
        "~ enters",                       # self subjects belong to the legacy self row
        "you draw a card",                # not an object event
        "a creature attacks alone or dies",  # "alone" is only valid after a lone attack verb
        "a minotaur attacks this turn",   # a delayed trigger (RULE 603.7), not a standing one
        "you sacrifice a creature you control",   # the actor already says whose
        "you sacrifice 2 or more creatures",      # a batch quantity: not an object phrase
        "an opponent sacrifices ~",               # only its controller can sacrifice this permanent
        "you discard ~",                          # a discarded source is in the graveyard already
    ],
)
def test_object_head_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


def test_compound_heads_share_one_body():
    result = parse_oracle(Card(
        id="C", name="C", type_line="Enchantment", oracle_text=(
            "When ~ enters and whenever another creature you control dies, you gain 1 life."
        ),
    ))
    assert result.modeled
    events = sorted(spec.trigger["event"] for spec in result.specs if spec.ability_kind == "triggered")
    assert events == ["DIES", "ENTERS_BATTLEFIELD"]


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


@pytest.mark.parametrize(
    "name",
    [
        "Dauthi Ghoul",             # a creature with shadow dies
        "Kavu Monarch",             # another <subtype> enters
        "Dross Scorpion",           # ~ or another artifact creature dies
        "Faramir, Steward of Gondor",  # legendary, mana value N or greater
        "Kindred Discovery",        # of the chosen type, enters or attacks
        "Harvester of Souls",       # another nontoken creature dies
        "Endless Ranks of HYDRA",   # your commander enters or attacks
        "Foe-liage",                # a land enters during your turn
        "Necklace of Girion",       # cast head and enter head in one compound
        "Sludge Strider",           # enters or leaves the battlefield
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Engine: matches_object_filter's card_type_all
# ---------------------------------------------------------------------------


def _creature(state, owner="p1", name="Bear", power=2, toughness=2, types="Creature — Bear",
              token=False, on_battlefield=True, **kw):
    is_creature = "Creature" in types
    card = Card(id=name, name=name, type_line=types, is_creature=is_creature,
                power=power if is_creature else None,
                toughness=toughness if is_creature else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.is_token = token
    if on_battlefield:
        state.add_to_battlefield(obj)
    return obj


def test_filter_card_type_all_requires_every_type():
    engine, state = _engine()
    plain = _creature(state)
    artifact_creature = _creature(state, name="Golem", types="Artifact Creature — Golem")
    assert matches_object_filter(artifact_creature, {"card_type_all": ["artifact", "creature"]})
    assert not matches_object_filter(plain, {"card_type_all": ["artifact", "creature"]})


# ---------------------------------------------------------------------------
# Engine: real events
# ---------------------------------------------------------------------------


def _fire_enter(engine, state, obj):
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, card_id=obj.card.id,
        object=obj.name, instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    ))
    engine.resolve_until_stable()


def _gain(state, action):
    before = state.player_by_id("p1").life
    action()
    return state.player_by_id("p1").life - before


def test_dies_filter_reads_last_known_power_and_controller():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever a creature you control with power 4 or greater dies, {GAIN}")
    big = _creature(state, name="Big", power=4, toughness=4)
    small = _creature(state, name="Small")
    theirs = _creature(state, owner="p2", name="Theirs", power=5, toughness=5)

    def die(obj):
        return _gain(state, lambda: (engine.rules.destroy(obj), engine.resolve_until_stable()))

    assert die(small) == 0
    assert die(theirs) == 0      # "you control"
    assert die(big) == 1


def test_nontoken_excludes_tokens():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever another nontoken creature dies, {GAIN}")
    real = _creature(state, name="Real")
    token = _creature(state, name="Token", token=True)

    def die(obj):
        return _gain(state, lambda: (engine.rules.destroy(obj), engine.resolve_until_stable()))

    assert die(token) == 0
    assert die(real) == 1


def test_self_or_another_fires_for_the_source_without_the_filter():
    engine, state = _engine()
    state.current_step = "main1"
    oracle = f"Whenever ~ or another creature you control with power 5 or greater dies, {GAIN}"
    card = Card(id="Src", name="Src", type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, oracle_text=oracle)
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(src)
    state.add_to_battlefield(src)
    small = _creature(state, name="Small")
    big = _creature(state, name="Big", power=5, toughness=5)

    def die(obj):
        return _gain(state, lambda: (engine.rules.destroy(obj), engine.resolve_until_stable()))

    assert die(small) == 0
    assert die(big) == 1
    assert die(src) == 1         # the source qualifies on its own


def test_subtype_enters_excludes_the_source_and_other_subtypes():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever another Elf enters, {GAIN}")
    elf = _creature(state, name="Elf", types="Creature — Elf", on_battlefield=False)
    bear = _creature(state, name="Bear", on_battlefield=False)
    for obj in (elf, bear):
        state.add_to_battlefield(obj)

    assert _gain(state, lambda: _fire_enter(engine, state, bear)) == 0
    assert _gain(state, lambda: _fire_enter(engine, state, elf)) == 1


def test_enters_or_attacks_is_one_ability_per_event():
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "declare_attackers"
    _listener(state, f"Whenever another creature you control enters or attacks, {GAIN}")
    bear = _creature(state, name="Bear", on_battlefield=False)
    state.add_to_battlefield(bear)
    bear.summoning_sick = False
    p1 = state.player_by_id("p1")

    assert _gain(state, lambda: _fire_enter(engine, state, bear)) == 1

    def attack():
        engine.declare_attackers(p1, [bear])
        engine.resolve_until_stable()

    assert _gain(state, attack) == 1


def test_land_enters_during_your_turn_is_gated_on_whose_turn_it_is():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever a land enters during your turn, {GAIN}")
    land = _creature(state, name="Forest", types="Basic Land — Forest", on_battlefield=False)
    state.add_to_battlefield(land)

    assert _gain(state, lambda: _fire_enter(engine, state, land)) == 1
    state.active_player_index = 1
    assert _gain(state, lambda: _fire_enter(engine, state, land)) == 0


def test_chosen_type_reads_the_source_choice_on_death():
    engine, state = _engine()
    state.current_step = "main1"
    listener = _listener(state, f"Whenever a creature of the chosen type dies, {GAIN}")
    listener.chosen_type = "Elf"
    elf = _creature(state, name="Elf", types="Creature — Elf")
    bear = _creature(state, name="Bear")

    def die(obj):
        return _gain(state, lambda: (engine.rules.destroy(obj), engine.resolve_until_stable()))

    assert die(bear) == 0
    assert die(elf) == 1


def test_compound_head_fires_both_halves_independently():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"When ~ enters and whenever another creature you control dies, {GAIN}")
    victim = _creature(state, name="Victim")

    assert _gain(state, lambda: (engine.rules.destroy(victim), engine.resolve_until_stable())) == 1


# ---------------------------------------------------------------------------
# A pay-then-return graveyard trigger must actually function from the graveyard
# ---------------------------------------------------------------------------


def _graveyard_sorcery(state, name):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = GameObject(_named(name), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    state.player_by_id("p1").graveyard.append(obj)
    return obj


@pytest.mark.parametrize(
    "name", ["Unconventional Tactics", "Endless Ranks of HYDRA", "Killian's Confidence"]
)
def test_pay_then_return_self_triggers_function_from_the_graveyard(name):
    engine, state = _engine()
    sorcery = _graveyard_sorcery(state, name)
    assert sorcery.triggered_abilities
    assert all(a.functions_from_graveyard for a in sorcery.triggered_abilities)


def test_commander_head_offers_the_graveyard_payment_only_for_a_commander():
    engine, state = _engine()
    state.current_step = "main1"
    _graveyard_sorcery(state, "Endless Ranks of HYDRA")
    state.player_by_id("p1").mana_pool.add("B", 2)
    plain = _creature(state, name="Plain")
    _fire_enter(engine, state, plain)
    assert state.pending_choice is None
    commander = _creature(state, name="Cmdr")
    commander.is_commander = True
    _fire_enter(engine, state, commander)
    assert state.pending_choice["kind"] == "pay_cost_then"


# ---------------------------------------------------------------------------
# Engine: player-acts-on-object events (sacrifice, discard)
# ---------------------------------------------------------------------------


def _sacrifice(engine, obj):
    engine.rules.put_into_graveyard(obj)
    engine.resolve_until_stable()


def test_sacrifice_head_filters_the_sacrificed_object_and_its_controller():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever you sacrifice another creature, {GAIN}")
    mine = _creature(state, name="Mine")
    theirs = _creature(state, owner="p2", name="Theirs")
    land = _creature(state, name="Forest", types="Basic Land — Forest")

    assert _gain(state, lambda: _sacrifice(engine, land)) == 0     # not a creature
    assert _gain(state, lambda: _sacrifice(engine, theirs)) == 0   # an opponent's sacrifice
    assert _gain(state, lambda: _sacrifice(engine, mine)) == 1


def test_sacrifice_of_a_named_subtype_token_is_read_from_the_event():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever you sacrifice a Treasure, {GAIN}")
    treasure = _creature(state, name="Treasure", types="Artifact — Treasure", token=True)
    other = _creature(state, name="Trinket", types="Artifact — Equipment")

    assert _gain(state, lambda: _sacrifice(engine, other)) == 0
    assert _gain(state, lambda: _sacrifice(engine, treasure)) == 1


def test_opponent_sacrifice_scope():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever an opponent sacrifices a creature, {GAIN}")
    mine = _creature(state, name="Mine")
    theirs = _creature(state, owner="p2", name="Theirs")

    assert _gain(state, lambda: _sacrifice(engine, mine)) == 0
    assert _gain(state, lambda: _sacrifice(engine, theirs)) == 1


def test_discard_head_reads_the_discarded_cards_printed_types():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever an opponent discards a creature card, {GAIN}")

    def in_hand(name, types, owner="p2"):
        card = Card(id=name, name=name, type_line=types, is_creature="Creature" in types,
                    power=1 if "Creature" in types else None,
                    toughness=1 if "Creature" in types else None)
        obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
        state.player_by_id(owner).hand.append(obj)
        return obj

    bear = in_hand("Bear", "Creature — Bear")
    bolt = in_hand("Bolt", "Instant")
    mine = in_hand("Mine", "Creature — Bear", owner="p1")

    def discard(obj):
        return _gain(state, lambda: (engine.rules.discard_specific(obj), engine.resolve_until_stable()))

    assert discard(bolt) == 0
    assert discard(mine) == 0    # "an opponent"
    assert discard(bear) == 1


def test_permanent_card_excludes_instants_and_sorceries():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever you discard a permanent card, {GAIN}")

    def in_hand(name, types):
        card = Card(id=name, name=name, type_line=types)
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        state.player_by_id("p1").hand.append(obj)
        return obj

    land, bolt = in_hand("Forest", "Basic Land — Forest"), in_hand("Bolt", "Instant")

    def discard(obj):
        return _gain(state, lambda: (engine.rules.discard_specific(obj), engine.resolve_until_stable()))

    assert discard(bolt) == 0
    assert discard(land) == 1


def test_event_player_referent_resolves_for_sacrifice_and_discard():
    # "…deals 2 damage to them/that player" reads the acting player off the event;
    # a SACRIFICE event names it `controller_id`, a DISCARD_CARD event `player_id`.
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, "Whenever an opponent sacrifices an artifact, Listener deals 2 damage to them.")
    _listener(state, "Whenever an opponent discards a card, Listener deals 3 damage to that player.")
    artifact = _creature(state, owner="p2", name="Rock", types="Artifact")
    p2 = state.player_by_id("p2")
    before = p2.life
    _sacrifice(engine, artifact)
    assert before - p2.life == 2

    card = GameObject(Card(id="C", name="C", type_line="Sorcery"), owner_id="p2", zone=Zone.HAND)
    p2.hand.append(card)
    before = p2.life
    engine.rules.discard_specific(card)
    engine.resolve_until_stable()
    assert before - p2.life == 3


def test_group_subject_delayed_pronoun_tail_fails_closed():
    # "…dies, return it … at the beginning of the next end step": the delayed
    # capture would fall back to the source, not the creature that died.
    assert parse_oracle(_named("Rienne, Angel of Rebirth")).modeled is False


# ---------------------------------------------------------------------------
# Damage heads (RULE 120.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cond, condition, trigger",
    [
        ("a creature you control with a counter on it deals combat damage to a player",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"card_type": "creature", "has_counter": True}},
         {"filter": {"combat": True, "is_player": True}}),
        ("a source you control deals noncombat damage to an opponent",
         {"subject": "group", "controller": "you", "other": False, "recipient_is_opponent": True},
         {"filter": {"combat": False, "is_player": True}}),
        ("a creature you control deals combat damage to a creature",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"card_type": "creature"}, "recipient_filter": {"card_type": "creature"}},
         {"filter": {"combat": True, "is_player": False}}),
        ("a creature deals combat damage to a player or planeswalker",
         {"subject": "group", "controller": "any", "other": False,
          "filter": {"card_type": "creature"}},
         {"filter": {"combat": True, "player_or_planeswalker": True}}),
        ("enchanted creature deals combat damage",
         {"subject": "attached_permanent"},
         {"filter": {"combat": True}}),
        ("a creature you control deals combat damage to a player during your turn",
         {"subject": "group", "controller": "you", "other": False,
          "filter": {"card_type": "creature"}},
         {"filter": {"combat": True, "is_player": True}, "phase_relation": "you"}),
    ],
)
def test_damage_head_parses(cond, condition, trigger):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "DAMAGE"
    assert (head.condition, head.trigger) == (condition, trigger)


@pytest.mark.parametrize(
    "cond",
    [
        "a creature deals damage to a creature you control",  # a recipient controller scope
        "~ deals combat damage to an opponent",  # self subject cannot carry recipient scope keys
        "enchanted creature deals damage to you",  # nor can an attached one
        "a frobnicator deals combat damage to a player",
        "a creature deals combat damage to a frobnicator",
    ],
)
def test_damage_head_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


def _deal(engine, state, source, target, combat=True):
    engine.rules.deal_damage(target, 1, source, combat=combat)
    engine.resolve_until_stable()


def test_damage_head_scopes_source_recipient_and_combat():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever a creature you control with a counter on it deals combat damage to an opponent, {GAIN}")
    plain = _creature(state, name="Plain")
    marked = _creature(state, name="Marked")
    marked.counters["+1/+1"] = 1
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    assert _gain(state, lambda: _deal(engine, state, plain, p2)) == 0     # no counter
    assert _gain(state, lambda: _deal(engine, state, marked, p1)) == -1   # not an opponent: 1 damage, no gain
    assert _gain(state, lambda: _deal(engine, state, marked, p2, combat=False)) == 0  # not combat
    assert _gain(state, lambda: _deal(engine, state, marked, p2)) == 1


def test_damage_to_a_creature_recipient_is_read_through_the_object_filter():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever a creature you control deals combat damage to a creature, {GAIN}")
    mine = _creature(state, name="Mine", power=3, toughness=3)
    victim = _creature(state, owner="p2", name="Victim", power=1, toughness=9)
    p2 = state.player_by_id("p2")

    assert _gain(state, lambda: _deal(engine, state, mine, p2)) == 0       # a player, not a creature
    assert _gain(state, lambda: _deal(engine, state, mine, victim)) == 1


# ---------------------------------------------------------------------------
# "for each counter on it" on a self-subject leaves/dies trigger (found while
# auditing Vogar, Necropolis Tyrant): the referent is the source itself, read as
# it was when it left (RULE 603.10a), and a printed multiplier scales the count.
# ---------------------------------------------------------------------------


def _leaving_source(name, counter, count, action):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, state = _engine()
    state.current_step = "main1"
    source = GameObject(_named(name), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    state.add_to_battlefield(source)
    source.counters[counter] = count
    p1 = state.player_by_id("p1")
    for i in range(6):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    hand, life = len(p1.hand), p1.life
    action(engine, source)
    engine.resolve_until_stable()
    return len(p1.hand) - hand, p1.life - life


@pytest.mark.parametrize(
    "name, counter", [("Vogar, Necropolis Tyrant", "+1/+1"), ("Marketback Walker", "+1/+1")]
)
def test_dies_draws_a_card_for_each_counter_it_had(name, counter):
    drawn, _ = _leaving_source(name, counter, 3, lambda e, o: e.rules.destroy(o))
    assert drawn == 3


def test_leaves_the_battlefield_reads_the_last_known_counters():
    drawn, _ = _leaving_source(
        "Bloodtracker", "+1/+1", 2, lambda e, o: e.rules.exile(o)
    )
    assert drawn == 2


def test_a_printed_multiplier_scales_the_for_each_count():
    # "…you lose 2 life for each age counter on it": 3 counters -> 6 life, not 3.
    _, life = _leaving_source("Krovikan Whispers", "age", 3, lambda e, o: e.rules.destroy(o))
    assert life == -6


def test_group_subject_bare_it_that_would_hit_the_source_fails_closed():
    # "…deals damage to you, return **it** to its owner's hand": `return_to_hand`
    # with no target acts on the ability's own source (the Field), not the
    # damaging permanent — the binder only retargets `tap` for a group subject.
    assert parse_oracle(_named("Dissipation Field")).modeled is False


# ---------------------------------------------------------------------------
# Designations and collective terms are not subtypes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("commander you control", ({"is_commander": True}, "you")),
        ("outlaw you control",
         ({"subtype_any": ["assassin", "mercenary", "pirate", "rogue", "warlock"]}, "you")),
        ("land or bird you control",
         ({"any_of": [{"card_type": "land"}, {"subtype": "bird"}]}, "you")),
    ],
)
def test_words_that_are_not_subtypes_are_read_for_what_they_are(phrase, expected):
    assert parse_object_phrase(phrase) == expected


def test_a_commander_attacking_fires_a_commander_trigger():
    # Keleth, Sunmane Familiar: "commander" used to be read as a creature subtype no
    # object has, so this claimed trigger could never fire.
    engine, state = _engine()
    engine.begin_turn()
    state.current_step = "declare_attackers"
    _listener(state, f"Whenever a commander you control attacks, {GAIN}")
    plain = _creature(state, name="Plain", on_battlefield=False)
    commander = _creature(state, name="Cmdr", on_battlefield=False)
    commander.is_commander = True
    for obj in (plain, commander):
        state.add_to_battlefield(obj)
        obj.summoning_sick = False
    p1 = state.player_by_id("p1")

    def attack(obj):
        engine.declare_attackers(p1, [obj])
        engine.resolve_until_stable()

    assert _gain(state, lambda: attack(plain)) == 0
    assert _gain(state, lambda: attack(commander)) == 1


def test_an_outlaw_entering_fires_for_each_of_its_five_types():
    engine, state = _engine()
    state.current_step = "main1"
    _listener(state, f"Whenever another outlaw you control enters, {GAIN}")
    pirate = _creature(state, name="Pirate", types="Creature — Human Pirate", on_battlefield=False)
    bear = _creature(state, name="Bear", on_battlefield=False)
    for obj in (pirate, bear):
        state.add_to_battlefield(obj)

    assert _gain(state, lambda: _fire_enter(engine, state, bear)) == 0
    assert _gain(state, lambda: _fire_enter(engine, state, pirate)) == 1
