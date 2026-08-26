"""Monstrosity (RULE 701.37), Adapt (RULE 701.46) and Goad (RULE 701.15) —
the MEC-2/MEC-3 batch.

Three keyword actions that had no primitive and no recognition at all:

* **Monstrosity N** (701.37a) — "if this permanent isn't monstrous, put N
  +1/+1 counters on it and it becomes monstrous", one atomic
  `RulesEngine.monstrosity` for the same reason Renown is one (the guard,
  the counters and the designation are a single conditional). The
  designation (`GameObject.is_monstrous`, 701.37b) exists to be read by two
  things this batch also builds: `EventType.BECAME_MONSTROUS` ("when ~
  becomes monstrous, …") and the RULE 613.6 conditional static "as long as
  ~ is monstrous, it has `<keywords>`" — which shipped here as a bespoke
  ``requires_monstrous`` selector param and was immediately generalized into
  `game/static_conditions.py`'s ``active_if`` vocabulary (see
  `test_static_conditions_and_durations.py`).
* **Adapt N** (701.46a) — deliberately *not* the same primitive: its gate is
  the creature's current +1/+1 counters, not a designation, so it can happen
  again and again and defines no "becomes adapted" event. The adapt cards'
  own "as long as ~ has a +1/+1 counter on it" statics needed nothing new —
  that is the layer engine's existing ``min_level`` gate.
* **Goad** (701.15) — a designation with *two* combat requirements: attacks
  each combat if able (which rides the existing `attacks_if_able` check) and
  attacks a player other than the goader if able (which can only be judged
  once the whole attack is declared, so it sits with
  `_enforce_attack_alone_restrictions` on the way out of the step). Goaded
  is a set of goaders, not a flag — 701.15c's several goaders each add a
  requirement, 701.15d's re-goad adds nothing — and it expires at the start
  of the goader's next turn (701.15a), while its *static* half ("enchanted
  creature … is goaded") is re-derived every recompute so it vanishes with
  its Aura.

Each test drives real oracle text through `parse_oracle` (asserting the card
is fully `MODELED`) **and** exercises it against a real `GameEngine`, per
this project's "parse-only verification has masked real runtime bugs" rule.

Reference: mtg_analyzer/game/{rules_engine,effects,combat,continuous,
game_engine}.py, mtg_analyzer/parser/oracle/{segmenter,catalogue/handlers,
catalogue/static_handlers}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Beast", mana_cost="{2}{G}"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []), mana_cost_string=mana_cost,
    )


def _aura(name, oracle_text):
    return Card(
        id=name, name=name, type_line="Enchantment — Aura",
        oracle_text=oracle_text, mana_cost_string="{1}{U}",
    )


def _engine(players=(("p1", "Alice", []), ("p2", "Bob", []))):
    return GameEngine.new_game(list(players), starting_life=20, starting_hand=0)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _modeled(card):
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    assert result.unclaimed == []
    return result


def _to_declare_attackers(eng):
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()


def _events(state, kind):
    return [e for e in state.event_log if e.type == kind]


# ---------------------------------------------------------------------------
# Monstrosity (RULE 701.37)
# ---------------------------------------------------------------------------


def test_monstrosity_puts_counters_and_sets_the_designation():
    eng = _engine()
    obj = _put(eng.state, _creature("Ill-Tempered Cyclops"))

    assert eng.rules.monstrosity(obj, 3) is True
    assert obj.is_monstrous is True
    assert obj.plus_one_counters == 3
    assert obj.monstrosity_x == 3  # RULE 701.37c
    assert len(_events(eng.state, EventType.BECAME_MONSTROUS)) == 1


def test_monstrosity_is_a_no_op_once_already_monstrous():
    # RULE 701.37a's "if this permanent isn't monstrous" — a second
    # activation puts *no* counters on and fires no second event.
    eng = _engine()
    obj = _put(eng.state, _creature("Ill-Tempered Cyclops"))
    eng.rules.monstrosity(obj, 3)

    assert eng.rules.monstrosity(obj, 3) is False
    assert obj.plus_one_counters == 3
    assert len(_events(eng.state, EventType.BECAME_MONSTROUS)) == 1


def test_monstrous_does_not_survive_leaving_the_battlefield():
    # RULE 701.37b: "stays monstrous until it leaves the battlefield" — which
    # is RULE 400.7's new object (`reset_as_new_object`).
    eng = _engine()
    obj = _put(eng.state, _creature("Ill-Tempered Cyclops"))
    eng.rules.monstrosity(obj, 2)
    assert obj.is_monstrous is True

    obj.reset_as_new_object()
    assert obj.is_monstrous is False
    assert obj.monstrosity_x == 0


def test_monstrosity_activated_ability_parses_and_resolves():
    card = _creature(
        "Fleecemane Lion",
        "{3}{G}{W}: Monstrosity 1.\n"
        "As long as Fleecemane Lion is monstrous, it has hexproof and indestructible.",
        power=3, toughness=3,
    )
    _modeled(card)

    eng = _engine()
    obj = _put(eng.state, card)
    ability = obj.activated_abilities[0]
    ability.effects[0].apply(eng.rules.context)

    assert obj.is_monstrous is True
    assert obj.plus_one_counters == 1


def test_as_long_as_monstrous_grant_only_applies_once_monstrous():
    # The RULE 613.6 conditional static: the keywords must be absent before
    # and present after, re-derived by the layer engine rather than granted
    # once at resolution.
    card = _creature(
        "Fleecemane Lion",
        "{3}{G}{W}: Monstrosity 1.\n"
        "As long as Fleecemane Lion is monstrous, it has hexproof and indestructible.",
        power=3, toughness=3,
    )
    _modeled(card)

    eng = _engine()
    obj = _put(eng.state, card)
    continuous.recompute(eng.state)
    assert not combat.has(obj, "hexproof")
    assert not combat.has(obj, "indestructible")

    eng.rules.monstrosity(obj, 1)
    continuous.recompute(eng.state)
    assert combat.has(obj, "hexproof")
    assert combat.has(obj, "indestructible")


def test_becomes_monstrous_trigger_fires_only_on_the_transition():
    card = _creature(
        "Nessian Asp",
        "{6}{G}: Monstrosity 4.\nWhen Nessian Asp becomes monstrous, you gain 3 life.",
    )
    _modeled(card)

    eng = _engine()
    obj = _put(eng.state, card)
    player = eng.state.player_by_id("p1")
    start = player.life

    eng.rules.monstrosity(obj, 4)
    eng.resolve_until_stable()
    assert player.life == start + 3

    # A second monstrosity does nothing at all — no counters, no trigger.
    eng.rules.monstrosity(obj, 4)
    eng.resolve_until_stable()
    assert player.life == start + 3


def test_monstrosity_x_uses_the_announced_x():
    # "{X}{X}{R}: Monstrosity X" — the ``"x"`` sentinel `_substitute_x`
    # rewrites at resolution, and RULE 701.37c's recorded value.
    specs = match_clause("monstrosity x")
    assert [(s.type, s.params) for s in specs] == [("monstrosity", {"amount": "x"})]

    from mtg_analyzer.game.effects import EffectRegistry

    effect = EffectRegistry.create("monstrosity", {"amount": "x"})
    eng = _engine()
    obj = _put(eng.state, _creature("Fanatic of Xenagos"))
    effect.source = obj
    eng.rules._substitute_x([effect], 4)
    effect.apply(eng.rules.context)

    assert obj.is_monstrous is True
    assert obj.plus_one_counters == 4
    assert obj.monstrosity_x == 4


# ---------------------------------------------------------------------------
# Adapt (RULE 701.46)
# ---------------------------------------------------------------------------


def test_adapt_puts_counters_only_when_there_are_none():
    eng = _engine()
    obj = _put(eng.state, _creature("Sauroform Hybrid"))

    assert eng.rules.adapt(obj, 3) is True
    assert obj.plus_one_counters == 3

    # RULE 701.46a: it already has +1/+1 counters, so this does nothing.
    assert eng.rules.adapt(obj, 3) is False
    assert obj.plus_one_counters == 3


def test_adapt_applies_again_once_the_counters_are_gone():
    # The designation-free gate is the whole difference from monstrosity:
    # remove the counters and adapt works again.
    eng = _engine()
    obj = _put(eng.state, _creature("Sauroform Hybrid"))
    eng.rules.adapt(obj, 2)
    obj.plus_one_counters = 0

    assert eng.rules.adapt(obj, 2) is True
    assert obj.plus_one_counters == 2


def test_adapt_activated_ability_parses_and_resolves():
    card = _creature("Aeromunculus", "{1}{G}{U}: Adapt 1.", keywords=["Flying"])
    _modeled(card)

    eng = _engine()
    obj = _put(eng.state, card)
    obj.activated_abilities[0].effects[0].apply(eng.rules.context)
    assert obj.plus_one_counters == 1


def test_adapt_does_not_define_a_designation():
    # Nothing in the engine should have grown an "is_adapted" flag — the real
    # cards read their own +1/+1 counters, so a designation would be a second
    # source of truth that could disagree.
    eng = _engine()
    obj = _put(eng.state, _creature("Sauroform Hybrid"))
    eng.rules.adapt(obj, 1)
    assert obj.is_monstrous is False


# ---------------------------------------------------------------------------
# Goad (RULE 701.15)
# ---------------------------------------------------------------------------


def test_goad_records_the_goader_and_fires_the_event():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"), controller="p2")

    eng.rules.goad(obj, "p1")
    assert combat.is_goaded(obj)
    assert combat.goaders(obj) == {"p1"}
    assert len(_events(eng.state, EventType.GOADED)) == 1


def test_several_goaders_each_add_their_own_requirement():
    # RULE 701.15c/d: two players goading adds two requirements; the same
    # player goading twice adds nothing (a set gives both for free).
    eng = _engine([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])])
    obj = _put(eng.state, _creature("Bear"), controller="p2")

    eng.rules.goad(obj, "p1")
    eng.rules.goad(obj, "p3")
    eng.rules.goad(obj, "p1")
    assert combat.goaders(obj) == {"p1", "p3"}


def test_goaded_creature_must_attack():
    # RULE 701.15b's first half, enforced exactly like `attacks_if_able`.
    eng = _engine()
    state = eng.state
    obj = _put(state, _creature("Goaded Bear"))
    _put(state, _creature("Wall"), controller="p2")
    eng.rules.goad(obj, "p2")
    eng.start()
    _to_declare_attackers(eng)

    with pytest.raises(ValueError, match="attacks each combat if able"):
        eng.advance_step()

    eng.declare_attackers(state.active_player, [obj])
    eng.advance_step()  # now legal
    assert obj.attacking is True


def test_goad_expires_at_the_start_of_the_goaders_next_turn():
    # RULE 701.15a: "until the next turn of the controller of that spell or
    # ability" — p2 goads on p1's turn, and it lapses as p2's turn begins.
    eng = _engine()
    obj = _put(eng.state, _creature("Goaded Bear"))
    eng.rules.goad(obj, "p2")
    assert combat.is_goaded(obj)

    eng.start()
    eng.begin_turn()  # → p2's turn
    assert eng.state.active_player.id == "p2"
    assert not combat.is_goaded(obj)


def test_goad_survives_a_turn_that_is_not_the_goaders():
    eng = _engine([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])])
    obj = _put(eng.state, _creature("Goaded Bear"))
    eng.rules.goad(obj, "p3")

    eng.start()
    eng.begin_turn()  # → p2, not the goader
    assert eng.state.active_player.id == "p2"
    assert combat.is_goaded(obj)


def test_goaded_creature_must_attack_someone_other_than_its_goader():
    # RULE 701.15b's second half, with a real alternative available.
    eng = _engine([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])])
    state = eng.state
    obj = _put(state, _creature("Goaded Bear"))
    eng.rules.goad(obj, "p2")
    eng.start()
    _to_declare_attackers(eng)

    eng.declare_attackers(
        state.active_player,
        [{"attacker": obj, "defender": state.player_by_id("p2")}],
    )
    with pytest.raises(ValueError, match="must attack a player other than"):
        eng.advance_step()


def test_goaded_creature_may_attack_its_goader_when_nobody_else_is_attackable():
    # The "if able" half. In a two-player game "a player other than you" has
    # no answer at all, so attacking the goader is correct and must not
    # raise — this is the case that makes goad inert in 1v1.
    eng = _engine()
    state = eng.state
    obj = _put(state, _creature("Goaded Bear"))
    eng.rules.goad(obj, "p2")
    eng.start()
    _to_declare_attackers(eng)

    eng.declare_attackers(
        state.active_player,
        [{"attacker": obj, "defender": state.player_by_id("p2")}],
    )
    eng.advance_step()  # no ValueError
    assert obj.attacking is True


def test_goaded_creature_attacking_a_third_player_is_fine():
    eng = _engine([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Carol", [])])
    state = eng.state
    obj = _put(state, _creature("Goaded Bear"))
    eng.rules.goad(obj, "p2")
    eng.start()
    _to_declare_attackers(eng)

    eng.declare_attackers(
        state.active_player,
        [{"attacker": obj, "defender": state.player_by_id("p3")}],
    )
    eng.advance_step()
    assert obj.attacking is True


def test_goad_target_creature_parses_and_resolves():
    from mtg_analyzer.game.effects import EffectRegistry

    specs = match_clause("goad target creature")
    assert [(s.type, s.params) for s in specs] == [("goad", {"target_kind": "creature"})]

    eng = _engine()
    source = _put(eng.state, _creature("Goader"))
    victim = _put(eng.state, _creature("Bear"), controller="p2")
    effect = EffectRegistry.create("goad", {"target_kind": "creature"})
    effect.source = source
    effect.apply(eng.rules.context, [victim])

    assert combat.goaders(victim) == {"p1"}


def test_goad_mass_form_hits_every_opposing_creature():
    from mtg_analyzer.game.effects import EffectRegistry

    specs = match_clause("goad all creatures your opponents control")
    assert specs and specs[0].type == "goad"

    eng = _engine()
    source = _put(eng.state, _creature("Disrupt Decorum"))
    theirs_a = _put(eng.state, _creature("Bear A"), controller="p2")
    theirs_b = _put(eng.state, _creature("Bear B"), controller="p2")
    mine = _put(eng.state, _creature("My Bear"), controller="p1")

    effect = EffectRegistry.create("goad", specs[0].params)
    effect.source = source
    effect.apply(eng.rules.context)

    assert combat.is_goaded(theirs_a) and combat.is_goaded(theirs_b)
    assert not combat.is_goaded(mine)  # never your own creatures


def test_static_goad_from_an_aura_applies_and_vanishes_with_it():
    card = _aura("Acquired Mutation", "Enchant creature\nEnchanted creature gets +2/+2 and is goaded.")
    _modeled(card)

    eng = _engine()
    state = eng.state
    victim = _put(state, _creature("Bear"), controller="p2")
    aura = _put(state, card)
    aura.attached_to = victim.instance_id
    continuous.recompute(state)

    assert combat.goaders(victim) == {"p1"}
    assert victim.power == 4  # the anthem half still works alongside it

    # The designation is re-derived, not sticky: removing the Aura removes it
    # (unlike a resolve-time goad, which would persist to the goader's turn).
    state.battlefield.remove(aura)
    continuous.recompute(state)
    assert not combat.is_goaded(victim)


def test_static_goad_does_not_leak_into_the_sticky_set():
    card = _aura("Acquired Mutation", "Enchant creature\nEnchanted creature gets +2/+2 and is goaded.")
    eng = _engine()
    victim = _put(eng.state, _creature("Bear"), controller="p2")
    aura = _put(eng.state, card)
    aura.attached_to = victim.instance_id
    continuous.recompute(eng.state)

    assert victim.goaded_by == set()  # only `_goaded_by_static` is set
    assert combat.is_goaded(victim)


def test_bare_enchanted_creature_is_goaded_parses():
    assert [(s.type, s.params) for s in static_effect_specs("enchanted creature is goaded.")] == [
        ("goaded", {"affects": "attached_permanent"})
    ]


def test_ungoaded_creature_is_never_forced_to_attack():
    # The negative case: the new requirement must not bite an ordinary
    # creature, which is free to sit back.
    eng = _engine()
    state = eng.state
    obj = _put(state, _creature("Peaceful Bear"))
    eng.start()
    _to_declare_attackers(eng)
    eng.advance_step()  # no ValueError
    assert obj.attacking is False


def test_compound_monstrous_grant_now_claims_both_halves():
    # This clause was the whole of MEC-13, and used to fail closed (this test
    # asserted exactly that). The grant grammar now carries a combat
    # *permission* tail alongside the keyword list, so Colossus of Akros gets
    # both halves — see `test_static_conditions_and_durations.py` for the
    # permission's own engine behaviour.
    specs = static_effect_specs(
        "as long as ~ is monstrous, it has trample and can attack as though "
        "it didn't have defender."
    )
    assert [(s.type, s.params.get("kind") or s.params.get("keywords")) for s in specs] == [
        ("grant_keyword", ["trample"]),
        ("combat_restriction", "attacks_as_though_no_defender"),
    ]
    assert all(s.params["active_if"] == {"kind": "source_monstrous"} for s in specs)


def test_unknown_permission_tail_still_fails_the_whole_clause():
    # The fail-closed half is what makes the tail safe: a permission outside
    # the vocabulary must not leave the keywords claimed and the permission
    # silently dropped.
    assert static_effect_specs("~ has flying and can do a barrel roll.") is None
