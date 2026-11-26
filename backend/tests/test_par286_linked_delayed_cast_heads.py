"""PAR-286 milestone 11: linked "that creature" heads, delayed-step heads and qualified cast / counter heads.

Every behaviour test drives the real engine event on the real card and pairs it with a near miss that must not fire.
RULE 603.7 delayed abilities fire only inside their window (the test also checks just outside it).
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, activate, answer, attack, card, cast, filler, game, main_phase, step

NEWLY_COVERED = [
    # linked "that creature" heads
    "Desperate Measures", "Trophy Hunter", "Glyph of Life", "Captain Howler, Sea Scourge", "Maeve, Insidious Singer",
    # delayed-step heads
    "Last Chance", "Warrior's Oath", "Intervention of Keranos", "Vivien's Stampede", "Archivist of Gondor",
    # qualified cast / counter heads
    "Brimaz, Blight of Oreskos", "Mindsparker", "Runescale Stormbrood // Chilling Screech", "Pyromancer Ascension",
    "Dovin's Acuity", "Lullmage Mentor", "Multani's Presence", "Kalamax, the Stormsire", "Saproling Infestation",
]


def _segment(text, spell=True):
    return segment_line(text, allow_spell_effect=spell, provenance=ParserProvenance())


def _hand(engine, pid="p1"):
    return len(engine.state.player_by_id(pid).hand)


def _life(engine, pid="p1"):
    return engine.state.player_by_id(pid).life


def _next_turn(engine):
    engine.state.internal_turn.number += 1


@pytest.mark.parametrize("name", NEWLY_COVERED)
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


# --- linked "that creature" heads ---------------------------------------------------------------------------------

#: Desperate Measures: "+1/-1" kills a 1-toughness creature; it draws two cards.
MEASURES_DRAW = 2


def _measures(engine, owner, toughness=1):
    victim = filler(engine, "Victim", type_line="Creature", player=owner, power=1, toughness=toughness)
    spell = card(engine, "Desperate Measures", zone=Zone.HAND)
    cast(engine, spell, targets=[victim])
    return victim


def test_desperate_measures_draws_when_your_creature_dies():
    engine = game()
    before = _hand(engine)
    victim = _measures(engine, "p1")
    assert victim.zone == Zone.GRAVEYARD
    assert _hand(engine) == before + MEASURES_DRAW


def test_desperate_measures_near_misses_do_not_draw():
    engine = game()
    before = _hand(engine)
    victim = _measures(engine, "p2")                 # dies under the opponent's control
    assert victim.zone == Zone.GRAVEYARD
    assert _hand(engine) == before
    engine = game()
    victim = _measures(engine, "p1", toughness=5)    # survives, so nothing died yet
    other = filler(engine, "Other", type_line="Creature", power=1, toughness=1)
    before = _hand(engine)
    engine.rules.destroy(other)                      # another creature dying: not "it"
    engine.resolve_until_stable()
    assert _hand(engine) == before
    _next_turn(engine)                               # outside "this turn"
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert _hand(engine) == before


def test_desperate_measures_dies_under_your_control_uses_the_last_controller():
    engine = game()
    victim = _measures(engine, "p1", toughness=5)
    victim.controller_id = "p2"                      # control changed before it died (RULE 700.4)
    before = _hand(engine)
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert _hand(engine) == before


def _trophy_hunter(engine):
    hunter = card(engine, "Trophy Hunter")
    flier = filler(engine, "Flier", type_line="Creature", player="p2", power=1, toughness=2, keywords=["Flying"])
    ground = filler(engine, "Ground", type_line="Creature", player="p2", power=1, toughness=2)
    engine.recompute_continuous_effects()
    return hunter, flier, ground


def test_trophy_hunter_grows_only_for_a_flier_it_damaged_this_turn():
    engine = game()
    hunter, flier, ground = _trophy_hunter(engine)
    engine.rules.deal_damage(ground, 2, source=hunter)       # a non-flier it damaged
    engine.rules.deal_damage(flier, 1, source=hunter)
    engine.resolve_until_stable()
    assert ground.zone == Zone.GRAVEYARD and hunter.counters.get("+1/+1", 0) == 0
    engine.rules.deal_damage(flier, 1, source=hunter)        # now lethal
    engine.resolve_until_stable()
    assert flier.zone == Zone.GRAVEYARD
    assert hunter.counters.get("+1/+1", 0) == 1


def test_trophy_hunter_ignores_a_flier_it_did_not_damage_and_a_later_turn():
    engine = game()
    hunter, flier, _ = _trophy_hunter(engine)
    engine.rules.destroy(flier)                              # never damaged by the Hunter
    engine.resolve_until_stable()
    assert hunter.counters.get("+1/+1", 0) == 0
    engine = game()
    hunter, flier, _ = _trophy_hunter(engine)
    engine.rules.deal_damage(flier, 1, source=hunter)
    _next_turn(engine)
    engine.rules.destroy(flier)
    engine.resolve_until_stable()
    assert hunter.counters.get("+1/+1", 0) == 0


def _glyph(engine):
    wall = filler(engine, "Wall of Test", type_line="Creature — Wall", power=0, toughness=9)
    other = filler(engine, "Other", type_line="Creature", power=0, toughness=9)
    attacker = filler(engine, "Attacker", type_line="Creature", player="p2", power=3, toughness=3)
    spell = card(engine, "Glyph of Life", zone=Zone.HAND)
    cast(engine, spell, targets=[wall])
    return wall, other, attacker


def test_glyph_of_life_gains_life_for_damage_from_an_attacking_creature_only():
    engine = game()
    wall, other, attacker = _glyph(engine)
    before = _life(engine)
    engine.rules.deal_damage(wall, 3, source=attacker, combat=False)      # not attacking: near miss
    engine.resolve_until_stable()
    assert _life(engine) == before
    attacker.attacking = True
    engine.rules.deal_damage(other, 3, source=attacker, combat=True)      # a different creature: near miss
    engine.resolve_until_stable()
    assert _life(engine) == before
    engine.rules.deal_damage(wall, 3, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert _life(engine) == before + 3                                    # "that much life"


def test_glyph_of_life_ends_with_the_turn():
    engine = game()
    wall, _, attacker = _glyph(engine)
    attacker.attacking = True
    _next_turn(engine)
    before = _life(engine)
    engine.rules.deal_damage(wall, 3, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert _life(engine) == before


def test_glyph_of_life_trigger_survives_clone():
    engine = game()
    wall, _, _ = _glyph(engine)
    clone = copy.deepcopy(engine.state)
    cloned, original = clone.turn_scoped_triggers[0], engine.state.turn_scoped_triggers[0]
    assert cloned is not original
    assert (cloned.bound_object_id, cloned.bound_incarnation) == (wall.instance_id, wall.zone_incarnation)
    assert original.ends_when_object_moves is True


def _howler(engine):
    howler = card(engine, "Captain Howler, Sea Scourge")
    chosen = filler(engine, "Chosen", type_line="Creature", power=1, toughness=5)
    other = filler(engine, "Other", type_line="Creature", power=1, toughness=5)
    discarded = filler(engine, "Discarded", type_line="Creature", zone=Zone.HAND)
    discarded2 = filler(engine, "Discarded Too", type_line="Creature", zone=Zone.HAND)
    return howler, chosen, other, [discarded, discarded2]


def test_howler_pumps_per_discarded_card_and_draws_when_that_creature_hits_a_player():
    engine = game()
    _, chosen, other, cards = _howler(engine)
    engine.rules.discard(engine.state.player_by_id("p1"), 1)
    engine.resolve_until_stable()
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if o.get("label") == "Chosen"), None))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert chosen.power == 1 + 2                                          # +2/+0 for the one card discarded
    before = _hand(engine)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=other, combat=True)
    engine.resolve_until_stable()
    assert _hand(engine) == before                                        # another creature: near miss
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=chosen, combat=False)
    engine.resolve_until_stable()
    assert _hand(engine) == before                                        # noncombat damage: near miss
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=chosen, combat=True)
    engine.resolve_until_stable()
    assert _hand(engine) == before + 1


def test_howler_batch_counts_every_card_of_one_discard():
    engine = game()
    _, chosen, _, cards = _howler(engine)
    engine.rules.discard(engine.state.player_by_id("p1"), 2)
    engine.resolve_until_stable()
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if o.get("label") == "Chosen"), None))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert chosen.power == 1 + 2 * 2                                      # +2/+0 for each of the two cards


def _maeve_attack(attacker_name, defender_id):
    """Maeve goads one of p2's creatures; p2 attacks ``defender_id`` with ``attacker_name``. Returns p1's cards drawn."""
    engine = game(players=3)
    maeve = card(engine, "Maeve, Insidious Singer")
    goaded = filler(engine, "Goaded", type_line="Creature", player="p2", power=2, toughness=2)
    other = filler(engine, "Other", type_line="Creature", player="p2", power=2, toughness=2)
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(engine, maeve, targets=[goaded])
    assert len(engine.state.turn_scoped_triggers) == 1
    engine.state.active_player_index = 1
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    p2 = engine.state.player_by_id("p2")
    defenders = {d["id"]: d for d in engine.legal_defenders_for(p2) if d["kind"] == "player"}
    before = _hand(engine)
    attacker = goaded if attacker_name == "Goaded" else other
    engine.declare_attackers(p2, [{"attacker": attacker, "defender": defenders[defender_id]}])
    engine.resolve_until_stable()
    return _hand(engine) - before


def test_maeve_draws_when_the_goaded_creature_attacks_an_opponent_of_yours():
    assert _maeve_attack("Goaded", "p3") == 1


def test_maeve_near_misses_do_not_draw():
    assert _maeve_attack("Goaded", "p1") == 0     # attacks Maeve's controller: not "one of your opponents"
    assert _maeve_attack("Other", "p3") == 0      # a creature that was not goaded


def test_that_creature_heads_need_a_chosen_creature():
    ok = "goad target creature. whenever that creature attacks 1 of your opponents this turn, draw a card."
    assert _segment(ok).claimed
    assert not _segment("whenever that creature attacks 1 of your opponents this turn, draw a card.").claimed
    assert not _segment("goad target creature. whenever that creature attacks 3 of your opponents this turn, draw a card.").claimed
    assert not _segment("choose target creature. whenever that creature is dealt damage by a blocking creature this turn, you gain that much life.").claimed


# --- spec changes of already-MODELED cards: "X counters on target creature. It gains ..." -----------------------------
# The bind that measures X no longer swallows the following "that creature / it / they gain" clause (a measured clause
# whose inner effect picked a creature now announces it, `announces_creature_target`); these execute the six cards.


def _creature_with_flying_or_trample(engine, name):
    return filler(engine, name, type_line="Creature", power=1, toughness=1)


def test_flame_on_counters_then_flying_on_the_same_creature():
    engine = game()
    target = _creature_with_flying_or_trample(engine, "Target")
    for i in range(3):
        filler(engine, f"Spell {i}", type_line="Instant", zone=Zone.GRAVEYARD)
    cast(engine, card(engine, "Flame On!", zone=Zone.HAND, without=True), targets=[target])
    engine.recompute_continuous_effects()
    assert target.counters.get("+1/+1", 0) == 3
    assert "flying" in {k.lower() for k in target.granted_keywords}


def test_infuse_with_the_elements_counters_then_trample():
    engine = game()
    target = _creature_with_flying_or_trample(engine, "Target")
    other = _creature_with_flying_or_trample(engine, "Other")
    cast(engine, card(engine, "Infuse with the Elements", zone=Zone.HAND), pool={"G": 1, "C": 3}, targets=[target])
    engine.recompute_continuous_effects()
    assert target.counters.get("+1/+1", 0) >= 1
    assert "trample" in {k.lower() for k in target.granted_keywords}
    assert "trample" not in {k.lower() for k in other.granted_keywords}


def test_ajani_ultimate_counters_by_life_then_trample():
    engine = game()
    target = _creature_with_flying_or_trample(engine, "Target")
    ajani = card(engine, "Ajani, Valiant Protector")
    ajani.counters["loyalty"] = 11
    activate(engine, ajani, 2, targets=[target])
    engine.recompute_continuous_effects()
    assert target.counters.get("+1/+1", 0) == _life(engine)
    assert "trample" in {k.lower() for k in target.granted_keywords}


def test_halana_and_alena_counters_equal_power_then_haste():
    engine = game()
    halana = card(engine, "Halana and Alena, Partners")
    target = _creature_with_flying_or_trample(engine, "Target")
    engine.recompute_continuous_effects()
    power = halana.power
    step(engine, "begin_combat")
    answer(engine)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert target.counters.get("+1/+1", 0) == power
    assert "haste" in {k.lower() for k in target.granted_keywords}
    assert halana.counters.get("+1/+1", 0) == 0                          # "another target creature"


def test_ovika_tokens_gain_haste():
    engine = game()
    card(engine, "Ovika, Enigma Goliath")
    spell = filler(engine, "Bolt", type_line="Instant", mv=3, zone=Zone.HAND)
    cast(engine, spell)
    engine.recompute_continuous_effects()
    goblins = [o for o in engine.state.battlefield if o.name == "Phyrexian Goblin"]
    assert len(goblins) == 3
    assert all("haste" in {k.lower() for k in g.granted_keywords} for g in goblins)


def test_rionya_copies_gain_haste():
    from mtg_analyzer.game import combat

    engine = game()
    card(engine, "Rionya, Fire Dancer")
    target = filler(engine, "Original", type_line="Creature", power=2, toughness=2)
    cast(engine, filler(engine, "Bolt", type_line="Instant", zone=Zone.HAND))
    step(engine, "begin_combat")
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if o.get("label") == "Original"), None))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    copies = [o for o in engine.state.battlefield if o.name == "Original" and o is not target]
    assert len(copies) >= 1
    assert all(combat.has(c, "haste") for c in copies)
    assert not combat.has(target, "haste")


# --- delayed-step heads --------------------------------------------------------------------------------------------


def _lost(engine, pid="p1"):
    return engine.state.player_by_id(pid).has_lost


@pytest.mark.parametrize("name", ["Last Chance", "Warrior's Oath", "Final Fortune"])  # Final Fortune: authored, now also parser-MODELED
def test_extra_turn_card_loses_the_game_at_the_extra_turns_end_step_only(name):
    engine = game()
    cast(engine, card(engine, name, zone=Zone.HAND))
    assert len(engine.state.delayed_triggers) == 1
    step(engine, "end")                                   # this turn's own end step: not "that turn's"
    assert not _lost(engine) and len(engine.state.delayed_triggers) == 1
    _next_turn(engine)                                    # the extra turn
    step(engine, "upkeep")
    assert not _lost(engine)                              # not an end step
    step(engine, "end")
    assert _lost(engine)


def test_extra_turn_delayed_trigger_survives_clone():
    engine = game()
    cast(engine, card(engine, "Last Chance", zone=Zone.HAND))
    original = engine.state.delayed_triggers[0]
    cloned = copy.deepcopy(engine.state).delayed_triggers[0]
    assert cloned is not original and cloned.min_turn == original.min_turn == engine.state.internal_turn.number + 1


def _creature(engine, name, toughness, player="p1"):
    return filler(engine, name, type_line="Creature", player=player, power=1, toughness=toughness)


#: Intervention of Keranos' damage to each creature.
KERANOS_DAMAGE = 3


def test_intervention_of_keranos_damages_every_creature_at_the_beginning_of_combat():
    engine = game()
    weak = _creature(engine, "Weak", KERANOS_DAMAGE)
    strong = _creature(engine, "Strong", KERANOS_DAMAGE + 1, player="p2")
    cast(engine, card(engine, "Intervention of Keranos", zone=Zone.HAND))
    assert weak.zone == Zone.BATTLEFIELD                  # nothing happens until combat
    step(engine, "begin_combat")
    assert weak.zone == Zone.GRAVEYARD and strong.zone == Zone.BATTLEFIELD
    assert strong.damage_marked == KERANOS_DAMAGE
    step(engine, "begin_combat")                          # a single beginning of combat only
    assert strong.damage_marked == KERANOS_DAMAGE


def test_intervention_of_keranos_expires_with_the_turn():
    engine = game()
    victim = _creature(engine, "Victim", KERANOS_DAMAGE)
    cast(engine, card(engine, "Intervention of Keranos", zone=Zone.HAND))
    _next_turn(engine)                                    # RULE 603.7b: "this turn" is over
    step(engine, "begin_combat")
    assert victim.zone == Zone.BATTLEFIELD and not engine.state.delayed_triggers


def test_vivien_stampede_draws_for_each_player_dealt_combat_damage_at_the_next_main_phase():
    engine = game(players=3)
    source = _creature(engine, "Hitter", 3)
    cast(engine, card(engine, "Vivien's Stampede", zone=Zone.HAND))
    p2, p3 = engine.state.player_by_id("p2"), engine.state.player_by_id("p3")
    engine.rules.deal_damage(p2, 1, source=source, combat=True)
    engine.rules.deal_damage(p3, 1, source=source, combat=False)      # noncombat: not counted
    before = _hand(engine)
    step(engine, "begin_combat")
    assert _hand(engine) == before                                    # not a main phase
    step(engine, "main2")
    assert _hand(engine) == before + 1
    step(engine, "main2")                                              # one-shot
    assert _hand(engine) == before + 1


def test_vivien_stampede_expires_with_the_turn():
    engine = game()
    cast(engine, card(engine, "Vivien's Stampede", zone=Zone.HAND))
    _next_turn(engine)
    before = _hand(engine)
    step(engine, "main1")
    assert _hand(engine) == before and not engine.state.delayed_triggers


def test_delayed_step_line_needs_a_spell():
    assert _segment("at the beginning of the next main phase this turn, draw a card.").claimed
    assert not _segment("at the beginning of the next main phase this turn, draw a card.", spell=False).claimed
    assert not _segment("at the beginning of the next main phase of some turn, draw a card.").claimed


def test_archivist_of_gondor_draws_at_the_monarchs_own_end_step():
    engine = game()
    card(engine, "Archivist of Gondor")
    engine.state.monarch_id = "p2"
    base_p1, base_p2 = _hand(engine, "p1"), _hand(engine, "p2")
    step(engine, "end", player="p1")                      # p1's turn: p2 is the monarch, not the active player
    assert (_hand(engine, "p1"), _hand(engine, "p2")) == (base_p1, base_p2)
    engine.state.active_player_index = 1
    step(engine, "end", player="p2")
    # the monarch's own RULE 724.2 draw plus the Archivist's extra one; the other player draws nothing
    assert (_hand(engine, "p1"), _hand(engine, "p2")) == (base_p1, base_p2 + 2)
    engine.state.monarch_id = None                        # no monarch: nobody
    step(engine, "end", player="p2")
    assert _hand(engine, "p2") == base_p2 + 2


# --- qualified cast / counter heads --------------------------------------------------------------------------------


def _cast_for(engine, name, player, targets=None, zone=Zone.HAND, **kw):
    """``player`` casts the real card ``name`` (resolved); returns the object."""
    obj = card(engine, name, player=player, zone=zone)
    cast(engine, obj, targets=targets, **kw)
    answer(engine)                                         # Opt's own scry choice, if any
    return obj


#: Mindsparker's damage to the caster.
MINDSPARKER_DAMAGE = 2


def test_mindsparker_hurts_an_opponent_who_casts_a_white_or_blue_instant_or_sorcery():
    engine = game()
    card(engine, "Mindsparker")
    before = _life(engine, "p2")
    _cast_for(engine, "Opt", "p2")                                            # blue instant
    assert _life(engine, "p2") == before - MINDSPARKER_DAMAGE
    _cast_for(engine, "Lightning Bolt", "p2", targets=[engine.state.player_by_id("p1")])   # red: near miss
    assert _life(engine, "p2") == before - MINDSPARKER_DAMAGE
    engine.state.active_player_index = 1                                      # creature spells need their sorcery timing
    _cast_for(engine, "Looter il-Kor", "p2")                                  # blue creature: near miss
    assert _life(engine, "p2") == before - MINDSPARKER_DAMAGE
    mine = _life(engine, "p1")
    engine.state.active_player_index = 0
    _cast_for(engine, "Opt", "p1")                                            # your own spell: near miss
    assert _life(engine, "p1") == mine and _life(engine, "p2") == before - MINDSPARKER_DAMAGE


def _stormbrood(engine):
    return card(engine, "Runescale Stormbrood // Chilling Screech")


def test_runescale_stormbrood_pumps_for_a_noncreature_or_a_dragon_spell_only():
    engine = game()
    brood = _stormbrood(engine)
    engine.recompute_continuous_effects()
    base = brood.power
    cast(engine, card(engine, "Opt", zone=Zone.HAND))                         # noncreature
    answer(engine)
    engine.recompute_continuous_effects()
    assert brood.power == base + 2
    cast(engine, filler(engine, "Elf", type_line="Creature — Elf", zone=Zone.HAND))   # near miss: a plain creature
    engine.recompute_continuous_effects()
    assert brood.power == base + 2
    cast(engine, filler(engine, "Drake", type_line="Creature — Dragon", zone=Zone.HAND))
    engine.recompute_continuous_effects()
    assert brood.power == base + 4


def test_spell_union_head_needs_both_sides_to_be_plain_spell_phrases():
    assert _segment("whenever you cast a noncreature spell or a dragon spell, ~ gets +2/+0 until end of turn.",
                    spell=False).claimed
    assert not _segment("whenever you cast a noncreature spell or a dragon spell from your graveyard, ~ gets +2/+0 until end of turn.",
                        spell=False).claimed
    assert not _segment("whenever you cast a noncreature spell or a dragon, ~ gets +2/+0 until end of turn.",
                        spell=False).claimed


def test_brimaz_incubates_for_a_phyrexian_creature_or_an_artifact_creature_spell():
    engine = game()
    card(engine, "Brimaz, Blight of Oreskos")
    incubators = lambda: [o for o in engine.state.battlefield if o.name == "Incubator"]
    cast(engine, filler(engine, "Plain", type_line="Creature — Elf", mv=2, zone=Zone.HAND))   # near miss
    assert not incubators()
    cast(engine, filler(engine, "Golem", type_line="Artifact Creature — Golem", mv=3, zone=Zone.HAND))
    assert len(incubators()) == 1 and incubators()[0].counters.get("+1/+1", 0) == 3            # X = that spell's value
    cast(engine, filler(engine, "Praetor", type_line="Creature — Phyrexian Horror", mv=4, zone=Zone.HAND))
    assert sorted(o.counters.get("+1/+1", 0) for o in incubators()) == [3, 4]
    cast(engine, filler(engine, "Trinket", type_line="Artifact", mv=1, zone=Zone.HAND))        # an artifact, not a creature
    assert len(incubators()) == 2


def test_pyromancer_ascension_counts_only_a_same_named_spell():
    engine = game()
    ascension = card(engine, "Pyromancer Ascension")
    card(engine, "Opt", zone=Zone.GRAVEYARD)
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[engine.state.player_by_id("p2")])
    answer(engine)
    assert ascension.counters.get("quest", 0) == 0                                              # a different name
    cast(engine, card(engine, "Opt", zone=Zone.HAND))
    answer(engine)
    assert ascension.counters.get("quest", 0) == 1


def test_dovin_acuity_offers_the_return_only_for_an_instant_in_your_main_phase():
    engine = game()
    acuity = card(engine, "Dovin's Acuity")
    cast(engine, card(engine, "Opt", zone=Zone.HAND))                                           # your main phase
    assert engine.state.pending_choice is not None and engine.state.pending_choice["options"][0]["id"] == "do"
    engine.resolve_pending_choice("do")
    engine.resolve_until_stable()
    assert acuity.zone == Zone.HAND
    engine = game()
    acuity = card(engine, "Dovin's Acuity")
    sorcery = filler(engine, "Sorcery", type_line="Sorcery", zone=Zone.HAND)
    cast(engine, sorcery)                                                                       # near miss: a sorcery
    answer(engine)
    assert engine.state.pending_choice is None and acuity.zone == Zone.BATTLEFIELD
    opt = card(engine, "Opt", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many(RICH)
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.cast_spell(p1, opt)                                                                  # near miss: during combat
    engine.resolve_until_stable()
    answer(engine)                                                                              # Opt's own scry
    assert engine.state.pending_choice is None and acuity.zone == Zone.BATTLEFIELD
    engine.state.active_player_index = 1
    main_phase(engine)
    other = card(engine, "Opt", zone=Zone.HAND)
    p1.mana_pool.add_many(RICH)
    engine.cast_spell(p1, other)                                                                # near miss: their main phase
    engine.resolve_until_stable()
    answer(engine)
    assert engine.state.pending_choice is None and acuity.zone == Zone.BATTLEFIELD


def _counter_setup(countering_player):
    """p2 casts Opt; ``countering_player`` counters it with a real Counterspell. Returns the engine."""
    engine = game()
    card(engine, "Lullmage Mentor")
    card(engine, "Multani's Presence")
    spell_owner = "p2"
    opt = card(engine, "Opt", player=spell_owner, zone=Zone.HAND)
    main_phase(engine)
    engine.state.player_by_id(spell_owner).mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id(spell_owner), opt)
    counter = card(engine, "Counterspell", player=countering_player, zone=Zone.HAND)
    engine.state.player_by_id(countering_player).mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id(countering_player), counter, targets=[opt])
    engine.resolve_until_stable()
    return engine, opt


def _merfolk(engine):
    return [o for o in engine.state.battlefield if o.name == "Merfolk"]


def test_lullmage_mentor_makes_a_merfolk_when_your_spell_counters():
    engine, opt = _counter_setup("p1")
    assert opt.zone == Zone.GRAVEYARD
    answer(engine)                                         # "you may": accept
    engine.resolve_until_stable()
    assert len(_merfolk(engine)) == 1


def test_lullmage_mentor_ignores_a_spell_the_opponent_countered():
    engine = game()
    card(engine, "Lullmage Mentor")
    mine = card(engine, "Opt", zone=Zone.HAND)
    main_phase(engine)
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p1"), mine)
    counter = card(engine, "Counterspell", player="p2", zone=Zone.HAND)
    engine.state.player_by_id("p2").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p2"), counter, targets=[mine])
    engine.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD
    assert engine.state.pending_choice is None and not _merfolk(engine)


def test_multanis_presence_draws_when_a_spell_you_cast_is_countered_by_anyone():
    engine = game()
    card(engine, "Multani's Presence")
    mine = card(engine, "Opt", zone=Zone.HAND)
    main_phase(engine)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many(RICH)
    engine.cast_spell(p1, mine)
    counter = card(engine, "Counterspell", player="p2", zone=Zone.HAND)
    engine.state.player_by_id("p2").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p2"), counter, targets=[mine])
    before = _hand(engine)
    engine.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD
    assert _hand(engine) == before + 1


def test_multanis_presence_ignores_an_opponents_countered_spell():
    engine = game()
    card(engine, "Multani's Presence")
    theirs = card(engine, "Opt", player="p2", zone=Zone.HAND)
    main_phase(engine)
    engine.state.player_by_id("p2").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p2"), theirs)
    counter = card(engine, "Counterspell", zone=Zone.HAND)
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p1"), counter, targets=[theirs])
    before = _hand(engine)                                 # the Counterspell has left the hand
    engine.resolve_until_stable()
    assert theirs.zone == Zone.GRAVEYARD                   # the opponent's spell really was countered
    assert _hand(engine) == before


def test_kalamax_counts_only_copies_of_instant_spells():
    engine = game()
    kalamax = card(engine, "Kalamax, the Stormsire")
    kalamax.tapped = True
    cast(engine, card(engine, "Opt", zone=Zone.HAND))      # first instant this turn with Kalamax tapped: copied
    answer(engine)
    assert kalamax.counters.get("+1/+1", 0) == 1


def test_kalamax_ignores_a_copied_sorcery_and_an_opponents_copy():
    engine = game()
    kalamax = card(engine, "Kalamax, the Stormsire")
    sorcery = filler(engine, "Sorcery", type_line="Sorcery", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    main_phase(engine)
    p1.mana_pool.add_many(RICH)
    engine.cast_spell(p1, sorcery)
    assert sorcery.zone == Zone.STACK
    engine.rules.copy_spell(sorcery, "p1")                 # a copy of a sorcery spell
    engine.resolve_until_stable()
    answer(engine)
    assert kalamax.counters.get("+1/+1", 0) == 0
    instant = card(engine, "Opt", player="p2", zone=Zone.HAND)
    engine.state.player_by_id("p2").mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.player_by_id("p2"), instant)
    engine.rules.copy_spell(instant, "p2")                 # "you copy": the opponent's copy is not yours
    engine.resolve_until_stable()
    answer(engine)
    assert kalamax.counters.get("+1/+1", 0) == 0


def test_saproling_infestation_makes_a_saproling_for_any_kicked_spell():
    engine = game()
    card(engine, "Saproling Infestation")
    saprolings = lambda: [o for o in engine.state.battlefield if o.name == "Saproling"]
    target = engine.state.player_by_id("p2")
    cast(engine, card(engine, "Burst Lightning", zone=Zone.HAND), targets=[target])            # not kicked: near miss
    assert not saprolings()
    cast(engine, card(engine, "Burst Lightning", zone=Zone.HAND), targets=[target], kicked=1)
    assert len(saprolings()) == 1
    cast(engine, card(engine, "Burst Lightning", player="p2", zone=Zone.HAND), targets=[engine.state.player_by_id("p1")], kicked=1)
    assert len(saprolings()) == 2                                                              # "a player kicks a spell"


def test_cast_head_phrases_fail_closed_when_unrecognised():
    assert not _segment("whenever you cast a noncreature spell or a, ~ gets +2/+0 until end of turn.", spell=False).claimed
    assert not _segment("whenever a player kicks, you create a 1/1 green saproling creature token.", spell=False).claimed
    assert not _segment("whenever you copy a spell from exile, you gain 1 life.", spell=False).claimed


# --- incidentally claimed cards: whole-card execution -------------------------------------------------------------
# M11's shared work (the linked "that creature would die this turn" and the spell-restriction clauses) also made these
# eight cards MODELED. Each runs on the real engine with a near miss, checking the whole card, not the claimed clause.

INCIDENTAL = [
    "Blitz of the Thunder-Raptor", "Bouncer's Beatdown", "Combustion Technique",
    "Magistrate's Veto", "Necrotic Wound", "Spoils of the Hunt", "Temple Thief",
]


@pytest.mark.parametrize("name", INCIDENTAL)
def test_incidental_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _gy(engine, count, type_line, player="p1", name="Gy", **kw):
    for i in range(count):
        filler(engine, f"{name}{i}", type_line=type_line, player=player, zone=Zone.GRAVEYARD, **kw)


def _cast_at(engine, name, victim, pool=RICH, **kw):
    spell = card(engine, name, zone=Zone.HAND)
    cast(engine, spell, pool=pool, targets=[victim], **kw)
    return spell


def test_blitz_counts_instants_and_sorceries_only_and_exiles_a_lethal_target():
    engine = game()
    _gy(engine, 2, "Instant", name="I")
    _gy(engine, 1, "Creature", name="C", power=1, toughness=1)           # not an instant or sorcery
    big = _creature(engine, "Big", 3, "p2")
    _cast_at(engine, "Blitz of the Thunder-Raptor", big)
    assert big.zone == Zone.BATTLEFIELD and big.damage_marked == 2        # 2 damage, creature card not counted
    engine = game()
    _gy(engine, 2, "Sorcery", name="S")
    small = _creature(engine, "Small", 2, "p2")
    _cast_at(engine, "Blitz of the Thunder-Raptor", small)
    assert small.zone == Zone.EXILE                                       # lethal damage: exiled, not buried


def test_blitz_exile_replacement_ends_with_the_turn():
    engine = game()
    _gy(engine, 1, "Instant")
    target = _creature(engine, "Target", 3, "p2")
    _cast_at(engine, "Blitz of the Thunder-Raptor", target)
    _next_turn(engine)
    engine.rules.destroy(target)
    engine.resolve_until_stable()
    assert target.zone == Zone.GRAVEYARD


def test_blitz_exile_replacement_is_only_for_its_target():
    engine = game()
    _gy(engine, 1, "Instant")
    target = _creature(engine, "Target", 3, "p2")
    other = _creature(engine, "Other", 1, "p2")
    _cast_at(engine, "Blitz of the Thunder-Raptor", target)
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert other.zone == Zone.GRAVEYARD


def test_bouncers_beatdown_uses_the_greatest_power_and_exiles():
    engine = game()
    filler(engine, "Small", power=1, toughness=1)
    filler(engine, "Large", power=4, toughness=4)
    victim = _creature(engine, "Victim", 4, "p2")
    _cast_at(engine, "Bouncer's Beatdown", victim)
    assert victim.zone == Zone.EXILE
    engine = game()
    filler(engine, "Small", power=1, toughness=1)
    filler(engine, "Large", power=4, toughness=4)
    survivor = _creature(engine, "Survivor", 5, "p2")                     # 4 damage is not lethal
    _cast_at(engine, "Bouncer's Beatdown", survivor)
    assert survivor.zone == Zone.BATTLEFIELD and survivor.damage_marked == 4


def _black_creature(engine, toughness, player="p2"):
    return filler(engine, "Blackie", player=player, power=1, toughness=toughness, mv=1, mana_cost_string="{B}")


def test_bouncers_beatdown_costs_two_less_only_for_a_black_target():
    engine = game()
    filler(engine, "Large", power=4, toughness=4)
    black = _black_creature(engine, 4)
    spell = card(engine, "Bouncer's Beatdown", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    main_phase(engine)
    p1.mana_pool.add("G", 1)                                              # {G} only: legal only with the discount
    engine.cast_spell(p1, spell, targets=[black])
    engine.resolve_until_stable()
    assert black.zone == Zone.EXILE
    engine = game()
    filler(engine, "Large", power=4, toughness=4)
    plain = _creature(engine, "Plain", 4, "p2")
    spell = card(engine, "Bouncer's Beatdown", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    main_phase(engine)
    p1.mana_pool.add("G", 1)
    try:
        engine.cast_spell(p1, spell, targets=[plain])
        engine.resolve_until_stable()
    except Exception:                                                    # an unaffordable cast is rejected
        pass
    assert plain.zone == Zone.BATTLEFIELD and plain.damage_marked == 0


#: Combustion Technique's printed base damage.
COMBUSTION_BASE = 2


def test_combustion_technique_adds_lessons_in_the_graveyard_and_exiles():
    engine = game()
    _gy(engine, 1, "Instant — Lesson", name="L")
    _gy(engine, 1, "Instant", name="NotLesson")
    victim = _creature(engine, "Victim", COMBUSTION_BASE + 1, "p2")       # 2 + 1 Lesson = 3: lethal
    _cast_at(engine, "Combustion Technique", victim)
    assert victim.zone == Zone.EXILE
    engine = game()
    _gy(engine, 3, "Instant", name="NotLesson")                           # no Lessons: only 2 damage
    survivor = _creature(engine, "Survivor", COMBUSTION_BASE + 1, "p2")
    _cast_at(engine, "Combustion Technique", survivor)
    assert survivor.zone == Zone.BATTLEFIELD and survivor.damage_marked == COMBUSTION_BASE


#: Kamahl's Sledge's own text: the threshold "instead" replaces the WHOLE base instruction (RULE 608.2c, 614.6).
SLEDGE_TEXT = ("~ deals 4 damage to target creature. if there are 7 or more cards in your graveyard, instead ~ deals 4 damage "
               "to that creature and 4 damage to that creature's controller.")


def test_kamahls_sledge_stays_unclaimed_rather_than_gating_only_half_of_its_instead():
    """A cut inside a gated "instead" sentence gated the first damage only and hit the controller at any graveyard size.

    The parser refuses the card (the replacement needs a "that creature's controller" referent no row binds yet), so the
    engine never runs a half-conditional spec.
    """
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    assert parse_effect_body(SLEDGE_TEXT) is None
    assert parse_oracle(CardDatabase(DB_PATH).get_card("Kamahl's Sledge")).coverage != MODELED


def test_instead_override_near_misses_keep_their_whole_replacement():
    """Near miss: a replacement the override row reads whole is still claimed, with both branches conditional."""
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    specs = parse_effect_body("~ deals 4 damage to target creature. if there are 7 or more cards in your graveyard, instead ~ deals 6 damage to that creature.")
    assert specs is not None and len(specs) == 1            # one bind: the size is the only thing the condition changes
    below = parse_effect_body("~ deals 4 damage to target creature.")
    assert [spec.type for spec in below] == ["damage"]       # below threshold: only the creature is damaged


def _declare(engine, attacker):
    """``attacker`` attacks the opponent, then the game moves to the declare-blockers step (RULE 509.1)."""
    attack(engine, [attacker])
    engine.state.current_step = "declare_blockers"


def _blocks(engine, attacker, blocker):
    return engine.can_block(engine.state.player_by_id(blocker.controller_id), blocker, attacker)


def _colored(engine, name, mana, player):
    return filler(engine, name, player=player, power=1, toughness=1, mv=1, mana_cost_string=mana)


def test_magistrates_veto_stops_white_and_blue_blockers_only():
    engine = game()
    attacker = _colored(engine, "Att", "{G}", "p1")
    _declare(engine, attacker)
    white = _colored(engine, "White", "{W}", "p2")
    blue = _colored(engine, "Blue", "{U}", "p2")
    red = _colored(engine, "Red", "{R}", "p2")
    colorless = filler(engine, "Art", power=1, toughness=1, player="p2")
    assert _blocks(engine, attacker, white) and _blocks(engine, attacker, blue)       # before the Veto
    card(engine, "Magistrate's Veto")
    engine.recompute_continuous_effects()
    assert not _blocks(engine, attacker, white)
    assert not _blocks(engine, attacker, blue)
    assert _blocks(engine, attacker, red) and _blocks(engine, attacker, colorless)    # near misses


def test_magistrates_veto_also_stops_your_own_white_creatures():
    engine = game()
    attacker = _colored(engine, "Att", "{G}", "p2")
    engine.state.active_player_index = 1
    _declare(engine, attacker)
    mine = _colored(engine, "Mine", "{W}", "p1")
    card(engine, "Magistrate's Veto")
    engine.recompute_continuous_effects()
    assert not _blocks(engine, attacker, mine)                             # "white creatures" is not controller-scoped


def test_necrotic_wound_shrinks_by_creature_cards_and_exiles():
    engine = game()
    _gy(engine, 2, "Creature", name="C", power=1, toughness=1)
    _gy(engine, 1, "Instant", name="I")                                    # not a creature card
    victim = _creature(engine, "Victim", 2, "p2")
    _cast_at(engine, "Necrotic Wound", victim)
    assert victim.zone == Zone.EXILE                                       # -2/-2 kills it; exile instead
    engine = game()
    _gy(engine, 2, "Creature", name="C", power=1, toughness=1)
    survivor = _creature(engine, "Survivor", 3, "p2")
    _cast_at(engine, "Necrotic Wound", survivor)
    engine.recompute_continuous_effects()
    assert survivor.zone == Zone.BATTLEFIELD and survivor.toughness == 1


def test_necrotic_wound_with_an_empty_graveyard_does_nothing():
    engine = game()
    victim = _creature(engine, "Victim", 1, "p2")
    _cast_at(engine, "Necrotic Wound", victim)
    engine.recompute_continuous_effects()
    assert victim.zone == Zone.BATTLEFIELD and victim.toughness == 1


def _treasure_object(engine):
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    treasure = GameObject(Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure",
                               oracle_text="{T}, Sacrifice this artifact: Add one mana of any color."),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    treasure.summoning_sick = False
    treasure.controller_id = "p1"
    engine.state.add_to_battlefield(treasure)
    return treasure


def _spoils(engine, with_treasure):
    mine = filler(engine, "Mine", power=2, toughness=5)
    theirs = _creature(engine, "Theirs", 3, "p2")
    spell = card(engine, "Spoils of the Hunt", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    main_phase(engine)
    if with_treasure:
        engine.tap_for_mana(p1, _treasure_object(engine), option_index=4)       # green, sacrificing the Treasure
        p1.mana_pool.add("G", 2)
    else:
        p1.mana_pool.add_many({"G": 3})
    engine.cast_spell(p1, spell, targets=[mine, theirs])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    return mine, theirs


def test_spoils_of_the_hunt_pumps_per_treasure_mana_then_bites():
    engine = game()
    mine, theirs = _spoils(engine, with_treasure=True)
    assert mine.power == 3                       # 2 + one Treasure mana
    assert theirs.damage_marked == 3 or theirs.zone == Zone.GRAVEYARD    # the bite uses the pumped power


def test_spoils_of_the_hunt_without_treasure_mana_does_not_pump():
    engine = game()
    mine, theirs = _spoils(engine, with_treasure=False)
    assert mine.power == 2
    assert theirs.damage_marked == 2


def test_temple_thief_is_blocked_by_anything_but_enchanted_or_enchantment_creatures():
    engine = game()
    thief = card(engine, "Temple Thief")
    _declare(engine, thief)
    plain = filler(engine, "Plain", power=1, toughness=1, player="p2")
    ench_creature = filler(engine, "EnchCreature", type_line="Enchantment Creature", power=1, toughness=1, player="p2")
    enchanted = filler(engine, "Enchanted", power=1, toughness=1, player="p2")
    aura = filler(engine, "Aura", type_line="Enchantment — Aura", player="p2")
    aura.attached_to = enchanted.instance_id
    engine.recompute_continuous_effects()
    assert _blocks(engine, thief, plain)                                  # near miss
    assert not _blocks(engine, thief, ench_creature)
    assert not _blocks(engine, thief, enchanted)


# --- a "this way" amount never reads a pool its own body fills ---------------------------------------------------

def test_this_way_amount_is_not_bound_over_its_own_producer():
    """RULE 608.2c: "exile X ... . For each ... exiled this way, create a copy of it" is not one scaled exile (Foggy Swamp Visions)."""
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    text = "exile x target creature cards from graveyards. for each creature card exiled this way, create a token that's a copy of it."
    assert parse_effect_body(text) is None
    # near miss: a consumer that is not the producer keeps its reading
    specs = parse_effect_body("exile x target creature cards from graveyards. you gain 1 life for each creature card exiled this way.")
    assert [s.type for s in specs] == ["exile", "bind"]
