"""PAR-119 — "whenever you attack with N or more X" and Battalion, as one composed head.

The count is over the whole declaration, which only exists once combat locks in, so the
engine fires `ATTACKERS_DECLARED` (per attacking player, with every attacker) beside
`PLAYER_ATTACKED`; the head's ``attackers_declared`` spec — an object filter, a min/max, "other"
and "includes the source" — is evaluated over that set. Parse tests pin the grammar and what
it refuses; execute tests declare real attackers and count what fires.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _put

SPEC = "attackers_declared"


def _spec(cond):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "ATTACKERS_DECLARED"
    return head.trigger[SPEC]


@pytest.mark.parametrize(
    "cond, expected",
    [
        ("you attack with 3 or more creatures", {"filter": {"card_type": "creature"}, "min": 3}),
        ("you attack with exactly 2 creatures", {"filter": {"card_type": "creature"}, "min": 2, "max": 2}),
        ("you attack with at least 2 creatures", {"filter": {"card_type": "creature"}, "min": 2}),
        ("you attack with 1 or more other creatures with flying",
         {"filter": {"card_type": "creature", "keyword": "flying"}, "min": 1, "other": True}),
        ("you attack with 2 or more spiders", {"filter": {"subtype": "spider"}, "min": 2}),
        ("~ and at least 2 other creatures attack",
         {"filter": {"card_type": "creature"}, "min": 2, "other": True, "includes_source": True}),
        ("~ and at least 1 other warriors attack",
         {"filter": {"subtype": "warrior"}, "min": 1, "other": True, "includes_source": True}),
    ],
)
def test_the_attack_batch_grammar(cond, expected):
    assert _spec(cond) == expected


@pytest.mark.parametrize(
    "cond",
    [
        "you attack with 3 or more frobnicators",
        "you attack with 2 or more creatures an opponent controls",
        "you attack with creatures with total power 6 or greater",
        "you attack with your commander",
    ],
)
def test_the_attack_batch_grammar_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


@pytest.mark.parametrize(
    "name",
    ["Armasaur Guide", "Chivalric Alliance", "Boros Elite", "Tajic, Blade of the Legion",
     "Tide Skimmer", "Hermes, Overseer of Elpis", "Harbin, Vanguard Aviator", "Jolene, Plundering Pugilist",
     "Paired Tactician", "Alluring Suitor // Deadly Dancer", "Sentinel Sarah Lyons"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


@pytest.mark.parametrize("name", ["Lulu, Curious Hollyphant", "Amazing Alliance", "Arthur, Marigold Knight"])
def test_bodies_the_shared_event_cannot_answer_stay_unclaimed(name):
    # "that many" / "that much" and "that creature" would read the wrong thing: the count
    # depends on this head's own filter, and the event is shared by every listener.
    assert parse_oracle(_named(name)).modeled is False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _attackers(state, specs, owner="p1"):
    out = []
    for name, types, kw in specs:
        card = Card(id=name, name=name, type_line=types, is_creature=True, power=2, toughness=2,
                    keywords=list(kw))
        obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
        obj.controller_id = owner
        obj.summoning_sick = False
        state.add_to_battlefield(obj)
        out.append(obj)
    return out


def _attack(engine, state, attackers):
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, attackers)
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def _drawn(state, action):
    p1 = state.player_by_id("p1")
    before = len(p1.hand)
    action()
    return len(p1.hand) - before


def _stocked():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    for i in range(6):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    return engine, state


def test_n_or_more_counts_the_whole_declaration():
    engine, state = _stocked()
    _put(state, "Whenever you attack with three or more creatures, draw a card.",
         name="Guide", types="Enchantment")
    two = _attackers(state, [("A", "Creature — Bear", ()), ("B", "Creature — Bear", ())])
    assert _drawn(state, lambda: _attack(engine, state, two)) == 0
    engine2, state2 = _stocked()
    _put(state2, "Whenever you attack with three or more creatures, draw a card.",
         name="Guide", types="Enchantment")
    three = _attackers(state2, [(n, "Creature — Bear", ()) for n in "ABC"])
    assert _drawn(state2, lambda: _attack(engine2, state2, three)) == 1


def test_the_filter_counts_only_matching_attackers():
    engine, state = _stocked()
    _put(state, "Whenever you attack with two or more creatures with flying, draw a card.",
         name="Skimmer", types="Enchantment")
    mixed = _attackers(state, [("A", "Creature — Bird", ("Flying",)), ("B", "Creature — Bear", ()),
                               ("C", "Creature — Bear", ())])
    assert _drawn(state, lambda: _attack(engine, state, mixed)) == 0
    engine2, state2 = _stocked()
    _put(state2, "Whenever you attack with two or more creatures with flying, draw a card.",
         name="Skimmer", types="Enchantment")
    fliers = _attackers(state2, [("A", "Creature — Bird", ("Flying",)), ("B", "Creature — Bird", ("Flying",))])
    assert _drawn(state2, lambda: _attack(engine2, state2, fliers)) == 1


def test_exactly_two_refuses_three():
    engine, state = _stocked()
    _put(state, "When you attack with exactly two creatures, draw a card.", name="Suitor", types="Enchantment")
    three = _attackers(state, [(n, "Creature — Bear", ()) for n in "ABC"])
    assert _drawn(state, lambda: _attack(engine, state, three)) == 0


def test_another_players_attack_does_not_trigger_it():
    engine, state = _stocked()
    _put(state, "Whenever you attack with one or more creatures, draw a card.", name="Mine", types="Enchantment")
    theirs = _attackers(state, [("T", "Creature — Bear", ())], owner="p2")
    state.active_player_index = 1
    assert _drawn(state, lambda: _attack(engine, state, theirs)) == 0


def test_battalion_needs_the_source_to_attack_with_enough_company():
    text = "Whenever ~ and at least two other creatures attack, draw a card."
    engine, state = _stocked()
    source = _put(state, text, name="Elite", types="Creature — Human Soldier")
    source.summoning_sick = False
    others = _attackers(state, [("A", "Creature — Bear", ()), ("B", "Creature — Bear", ())])
    # the source stays home: two attackers are not "it and two others"
    assert _drawn(state, lambda: _attack(engine, state, others)) == 0

    engine2, state2 = _stocked()
    source2 = _put(state2, text, name="Elite", types="Creature — Human Soldier")
    source2.summoning_sick = False
    company = _attackers(state2, [("A", "Creature — Bear", ())])
    assert _drawn(state2, lambda: _attack(engine2, state2, [source2] + company)) == 0  # one other only

    engine3, state3 = _stocked()
    source3 = _put(state3, text, name="Elite", types="Creature — Human Soldier")
    source3.summoning_sick = False
    company3 = _attackers(state3, [("A", "Creature — Bear", ()), ("B", "Creature — Bear", ())])
    assert _drawn(state3, lambda: _attack(engine3, state3, [source3] + company3)) == 1


def test_an_other_filter_never_counts_the_source():
    text = "Whenever you attack with one or more other creatures with flying, draw a card."
    engine, state = _stocked()
    source = _put(state, text, name="Lulu", types="Creature — Elephant")
    source.summoning_sick = False
    source.card.keywords.append("Flying")
    assert _drawn(state, lambda: _attack(engine, state, [source])) == 0


# ---------------------------------------------------------------------------
# The block relation: "blocks / becomes blocked by <a creature …>"
# ---------------------------------------------------------------------------

BASILISK = "Whenever ~ blocks or becomes blocked by a non-Wall creature, destroy that creature at end of combat."


@pytest.mark.parametrize(
    "cond, events, related",
    [
        ("~ blocks a creature with flying", "BLOCKS", {"card_type": "creature", "keyword": "flying"}),
        ("~ becomes blocked by an artifact creature", "BECOMES_BLOCKED", {"card_type_all": ["artifact", "creature"]}),
        ("~ blocks or becomes blocked by a non-wall creature", ["BLOCKS", "BECOMES_BLOCKED"],
         {"without_subtype": "wall", "card_type": "creature"}),
        ("~ blocks a creature", "BLOCKS", None),
    ],
)
def test_the_block_relation_grammar(cond, events, related):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == events
    assert head.trigger.get("related_filter") == related


@pytest.mark.parametrize(
    "name", ["Cockatrice", "Rock Basilisk", "Gorgon Recluse", "Infernal Medusa", "Ezuri's Archers", "Tel-Jilad Wolf"]
)
def test_real_block_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def _combat(state, engine, attackers, blockers):
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, attackers)
    state.current_step = "declare_blockers"
    pairs = [{"blocker": b, "attacker": a} for b, a in blockers]
    engine.declare_blockers(state.player_by_id("p2"), pairs)
    engine.resolve_until_stable()


def _end_combat(engine, state):
    state.current_step = "end_combat"
    engine._fire_delayed_triggers("end_combat")
    engine.resolve_until_stable()


def _on_battlefield(state, obj):
    return any(o is obj for o in state.battlefield)


def test_a_basilisk_that_blocks_destroys_the_creature_it_blocked_not_itself():
    engine, state = _engine()
    attacker = _attackers(state, [("Raider", "Creature — Bear", ())])[0]
    basilisk = _put(state, BASILISK, name="Basilisk", types="Creature — Basilisk", owner="p2")
    basilisk.summoning_sick = False
    _combat(state, engine, [attacker], [(basilisk, attacker)])
    assert _on_battlefield(state, attacker) and _on_battlefield(state, basilisk)
    _end_combat(engine, state)
    assert not _on_battlefield(state, attacker)
    assert _on_battlefield(state, basilisk)


def test_a_basilisk_that_is_blocked_destroys_its_blocker():
    engine, state = _engine()
    basilisk = _put(state, BASILISK, name="Basilisk", types="Creature — Basilisk")
    basilisk.summoning_sick = False
    blocker = _attackers(state, [("Wall-less", "Creature — Bear", ())], owner="p2")[0]
    _combat(state, engine, [basilisk], [(blocker, basilisk)])
    _end_combat(engine, state)
    assert not _on_battlefield(state, blocker)
    assert _on_battlefield(state, basilisk)


def test_the_filter_spares_a_wall():
    engine, state = _engine()
    basilisk = _put(state, BASILISK, name="Basilisk", types="Creature — Basilisk")
    basilisk.summoning_sick = False
    wall = _attackers(state, [("Wall", "Creature — Wall", ())], owner="p2")[0]
    _combat(state, engine, [basilisk], [(wall, basilisk)])
    _end_combat(engine, state)
    assert _on_battlefield(state, wall)


def test_blocks_a_creature_with_flying_reads_the_attacker():
    text = "Whenever ~ blocks a creature with flying, draw a card."
    engine, state = _stocked()
    flier = _attackers(state, [("Bird", "Creature — Bird", ("Flying",))])[0]
    ground = _attackers(state, [("Bear", "Creature — Bear", ())])[0]
    spider = _put(state, text, name="Spider", types="Creature — Spider", owner="p1")
    spider.summoning_sick = False
    # the spider's controller is p2 in the test board: give it to p2 by re-owning
    spider.controller_id = "p2"
    state.player_by_id("p2").library.extend(
        GameObject(Card(id=f"M{i}", name=f"M{i}", type_line="Land"), owner_id="p2", zone=Zone.LIBRARY)
        for i in range(4)
    )
    p2 = state.player_by_id("p2")
    before = len(p2.hand)
    _combat(state, engine, [ground, flier], [(spider, ground)])
    assert len(p2.hand) == before  # blocked the ground creature


def _hand_has(state, owner, obj):
    return any(o is obj for o in state.player_by_id(owner).hand)


def test_wall_of_tears_returns_the_creature_it_blocked_at_end_of_combat():
    engine, state = _engine()
    attacker = _attackers(state, [("Raider", "Creature — Bear", ())])[0]
    wall = _put(state, "Whenever ~ blocks a creature, return that creature to its owner's hand at end of combat.",
                name="Wall of Tears", types="Creature — Wall", owner="p2")
    wall.summoning_sick = False
    _combat(state, engine, [attacker], [(wall, attacker)])
    assert _on_battlefield(state, attacker)
    _end_combat(engine, state)
    assert _hand_has(state, "p1", attacker)
    assert _on_battlefield(state, wall)


# ---------------------------------------------------------------------------
# "whenever A or B" as two independent triggers sharing one body (RULE 603.2)
# ---------------------------------------------------------------------------

STAFF = "Whenever you cast a red spell or a Mountain you control enters, you gain 1 life."


def _life(state, action):
    p1 = state.player_by_id("p1")
    before = p1.life
    action()
    engine_life = p1.life - before
    return engine_life


def test_an_or_compound_splits_into_two_triggers_sharing_the_body():
    from mtg_analyzer.parser.oracle.gate import parse_oracle as parse
    from mtg_analyzer.models.cards.card import Card as C

    result = parse(C(id="S", name="S", type_line="Artifact", oracle_text=STAFF))
    assert result.modeled
    events = sorted(s.trigger["event"] for s in result.specs if s.ability_kind == "triggered")
    assert events == ["ENTERS_BATTLEFIELD", "SPELL_CAST"]


def test_only_the_named_half_fires_each_trigger():
    from tests.test_par119_object_trigger_head import _fire_enter
    from tests.test_par119_cast_trigger_grammar import _spell, _cast_event

    engine, state = _engine()
    state.current_step = "main1"
    _put(state, STAFF, name="Staff", types="Artifact")
    mountain = _put(state, "Nothing.", name="Mountain", types="Basic Land — Mountain")
    forest = _put(state, "Nothing.", name="Forest", types="Basic Land — Forest")
    p1 = state.player_by_id("p1")
    life = p1.life
    _fire_enter(engine, state, forest)
    assert p1.life == life  # not a Mountain
    _fire_enter(engine, state, mountain)
    assert p1.life == life + 1
    _cast_event(engine, state, _spell(state, colors="R"))
    assert p1.life == life + 2
    _cast_event(engine, state, _spell(state, colors="U"))
    assert p1.life == life + 2  # a blue spell is neither half


# ---------------------------------------------------------------------------
# "attacks and isn't blocked" and "attacks while <state>"
# ---------------------------------------------------------------------------

UNBLOCKED = "Whenever ~ attacks and isn't blocked, you gain 2 life."


def test_attacks_and_isnt_blocked_is_its_own_event():
    head = parse_object_trigger_head("a creature you control attacks and isn't blocked")
    assert head is not None and head.event == "ATTACKER_UNBLOCKED"


def test_only_an_unblocked_attacker_triggers_it():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    unblocked = _put(state, UNBLOCKED, name="Mosquito", types="Creature — Insect")
    unblocked.summoning_sick = False
    blocked = _put(state, UNBLOCKED, name="Blocked", types="Creature — Insect")
    blocked.summoning_sick = False
    blocker = _attackers(state, [("Wall", "Creature — Wall", ())], owner="p2")[0]
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, [unblocked, blocked])
    state.current_step = "declare_blockers"
    engine.declare_blockers(state.player_by_id("p2"), [{"blocker": blocker, "attacker": blocked}])
    life = p1.life
    engine._fire_unblocked_events()
    engine.resolve_until_stable()
    assert p1.life == life + 2  # one of the two attackers was unblocked, not both


def test_attacks_while_a_condition_holds_gates_the_effect():
    text = "Whenever ~ attacks while you control a creature with power 4 or greater, you gain 2 life."
    for ally_power, gained in ((2, 0), (4, 2)):
        engine, state = _engine()
        p1 = state.player_by_id("p1")
        goblin = _put(state, text, name="Goblin", types="Creature — Goblin")
        goblin.summoning_sick = False
        ally = _attackers(state, [("Ally", "Creature — Bear", ())])[0]
        ally.card.power = ally_power
        life = p1.life
        _combat(state, engine, [goblin], [])
        assert p1.life == life + gained


def test_attacks_while_saddled_reads_the_sources_own_saddle():
    text = "Whenever ~ attacks while saddled, you gain 2 life."
    for saddled, gained in ((False, 0), (True, 2)):
        engine, state = _engine()
        p1 = state.player_by_id("p1")
        mount = _put(state, text, name="Mount", types="Creature — Mount")
        mount.summoning_sick = False
        if saddled:
            mount.saddled_until_turn = state.internal_turn.number
        life = p1.life
        _combat(state, engine, [mount], [])
        assert p1.life == life + gained


def test_saddled_is_refused_for_a_group_subject():
    # `requires_saddled` reads the source, so it would be wrong for "a creature you control".
    from mtg_analyzer.models.cards.card import Card as C
    from mtg_analyzer.parser.oracle.gate import parse_oracle as parse

    card = C(id="M", name="M", type_line="Enchantment",
             oracle_text="Whenever a creature you control attacks while saddled, draw a card.")
    assert not parse(card).modeled
