"""Execute real combat costs, duration effects and whole-declaration restrictions."""
import pytest

from mtg_analyzer.game import continuous, durations
from mtg_analyzer.game.card_registry import enters_tapped
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par290_restrictions import _bear, _blockable, _cast_real, _engine, _named, _put, _real


@pytest.mark.parametrize("name", [
    "Exalted Dragon", "Floodtide Serpent", "Hollow Warrior", "Leviathan", "Reclamation",
    "Flooded Woodlands", "Heat Wave", "Forbidding Spirit", "Sivitri, Dragon Master",
    "War Tax", "War Cadence", "Orzhov Advokist", "Okk", "Orcish Conscripts", "Scarred Puma",
])
def test_oracle_is_fully_modeled(name):
    assert parse_oracle(_named(name)).modeled


def _begin_attack(eng, seat=0):
    eng.state.active_player_index = seat
    eng.state.current_step = "declare_attackers"
    return eng.state.active_player


def test_dragon_cost_is_chosen_before_any_cost_or_attack_commits():
    eng = _engine()
    dragon = _real(eng, "Exalted Dragon")
    island = _real(eng, "Island")
    plains = _real(eng, "Plains")
    player = _begin_attack(eng)

    eng.declare_attackers(player, [dragon])
    assert not dragon.tapped and not dragon.attacking
    assert {o["instance_id"] for o in eng.state.pending_choice["options"]} == {island.instance_id, plains.instance_id}
    eng.resolve_pending_choice("decline")
    assert island.zone == plains.zone == Zone.BATTLEFIELD
    eng.declare_attackers(player, [dragon])
    eng.resolve_pending_choice(str(plains.instance_id))
    assert dragon.attacking and dragon.tapped
    assert plains.zone == Zone.GRAVEYARD and island.zone == Zone.BATTLEFIELD


def test_one_land_cannot_pay_two_per_attacker_sacrifices():
    eng = _engine()
    _real(eng, "Flooded Woodlands", "p2")
    green = [_put(eng, _bear(name, mana_cost_string="{G}")) for name in ("Green one", "Green two")]
    forest = _real(eng, "Forest")
    player = _begin_attack(eng)
    with pytest.raises(ValueError, match="cannot pay the permanent costs"):
        eng.declare_attackers(player, green)
    assert forest.zone == Zone.BATTLEFIELD
    assert not any(obj.attacking or obj.tapped for obj in green)


def test_leviathan_only_sacrifices_islands():
    eng = _engine()
    leviathan = _real(eng, "Leviathan")
    assert enters_tapped(leviathan.card)
    first = _real(eng, "Island")
    plains = _real(eng, "Plains")
    player = _begin_attack(eng)
    with pytest.raises(ValueError, match="cannot pay the permanent costs"):
        eng.declare_attackers(player, [leviathan])
    second = _real(eng, "Island")
    eng.declare_attackers(player, [leviathan], cost_choices=(first.instance_id, second.instance_id))
    assert leviathan.attacking
    assert first.zone == second.zone == Zone.GRAVEYARD and plains.zone == Zone.BATTLEFIELD


def test_floodtide_serpent_returns_enchantment_as_cost():
    eng = _engine()
    serpent = _real(eng, "Floodtide Serpent")
    enchantment = _real(eng, "War Tax")
    eng.declare_attackers(_begin_attack(eng), [serpent])
    assert serpent.attacking and enchantment.zone == Zone.HAND


def test_hollow_warrior_cannot_use_another_declared_blocker_for_its_cost():
    eng = _engine()
    attacker = _put(eng, _bear("Attacker"))
    hollow = _real(eng, "Hollow Warrior", "p2")
    helper = _put(eng, _bear("Helper"), "p2")
    assert _blockable(eng, attacker, hollow)
    eng.state.current_step = "declare_blockers"
    defender = eng.state.player_by_id("p2")
    with pytest.raises(ValueError, match="cannot pay the permanent costs"):
        eng.declare_blockers(defender, [(hollow, attacker), (helper, attacker)])
    assert not helper.tapped and hollow.blocking is None
    eng.declare_blockers(defender, [(hollow, attacker)])
    assert helper.tapped and hollow.blocking == attacker.instance_id


def test_heat_wave_life_is_paid_only_when_blocking_its_controllers_creatures():
    eng = _engine(3)
    _real(eng, "Heat Wave", "p1")
    attacker = _put(eng, _bear("Mine"), "p1")
    green = _put(eng, _bear("Green", mana_cost_string="{G}"), "p2")
    blue = _put(eng, _bear("Blue", mana_cost_string="{U}"), "p2")
    assert _blockable(eng, attacker, green)
    assert not _blockable(eng, attacker, blue)
    eng.state.current_step = "declare_blockers"
    defender = eng.state.player_by_id("p2")
    with pytest.raises(ValueError, match="costs declined"):
        eng.declare_blockers(defender, [(green, attacker)], pay_block_tax=False)
    assert defender.life == 20
    eng.declare_blockers(defender, [(green, attacker)])
    assert defender.life == 19


@pytest.mark.parametrize("name,verb", [("War Tax", "attack"), ("War Cadence", "block")])
def test_x_tax_is_locked_on_resolution_stacks_and_expires_in_cleanup(name, verb):
    eng = _engine()
    source = _real(eng, name)
    player = eng.state.active_player
    player.mana_pool.add("U" if verb == "attack" else "R", 5)
    player.mana_pool.add("C", 5)
    eng.state.current_step = "main1"
    for x in [2, 3]:
        eng.activate_ability(player, source, x=x)
        eng.resolve_until_stable()
    eng.rules.put_into_graveyard(source)
    amount = (lambda: continuous.attack_tax_per_creature_for(eng.state, "p2", "battle")
              if verb == "attack" else continuous.block_tax_per_creature(eng.state))
    assert amount() == 5
    durations.sweep(eng.state, "end_of_combat")
    assert amount() == 5
    durations.sweep(eng.state, "cleanup")
    assert amount() == 0


def test_spirit_protects_player_and_planeswalkers_until_their_next_turn():
    eng = _engine(3)
    source = _cast_real(eng, "Forbidding Spirit")
    eng.rules.put_into_graveyard(source)
    eng.state.active_player_index = 1
    durations.sweep(eng.state, "turn_begin")
    for kind in ("player", "planeswalker", "battle"):
        assert continuous.attack_tax_per_creature_for(eng.state, "p1", kind) == (0 if kind == "battle" else 2)
        assert continuous.attack_tax_per_creature_for(eng.state, "p3", kind) == 0
    eng.state.active_player_index = 0
    durations.sweep(eng.state, "turn_begin")
    assert continuous.attack_tax_per_creature_for(eng.state, "p1") == 0


def test_sivitri_charges_life_for_later_attackers():
    eng = _engine()
    source = _real(eng, "Sivitri, Dragon Master")
    source.add_counters("loyalty", 4)
    eng.state.current_step = "main1"
    eng.activate_ability(eng.state.active_player, source)
    eng.resolve_until_stable()
    attacker = _put(eng, _bear("Later attacker"), "p2")
    player = _begin_attack(eng, 1)
    declaration = {"attacker": attacker, "defender": {"kind": "player", "id": "p1"}}
    player.life = 1
    with pytest.raises(ValueError, match="cannot pay the life cost"):
        eng.declare_attackers(player, [declaration])
    assert not attacker.tapped and player.life == 1
    player.life = 20
    eng.declare_attackers(player, [declaration])
    assert attacker.attacking and player.life == 18


def test_advokist_prompts_each_player_and_only_bars_accepting_players():
    eng = _engine(3)
    _real(eng, "Orzhov Advokist")
    chosen = _put(eng, _bear("Chosen"), "p2")
    other = _put(eng, _bear("Other"), "p3")
    eng.state.current_step = "upkeep"
    # Resolve the actual bound upkeep ability.
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(chosen.instance_id))
    assert eng.state.pending_choice["player_id"] == "p3"
    eng.resolve_pending_choice("decline")
    assert chosen.plus_one_counters == 2 and other.plus_one_counters == 0
    later = _put(eng, _bear("Later"), "p2")
    assert continuous.defender_attack_prohibited(eng.state, later, "p1", "planeswalker")
    assert not continuous.defender_attack_prohibited(eng.state, later, "p3")
    assert not continuous.defender_attack_prohibited(eng.state, other, "p1")
    durations.sweep(eng.state, "turn_begin")
    assert not continuous.defender_attack_prohibited(eng.state, later, "p1")


@pytest.mark.parametrize("name,qualities", [
    ("Okk", [{"power": 5}]), ("Orcish Conscripts", [{}, {}]), ("Scarred Puma", [{"mana_cost_string": "{G}"}]),
])
def test_required_attack_companions_are_checked_before_anything_taps(name, qualities):
    eng = _engine()
    creature = _real(eng, name)
    companions = [_put(eng, _bear(f"Companion {n}", **quality)) for n, quality in enumerate(qualities)]
    unrelated = _put(eng, _bear("Wrong companion"))
    player = _begin_attack(eng)
    with pytest.raises(ValueError, match="needs more eligible"):
        eng.declare_attackers(player, [creature, unrelated])
    assert not creature.tapped and not unrelated.tapped
    eng.declare_attackers(player, [creature, *companions])
    assert all(o.attacking for o in [creature, *companions])


def test_okk_checks_companion_power_across_block_assignments():
    eng = _engine()
    attacking = [_put(eng, _bear(f"Attacker {n}")) for n in range(2)]
    okk = _real(eng, "Okk", "p2")
    helper = _put(eng, _bear("Large blocker", power=5), "p2")
    for attacker in attacking:
        assert _blockable(eng, attacker, okk)
    eng.state.current_step = "declare_blockers"
    defender = eng.state.player_by_id("p2")
    with pytest.raises(ValueError, match="needs more eligible"):
        eng.declare_blockers(defender, [(okk, attacking[0])])
    eng.declare_blockers(defender, [(okk, attacking[0]), (helper, attacking[1])])
    assert okk.blocking == attacking[0].instance_id


def test_goad_cannot_require_okk_to_attack_without_a_companion():
    eng = _engine()
    okk = _real(eng, "Okk")
    okk.goaded_by.add("p2")
    _begin_attack(eng)
    eng._enforce_attacks_if_able()
    _put(eng, _bear("Large companion", power=5))
    with pytest.raises(ValueError, match="attacks each combat if able"):
        eng._enforce_attacks_if_able()


def test_lure_cannot_require_okk_to_block_without_a_companion():
    eng = _engine()
    attacker = _put(eng, _bear("Luring attacker"))
    lure = _real(eng, "Lure")
    lure.attached_to = attacker.instance_id
    okk = _real(eng, "Okk", "p2")
    assert _blockable(eng, attacker, okk)
    eng._enforce_block_requirements()
    _put(eng, _bear("Large companion", power=5), "p2")
    with pytest.raises(ValueError, match="must block"):
        eng._enforce_block_requirements()
