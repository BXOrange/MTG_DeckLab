"""BUG-24 — "damage can't be prevented" (RULE 615.12) lets damage through protection's
prevention part (RULE 702.16e); its targeting restriction (RULE 702.16b) is untouched."""

from __future__ import annotations

from mtg_analyzer.game.combat import is_protected_from
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    filler = Card(id="F", name="F", type_line="Instant")
    eng = GameEngine.new_game(
        [("p1", "p1", [filler] * 20), ("p2", "p2", [filler] * 20)], starting_hand=0,
    )
    return eng


def _creature(eng, name, owner, oracle="", colors=(), power=2, toughness=2):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness, oracle_text=oracle,
             color_identity=set(colors)),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _setup():
    eng = _engine()
    red = _creature(eng, "Red Bear", "p1", colors={"R"}, power=3)
    pro = _creature(eng, "Pro Bear", "p2", oracle="Protection from red")
    return eng, red, pro


def test_protection_prevents_noncombat_damage_by_default():
    eng, red, pro = _setup()
    eng.rules.deal_damage(pro, 3, source=red)
    assert pro.damage_marked == 0


def test_unpreventable_flag_lets_noncombat_damage_through_protection():
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    eng.rules.deal_damage(pro, 3, source=red)
    assert pro.damage_marked == 3


def test_unpreventable_flag_lets_combat_damage_through_protection():
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    eng._apply_combat_damage([(pro, 3, red)])
    assert pro.damage_marked == 3


def test_protection_still_prevents_combat_damage_by_default():
    eng, red, pro = _setup()
    eng._apply_combat_damage([(pro, 3, red)])
    assert pro.damage_marked == 0


def test_protected_blocker_deals_damage_back_when_unpreventable():
    # A pro-red creature may block a red attacker; the attacker's damage to it
    # goes through under RULE 615.12, the blocker's damage to the attacker always does.
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    eng._apply_combat_damage([(pro, 3, red), (red, 2, pro)])
    assert pro.damage_marked == 3
    assert red.damage_marked == 2


def test_unpreventable_damage_is_lethal_to_protected_creature():
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    eng.rules.deal_damage(pro, 3, source=red)
    eng.resolve_until_stable()
    assert pro.zone != Zone.BATTLEFIELD


def test_protection_still_prevents_after_flag_clears():
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    eng.state.damage_prevention_disabled = False
    eng.rules.deal_damage(pro, 3, source=red)
    assert pro.damage_marked == 0


def test_targeting_restriction_survives_unpreventable_damage():
    # RULE 702.16b: protection's targeting part is not damage prevention.
    eng, red, pro = _setup()
    eng.state.damage_prevention_disabled = True
    assert is_protected_from(pro, red)


# --- player protection (RULE 702.16e) --------------------------------------

from mtg_analyzer.game import continuous  # noqa: E402
from mtg_analyzer.game.binding.core import bind_from_catalogue  # noqa: E402
from mtg_analyzer.game.effects.library import PlayerShieldEffect  # noqa: E402


def test_player_protected_from_everything():
    eng, red, _ = _setup()
    p2 = eng.state.player_by_id("p2")
    START = p2.life
    p2.player_effects.append(PlayerShieldEffect(life_locked=False))
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START
    eng.state.damage_prevention_disabled = True
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START - 3


def test_player_protected_from_source_controller():
    eng, red, _ = _setup()
    p2 = eng.state.player_by_id("p2")
    START = p2.life
    p2.player_effects.append(PlayerShieldEffect(
        life_locked=False, protection_from_everything=False, protected_from_player_id="p1"))
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START
    eng.state.damage_prevention_disabled = True
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START - 3


def test_player_static_quality_protection(monkeypatch):
    eng, red, _ = _setup()
    p2 = eng.state.player_by_id("p2")
    START = p2.life
    monkeypatch.setattr(continuous, "player_static_protections", lambda s, p: {"creatures"})
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START
    eng.state.damage_prevention_disabled = True
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START - 3


def test_standing_static_path_everlasting_torment():
    eng, red, _ = _setup()
    p2 = eng.state.player_by_id("p2")
    START = p2.life
    p2.player_effects.append(PlayerShieldEffect(life_locked=False))
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START
    torment = GameObject(
        Card(id="ET", name="Everlasting Torment", type_line="Enchantment"),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(torment)
    eng.state.add_to_battlefield(torment)
    eng.recompute_continuous_effects()
    assert continuous.damage_prevention_globally_disabled(eng.state)
    eng.rules.deal_damage(p2, 3, source=red)
    assert p2.life == START - 3
