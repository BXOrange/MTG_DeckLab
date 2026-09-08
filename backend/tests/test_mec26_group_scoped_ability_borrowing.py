"""Tests for MEC-26 — Drana and Linvala / Scheming Fence, the two cards a
second MEC-23 deferral had left open (found while sizing MEC-21, 2026-07-22;
deferred again by MEC-23, 2026-08-11; this batch is the mandatory
hand-author-or-promote close per the project's no-half-implementations
rule — see CLAUDE.md).

Both print a **standing, group-scoped** ability-borrowing static, distinct
from MEC-23's own resolve-time, single-target snapshot
(`GainActivatedAbilitiesOfTargetEffect`) and closer in shape to MEC-21's
standing `grant_borrowed_activated_ability` (Agatha's Soul Cauldron) — just
reading its donor set off something other than `GameObject.exiled_with_ids`:

  * Drana and Linvala: ``source_mode="group"`` — the donor set is "all
    creatures your opponents control", a live `affects` selector
    (``"creatures_opponents_control"``) read straight off the battlefield
    every `continuous.recompute` pass, not a fixed list.
  * Scheming Fence: ``source_mode="chosen_permanent"`` — a single donor
    named once by a new interactive ETB pick (`ChoosePermanentEffect`/
    ``"choose_permanent"``, `GameObject.chosen_permanent_id`, a new
    `continuous.group_selector_objects` selector of the same name), plus a
    new ``exclude_loyalty`` param since the chosen permanent need not be a
    creature.

Both also print "Activated abilities of <the same donor scope> can't be
activated." — the existing `activation_prohibition` static needed no new
code at all, just scoping its already-general ``affects`` selector to
these new selector values — and "you may spend mana as though it were mana
of any color to activate those abilities", which turned out to need no
third param either: MEC-23's `self_only` already covers it, since neither
card prints any *other* activated ability of its own.

Reference: mtg_analyzer/game/effects/core.py (`ChoosePermanentEffect`,
`grant_borrowed_activated_ability`'s ``source_mode``/``exclude_loyalty``),
mtg_analyzer/game/continuous.py (`_apply_borrowed_activated_abilities`,
`group_selector_objects`'s ``"chosen_permanent"``),
mtg_analyzer/game/rules/misc_mixin.py (`request_choose_objects`'s
``"choose_permanent"`` action), mtg_analyzer/models/game_object.py
(`chosen_permanent_id`), mtg_analyzer/game/ability_catalogue.py (Drana and
Linvala, Scheming Fence), RULE 113.7c/605.1a/606.5c/613.7f.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.events import EventType, GameEvent


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


def drana_and_linvala():
    return Card(
        id="Drana and Linvala", name="Drana and Linvala",
        type_line="Legendary Creature — Vampire Angel", is_creature=True,
        power=3, toughness=4, mana_cost_string="{1}{W}{W}{B}",
        oracle_text=(
            "Flying, vigilance\n"
            "Activated abilities of creatures your opponents control can't be "
            "activated.\n"
            "Drana and Linvala has all activated abilities of all creatures "
            "your opponents control. You may spend mana as though it were "
            "mana of any color to activate those abilities."
        ),
    )


def scheming_fence():
    return Card(
        id="Scheming Fence", name="Scheming Fence",
        type_line="Creature — Human Citizen", is_creature=True,
        power=2, toughness=3, mana_cost_string="{W}{U}",
        oracle_text=(
            "As this creature enters, you may choose a nonland permanent.\n"
            "Activated abilities of the chosen permanent can't be activated.\n"
            "This creature has all activated abilities of the chosen "
            "permanent except for loyalty abilities. You may spend mana as "
            "though it were mana of any color to activate those abilities."
        ),
    )


def red_pinger(name="Red Guy"):
    return Card(
        id=name, name=name, type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        oracle_text="{R}: This creature deals 1 damage to any target.",
    )


def bear():
    return Card(id="Bear", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def planeswalker_with_loyalty():
    return Card(
        id="Test Walker", name="Test Walker",
        type_line="Legendary Planeswalker — Test", loyalty=3,
        mana_cost_string="{2}{R}",
        oracle_text="[+1]: Test Walker deals 1 damage to any target.",
    )


def fire_etb(state, obj):
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, object=obj.name,
            controller_id=obj.controller_id, instance_id=obj.instance_id,
            object_types=sorted(obj.type_words),
        )
    )


# ---------------------------------------------------------------------------
# Drana and Linvala — group-scoped ("all creatures your opponents control")
# ---------------------------------------------------------------------------


def test_drana_borrows_abilities_from_every_opponent_creature():
    eng = make_engine()
    drana = put(eng.state, drana_and_linvala())
    foe1 = put(eng.state, red_pinger("Foe One"), controller="p2")
    foe2 = put(eng.state, red_pinger("Foe Two"), controller="p2")
    eng.recompute_continuous_effects()

    assert len(drana.granted_activated_abilities) == 2
    assert all(a.source is drana for a in drana.granted_activated_abilities)


def test_drana_does_not_borrow_from_her_own_controllers_creatures():
    eng = make_engine()
    drana = put(eng.state, drana_and_linvala())
    put(eng.state, red_pinger(), controller="p1")
    eng.recompute_continuous_effects()

    assert drana.granted_activated_abilities == []


def test_the_borrow_set_is_live_not_a_snapshot():
    eng = make_engine()
    drana = put(eng.state, drana_and_linvala())
    foe = put(eng.state, red_pinger(), controller="p2")
    eng.recompute_continuous_effects()
    assert len(drana.granted_activated_abilities) == 1

    eng.state.battlefield.remove(foe)
    eng.recompute_continuous_effects()
    assert drana.granted_activated_abilities == []


def test_opponent_creatures_own_activation_is_prohibited():
    eng = make_engine()
    put(eng.state, drana_and_linvala())
    foe = put(eng.state, red_pinger(), controller="p2")
    eng.recompute_continuous_effects()

    p2 = eng.state.player_by_id("p2")
    p2.mana_pool.add("R", 1)
    assert eng.can_activate(p2, foe, foe.activated_abilities[0], tap_choices=[]) is False


def test_wildcard_mana_pays_a_borrowed_red_cost_off_drana():
    eng = make_engine()
    drana = put(eng.state, drana_and_linvala())
    put(eng.state, red_pinger(), controller="p2")
    eng.recompute_continuous_effects()

    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("U", 1)
    borrowed = drana.granted_activated_abilities[0]
    assert eng.can_activate(p1, drana, borrowed, tap_choices=[])


def test_drana_and_linvala_is_registered_with_all_three_statics():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(drana_and_linvala())
    kinds = [(s.ability_kind, s.effects[0].type) for s in specs]
    assert ("static", "activation_prohibition") in kinds
    assert ("static", "grant_borrowed_activated_ability") in kinds
    assert ("static", "grant_any_color_for_activation") in kinds
    borrow = next(s for s in specs if s.effects[0].type == "grant_borrowed_activated_ability")
    assert borrow.effects[0].params.get("source_mode") == "group"
    assert borrow.effects[0].params.get("source_affects") == "creatures_opponents_control"


# ---------------------------------------------------------------------------
# Scheming Fence — a single chosen donor
# ---------------------------------------------------------------------------


def test_etb_offers_an_optional_choose_permanent_pick():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    put(eng.state, bear(), controller="p2")
    fire_etb(eng.state, fence)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    assert choice["action"] == "choose_permanent"
    assert choice["optional"] is True
    assert any(o.get("id") == "decline" for o in choice["options"])


def test_declining_the_choice_leaves_nothing_borrowed_or_prohibited():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    target = put(eng.state, red_pinger(), controller="p2")
    fire_etb(eng.state, fence)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    eng.rules.resolve_choose_objects_choice(None)  # decline
    eng.recompute_continuous_effects()

    assert fence.chosen_permanent_id is None
    assert fence.granted_activated_abilities == []
    p2 = eng.state.player_by_id("p2")
    p2.mana_pool.add("R", 1)
    assert eng.can_activate(p2, target, target.activated_abilities[0], tap_choices=[])


def test_choosing_a_permanent_grants_its_abilities_and_prohibits_the_original():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    target = put(eng.state, red_pinger(), controller="p2")
    fire_etb(eng.state, fence)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    eng.rules.resolve_choose_objects_choice(target.instance_id)
    eng.recompute_continuous_effects()

    assert fence.chosen_permanent_id == target.instance_id
    assert len(fence.granted_activated_abilities) == 1
    assert fence.granted_activated_abilities[0].source is fence

    p2 = eng.state.player_by_id("p2")
    p2.mana_pool.add("R", 1)
    assert eng.can_activate(p2, target, target.activated_abilities[0], tap_choices=[]) is False


def test_loyalty_abilities_are_excluded_from_the_borrowed_set():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    walker = put(eng.state, planeswalker_with_loyalty(), controller="p2")
    fire_etb(eng.state, fence)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    eng.rules.resolve_choose_objects_choice(walker.instance_id)
    eng.recompute_continuous_effects()

    assert fence.chosen_permanent_id == walker.instance_id
    assert fence.granted_activated_abilities == []
    # the planeswalker's own loyalty ability is untouched
    assert walker.activated_abilities[0].cost.is_loyalty


def test_wildcard_mana_pays_a_borrowed_red_cost_off_fence():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    target = put(eng.state, red_pinger(), controller="p2")
    fire_etb(eng.state, fence)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.rules.resolve_choose_objects_choice(target.instance_id)
    eng.recompute_continuous_effects()

    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("U", 1)
    borrowed = fence.granted_activated_abilities[0]
    assert eng.can_activate(p1, fence, borrowed, tap_choices=[])


def test_choosing_itself_is_a_harmless_no_op():
    eng = make_engine()
    fence = put(eng.state, scheming_fence())
    fire_etb(eng.state, fence)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    eng.rules.resolve_choose_objects_choice(fence.instance_id)
    eng.recompute_continuous_effects()

    assert fence.chosen_permanent_id == fence.instance_id
    assert fence.granted_activated_abilities == []


def test_scheming_fence_is_registered_with_all_four_pieces():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(scheming_fence())
    kinds = [(s.ability_kind, s.effects[0].type) for s in specs]
    assert ("triggered", "choose_permanent") in kinds
    assert ("static", "activation_prohibition") in kinds
    assert ("static", "grant_borrowed_activated_ability") in kinds
    assert ("static", "grant_any_color_for_activation") in kinds
    borrow = next(s for s in specs if s.effects[0].type == "grant_borrowed_activated_ability")
    assert borrow.effects[0].params.get("source_mode") == "chosen_permanent"
    assert borrow.effects[0].params.get("exclude_loyalty") is True
    assert borrow.effects[0].params.get("creature_only") is False
