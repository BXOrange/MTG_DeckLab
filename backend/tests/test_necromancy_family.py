"""MEC-44 — Necromancy, RULE 303.4f's *non-Aura* reanimator template
(Animate Dead's own sibling ticket, MEC-34 — that card is a real Aura from
load time; Necromancy prints as a plain Enchantment and only becomes one
once its own "when this enters" ability resolves). Covers the three real
gaps closed: the unconditional flash grant (`conditional_flash=
{"unconditional": True}`), the "cast at a time a sorcery couldn't have been
cast → sacrifice at next cleanup" downside (`GameObject.
cast_outside_sorcery_speed`, a new `EffectSpec.condition` key gating a
`create_delayed_trigger`), and the "becomes an Aura" transformation itself
(`BecomeAuraEffect` writing `GameObject.parametric_keywords["enchant"]`
directly onto the live object).

Reference: docs/implementation-state/Done_Backend.md "MEC-44" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _graveyard_creature(state, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    state.player_by_id(controller).graveyard.append(obj)
    return obj


def _cast_necromancy_at_sorcery_speed(hand=1):
    eng = make_engine([_named("Necromancy")], [_named("Necromancy")], hand=hand)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})  # {2}{B}
    return eng, p1


def _cast_necromancy_at_instant_speed(hand=1):
    # p1's own upkeep step — never sorcery-speed-legal (RULE 601.3a), so
    # this exercises the flash grant for real. Genuinely advanced there
    # (not just poking `current_step`) so the turn loop's own cursor stays
    # in sync for a later `advance_step()` in the same test.
    eng = make_engine([_named("Necromancy")], [_named("Necromancy")], hand=hand)
    eng.start()
    while eng.state.current_step != "upkeep":
        eng.advance_step()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    return eng, p1


def _cast_and_reanimate(eng, p1, bear):
    necromancy = p1.hand[0]
    bind_from_catalogue(necromancy)
    eng.cast_spell(p1, necromancy)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    pick = next(o for o in choice["options"] if o["instance_id"] == bear.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()
    return necromancy


def test_necromancy_can_be_cast_at_instant_speed():
    eng, p1 = _cast_necromancy_at_instant_speed()
    necromancy = p1.hand[0]
    bind_from_catalogue(necromancy)
    assert eng.can_cast(p1, necromancy)


def test_necromancy_reanimates_under_the_casters_control_and_becomes_an_aura():
    eng, p1 = _cast_necromancy_at_sorcery_speed()
    bear = _graveyard_creature(eng.state, creature("Bear", power=2, toughness=2), controller="p2")
    necromancy = _cast_and_reanimate(eng, p1, bear)

    reanimated = next(o for o in eng.state.battlefield if o.card.name == "Bear")
    assert reanimated.controller_id == "p1"  # under YOUR control, not the owner's
    assert reanimated.owner_id == "p2"
    assert necromancy.attached_to == reanimated.instance_id
    assert necromancy.parametric_keywords.get("enchant") is not None


def test_necromancy_leaving_sacrifices_the_reanimated_creature():
    eng, p1 = _cast_necromancy_at_sorcery_speed()
    bear = _graveyard_creature(eng.state, creature("Bear", power=2, toughness=2), controller="p1")
    necromancy = _cast_and_reanimate(eng, p1, bear)
    reanimated = next(o for o in eng.state.battlefield if o.card.name == "Bear")

    eng.rules.put_into_graveyard(necromancy)
    eng.resolve_until_stable()

    assert necromancy not in eng.state.battlefield
    assert reanimated not in eng.state.battlefield
    assert reanimated in p1.graveyard


def test_sorcery_speed_cast_arms_no_delayed_sacrifice():
    eng, p1 = _cast_necromancy_at_sorcery_speed()
    bear = _graveyard_creature(eng.state, creature("Bear"), controller="p1")
    necromancy = _cast_and_reanimate(eng, p1, bear)
    assert necromancy.cast_outside_sorcery_speed is False
    assert eng.state.delayed_triggers == []


def test_instant_speed_cast_arms_a_delayed_sacrifice_at_next_cleanup():
    eng, p1 = _cast_necromancy_at_instant_speed()
    bear = _graveyard_creature(eng.state, creature("Bear"), controller="p1")
    necromancy = _cast_and_reanimate(eng, p1, bear)
    assert necromancy.cast_outside_sorcery_speed is True
    assert len(eng.state.delayed_triggers) == 1
    assert eng.state.delayed_triggers[0].step == "cleanup"


def test_instant_speed_cast_actually_sacrifices_necromancy_at_cleanup():
    eng, p1 = _cast_necromancy_at_instant_speed()
    bear = _graveyard_creature(eng.state, creature("Bear"), controller="p1")
    necromancy = _cast_and_reanimate(eng, p1, bear)

    while eng.state.current_step != "cleanup":
        eng.advance_step()
    eng.resolve_until_stable()

    assert necromancy not in eng.state.battlefield
    assert necromancy in p1.graveyard
