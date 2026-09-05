"""cEDH cube batch 25, wave 6 — the bespoke tail.

The shared new primitive is **two independently-chosen targets of different
kinds in one clause** (`GameEffect.extra_target_specs`), which was the whole
"two independent targeting effects on one ability" blocker: the gathering
paths now read `target_specs` (plural) and `_apply_effects_partitioned`
hands such an effect all of its groups flattened. Brass Squire, Halvar and
Archdruid's Charm all ride it.

Also here: Dauntless Dismantler's X-filtered mass destroy, Pemmin's Aura's
inline two-way modal, Dress Down, and the three planeswalkers — including a
``[-X]`` loyalty cost (RULE 606.5c) and Jeska's scoped, duration-bounded
damage multiplier.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _equipment(name="Sword"):
    """A real Equipment — i.e. one that actually prints Equip, which is what
    `RulesEngine._attachment_kind` reads to decide it can be attached at
    all. Brass Squire attaches it *without* the Equip cost being paid, which
    is the whole point of the card."""
    return _card(name, "Artifact — Equipment", "{2}", 2,
                 oracle_text="Equipped creature gets +2/+0.\nEquip {2}",
                 keywords=["Equip"])


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _catalogue_obj(name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# Two independently-chosen targets in one clause
# ---------------------------------------------------------------------------


def test_an_effect_can_announce_two_requirements_of_different_kinds():
    from mtg_analyzer.game.effects import AttachChosenEffect

    effect = AttachChosenEffect()
    kinds = [spec.kind for spec in effect.target_specs]
    assert kinds == ["equipment_you_control", "creature_you_control"]


def test_brass_squire_attaches_a_chosen_equipment_to_a_chosen_creature():
    engine, state, p1, _ = _engine()
    squire = _catalogue_obj("Brass Squire")
    state.add_to_battlefield(squire)
    sword = _bf(state, _equipment("Sword"))
    holder = _bf(state, _card("Holder"))

    engine.activate_ability(
        p1, squire, 0, target_groups=[[sword], [holder]],
    )
    engine.resolve_until_stable()

    assert sword.attached_to == holder.instance_id


def test_each_requirement_gets_its_own_slice_of_the_targets():
    """The two picks must not be read off the front of one shared list —
    that is exactly the bug `target_groups` exists to prevent."""
    engine, state, p1, _ = _engine()
    squire = _catalogue_obj("Brass Squire")
    state.add_to_battlefield(squire)
    sword = _bf(state, _equipment("Sword"))
    first_creature = _bf(state, _card("Decoy"))
    holder = _bf(state, _card("Holder"))

    engine.activate_ability(p1, squire, 0, target_groups=[[sword], [holder]])
    engine.resolve_until_stable()

    assert sword.attached_to == holder.instance_id
    assert first_creature.attached_to is None


def test_halvars_target_kind_needs_both_the_attachment_and_its_host_to_be_yours():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state, p1, p2 = _engine()
    mine_host = _bf(state, _card("MyBear"))
    theirs_host = _bf(state, _card("TheirBear"), controller="p2")
    attached_to_mine = _bf(state, _equipment("MySword"))
    attached_to_mine.attached_to = mine_host.instance_id
    attached_to_theirs = _bf(state, _equipment("OtherSword"))
    attached_to_theirs.attached_to = theirs_host.instance_id
    _bf(state, _equipment("Loose"))  # unattached

    spec = TargetSpec(kind="attached_aura_or_equipment_you_control")
    ids = {t["instance_id"] for t in legal_targets(state, "p1", spec)}

    assert ids == {attached_to_mine.instance_id}


def test_halvar_grants_double_strike_to_equipped_creatures_you_control():
    engine, state, p1, _ = _engine()
    halvar = _catalogue_obj("Halvar, God of Battle")
    state.add_to_battlefield(halvar)
    equipped = _bf(state, _card("Equipped"))
    plain = _bf(state, _card("Plain"))
    sword = _bf(state, _equipment("Sword"))
    sword.attached_to = equipped.instance_id

    engine.recompute_continuous_effects()

    assert "double strike" in equipped.granted_keywords
    assert "double strike" not in plain.granted_keywords


def test_archdruids_charm_counters_first_then_damages_with_the_boosted_power():
    """RULE 613's layer pass runs between the two halves — putting the
    counter on first is the entire point, and no separate damage effect
    could see the boosted power."""
    engine, state, p1, p2 = _engine()
    mine = _bf(state, _card("Mine"))                      # 2/2
    theirs = _bf(state, _card("Theirs"), controller="p2")  # 2/2

    spell = _catalogue_obj("Archdruid's Charm", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 4)
    engine.cast_spell(p1, spell, mode=1, target_groups=[[mine], [theirs]])
    engine.resolve_until_stable()

    assert mine.counters.get("+1/+1") == 1
    # 3 damage (2 base + the counter, not 2) is lethal to a 2/2, so the SBA
    # pass has already moved it — which is itself the proof the boosted
    # power was used.
    assert theirs not in state.battlefield
    assert theirs in p2.graveyard


def test_archdruids_charm_third_mode_can_exile_either_type():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state, p1, p2 = _engine()
    artifact = _bf(state, _card("Sol Ring", "Artifact", "{1}", 1), controller="p2")
    enchantment = _bf(state, _card("Rancor", "Enchantment", "{G}", 1), controller="p2")
    creature = _bf(state, _card("Bear"), controller="p2")

    spec = TargetSpec(kind="artifact_or_enchantment")
    ids = {t["instance_id"] for t in legal_targets(state, "p1", spec)}

    assert ids == {artifact.instance_id, enchantment.instance_id}
    assert creature.instance_id not in ids


# ---------------------------------------------------------------------------
# Dauntless Dismantler — a mass destroy filtered by the announced X
# ---------------------------------------------------------------------------


def test_dauntless_dismantler_destroys_exactly_the_artifacts_at_mana_value_x():
    engine, state, p1, p2 = _engine()
    dismantler = _catalogue_obj("Dauntless Dismantler")
    state.add_to_battlefield(dismantler)
    two_drop = _bf(state, _card("Signet", "Artifact", "{2}", 2), controller="p2")
    other_two = _bf(state, _card("Talisman", "Artifact", "{2}", 2))
    one_drop = _bf(state, _card("Sol Ring", "Artifact", "{1}", 1), controller="p2")
    creature = _bf(state, _card("Bear"), controller="p2")
    p1.mana_pool.add("W", 5)  # {X}{X}{W} with X = 2

    engine.activate_ability(p1, dismantler, 0, x=2)
    engine.resolve_until_stable()

    assert two_drop not in state.battlefield
    assert other_two not in state.battlefield   # yours too — "each artifact"
    assert one_drop in state.battlefield
    assert creature in state.battlefield


def test_dauntless_dismantlers_static_half_is_the_shipped_enters_tapped_rule():
    from mtg_analyzer.game import continuous

    engine, state, p1, p2 = _engine()
    dismantler = _catalogue_obj("Dauntless Dismantler")
    state.add_to_battlefield(dismantler)
    theirs = GameObject(_card("Sol Ring", "Artifact", "{1}", 1), owner_id="p2",
                        zone=Zone.STACK)
    mine = GameObject(_card("Talisman", "Artifact", "{2}", 2), owner_id="p1",
                      zone=Zone.STACK)

    assert continuous.enters_tapped_from_static(state, theirs) is True
    assert continuous.enters_tapped_from_static(state, mine) is False


# ---------------------------------------------------------------------------
# Pemmin's Aura — the inline two-way modal, split into two abilities
# ---------------------------------------------------------------------------


def test_pemmins_aura_offers_both_halves_of_its_inline_modal():
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    aura = _catalogue_obj("Pemmin's Aura")
    aura.attached_to = host.instance_id
    state.add_to_battlefield(aura)

    # Untap, flying, shroud, +1/-1, -1/+1 — the last two being the split
    # halves of the printed "or" sentence.
    assert len(aura.activated_abilities) == 5


def test_pemmins_aura_pumps_the_enchanted_creature_either_way():
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    aura = _catalogue_obj("Pemmin's Aura")
    aura.attached_to = host.instance_id
    state.add_to_battlefield(aura)
    p1.mana_pool.add("U", 5)

    engine.activate_ability(p1, aura, 3)  # +1/-1
    engine.resolve_until_stable()
    assert (host.power, host.toughness) == (3, 1)

    engine.activate_ability(p1, aura, 4)  # -1/+1
    engine.resolve_until_stable()
    assert (host.power, host.toughness) == (2, 2)


def test_pemmins_aura_untaps_the_enchanted_creature():
    engine, state, p1, _ = _engine()
    host = _bf(state, _card("Host"))
    host.tapped = True
    aura = _catalogue_obj("Pemmin's Aura")
    aura.attached_to = host.instance_id
    state.add_to_battlefield(aura)
    p1.mana_pool.add("U", 1)

    engine.activate_ability(p1, aura, 0)
    engine.resolve_until_stable()

    assert host.tapped is False


# ---------------------------------------------------------------------------
# Dress Down
# ---------------------------------------------------------------------------


def test_dress_down_strips_creature_abilities_but_keeps_its_own():
    engine, state, p1, _ = _engine()
    flier = _bf(state, _card("Flier", keywords=["Flying"]))
    dress_down = _catalogue_obj("Dress Down")
    state.add_to_battlefield(dress_down)

    engine.recompute_continuous_effects()

    assert flier.loses_all_abilities is True
    assert dress_down.loses_all_abilities is False  # it names *creatures*


def test_dress_down_draws_on_entry_and_sacrifices_itself_at_end_step():
    engine, state, p1, _ = _engine()
    for i in range(3):
        p1.add_to_zone(
            GameObject(_card(f"Lib{i}", "Instant", "{U}", 1), owner_id="p1",
                       zone=Zone.LIBRARY),
            Zone.LIBRARY,
        )
    dress_down = _catalogue_obj("Dress Down")
    state.add_to_battlefield(dress_down)

    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD,
        instance_id=dress_down.instance_id,
        controller_id="p1",
        object_types=sorted(dress_down.type_words),
    ))
    engine.resolve_until_stable()
    assert len(p1.hand) == 1

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end"))
    engine.resolve_until_stable()
    assert dress_down not in state.battlefield


# ---------------------------------------------------------------------------
# Professor Onyx
# ---------------------------------------------------------------------------


def test_professor_onyxs_minus_three_takes_the_biggest_creature():
    """The one place the engine's arbitrary auto-pick would be actively
    *wrong* — the card's whole effect is that a spare token can't dodge it."""
    engine, state, p1, p2 = _engine()
    onyx = _catalogue_obj("Professor Onyx")
    onyx.add_counters("loyalty", 5)
    state.add_to_battlefield(onyx)
    chaff = _bf(state, _card("Chaff", power=1, toughness=1), controller="p2")
    fatty = _bf(state, _card("Fatty", power=7, toughness=7), controller="p2")

    engine.activate_ability(p1, onyx, 1)
    engine.resolve_until_stable()

    assert fatty not in state.battlefield
    assert chaff in state.battlefield


def test_professor_onyxs_ultimate_runs_seven_rounds():
    engine, state, p1, p2 = _engine()
    onyx = _catalogue_obj("Professor Onyx")
    onyx.add_counters("loyalty", 10)
    state.add_to_battlefield(onyx)
    for i in range(3):
        p2.add_to_zone(
            GameObject(_card(f"Card{i}", "Instant", "{U}", 1), owner_id="p2",
                       zone=Zone.HAND),
            Zone.HAND,
        )

    engine.activate_ability(p1, onyx, 2)
    engine.resolve_until_stable()

    # RULE 118.3: each round is a real "discard, or lose 3 life?" prompt,
    # chained one at a time — pay the first three, and the last four rounds
    # find an empty hand and skip straight to the life loss.
    for _ in range(3):
        assert state.pending_choice["kind"] == "pay_cost_then"
        engine.resolve_pending_choice("pay")
    assert state.pending_choice is None

    # Three discards, then four rounds of 3 life with an empty hand.
    assert p2.hand == []
    assert p2.life == 20 - 4 * 3


def test_professor_onyxs_ultimate_leaves_its_controller_alone():
    engine, state, p1, p2 = _engine()
    onyx = _catalogue_obj("Professor Onyx")
    onyx.add_counters("loyalty", 10)
    state.add_to_battlefield(onyx)

    engine.activate_ability(p1, onyx, 2)
    engine.resolve_until_stable()

    assert p1.life == 20  # "each *opponent*"


# ---------------------------------------------------------------------------
# Tevesh Szat, Doom of Fools
# ---------------------------------------------------------------------------


def test_tevesh_szats_ultimate_gathers_every_commander_under_your_control():
    engine, state, p1, p2 = _engine()
    szat = _catalogue_obj("Tevesh Szat, Doom of Fools")
    szat.add_counters("loyalty", 12)
    state.add_to_battlefield(szat)

    on_board = _bf(state, _card("TheirGeneral"), controller="p2")
    on_board.is_commander = True
    in_command = GameObject(_card("CommandZoneGeneral"), owner_id="p2", zone=Zone.COMMAND)
    in_command.is_commander = True
    p2.add_to_zone(in_command, Zone.COMMAND)

    engine.activate_ability(p1, szat, 2)
    engine.resolve_until_stable()

    assert on_board.controller_id == "p1"
    assert in_command in state.battlefield
    assert in_command.controller_id == "p1"
    assert in_command not in p2.command


def test_tevesh_szats_plus_two_makes_two_thrulls():
    engine, state, p1, _ = _engine()
    szat = _catalogue_obj("Tevesh Szat, Doom of Fools")
    szat.add_counters("loyalty", 3)
    state.add_to_battlefield(szat)

    engine.activate_ability(p1, szat, 0)
    engine.resolve_until_stable()

    thrulls = [o for o in state.battlefield if o.name == "Thrull"]
    assert len(thrulls) == 2
    assert all(o.controller_id == "p1" for o in thrulls)


# ---------------------------------------------------------------------------
# Jeska, Thrice Reborn — a [-X] loyalty cost and a scoped damage multiplier
# ---------------------------------------------------------------------------


def test_a_minus_x_loyalty_cost_removes_the_announced_x():
    """RULE 606.5c's ``[-X]`` — the loyalty removed is the announced X, not a
    printed constant."""
    engine, state, p1, p2 = _engine()
    jeska = _catalogue_obj("Jeska, Thrice Reborn")
    jeska.add_counters("loyalty", 6)
    state.add_to_battlefield(jeska)

    engine.activate_ability(p1, jeska, 1, targets=[p2], x=4)
    engine.resolve_until_stable()

    assert jeska.counters.get("loyalty") == 2
    assert p2.life == 16


def test_a_minus_x_loyalty_cost_cannot_exceed_the_loyalty_on_hand():
    engine, state, p1, p2 = _engine()
    jeska = _catalogue_obj("Jeska, Thrice Reborn")
    jeska.add_counters("loyalty", 2)
    state.add_to_battlefield(jeska)

    ability = jeska.activated_abilities[1]
    assert engine.can_activate(p1, jeska, ability, x=2) is True
    assert engine.can_activate(p1, jeska, ability, x=3) is False


def test_jeskas_zero_triples_that_creatures_combat_damage_to_your_opponents():
    engine, state, p1, p2 = _engine()
    jeska = _catalogue_obj("Jeska, Thrice Reborn")
    jeska.add_counters("loyalty", 3)
    state.add_to_battlefield(jeska)
    attacker = _bf(state, _card("Attacker", power=3, toughness=3))

    engine.activate_ability(p1, jeska, 0, targets=[attacker])
    engine.resolve_until_stable()

    engine.rules.deal_damage(p2, 3, source=attacker, combat=True)
    assert p2.life == 20 - 9


def test_jeskas_zero_leaves_noncombat_damage_and_its_controller_alone():
    engine, state, p1, p2 = _engine()
    jeska = _catalogue_obj("Jeska, Thrice Reborn")
    jeska.add_counters("loyalty", 3)
    state.add_to_battlefield(jeska)
    attacker = _bf(state, _card("Attacker", power=3, toughness=3))

    engine.activate_ability(p1, jeska, 0, targets=[attacker])
    engine.resolve_until_stable()

    engine.rules.deal_damage(p2, 3, source=attacker, combat=False)
    assert p2.life == 17  # noncombat — untouched

    engine.rules.deal_damage(p1, 3, source=attacker, combat=True)
    assert p1.life == 17  # "one of your *opponents*"


def test_jeskas_multiplier_lapses_at_your_next_turn():
    engine, state, p1, p2 = _engine()
    jeska = _catalogue_obj("Jeska, Thrice Reborn")
    jeska.add_counters("loyalty", 3)
    state.add_to_battlefield(jeska)
    attacker = _bf(state, _card("Attacker", power=3, toughness=3))
    engine.activate_ability(p1, jeska, 0, targets=[attacker])
    engine.resolve_until_stable()

    state.internal_turn.number = 1  # p1 is active; their next turn is two begin_turns away
    engine.begin_turn()
    assert attacker.replacement_effects
    engine.begin_turn()
    assert attacker.replacement_effects == []
