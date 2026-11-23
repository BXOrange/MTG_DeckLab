"""PAR-323: "that creature" / "it" under an Aura's or Equipment's own event names the attached host.

RULE 303.4 / 301.5: under "whenever enchanted creature attacks / blocks / becomes blocked / becomes the target of ...", the
one creature the event is about is the host, so a body's "that creature" is that creature (read off the firing event).
RULE 701.3b: under "whenever ~ becomes attached to a creature", "that creature" is the creature just attached to, never
the Equipment. Every behaviour test fields a bystander creature that must stay untouched.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, attack, card, cast, filler, game, named

CARDS = ["Aggression", "Crystallization", "Enormous Energy Blade", "Gift of the Woods", "Mirror Mockery", "Maze's Mantle"]
HOST_POWER = 2
HOST_TOUGHNESS = 2
#: The {R}{R} Red Source plus the {R} Aura itself.
RED_DEVOTION = 3
#: Gift of the Woods' toughness bonus.
BLOCK_BONUS = 3


@pytest.mark.parametrize("name", CARDS)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _host(engine, name="Host", player="p1", **kw):
    return filler(engine, name, type_line="Creature — Bear", power=kw.pop("power", HOST_POWER),
                  toughness=kw.pop("toughness", HOST_TOUGHNESS), player=player, **kw)


def _aura(engine, name, host, player="p1"):
    aura = card(engine, name, player)
    assert engine.rules.attach_to_target(aura, host, check_control=False)
    engine.recompute_continuous_effects()
    return aura


def _life(engine, pid):
    return engine.state.player_by_id(pid).life


def _end_step(engine, player_index):
    """The end step of the seat at ``player_index`` begins (RULE 513.1), its triggers going on the stack and resolving."""
    engine.state.active_player_index = player_index
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def _combat(engine, attackers, blocks=()):
    state = engine.state
    attack(engine, attackers)
    state.current_step = "declare_blockers"
    engine.declare_blockers(state.player_by_id("p2"), [{"blocker": b, "attacker": a} for b, a in blocks])
    engine.resolve_until_stable()
    answer(engine)
    engine.resolve_until_stable()


def test_mirror_mockery_copies_the_host_not_the_bystander_and_exiles_the_token():
    engine = game()
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    _aura(engine, "Mirror Mockery", host)
    _combat(engine, [host, bystander])
    copies = [o for o in engine.state.battlefield if o.is_token]
    assert [c.name for c in copies] == ["Hosty"]
    engine.state.current_step = "end_combat"
    engine._fire_delayed_triggers("end_combat")
    engine.resolve_until_stable()
    assert not [o for o in engine.state.battlefield if o.is_token]


def test_mirror_mockery_does_nothing_when_the_bystander_alone_attacks():
    engine = game()
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    _aura(engine, "Mirror Mockery", host)
    _combat(engine, [bystander])
    assert not [o for o in engine.state.battlefield if o.is_token]


@pytest.mark.parametrize("host_side", ["attacker", "blocker"])
def test_gift_of_the_woods_pumps_only_the_host_and_gains_life(host_side):
    engine = game()
    host_attacks = host_side == "attacker"
    host = _host(engine, "Hosty", player="p1" if host_attacks else "p2")
    foe = _host(engine, "Foe", player="p2" if host_attacks else "p1")
    bystander = _host(engine, "Bystander", player="p1")
    _aura(engine, "Gift of the Woods", host, player=host.controller_id)
    life = _life(engine, host.controller_id)
    attacker, blocker = (host, foe) if host_attacks else (foe, host)
    _combat(engine, [attacker], blocks=[(blocker, attacker)])
    engine.recompute_continuous_effects()
    assert host.toughness == HOST_TOUGHNESS + BLOCK_BONUS
    assert foe.toughness == HOST_TOUGHNESS and bystander.toughness == HOST_TOUGHNESS
    assert _life(engine, host.controller_id) == life + 1


def test_crystallization_exiles_the_targeted_host_only():
    engine = game()
    host = _host(engine, "Hosty", player="p2")
    bystander = _host(engine, "Bystander", player="p2")
    _aura(engine, "Crystallization", host, player="p1")
    shock = card(engine, "Shock", zone=Zone.HAND)
    cast(engine, shock, targets=[host])
    answer(engine)
    engine.resolve_until_stable()
    assert host.zone == Zone.EXILE
    assert bystander.zone == Zone.BATTLEFIELD


def test_crystallization_ignores_a_spell_that_targets_the_bystander():
    engine = game()
    host = _host(engine, "Hosty", player="p2", toughness=5)
    bystander = _host(engine, "Bystander", player="p2", toughness=5)
    _aura(engine, "Crystallization", host, player="p1")
    cast(engine, card(engine, "Shock", zone=Zone.HAND), targets=[bystander])
    answer(engine)
    assert host.zone == Zone.BATTLEFIELD and bystander.zone == Zone.BATTLEFIELD


def test_enormous_energy_blade_taps_the_creature_it_attaches_to_not_itself_or_a_bystander():
    engine = game()
    blade = card(engine, "Enormous Energy Blade")
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    assert engine.rules.attach_to_target(blade, host)
    engine.resolve_until_stable()
    answer(engine)
    assert host.tapped and not bystander.tapped and not blade.tapped


def test_aggression_destroys_a_host_that_did_not_attack_and_spares_one_that_did():
    for attacked in (False, True):
        engine = game()
        host = _host(engine, "Hosty", player="p2")
        bystander = _host(engine, "Bystander", player="p2")
        _aura(engine, "Aggression", host, player="p1")
        host.attacked_this_turn = attacked
        bystander.attacked_this_turn = False
        _end_step(engine, 1)
        assert (host.zone != Zone.BATTLEFIELD) is (not attacked)
        assert bystander.zone == Zone.BATTLEFIELD


def test_aggression_enchants_a_non_wall_creature_only():
    engine = game()
    bear = _host(engine, "Bear")
    wall = filler(engine, "Wall", type_line="Creature — Wall", power=0, toughness=4)
    aggression = card(engine, "Aggression", zone=Zone.HAND)
    assert engine.rules.attach_to_target(aggression, bear)
    assert not engine.rules.attach_to_target(aggression, wall)


def test_puppet_crafting_enchants_an_artifact_or_non_aura_enchantment_only():
    engine = game()
    crafting = card(engine, "Puppet Crafting", zone=Zone.HAND)
    artifact = filler(engine, "Gadget", type_line="Artifact")
    enchantment = filler(engine, "Shrine", type_line="Enchantment")
    aura = filler(engine, "Some Aura", type_line="Enchantment — Aura")
    creature = _host(engine)
    assert engine.rules.attach_to_target(crafting, artifact)
    assert engine.rules.attach_to_target(crafting, enchantment)
    assert not engine.rules.attach_to_target(crafting, aura)
    assert not engine.rules.attach_to_target(crafting, creature)


def test_aggression_does_not_fire_on_the_auras_controllers_own_end_step():
    engine = game()
    host = _host(engine, "Hosty", player="p2")
    _aura(engine, "Aggression", host, player="p1")
    _end_step(engine, 0)
    assert host.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("toxic", [True, False])
def test_maze_s_mantle_shields_the_host_only_when_it_has_toxic(toxic):
    engine = game()
    kw = {"keywords": ["Toxic"]} if toxic else {}
    host = _host(engine, "Hosty", **kw)
    bystander = _host(engine, "Bystander", keywords=["Toxic"])
    mantle = card(engine, "Maze's Mantle", zone=Zone.HAND)
    cast(engine, mantle, targets=[host])
    answer(engine)
    engine.recompute_continuous_effects()
    assert ("hexproof" in {k.lower() for k in host.granted_keywords}) is toxic
    assert "hexproof" not in {k.lower() for k in bystander.granted_keywords}


# --- the other cards the shared template newly claims ---------------------------------------------------------------

NEWLY_CLAIMED = ["Parasitic Impetus", "Avacyn's Collar", "Insubordination", "Oathkeeper, Takeno's Daisho", "Razorfield Ripper", "Spiked Ripsaw", "Thunderous Might"]


@pytest.mark.parametrize("name", NEWLY_CLAIMED)
def test_newly_claimed_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


@pytest.mark.parametrize("attacked", [False, True])
def test_insubordination_hurts_the_hosts_controller_unless_the_host_attacked(attacked):
    engine = game(players=3)
    host = _host(engine, "Hosty", player="p2")
    other = _host(engine, "Other", player="p3")
    _aura(engine, "Insubordination", host, player="p1")
    host.attacked_this_turn = attacked
    other.attacked_this_turn = False                                      # a bystander that did not attack is irrelevant
    _end_step(engine, 1)
    assert _life(engine, "p2") == (20 if attacked else 18)
    assert _life(engine, "p1") == 20 and _life(engine, "p3") == 20


def test_thunderous_might_pumps_the_attacking_host_by_devotion_not_a_bystander():
    engine = game()
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    filler(engine, "Red Source", type_line="Creature — Goblin", power=1, toughness=1, mana_cost_string="{R}{R}")
    _aura(engine, "Thunderous Might", host)
    _combat(engine, [host, bystander])
    engine.recompute_continuous_effects()
    assert host.power == HOST_POWER + RED_DEVOTION and bystander.power == HOST_POWER


def test_razorfield_ripper_pumps_the_equipped_attacker_and_gives_energy():
    engine = game()
    ripper = card(engine, "Razorfield Ripper")
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    ripper.attached_to = host.instance_id
    _combat(engine, [host, bystander])
    engine.recompute_continuous_effects()
    assert engine.state.player_by_id("p1").counters.get("energy", 0) == 1
    assert host.power == HOST_POWER + 1 and bystander.power == HOST_POWER


def test_spiked_ripsaw_gives_trample_to_the_equipped_attacker_after_sacrificing_a_forest():
    engine = game()
    ripsaw = card(engine, "Spiked Ripsaw")
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    forest = filler(engine, "Test Forest", type_line="Basic Land — Forest")
    ripsaw.attached_to = host.instance_id
    _combat(engine, [host, bystander])
    engine.recompute_continuous_effects()
    assert forest.zone != Zone.BATTLEFIELD
    assert "trample" in {k.lower() for k in host.granted_keywords}
    assert "trample" not in {k.lower() for k in bystander.granted_keywords}


@pytest.mark.parametrize("subtype,returns", [("Samurai", True), ("Bear", False)])
def test_oathkeeper_returns_a_dying_samurai_host_only(subtype, returns):
    engine = game()
    daisho = card(engine, "Oathkeeper, Takeno's Daisho")
    host = filler(engine, "Hosty", type_line=f"Creature — {subtype}", power=HOST_POWER, toughness=HOST_TOUGHNESS)
    bystander = filler(engine, "Bystander", type_line="Creature — Samurai", power=HOST_POWER, toughness=HOST_TOUGHNESS)
    daisho.attached_to = host.instance_id
    engine.rules.destroy(bystander)                                      # a Samurai that is not equipped: nothing returns
    engine.resolve_until_stable()
    assert bystander.zone != Zone.BATTLEFIELD
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    answer(engine)
    assert (host.zone == Zone.BATTLEFIELD) is returns


def test_oathkeeper_exiles_the_equipped_creature_when_it_is_put_into_a_graveyard():
    engine = game()
    daisho = card(engine, "Oathkeeper, Takeno's Daisho")
    host = _host(engine, "Hosty")
    bystander = _host(engine, "Bystander")
    daisho.attached_to = host.instance_id
    engine.rules.destroy(daisho)
    engine.resolve_until_stable()
    answer(engine)
    assert host.zone == Zone.EXILE and bystander.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("host_attacks", [True, False])
def test_parasitic_impetus_drains_the_attacking_hosts_controller_for_the_auras_controller(host_attacks):
    engine = game(players=3)
    host = _host(engine, "Hosty", player="p2")
    bystander = _host(engine, "Bystander", player="p2")
    _aura(engine, "Parasitic Impetus", host, player="p1")
    engine.state.active_player_index = 1
    attack(engine, [host if host_attacks else bystander])
    engine.resolve_until_stable()
    answer(engine)
    drained = (_life(engine, "p1"), _life(engine, "p2"), _life(engine, "p3"))
    assert drained == ((22, 18, 20) if host_attacks else (20, 20, 20))


@pytest.mark.parametrize("equipment", ["Avacyn's Collar", "Slayer's Plate"])
@pytest.mark.parametrize("subtype,spirit", [("Human", True), ("Bear", False)])
def test_human_gated_spirit_equipment_makes_a_spirit_only_when_the_equipped_creature_was_a_human(equipment, subtype, spirit):
    engine = game()
    collar = card(engine, equipment)
    host = filler(engine, "Hosty", type_line=f"Creature — {subtype}", power=HOST_POWER, toughness=HOST_TOUGHNESS)
    bystander = filler(engine, "Bystander", type_line="Creature — Human", power=HOST_POWER, toughness=HOST_TOUGHNESS)
    assert engine.rules.attach_to_target(collar, host)
    engine.rules.destroy(bystander)                                       # an unequipped Human dying makes no Spirit
    engine.resolve_until_stable()
    assert not named(engine, "Spirit")
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    answer(engine)
    assert bool(named(engine, "Spirit")) is spirit


def test_attached_retarget_constant_matches_the_binder():
    from mtg_analyzer.game.binding.core import _ATTACHED_PERMANENT_RETARGET_FIELDS
    from mtg_analyzer.parser.oracle.segmenter.conditions import ATTACHED_RETARGETED_EFFECT_TYPES
    assert ATTACHED_RETARGETED_EFFECT_TYPES == frozenset(_ATTACHED_PERMANENT_RETARGET_FIELDS)


def test_writ_of_passage_stays_unclaimed_until_unblockable_can_name_the_host():
    assert parse_oracle(CardDatabase(DB_PATH).get_card("Writ of Passage")).coverage != MODELED
