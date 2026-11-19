"""PAR-286 milestone 8: a reflexive "When you do" payoff that names the antecedent's object.

RULE 603.12: the payoff is a fresh trigger that exists only if the antecedent was actually carried out. RULE 608.2h /
400.7: its "it" is the object the antecedent made, returned or amassed -- in the zone visit it was in -- and a payoff
whose referent has since left the battlefield acts on nothing rather than on a different permanent.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, answer, card, cast, filler, game, main_phase, pick_label

#: Windmill Slam's printed token power (and so its damage).
WINDMILL_POWER = 4
#: Foray of Orcs amasses 2; one more counter already on an existing Army.
AMASS_COUNT = 2
EXISTING_ARMY_COUNTERS = 1
#: A toughness no fight here can kill, so damage marked is what is read.
SOAK_TOUGHNESS = 20
FIGHTER_POWER = 3
VICTIM_POWER = 1


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


@pytest.mark.parametrize("name", ["Windmill Slam", "Foray of Orcs", "Back for More", "Novel Nunchaku"])
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_pronoun_payoff_after_a_non_carrying_antecedent_stays_unclaimed():
    # a drawn card is nothing "it" can name; the payoff must not silently act on the source instead
    assert not _segment("draw a card. when you do, it deals 2 damage to target creature.").claimed
    assert _segment("create a 4/4 windmill artifact creature token with defender. when you do, it deals damage "
                    "equal to its power to any target.").claimed


def _bodies(engine):
    victim = filler(engine, "Victim", player="p2", power=VICTIM_POWER, toughness=SOAK_TOUGHNESS)
    bystander = filler(engine, "Bystander", player="p2", power=VICTIM_POWER, toughness=SOAK_TOUGHNESS)
    return victim, bystander


def test_windmill_slam_token_deals_its_power_to_the_chosen_target_only():
    engine = game()
    victim, bystander = _bodies(engine)
    cast(engine, card(engine, "Windmill Slam", zone=Zone.HAND))
    answer(engine, pick_label("Victim"))
    assert victim.damage_marked == WINDMILL_POWER
    assert bystander.damage_marked == 0            # near miss: the other creature is untouched


def test_foray_of_orcs_damage_is_the_amassed_armys_power():
    engine = game()
    victim, bystander = _bodies(engine)
    cast(engine, card(engine, "Foray of Orcs", zone=Zone.HAND))
    answer(engine, pick_label("Victim"))
    assert victim.damage_marked == AMASS_COUNT
    assert bystander.damage_marked == 0


def test_foray_of_orcs_reads_the_existing_army_it_found():
    engine = game()
    victim, bystander = _bodies(engine)
    army = filler(engine, "Army", type_line="Creature — Zombie Army", power=EXISTING_ARMY_COUNTERS, toughness=EXISTING_ARMY_COUNTERS)
    bystander_army = filler(engine, "Pawn", power=7, toughness=SOAK_TOUGHNESS)   # near miss: a bigger non-Army creature
    cast(engine, card(engine, "Foray of Orcs", zone=Zone.HAND))
    answer(engine, pick_label("Victim"))
    assert army.counters.get("+1/+1") == AMASS_COUNT
    assert victim.damage_marked == EXISTING_ARMY_COUNTERS + AMASS_COUNT
    assert bystander_army.damage_marked == 0


def _back_for_more(engine, dead):
    spell = card(engine, "Back for More", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[dead])
    return spell


def _resolve_spell(engine):
    engine.rules.resolve_top_of_stack()


def test_back_for_more_returned_creature_fights_the_chosen_creature():
    engine = game()
    victim, bystander = _bodies(engine)
    dead = filler(engine, "Dead", power=FIGHTER_POWER, toughness=SOAK_TOUGHNESS, zone=Zone.GRAVEYARD)
    mine = filler(engine, "Mine", power=9, toughness=SOAK_TOUGHNESS)   # near miss: a stronger creature already there
    _back_for_more(engine, dead)
    engine.resolve_until_stable()
    answer(engine, pick_label("Victim"))
    assert dead.zone == Zone.BATTLEFIELD
    assert victim.damage_marked == FIGHTER_POWER and dead.damage_marked == VICTIM_POWER
    assert mine.damage_marked == 0 and bystander.damage_marked == 0


def test_back_for_more_declining_the_fight_target_fights_nothing():
    engine = game()
    victim, bystander = _bodies(engine)
    dead = filler(engine, "Dead", power=FIGHTER_POWER, toughness=SOAK_TOUGHNESS, zone=Zone.GRAVEYARD)
    _back_for_more(engine, dead)
    engine.resolve_until_stable()
    answer(engine, pick_label("Nichts"))
    assert dead.zone == Zone.BATTLEFIELD
    assert victim.damage_marked == 0 and dead.damage_marked == 0


def test_back_for_more_does_not_trigger_when_the_return_did_not_happen():
    engine = game()
    victim, _ = _bodies(engine)
    dead = filler(engine, "Dead", power=FIGHTER_POWER, toughness=SOAK_TOUGHNESS, zone=Zone.GRAVEYARD)
    _back_for_more(engine, dead)
    owner = engine.state.player_by_id("p1")
    owner.zones[Zone.GRAVEYARD].remove(dead)       # the target is gone before the spell resolves (RULE 608.2b)
    dead.zone = Zone.EXILE
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert victim.damage_marked == 0
    assert dead.zone == Zone.EXILE and not engine.state.pending_ability_triggers


def test_back_for_more_referent_that_left_play_before_the_trigger_resolves_fights_nothing():
    engine = game()
    victim, _ = _bodies(engine)
    dead = filler(engine, "Dead", power=FIGHTER_POWER, toughness=SOAK_TOUGHNESS, zone=Zone.GRAVEYARD)
    _back_for_more(engine, dead)
    _resolve_spell(engine)
    assert engine.state.pending_ability_triggers                 # the reflexive trigger exists, not yet on the stack
    engine.rules.destroy(dead)                     # RULE 400.7: the returned creature is now a different object
    engine.resolve_until_stable()
    answer(engine, pick_label("Victim"))
    assert dead.zone == Zone.GRAVEYARD
    assert victim.damage_marked == 0


def test_carried_referent_survives_clone():
    engine = game()
    _bodies(engine)
    dead = filler(engine, "Dead", power=FIGHTER_POWER, toughness=SOAK_TOUGHNESS, zone=Zone.GRAVEYARD)
    _back_for_more(engine, dead)
    _resolve_spell(engine)
    original = engine.state.pending_ability_triggers[0][0].effects[0]
    clone = engine.state.clone()
    cloned = clone.pending_ability_triggers[0][0].effects[0]
    assert cloned is not original
    assert cloned.carried == [(clone.find_object(dead.instance_id), dead.zone_incarnation)]
    assert cloned.carried[0][0] is not dead         # a copy inside the cloned game, not the live object


def test_novel_nunchaku_equipped_creature_fights_after_the_attach():
    engine = game()
    victim, bystander = _bodies(engine)
    mine = filler(engine, "Mine", power=2, toughness=SOAK_TOUGHNESS)
    other_mine = filler(engine, "Other Mine", power=8, toughness=SOAK_TOUGHNESS)
    cast(engine, card(engine, "Novel Nunchaku", zone=Zone.HAND))
    answer(engine, pick_label("Mine"))
    answer(engine, pick_label("Victim"))
    nunchaku = next(o for o in engine.state.battlefield if o.name == "Novel Nunchaku")
    assert nunchaku.attached_to == mine.instance_id
    assert victim.damage_marked > 0 and mine.damage_marked == VICTIM_POWER
    assert other_mine.damage_marked == 0 and bystander.damage_marked == 0   # near miss: only the equipped one fights


def _windmill_token(engine):
    engine.state.pending_ability_triggers  # resolve the spell only; the reflexive trigger is still pending
    _resolve_spell(engine)
    return next(o for o in engine.state.battlefield if o.name == "Windmill")


def test_windmill_slam_token_removed_before_the_trigger_resolves_deals_its_last_known_power():
    engine = game()
    victim, bystander = _bodies(engine)
    spell = card(engine, "Windmill Slam", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell)
    token = _windmill_token(engine)
    assert engine.state.pending_ability_triggers
    engine.rules.destroy(token)                    # RULE 400.7: the token is gone before the payoff resolves
    assert token not in engine.state.battlefield
    engine.resolve_until_stable()
    answer(engine, pick_label("Victim"))
    assert victim.damage_marked == WINDMILL_POWER  # RULE 608.2h: last-known power, not nothing
    assert bystander.damage_marked == 0


def test_foray_of_orcs_army_removed_before_the_trigger_resolves_deals_its_last_known_power():
    engine = game()
    victim, bystander = _bodies(engine)
    army = filler(engine, "Army", type_line="Creature — Zombie Army", power=EXISTING_ARMY_COUNTERS, toughness=EXISTING_ARMY_COUNTERS)
    spell = card(engine, "Foray of Orcs", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell)
    _resolve_spell(engine)
    assert engine.state.pending_ability_triggers
    engine.rules.destroy(army)
    assert army not in engine.state.battlefield
    engine.resolve_until_stable()
    answer(engine, pick_label("Victim"))
    assert victim.damage_marked == EXISTING_ARMY_COUNTERS + AMASS_COUNT   # last-known power, counters included
    assert bystander.damage_marked == 0
