"""PAR-202 — "at end of combat" as a trigger head and as a delayed rider, executed on the real engine.

RULE 511.1: "at end of combat" abilities trigger as the end of combat step begins, with combat still intact
(RULE 511.2-3), so a blocker/attacker relation is still readable. RULE 603.4: an intervening-if is checked when
the ability would trigger and again on resolution. RULE 603.7: "<effect> at end of combat" inside another
ability creates a delayed triggered ability that fires once, at the next end of combat step.

Parse tests pin the grammar and what it refuses; execute tests step a real turn to the end of combat step.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.test_par119_object_trigger_head import _named

LAND = Card(id="Forest", name="Forest", type_line="Basic Land - Forest", is_land=True)
DECK_SIZE = 12  # enough library for a few draws in a one-turn scenario

GREATER_WEREWOLF = "At end of combat, put a -0/-2 counter on each creature blocking or blocked by ~."
FROSTBEAST = "At end of combat, destroy all creatures blocking or blocked by ~."
HEAT_STROKE = "At end of combat, destroy each creature that blocked or was blocked this turn."
WALL_OF_NETS = (
    "At end of combat, exile all creatures blocked by ~.\n"
    "When ~ leaves the battlefield, return all cards exiled with it to the battlefield under "
    "their owners' control."
)
DRAGSTER = (
    "At end of combat, if ~ attacked or blocked this combat, put a velocity counter on it. Then if it "
    "has 2 or more velocity counters on it, sacrifice it and draw 2 cards."
)
HOME_GUARD = (
    "At end of combat, if ~ attacked or blocked this combat, put a -0/-1 counter on ~ and "
    "create a 0/1 white Deserter creature token."
)
KYTHEON = (
    "At end of combat, if ~ and at least two other creatures attacked this combat, exile ~, "
    "then return him to the battlefield transformed under his owner's control."
)
CLOCKWORK = "Whenever ~ attacks or blocks, remove a +1/+1 counter from it at end of combat."
WARCRAWLER = "Whenever ~ attacks or blocks, put a -1/-1 counter on it at end of combat."
FROSTWEB = "Whenever ~ blocks a creature with flying, put a +1/+1 counter on ~ at end of combat."
FERRETS = (
    "At end of combat, tap all creatures that blocked ~ this turn. They don't untap during their controller's "
    "next untap step."
)
WRETCHED = "At end of combat, gain control of all creatures blocking ~ for as long as you control ~."
VENOM = (
    "Whenever enchanted creature blocks or becomes blocked by a non-Wall creature, destroy the other creature at "
    "end of combat."
)
ENTRANCER = "Whenever ~ becomes blocked by a creature, gain control of that creature at end of combat."
CONTEMPT = "When enchanted creature attacks, return it and ~ to their owners' hands at end of combat."
OUTRIGGER = "When ~ attacks or blocks, put it on top of its owner's library at end of combat."
AVIAN = (
    "At end of combat, if ~ attacked or blocked this combat, remove a +1/+0 counter from it.\n"
    "{X}, {T}: Put up to X +1/+0 counters on ~. This ability can't cause the total number of +1/+0 counters on ~ to "
    "be greater than 4. Activate only during your upkeep."
)
STAKE = (
    "Equipped creature gets +1/+0.\nWhenever equipped creature blocks or becomes blocked by a Vampire, destroy "
    "that creature. It can't be regenerated.\nEquip {1}"
)
ABOMINATION = (
    "Whenever ~ blocks or becomes blocked by a green or white creature, destroy that creature at end "
    "of combat."
)


# ---------------------------------------------------------------------------
# Parse shape
# ---------------------------------------------------------------------------


def _parse(oracle, name="Probe", types="Creature - Bear"):
    return parse_oracle(Card(id=name, name=name, type_line=types, oracle_text=oracle, is_creature="Creature" in types))


def _trigger(oracle):
    result = _parse(oracle)
    assert result.modeled, oracle
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert len(triggered) >= 1
    return triggered[0]


def test_the_head_is_the_end_of_combat_step_begin():
    spec = _trigger(GREATER_WEREWOLF)
    assert spec.trigger["event"] == "STEP_BEGIN" and spec.trigger["filter"] == {"step": "end_combat"}
    assert "phase_relation" not in spec.trigger


def test_on_your_turn_scopes_the_step_to_the_controller():
    spec = _trigger("At end of combat on your turn, draw a card.")
    assert spec.trigger["filter"] == {"step": "end_combat"} and spec.trigger["phase_relation"] == "you"


def test_the_intervening_if_gates_trigger_and_resolution():
    spec = _trigger(HOME_GUARD)
    gate = spec.trigger["active_if"]
    assert gate["kind"] == "event_this_turn" and gate["scope"] == "combat"
    assert gate["trigger"]["event"] == ["ATTACKS", "BLOCKS"]
    # RULE 603.4: the same predicate also gates the body, so it is re-checked when the ability resolves.
    assert spec.effects[0].type == "seq" and spec.effects[0].condition == gate


def test_a_delayed_self_rider_captures_the_source():
    spec = _trigger(CLOCKWORK)
    delayed = spec.effects[0]
    assert delayed.type == "create_delayed_trigger"
    assert delayed.params["step"] == "end_combat" and delayed.params["capture"] == "self"


@pytest.mark.parametrize(
    "oracle",
    [
        # a counter rider aimed at someone else is not a self rider
        "Whenever ~ attacks, put a +1/+1 counter on target creature at end of combat.",
        # "blocked by" a pronoun has no source the grammar can name
        "At end of combat, destroy all creatures blocked by it.",
        # a non-intervening, unmodeled condition fails closed
        "At end of combat, if the moon is full, draw a card.",
    ],
)
def test_unmodeled_shapes_stay_unclaimed(oracle):
    assert _parse(oracle).modeled is False


@pytest.mark.parametrize(
    "name",
    [
        "Greater Werewolf", "Kjeldoran Frostbeast", "Wall of Nets", "Heat Stroke", "Daredevil Dragster",
        "Kjeldoran Home Guard", "Clockwork Beetle", "Clockwork Condor", "Clockwork Dragon", "Clockwork Vorrac",
        "Wicker Warcrawler", "Frostweb Spider", "Abomination", "Joven's Ferrets", "The Wretched",
        "Tolarian Entrancer", "Saprazzan Outrigger", "Contempt", "Venom", "Clockwork Avian", "Clockwork Beast",
        "Clockwork Steed", "Clockwork Swarm", "Wooden Stake",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution on a real turn
# ---------------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", [LAND] * DECK_SIZE), ("p2", "p2", [LAND] * DECK_SIZE)], starting_life=20, starting_hand=0,
    )
    eng.start()
    return eng


def _creature(eng, name, owner="p1", oracle="", types="Creature - Bear", power=2, toughness=5, keywords=(),
              mana_cost_string="", **card_kw):
    card = Card(id=name, name=name, type_line=types, is_creature=True, power=power, toughness=toughness,
                oracle_text=oracle, keywords=list(keywords), mana_cost_string=mana_cost_string, **card_kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _aura(eng, name, owner, oracle, host):
    """An Aura already attached to ``host`` (set before it enters, as the aura tests do)."""
    card = Card(id=name, name=name, type_line="Enchantment - Aura", oracle_text="Enchant creature\n" + oracle)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    obj.attached_to = host.instance_id
    eng.state.add_to_battlefield(obj)
    return obj


def _colored(eng, name, color, owner="p2"):
    return _creature(eng, name, owner=owner, mana_cost_string="{" + color + "}", toughness=9)


def _advance_to(eng, step):
    for _ in range(60):
        if eng.state.current_step == step:
            return
        eng.advance_step()
    raise AssertionError(step)


def _attack(eng, attackers, blocks=()):
    """Declare ``attackers`` at p2, then p2's ``blocks`` ((blocker, attacker) pairs)."""
    _advance_to(eng, "declare_attackers")
    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": a, "defender": {"kind": "player", "id": "p2"}} for a in attackers],
    )
    if blocks:
        _advance_to(eng, "declare_blockers")
        eng.declare_blockers(eng.state.player_by_id("p2"), [{"blocker": b, "attacker": a} for b, a in blocks])


def _block_only(eng, blocker, attacker):
    """p1 attacks with ``attacker`` (p1's creature) and p2's ``blocker`` blocks it."""
    _attack(eng, [attacker], [(blocker, attacker)])


def _end_of_combat(eng):
    """Advance into the end of combat step and let its triggers resolve (combat still intact, RULE 511.2)."""
    _advance_to(eng, "end_combat")
    eng.resolve_until_stable()


def _alive(eng, obj):
    return any(o is obj for o in eng.state.battlefield)


def _counter(obj, kind):
    return (obj.counters or {}).get(kind, 0)


# -- shape A: the trigger head ----------------------------------------------


def test_greater_werewolf_marks_each_creature_it_blocked_or_was_blocked_by():
    eng = _engine()
    wolf = _creature(eng, "Wolf", "p1", GREATER_WEREWOLF)
    blocker = _creature(eng, "Blocker", "p2")
    bystander = _creature(eng, "Bystander", "p2")
    _block_only(eng, blocker, wolf)
    assert _counter(blocker, "-0/-2") == 0  # nothing happens before the end of combat step
    _end_of_combat(eng)
    assert _counter(blocker, "-0/-2") == 1
    assert _counter(bystander, "-0/-2") == 0 and _counter(wolf, "-0/-2") == 0


def test_greater_werewolf_blocking_marks_the_attacker_it_blocked():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1")
    wolf = _creature(eng, "Wolf", "p2", GREATER_WEREWOLF)
    _block_only(eng, wolf, attacker)
    _end_of_combat(eng)
    assert _counter(attacker, "-0/-2") == 1


def test_frostbeast_destroys_every_blocker_and_nothing_else():
    eng = _engine()
    beast = _creature(eng, "Beast", "p1", FROSTBEAST, toughness=9)
    one = _creature(eng, "One", "p2", toughness=9)
    two = _creature(eng, "Two", "p2", toughness=9)
    bystander = _creature(eng, "Bystander", "p2")
    _attack(eng, [beast], [(one, beast), (two, beast)])
    _end_of_combat(eng)
    assert not _alive(eng, one) and not _alive(eng, two)
    assert _alive(eng, beast) and _alive(eng, bystander)


def test_frostbeast_does_nothing_when_unblocked():
    eng = _engine()
    beast = _creature(eng, "Beast", "p1", FROSTBEAST)
    other = _creature(eng, "Other", "p2")
    _attack(eng, [beast])
    _end_of_combat(eng)
    assert _alive(eng, other)


def test_wall_of_nets_exiles_the_attackers_it_blocked_until_it_leaves():
    eng = _engine()
    wall = _creature(eng, "Wall", "p2", WALL_OF_NETS, types="Creature - Wall", toughness=9)
    blocked = _creature(eng, "Blocked", "p1")
    unblocked = _creature(eng, "Unblocked", "p1")
    _attack(eng, [blocked, unblocked], [(wall, blocked)])
    _end_of_combat(eng)
    assert not _alive(eng, blocked)
    assert _alive(eng, unblocked) and _alive(eng, wall)


def test_heat_stroke_destroys_each_creature_that_blocked_or_was_blocked_this_turn():
    eng = _engine()
    stroke = _creature(eng, "Stroke", "p1", HEAT_STROKE, types="Enchantment", power=0, toughness=0)
    stroke.card.is_creature = False
    attacker = _creature(eng, "Attacker", "p1")
    unblocked = _creature(eng, "Unblocked", "p1")
    blocker = _creature(eng, "Blocker", "p2")
    idle = _creature(eng, "Idle", "p2")
    _attack(eng, [attacker, unblocked], [(blocker, attacker)])
    _end_of_combat(eng)
    assert not _alive(eng, attacker) and not _alive(eng, blocker)
    assert _alive(eng, unblocked) and _alive(eng, idle)


def test_dragster_counts_up_and_sacrifices_at_two_counters():
    eng = _engine()
    dragster = _creature(eng, "Dragster", "p1", DRAGSTER)
    dragster.counters["velocity"] = 1
    hand = len(eng.state.player_by_id("p1").hand)
    _attack(eng, [dragster])
    _end_of_combat(eng)
    assert not _alive(eng, dragster)
    assert len(eng.state.player_by_id("p1").hand) == hand + 2


def test_dragster_first_pass_only_adds_a_counter():
    eng = _engine()
    dragster = _creature(eng, "Dragster", "p1", DRAGSTER)
    _attack(eng, [dragster])
    _end_of_combat(eng)
    assert _alive(eng, dragster) and _counter(dragster, "velocity") == 1


def test_dragster_that_neither_attacked_nor_blocked_does_nothing():
    eng = _engine()
    dragster = _creature(eng, "Dragster", "p1", DRAGSTER)
    bystander = _creature(eng, "Bystander", "p1")
    _attack(eng, [bystander])
    _end_of_combat(eng)
    assert _counter(dragster, "velocity") == 0


def test_dragster_that_blocked_also_counts():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1")
    dragster = _creature(eng, "Dragster", "p2", DRAGSTER)
    _block_only(eng, dragster, attacker)
    _end_of_combat(eng)
    assert _counter(dragster, "velocity") == 1


def test_home_guard_makes_a_deserter_only_after_fighting():
    eng = _engine()
    guard = _creature(eng, "Guard", "p1", HOME_GUARD, toughness=3)
    _attack(eng, [guard])
    _end_of_combat(eng)
    assert _counter(guard, "-0/-1") == 1
    assert sum(1 for o in eng.state.battlefield if o.name == "Deserter") == 1

    eng2 = _engine()
    idle = _creature(eng2, "Guard", "p1", HOME_GUARD)
    other = _creature(eng2, "Other", "p1")
    _attack(eng2, [other])
    _end_of_combat(eng2)
    assert _counter(idle, "-0/-1") == 0
    assert not any(o.name == "Deserter" for o in eng2.state.battlefield)


def _kytheon(eng):
    return _creature(
        eng, "Kytheon, Hero of Akros", "p1", KYTHEON, layout="transform", back_name="Gideon, Battle-Forged",
        back_type_line="Legendary Planeswalker - Gideon", back_loyalty=3,
    )


def test_kytheon_transforms_only_with_two_other_attackers():
    eng = _engine()
    kytheon = _kytheon(eng)
    a = _creature(eng, "A", "p1")
    b = _creature(eng, "B", "p1")
    _attack(eng, [kytheon, a, b])
    _end_of_combat(eng)
    names = {o.name for o in eng.state.battlefield}
    assert "Gideon, Battle-Forged" in names and "Kytheon, Hero of Akros" not in names

    eng2 = _engine()
    kytheon2 = _kytheon(eng2)
    only = _creature(eng2, "A", "p1")
    _attack(eng2, [kytheon2, only])
    _end_of_combat(eng2)
    assert {o.name for o in eng2.state.battlefield} >= {"Kytheon, Hero of Akros"}
    assert "Gideon, Battle-Forged" not in {o.name for o in eng2.state.battlefield}


def test_kytheon_that_attacked_alone_with_a_bystander_stays_put():
    eng = _engine()
    kytheon = _kytheon(eng)
    a = _creature(eng, "A", "p1")
    _creature(eng, "Home", "p1")
    _attack(eng, [kytheon, a])
    _end_of_combat(eng)
    assert any(o.name == "Kytheon, Hero of Akros" for o in eng.state.battlefield)


# -- shape B: the delayed rider ----------------------------------------------


def test_clockwork_removes_a_counter_only_at_end_of_combat_and_only_once():
    eng = _engine()
    beetle = _creature(eng, "Beetle", "p1", CLOCKWORK, power=0, toughness=4)
    beetle.counters["+1/+1"] = 2
    _attack(eng, [beetle])
    eng.resolve_until_stable()
    assert _counter(beetle, "+1/+1") == 2  # the trigger only *created* the delayed ability
    _end_of_combat(eng)
    assert _counter(beetle, "+1/+1") == 1
    assert not eng.state.delayed_triggers  # it fired and is gone: "at end of combat" is a one-shot
    eng.advance_step()
    eng.resolve_until_stable()
    assert _counter(beetle, "+1/+1") == 1


def test_clockwork_that_stayed_home_keeps_its_counters():
    eng = _engine()
    beetle = _creature(eng, "Beetle", "p1", CLOCKWORK, power=0, toughness=4)
    beetle.counters["+1/+1"] = 2
    other = _creature(eng, "Other", "p1")
    _attack(eng, [other])
    _end_of_combat(eng)
    assert _counter(beetle, "+1/+1") == 2


def test_clockwork_that_died_in_combat_leaves_nothing_to_remove():
    eng = _engine()
    beetle = _creature(eng, "Beetle", "p1", CLOCKWORK, power=0, toughness=1)
    beetle.counters["+1/+1"] = 1
    killer = _creature(eng, "Killer", "p2", power=4)
    _block_only(eng, killer, beetle)
    _end_of_combat(eng)  # must not raise: the delayed ability's referent is gone (RULE 400.7)
    assert not _alive(eng, beetle)


def test_warcrawler_shrinks_itself_at_end_of_combat():
    eng = _engine()
    crawler = _creature(eng, "Crawler", "p1", WARCRAWLER, toughness=5)
    _attack(eng, [crawler])
    _end_of_combat(eng)
    assert _counter(crawler, "-1/-1") == 1


def test_frostweb_spider_grows_only_after_blocking_a_flier():
    eng = _engine()
    flier = _creature(eng, "Flier", "p1", keywords=("Flying",))
    spider = _creature(eng, "Spider", "p2", FROSTWEB, types="Creature - Spider", keywords=("Reach",))
    _block_only(eng, spider, flier)
    assert _counter(spider, "+1/+1") == 0
    _end_of_combat(eng)
    assert _counter(spider, "+1/+1") == 1

    eng2 = _engine()
    ground = _creature(eng2, "Ground", "p1")
    spider2 = _creature(eng2, "Spider", "p2", FROSTWEB, types="Creature - Spider")
    _block_only(eng2, spider2, ground)
    _end_of_combat(eng2)
    assert _counter(spider2, "+1/+1") == 0


def test_abomination_destroys_only_green_or_white_creatures_it_fought():
    for color, destroyed in (("G", True), ("W", True), ("R", False)):
        eng = _engine()
        abom = _creature(eng, "Abomination", "p1", ABOMINATION, toughness=9)
        victim = _colored(eng, "Victim", color)
        _block_only(eng, victim, abom)
        assert _alive(eng, victim)
        _end_of_combat(eng)
        assert _alive(eng, victim) is (not destroyed), color
        assert _alive(eng, abom)


def test_joven_ferrets_taps_what_blocked_it_and_keeps_it_tapped_through_the_next_untap():
    eng = _engine()
    ferrets = _creature(eng, "Ferrets", "p1", FERRETS)
    blocker = _creature(eng, "Blocker", "p2")
    bystander = _creature(eng, "Bystander", "p2")
    _block_only(eng, blocker, ferrets)
    assert not blocker.tapped
    _end_of_combat(eng)
    assert blocker.tapped and not bystander.tapped
    # RULE 502.3: it skips p2's next untap step (the step after this turn), staying tapped.
    for _ in range(80):
        eng.advance_step()
        if eng.state.active_player.id == "p2" and eng.state.current_step == "main1":
            break
    assert blocker.tapped


def test_the_wretched_steals_its_blockers_for_as_long_as_it_stays():
    eng = _engine()
    wretched = _creature(eng, "Wretched", "p1", WRETCHED, toughness=9)
    one = _creature(eng, "One", "p2", toughness=9)
    two = _creature(eng, "Two", "p2", toughness=9)
    bystander = _creature(eng, "Bystander", "p2")
    _attack(eng, [wretched], [(one, wretched), (two, wretched)])
    assert one.controller_id == "p2"
    _end_of_combat(eng)
    assert one.controller_id == "p1" and two.controller_id == "p1" and bystander.controller_id == "p2"
    # RULE 611.2b: control ends when the Wretched leaves the battlefield.
    eng.rules.put_into_graveyard(wretched)
    eng.resolve_until_stable()
    assert one.controller_id == "p2" and two.controller_id == "p2"


def test_tolarian_entrancer_takes_the_creature_that_blocked_it_at_end_of_combat():
    eng = _engine()
    entrancer = _creature(eng, "Entrancer", "p1", ENTRANCER, toughness=9)
    blocker = _creature(eng, "Blocker", "p2", toughness=9)
    _block_only(eng, blocker, entrancer)
    assert blocker.controller_id == "p2"
    _end_of_combat(eng)
    assert blocker.controller_id == "p1"
    assert entrancer.controller_id == "p1"


def test_venom_destroys_the_other_creature_but_spares_a_wall():
    for types, destroyed in (("Creature - Bear", True), ("Creature — Wall", False)):
        eng = _engine()
        host = _creature(eng, "Host", "p1", toughness=9)
        _aura(eng, "Venom", "p1", VENOM, host)
        victim = _creature(eng, "Victim", "p2", types=types, toughness=9)
        _block_only(eng, victim, host)
        _end_of_combat(eng)
        assert _alive(eng, victim) is (not destroyed), types
        assert _alive(eng, host)


def test_contempt_returns_the_attacker_and_itself_at_end_of_combat():
    eng = _engine()
    host = _creature(eng, "Host", "p1")
    other = _creature(eng, "Other", "p1")
    contempt = _aura(eng, "Contempt", "p2", CONTEMPT, host)
    _attack(eng, [host, other])
    assert _alive(eng, host) and _alive(eng, contempt)
    _end_of_combat(eng)
    assert not _alive(eng, host) and not _alive(eng, contempt)
    assert _alive(eng, other)


def test_outrigger_goes_to_the_top_of_the_library_only_at_end_of_combat():
    eng = _engine()
    outrigger = _creature(eng, "Outrigger", "p1", OUTRIGGER)
    library = eng.state.player_by_id("p1").library
    size = len(library)
    _attack(eng, [outrigger])
    eng.resolve_until_stable()
    assert _alive(eng, outrigger)
    _end_of_combat(eng)
    assert not _alive(eng, outrigger)
    assert len(library) == size + 1 and library[-1] is outrigger  # RULE 401.7: the list end is the top


def test_a_that_creature_rider_fails_closed_off_a_block_head():
    assert _parse("Whenever ~ attacks, gain control of that creature at end of combat.").modeled is False


def _avian_upkeep(eng, avian, x):
    """Activate the Avian's ability in p1's upkeep for ``x`` and return the pending number choice."""
    _advance_to(eng, "upkeep")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"C": x})
    avian.summoning_sick = False
    eng.activate_ability(p1, avian, 0, x=x)
    eng.resolve_until_stable()
    return eng.state.pending_choice


def test_clockwork_avian_up_to_x_is_a_choice_capped_by_what_it_already_carries():
    eng = _engine()
    avian = _creature(eng, "Avian", "p1", AVIAN, power=0, toughness=3)
    avian.counters["+1/+0"] = 3
    choice = _avian_upkeep(eng, avian, 3)
    assert choice is not None and choice["kind"] == "choose_number_resolve"
    # X = 3 would reach 6, but the cap is 4: at most one more counter may be placed.
    assert [o["id"] for o in choice["options"]] == ["0", "1"]


def test_clockwork_avian_places_the_chosen_number():
    eng = _engine()
    avian = _creature(eng, "Avian", "p1", AVIAN, power=0, toughness=3)
    choice = _avian_upkeep(eng, avian, 3)
    assert [o["id"] for o in choice["options"]] == ["0", "1", "2", "3"]
    eng.resolve_pending_choice("2")
    assert _counter(avian, "+1/+0") == 2


def test_clockwork_avian_loses_a_counter_only_after_fighting():
    eng = _engine()
    avian = _creature(eng, "Avian", "p1", AVIAN, power=0, toughness=3)
    avian.counters["+1/+0"] = 2
    other = _creature(eng, "Other", "p1")
    _attack(eng, [other])
    _end_of_combat(eng)
    assert _counter(avian, "+1/+0") == 2

    eng2 = _engine()
    avian2 = _creature(eng2, "Avian", "p1", AVIAN, power=0, toughness=3)
    avian2.counters["+1/+0"] = 2
    _attack(eng2, [avian2])
    _end_of_combat(eng2)
    assert _counter(avian2, "+1/+0") == 1


def test_wooden_stake_destroys_the_far_side_vampire_not_the_equipped_creature():
    for types, destroyed in (("Creature — Vampire", True), ("Creature — Bear", False)):
        eng = _engine()
        host = _creature(eng, "Host", "p2", toughness=9)
        stake = _aura(eng, "Stake", "p2", STAKE, host)
        victim = _creature(eng, "Victim", "p1", types=types, toughness=9)
        _block_only(eng, host, victim)
        eng.resolve_until_stable()
        assert _alive(eng, victim) is (not destroyed), types
        assert _alive(eng, host) and _alive(eng, stake)
