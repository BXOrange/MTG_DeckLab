"""PAR-286 milestone 6: three small head clusters that reuse existing engine events.

* "whenever you gain or lose life during your turn" (Moonstone Harbinger, Wax-Wane Witness): `LIFE_GAINED` and
  `LIFE_LOST` share one once-per-turn state (RULE 603.2, `limit_group`).
* "whenever enchanted / fortified <permanent> becomes tapped" with the host's controller as the recipient (Insolence,
  Lust for War, Psychic Venom, Relic Putrescence, Darksteel Garrison; Impending Doom reads the same
  "that creature's controller" under its dies head).
* "whenever a permanent you control transforms [into ...]" (Cult of the Waxing Moon, Norn's Inquisitor): `TRANSFORMED`
  fires after the flip, so the "into" phrase is read against the new face.
* "whenever 1 or more nontoken <type> you control become tapped" (Deeproot Pilgrimage): one trigger per batch
  (RULE 603.2c), also for a mass tap and for the attack declaration.

Every test drives the real event on the real card; each has a near miss that must not fire.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, attack, card, filler, game, named

NEWLY_MODELED = [
    "Moonstone Harbinger", "Wax-Wane Witness", "Insolence", "Lust for War", "Psychic Venom", "Relic Putrescence",
    "Darksteel Garrison", "Impending Doom", "Cult of the Waxing Moon", "Norn's Inquisitor", "Deeproot Pilgrimage",
]
OPPONENT = "p2"
ME = "p1"
STARTING_LIFE = 20
#: The printed damage of each Aura's trigger.
INSOLENCE_DAMAGE, LUST_FOR_WAR_DAMAGE, PSYCHIC_VENOM_DAMAGE = 2, 3, 2


@pytest.mark.parametrize("name", NEWLY_MODELED)
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def _player(engine, pid):
    return engine.state.player_by_id(pid)


def _power(engine, obj):
    engine.recompute_continuous_effects()
    return obj.power


# ---------------------------------------------------------------- gain or lose life during your turn

def test_wax_wane_witness_fires_on_my_gain_and_my_loss_during_my_turn():
    engine = game()
    witness = card(engine, "Wax-Wane Witness")
    base = _power(engine, witness)
    engine.rules.gain_life(_player(engine, ME), 1)
    engine.resolve_until_stable()
    assert _power(engine, witness) == base + 1
    engine.rules.lose_life(_player(engine, ME), 1)
    engine.resolve_until_stable()
    assert _power(engine, witness) == base + 2  # "this ability" has no once-a-turn limit on Wax-Wane Witness


def test_wax_wane_witness_ignores_the_opponent_and_the_opponents_turn():
    engine = game()
    witness = card(engine, "Wax-Wane Witness")
    base = _power(engine, witness)
    # near miss 1: the opponent gains and loses life on my turn
    engine.rules.gain_life(_player(engine, OPPONENT), 3)
    engine.rules.lose_life(_player(engine, OPPONENT), 3)
    engine.resolve_until_stable()
    assert _power(engine, witness) == base
    # near miss 2: I gain life on the opponent's turn
    engine.state.active_player_index = 1
    engine.rules.gain_life(_player(engine, ME), 1)
    engine.rules.lose_life(_player(engine, ME), 1)
    engine.resolve_until_stable()
    assert _power(engine, witness) == base


def test_moonstone_harbinger_pumps_bats_once_per_turn_across_gain_and_loss():
    engine = game()
    harbinger = card(engine, "Moonstone Harbinger")
    bat = filler(engine, "Other Bat", type_line="Creature — Bat", power=1, toughness=1)
    nonbat = filler(engine, "Not A Bat", type_line="Creature — Cat", power=1, toughness=1)
    base, own = _power(engine, bat), _power(engine, harbinger)
    engine.rules.gain_life(_player(engine, ME), 1)
    engine.resolve_until_stable()
    engine.rules.lose_life(_player(engine, ME), 1)  # same turn: the shared limit stops the second trigger
    engine.resolve_until_stable()
    assert _power(engine, bat) == base + 1
    assert _power(engine, harbinger) == own + 1  # it is a Bat itself, pumped once too
    assert _power(engine, nonbat) == 1


def test_moonstone_harbinger_loss_alone_also_triggers():
    engine = game()
    card(engine, "Moonstone Harbinger")
    bat = filler(engine, "Other Bat", type_line="Creature — Bat", power=1, toughness=1)
    engine.rules.lose_life(_player(engine, ME), 1)
    engine.resolve_until_stable()
    assert _power(engine, bat) == 2


# ---------------------------------------------------------------- becomes tapped, attached subjects

def _aura_on(engine, name, host):
    aura = card(engine, name)
    aura.attached_to = host.instance_id
    return aura


@pytest.mark.parametrize("name, damage", [
    ("Insolence", INSOLENCE_DAMAGE), ("Lust for War", LUST_FOR_WAR_DAMAGE),
])
def test_creature_auras_hurt_the_hosts_controller_when_it_becomes_tapped(name, damage):
    engine = game()
    host = filler(engine, "Host", type_line="Creature", player=OPPONENT, power=2, toughness=2)
    other = filler(engine, "Other", type_line="Creature", player=OPPONENT, power=2, toughness=2)
    _aura_on(engine, name, host)
    # near miss: a creature the Aura does not enchant
    engine.rules.set_tapped(other, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE
    engine.rules.set_tapped(host, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE - damage
    assert _player(engine, ME).life == STARTING_LIFE  # the Aura's controller is not hurt


def test_psychic_venom_reads_the_enchanted_land():
    engine = game()
    land = filler(engine, "Their Land", type_line="Land", player=OPPONENT)
    other = filler(engine, "Their Other Land", type_line="Land", player=OPPONENT)
    _aura_on(engine, "Psychic Venom", land)
    engine.rules.set_tapped(other, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE
    engine.rules.set_tapped(land, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE - PSYCHIC_VENOM_DAMAGE


def test_relic_putrescence_gives_the_artifacts_controller_a_poison_counter():
    engine = game()
    relic = filler(engine, "Their Relic", type_line="Artifact", player=OPPONENT)
    other = filler(engine, "Other Relic", type_line="Artifact", player=OPPONENT)
    _aura_on(engine, "Relic Putrescence", relic)
    engine.rules.set_tapped(other, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).poison == 0
    engine.rules.set_tapped(relic, True)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).poison == 1
    assert _player(engine, ME).poison == 0


def test_a_permanent_that_enters_tapped_does_not_become_tapped():
    engine = game()
    host = filler(engine, "Host", type_line="Creature", player=OPPONENT, power=2, toughness=2)
    _aura_on(engine, "Insolence", host)
    host.tapped = True  # RULE 614.1: entering tapped is not a transition
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE


def test_impending_doom_hurts_the_dead_hosts_controller():
    engine = game()
    host = filler(engine, "Host", type_line="Creature", player=OPPONENT, power=1, toughness=1)
    _aura_on(engine, "Impending Doom", host)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert _player(engine, OPPONENT).life == STARTING_LIFE - 3
    assert _player(engine, ME).life == STARTING_LIFE


def test_darksteel_garrison_pumps_a_creature_when_the_fortified_land_taps():
    engine = game()
    land = filler(engine, "Fortified Land", type_line="Land")
    other_land = filler(engine, "Other Land", type_line="Land")
    target = filler(engine, "Target", type_line="Creature", power=1, toughness=1)
    _aura_on(engine, "Darksteel Garrison", land)
    engine.rules.set_tapped(other_land, True)  # near miss: an unfortified land
    engine.resolve_until_stable()
    answer(engine)
    assert _power(engine, target) == 1
    engine.rules.set_tapped(land, True)
    engine.resolve_until_stable()
    answer(engine)
    engine.resolve_until_stable()
    assert _power(engine, target) == 2


# ---------------------------------------------------------------- transforms

def _dfc(engine, name, player=ME):
    obj = card(engine, name, player)
    assert obj.card.has_back_face
    return obj


def _transform(engine, obj):
    assert engine.rules.transform_permanent(obj)
    engine.resolve_until_stable()


def test_cult_of_the_waxing_moon_makes_a_wolf_only_for_a_non_human_creature_face():
    engine = game()
    card(engine, "Cult of the Waxing Moon")
    agent = _dfc(engine, "Aetherblade Agent // Gitaxian Mindstinger")  # Human Rogue -> Phyrexian Rogue
    _transform(engine, agent)
    assert len(named(engine, "Wolf")) == 1
    # near miss: it transforms back into a Human
    _transform(engine, agent)
    assert len(named(engine, "Wolf")) == 1
    # near miss: an opponent's permanent transforms
    theirs = _dfc(engine, "Aetherblade Agent // Gitaxian Mindstinger", OPPONENT)
    _transform(engine, theirs)
    assert len(named(engine, "Wolf")) == 1


def test_norns_inquisitor_counters_only_a_permanent_that_becomes_a_phyrexian():
    engine = game()
    card(engine, "Norn's Inquisitor")
    werewolf = _dfc(engine, "Villagers of Estwald // Howlpack of Estwald")
    _transform(engine, werewolf)  # near miss: Human Werewolf -> Werewolf, no Phyrexian
    assert werewolf.counters.get("+1/+1", 0) == 0
    agent = _dfc(engine, "Aetherblade Agent // Gitaxian Mindstinger")
    _transform(engine, agent)
    assert agent.counters.get("+1/+1", 0) == 1  # "put a +1/+1 counter on it": the transformed permanent
    theirs = _dfc(engine, "Aetherblade Agent // Gitaxian Mindstinger", OPPONENT)
    _transform(engine, theirs)  # near miss: not mine
    assert theirs.counters.get("+1/+1", 0) == 0


# ---------------------------------------------------------------- 1 or more ... become tapped (batch)

def _merfolk(engine, name, token=False, player=ME):
    obj = filler(engine, name, type_line="Creature — Merfolk", player=player, power=1, toughness=1)
    obj.is_token = token
    return obj


def _tokens(engine):
    return [o for o in engine.state.battlefield if o.name == "Merfolk" and o.is_token]  # the created 1/1 tokens


def test_deeproot_pilgrimage_triggers_once_for_a_batch_of_two_merfolk():
    engine = game()
    card(engine, "Deeproot Pilgrimage")
    first, second = _merfolk(engine, "Merfolk A"), _merfolk(engine, "Merfolk B")
    attack(engine, [first, second])  # the declaration taps both at once
    assert first.tapped and second.tapped
    assert len(_tokens(engine)) == 1


def test_deeproot_pilgrimage_triggers_for_a_single_merfolk_and_for_a_tap_effect_each_time():
    engine = game()
    card(engine, "Deeproot Pilgrimage")
    merfolk = _merfolk(engine, "Merfolk A")
    engine.rules.set_tapped(merfolk, True)
    engine.resolve_until_stable()
    assert len(_tokens(engine)) == 1
    engine.rules.set_tapped(merfolk, False)
    engine.rules.set_tapped(merfolk, True)
    engine.resolve_until_stable()
    assert len(_tokens(engine)) == 2


def test_deeproot_pilgrimage_ignores_tokens_other_types_and_opponents_merfolk():
    engine = game()
    card(engine, "Deeproot Pilgrimage")
    token = _merfolk(engine, "Merfolk Token", token=True)
    human = filler(engine, "Human", type_line="Creature — Human", power=1, toughness=1)
    theirs = _merfolk(engine, "Their Merfolk", player=OPPONENT)
    for obj in (token, human, theirs):
        engine.rules.set_tapped(obj, True)
    engine.resolve_until_stable()
    assert _tokens(engine) == []  # no Merfolk token was created (the pre-existing one has another name)
