"""PAR-204 (RULE 118.3, 608.2c, 603.12): optional payments and "if you do" chains, executed in the real engine.

Shapes: a targeted antecedent whose target is announced with the ability (Cyclone Sire, Noyan Dar, Wall of
Resurgence), compound costs ("pay {1} and 1 life"), graveyard-recursion triggers (RULE 113.6k), an X payment capped by a
turn total, and the comma form of the threaten tail. Parse verdicts are only the entry point: each shape is paid,
declined and (where it matters) cloned mid-choice.
"""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import (
    RICH, answer, card, cast, filler, game, main_phase, pick_label, put_on_battlefield, step,
)

PROVENANCE = ParserProvenance(version="test", source="test")

NEWLY_MODELED = (
    "Cyclone Sire", "Noyan Dar, Roil Shaper", "Wall of Resurgence", "Ghastly Remains", "Pyre Zombie",
    "Master of Death", "Pyrewild Shaman", "Blood Operative", "Furious Forebear", "Boneyard Scourge", "Wolfbat",
    "Miara, Thorn of the Glade", "Sokenzan Smelter", "Dreamshaper Shaman", "Casal, Lurkwood Pathfinder // Casal, Pathbreaker Owlbear",
    "Eldrazi Obligator", "Shanna, Purifying Blade", "Mortarion, Daemon Primarch", "Auntie's Snitch",
)


def _modeled(name):
    return parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _claimed(line):
    return segment_line(normalize(line), allow_spell_effect=True, provenance=PROVENANCE).claimed


@pytest.mark.parametrize("name", NEWLY_MODELED)
def test_newly_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _lands(eng):
    return (filler(eng, "LandA", type_line="Basic Land — Forest"), filler(eng, "LandB", type_line="Basic Land — Forest"))


def _opening_choice(eng):
    """Answer the target announcement (first legal target) and return the pending optional question."""
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(str(choice["options"][0]["id"]))
    eng.resolve_until_stable()
    return eng.state.pending_choice


# --- targeted counters, then animation (the three named cards) --------------------------------------------------

def test_wall_of_resurgence_counters_then_animates_the_announced_land():
    eng = game()
    land, other = _lands(eng)
    put_on_battlefield(eng, "Wall of Resurgence")
    question = _opening_choice(eng)
    assert question["kind"] == "composite_optional"
    eng.resolve_pending_choice("yes")
    eng.resolve_until_stable()
    assert land.counters == {"+1/+1": 3}
    # RULE 205.1b: still a land, now also a 0/0 Elemental creature with haste; the counters make it 3/3.
    assert land.is_creature and "land" in land.type_words
    assert (land.power, land.toughness) == (3, 3)
    assert "haste" in land.granted_keywords
    assert not other.is_creature and not other.counters


def test_declining_the_question_does_nothing():
    eng = game()
    land, _ = _lands(eng)
    put_on_battlefield(eng, "Wall of Resurgence")
    _opening_choice(eng)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert not land.counters and not land.is_creature


def test_the_target_is_chosen_before_the_question_and_survives_a_clone_of_it():
    eng = game()
    land, other = _lands(eng)
    put_on_battlefield(eng, "Wall of Resurgence")
    question = _opening_choice(eng)
    assert question["kind"] == "composite_optional"
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("yes")
    clone.resolve_until_stable()
    animated = [o for o in clone.state.battlefield if o.is_creature and "land" in o.type_words]
    assert [o.name for o in animated] == [land.name]  # the clone kept the announced pick
    assert not land.counters  # the original is untouched by resolving the clone


def test_outcome_gating_the_animation_needs_the_counters_to_have_been_placed():
    """RULE 608.2c: "if you do" only holds when the antecedent really happened -- its target is gone, so it did not."""
    eng = game()
    land, other = _lands(eng)
    put_on_battlefield(eng, "Wall of Resurgence")
    question = _opening_choice(eng)
    assert question["kind"] == "composite_optional"
    eng.state.remove_from_battlefield(land)  # the announced land left before the question was answered
    land.zone = Zone.GRAVEYARD
    eng.resolve_pending_choice("yes")
    eng.resolve_until_stable()
    assert not land.is_creature and not other.is_creature and not other.counters


def test_cyclone_sire_acts_from_the_graveyard_after_it_dies():
    eng = game()
    land, _ = _lands(eng)
    sire = card(eng, "Cyclone Sire")
    eng.rules.destroy(sire)
    eng.resolve_until_stable()
    question = _opening_choice(eng)
    assert question["kind"] == "composite_optional"
    eng.resolve_pending_choice("yes")
    eng.resolve_until_stable()
    assert land.counters == {"+1/+1": 3} and land.is_creature


def test_noyan_dar_triggers_on_an_instant_cast_and_not_on_a_creature_spell():
    eng = game()
    land, _ = _lands(eng)
    card(eng, "Noyan Dar, Roil Shaper")
    cast(eng, filler(eng, "Bear", type_line="Creature — Bear", player="p1", zone=Zone.HAND, power=2, toughness=2))
    assert eng.state.pending_choice is None
    cast(eng, filler(eng, "Spark", type_line="Instant", player="p1", zone=Zone.HAND))
    # the instant has no effect of its own; the cast trigger announces its land first
    question = _opening_choice(eng) if eng.state.pending_choice["kind"] == "trigger_target" else eng.state.pending_choice
    assert question["kind"] == "composite_optional"
    eng.resolve_pending_choice("yes")
    eng.resolve_until_stable()
    assert land.counters == {"+1/+1": 3} and land.is_creature


# --- compound costs ---------------------------------------------------------------------------------------------

def _dies(eng, obj):
    eng.state.fire_event(GameEvent(EventType.DIES, controller_id=obj.controller_id, instance_id=obj.instance_id,
                                   object=obj.name, object_types=sorted(obj.type_words)))
    eng.resolve_until_stable()


def test_miara_pays_mana_and_life_together_then_draws():
    eng = game()
    miara = put_on_battlefield(eng, "Miara, Thorn of the Glade")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 1})
    before = (me.life, len(me.hand))
    _dies(eng, miara)
    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert (me.life, len(me.hand)) == (before[0] - 1, before[1] + 1)


def test_a_compound_cost_that_cannot_be_paid_in_full_is_not_offered():
    eng = game()
    miara = put_on_battlefield(eng, "Miara, Thorn of the Glade")
    me = eng.state.player_by_id("p1")  # no mana in the pool and no lands: the mana half cannot be met
    hand = len(me.hand)
    _dies(eng, miara)
    assert eng.state.pending_choice is None and len(me.hand) == hand


def test_declining_a_compound_cost_charges_nothing():
    eng = game()
    miara = put_on_battlefield(eng, "Miara, Thorn of the Glade")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 1})
    hand, life = len(me.hand), me.life
    _dies(eng, miara)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert (me.life, len(me.hand)) == (life, hand)


def test_sokenzan_smelter_needs_the_artifact_to_sacrifice():
    eng = game()
    card(eng, "Sokenzan Smelter")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 1})
    step(eng, "begin_combat")
    assert eng.state.pending_choice is None  # no artifact: unaffordable, so never offered
    rock = filler(eng, "Rock", type_line="Artifact")
    me.mana_pool.add_many({"C": 1})
    step(eng, "begin_combat")
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    answer(eng)
    eng.resolve_until_stable()
    assert rock.zone == Zone.GRAVEYARD
    assert any(o.name == "Construct" and o.controller_id == "p1" for o in eng.state.battlefield)


# --- graveyard recursion (RULE 113.6k) --------------------------------------------------------------------------

def _graveyard_card(eng, name):
    return card(eng, name, zone=Zone.GRAVEYARD)


def test_ghastly_remains_pays_at_upkeep_and_returns_to_hand():
    eng = game()
    obj = _graveyard_card(eng, "Ghastly Remains")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"B": 3})
    step(eng, "upkeep")
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert obj.zone == Zone.HAND and obj in me.hand


def test_ghastly_remains_declined_stays_in_the_graveyard():
    eng = game()
    obj = _graveyard_card(eng, "Ghastly Remains")
    eng.state.player_by_id("p1").mana_pool.add_many({"B": 3})
    step(eng, "upkeep")
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert obj.zone == Zone.GRAVEYARD


def test_graveyard_recursion_is_not_offered_when_it_cannot_be_paid():
    eng = game()
    _graveyard_card(eng, "Ghastly Remains")
    step(eng, "upkeep")
    assert eng.state.pending_choice is None


def test_graveyard_trigger_does_nothing_from_the_battlefield():
    eng = game()
    card(eng, "Ghastly Remains")
    eng.state.player_by_id("p1").mana_pool.add_many({"B": 3})
    step(eng, "upkeep")
    assert eng.state.pending_choice is None


def test_master_of_death_pays_life():
    eng = game()
    obj = _graveyard_card(eng, "Master of Death")
    me = eng.state.player_by_id("p1")
    life = me.life
    step(eng, "upkeep")
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert obj.zone == Zone.HAND and me.life == life - 1


def test_graveyard_dies_trigger_with_a_while_clause_returns_the_card():
    eng = game()
    obj = _graveyard_card(eng, "Furious Forebear")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"W": 1, "C": 1})
    victim = filler(eng, "Victim", type_line="Creature — Bear", power=1, toughness=1)
    _dies(eng, victim)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert obj.zone == Zone.HAND


def test_wolfbat_returns_with_a_finality_counter():
    eng = game()
    obj = _graveyard_card(eng, "Wolfbat")
    me = eng.state.player_by_id("p1")
    me.mana_pool.add_many({"B": 1})
    eng.rules.draw(me, 2)  # the second draw of the turn is the trigger (RULE 121)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and obj.counters.get("finality") == 1


# --- X capped by a turn total ----------------------------------------------------------------------------------

def test_shanna_offers_only_x_up_to_the_life_gained_this_turn():
    eng = game()
    card(eng, "Shanna, Purifying Blade")
    me = eng.state.player_by_id("p1")
    eng.rules.gain_life(me, 3)
    me.mana_pool.add_many({"C": 5})
    hand = len(me.hand)
    step(eng, "end")
    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then"
    assert [o.get("x") for o in choice["options"] if o.get("x") is not None] == [3, 2, 1, 0]
    clone = GameEngine(eng.state.clone())
    eng.resolve_pending_choice(next(str(o["id"]) for o in choice["options"] if o.get("x") == 2))
    eng.resolve_until_stable()
    assert len(me.hand) == hand + 2
    clone.resolve_pending_choice(next(str(o["id"]) for o in choice["options"] if o.get("x") == 3))
    clone.resolve_until_stable()
    assert len(clone.state.player_by_id("p1").hand) == hand + 3  # the clone kept the cap and the announced X


def test_shanna_with_no_life_gained_can_only_pay_nothing():
    eng = game()
    card(eng, "Shanna, Purifying Blade")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 5})
    step(eng, "end")
    choice = eng.state.pending_choice
    assert choice is None or [o.get("x") for o in choice["options"] if o.get("x") is not None] == [0]


# --- the comma form of the threaten tail, pronoun transform --------------------------------------------------

def _cast_obligator(eng):
    target = filler(eng, "Theirs", type_line="Creature — Bear", player="p2", power=2, toughness=2)
    target.tapped = True
    cast(eng, card(eng, "Eldrazi Obligator", zone=Zone.HAND))
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target"  # RULE 601.2c: the target is announced with the cast trigger
    eng.resolve_pending_choice(str(choice["options"][0]["id"]))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    return target


def test_eldrazi_obligator_threatens_untaps_and_gives_haste_when_paid():
    eng = game()
    target = _cast_obligator(eng)
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert target.controller_id == "p1" and not target.tapped and "haste" in target.granted_keywords


def test_eldrazi_obligator_declined_leaves_the_creature_alone():
    eng = game()
    target = _cast_obligator(eng)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert target.controller_id == "p2" and target.tapped


# --- adversarial / fail-closed ------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    # a compound cost whose second part is not in the closed vocabulary stays unclaimed
    "whenever ~ attacks, you may pay {1} and tap an untapped creature you control. if you do, draw a card.",
    # an X cap with no announced X has nothing to cap
    "at the beginning of your end step, you may pay 2 life. if you do, draw x cards. x can't be greater than the amount of life you gained this turn.",
    # a targeted antecedent with a payoff that targets again has nowhere to announce the second target
    "when ~ enters, you may put 3 +1/+1 counters on target land you control. if you do, destroy target creature.",
])
def test_unmodeled_shapes_stay_unclaimed(line):
    assert not _claimed(line)


def test_targeted_antecedent_composition_is_one_optional_with_if_you_do_from():
    seg = segment_line(normalize(
        "when ~ enters, you may put 3 +1/+1 counters on target land you control. if you do, that land becomes a 0/0 elemental "
        "creature with haste that's still a land."), allow_spell_effect=True, provenance=PROVENANCE)
    (effect,) = seg.spec.effects
    assert effect.type == "optional" and effect.params["if_you_do_from"] == 1
    assert [e["type"] for e in effect.params["effects"]] == ["add_counters", "grant_until"]


# --- bots answer the payment from their own view ---------------------------------------------------------------

@pytest.mark.parametrize("policy", ["base", "smart2"])
def test_a_bot_answers_the_payment_choice_with_a_legal_action(policy):
    from mtg_analyzer.services.bot_policies.base import Bot
    from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
    from mtg_analyzer.services.game_session import GameSession

    eng = game()
    obj = card(eng, "Ghastly Remains", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p1").mana_pool.add_many({"B": 3})
    step(eng, "upkeep")
    session = GameSession(eng, require_setup=False)
    answers = [a for a in session.legal_actions("p1") if a["type"] in ("choose", "decline")]
    assert {a["type"] for a in answers} == {"choose", "decline"}
    bot = (Bot if policy == "base" else SmartBot2)("p1")
    view = session.view(perspective="p1")
    picked = bot.answer_choice(view, answers)
    assert picked in answers
    session.apply_action(picked)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert obj.zone in (Zone.HAND, Zone.GRAVEYARD)  # either answer is legal; the point is the bot can answer


# --- the opponent is the payer (existing `payer` modes stay intact) ---------------------------------------------

def test_opponent_pays_variant_asks_the_other_player_and_declining_costs_them_life():
    eng = game()
    theirs = filler(eng, "Theirs", type_line="Creature — Bear", player="p2", power=5, toughness=5)
    filler(eng, "Spare", type_line="Artifact", player="p2")
    cast(eng, card(eng, "Torment of Venom", zone=Zone.HAND), targets=[theirs])
    choice = eng.state.pending_choice
    assert choice["kind"] == "pay_cost_then" and choice["player_id"] == "p2"
    clone = GameEngine(eng.state.clone())
    life = eng.state.player_by_id("p2").life
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == life - 3
    assert clone.state.pending_choice["player_id"] == "p2"  # the clone kept the question for the same payer
