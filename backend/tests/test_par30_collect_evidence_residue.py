"""PAR-30 — Collect Evidence / Forage / Blight activated-body residue.

The remaining per-card primitives after the shared Champion ``behold_exile``
cost (that lives in `test_par30_champion_behold_exile.py`):

* RULE 122.1c stun counters — skip-untap replacement in `RulesEngine.set_tapped`
* Champion of the Weird — `BlightEffect(target_kind="opponent")`
* Tenth District Hero — `type_change` ``legendary`` + `source_has_subtype` cond
* Molten Exhale — `conditional_flash={"controller_beholds_subtype": …}`
* Elven Passage — `MayBeholdThenUntapLinkedEffect`
* Incinerator of the Guilty — `CollectEvidenceXThenBoardDamageEffect`
* Memory Vampire — `MemoryVampireCombatEffect` + `cast_without_paying` control
* Conspiracy Unraveler — `granted_alt_cast_cost` static
* Celestial Reunion — `behold_two_shared_type` + `CelestialReunionSearchEffect`
"""

from __future__ import annotations

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


# --- RULE 122.1c: stun counters skip the next untap --------------------

def test_stun_counter_replaces_untap():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    bear = obj_on_battlefield(eng.state, eng, creature("Bear"), controller="p1")
    eng.rules.set_tapped(bear, True)
    bear.add_counters("stun", 2)

    eng.rules.set_tapped(bear, False)  # first "untap" → removes one stun
    assert bear.tapped is True
    assert bear.counters.get("stun") == 1

    eng.rules.set_tapped(bear, False)  # second → removes the last stun
    assert bear.tapped is True
    assert "stun" not in bear.counters

    eng.rules.set_tapped(bear, False)  # now it really untaps
    assert bear.tapped is False


def test_stun_counter_survives_untap_step():
    eng = make_engine([creature("F")] * 40, [creature("B")] * 40, hand=0)
    bear = obj_on_battlefield(eng.state, eng, creature("Bear"), controller="p1")
    eng.rules.set_tapped(bear, True)
    bear.add_counters("stun", 1)
    eng.run_turn()  # turn 1 (p1) — its untap step spends the stun counter
    assert "stun" not in bear.counters
    assert bear.tapped is True  # did not untap this turn
    eng.run_turn()  # turn 2 (p2)
    eng.run_turn()  # turn 3 (p1) — now it untaps for real
    assert bear.tapped is False


# --- Champion of the Weird: "target opponent blights N" ----------------

def test_champion_of_the_weird_target_opponent_blights():
    weird = Card(
        id="weird", name="Champion of the Weird",
        type_line="Creature — Goblin Berserker",
        mana_cost_string="{1}{B}", converted_mana_cost=2,
        is_creature=True, power=6, toughness=6, oracle_text="x",
    )
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"  # "Activate only as a sorcery"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    ch = obj_on_battlefield(eng.state, eng, weird, controller="p1")
    bind_from_catalogue(ch)
    ch.summoning_sick = False
    gob = obj_on_battlefield(
        eng.state, eng, creature("Goblin", type_line="Creature — Goblin"), controller="p1"
    )
    bind_from_catalogue(gob)
    victim = obj_on_battlefield(
        eng.state, eng, creature("Ox", power=4, toughness=4), controller="p2"
    )
    bind_from_catalogue(victim)

    assert ch.activated_abilities, "blight ability bound"
    ab = ch.activated_abilities[0]
    assert eng.can_activate(p1, ch, ab) is True
    eng.activate_ability(p1, ch, 0, targets=[p2])
    eng.resolve_until_stable()
    assert victim.counters.get("-1/-1") == 2


# --- Tenth District Hero: two collect-evidence levelers ---------------

def _hero_engine():
    hero = Card(
        id="tdh", name="Tenth District Hero", type_line="Creature — Human Soldier",
        mana_cost_string="{W}", converted_mana_cost=1,
        is_creature=True, power=2, toughness=1, oracle_text="x",
    )
    eng = make_engine([creature("F")] * 20, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    h = obj_on_battlefield(eng.state, eng, hero, controller="p1")
    bind_from_catalogue(h)
    h.summoning_sick = False
    for cost in ("{2}{G}", "{3}{R}", "{4}{U}", "{2}{B}"):
        gy = obj_on_battlefield(eng.state, eng, creature("GY", cost=cost), controller="p1")
        eng.rules.put_into_graveyard(gy)
    p1.mana_pool.add_many({"W": 6, "C": 6})
    return eng, p1, h


def test_tenth_district_hero_level_one():
    from mtg_analyzer.game import continuous

    eng, p1, h = _hero_engine()
    eng.activate_ability(p1, h, 0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert h.power == 4 and h.toughness == 4
    assert "vigilance" in h.granted_keywords
    assert continuous.has_subtype(h, "Detective")
    assert continuous.has_subtype(h, "Human")
    assert not continuous.has_subtype(h, "Soldier")


def test_tenth_district_hero_level_two_gated_on_detective():
    eng, p1, h = _hero_engine()
    eng.activate_ability(p1, h, 0)  # become a Detective first
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    buddy = obj_on_battlefield(eng.state, eng, creature("Buddy"), controller="p1")
    bind_from_catalogue(buddy)
    eng.activate_ability(p1, h, 1)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert h.is_legendary is True
    assert h.power == 5 and h.toughness == 5
    assert "indestructible" in buddy.granted_keywords


def test_tenth_district_hero_level_two_noop_without_detective():
    eng, p1, h = _hero_engine()
    buddy = obj_on_battlefield(eng.state, eng, creature("Buddy"), controller="p1")
    bind_from_catalogue(buddy)
    eng.activate_ability(p1, h, 1)  # level 2 with no prior level 1
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert h.is_legendary is False
    assert "indestructible" not in buddy.granted_keywords


# --- Molten Exhale: Dragon-gated flash timing -----------------------

def test_molten_exhale_flash_gated_on_dragon():
    me = Card(
        id="me", name="Molten Exhale", type_line="Sorcery",
        mana_cost_string="{3}{R}", converted_mana_cost=4, is_sorcery=True,
        oracle_text=(
            "You may cast this spell as though it had flash if you behold a "
            "Dragon as an additional cost to cast it.\n"
            "Molten Exhale deals 4 damage to target creature or planeswalker."
        ),
    )
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # sorcery speed illegal
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1, "C": 3})
    sp = GameObject(me, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(sp)
    bind_from_catalogue(sp)
    assert eng.can_cast(p1, sp) is False

    drag = obj_on_battlefield(
        eng.state, eng, creature("Shivan Dragon", type_line="Creature — Dragon"),
        controller="p1",
    )
    bind_from_catalogue(drag)
    eng.recompute_continuous_effects()
    assert eng.can_cast(p1, sp) is True


# --- Elven Passage: fetch + reflexive behold-Elf untap ---------------

def _elven_passage_engine(has_elf: bool):
    land = Card(id="ep", name="Elven Passage", type_line="Land", oracle_text="x")
    basic = Card(
        id="forest", name="Forest", type_line="Basic Land — Forest",
        oracle_text="({T}: Add {G}.)",
    )
    eng = make_engine([basic] * 5, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    ep = obj_on_battlefield(eng.state, eng, land, controller="p1")
    bind_from_catalogue(ep)
    ep.summoning_sick = False
    if has_elf:
        elf = GameObject(
            creature("Llanowar Elves", type_line="Creature — Elf Druid"),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.hand.append(elf)
    return eng, p1, ep


def _drain_choices(eng):
    pc = eng.state.pending_choice
    while pc:
        if pc.get("kind") == "search":
            opt = next(o for o in pc["options"] if o["id"] != "decline")
            eng.resolve_pending_choice(opt["id"])
        else:
            eng.resolve_pending_choice(pc["options"][0]["id"])
        eng.resolve_until_stable()
        pc = eng.state.pending_choice


def test_elven_passage_untaps_fetched_land_with_elf():
    eng, p1, ep = _elven_passage_engine(has_elf=True)
    eng.activate_ability(p1, ep, 0)
    eng.resolve_until_stable()
    _drain_choices(eng)
    forest = next(o for o in eng.state.battlefield if o.name == "Forest")
    assert forest.tapped is False
    assert p1.life == 19
    assert ep.zone == Zone.GRAVEYARD


def test_elven_passage_leaves_land_tapped_without_elf():
    eng, p1, ep = _elven_passage_engine(has_elf=False)
    eng.activate_ability(p1, ep, 0)
    eng.resolve_until_stable()
    _drain_choices(eng)
    forest = next(o for o in eng.state.battlefield if o.name == "Forest")
    assert forest.tapped is True


# --- Incinerator of the Guilty: dynamic collect evidence X --------

def test_incinerator_board_damage():
    inc = Card(
        id="inc", name="Incinerator of the Guilty", type_line="Creature — Phoenix",
        mana_cost_string="{4}{R}{R}", converted_mana_cost=6,
        is_creature=True, power=4, toughness=4, oracle_text="x",
    )
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    inco = obj_on_battlefield(eng.state, eng, inc, controller="p1")
    bind_from_catalogue(inco)
    inco.summoning_sick = False
    for cost in ("{2}{G}", "{3}{R}"):  # total mana value 7
        gy = obj_on_battlefield(eng.state, eng, creature("GY", cost=cost), controller="p1")
        eng.rules.put_into_graveyard(gy)
    v1 = obj_on_battlefield(eng.state, eng, creature("Ox", power=6, toughness=6), controller="p2")
    bind_from_catalogue(v1)
    v2 = obj_on_battlefield(eng.state, eng, creature("Cat", power=1, toughness=2), controller="p2")
    bind_from_catalogue(v2)

    eng.state.fire_event(GameEvent(
        EventType.DAMAGE, source_id=inco.instance_id, target_id="p2",
        amount=4, combat=True, is_player=True,
    ))
    eng.resolve_until_stable()
    assert list(p1.graveyard) == []  # X = 7, all exiled
    assert v1.zone == Zone.GRAVEYARD  # 7 >= 6 toughness
    assert v2.zone == Zone.GRAVEYARD


# --- Memory Vampire: mill + free-cast from defender's graveyard ----

def test_memory_vampire_free_cast_from_defender_graveyard():
    mv = Card(
        id="mv", name="Memory Vampire", type_line="Creature — Vampire",
        mana_cost_string="{4}{B}", converted_mana_cost=5,
        is_creature=True, power=3, toughness=4, oracle_text="x",
    )
    eng = make_engine(
        [creature("F")] * 5,
        [creature("Swamp", type_line="Basic Land — Swamp")] * 20, hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    mvo = obj_on_battlefield(eng.state, eng, mv, controller="p1")
    bind_from_catalogue(mvo)
    mvo.summoning_sick = False
    for cost in ("{4}{G}", "{5}{R}"):  # >= 9 total mana value
        gy = obj_on_battlefield(eng.state, eng, creature("GY", cost=cost), controller="p1")
        eng.rules.put_into_graveyard(gy)
    bomb = obj_on_battlefield(
        eng.state, eng,
        creature("Big Demon", cost="{5}{B}{B}", power=7, toughness=7,
                 type_line="Creature — Demon"),
        controller="p2",
    )
    eng.rules.put_into_graveyard(bomb)
    p2_lib = len(p2.library)

    eng.state.fire_event(GameEvent(
        EventType.DAMAGE, source_id=mvo.instance_id, target_id="p2",
        amount=3, combat=True, is_player=True,
    ))
    eng.resolve_until_stable()
    assert p2_lib - len(p2.library) == 3  # milled "that many"
    assert bomb.zone == Zone.BATTLEFIELD
    assert bomb.controller_id == "p1"  # caster controls it
    assert bomb.owner_id == "p2"


# --- Conspiracy Unraveler: board-wide collect-evidence alt cost ----

def test_conspiracy_unraveler_alt_cast_cost():
    cu = Card(
        id="cu", name="Conspiracy Unraveler",
        type_line="Artifact Creature — Construct",
        mana_cost_string="{6}", converted_mana_cost=6,
        is_creature=True, power=5, toughness=5, oracle_text="x",
    )
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    cuo = obj_on_battlefield(eng.state, eng, cu, controller="p1")
    bind_from_catalogue(cuo)
    for cost in ("{5}{G}", "{4}{R}", "{3}{B}"):  # 15 total mana value
        gy = obj_on_battlefield(eng.state, eng, creature("GY", cost=cost), controller="p1")
        eng.rules.put_into_graveyard(gy)
    bomb = GameObject(
        creature("Expensive Bomb", cost="{7}{U}{U}", power=6, toughness=6,
                 type_line="Creature — Kraken"),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.hand.append(bomb)
    bind_from_catalogue(bomb)

    assert eng.can_cast(p1, bomb) is False  # no mana
    assert eng.can_cast(p1, bomb, alt_cost=True) is True
    actions = [a for a in eng.legal_actions(p1) if a.get("alt_cost")]
    assert actions and actions[0]["alt_cost_label"] == "Collect evidence 10"

    eng.cast_spell(p1, bomb, alt_cost=True)
    eng.resolve_until_stable()
    assert bomb.zone == Zone.BATTLEFIELD
    assert len(p1.graveyard) == 1  # 15 - (6+5) exiled to meet 10


# --- Celestial Reunion: behold-two additional cost + conditional dest -

def _celestial_engine(elves_on_battlefield: int):
    cr = Card(
        id="cr", name="Celestial Reunion", type_line="Sorcery",
        mana_cost_string="{X}{W}{W}", converted_mana_cost=2, is_sorcery=True,
        oracle_text="x",
    )
    elf_lib = creature("Elvish Mystic", cost="{G}", power=1, toughness=1,
                       type_line="Creature — Elf Druid")
    eng = make_engine([elf_lib] + [creature("Filler")] * 5, [creature("B")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    for i in range(elves_on_battlefield):
        e = obj_on_battlefield(
            eng.state, eng, creature(f"Elf{i}", type_line="Creature — Elf"),
            controller="p1",
        )
        bind_from_catalogue(e)
    sp = GameObject(cr, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(sp)
    bind_from_catalogue(sp)
    p1.mana_pool.add_many({"W": 2, "C": 3})
    return eng, p1, sp


def test_celestial_reunion_battlefield_when_additional_cost_paid():
    eng, p1, sp = _celestial_engine(elves_on_battlefield=2)
    assert eng.can_cast(p1, sp, pay_additional=True, x=2) is True
    eng.cast_spell(p1, sp, x=2, pay_additional=True)
    eng.resolve_until_stable()
    assert sp.additional_cost_paid is True
    assert sp.chosen_type == "elf"
    pc = eng.state.pending_choice
    opt = next(o for o in pc["options"] if "Elvish" in o.get("label", ""))
    eng.resolve_pending_choice(opt["id"])
    eng.resolve_until_stable()
    assert any(o.name == "Elvish Mystic" for o in eng.state.battlefield)


def test_celestial_reunion_hand_when_not_paid():
    eng, p1, sp = _celestial_engine(elves_on_battlefield=0)
    eng.cast_spell(p1, sp, x=2)  # no pay_additional
    eng.resolve_until_stable()
    assert sp.additional_cost_paid is False
    pc = eng.state.pending_choice
    opt = next(o for o in pc["options"] if "Elvish" in o.get("label", ""))
    eng.resolve_pending_choice(opt["id"])
    eng.resolve_until_stable()
    assert any(c.name == "Elvish Mystic" for c in p1.hand)
    assert not any(o.name == "Elvish Mystic" for o in eng.state.battlefield)
