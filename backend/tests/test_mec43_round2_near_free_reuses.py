"""MEC-43 round 2 "near-free reuses" batch (2026-08-24) — closes 17 more
cards across `cEDH staples 2`/`K'rrik cEDH` (5 via parser-regex widenings,
12 hand-authored), each needing only a small param widening of an existing
primitive. Covers the genuinely new/widened primitives:

Parser widenings: `graveyard_library_cast_prohibition`/`_entry_prohibition`'s
new ``zones`` param (Kunoros, Hound of Athreos — "graveyards", no
"or/and libraries"); `trigger_prohibition`'s DIES sibling (Hushbringer's
"entering **or dying**"); `enters_tapped_static`'s per-word ``nonbasic``
(Thalia, Heretic Cathar's mixed "creatures and nonbasic lands");
`reveal_hand_choose_discard`'s new ``max_mana_value``/trailing ``lose_life``
riders (Inquisition of Kozilek/Thoughtseize).

Hand-authored, new/widened primitives: `targeting._GRAVEYARD_TYPE_FILTERS`'s
``artifact_or_creature`` combined filter (Beacon of Unrest);
`GrantUntilEffect`'s ``duration="rest_of_game"``/``previous_subject`` combo
applied to `type_change`/`color_change` (Rise from the Grave/Chainer,
Dementia Master); `ReturnFromGraveyardEffect`'s new ``tapped``/
``trigger_subject_key="remembered"`` (Tenacious Dead, via
`PayCostThenEffect.remember_trigger_subject`); `ExileAllGraveyardsEffect`'s
new ``colors`` filter + `graveyard_redirect`'s new ``colors`` param
(Sanctifier en-Vec); `remove_all_abilities`/`type_change`/`color_change`
composed on ``affects="attached_permanent"`` (Kenrith's Transformation, the
"Elk" template); `count_selector`'s new
``"colors_among_permanents_you_control"`` (Conqueror's Flail/Faeburrow
Elder) plus `static_conditions`' new ``"all"`` AND-combinator (Conqueror's
Flail's two-gate cast lockdown); the qualified `combat_restriction` +
`TriggerDoublerEffect`'s new ``min_power``/``max_power`` axis (Delney,
Streetwise Lookout); `effect_binder._group_ok`'s list-``type`` OR support
(Runic Armasaur's "creature or land"); `DrawCardEffect`'s new
``"half_target_library_round_up"`` selector + `LoseLifeEffect`'s new
``amount_from_half_target_life``/``previous_subject`` (Peer into the
Abyss); the new `ExchangeLifeTotalsEffect` (Soul Conduit).

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bear(name="Bear", cost="{1}{G}", cmc=2, power=2, toughness=2, **kw):
    return _card(
        name, "Creature — Bear", cost, cmc, is_creature=True, power=power, toughness=toughness, **kw,
    )


def _bf(state, card, controller="p1", obj=None, bind=False):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    if bind:
        bind_from_catalogue(obj)
    return obj


def _catalogue_obj(state, name, controller="p1", zone=Zone.BATTLEFIELD, sick=False):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = sick
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def _gy(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Kunoros, Hound of Athreos — graveyard_library_*'s new ``zones`` param
# ---------------------------------------------------------------------------


def test_kunoros_prohibits_graveyard_cast_and_entry_but_not_library():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Kunoros, Hound of Athreos", controller="p1")
    engine.recompute_continuous_effects()

    assert continuous.graveyard_library_cast_prohibited(state, zone="graveyard") is True
    assert continuous.graveyard_library_cast_prohibited(state, zone="library") is False

    creature_card = _bear("Reanimated Bear")
    assert continuous.graveyard_library_entry_prohibited(state, creature_card, zone="graveyard") is True
    assert continuous.graveyard_library_entry_prohibited(state, creature_card, zone="library") is False


# ---------------------------------------------------------------------------
# Hushbringer — trigger_prohibition's DIES sibling
# ---------------------------------------------------------------------------


def test_hushbringer_suppresses_both_etb_and_dies_triggers():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Hushbringer", controller="p2")
    engine.recompute_continuous_effects()

    etb_event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=1, object_types=["creature"])
    dies_event = GameEvent(EventType.DIES, instance_id=1, object_types=["creature"])
    other_event = GameEvent(EventType.ATTACKS, instance_id=1, player_id="p1", object_types=["creature"])

    assert continuous.trigger_suppressed(state, etb_event) is True
    assert continuous.trigger_suppressed(state, dies_event) is True
    assert continuous.trigger_suppressed(state, other_event) is False


# ---------------------------------------------------------------------------
# Thalia, Heretic Cathar — enters_tapped_static's per-word ``nonbasic``
# ---------------------------------------------------------------------------


def test_thalia_taps_opponents_creatures_and_only_nonbasic_lands():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Thalia, Heretic Cathar", controller="p1")
    engine.recompute_continuous_effects()

    opp_creature = _card("Opp Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    basic_land = _card("Forest", "Basic Land — Forest", is_land=True)
    nonbasic_land = _card("Ancient Tomb", "Land", is_land=True)

    assert continuous.enters_tapped_from_static(state, GameObject(opp_creature, owner_id="p2")) is True
    assert continuous.enters_tapped_from_static(state, GameObject(basic_land, owner_id="p2")) is False
    assert continuous.enters_tapped_from_static(state, GameObject(nonbasic_land, owner_id="p2")) is True
    # Thalia's own controller is unaffected either way.
    assert continuous.enters_tapped_from_static(state, GameObject(opp_creature, owner_id="p1")) is False


# ---------------------------------------------------------------------------
# Thoughtseize / Inquisition of Kozilek — reveal_hand_choose_discard riders
# ---------------------------------------------------------------------------


def test_thoughtseize_execute_via_effect_binder():
    from mtg_analyzer.game.ability_catalogue import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry
    from mtg_analyzer.game.effects.core import GameContext

    engine, state, p1, p2 = _engine()
    spell_card = _named("Thoughtseize")
    source = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)
    hand_land = GameObject(_card("Swamp", "Basic Land — Swamp", is_land=True), owner_id="p2", zone=Zone.HAND)
    hand_creature = GameObject(_bear("Bob's Bear"), owner_id="p2", zone=Zone.HAND)
    p2.hand.extend([hand_land, hand_creature])
    p1.life = 20

    spec = specs_for(spell_card)[0]
    context = GameContext(state, engine.rules)
    context.source = source
    for effect_spec in spec.effects:
        effect = EffectRegistry.create(effect_spec.type, effect_spec.params)
        effect.source = source
        effect.apply(context, targets=[p2])

    assert hand_creature not in p2.hand
    assert hand_creature in p2.graveyard
    assert hand_land in p2.hand  # the land was never a legal choice
    assert p1.life == 18


def test_inquisition_of_kozilek_only_offers_cheap_nonland_cards():
    from mtg_analyzer.game.ability_catalogue import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    engine, state, p1, p2 = _engine()
    spell_card = _named("Inquisition of Kozilek")
    source = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)
    cheap = GameObject(_bear("Cheap Bear", cmc=2), owner_id="p2", zone=Zone.HAND)
    expensive = GameObject(_bear("Expensive Bear", cmc=6), owner_id="p2", zone=Zone.HAND)
    p2.hand.extend([cheap, expensive])

    spec = specs_for(spell_card)[0]
    context = GameContext(state, engine.rules)
    context.source = source
    effect_spec = spec.effects[0]
    effect = EffectRegistry.create(effect_spec.type, effect_spec.params)
    effect.source = source
    effect.apply(context, targets=[p2])

    assert cheap not in p2.hand
    assert expensive in p2.hand


# ---------------------------------------------------------------------------
# Sanctifier en-Vec — exile_all_graveyards' colors + graveyard_redirect's colors
# ---------------------------------------------------------------------------


def test_sanctifier_en_vec_etb_exiles_only_black_or_red_graveyard_cards():
    engine, state, p1, p2 = _engine()
    black_card = _gy(state, _card("Dead Zombie", "Creature — Zombie", is_creature=True, color_identity={"B"}), owner="p2")
    green_card = _gy(state, _card("Dead Elf", "Creature — Elf", is_creature=True, color_identity={"G"}), owner="p2")

    _catalogue_obj(state, "Sanctifier en-Vec", controller="p1")
    engine.recompute_continuous_effects()
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=999999))
    # The ETB is bound to the creature's own instance_id, so fire it for real.
    sanctifier = next(o for o in state.battlefield if o.name == "Sanctifier en-Vec")
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=sanctifier.instance_id))
    engine.resolve_until_stable()

    assert black_card in p2.exile
    assert green_card in p2.graveyard


def test_sanctifier_en_vec_redirects_only_colored_graveyard_moves():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Sanctifier en-Vec", controller="p1")
    engine.recompute_continuous_effects()

    red_creature = _bf(state, _card("Red Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"R"}), controller="p2", bind=True)
    green_creature = _bf(state, _card("Green Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"G"}), controller="p2", bind=True)

    engine.rules.destroy(red_creature)
    engine.rules.destroy(green_creature)

    assert red_creature in p2.exile
    assert green_creature in p2.graveyard


# ---------------------------------------------------------------------------
# Beacon of Unrest / Rise from the Grave — reanimation-family wrinkles
# ---------------------------------------------------------------------------


def test_beacon_of_unrest_reanimates_artifact_and_shuffles_itself_into_library():
    from mtg_analyzer.game.ability_catalogue import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext

    engine, state, p1, p2 = _engine()
    artifact = _gy(state, _card("Dead Artifact", "Artifact"), owner="p1")
    spell_card = _named("Beacon of Unrest")
    source = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)
    state.player_by_id("p1").library.clear()

    spec = specs_for(spell_card)[0]
    context = GameContext(state, engine.rules)
    context.source = source
    for effect_spec in spec.effects:
        effect = EffectRegistry.create(effect_spec.type, effect_spec.params)
        effect.source = source
        effect.apply(context, targets=[artifact])

    assert artifact in state.battlefield
    assert artifact.controller_id == "p1"
    assert any(o.card.name == "Beacon of Unrest" for o in p1.library)


def test_rise_from_the_grave_makes_the_reanimated_creature_a_black_zombie():
    from mtg_analyzer.game.ability_catalogue import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext, _apply_effects_partitioned

    engine, state, p1, p2 = _engine()
    creature_card = _card("Red Dragon", "Creature — Dragon", is_creature=True, power=4, toughness=4, color_identity={"R"})
    creature = _gy(state, creature_card, owner="p2")
    spell_card = _named("Rise from the Grave")
    source = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)

    spec = specs_for(spell_card)[0]
    context = GameContext(state, engine.rules)
    context.source = source
    effects = []
    for effect_spec in spec.effects:
        effect = EffectRegistry.create(effect_spec.type, effect_spec.params)
        effect.source = source
        effects.append(effect)
    # `grant_until`'s `previous_subject` reads `GameContext.previous_targets`,
    # which only `_apply_effects_partitioned` (the real per-ability dispatch)
    # maintains between effects — a bare per-effect loop, unlike every other
    # test in this file, would leave it empty.
    _apply_effects_partitioned(effects, context, [creature], None, source=source)
    engine.recompute_continuous_effects()

    assert creature in state.battlefield
    assert creature.controller_id == "p1"
    assert combat.matches_object_filter(creature, {"subtype": "zombie"}) is True
    assert "B" in creature.colors
    assert "R" in creature.colors  # "in addition to its other colors"


# ---------------------------------------------------------------------------
# Tenacious Dead — DIES trigger, pay_cost_then, trigger_subject_key
# ---------------------------------------------------------------------------


def test_tenacious_dead_returns_tapped_when_the_cost_is_paid():
    engine, state, p1, p2 = _engine()
    skeleton = _catalogue_obj(state, "Tenacious Dead", controller="p1")
    p1.mana_pool.add_many({"B": 1, "C": 1})
    engine.recompute_continuous_effects()

    engine.rules.destroy(skeleton)
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice.get("kind") == "pay_cost_then"
    engine.rules.resolve_choice("pay")
    engine.resolve_until_stable()

    returned = next((o for o in state.battlefield if o.name == "Tenacious Dead"), None)
    assert returned is not None
    assert returned.tapped is True
    assert returned.controller_id == "p1"


def test_tenacious_dead_stays_dead_when_the_cost_is_declined():
    engine, state, p1, p2 = _engine()
    skeleton = _catalogue_obj(state, "Tenacious Dead", controller="p1")
    engine.recompute_continuous_effects()  # no mana in pool — can't pay

    engine.rules.destroy(skeleton)
    engine.resolve_until_stable()

    assert not any(o.name == "Tenacious Dead" for o in state.battlefield)
    assert skeleton in p1.graveyard


# ---------------------------------------------------------------------------
# Chainer, Dementia Master — anthem + activated reanimation + leaves-trigger
# ---------------------------------------------------------------------------


def test_chainer_anthem_and_reanimation_and_leaves_trigger():
    engine, state, p1, p2 = _engine()
    chainer = _catalogue_obj(state, "Chainer, Dementia Master", controller="p1")
    nightmare = _bf(state, _card("Stock Nightmare", "Creature — Nightmare", is_creature=True, power=2, toughness=2), controller="p1", bind=True)
    p1.mana_pool.add_many({"B": 3})
    p1.life = 20
    dead_creature = _gy(state, _card("Dead Ogre", "Creature — Ogre", is_creature=True, power=3, toughness=3, color_identity={"R"}), owner="p2")
    engine.recompute_continuous_effects()

    assert nightmare.power == 3 and nightmare.toughness == 3  # +1/+1 anthem

    engine.activate_ability(p1, chainer, ability_index=0, targets=[dead_creature])
    engine.resolve_until_stable()

    assert dead_creature in state.battlefield
    assert dead_creature.controller_id == "p1"
    assert combat.matches_object_filter(dead_creature, {"subtype": "nightmare"}) is True
    assert "B" in dead_creature.colors
    engine.recompute_continuous_effects()
    assert dead_creature.power == 4  # also got the Nightmare anthem now

    engine.rules.destroy(chainer)
    engine.resolve_until_stable()

    assert nightmare not in state.battlefield
    assert dead_creature not in state.battlefield
    assert nightmare in p1.exile
    assert dead_creature in p2.exile


# ---------------------------------------------------------------------------
# Kenrith's Transformation — the "Elk" template
# ---------------------------------------------------------------------------


def test_kenriths_transformation_turns_the_host_into_a_vanilla_elk():
    engine, state, p1, p2 = _engine()
    host = _bf(state, _card(
        "Angry Angel", "Creature — Angel", is_creature=True, power=5, toughness=5,
        keywords=["Flying"],
    ), controller="p2")
    host.summoning_sick = False
    aura = _catalogue_obj(state, "Kenrith's Transformation", controller="p1")
    aura.attached_to = host.instance_id
    before_hand = len(p1.hand)
    engine.recompute_continuous_effects()

    assert host.power == 3 and host.toughness == 3
    assert "G" in host.colors
    assert combat.matches_object_filter(host, {"subtype": "elk"}) is True
    assert host.loses_all_abilities is True


# ---------------------------------------------------------------------------
# Conqueror's Flail / Faeburrow Elder — colors_among_permanents_you_control
# ---------------------------------------------------------------------------


def test_conquerors_flail_scales_with_colors_and_locks_out_your_turn_only():
    engine, state, p1, p2 = _engine()
    host = _bf(state, _bear("Host Bear"), controller="p1", bind=True)
    flail = _catalogue_obj(state, "Conqueror's Flail", controller="p1")
    flail.attached_to = host.instance_id
    # p1 controls a red host and a white/blue extra permanent → 3 colors.
    host.card.color_identity = {"R"}
    extra = _bf(state, _card("Extra", "Artifact", color_identity={"W", "U"}), controller="p1")
    engine.recompute_continuous_effects()

    assert host.power == 5 and host.toughness == 5  # base 2/2 + 3/3

    state.active_player_index = 0  # p1's own turn
    assert continuous.cast_prohibited(state, p1, _bear("Own spell")) is False
    assert continuous.cast_prohibited(state, p2, _bear("Opp spell")) is True

    state.active_player_index = 1  # p2's own turn — the lockdown only applies on p1's
    assert continuous.cast_prohibited(state, p2, _bear("Opp spell")) is False


def test_faeburrow_elder_gets_pt_for_each_color_you_control():
    engine, state, p1, p2 = _engine()
    elder = _catalogue_obj(state, "Faeburrow Elder", controller="p1")
    base_power, base_toughness = elder.card.power or 0, elder.card.toughness or 0
    engine.recompute_continuous_effects()

    # Faeburrow Elder is itself GW → 2 colors among p1's permanents, so the
    # anthem should add exactly +2/+2 on top of whatever the card's own
    # printed base is (the local cache's cached row for this card carries
    # 0/0 rather than the real printed 1/1 — a pre-existing data-quality
    # quirk unrelated to this batch, so the assertion reads the base back
    # off the card itself rather than hardcoding the real printed value).
    assert elder.power == base_power + 2
    assert elder.toughness == base_toughness + 2


# ---------------------------------------------------------------------------
# Delney, Streetwise Lookout — qualified combat_restriction + trigger_doubler
# ---------------------------------------------------------------------------


def test_delney_protects_only_its_own_weak_creatures_from_strong_blockers():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Delney, Streetwise Lookout", controller="p1")
    weak_attacker = _bf(state, _bear("Weak", power=2, toughness=2), controller="p1", bind=True)
    strong_attacker = _bf(state, _bear("Strong", power=5, toughness=5), controller="p1", bind=True)
    strong_blocker = _bf(state, _bear("Blocker", power=4, toughness=4), controller="p2", bind=True)
    engine.recompute_continuous_effects()

    weak_attacker.attacking = True
    weak_attacker.combat_defender = {"kind": "player", "id": "p2", "label": "p2"}
    strong_attacker.attacking = True
    strong_attacker.combat_defender = {"kind": "player", "id": "p2", "label": "p2"}

    assert engine.can_block(p2, strong_blocker, weak_attacker) is False
    assert engine.can_block(p2, strong_blocker, strong_attacker) is True


def test_delney_doubles_triggers_of_its_own_weak_creatures():
    engine, state, p1, p2 = _engine()
    delney = _catalogue_obj(state, "Delney, Streetwise Lookout", controller="p1")
    weak = _bf(state, _bear("Weak", power=2, toughness=2), controller="p1", bind=True)
    strong = _bf(state, _bear("Strong", power=3, toughness=3), controller="p1", bind=True)
    engine.recompute_continuous_effects()

    assert continuous.trigger_doubler_bonus(state, weak) == 1
    assert continuous.trigger_doubler_bonus(state, strong) == 0


# ---------------------------------------------------------------------------
# Runic Armasaur — ACTIVATED_ABILITY group trigger with a two-type OR filter
# ---------------------------------------------------------------------------


def test_runic_armasaur_draws_off_an_opponents_land_ability_not_a_mana_one():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Runic Armasaur", controller="p1")
    engine.recompute_continuous_effects()
    before_hand = len(p1.hand)
    for _ in range(3):
        p1.library.append(GameObject(_bear(f"Filler {_}"), owner_id="p1", zone=Zone.LIBRARY))

    land = GameObject(_card("Ancient Tomb", "Land", is_land=True), owner_id="p2", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(land)
    state.fire_event(GameEvent(
        EventType.ACTIVATED_ABILITY, player_id="p2", controller_id="p2",
        instance_id=land.instance_id, object_types=sorted(land.type_words),
    ))
    engine.resolve_until_stable()

    assert len(p1.hand) == before_hand + 1


def test_runic_armasaur_does_not_trigger_off_its_own_controllers_activation():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Runic Armasaur", controller="p1")
    engine.recompute_continuous_effects()
    before_hand = len(p1.hand)

    own_land = GameObject(_card("Ancient Tomb", "Land", is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(own_land)
    state.fire_event(GameEvent(
        EventType.ACTIVATED_ABILITY, player_id="p1", controller_id="p1",
        instance_id=own_land.instance_id, object_types=sorted(own_land.type_words),
    ))
    engine.resolve_until_stable()

    assert len(p1.hand) == before_hand


# ---------------------------------------------------------------------------
# Peer into the Abyss — half-target-library draw + half-target-life loss
# ---------------------------------------------------------------------------


def test_peer_into_the_abyss_draws_and_drains_the_targeted_players_own_stats():
    from mtg_analyzer.game.ability_catalogue import specs_for
    from mtg_analyzer.game.effects.core import EffectRegistry, GameContext, _apply_effects_partitioned

    engine, state, p1, p2 = _engine()
    spell_card = _named("Peer into the Abyss")
    source = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)
    p2.life = 11
    for _ in range(9):
        p2.library.append(GameObject(_bear("Filler"), owner_id="p2", zone=Zone.LIBRARY))

    spec = specs_for(spell_card)[0]
    context = GameContext(state, engine.rules)
    context.source = source
    effects = []
    for effect_spec in spec.effects:
        effect = EffectRegistry.create(effect_spec.type, effect_spec.params)
        effect.source = source
        effects.append(effect)
    # `LoseLifeEffect.previous_subject` reads `GameContext.previous_targets`,
    # populated between effects only by the real per-ability dispatch.
    _apply_effects_partitioned(effects, context, [p2], None, source=source)

    assert len(p2.hand) == 5  # ceil(9/2)
    assert p2.life == 5  # 11 - ceil(11/2) = 11 - 6


# ---------------------------------------------------------------------------
# Soul Conduit — the new ExchangeLifeTotalsEffect
# ---------------------------------------------------------------------------


def test_soul_conduit_exchanges_life_totals():
    engine, state, p1, p2 = _engine()
    conduit = _catalogue_obj(state, "Soul Conduit", controller="p1")
    p1.life = 30
    p2.life = 5
    p1.mana_pool.add_many({"C": 6})
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, conduit, ability_index=0, targets=[p1, p2])
    engine.resolve_until_stable()

    assert p1.life == 5
    assert p2.life == 30
