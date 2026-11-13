"""Hand-authored PAR-252 residue: complete abilities through the real engine."""
from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous, mana_abilities
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_registered, specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.game import creature, land
from tests.test_par252_prepared_state import CODIE, COURSEWORK

HIVE = (
    "If you control two or more other lands, this land enters tapped.\n"
    "{T}: Add {B}.\n"
    '{3}{B}: Until end of turn, this land becomes a 3/3 black Beholder creature with menace and '
    '"Whenever this creature attacks, exile target card from defending player\'s graveyard." It\'s still a land.'
)


def _card(name):
    if name == "Codie, Ravenous Codex":
        return creature(name, cost="{3}", power=1, toughness=4,
                        type_line="Legendary Artifact Creature — Book Construct", oracle_text=CODIE)
    if name == "Hive of the Eye Tyrant":
        return Card(id=name, name=name, type_line="Land", is_land=True, oracle_text=HIVE)
    return Card(id=name, name=name, type_line="Enchantment — Aura",
                mana_cost_string="{2}{U}", oracle_text=COURSEWORK)


def _engine():
    e = GameEngine.new_game([(p, p, []) for p in ("p1", "p2", "p3")],
                           starting_life=20, starting_hand=0)
    e.state.current_phase, e.state.current_step = "precombat_main", "main1"
    for p in e.state.players:
        p.mana_pool.add_many({c: 20 for c in "WUBRGC"})
    return e


def _object(e, card, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        e.state.add_to_battlefield(obj)
    else:
        getattr(e.state.player_by_id(player), zone.value).append(obj)
    return obj


def _prepare(e, player="p1", targeted=False, prepared=True):
    obj = _object(e, creature("Preparation Student", layout="prepare", back_name="Practice Spell",
        oracle_text="Flying\n{1}: You gain 1 life.",
        back_type_line="Instant", back_mana_cost_string="{1}",
        back_oracle_text=("Practice Spell deals 2 damage to any target." if targeted else "You gain 1 life.")), player)
    if not prepared:
        return obj, None
    e.rules.make_prepared(obj)
    copy = next(c for c in e.state.player_by_id(player).exile if c.prepared_source_id == obj.instance_id)
    return obj, copy


@pytest.mark.parametrize("name", ["Codie, Ravenous Codex", "Hive of the Eye Tyrant", "Infinite Coursework"])
def test_registered_fresh_specs_validate_and_bind(name):
    card = _card(name)
    assert is_registered(name)
    first, second = specs_for(card), specs_for(card)
    assert first and len(first) == len(second)
    for a, b in zip(first, second):
        assert a is not b and a.effects is not b.effects
        a.validate()
    e = _engine()
    obj = _object(e, card)
    assert obj.activated_abilities if name != "Infinite Coursework" else obj.static_effects


def test_codie_copies_prepared_spell_without_casting_the_copy_again():
    e = _engine()
    _object(e, _card("Codie, Ravenous Codex"))
    source, spell = _prepare(e)
    player = e.state.player_by_id("p1")
    e.cast_spell(player, spell)
    assert not source.prepared
    e.resolve_until_stable()
    assert player.life == 22  # original and exactly one copy
    assert not e.state.pending_choice and not e.state.stack


@pytest.mark.parametrize("retarget", [False, True])
def test_codie_can_keep_or_change_the_copied_spells_targets(retarget):
    e = _engine()
    _object(e, _card("Codie, Ravenous Codex"))
    _, spell = _prepare(e, targeted=True)
    e.cast_spell(e.state.player_by_id("p1"), spell, targets=[e.state.player_by_id("p2")])
    e.resolve_until_stable()
    assert e.state.pending_choice["kind"] == "copy_targets"
    if retarget:
        option = next(o for o in e.state.pending_choice["options"] if o.get("player_id") == "p3")
        e.rules.resolve_choice(option["id"])
    else:
        e.rules.resolve_choice("decline")
    e.resolve_until_stable()
    assert e.state.player_by_id("p2").life == (18 if retarget else 16)
    assert e.state.player_by_id("p3").life == (18 if retarget else 20)


@pytest.mark.parametrize("player", ["p1", "p2"])
def test_codie_does_not_copy_normal_spells_or_an_opponents_prepared_spell(player):
    e = _engine()
    _object(e, _card("Codie, Ravenous Codex"))
    if player == "p2":
        _, spell = _prepare(e, player)
        e.state.active_player_index = 1
    else:
        spell = _object(e, Card(id="normal", name="Normal", type_line="Instant", is_instant=True,
                                oracle_text="You gain 1 life."), zone=Zone.HAND)
    caster = e.state.player_by_id(player)
    e.cast_spell(caster, spell)
    e.resolve_until_stable()
    assert caster.life == 21


def test_codie_does_not_copy_an_ordinary_spell_cast_from_exile():
    e = _engine()
    _object(e, _card("Codie, Ravenous Codex"))
    # Exercise the casting primitive from exile without a prepare-spell link.
    spell = _object(e, Card(id="rebound", name="Rebound", type_line="Instant", is_instant=True,
                            oracle_text="You gain 1 life."), zone=Zone.EXILE)
    e.rules.cast_spell(e.state.player_by_id("p1"), spell)
    e.resolve_until_stable()
    assert e.state.player_by_id("p1").life == 21


def test_codie_activation_prepares_only_eligible_creatures_you_control():
    e = _engine()
    codie = _object(e, _card("Codie, Ravenous Codex"))
    mine, _ = _prepare(e, prepared=False)
    theirs, _ = _prepare(e, "p2", prepared=False)
    e.activate_ability(e.state.player_by_id("p1"), codie, 0)
    e.resolve_until_stable()
    assert mine.prepared and not theirs.prepared and not codie.prepared and codie.tapped


def test_codie_can_copy_the_prepared_spell_after_the_original_is_countered():
    e = _engine()
    _object(e, _card("Codie, Ravenous Codex"))
    _, spell = _prepare(e)
    e.cast_spell(e.state.player_by_id("p1"), spell)
    e.rules.put_triggers_on_stack()
    e.rules.counter_spell(spell)
    e.resolve_until_stable()
    assert e.state.player_by_id("p1").life == 21


def _animate(e):
    hive = _object(e, _card("Hive of the Eye Tyrant"))
    e.activate_ability(e.state.player_by_id("p1"), hive, 0)
    e.resolve_until_stable()
    e.recompute_continuous_effects()
    return hive


def test_hive_animation_retains_land_and_mana_with_the_right_characteristics():
    e = _engine()
    hive = _animate(e)
    assert hive.is_creature and hive.is_land
    assert (hive.power, hive.toughness) == (3, 3)
    assert hive.has_subtype("Beholder") and combat.has(hive, "menace")
    assert hive.colors == {"B"}
    assert any({"B": 1} in a.options for a in mana_abilities.mana_abilities_for(hive, e.state))
    assert len(hive.granted_triggered_abilities) == 1
    e.recompute_continuous_effects()
    assert len(hive.granted_triggered_abilities) == 1


def test_hive_attack_exiles_only_from_the_actual_defending_players_graveyard():
    e = _engine()
    hive = _animate(e)
    victim = _object(e, creature("Defender's dead creature"), "p3", Zone.GRAVEYARD)
    _object(e, creature("Other opponent's dead creature"), "p2", Zone.GRAVEYARD)
    _object(e, creature("My dead creature"), "p1", Zone.GRAVEYARD)
    e.state.current_phase, e.state.current_step = "combat", "declare_attackers"
    e.declare_attackers(e.state.player_by_id("p1"), [{
        "attacker": hive, "defender": {"kind": "player", "id": "p3", "label": "p3"},
    }])
    e.resolve_until_stable()
    choice = e.state.pending_choice
    assert choice and choice["kind"] == "trigger_target"
    assert {o.get("instance_id") for o in choice["options"] if o.get("instance_id")} == {victim.instance_id}
    e.rules.resolve_choice(next(o["id"] for o in choice["options"] if o.get("instance_id") == victim.instance_id))
    e.resolve_until_stable()
    assert victim.zone == Zone.EXILE and victim in e.state.player_by_id("p3").exile


def test_hive_animation_and_trigger_expire_at_cleanup():
    e = _engine()
    hive = _animate(e)
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert hive.is_land and not hive.is_creature
    assert not hive.granted_triggered_abilities and not combat.has(hive, "menace")


def test_each_hive_activation_grants_another_attack_trigger_until_cleanup():
    e = _engine()
    hive = _animate(e)
    e.activate_ability(e.state.player_by_id("p1"), hive, 0)
    e.resolve_until_stable()
    e.recompute_continuous_effects()
    assert len(hive.granted_triggered_abilities) == 2
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert not hive.granted_triggered_abilities


@pytest.mark.parametrize("other_lands, tapped", [(0, False), (1, False), (2, True), (3, True)])
def test_hive_keeps_its_conditional_tapped_entry(other_lands, tapped):
    e = _engine()
    for i in range(other_lands):
        _object(e, land(str(i)))
    hive = _object(e, _card("Hive of the Eye Tyrant"), zone=Zone.HAND)
    e.play_land(e.state.player_by_id("p1"), hive)
    assert hive.tapped is tapped


def _coursework(e):
    host, copy = _prepare(e)
    aura = _object(e, _card("Infinite Coursework"), zone=Zone.HAND)
    e.cast_spell(e.state.player_by_id("p1"), aura, targets=[host])
    e.resolve_until_stable()
    return host, copy, aura


def test_coursework_cast_attaches_taps_unprepares_and_removes_abilities():
    e = _engine()
    host, copy, aura = _coursework(e)
    assert aura.attached_to == host.instance_id
    assert host.tapped and not host.prepared
    assert copy not in e.state.player_by_id("p1").exile
    assert host.loses_all_abilities and continuous.has_no_untap_static(e.state, host)
    assert not combat.has(host, "flying")
    with pytest.raises(ValueError, match="abilit"):
        e.activate_ability(e.state.player_by_id("p1"), host, 0)


def test_coursework_stops_untap_steps_but_allows_effects_to_untap():
    e = _engine()
    host, _, _ = _coursework(e)
    e._step_untap()
    assert host.tapped
    e.rules.set_tapped(host, False)
    assert not host.tapped
    host.tapped = True
    e._step_untap()
    assert host.tapped


def test_coursework_releases_its_host_when_the_aura_leaves():
    e = _engine()
    host, _, aura = _coursework(e)
    e.rules.destroy(aura)
    e.recompute_continuous_effects()
    assert not host.loses_all_abilities and not continuous.has_no_untap_static(e.state, host)
    assert combat.has(host, "flying")
    e._step_untap()
    assert not host.tapped
    e.activate_ability(e.state.player_by_id("p1"), host, 0)
    e.resolve_until_stable()
    assert e.state.player_by_id("p1").life == 21
