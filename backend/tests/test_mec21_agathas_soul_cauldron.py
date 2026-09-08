"""Tests for MEC-21 — Agatha's Soul Cauldron's two previously-unmodeled
clauses, and the "cards exiled with ~" generalization they needed.

Two primitives, both real, both reusable beyond this one card:

  * `effects.grant_any_color_for_activation` — a standing RULE 605.1a
    wildcard *permission* over activation-cost mana ("you may spend mana as
    though it were mana of any color to activate abilities of creatures you
    control"), consulted by `continuous.any_color_for_activation` from every
    activation-cost payment site in `game/engine/activation_mixin.py`.
    Distinct from the shipped RULE 605.3a `restriction_predicate_for_cast`/
    `_for_activation` machinery, which restricts *what* a lot of mana can
    pay for, never *what color* it counts as.
  * `GameObject.exiled_with_ids` (`ExileEffect`'s new ``track_exiled_with``
    param) — the generalized, *accumulating* sibling of the O-Ring-shaped
    `linked_exile_id`, reusable by any future "exile with ~" card (~185
    cached cards print that shape per this ticket's own sizing). Consumed
    here by `effects.grant_borrowed_activated_ability`/`continuous.
    _apply_borrowed_activated_abilities`, which builds one fresh
    `ActivatedAbility` per (grantee, exiled creature, ability index) — the
    exiled card's own cost/effects, bound once at bind-on-load like any
    other permanent's, with each nested effect's `.source` redirected to
    the grantee (RULE 113.7c).

Reference: mtg_analyzer/game/effects/core.py (`ExileEffect.track_exiled_with`,
`grant_any_color_for_activation`, `grant_borrowed_activated_ability`),
mtg_analyzer/game/continuous.py (`any_color_for_activation`,
`_apply_borrowed_activated_abilities`), mtg_analyzer/game/ability_catalogue.py
(Agatha's Soul Cauldron), RULE 113.7c/605.1a/605.3a/613.7f.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def cauldron():
    return Card(id="Agatha's Soul Cauldron", name="Agatha's Soul Cauldron",
                type_line="Legendary Artifact", is_creature=False)


def bear():
    return Card(id="Bear", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def pinger():
    return Card(id="Prodigal Pyromancer", name="Prodigal Pyromancer",
                type_line="Creature — Human Wizard", is_creature=True, power=1, toughness=1,
                oracle_text="{T}: This creature deals 1 damage to any target.")


def blue_pinger():
    return Card(id="Blue Guy", name="Blue Guy", type_line="Creature — Human Wizard",
                is_creature=True, power=1, toughness=1,
                oracle_text="{U}, {T}: This creature deals 1 damage to any target.")


def exile_with(eng, cauldron_obj, target_obj):
    """Mimic Agatha's Soul Cauldron's own activated ability's exile half —
    ``ExileEffect(track_exiled_with=True)`` — without needing a full target
    round-trip through `activate_ability`."""
    eng.rules.exile(target_obj)
    cauldron_obj.exiled_with_ids.append(target_obj.instance_id)


# ---------------------------------------------------------------------------
# Clause 1 — any-color mana permission for activating creature abilities
# ---------------------------------------------------------------------------


def test_can_activate_a_creature_ability_with_the_wrong_color_mana():
    eng = make_engine()
    put(eng.state, cauldron())
    creature = put(eng.state, blue_pinger())
    eng.recompute_continuous_effects()

    player = eng.state.player_by_id("p1")
    player.mana_pool.add("G", 1)  # not blue — only legal via the wildcard
    assert eng.can_activate(player, creature, creature.activated_abilities[0])


def test_without_the_cauldron_the_wrong_color_mana_is_illegal():
    eng = make_engine()
    creature = put(eng.state, blue_pinger())
    eng.recompute_continuous_effects()

    player = eng.state.player_by_id("p1")
    player.mana_pool.add("G", 1)
    assert not eng.can_activate(player, creature, creature.activated_abilities[0])


def test_the_wildcard_does_not_apply_to_a_noncreature_permanents_ability():
    eng = make_engine()
    put(eng.state, cauldron())
    rock = put(
        eng.state,
        Card(id="Mana Rock", name="Mana Rock", type_line="Artifact",
             oracle_text="{U}, {T}: Add {C}{C}."),
    )
    eng.recompute_continuous_effects()
    player = eng.state.player_by_id("p1")
    # A mana ability isn't reached through `can_activate`/`activate_ability`
    # at all (RULE 605), so this just confirms the wildcard is scoped by
    # `creature_abilities_only` rather than blanket-covering every artifact.
    from mtg_analyzer.game import continuous
    assert not continuous.any_color_for_activation(eng.state, player, rock)


# ---------------------------------------------------------------------------
# Clause 2 — borrowed activated abilities from creatures exiled with it
# ---------------------------------------------------------------------------


def test_a_counter_bearing_creature_gains_the_exiled_creatures_ability():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    grantee = put(eng.state, bear())
    grantee.add_counters("+1/+1", 1)

    p1 = eng.state.player_by_id("p1")
    gy_pinger = GameObject(pinger(), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(gy_pinger)
    p1.add_to_zone(gy_pinger, Zone.GRAVEYARD)

    exile_with(eng, the_cauldron, gy_pinger)
    eng.recompute_continuous_effects()

    assert len(grantee.granted_activated_abilities) == 1
    granted = grantee.granted_activated_abilities[0]
    assert granted.source is grantee  # RULE 113.7c — applies as the grantee's own


def test_a_creature_without_a_plus_one_counter_gains_nothing():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    grantee = put(eng.state, bear())  # no counters

    p1 = eng.state.player_by_id("p1")
    gy_pinger = GameObject(pinger(), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(gy_pinger)
    p1.add_to_zone(gy_pinger, Zone.GRAVEYARD)
    exile_with(eng, the_cauldron, gy_pinger)
    eng.recompute_continuous_effects()

    assert grantee.granted_activated_abilities == []


def test_activating_the_borrowed_ability_costs_and_taps_the_grantee_not_the_exiled_card():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    grantee = put(eng.state, bear())
    grantee.add_counters("+1/+1", 1)

    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    gy_pinger = GameObject(pinger(), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(gy_pinger)
    p1.add_to_zone(gy_pinger, Zone.GRAVEYARD)
    exile_with(eng, the_cauldron, gy_pinger)
    eng.recompute_continuous_effects()

    life_before = p2.life
    ability_index = len(grantee.activated_abilities)  # the borrowed one is appended after any printed ones
    eng.activate_ability(p1, grantee, ability_index=ability_index, targets=[p2])
    eng.resolve_until_stable()

    assert p2.life == life_before - 1
    assert grantee.tapped
    assert not gy_pinger.tapped  # the original, still sitting in exile, is untouched


def test_the_grant_disappears_once_the_exiled_card_leaves_exile():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    grantee = put(eng.state, bear())
    grantee.add_counters("+1/+1", 1)

    p1 = eng.state.player_by_id("p1")
    gy_pinger = GameObject(pinger(), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(gy_pinger)
    p1.add_to_zone(gy_pinger, Zone.GRAVEYARD)
    exile_with(eng, the_cauldron, gy_pinger)
    eng.recompute_continuous_effects()
    assert len(grantee.granted_activated_abilities) == 1

    eng.rules.return_to_hand(gy_pinger)  # leaves exile — no longer "exiled with" it
    eng.recompute_continuous_effects()

    assert grantee.granted_activated_abilities == []


def test_a_noncreature_card_exiled_this_way_grants_nothing():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    grantee = put(eng.state, bear())
    grantee.add_counters("+1/+1", 1)

    p1 = eng.state.player_by_id("p1")
    sorcery = Card(id="Some Sorcery", name="Some Sorcery", type_line="Sorcery", is_sorcery=True,
                    oracle_text="{T}: Draw a card.")
    gy_sorcery = GameObject(sorcery, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(gy_sorcery)
    p1.add_to_zone(gy_sorcery, Zone.GRAVEYARD)
    exile_with(eng, the_cauldron, gy_sorcery)
    eng.recompute_continuous_effects()

    assert grantee.granted_activated_abilities == []


# ---------------------------------------------------------------------------
# `GameObject.exiled_with_ids` itself — the generalized tracker
# ---------------------------------------------------------------------------


def test_exiled_with_ids_accumulates_across_multiple_exiles():
    eng = make_engine()
    the_cauldron = put(eng.state, cauldron())
    p1 = eng.state.player_by_id("p1")
    first = GameObject(bear(), owner_id="p1", zone=Zone.GRAVEYARD)
    second = GameObject(pinger(), owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(first)
    bind_from_catalogue(second)
    p1.add_to_zone(first, Zone.GRAVEYARD)
    p1.add_to_zone(second, Zone.GRAVEYARD)

    exile_with(eng, the_cauldron, first)
    exile_with(eng, the_cauldron, second)

    assert the_cauldron.exiled_with_ids == [first.instance_id, second.instance_id]


def test_exiled_with_ids_resets_on_reset_as_new_object():
    the_cauldron = cauldron()
    obj = GameObject(the_cauldron, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.exiled_with_ids = [1, 2, 3]
    obj.reset_as_new_object()
    assert obj.exiled_with_ids == []


# ---------------------------------------------------------------------------
# Real card end-to-end
# ---------------------------------------------------------------------------


def test_agathas_soul_cauldron_is_registered_with_all_three_pieces():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(cauldron())
    kinds = [(s.ability_kind, s.effects[0].type) for s in specs]
    assert ("activated", "exile") in kinds
    assert ("static", "grant_any_color_for_activation") in kinds
    assert ("static", "grant_borrowed_activated_ability") in kinds
    activated = next(s for s in specs if s.ability_kind == "activated")
    assert activated.effects[0].params.get("track_exiled_with") is True
