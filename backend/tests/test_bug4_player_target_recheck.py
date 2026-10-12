"""BUG-4 — RULE 608.2b: a targeted *player* is rechecked as the spell/ability resolves.

Hexproof (RULE 702.11b, 702.11c: stops only the player's opponents' spells/abilities) and protection from
everything (RULE 702.16b, 702.16e) gained in response make the player an illegal target. The recheck reuses the
announce-time predicate (`targeting.legal_targets`) through `target_meets_restrictions`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.library import PlayerShieldEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.game import make_engine


def _creature(name, text="", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Test", oracle_text=text, is_creature=True,
                power=power, toughness=toughness)


def _engine():
    eng = make_engine([_creature(f"Filler {i}") for i in range(5)],
                      [_creature(f"Other {i}") for i in range(5)], hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _fire(eng, text, *targets, groups=None):
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, _creature("Source", f"{{R}}: {text}", 1, 1))
    p1.mana_pool.add_many({"R": 1})
    kwargs = {"target_groups": groups} if groups else {}
    eng.activate_ability(p1, src, targets=list(targets), **kwargs)
    return src


def _grant_hexproof(eng, controller):
    # Shalai, Voice of Plenty: "You, planeswalkers you control, and other creatures you control have hexproof."
    card = Card(id="Shalai", name="Shalai, Voice of Plenty", type_line="Legendary Creature — Angel",
                oracle_text="Flying\nYou, planeswalkers you control, and other creatures you control have hexproof.",
                is_creature=True, power=3, toughness=4)
    _put(eng, card, controller=controller)
    eng.recompute_continuous_effects()


def _protect_from_everything(eng, player_id):
    eng.state.player_by_id(player_id).player_effects.append(PlayerShieldEffect(life_locked=False))


def test_player_who_gains_hexproof_in_response_loses_no_life():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    _fire(eng, "Target player loses 3 life.", p2)
    _grant_hexproof(eng, "p2")
    eng.resolve_until_stable()
    assert p2.life == 20


def test_player_without_hexproof_loses_life():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    _fire(eng, "Target player loses 3 life.", p2)
    eng.resolve_until_stable()
    assert p2.life == 17


def test_player_who_gains_hexproof_does_not_draw():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    _fire(eng, "Target player draws a card.", p2)
    hand = len(p2.hand)
    _grant_hexproof(eng, "p2")
    eng.resolve_until_stable()
    assert len(p2.hand) == hand


def test_player_who_gains_hexproof_does_not_discard():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    eng.rules.draw(p2, 2)
    hand = len(p2.hand)
    _fire(eng, "Target player discards a card.", p2)
    _grant_hexproof(eng, "p2")
    eng.resolve_until_stable()
    assert len(p2.hand) == hand


def test_protection_from_everything_gained_in_response_is_illegal():
    # Teferi's Protection: RULE 702.16b -- protection includes "can't be the target of ... spells".
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    _fire(eng, "Target player loses 3 life.", p2)
    _protect_from_everything(eng, "p2")
    eng.resolve_until_stable()
    assert p2.life == 20


def test_own_ability_still_hits_self_after_gaining_hexproof():
    # RULE 702.11c: hexproof stops only opponents' spells and abilities.
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _fire(eng, "Target player loses 3 life.", p1)
    _grant_hexproof(eng, "p1")
    eng.resolve_until_stable()
    assert p1.life == 17


def test_own_ability_does_not_hit_self_after_gaining_protection():
    # RULE 702.16b: protection stops the player's own sources too (unlike hexproof).
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _fire(eng, "Target player loses 3 life.", p1)
    _protect_from_everything(eng, "p1")
    eng.resolve_until_stable()
    assert p1.life == 20


def test_spell_with_only_an_illegal_player_target_is_countered():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    card = Card(id="T", name="Test Instant", type_line="Instant", oracle_text="Target player loses 3 life.",
                is_instant=True, converted_mana_cost=0, color_identity=["B"])
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=[p2])
    _grant_hexproof(eng, "p2")
    eng.resolve_until_stable()
    assert p2.life == 20
    assert spell.zone == Zone.GRAVEYARD


def test_only_the_illegal_player_is_skipped_in_a_multi_target_ability():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    victim = _put(eng, _creature("Victim"), controller="p2")
    _fire(eng, "Target player loses 3 life and tap target creature.", p2, victim, groups=[[p2], [victim]])
    _protect_from_everything(eng, "p2")  # the creature stays targetable; only the player turns illegal
    eng.resolve_until_stable()
    assert p2.life == 20
    assert victim.tapped
