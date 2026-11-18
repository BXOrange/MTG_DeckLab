"""PAR-284 milestone 22: counts read as a spell / ability is announced (RULE 601.2c, 601.2d, 603.3d).

Aether Burst ("up to X target creatures, where X is 1 plus the number of cards named ~ in all graveyards as you cast this
spell") reads a dict `TargetSpec.count_selector` in `targeting.resolved_count`; Jaws of Stone / Volcanic Wind divide a
damage total fixed when the spell is cast (`DealDamageEffect.announced_amount`, frozen by `damage_division.prepare`);
Elrond, Master of Healing reads the firing SCRY event's card count for its target count. All run on a real engine.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError
from tests.support.deck_batch import RICH, card, filler, game, main_phase

AETHER_BURST = "return up to x target creatures to their owners' hands, where x is 1 plus the number of cards named ~ in all graveyards as you cast this spell"
JAWS = "~ deals x damage divided as you choose among any number of targets, where x is the number of mountains you control as you cast this spell"


def _cast_action(engine, player, spell):
    return next(a for a in engine.legal_actions(player) if a.get("type") == "cast_spell"
                and a.get("instance_id") == spell.instance_id)


# --- parser ---------------------------------------------------------------------------------------------------------

def test_target_count_binds_the_structured_selector():
    [spec] = parse_effect_body(AETHER_BURST)
    assert spec.type == "return_to_hand"
    assert spec.params["count_selector"] == {
        "terms": [{"zone": "graveyard", "of": "any", "filter": {"named_as_reference": True}}], "plus": 1}


def test_divided_total_binds_an_announced_amount():
    [spec] = parse_effect_body(JAWS)
    assert spec.type == "damage" and spec.params["division_required"] is True and spec.params["amount"] == 0
    assert spec.params["announced_amount"] == {"zone": "battlefield", "of": "you", "filter": {"subtype": "mountain"}}


@pytest.mark.parametrize("phrase", [
    # a count about another target of the same spell needs that target first: stays unclaimed (Reap)
    "return up to x target cards from your graveyard to your hand, where x is the number of black permanents target opponent controls as you cast this spell",
    # without the announce marker the plain resolution-time reading is unchanged
    "~ deals x damage divided as you choose among any number of targets, where x is the number of mountains you control",
])
def test_other_shapes_keep_their_reading(phrase):
    specs = parse_effect_body(phrase)
    assert specs is None or all("announced_amount" not in s.params for s in specs)


def test_a_trigger_cannot_announce_a_division_total():
    specs = parse_effect_body("~ deals x damage divided as you choose among any number of targets, where x is the number of cards looked at while scrying this way as you cast this spell")
    assert specs is None


@pytest.mark.parametrize("bad", [
    {"kind": "trigger_event", "field": "count"},
    {"zone": "nowhere"},
])
def test_spec_validation_rejects_malformed_announced_counts(bad):
    spec = AbilitySpec("spell_effect", [EffectSpec("return_to_hand", {"target_kind": "creature", "count_selector": bad})])
    with pytest.raises(SpecValidationError):
        spec.validate()


# --- engine: announce-time target count -------------------------------------------------------------------------------

def _burst_board(graveyard_copies):
    engine = game()
    player = engine.state.player_by_id("p1")
    spell = card(engine, "Aether Burst", zone=Zone.HAND)
    for i in range(graveyard_copies):
        card(engine, "Aether Burst", zone=Zone.GRAVEYARD)
    victims = [filler(engine, f"Victim {i}", player="p2", power=1, toughness=1) for i in range(4)]
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    return engine, player, spell, victims


def test_aether_burst_offers_one_plus_the_graveyard_copies():
    engine, player, spell, victims = _burst_board(2)
    entry = _cast_action(engine, player, spell)["targets"][0]
    assert entry["count"] == 3


def test_aether_burst_returns_exactly_the_announced_number():
    engine, player, spell, victims = _burst_board(1)
    engine.cast_spell(player, spell, targets=victims[:2])
    engine.resolve_until_stable()
    assert all(v in engine.state.player_by_id("p2").hand for v in victims[:2])
    assert all(v.zone == Zone.BATTLEFIELD for v in victims[2:])


def test_aether_burst_refuses_more_targets_than_announced():
    engine, player, spell, victims = _burst_board(0)
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=victims[:2])
    assert spell.zone == Zone.HAND


# --- engine: frozen divided-damage total --------------------------------------------------------------------------------

def _jaws_board(mountains):
    engine = game()
    player = engine.state.player_by_id("p1")
    spell = card(engine, "Jaws of Stone", zone=Zone.HAND)
    lands = [filler(engine, f"Mountain {i}", type_line="Basic Land — Mountain") for i in range(mountains)]
    victims = [filler(engine, f"Victim {i}", player="p2", power=1, toughness=9) for i in range(2)]
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    return engine, player, spell, lands, victims


def test_jaws_division_total_is_the_mountain_count_when_cast():
    engine, player, spell, lands, victims = _jaws_board(3)
    action = _cast_action(engine, player, spell)
    assert action["damage_divisions"][0]["total"] == 3
    engine.cast_spell(player, spell, targets=victims, damage_divisions={"0": [1, 2]})
    engine.resolve_until_stable()
    assert [v.damage_marked for v in victims] == [1, 2]


def test_jaws_total_is_frozen_when_a_mountain_leaves_before_resolution():
    engine, player, spell, lands, victims = _jaws_board(3)
    engine.cast_spell(player, spell, targets=victims, damage_divisions={"0": [1, 2]})
    engine.state.battlefield.remove(lands[0])
    engine.state.player_by_id("p1").graveyard.append(lands[0])
    engine.resolve_until_stable()
    assert [v.damage_marked for v in victims] == [1, 2]


def test_jaws_refuses_a_division_that_misses_the_total():
    engine, player, spell, lands, victims = _jaws_board(3)
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=victims, damage_divisions={"0": [1, 1]})
    assert spell.zone == Zone.HAND


def test_volcanic_wind_counts_every_creature_on_the_battlefield():
    engine = game()
    player = engine.state.player_by_id("p1")
    spell = card(engine, "Volcanic Wind", zone=Zone.HAND)
    mine = filler(engine, "Mine", power=1, toughness=9)
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=9)
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    assert _cast_action(engine, player, spell)["damage_divisions"][0]["total"] == 2
    engine.cast_spell(player, spell, targets=[theirs], damage_divisions={"0": [2]})
    engine.resolve_until_stable()
    assert theirs.damage_marked == 2 and mine.damage_marked == 0


# --- engine: trigger-time count from the firing event ---------------------------------------------------------------

def test_elrond_is_modeled_and_counts_the_cards_looked_at():
    from mtg_analyzer.models.cards.card import Card
    from tests.test_par284_this_way_windows import _card
    assert parse_oracle(_card("Elrond", "Legendary Creature — Elf Noble", "Whenever you scry, put a +1/+1 counter on each of up to X target creatures, where X is the number of cards looked at while scrying this way.")).modeled
    [spec] = parse_effect_body("put a +1/+1 counter on each of up to x target creatures, where x is the number of cards looked at while scrying this way")
    selector = spec.params["target_count_selector"]
    assert selector == {"kind": "trigger_event", "field": "count", "event": "SCRY"}
    target = targeting.TargetSpec(kind="creature", count_selector=selector, optional=True)
    engine = game()
    scry = GameEvent(EventType.SCRY, count=3, player_id="p1")
    assert targeting.resolved_count(target, engine.state, "p1", None, scry) == 3
    # another event, or none at all, never answers with a stale number
    assert targeting.resolved_count(target, engine.state, "p1", None, GameEvent(EventType.SURVEIL, count=3)) == 0
    assert targeting.resolved_count(target, engine.state, "p1", None, None) == 0


def _elrond_scry(cards_scryed):
    engine = game(library=6)
    p1 = engine.state.player_by_id("p1")
    elrond = card(engine, "Elrond, Master of Healing")
    bears = [filler(engine, f"Bear {i}", power=2, toughness=2) for i in range(3)]
    main_phase(engine)
    engine.rules.scry(p1, cards_scryed, source=elrond)
    while engine.state.pending_choice is not None and engine.state.pending_choice["kind"] == "scry":
        engine.rules.resolve_choice("decline")  # keep the cards where they are
    engine.resolve_until_stable()  # the SCRY event puts Elrond's trigger on the stack and opens its target choice
    return engine, bears


def test_elrond_puts_counters_on_as_many_targets_as_cards_scryed():
    engine, bears = _elrond_scry(2)
    for bear in bears[:2]:
        choice = engine.state.pending_choice
        assert choice["kind"] == "trigger_target_multi"
        engine.rules.resolve_choice(str(bear.instance_id))
    assert engine.state.pending_choice is None  # exactly two rounds were offered, not three
    engine.resolve_until_stable()
    assert [b.counters.get("+1/+1", 0) for b in bears] == [1, 1, 0]


def test_elrond_scrying_one_card_names_one_target():
    engine, bears = _elrond_scry(1)
    engine.rules.resolve_choice(str(bears[0].instance_id))
    assert engine.state.pending_choice is None
    engine.resolve_until_stable()
    assert [b.counters.get("+1/+1", 0) for b in bears] == [1, 0, 0]


# --- Glissa's Retriever: a dict count on a reflexive trigger's targets ---------------------------------------------------

def _retriever(poisoned):
    engine = game()
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    retriever = card(engine, "Glissa's Retriever")
    for opponent, poison in zip([p2], poisoned):
        opponent.poison = poison
    dead = [filler(engine, f"Gone {i}", zone=Zone.GRAVEYARD, type_line="Creature", power=1, toughness=1) for i in range(2)]
    main_phase(engine)
    return engine, p1, retriever, dead


def _kill_and_collect(engine, retriever, picks):
    engine.rules.destroy(retriever)
    engine.resolve_until_stable()
    for pick in picks:
        choice = engine.state.pending_choice
        assert choice is not None and choice["kind"].startswith("trigger_target")
        engine.rules.resolve_choice(str(pick.instance_id))
        engine.resolve_until_stable()


def test_glissas_retriever_is_modeled_and_exiles_itself_before_the_payoff_targets():
    engine, p1, retriever, dead = _retriever([3])
    # the exiled Retriever is not a legal pick: its own exile precedes the reflexive trigger's target choice
    engine.rules.destroy(retriever)
    engine.resolve_until_stable()
    assert retriever.zone == Zone.EXILE
    choice = engine.state.pending_choice
    assert choice is not None and str(retriever.instance_id) not in {str(o.get("id")) for o in choice["options"]}


def test_glissas_retriever_returns_one_card_per_corrupted_opponent():
    engine, p1, retriever, dead = _retriever([3])
    _kill_and_collect(engine, retriever, dead[:1])
    assert dead[0] in p1.hand and dead[1] in p1.graveyard
    assert engine.state.pending_choice is None  # one opponent, one target round


def test_glissas_retriever_with_no_corrupted_opponent_still_exiles_and_names_no_target():
    engine, p1, retriever, dead = _retriever([2])
    engine.rules.destroy(retriever)
    engine.resolve_until_stable()
    assert retriever.zone == Zone.EXILE and engine.state.pending_choice is None
    assert all(d in p1.graveyard for d in dead)
