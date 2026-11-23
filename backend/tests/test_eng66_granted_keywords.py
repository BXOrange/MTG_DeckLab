"""ENG-66: a keyword is granted only when its rules really run on the object that receives it.

Static and temporary grants of evolve / training / exploit (RULE 702.100, 702.149, 702.110) build the keyword's real
trigger for each receiving object, and absorb N (RULE 702.64) builds its damage-prevention replacement per receiving
object. Every test binds real cards by name from the cache, against a bystander that must not receive the keyword, and
ends the grant (source leaves) to show the rules stop with it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec
from mtg_analyzer.parser.oracle.catalogue.clause_primitives import GRANTABLE_PARAMETRIC_KEYWORDS
from mtg_analyzer.parser.oracle.catalogue.keywords import UNGRANTABLE_FLAG_KEYWORDS
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

#: The +1/+1 counter key on `GameObject.counters`.
PLUS_COUNTER = "+1/+1"


def real_card(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None, name
    return card


def engine() -> GameEngine:
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def put(eng: GameEngine, name: str, owner: str = "p1") -> GameObject:
    """Put a real card onto the battlefield without entering (no ETB trigger)."""
    obj = GameObject(real_card(name), owner_id=owner, controller_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    return obj


def enter(eng: GameEngine, name: str, owner: str = "p1") -> GameObject:
    """Enter a real card the way a resolving permanent spell does (fires ENTERS_BATTLEFIELD)."""
    player = eng.state.player_by_id(owner)
    obj = GameObject(real_card(name), owner_id=owner, controller_id=owner, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    player.remove_from_zone(obj, Zone.HAND)
    eng.rules._put_searched_card(player, obj, "battlefield")
    eng.resolve_until_stable()
    return obj


def leave(eng: GameEngine, obj: GameObject) -> None:
    eng.state.battlefield.remove(obj)
    eng.recompute_continuous_effects()


def counters(obj: GameObject) -> int:
    return int(obj.counters.get(PLUS_COUNTER, 0))


def attack(eng: GameEngine, *attackers: GameObject) -> None:
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.player_by_id("p1"), list(attackers))
    eng.resolve_until_stable()


# -- parse: what is grantable -------------------------------------------------------------------------------------


def test_absorb_is_grantable_and_unmodelled_behaviours_stay_refused():
    assert "absorb" in GRANTABLE_PARAMETRIC_KEYWORDS
    for keyword in ("frenzy", "poisonous", "afterlife", "fabricate", "modular"):
        assert keyword in GRANTABLE_PARAMETRIC_KEYWORDS
        assert static_effect_specs(f"all slivers have {keyword} 1.")
    assert "outlast" not in GRANTABLE_PARAMETRIC_KEYWORDS  # Outlast has a mana cost.
    assert static_effect_specs("all slivers have outlast 1.") is None
    assert static_effect_specs("other slivers you control have outlast {2}.") is None
    assert UNGRANTABLE_FLAG_KEYWORDS >= {"living_weapon", "soulbond", "job_select", "haunt", "ravenous"}
    assert "exploit" not in UNGRANTABLE_FLAG_KEYWORDS


@pytest.mark.parametrize("name", [
    "Lymph Sliver", "Colonel Autumn", "Warrior's Resolve", "Elder Arthur Maxson", "Propagator Drone", "Tyranid Prime",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


# -- evolve (RULE 702.100) ----------------------------------------------------------------------------------------


def test_tyranid_prime_grants_a_working_evolve_to_other_creatures_you_control():
    eng = engine()
    put(eng, "Tyranid Prime")
    mine = put(eng, "Isamaru, Hound of Konda")
    theirs = put(eng, "Grizzly Bears", "p2")
    assert "evolve" in mine.granted_keywords and "evolve" not in theirs.granted_keywords
    enter(eng, "Serra Angel")  # 4/4 against my 2/2
    assert counters(mine) == 1
    enter(eng, "Serra Angel", "p2")  # their bear got no grant: their entrant does not evolve it
    assert counters(theirs) == 0


def test_a_smaller_entrant_does_not_evolve_the_receiver():
    eng = engine()
    put(eng, "Tyranid Prime")
    mine = put(eng, "Serra Angel")
    enter(eng, "Isamaru, Hound of Konda")
    assert counters(mine) == 0


def test_printed_plus_granted_evolve_triggers_once_per_instance():
    # RULE 702.100c: each instance of evolve triggers separately.
    eng = engine()
    put(eng, "Tyranid Prime")
    snapjaw = put(eng, "Adaptive Snapjaw")  # printed evolve, 6/2
    enter(eng, "Serra Angel")  # toughness 4 > 2
    assert counters(snapjaw) == 2


def test_evolve_stops_with_its_grant():
    eng = engine()
    prime = put(eng, "Tyranid Prime")
    mine = put(eng, "Isamaru, Hound of Konda")
    leave(eng, prime)
    assert "evolve" not in mine.granted_keywords
    enter(eng, "Serra Angel")
    assert counters(mine) == 0


def test_propagator_drone_grants_evolve_to_tokens_only():
    eng = engine()
    put(eng, "Propagator Drone")
    token = put(eng, "Grizzly Bears")
    token.is_token = True
    card = put(eng, "Isamaru, Hound of Konda")
    eng.recompute_continuous_effects()
    enter(eng, "Serra Angel")
    assert counters(token) == 1 and counters(card) == 0


def test_temporary_evolve_grant_expires():
    eng = engine()
    mine = put(eng, "Isamaru, Hound of Konda")
    mine.temp_keywords.add("evolve")
    eng.recompute_continuous_effects()
    enter(eng, "Serra Angel")
    assert counters(mine) == 1
    mine.temp_keywords.clear()  # cleanup step (RULE 514.2)
    eng.recompute_continuous_effects()
    enter(eng, "Serra Angel")
    assert counters(mine) == 1


# -- training (RULE 702.149) --------------------------------------------------------------------------------------


def test_warriors_resolve_grants_a_working_training_to_the_lesser_attacker():
    eng = engine()
    put(eng, "Warrior's Resolve")
    small = put(eng, "Isamaru, Hound of Konda")
    big = put(eng, "Serra Angel")
    attack(eng, small, big)
    assert counters(small) == 1 and counters(big) == 0


def test_training_does_not_reach_a_creature_the_grant_does_not_cover():
    eng = engine()
    put(eng, "Warrior's Resolve")
    mine = put(eng, "Serra Angel")
    # A bystander with no training attacking beside a bigger creature gets nothing: only p1 controls the grant.
    other = put(eng, "Grizzly Bears", "p2")
    assert "training" not in other.granted_keywords
    attack(eng, mine)
    assert counters(mine) == 0  # alone: no creature with greater power attacks


def test_printed_plus_granted_training_triggers_once_per_instance():
    eng = engine()
    put(eng, "Warrior's Resolve")
    rider = put(eng, "Gryff Rider")  # printed training, 2/1
    big = put(eng, "Serra Angel")
    attack(eng, rider, big)
    assert counters(rider) == 2  # RULE 702.149c: each instance triggers separately


def test_training_stops_with_its_grant():
    eng = engine()
    resolve = put(eng, "Warrior's Resolve")
    small = put(eng, "Isamaru, Hound of Konda")
    big = put(eng, "Serra Angel")
    leave(eng, resolve)
    attack(eng, small, big)
    assert counters(small) == 0


def test_temporary_training_grant_expires():
    eng = engine()
    small = put(eng, "Isamaru, Hound of Konda")
    big = put(eng, "Serra Angel")
    small.temp_keywords.add("training")
    eng.recompute_continuous_effects()
    assert any(getattr(t, "granted_keyword", None) == "training" for t in small._granted_triggered_abilities)
    small.temp_keywords.clear()
    eng.recompute_continuous_effects()
    assert not small._granted_triggered_abilities
    attack(eng, small, big)
    assert counters(small) == 0


# -- exploit (RULE 702.110) ---------------------------------------------------------------------------------------


def exploit_choice_offered(eng: GameEngine, victim: GameObject) -> bool:
    choice = eng.state.pending_choice
    return choice is not None and any(opt.get("instance_id") == victim.instance_id for opt in choice["options"])


def test_colonel_autumn_gives_exploit_to_an_entering_legendary_creature_only():
    eng = engine()
    put(eng, "Colonel Autumn")
    fodder = put(eng, "Grizzly Bears")
    enter(eng, "Grizzly Bears")  # not legendary: no exploit
    assert eng.state.pending_choice is None
    legend = enter(eng, "Isamaru, Hound of Konda")
    assert exploit_choice_offered(eng, fodder)
    eng.resolve_pending_choice(fodder.instance_id)
    eng.resolve_until_stable()
    assert fodder.zone == Zone.GRAVEYARD
    # Colonel Autumn's own trigger: +1/+1 counter on each creature you control.
    assert counters(legend) == 1


def test_exploit_grant_does_not_reach_the_opponents_legend():
    eng = engine()
    put(eng, "Colonel Autumn")
    put(eng, "Grizzly Bears", "p2")
    enter(eng, "Isamaru, Hound of Konda", "p2")
    assert eng.state.pending_choice is None


def test_exploit_stops_with_its_grant():
    eng = engine()
    colonel = put(eng, "Colonel Autumn")
    put(eng, "Grizzly Bears")
    leave(eng, colonel)
    enter(eng, "Isamaru, Hound of Konda")
    assert eng.state.pending_choice is None


def test_printed_plus_granted_exploit_asks_twice():
    # Colonel Autumn prints exploit and a second Colonel Autumn grants it again to the first (legendary): two instances.
    eng = engine()
    put(eng, "Colonel Autumn")
    entered = enter(eng, "Colonel Autumn")
    assert entered.zone == Zone.BATTLEFIELD
    exploit_triggers = [t for t in entered.triggered_abilities + entered._granted_triggered_abilities
                        if (getattr(t, "keyword_name", None) or getattr(t, "granted_keyword", None)) == "exploit"]
    assert len(exploit_triggers) == 2


def test_temporary_exploit_grant_expires():
    eng = engine()
    mine = put(eng, "Grizzly Bears")
    mine.temp_keywords.add("exploit")
    eng.recompute_continuous_effects()
    assert [t for t in mine._granted_triggered_abilities if t.granted_keyword == "exploit"]
    mine.temp_keywords.clear()
    eng.recompute_continuous_effects()
    assert not mine._granted_triggered_abilities


# -- absorb (RULE 702.64) -----------------------------------------------------------------------------------------


def hit(eng: GameEngine, victim: GameObject, amount: int) -> int:
    source = put(eng, "Grizzly Bears", "p2")
    victim.damage_marked = 0
    eng.rules.deal_damage(victim, amount, source=source)
    while eng.state.pending_choice is not None:  # RULE 616.1: the affected player orders several applicable replacements
        choice = eng.state.pending_choice
        assert choice["kind"] == "replacement_order"
        eng.resolve_pending_choice(choice["options"][0]["id"])
    eng.state.battlefield.remove(source)
    return victim.damage_marked


def test_lymph_sliver_gives_every_sliver_absorb_1_and_no_bystander():
    eng = engine()
    put(eng, "Lymph Sliver")
    ally = put(eng, "Serra Angel")
    ally.card.type_line = "Creature — Sliver"  # a Sliver by type, not by name
    bystander = put(eng, "Grizzly Bears")
    eng.recompute_continuous_effects()
    assert hit(eng, ally, 3) == 2  # 1 of 3 prevented
    assert hit(eng, bystander, 3) == 3


def test_absorb_stops_when_the_lymph_sliver_leaves():
    eng = engine()
    sliver = put(eng, "Lymph Sliver")
    assert hit(eng, sliver, 3) == 2
    other = put(eng, "Lymph Sliver")
    assert hit(eng, sliver, 3) == 1  # RULE 702.64b: two instances each prevent 1
    leave(eng, other)
    assert hit(eng, sliver, 3) == 2
    leave(eng, sliver)


def test_printed_plus_granted_absorb_prevents_both_amounts():
    eng = engine()
    put(eng, "Lymph Sliver")
    sliver = put(eng, "Lymph Sliver")
    attach_to_object(sliver, [AbilitySpec("keyword", [], keyword={"name": "absorb", "n": 2})])  # a printed Absorb 2
    assert hit(eng, sliver, 6) == 6 - 2 - 1 - 1  # printed 2 plus two granted instances of 1


def test_temporary_absorb_grant_expires():
    eng = engine()
    bear = put(eng, "Grizzly Bears")
    bear.temp_parametric_keywords["absorb"] = 2
    eng.recompute_continuous_effects()
    assert hit(eng, bear, 3) == 1
    bear.temp_parametric_keywords.clear()
    eng.recompute_continuous_effects()
    assert hit(eng, bear, 3) == 3


def test_granted_rules_survive_clone_and_undo():
    eng = engine()
    put(eng, "Lymph Sliver")
    put(eng, "Tyranid Prime")
    snail = put(eng, "Isamaru, Hound of Konda")
    restored = GameEngine(eng.state.clone())
    restored.recompute_continuous_effects()
    sliver = next(o for o in restored.state.battlefield if o.card.name == "Lymph Sliver")
    assert hit(restored, sliver, 3) == 2
    mine = next(o for o in restored.state.battlefield if o.card.name == "Isamaru, Hound of Konda")
    enter(restored, "Serra Angel")
    assert counters(mine) == 1 and counters(snail) == 0  # the original game is untouched


def test_token_created_with_absorb_prevents_damage_to_itself():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    eng = engine()
    source = put(eng, "Grizzly Bears")
    effects = build_effects(match_clause("create a 1/1 white spirit creature token with absorb 1"), source)
    effects[0].apply(eng.rules.context, [])
    eng.resolve_until_stable()
    token = next(o for o in eng.state.battlefield if o.is_token)
    assert hit(eng, token, 3) == 2
    assert hit(eng, source, 3) == 3  # the creator did not receive it


def test_resolved_pump_grants_absorb_to_the_group_until_end_of_turn():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    eng = engine()
    mine = put(eng, "Grizzly Bears")
    theirs = put(eng, "Grizzly Bears", "p2")
    effects = build_effects(match_clause("creatures you control gain absorb 1 until end of turn"), mine)
    effects[0].apply(eng.rules.context, [])
    eng.recompute_continuous_effects()
    assert hit(eng, mine, 2) == 1
    assert hit(eng, theirs, 2) == 2


def test_elder_arthur_maxson_gives_training_to_creature_tokens_only():
    eng = engine()
    put(eng, "Elder Arthur Maxson")
    small_token = put(eng, "Isamaru, Hound of Konda")
    small_token.is_token = True
    small_card = put(eng, "Grizzly Bears")
    big = put(eng, "Serra Angel")
    eng.recompute_continuous_effects()
    attack(eng, small_token, small_card, big)
    assert counters(small_token) == 1 and counters(small_card) == 0


@pytest.mark.parametrize("keyword", ["training", "evolve", "exploit"])
def test_a_token_created_with_the_keyword_gets_its_trigger(keyword):
    # Torens / Monet / Propagator-style tokens "with training": the created token's own keyword builds its trigger.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    eng = engine()
    source = put(eng, "Grizzly Bears")
    effects = build_effects(match_clause(f"create a 1/1 white human soldier creature token with {keyword}"), source)
    effects[0].apply(eng.rules.context, [])
    eng.resolve_until_stable()
    token = next(o for o in eng.state.battlefield if o.is_token)
    assert any(keyword in (t.description or "").lower() for t in token.triggered_abilities)
