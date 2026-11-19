"""PAR-286 milestone 7: "when you discard this card" and "whenever a creature dealt damage this way dies this turn".

RULE 701.9 / 603.1: a card's own discard trigger fires from the graveyard it just landed in (cleanup, cost or effect
discard alike), never for another card and never when the card merely dies or is put in the graveyard some other way.
RULE 603.7c / 400.7: the turn-long trigger watches only the creatures the damage clause hit, in the battlefield visit
that was hit, and only until the turn ends.
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, cast, filler, game

#: Titanbones' printed life gain.
TITANBONES_LIFE = 3
#: Skeletonize's damage / the toughness that dies to it, and one that survives it.
SKELETONIZE_DAMAGE = 3
DIES_TOUGHNESS = 3
SURVIVES_TOUGHNESS = 5
#: Reckless Blaze damage; one body dies to it, one survives it.
BLAZE_DAMAGE = 5
BLAZE_DIES_TOUGHNESS = 2
BLAZE_SURVIVES_TOUGHNESS = 9
#: The mana cost of Reckless Blaze is {3}{R}{R}; a pool of exactly that leaves only what the trigger adds.
BLAZE_POOL = {"R": 2, "C": 3}


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


@pytest.mark.parametrize("name", [
    "Titanbones, Towering Heart", "Bartered Cow",
    "Ghired's Belligerence", "Reckless Blaze", "Skeletonize",
])
def test_cards_are_modeled_or_authored(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_discard_head_is_self_only():
    assert _segment("when you discard this card, you gain 3 life.").claimed
    # near misses: another card's discard is the existing "whenever you discard a card" family, not this head
    assert not _segment("when you discard this card, you gain 3 life. draw a card from nowhere.").claimed
    assert not _segment("when you discard that card, you gain 3 life.").claimed


def _life(engine, pid="p1"):
    return engine.state.player_by_id(pid).life


def _titanbones(engine):
    return card(engine, "Titanbones, Towering Heart", zone=Zone.HAND)


def test_titanbones_gains_life_when_discarded_by_an_effect_and_by_cleanup():
    engine = game()
    tb = _titanbones(engine)
    before = _life(engine)
    engine.rules.discard_specific(tb)
    engine.resolve_until_stable()
    assert tb.zone == Zone.GRAVEYARD
    assert _life(engine) == before + TITANBONES_LIFE


def test_titanbones_does_not_fire_for_other_discards_or_dying():
    engine = game()
    tb = _titanbones(engine)
    other = filler(engine, "Other", type_line="Creature", zone=Zone.HAND, power=1, toughness=1)
    before = _life(engine)
    engine.rules.discard_specific(other)          # near miss: a different card is discarded while Titanbones waits
    engine.resolve_until_stable()
    assert _life(engine) == before
    assert tb.zone == Zone.HAND
    # near miss: Titanbones on the battlefield dying is not a discard
    on_bf = card(engine, "Titanbones, Towering Heart")
    engine.rules.destroy(on_bf)
    engine.resolve_until_stable()
    assert _life(engine) == before


def _foods(engine, pid="p1"):
    return [o for o in engine.state.battlefield if o.name == "Food" and o.controller_id == pid]


def test_bartered_cow_makes_food_on_discard_and_on_death_only():
    engine = game()
    cow = card(engine, "Bartered Cow", zone=Zone.HAND)
    engine.rules.discard_specific(cow)
    engine.resolve_until_stable()
    assert len(_foods(engine)) == 1
    dying = card(engine, "Bartered Cow")
    engine.rules.destroy(dying)
    engine.resolve_until_stable()
    assert len(_foods(engine)) == 2
    bystander = filler(engine, "Bystander", type_line="Creature", power=1, toughness=1)
    engine.rules.destroy(bystander)               # near miss: another creature dying
    engine.resolve_until_stable()
    assert len(_foods(engine)) == 2


def _skeletons(engine):
    return [o for o in engine.state.battlefield if o.name == "Skeleton"]


def _skeletonize(engine, toughness=DIES_TOUGHNESS):
    victim = filler(engine, "Victim", type_line="Creature", player="p2", power=1, toughness=toughness)
    bystander = filler(engine, "Bystander", type_line="Creature", player="p2", power=1, toughness=SURVIVES_TOUGHNESS)
    spell = card(engine, "Skeletonize", zone=Zone.HAND)
    cast(engine, spell, targets=[victim])
    return victim, bystander


def test_skeletonize_fires_for_the_damaged_creature_dying_right_away():
    engine = game()
    victim, _ = _skeletonize(engine)
    assert victim.zone == Zone.GRAVEYARD
    assert len(_skeletons(engine)) == 1


def test_skeletonize_fires_when_the_damaged_creature_dies_later_this_turn_only():
    engine = game()
    victim, bystander = _skeletonize(engine, toughness=SURVIVES_TOUGHNESS)
    assert victim.zone == Zone.BATTLEFIELD and not _skeletons(engine)
    engine.rules.destroy(bystander)               # near miss: a creature the spell never damaged
    engine.resolve_until_stable()
    assert not _skeletons(engine)
    engine.rules.destroy(victim)                  # inside the window
    engine.resolve_until_stable()
    assert len(_skeletons(engine)) == 1


def test_skeletonize_does_not_fire_after_the_turn_ends():
    engine = game()
    victim, _ = _skeletonize(engine, toughness=SURVIVES_TOUGHNESS)
    engine.state.internal_turn.number += 1
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert not _skeletons(engine)


def test_skeletonize_ignores_the_creature_after_it_changed_zones():
    engine = game()
    victim, _ = _skeletonize(engine, toughness=SURVIVES_TOUGHNESS)
    hit_visit = victim.zone_incarnation
    owner = engine.state.player_by_id("p2")
    engine.rules.return_to_hand(victim)
    engine.resolve_until_stable()
    owner.hand[:] = [o for o in owner.hand if o is not victim]
    victim.zone = Zone.BATTLEFIELD                # RULE 400.7: it comes back as a new object
    engine.state.add_to_battlefield(victim)
    assert victim.zone_incarnation != hit_visit
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert not _skeletons(engine)


def test_skeletonize_trigger_survives_clone():
    engine = game()
    victim, _ = _skeletonize(engine, toughness=SURVIVES_TOUGHNESS)
    original = engine.state.turn_scoped_triggers[0]
    clone = copy.deepcopy(engine.state)
    cloned = clone.turn_scoped_triggers[0]
    assert cloned is not original
    assert original.dealt_damage_visits == {victim.instance_id: victim.zone_incarnation}
    assert cloned.dealt_damage_visits == original.dealt_damage_visits


def test_reckless_blaze_adds_mana_only_for_your_damaged_creatures():
    engine = game()
    mine = filler(engine, "Mine", type_line="Creature", power=1, toughness=BLAZE_DIES_TOUGHNESS)
    survivor = filler(engine, "Survivor", type_line="Creature", power=1, toughness=BLAZE_SURVIVES_TOUGHNESS)
    theirs = filler(engine, "Theirs", type_line="Creature", player="p2", power=1, toughness=BLAZE_DIES_TOUGHNESS)
    blaze = card(engine, "Reckless Blaze", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    cast(engine, blaze, pool=dict(BLAZE_POOL))
    assert mine.zone == Zone.GRAVEYARD and theirs.zone == Zone.GRAVEYARD and survivor.zone == Zone.BATTLEFIELD
    # exactly one {R}: for "a creature you control", not for the opponent's dying creature
    assert p1.mana_pool.pool.get("R", 0) == 1


def test_ghireds_belligerence_populates_for_a_divided_damage_victim_dying():
    engine = game()
    token = filler(engine, "Soldier", type_line="Creature", power=1, toughness=1)
    token.is_token = True
    weak = filler(engine, "Weak", type_line="Creature", player="p2", power=1, toughness=1)
    sturdy = filler(engine, "Sturdy", type_line="Creature", player="p2", power=1, toughness=SURVIVES_TOUGHNESS)
    spell = card(engine, "Ghired's Belligerence", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"R": 5, "C": 5})
    from tests.support.deck_batch import main_phase
    main_phase(engine)
    engine.cast_spell(p1, spell, targets=[weak, sturdy], x=2)
    engine.resolve_until_stable()
    assert weak.zone == Zone.GRAVEYARD and sturdy.zone == Zone.BATTLEFIELD
    soldiers = [o for o in engine.state.battlefield if o.name == "Soldier" and o.controller_id == "p1"]
    assert len(soldiers) == 2                     # populate copied the token once
    engine.rules.destroy(token)                   # near miss: a creature that was not dealt damage
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.name == "Soldier"]) == 1  # the destroyed token is gone and nothing was populated


#: Sigil of Myrkul needs this many creature cards in your graveyard when the reflexive trigger is put on the stack.
MYRKUL_THRESHOLD = 4


def _myrkul_board(graveyard_creatures):
    from tests.support.deck_batch import answer, step
    engine = game()
    p1 = engine.state.player_by_id("p1")
    sigil = card(engine, "Sigil of Myrkul")
    body = filler(engine, "Body", type_line="Creature", power=1, toughness=1)
    for i in range(graveyard_creatures):
        dead = filler(engine, f"Dead {i}", type_line="Creature", zone=Zone.GRAVEYARD, power=1, toughness=1)
        assert dead.zone == Zone.GRAVEYARD
    step(engine, "begin_combat")
    answer(engine)
    engine.resolve_until_stable()
    return engine, sigil, body


def test_sigil_of_myrkul_reflexive_payoff_needs_the_graveyard_condition():
    engine, _, body = _myrkul_board(MYRKUL_THRESHOLD)
    assert body.counters.get("+1/+1", 0) == 1
    engine.recompute_continuous_effects()
    assert "deathtouch" in {k.lower() for k in body.granted_keywords}


def test_sigil_of_myrkul_does_nothing_below_the_threshold():
    engine, _, body = _myrkul_board(MYRKUL_THRESHOLD - 1)
    assert body.counters.get("+1/+1", 0) == 0
