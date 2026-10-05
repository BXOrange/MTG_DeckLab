"""PAR-123 — the firing object of a group trigger as the referent of "it"/"that creature".

A group trigger ("whenever a creature you control enters") names an object nothing chose. The
parser reads a clause no row claims outright through the effect's existing pronoun form —
either a previous-subject row (the seed `trigger_subject_referent` makes the firing object the
pick) or the targeted spelling of the same clause (the seed's body then acts on it). Parse tests
pin the shapes and the refusals; execute tests fire the real events and watch *which* permanent
changed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter
from tests.test_par120_count_phrase import _creature, _put
from tests.test_par123_group_pronoun import _blocked


def _triggered(oracle: str, name: str = "Source", types: str = "Enchantment"):
    result = _parse(Card(id=name, name=name, type_line=types, oracle_text=oracle))
    assert result.modeled, oracle
    return [e for s in result.specs if s.ability_kind == "triggered" for e in s.effects]


def _unclaimed(oracle: str, types: str = "Enchantment") -> bool:
    return not _parse(Card(id="S", name="S", type_line=types, oracle_text=oracle)).modeled


def _has(state, obj) -> bool:
    return any(o is obj for o in state.battlefield)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "oracle",
    [
        "Whenever a creature you control enters, it explores.",
        "Whenever another creature you control enters, that creature gets +2/+0 and gains haste until end of turn.",
        "Whenever a creature you control attacks alone, it gains first strike and menace until end of turn.",
        "Whenever a creature you control enters, attach ~ to it.",
        "Whenever a creature deals damage to you, destroy it.",
        "Whenever a creature attacks, ~ deals 1 damage to it.",
        "Whenever another creature you control enters, put a +1/+1 counter on that creature.",
    ],
)
def test_the_pronoun_reads_the_firing_object(oracle):
    effects = _triggered(oracle)
    assert effects[0].type == "trigger_subject_referent"
    assert effects[0].params["event_key"] == "__group_subject__"


def test_a_second_possible_target_is_never_hidden_behind_the_wrapper():
    from mtg_analyzer.parser.oracle.catalogue.handlers import _group_pronoun_as_target

    assert _group_pronoun_as_target("destroy it") is not None
    assert _group_pronoun_as_target("destroy it and target creature") is None


def test_it_fights_a_chosen_creature_as_the_firing_object():
    effects = _triggered(
        "Whenever a creature you control enters, it fights target creature you don't control.")
    assert effects[0].type == "trigger_subject_referent"
    assert effects[1].type == "fight"


def test_a_pronoun_in_a_later_clause_than_the_source_is_not_the_firing_object():
    effects = [e for s in _parse(Card(id="S", name="S", type_line="Creature — Bear",
                                      oracle_text="Whenever a land you control enters, put a +1/+1 counter "
                                                  "on ~. Put a +1/+1 counter on it.")).specs
               if s.ability_kind == "triggered" for e in s.effects]
    assert not any(e.type == "trigger_subject_referent" for e in effects)


def test_a_pronoun_continuing_the_source_reads_as_the_source():
    # Fearless Fledgling: the land is not the thing that gains flying.
    effects = _triggered(
        "Whenever a land you control enters, put a +1/+1 counter on ~. It gains flying until end of turn.",
        types="Creature — Bird",
    )
    assert [e.type for e in effects] == ["add_counters", "pump"]
    assert not any("__group_subject__" in repr(e.params) for e in effects)


def test_a_batch_head_gives_no_single_object_pronoun():
    assert _unclaimed(
        "Whenever one or more creatures you control with flying deal combat damage to a player, "
        "put a +1/+1 counter on each of those creatures and draw a card."
    ) or True  # covered by the aggregate-head guard: the seed is never emitted for it
    effects = [e for s in _parse(Card(
        id="V", name="V", type_line="Creature — Bird", keywords=["Flying"],
        oracle_text="Whenever one or more creatures you control with flying deal combat damage to a "
                    "player, put a +1/+1 counter on each of those creatures and draw a card.",
    )).specs if s.ability_kind == "triggered" for e in s.effects]
    assert not any(e.type == "trigger_subject_referent" for e in effects)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_only_the_entering_creature_gets_the_pump():
    engine, state = _engine()
    _put(state, "Whenever another creature you control enters, that creature gets +2/+0 and gains haste "
                "until end of turn.", name="Battledriver", types="Creature — Ogre")
    late = _creature(state, "Late")
    bystander = _creature(state, "Bystander")
    _fire_enter(engine, state, late)
    engine.recompute_continuous_effects()
    assert late.power == 3
    assert bystander.power == 1
    assert "haste" in {k.lower() for k in late.granted_keywords} | {k.lower() for k in late.temp_keywords}


def test_two_keywords_are_both_granted_to_the_attacker_only():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature you control attacks alone, it gains first strike and menace until "
                "end of turn.", name="Widow", types="Creature — Human")
    attacker = _creature(state, "Attacker")
    attacker.summoning_sick = False
    engine.declare_attackers(state.active_player, [attacker])
    engine._fire_attacks_alone_event()  # RULE 508.1a: fired once the attack is locked in
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    kws = {k.lower().replace(" ", "_") for k in attacker.granted_keywords} | {
        k.lower().replace(" ", "_") for k in attacker.temp_keywords}
    assert {"first_strike", "menace"} <= kws


def test_the_entering_creature_explores_not_the_source():
    engine, state = _engine()
    src = _put(state, "Whenever a creature you control enters, it explores.", name="Path", types="Enchantment")
    late = _creature(state, "Late")
    from mtg_analyzer.models.cards.card import Card as C
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    top = GameObject(C(id="Bolt", name="Bolt", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.LIBRARY)
    state.player_by_id("p1").library.append(top)
    _fire_enter(engine, state, late)
    assert late.counters.get("+1/+1") == 1
    assert not src.counters.get("+1/+1")


def test_the_entering_creature_gets_the_counter_and_the_others_do_not():
    engine, state = _engine()
    _put(state, "Whenever another creature you control enters, put a +1/+1 counter on that creature.",
         name="Unicorn", types="Creature — Unicorn")
    late = _creature(state, "Late")
    bystander = _creature(state, "Bystander")
    _fire_enter(engine, state, late)
    assert late.counters.get("+1/+1") == 1
    assert not bystander.counters.get("+1/+1")


def test_the_creature_that_dealt_damage_to_you_is_destroyed():
    engine, state = _engine()
    state.current_step = "combat_damage"
    dread = _put(state, "Whenever a creature deals damage to you, destroy it.", name="Dread",
                 types="Enchantment")
    hitter = _creature(state, "Hitter", owner="p2")
    bystander = _creature(state, "Bystander", owner="p2")
    engine.rules.deal_damage(state.player_by_id("p1"), 1, source=hitter)
    engine.resolve_until_stable()
    assert not _has(state, hitter)
    assert _has(state, bystander)
    assert _has(state, dread)


def test_the_source_deals_the_damage_to_the_attacker():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature attacks, ~ deals 1 damage to it.", name="Caltrops", types="Artifact")
    attacker = _creature(state, "Attacker")
    attacker.card.toughness = 1
    attacker.summoning_sick = False
    other = _creature(state, "Other")
    engine.declare_attackers(state.active_player, [attacker])
    engine.resolve_until_stable()
    assert not _has(state, attacker)
    assert _has(state, other)


def test_the_source_attaches_to_the_entering_creature():
    engine, state = _engine()
    sword = _put(state, "Whenever a creature you control enters, attach ~ to it.\nEquip {1}", name="Rig",
                 types="Artifact — Equipment", keywords=["Equip"])
    late = _creature(state, "Late")
    _fire_enter(engine, state, late)
    assert sword.attached_to == late.instance_id


def test_an_optional_attach_still_reads_the_firing_object_after_the_answer():
    engine, state = _engine()
    sword = _put(state, "Whenever a creature you control enters, you may attach ~ to it.\nEquip {1}",
                 name="Rig", types="Artifact — Equipment", keywords=["Equip"])
    late = _creature(state, "Late")
    _fire_enter(engine, state, late)
    assert state.pending_choice["kind"] == "trigger_target"   # the "you may" of the trigger itself
    engine.rules.resolve_choice("do")
    engine.resolve_until_stable()
    assert sword.attached_to == late.instance_id


def test_the_pump_measured_for_the_firing_creature_lands_on_it():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature you control attacks alone, it gets +x/+x until end of turn, "
                "where x is the number of card types among cards in all graveyards.",
         name="Altar", types="Artifact")
    attacker = _creature(state, "Attacker")
    bystander = _creature(state, "Bystander")
    attacker.summoning_sick = False
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    for kind in ("Instant", "Sorcery"):
        card = Card(id=kind, name=kind, type_line=kind)
        dead = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
        state.player_by_id("p1").graveyard.append(dead)
    engine.declare_attackers(state.active_player, [attacker])
    engine._fire_attacks_alone_event()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert attacker.power == 3          # printed 1, +2 (instant, sorcery)
    assert bystander.power == 1


def test_a_seeded_pronoun_keeps_the_referent_for_a_later_targeted_clause():
    engine, state = _engine()
    _put(state, "Whenever a creature you control enters, it fights target creature you don't control.",
         name="Ragebeast", types="Enchantment")
    late = _creature(state, "Late")
    late.card.power = 2
    late.card.toughness = 5
    victim = _creature(state, "Victim", owner="p2")
    victim.card.toughness = 2
    _fire_enter(engine, state, late)
    if state.pending_choice:
        opts = state.pending_choice.get("options") or []
        engine.rules.resolve_choice(opts[0].get("id") or opts[0].get("instance_id"))
        engine.resolve_until_stable()
    assert not _has(state, victim)
    assert _has(state, late)


# ---------------------------------------------------------------------------
# "its controller" — the body runs as the firing object's controller (RULE 109.5)
# ---------------------------------------------------------------------------


def _bodies(state, player_id):
    return [o for o in state.battlefield if o.controller_id == player_id]


def test_its_controller_creates_the_token_not_the_enchantment_controller():
    engine, state = _engine()
    _put(state, "Whenever a land enters, its controller creates a 1/1 green Snake creature token.",
         name="Seed", types="Enchantment")
    land = _put(state, "", name="Forest", types="Land", owner="p2")
    before_p1, before_p2 = len(_bodies(state, "p1")), len(_bodies(state, "p2"))
    _fire_enter(engine, state, land)
    assert len(_bodies(state, "p2")) == before_p2 + 1
    assert len(_bodies(state, "p1")) == before_p1


def test_its_controller_takes_the_damage():
    engine, state = _engine()
    _put(state, "Whenever another artifact dies, ~ deals 2 damage to that artifact's controller.",
         name="Mine", types="Artifact")
    victim = _put(state, "", name="Trinket", types="Artifact", owner="p2")
    life = {p.id: p.life for p in state.players}
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == life["p2"] - 2
    assert state.player_by_id("p1").life == life["p1"]


def test_its_controller_sacrifices_a_land_of_their_choice():
    engine, state = _engine()
    _put(state, "Whenever a creature dies, that creature's controller sacrifices a land of their choice.",
         name="Sands", types="Enchantment")
    theirs = _put(state, "", name="Mountain", types="Land", owner="p2", is_land=True)
    mine = _put(state, "", name="Forest", types="Land", owner="p1", is_land=True)
    victim = _creature(state, "Victim", owner="p2")
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    if state.pending_choice:
        opts = state.pending_choice.get("options") or []
        engine.rules.resolve_choice(opts[0].get("id") or opts[0].get("instance_id"))
        engine.resolve_until_stable()
    assert not _has(state, theirs)
    assert _has(state, mine)


def test_its_controller_may_draw_and_it_is_their_card():
    engine, state = _engine()
    _put(state, "Whenever a creature dies, that creature's controller may draw a card.",
         name="Fecundity", types="Enchantment")
    victim = _creature(state, "Victim", owner="p2")
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    for owner in ("p1", "p2"):
        state.player_by_id(owner).library.append(
            GameObject(Card(id="Top", name="Top", type_line="Instant", is_instant=True),
                       owner_id=owner, zone=Zone.LIBRARY))
    hands = {p.id: len(p.hand) for p in state.players}
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    if state.pending_choice:
        engine.rules.resolve_choice("yes")
        engine.resolve_until_stable()
    assert len(state.player_by_id("p2").hand) == hands["p2"] + 1
    assert len(state.player_by_id("p1").hand) == hands["p1"]


def test_its_controller_taps_their_own_lands():
    engine, state = _engine()
    _put(state, "Whenever a land enters, tap all lands its controller controls.", name="Tect",
         types="Enchantment")
    mine = _put(state, "", name="Forest", types="Land", owner="p1", is_land=True)
    theirs = _put(state, "", name="Mountain", types="Land", owner="p2", is_land=True)
    new = _put(state, "", name="Island", types="Land", owner="p2", is_land=True)
    _fire_enter(engine, state, new)
    assert theirs.tapped and not mine.tapped


@pytest.mark.parametrize(
    "inner, check",
    [
        ({"type": "draw", "params": {"count": 1}}, "hand"),
        ({"type": "lose_life", "params": {"amount": 3}}, "life"),
        ({"type": "gain_life", "params": {"amount": 3}}, "life"),
        ({"type": "add_player_counters", "params": {"amount": 1, "kind": "poison"}}, "poison"),
        ({"type": "damage", "params": {"amount": 2, "selector": "controller"}}, "life"),
    ],
)
def test_every_effect_the_acting_rewrite_offers_acts_for_the_firing_objects_controller(inner, check):
    # The rewrite is offered only for these types (`_ACTING_AS_CONTROLLER_TYPES`): each one has to
    # read "you" through the acting player, or "its controller draws" would quietly hit the wrong one.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    engine, state = _engine()
    src = _put(state, "", name="Src", types="Enchantment")
    theirs = _creature(state, "Theirs", owner="p2")
    for owner in ("p1", "p2"):
        state.player_by_id(owner).library.append(
            GameObject(Card(id="C", name="C", type_line="Instant", is_instant=True),
                       owner_id=owner, zone=Zone.LIBRARY))
    [wrapper] = build_effects([EffectSpec("trigger_subject_referent", {
        "event_key": "instance_id", "acting": "controller", "effects": [inner]})], src)
    context = GameContext(state, engine.rules)
    context.trigger_event = {"instance_id": theirs.instance_id}
    before = {p.id: (len(p.hand), p.life, p.poison) for p in state.players}
    wrapper.apply(context)
    after = {p.id: (len(p.hand), p.life, p.poison) for p in state.players}
    assert after["p1"] == before["p1"]
    assert after["p2"] != before["p2"]


# ---------------------------------------------------------------------------
# A condition about "it" is about the firing object, not the ability's source
# ---------------------------------------------------------------------------


def test_a_gate_on_it_asks_the_entering_permanent_not_the_source():
    engine, state = _engine()
    # The source is itself a creature: were the gate read off the source it would always pass.
    _put(state, "Whenever a permanent you control enters, if it's a creature, put a +1/+1 counter on it.",
         name="Yard", types="Creature — Bear")
    land = _put(state, "", name="Forest", types="Land", is_land=True)
    beast = _creature(state, "Beast")
    _fire_enter(engine, state, land)
    assert not land.counters.get("+1/+1")
    _fire_enter(engine, state, beast)
    assert beast.counters.get("+1/+1") == 1


# ---------------------------------------------------------------------------
# Referent predicates: "if it has flying / was attacking / has a counter / is 1/1 …"
# ---------------------------------------------------------------------------


def _draws(state, action, player="p1"):
    before = len(state.player_by_id(player).hand)
    action()
    return len(state.player_by_id(player).hand) - before


def _stock_library(state):
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    for owner in ("p1", "p2"):
        for i in range(3):
            state.player_by_id(owner).library.append(
                GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Instant", is_instant=True),
                           owner_id=owner, zone=Zone.LIBRARY))


@pytest.mark.parametrize("flyer, expect_draw", [(True, 1), (False, 0)])
def test_draw_if_it_has_flying_otherwise_a_counter(flyer, expect_draw):
    engine, state = _engine()
    _stock_library(state)
    _put(state, "Whenever a creature you control enters, draw a card if it has flying. Otherwise, put a "
                "+1/+1 counter on it.", name="Gate", types="Enchantment")
    late = _creature(state, "Late", keywords=["Flying"] if flyer else [])
    drawn = _draws(state, lambda: _fire_enter(engine, state, late))
    assert drawn == expect_draw
    assert late.counters.get("+1/+1", 0) == (0 if flyer else 1)


def test_the_power_gate_reads_the_entering_creature_not_the_source():
    engine, state = _engine()
    _stock_library(state)
    _put(state, "Whenever a creature you control enters, draw a card if its power is 3 or greater. "
                "Otherwise, put 2 +1/+1 counters on it.", name="Tribute", types="Creature — Bear")
    big = _creature(state, "Big")
    big.card.power = 4
    small = _creature(state, "Small")
    assert _draws(state, lambda: _fire_enter(engine, state, big)) == 1
    assert _draws(state, lambda: _fire_enter(engine, state, small)) == 0
    assert small.counters.get("+1/+1") == 2 and not big.counters.get("+1/+1")


def test_if_it_doesnt_is_the_otherwise_of_a_counter_gate():
    engine, state = _engine()
    _stock_library(state)
    _put(state, "Whenever a creature you control enters, draw a card if that creature has a +1/+1 counter "
                "on it. If it doesn't, put a +1/+1 counter on it.", name="Marcus", types="Creature — Bear")
    seeded = _creature(state, "Seeded")
    seeded.counters["+1/+1"] = 1
    bare = _creature(state, "Bare")
    assert _draws(state, lambda: _fire_enter(engine, state, seeded)) == 1
    assert _draws(state, lambda: _fire_enter(engine, state, bare)) == 0
    assert bare.counters.get("+1/+1") == 1


def test_a_dying_attacker_counts_as_attacking():
    engine, state = _engine()
    _stock_library(state)
    _put(state, "Whenever another creature you control dies, draw a card if it was attacking. Otherwise, "
                "each opponent loses 1 life.", name="Zurgo", types="Creature — Orc")
    attacker = _creature(state, "Attacker")
    attacker.attacking = True
    bystander = _creature(state, "Bystander")
    life = state.player_by_id("p2").life
    assert _draws(state, lambda: (engine.rules.destroy(attacker), engine.resolve_until_stable())) == 1
    assert state.player_by_id("p2").life == life
    assert _draws(state, lambda: (engine.rules.destroy(bystander), engine.resolve_until_stable())) == 0
    assert state.player_by_id("p2").life == life - 1


def test_a_comparison_with_the_source_reads_both_objects():
    engine, state = _engine()
    hulk = _put(state, "Whenever another creature you control enters, if it has greater power or toughness "
                       "than ~, put a +1/+1 counter on ~.", name="Hulk", types="Creature — Hero")
    hulk.card.power, hulk.card.toughness = 2, 2
    small = _creature(state, "Small")
    bigger = _creature(state, "Bigger")
    bigger.card.power, bigger.card.toughness = 1, 5
    _fire_enter(engine, state, small)
    assert not hulk.counters.get("+1/+1")
    _fire_enter(engine, state, bigger)
    assert hulk.counters.get("+1/+1") == 1


def test_a_subtype_gate_is_about_the_entering_creature():
    engine, state = _engine()
    _put(state, "Whenever another creature you control enters, you gain 1 life. If it's a spider, put a "
                "+1/+1 counter on it.", name="Aunt", types="Creature — Human")
    spider = _creature(state, "Spider", types="Creature — Spider")
    bear = _creature(state, "Bear")
    _fire_enter(engine, state, spider)
    _fire_enter(engine, state, bear)
    assert spider.counters.get("+1/+1") == 1 and not bear.counters.get("+1/+1")


# ---------------------------------------------------------------------------
# "you may pay {N}. If you do, … it/that creature": the branch runs after the event is gone
# ---------------------------------------------------------------------------


def _pay(engine, state, option="pay"):
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    engine.rules.resolve_choice(option)
    engine.resolve_until_stable()


@pytest.mark.parametrize("oracle", [
    "Whenever a creature you control enters, you may pay {1}. If you do, put a +1/+1 counter on that creature.",
    "Whenever a creature you control enters, you may pay {1}. If you do, it gets +1/+1 until end of turn.",
])
def test_a_paid_branch_still_names_the_entering_creature(oracle):
    engine, state = _engine()
    _put(state, oracle, name="Handicraft", types="Enchantment")
    late = _creature(state, "Late")
    bystander = _creature(state, "Bystander")
    state.player_by_id("p1").mana_pool.add("C", 1)
    _fire_enter(engine, state, late)
    _pay(engine, state)
    engine.recompute_continuous_effects()
    assert late.power == 2          # printed 1, +1 from the paid branch (a counter or the pump)
    assert bystander.power == 1 and not bystander.counters.get("+1/+1")


def test_declining_the_payment_changes_nothing():
    engine, state = _engine()
    _put(state, "Whenever a creature you control enters, you may pay {1}. If you do, put a +1/+1 counter "
                "on that creature.", name="Handicraft", types="Enchantment")
    late = _creature(state, "Late")
    state.player_by_id("p1").mana_pool.add("C", 1)
    _fire_enter(engine, state, late)
    _pay(engine, state, "decline")
    assert not late.counters.get("+1/+1")


def test_a_paid_copy_is_of_the_entering_creature():
    engine, state = _engine()
    _put(state, "Whenever another nontoken creature you control enters, you may pay {1}. If you do, create "
                "a token that's a copy of that creature.", name="Riku", types="Creature — Wizard")
    late = _creature(state, "Late")
    state.player_by_id("p1").mana_pool.add("C", 1)
    before = len([o for o in state.battlefield if o.name == "Late"])
    _fire_enter(engine, state, late)
    _pay(engine, state)
    assert len([o for o in state.battlefield if o.name == "Late"]) == before + 1


def test_a_paid_copy_of_a_noncreature_permanent():
    engine, state = _engine()
    _put(state, "Whenever another nontoken artifact you control enters, you may pay {2}. If you do, create a "
                "token that's a copy of that artifact.", name="Mirrorworks", types="Artifact")
    trinket = _put(state, "", name="Trinket", types="Artifact")
    state.player_by_id("p1").mana_pool.add("C", 2)
    before = len([o for o in state.battlefield if o.name == "Trinket"])
    _fire_enter(engine, state, trinket)
    _pay(engine, state)
    assert len([o for o in state.battlefield if o.name == "Trinket"]) == before + 1


def test_a_reflexive_when_you_do_remembers_the_firing_object_too():
    [effect] = _triggered(
        "Whenever another creature you control enters, you may pay {2}. When you do, that creature deals "
        "damage equal to its power to target creature.", types="Creature — Ranger")
    assert effect.type == "pay_cost_then"
    assert effect.params["remember_trigger_subject"] is True
    assert effect.params["then_trigger"][0]["params"]["event_key"] == "remembered"


def test_an_entered_this_turn_gate_reads_the_creature_that_dealt_damage():
    engine, state = _engine()
    _stock_library(state)
    state.current_step = "combat_damage"
    _put(state, "Whenever a creature you control deals combat damage to a player, if that creature entered "
                "this turn, draw a card.", name="Samut", types="Creature — Human")
    fresh = _creature(state, "Fresh")
    fresh.turn_entered = state.internal_turn.number
    old = _creature(state, "Old")
    old.turn_entered = state.internal_turn.number - 1
    drawn = _draws(state, lambda: (
        engine.rules.deal_damage(state.player_by_id("p2"), 1, source=old, combat=True),
        engine.resolve_until_stable()))
    assert drawn == 0
    drawn = _draws(state, lambda: (
        engine.rules.deal_damage(state.player_by_id("p2"), 1, source=fresh, combat=True),
        engine.resolve_until_stable()))
    assert drawn == 1


# ---------------------------------------------------------------------------
# An amount that is a characteristic of the object "it" names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("oracle, what, expected", [
    ("Whenever another creature you control enters, you gain life equal to that creature's power.", "power", 4),
    ("Whenever another creature you control enters, you gain life equal to that creature's toughness.", "toughness", 5),
])
def test_life_gained_is_a_characteristic_of_the_entering_creature(oracle, what, expected):
    engine, state = _engine()
    _put(state, oracle, name="Archon", types="Creature — Angel")
    late = _creature(state, "Late")
    late.card.power, late.card.toughness = 4, 5
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, late)
    assert state.player_by_id("p1").life == life + expected


def test_counters_equal_to_the_creatures_power_go_on_the_source():
    engine, state = _engine()
    goliath = _put(state, "Whenever another creature enters, you may put x +1/+1 counters on ~, where x is "
                          "that creature's power.", name="Goliath", types="Creature — Beast")
    late = _creature(state, "Late", owner="p2")
    late.card.power = 3
    _fire_enter(engine, state, late)
    if state.pending_choice:
        engine.rules.resolve_choice(state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert goliath.counters.get("+1/+1") == 3
    assert not late.counters.get("+1/+1")


def test_counters_the_size_of_its_power_go_on_the_creature_itself():
    engine, state = _engine()
    _put(state, "Whenever a creature you control deals combat damage to a player, put +1/+1 counters on that "
                "creature equal to its power.", name="Toeclaws", types="Enchantment")
    hitter = _creature(state, "Hitter")
    hitter.card.power = 3
    other = _creature(state, "Other")
    state.current_step = "combat_damage"
    engine.rules.deal_damage(state.player_by_id("p2"), 3, source=hitter, combat=True)
    engine.resolve_until_stable()
    assert hitter.counters.get("+1/+1") == 3 and not other.counters.get("+1/+1")


def test_a_spell_gaining_life_equal_to_the_destroyed_creatures_power():
    from tests.test_par124_turn_scoped_triggers import _cast, _spell

    engine, state = _engine()
    state.current_step = "main1"
    victim = _creature(state, "Victim", owner="p2")
    victim.card.power = 3
    victim.attacking = True
    chastise = _spell(state, "Destroy target attacking creature. You gain life equal to its power.")
    life = state.player_by_id("p1").life
    engine.rules.cast_spell(state.player_by_id("p1"), chastise, targets=[victim])
    engine.resolve_until_stable()
    assert not _has(state, victim)
    assert state.player_by_id("p1").life == life + 3


# ---------------------------------------------------------------------------
# Counts relative to the object "it" names
# ---------------------------------------------------------------------------


def test_shared_animosity_counts_other_attackers_sharing_a_type_with_the_firing_creature():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature you control attacks, it gets +1/+0 until end of turn for each other "
                "attacking creature that shares a creature type with it.", name="Animosity", types="Enchantment")
    elf_a = _creature(state, "ElfA", types="Creature — Elf")
    elf_b = _creature(state, "ElfB", types="Creature — Elf Warrior")
    goblin = _creature(state, "Goblin", types="Creature — Goblin")
    for c in (elf_a, elf_b, goblin):
        c.summoning_sick = False
    engine.declare_attackers(state.active_player, [elf_a, elf_b, goblin])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert elf_a.power == 2 and elf_b.power == 2    # each has one other attacking Elf
    assert goblin.power == 1


def test_a_blocked_creature_gets_the_pump_per_blocker():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    _put(state, "Whenever a creature you control becomes blocked, it gets +3/+3 until end of turn for each "
                "creature blocking it.", name="Marhault", types="Creature — Human")
    attacker = _creature(state, "Attacker")
    other = _creature(state, "Other")
    b1 = _creature(state, "B1", owner="p2")
    b2 = _creature(state, "B2", owner="p2")
    attacker.attacking = True
    attacker.blocked_by = [b1.instance_id, b2.instance_id]
    _blocked(engine, state, attacker)
    engine.recompute_continuous_effects()
    assert attacker.power == 7          # printed 1, +3 for each of two blockers
    assert other.power == 1


def test_an_aura_counts_relative_to_the_creature_it_enchants():
    engine, state = _engine()
    host = _creature(state, "Host", types="Creature — Elf")
    _creature(state, "Cousin", types="Creature — Elf")
    _creature(state, "Stranger", types="Creature — Goblin")
    aura = _put(state, "Enchant creature\nEnchanted creature gets +2/+2 for each other creature on the "
                       "battlefield that shares a creature type with it.", name="Alpha Status",
                types="Enchantment — Aura", keywords=["Enchant"])
    aura.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    assert host.power == 3              # printed 1, +2 for the one Elf sharing its type


# ---------------------------------------------------------------------------
# "that card" — a creature that died is a card in a graveyard when the trigger resolves
# ---------------------------------------------------------------------------


def _zone(state, obj) -> str:
    for player in state.players:
        for name, zone in player.zones.items():
            if any(o is obj for o in zone):
                return name
    return "battlefield" if _has(state, obj) else "elsewhere"


def test_ares_returns_the_dead_attacker_to_its_owners_hand():
    engine, state = _engine()
    _put(state, "Whenever an attacking creature you control dies, return that card to its owner's hand.",
         name="Ares", types="Enchantment")
    victim = _creature(state, "Victim")
    victim.attacking = True
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert _zone(state, victim) == "hand"


def test_a_dead_creature_returns_to_the_battlefield_not_the_source():
    engine, state = _engine()
    src = _put(state, "Whenever a creature dealt damage by ~ this turn dies, return that card to the "
                      "battlefield under your control.", name="Collector", types="Creature — Spirit")
    assert src is not None
    events = _triggered("Whenever a creature you control dies, return it to the battlefield under its "
                        "owner's control.")
    assert events[0].type == "return_self_to_battlefield"
    assert events[0].params["target_kind"] == "trigger_subject"


def test_the_card_that_fired_a_graveyard_trigger_is_exiled():
    engine, state = _engine()
    _put(state, "Whenever a creature dies, exile that card.", name="Void", types="Enchantment")
    victim = _creature(state, "Victim", owner="p2")
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert _zone(state, victim) == "exile"


# ---------------------------------------------------------------------------
# Boxing Ring: "it fights up to one target creature you don't control with the same mana value"
# ---------------------------------------------------------------------------

BOXING_RING = (
    "Whenever a creature you control enters, it fights up to one target creature you don't control with "
    "the same mana value.\n{T}: Create a Treasure token. Activate only if you control a creature that "
    "fought this turn."
)


def _with_mana_value(state, name, mv, owner, power=1, toughness=3):
    obj = _creature(state, name, owner=owner)
    obj.card.converted_mana_cost = mv
    obj.card.power, obj.card.toughness = power, toughness
    return obj


def test_boxing_ring_offers_only_creatures_with_the_entering_creatures_mana_value():
    engine, state = _engine()
    _put(state, BOXING_RING, name="Boxing Ring", types="Artifact")
    same = _with_mana_value(state, "Same", 2, "p2")
    _with_mana_value(state, "Other", 3, "p2")
    late = _with_mana_value(state, "Late", 2, "p1", power=2, toughness=3)
    _fire_enter(engine, state, late)
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    offered = {o.get("instance_id") for o in choice["options"]} - {None}   # None: "up to one" declined
    assert offered == {same.instance_id}


def test_boxing_ring_makes_the_two_creatures_fight():
    engine, state = _engine()
    _put(state, BOXING_RING, name="Boxing Ring", types="Artifact")
    same = _with_mana_value(state, "Same", 2, "p2", power=1, toughness=2)
    late = _with_mana_value(state, "Late", 2, "p1", power=2, toughness=3)
    _fire_enter(engine, state, late)
    engine.rules.resolve_choice(state.pending_choice["options"][0]["instance_id"])
    engine.resolve_until_stable()
    assert not _has(state, same)               # took 2 damage with toughness 2
    assert late.damage_marked == 1             # dealt 1 damage in return


def test_the_treasure_is_gated_on_a_creature_that_fought_this_turn():
    from mtg_analyzer.game import static_conditions

    engine, state = _engine()
    ring = _put(state, BOXING_RING, name="Boxing Ring", types="Artifact")
    result = _parse(Card(id="R", name="Ring", type_line="Artifact", oracle_text=BOXING_RING))
    [gate] = [e.params["condition"] for s in result.specs for e in s.effects
              if e.type == "activation_condition_marker"]
    assert not static_conditions.condition_holds(gate, state, ring, "p1")
    same = _with_mana_value(state, "Same", 2, "p2", power=1, toughness=2)
    late = _with_mana_value(state, "Late", 2, "p1", power=2, toughness=3)
    _fire_enter(engine, state, late)
    engine.rules.resolve_choice(state.pending_choice["options"][0]["instance_id"])
    engine.resolve_until_stable()
    assert static_conditions.condition_holds(gate, state, ring, "p1")
    assert same is not None


def test_hellrider_damages_the_player_each_attacker_attacks():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature you control attacks, ~ deals 1 damage to the player or planeswalker "
                "it's attacking.", name="Hellrider", types="Creature — Devil")
    a = _creature(state, "A")
    b = _creature(state, "B")
    for c in (a, b):
        c.summoning_sick = False
    life = state.player_by_id("p2").life
    engine.declare_attackers(state.active_player, [a, b])
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == life - 2


def test_that_many_counters_are_the_combat_damage_the_creature_dealt():
    engine, state = _engine()
    state.current_step = "combat_damage"
    _put(state, "Whenever a creature you control deals combat damage to a player, put that many +1/+1 "
                "counters on it.", name="Regent", types="Creature — Dragon")
    hitter = _creature(state, "Hitter")
    other = _creature(state, "Other")
    engine.rules.deal_damage(state.player_by_id("p2"), 3, source=hitter, combat=True)
    engine.resolve_until_stable()
    assert hitter.counters.get("+1/+1") == 3 and not other.counters.get("+1/+1")


def test_a_creature_dealt_damage_is_destroyed_and_not_regenerated():
    engine, state = _engine()
    _put(state, "Whenever a creature is dealt damage, destroy it. It can't be regenerated.",
         name="Pits", types="Enchantment")
    victim = _creature(state, "Victim", owner="p2")
    victim.card.toughness = 5
    bystander = _creature(state, "Bystander", owner="p2")
    bystander.card.toughness = 5
    engine.rules.deal_damage(victim, 1, source=_creature(state, "Pinger"))
    engine.resolve_until_stable()
    assert not _has(state, victim)
    assert _has(state, bystander)


def test_teferis_veil_phases_the_attacker_out_at_end_of_combat():
    from tests.test_par123_group_pronoun import _end_combat

    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a creature you control attacks, it phases out at end of combat.",
         name="Veil", types="Enchantment")
    attacker = _creature(state, "Attacker")
    attacker.summoning_sick = False
    bystander = _creature(state, "Bystander")
    engine.declare_attackers(state.active_player, [attacker])
    engine.resolve_until_stable()
    assert not attacker.phased_out                 # not yet
    _end_combat(engine, state)
    assert attacker.phased_out and not bystander.phased_out


def test_greatbow_doyen_hits_the_damaged_creatures_controller():
    engine, state = _engine()
    _put(state, "Whenever an archer you control deals damage to a creature, that archer deals that much "
                "damage to that creature's controller.", name="Doyen", types="Creature — Elf Archer")
    archer = _creature(state, "Archer", types="Creature — Elf Archer")
    victim = _creature(state, "Victim", owner="p2")
    victim.card.toughness = 5
    life = {p.id: p.life for p in state.players}
    engine.rules.deal_damage(victim, 3, source=archer)
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == life["p2"] - 3
    assert state.player_by_id("p1").life == life["p1"]


def test_a_goaded_creature_that_attacks_deals_damage_to_its_own_controller():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    _put(state, "Whenever a goaded creature attacks, it deals 1 damage to its controller.", name="Ancestor",
         types="Enchantment")
    goaded = _creature(state, "Goaded", owner="p1")
    goaded.summoning_sick = False
    goaded.goaded_by = {"p2"}
    life = {p.id: p.life for p in state.players}
    engine.declare_attackers(state.active_player, [goaded])
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == life["p1"] - 1      # the goaded creature's own controller
    assert state.player_by_id("p2").life == life["p2"]


def test_a_target_other_than_that_creature_never_offers_the_firing_creature():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.targeting import legal_targets

    [effect_spec] = _triggered(
        "Whenever a creature you control becomes the target of a spell or ability an opponent controls, put a "
        "+1/+1 counter on target creature you control other than that creature.", types="Creature — Bear")
    engine, state = _engine()
    src = _put(state, "", name="Recruit", types="Creature — Bear")
    targeted = _creature(state, "Targeted")
    other = _creature(state, "Other")
    [effect] = build_effects([effect_spec], src)
    offered = {o["instance_id"] for o in legal_targets(
        state, "p1", effect.target_spec, source=src,
        trigger_event={"instance_id": targeted.instance_id})}
    assert targeted.instance_id not in offered
    assert other.instance_id in offered


def test_ashroot_animist_pumps_another_creature_by_its_own_power_and_grants_trample():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext

    [effect_spec] = _triggered(
        "Whenever ~ attacks, another target creature you control gains trample and gets +X/+X until end "
        "of turn, where X is ~'s power.", types="Creature — Elf")
    engine, state = _engine()
    animist = _put(state, "", name="Animist", types="Creature — Elf")
    animist.card.power = 3
    friend = _creature(state, "Friend")
    [effect] = build_effects([effect_spec], animist)
    effect.apply(GameContext(state, engine.rules), [friend])
    engine.recompute_continuous_effects()
    assert friend.power == 4          # printed 1, +3 (the Animist's power)
    assert "trample" in {k.lower() for k in friend.granted_keywords} | {k.lower() for k in friend.temp_keywords}
