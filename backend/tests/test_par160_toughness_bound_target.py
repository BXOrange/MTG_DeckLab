"""PAR-160 — a power/toughness bound as a quality of any `{TARGET}` ("target creature you control with
toughness 2 or less", RULE 208.1 / 115.1 / 608.2b).

The bound rides `subgrammars.TARGET_QUALITY_TAIL` (the PAR-141 quality slot) and is read back as the same
``creature_filter`` (`min_/max_power|toughness`) `targeting` already enforced for destroy/exile/damage, so
every `{TARGET}` verb inherits it: Goblin Kites, Phantasmal Mount, Errant Doomsayers, Suspension Field, ...
The execute tests drive real engines: announce-time legality, resolution-time re-check, and Goblin Kites'
delayed flip / Phantasmal Mount's two leave-the-battlefield sacrifice riders.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.targeting import effects_target_specs, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import make_engine

HEADS, TAILS = 0, 1  # `RulesEngine.coin_flip`: ``random_int(2) == 0`` is a won flip

_KITES_TEXT = (
    "{R}: Target creature you control with toughness 2 or less gains flying until end of turn. "
    "Flip a coin at the beginning of the next end step. If you lose the flip, sacrifice that creature."
)
_MOUNT_TEXT = (
    "Flying\n{T}: Target creature you control with toughness 2 or less gets +1/+1 and gains flying until "
    "end of turn. When this creature leaves the battlefield this turn, sacrifice that creature. When the "
    "creature leaves the battlefield this turn, sacrifice this creature."
)


@pytest.fixture
def script_flips(monkeypatch):
    real = RulesEngine.random_int
    queue: list[int] = []

    def fake(self, n):
        if n == 2 and queue:
            return queue.pop(0)
        return real(self, n)

    monkeypatch.setattr(RulesEngine, "random_int", fake)

    def feed(*results):
        queue[:] = list(results)

    return feed


def _creature(name, text="", power=1, toughness=1, type_line="Creature — Test"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature=True,
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


def _offered(eng, source, ability_index=0):
    specs = effects_target_specs(source.activated_abilities[ability_index].effects)
    assert len(specs) == 1
    return [o["name"] for o in legal_targets(eng.state, "p1", specs[0], source=source)]


# --- parse ---------------------------------------------------------------------------------------------


def test_the_bound_is_a_creature_filter_on_a_you_control_target():
    (spec,) = match_clause("target creature you control with toughness 2 or less gains flying until end of turn")
    assert spec.params["target_kind"] == "creature_you_control"
    assert spec.params["creature_filter"] == {"max_toughness": 2}
    (spec,) = match_clause("tap target creature with toughness 3 or greater")
    assert spec.params["creature_filter"] == {"min_toughness": 3}
    (spec,) = match_clause("tap target creature an opponent controls with power 4 or greater")
    assert spec.params["target_kind"] == "creature_you_dont_control"
    assert spec.params["creature_filter"] == {"min_power": 4}


def test_a_disjunction_or_unknown_stat_is_not_claimed():
    assert match_clause("tap target creature with power or toughness 2 or less") is None
    assert match_clause("tap target creature with loyalty 2 or less") is None


@pytest.mark.parametrize("name,text,kinds", [
    ("Goblin Kites", _KITES_TEXT, {"pump", "create_delayed_trigger"}),
    ("Phantasmal Mount", _MOUNT_TEXT, {"pump", "create_turn_trigger"}),
    ("Errant Doomsayers", "{T}: Tap target creature with toughness 2 or less.", {"tap"}),
])
def test_real_cards_are_modeled(name, text, kinds):
    result = parse_oracle(Card(id=name, name=name, type_line="Creature — Test", oracle_text=text, is_creature=True))
    assert result.modeled, name
    assert kinds <= {e.type for s in result.specs for e in s.effects}


def test_phantasmal_mount_riders_are_two_baked_turn_triggers():
    specs = parse_effect_body(
        "target creature you control with toughness 2 or less gets +1/+1 and gains flying until end of turn. "
        "when ~ leaves the battlefield this turn, sacrifice that creature. "
        "when the creature leaves the battlefield this turn, sacrifice ~."
    )
    assert [s.type for s in specs] == ["pump", "create_turn_trigger", "create_turn_trigger"]
    assert specs[1].params["bake_previous_objects"] is True
    assert specs[2].params["previous_subject"] is True
    # "that creature" with nothing chosen before it stays unclaimed
    assert parse_effect_body("when ~ leaves the battlefield this turn, sacrifice that creature") is None


# --- execute: Goblin Kites -----------------------------------------------------------------------------


def test_kites_offers_only_your_creatures_of_toughness_two_or_less():
    eng = _engine()
    kites = _put(eng, _creature("Goblin Kites", _KITES_TEXT, 0, 1))
    _put(eng, _creature("Small", power=1, toughness=2))
    _put(eng, _creature("Big", power=2, toughness=3))
    _put(eng, _creature("Theirs", power=1, toughness=1), controller="p2")
    assert sorted(_offered(eng, kites)) == ["Goblin Kites", "Small"]


def test_kites_refuses_a_toughness_three_target_on_announcement():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    kites = _put(eng, _creature("Goblin Kites", _KITES_TEXT, 0, 1))
    big = _put(eng, _creature("Big", power=2, toughness=3))
    p1.mana_pool.add_many({"R": 1})
    with pytest.raises(ValueError):
        eng.activate_ability(p1, kites, targets=[big])
    assert "flying" not in big.granted_keywords


def test_kites_target_that_grew_in_response_is_illegal_on_resolution():
    # RULE 608.2b: the bound is re-checked as the ability resolves; a target that is no longer legal is not affected.
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    kites = _put(eng, _creature("Goblin Kites", _KITES_TEXT, 0, 1))
    small = _put(eng, _creature("Small", power=1, toughness=2))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, kites, targets=[small])
    small.counters["+1/+1"] = 1  # toughness 3 before the ability resolves
    eng.recompute_continuous_effects()
    eng.resolve_until_stable()
    assert "flying" not in small.granted_keywords


@pytest.mark.parametrize("result,alive", [(HEADS, True), (TAILS, False)])
def test_kites_end_step_flip_sacrifices_the_target_on_a_loss(script_flips, result, alive):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    kites = _put(eng, _creature("Goblin Kites", _KITES_TEXT, 0, 1))
    small = _put(eng, _creature("Small", power=1, toughness=2))
    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, kites, targets=[small])
    eng.resolve_until_stable()
    assert "flying" in small.granted_keywords
    script_flips(result)
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert (small.zone == Zone.BATTLEFIELD) is alive
    assert kites.zone == Zone.BATTLEFIELD


# --- execute: Phantasmal Mount -------------------------------------------------------------------------


def _mount_board():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    mount = _put(eng, _creature("Phantasmal Mount", _MOUNT_TEXT, 1, 1, "Creature — Horse Illusion"))
    rider = _put(eng, _creature("Rider", power=1, toughness=2))
    eng.activate_ability(p1, mount, targets=[rider])
    eng.resolve_until_stable()
    return eng, mount, rider


def test_mount_pumps_and_grants_flying_to_a_small_creature():
    eng, mount, rider = _mount_board()
    assert (rider.power, rider.toughness) == (2, 3)
    assert "flying" in rider.granted_keywords
    assert mount.zone == rider.zone == Zone.BATTLEFIELD


def test_mount_refuses_a_toughness_three_creature():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    mount = _put(eng, _creature("Phantasmal Mount", _MOUNT_TEXT, 1, 1, "Creature — Horse Illusion"))
    big = _put(eng, _creature("Big", power=2, toughness=3))
    assert sorted(_offered(eng, mount)) == ["Phantasmal Mount"]
    with pytest.raises(ValueError):
        eng.activate_ability(p1, mount, targets=[big])


def test_mount_leaving_sacrifices_the_pumped_creature():
    eng, mount, rider = _mount_board()
    eng.rules.destroy(mount)
    eng.resolve_until_stable()
    assert mount.zone == Zone.GRAVEYARD
    assert rider.zone == Zone.GRAVEYARD


def test_the_pumped_creature_leaving_sacrifices_the_mount():
    eng, mount, rider = _mount_board()
    eng.rules.destroy(rider)
    eng.resolve_until_stable()
    assert rider.zone == Zone.GRAVEYARD
    assert mount.zone == Zone.GRAVEYARD


def test_an_unrelated_creature_leaving_does_nothing():
    eng, mount, rider = _mount_board()
    bystander = _put(eng, _creature("Bystander", power=1, toughness=1))
    eng.rules.destroy(bystander)
    eng.resolve_until_stable()
    assert mount.zone == rider.zone == Zone.BATTLEFIELD


def test_the_riders_expire_at_end_of_turn():
    eng, mount, rider = _mount_board()
    eng.state.turn_scoped_triggers.clear()  # what cleanup does to every "this turn" trigger (RULE 514.2)
    eng.rules.destroy(mount)
    eng.resolve_until_stable()
    assert rider.zone == Zone.BATTLEFIELD


# --- execute: the bound on other verbs the same slot unlocked -----------------------------------------


def test_errant_doomsayers_taps_only_small_toughness_creatures():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    doomsayers = _put(eng, _creature("Errant Doomsayers", "{T}: Tap target creature with toughness 2 or less.", 2, 2))
    small = _put(eng, _creature("Small", power=3, toughness=2), controller="p2")
    big = _put(eng, _creature("Big", power=1, toughness=3), controller="p2")
    assert _offered(eng, doomsayers) == ["Small"]  # the "creature" pool excludes the source
    with pytest.raises(ValueError):
        eng.activate_ability(p1, doomsayers, targets=[big])
    eng.activate_ability(p1, doomsayers, targets=[small])
    eng.resolve_until_stable()
    assert small.tapped and not big.tapped


def test_a_toughness_floor_offers_only_big_creatures():
    eng = _engine()
    guard = _put(eng, _creature("Test Guard", "{T}: Tap target creature with toughness 3 or greater.", 1, 1))
    _put(eng, _creature("Small", power=1, toughness=2), controller="p2")
    _put(eng, _creature("Big", power=1, toughness=3), controller="p2")
    assert _offered(eng, guard) == ["Big"]
