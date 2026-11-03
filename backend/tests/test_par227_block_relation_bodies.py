"""PAR-227 -- block-relation effect bodies that act on "that creature" (RULE 509.3).

"Whenever ~ blocks or becomes blocked by a creature, ~ deals 1 damage to that creature" (and the pump,
characteristic and ability-change siblings) read the creature on the *other* side of the block. The body is bound as a
`trigger_related_referent`, which runs once per relation the firing event names. Parse tests pin the shape and the
fail-closed edges; execute tests run real combats.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import parse_oracle

from tests.test_par119_attack_batch_head import _attackers, _combat
from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _put

HEAD = "Whenever ~ blocks or becomes blocked by a creature, "
HOUND = HEAD + "~ deals 1 damage to that creature."


def _parse(oracle, types="Creature — Bear"):
    return parse_oracle(Card(id="T", name="T", type_line=types, oracle_text=oracle, is_creature="Creature" in types))


@pytest.mark.parametrize(
    "name",
    [
        "Ashmouth Hound", "Assembled Alphas", "Flailing Drake", "Barrow-Blade", "Inferno Elemental", "Ornery Goblin",
        "Skewer Slinger", "Talruum Champion", "Mammoth Harness", "Aisling Leprechaun", "Witherscale Wurm",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def test_the_body_is_one_per_relation_wrapper_around_the_damage():
    [triggered] = _parse(HOUND).specs
    [wrapper] = triggered.effects
    assert wrapper.type == "trigger_related_referent"
    assert wrapper.params["effects"] == [{"type": "damage", "params": {
        "amount": 1, "recipient_subject": "previous_subject_object"}}]


@pytest.mark.parametrize(
    "oracle",
    [
        # the damage source of an Equipment head would be the Equipment, not the equipped creature
        "Whenever equipped creature blocks or becomes blocked by a creature, ~ deals 1 damage to that creature.",
        # the first half reads, the second does not: the whole ability stays unclaimed
        HEAD + "that creature gets +1/+1 until end of turn. frobnicate that creature.",
        # half-readable compound body: the unreadable half keeps the whole ability unclaimed
        HEAD + "that creature gets +1/+1 until end of turn and frobnicate.",
    ],
)
def test_refuses_what_it_cannot_bind_faithfully(oracle):
    assert not _parse(oracle, "Artifact — Equipment" if "equipped" in oracle else "Creature — Bear").modeled


def _board():
    engine, state = _engine()
    return engine, state


def _damage(obj):
    return obj.damage_marked


def test_a_hound_that_blocks_damages_only_the_creature_it_blocked():
    engine, state = _board()
    attacker, bystander = _attackers(state, [("Raider", "Creature — Bear", ()), ("Other", "Creature — Bear", ())])
    hound = _put(state, HOUND, name="Hound", types="Creature — Dog", owner="p2")
    hound.summoning_sick = False
    _combat(state, engine, [attacker, bystander], [(hound, attacker)])
    assert _damage(attacker) == 1 and _damage(bystander) == 0 and _damage(hound) == 0


def test_a_hound_that_is_blocked_by_two_creatures_damages_each_blocker_separately():
    engine, state = _board()
    hound = _put(state, HOUND, name="Hound", types="Creature — Dog")
    hound.summoning_sick = False
    first, second = _attackers(state, [("B1", "Creature — Bear", ()), ("B2", "Creature — Bear", ())], owner="p2")
    _combat(state, engine, [hound], [(first, hound), (second, hound)])
    assert _damage(first) == 1 and _damage(second) == 1


def test_the_head_filter_picks_which_relations_are_read():
    engine, state = _board()
    hound = _put(state, "Whenever ~ blocks or becomes blocked by a non-Wall creature, ~ deals 1 damage to that creature.",
                 name="Hound", types="Creature — Dog")
    hound.summoning_sick = False
    wall, bear = _attackers(state, [("Wall", "Creature — Wall", ()), ("Bear", "Creature — Bear", ())], owner="p2")
    _combat(state, engine, [hound], [(wall, hound), (bear, hound)])
    assert _damage(wall) == 0 and _damage(bear) == 1


def test_assembled_alphas_also_damages_the_creatures_controller():
    engine, state = _board()
    alphas = _put(state, HEAD + "~ deals 3 damage to that creature and 3 damage to that creature's controller.",
                  name="Alphas", types="Creature — Wolf")
    alphas.summoning_sick = False
    blocker = _attackers(state, [("Blocker", "Creature — Bear", ())], owner="p2")[0]
    life = state.player_by_id("p2").life
    _combat(state, engine, [alphas], [(blocker, alphas)])
    assert state.player_by_id("p2").life == life - 3
    assert state.player_by_id("p1").life == 20


def test_flailing_drake_pumps_the_other_creature_not_itself():
    engine, state = _board()
    drake = _put(state, HEAD + "that creature gets +1/+1 until end of turn.", name="Drake", types="Creature — Drake")
    drake.summoning_sick = False
    blocker = _attackers(state, [("Blocker", "Creature — Bear", ())], owner="p2")[0]
    _combat(state, engine, [drake], [(blocker, drake)])
    engine.recompute_continuous_effects()
    assert (blocker.power, blocker.toughness) == (3, 3)
    assert (drake.power, drake.toughness) == (2, 2)


def test_talruum_champion_strips_first_strike_from_the_other_creature():
    engine, state = _board()
    champ = _put(state, HEAD + "that creature loses first strike until end of turn.", name="Champ",
                 types="Creature — Minotaur")
    champ.summoning_sick = False
    blocker = _attackers(state, [("Blocker", "Creature — Knight", ("First strike",))], owner="p2")[0]
    assert combat.has_first_strike(blocker)
    _combat(state, engine, [champ], [(blocker, champ)])
    engine.recompute_continuous_effects()
    assert not combat.has_first_strike(blocker)


def test_barrow_blade_uses_the_equipped_creatures_relation_and_strips_the_other_creature():
    engine, state = _board()
    blade = _put(state, "Whenever equipped creature blocks or becomes blocked by a creature, that creature loses all "
                        "abilities until end of turn.", name="Blade", types="Artifact — Equipment", owner="p2")
    host, bystander = _attackers(state, [("Host", "Creature — Bear", ()), ("Bystander", "Creature — Bear", ())], owner="p2")
    attacker = _attackers(state, [("Flier", "Creature — Bird", ("Trample",))])[0]
    other = _attackers(state, [("Ground", "Creature — Bear", ("Trample",))])[0]
    blade.attached_to = host.instance_id
    _combat(state, engine, [attacker, other], [(host, attacker), (bystander, other)])
    engine.recompute_continuous_effects()
    assert attacker.loses_all_abilities is True
    assert other.loses_all_abilities is False  # blocked by a creature that is not equipped


def test_aisling_leprechaun_turns_the_other_creature_green():
    engine, state = _board()
    leprechaun = _put(state, HEAD + "that creature becomes green.", name="Leprechaun", types="Creature — Faerie")
    leprechaun.summoning_sick = False
    blocker = _attackers(state, [("Blocker", "Creature — Bear", ())], owner="p2")[0]
    _combat(state, engine, [leprechaun], [(blocker, leprechaun)])
    engine.recompute_continuous_effects()
    assert list(blocker.colors) == ["G"]


def test_a_quantity_of_the_other_creature_is_read_per_relation():
    engine, state = _board()
    drake = _put(state, HEAD + "that creature gets +X/+X until end of turn, where X is its power.", name="Drake",
                 types="Creature — Drake")
    drake.summoning_sick = False
    big, small = _attackers(state, [("Big", "Creature — Bear", ()), ("Small", "Creature — Bear", ())], owner="p2")
    big.card.power = 4
    engine.recompute_continuous_effects()
    _combat(state, engine, [drake], [(big, drake), (small, drake)])
    engine.recompute_continuous_effects()
    assert (big.power, small.power) == (8, 4)


def test_tapping_and_freezing_the_blocked_creature_leaves_the_blocker_untapped():
    engine, state = _board()
    spawn = _put(state, "Whenever ~ blocks a creature, tap that creature. That creature doesn't untap during its "
                        "controller's next untap step.", name="Spawn", types="Creature — Illusion", owner="p2")
    spawn.summoning_sick = False
    attacker, bystander = _attackers(state, [("Raider", "Creature — Bear", ()), ("Other", "Creature — Bear", ())])
    attacker.tapped = False
    _combat(state, engine, [attacker, bystander], [(spawn, attacker)])
    assert attacker.tapped and attacker.skip_next_untap
    assert not spawn.tapped and not spawn.skip_next_untap
    assert not bystander.skip_next_untap


def test_witherscale_style_ability_grant_reaches_the_other_creature_only():
    engine, state = _board()
    wurm = _put(state, HEAD + "that creature gains wither until end of turn.", name="Wurm", types="Creature — Wurm")
    wurm.summoning_sick = False
    blocker = _attackers(state, [("Blocker", "Creature — Bear", ())], owner="p2")[0]
    _combat(state, engine, [wurm], [(blocker, wurm)])
    engine.recompute_continuous_effects()
    assert "wither" in blocker.granted_keywords and "wither" not in wurm.granted_keywords
