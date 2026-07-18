"""Tests for phasing (RULE 702.26), scoped to what Robe of Stars actually
needs: a single permanent phases out via an activated ability
("Astral Projection — {1}{W}: Equipped creature phases out") and phases
back in at its controller's next untap step. No "phase out together"
attachment-chain family is modeled (see `game/effects.py`'s
`PhaseOutEffect` docstring) — Robe of Stars' own Equipment stays on the
battlefield, unattached, while the creature is gone.

Engine side: `GameObject.phased_out`, `GameState.permanents`/
`permanents_controlled_by` (the choke point everything else reads through),
`game/effects.py`'s `PhaseOutEffect`, `GameEngine._step_untap`'s RULE
702.26a phase-in sweep.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets


def creature(name="Bear", power=2, toughness=2, controller="p1"):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [creature()]), ("p2", "Bob", [creature("Enemy")])],
        starting_life=20, starting_hand=0,
    )


def _equip_robe_of_stars(eng, host, controller="p1"):
    robe = GameObject(
        Card(id="Robe of Stars", name="Robe of Stars", type_line="Artifact — Equipment"),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(robe)
    eng.state.add_to_battlefield(robe)
    robe.attached_to = host.instance_id
    return robe


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_astral_projection_phases_out_the_equipped_creature():
    eng = make_engine()
    p1 = eng.state.active_player
    bear = _put(eng, creature())
    robe = _equip_robe_of_stars(eng, bear)
    ability = next(a for a in robe.activated_abilities if a.cost.mana.converted_mana_cost == 2)
    p1.mana_pool.add_many({"W": 1, "C": 1})

    eng.activate_ability(p1, robe, robe.activated_abilities.index(ability))
    eng.resolve_until_stable()

    assert bear.phased_out is True
    assert robe.attached_to is None  # detached, not phased out itself


def test_phased_out_permanent_is_excluded_from_permanents():
    eng = make_engine()
    bear = _put(eng, creature())
    bear.phased_out = True
    assert bear not in eng.state.permanents()
    assert bear not in eng.state.permanents_controlled_by("p1")
    assert bear in eng.state.battlefield  # still structurally there (not a zone change)


def test_phased_out_creature_is_untargetable():
    eng = make_engine()
    bear = _put(eng, creature())
    enemy = _put(eng, creature("Enemy"), controller="p2")
    bear.phased_out = True

    spec = TargetSpec(kind="creature")
    options = legal_targets(eng.state, "p2", spec, source=enemy)
    ids = {o["instance_id"] for o in options}
    assert bear.instance_id not in ids


def test_phased_out_creature_cannot_attack_or_block():
    eng = make_engine()
    p1 = eng.state.active_player
    bear = _put(eng, creature())
    enemy = _put(eng, creature("Enemy"), controller="p2")
    bear.phased_out = True

    assert eng._can_attack(p1, bear) is False
    enemy.attacking = True
    enemy.combat_defender = {"kind": "player", "id": "p2"}
    p2 = next(p for p in eng.state.players if p is not p1)
    assert eng.can_block(p2, bear, enemy) is False


def test_phased_out_creature_is_invisible_to_static_anthems():
    eng = make_engine()
    bear = _put(eng, creature(power=2, toughness=2))
    _equip_robe_of_stars(eng, bear)
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (2, 5)  # +0/+3 from Robe of Stars

    bear.phased_out = True
    bear.attached_to = None  # Astral Projection already detached it
    continuous.recompute(eng.state)
    # Phased out: not in `state.permanents()`, so `affected_objects`/
    # `group_selector_objects` skip it entirely — its derived stats reset
    # to base rather than staying pumped.
    assert (bear.power, bear.toughness) == (2, 2)


def test_phased_out_creature_is_ignored_by_state_based_actions():
    eng = make_engine()
    bear = _put(eng, creature(power=2, toughness=2))
    bear.phased_out = True
    bear.damage_marked = 5  # would be lethal if it were live
    eng.rules.check_state_based_actions()
    assert bear in eng.state.battlefield  # not destroyed while phased out


def test_astral_projection_cannot_be_activated_on_an_already_phased_out_creature_twice():
    # Not itself illegal to activate again (Robe of Stars carries no such
    # restriction), but the ability's implicit "equipped creature" subject
    # resolves via `attached_to`, which Astral Projection already cleared —
    # so a second activation is simply a no-op (nothing attached anymore).
    eng = make_engine()
    p1 = eng.state.active_player
    bear = _put(eng, creature())
    robe = _equip_robe_of_stars(eng, bear)
    ability = next(a for a in robe.activated_abilities if a.cost.mana.converted_mana_cost == 2)
    idx = robe.activated_abilities.index(ability)
    p1.mana_pool.add_many({"W": 2, "C": 2})

    eng.activate_ability(p1, robe, idx)
    eng.resolve_until_stable()
    assert bear.phased_out is True

    eng.activate_ability(p1, robe, idx)
    eng.resolve_until_stable()
    assert bear.phased_out is True  # unchanged, no crash


def test_phases_back_in_at_the_controllers_next_untap_step():
    eng = make_engine()
    eng.begin_turn()  # turn 1, p1
    p1 = eng.state.active_player
    bear = _put(eng, creature())
    robe = _equip_robe_of_stars(eng, bear)
    ability = next(a for a in robe.activated_abilities if a.cost.mana.converted_mana_cost == 2)
    p1.mana_pool.add_many({"W": 1, "C": 1})

    eng.activate_ability(p1, robe, robe.activated_abilities.index(ability))
    eng.resolve_until_stable()
    assert bear.phased_out is True

    eng.begin_turn()  # p2's turn (2-player rotation)
    eng._step_untap()  # p2's untap step doesn't touch p1's permanents
    assert bear.phased_out is True

    eng.begin_turn()  # back to p1
    eng._step_untap()  # RULE 702.26a phase-in sweep runs here
    assert bear.phased_out is False
    assert bear in eng.state.permanents()
