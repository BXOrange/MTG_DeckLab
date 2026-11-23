"""Devour entry, visit history and Oracle payoffs through ordinary gameplay."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.battlefield_batches import start_token_batch
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter.effect_body import parse_effect_body


FODDER = Card(id="fodder", name="Fodder", type_line="Creature — Goblin",
              is_creature=True, power=2, toughness=2)


def _put(engine, card=FODDER, who="a", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=who, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(who).add_to_zone(obj, zone)
    return obj


def _engine():
    engine = GameEngine.new_game(
        [(pid, pid, [FODDER] * 8) for pid in ("a", "b")], starting_hand=0,
    )
    while engine.state.current_phase != "precombat_main":
        engine.advance_step()
    return engine


def _setup(name, oracle):
    engine = _engine()
    card = Card(id=name, name=name, type_line="Creature — Beast", is_creature=True,
                power=3, toughness=3, oracle_text=oracle)
    assert parse_oracle(card).modeled
    return engine, _put(engine, card, zone=Zone.HAND)


def _cast(engine, source):
    engine.cast_spell(engine.state.player_by_id("a"), source)
    engine.resolve_until_stable()


@pytest.mark.parametrize(("name", "multiplier"), [("Mycoloth", 2), ("Ribtruss Roaster", 1)])
def test_hand_authored_cards_use_printed_devour(name, multiplier):
    engine, source = _setup(name, f"Devour {multiplier}")
    victim = _put(engine)
    _cast(engine, source)
    engine.resolve_pending_choice(str(victim.instance_id))
    assert source.counters["+1/+1"] == multiplier
    assert victim.zone == Zone.GRAVEYARD


def test_marrow_chomper_sacrifices_together_and_reads_source_visit_after_leaving():
    engine, source = _setup(
        "Marrow Chomper", "Devour 2\nWhen this creature enters, you gain 2 life for each creature it devoured.",
    )
    one, two = _put(engine), _put(engine)
    one.counters["+1/+1"] = 2
    excluded = _put(engine, who="b")
    locked = _put(engine)
    locked.cant_be_sacrificed_this_turn = True
    _cast(engine, source)
    assert {o["instance_id"] for o in engine.state.pending_choice["options"] if "instance_id" in o} == {
        one.instance_id, two.instance_id,
    }
    engine.resolve_pending_choice(str(one.instance_id))
    assert one.zone == two.zone == Zone.BATTLEFIELD
    engine = GameEngine(engine.state.clone())
    engine.rules.resolve_choice(str(two.instance_id))
    source = engine.state.find_object(source.instance_id)
    assert source.counters["+1/+1"] == 4
    snapshots = [engine.state.zone_visit_sources[visit] for visit in source.devoured_creature_visits]
    assert [(obj.instance_id, obj.power) for obj in snapshots] == [(one.instance_id, 4), (two.instance_id, 2)]
    assert engine.state.find_object(excluded.instance_id).zone == Zone.BATTLEFIELD
    player = engine.state.player_by_id("a")
    before = player.life
    engine.rules.return_to_hand(source)
    assert source.devoured_creature_visits == ()
    engine.resolve_until_stable()
    assert player.life == before + 4
    _cast(engine, source)
    assert source.zone == Zone.BATTLEFIELD and source.devoured_creature_visits == ()
    assert "+1/+1" not in source.counters
    assert player.life == before + 4


@pytest.mark.parametrize("accept", [True, False])
def test_skullmulcher_draws_for_devoured_creatures(accept):
    engine, source = _setup(
        "Skullmulcher", "Devour 1\nWhen this creature enters, draw a card for each creature it devoured.",
    )
    victim = _put(engine)
    _cast(engine, source)
    player = engine.state.player_by_id("a")
    before = len(player.hand)
    engine.resolve_pending_choice(str(victim.instance_id) if accept else "decline")
    engine.resolve_until_stable()
    assert len(player.hand) == before + int(accept)


def test_tar_fiend_announces_a_player_and_scales_discard():
    engine, source = _setup(
        "Tar Fiend", "Devour 2\nWhen this creature enters, target player discards a card for each creature it devoured.",
    )
    one, two = _put(engine), _put(engine)
    cards = [_put(engine, who="b", zone=Zone.HAND) for _ in range(2)]
    _cast(engine, source)
    engine.resolve_pending_choice(str(one.instance_id))
    engine.resolve_pending_choice(str(two.instance_id))
    choice = engine.state.pending_choice
    assert choice["kind"].startswith("trigger_target")
    engine.resolve_pending_choice("b")
    engine.resolve_until_stable()
    assert [c.zone for c in cards] == [Zone.GRAVEYARD, Zone.GRAVEYARD]


@pytest.mark.parametrize("accept", [True, False])
def test_devoured_condition_gates_static_keywords_and_etb_trigger(accept):
    engine, source = _setup(
        "Hellkite Hatchling",
        "Devour 1\nThis creature has flying and trample if it devoured a creature.\n"
        "When this creature enters, if it devoured a creature, draw a card.",
    )
    victim = _put(engine)
    _cast(engine, source)
    player = engine.state.player_by_id("a")
    before = len(player.hand)
    engine.rules.resolve_choice(str(victim.instance_id) if accept else "decline")
    engine.recompute_continuous_effects()
    assert {"flying", "trample"} & source.granted_keywords == ({"flying", "trample"} if accept else set())
    engine.resolve_until_stable()
    assert len(player.hand) == before + int(accept)


def test_unrelated_devour_modifier_is_unclaimed():
    assert parse_effect_body("draw a card for each creature it devoured this turn.") is None


def test_simultaneous_tokens_each_get_their_own_devour_choice_after_clone():
    engine = _engine()
    one, two = _put(engine), _put(engine)
    dragon = Card(id="dragon", name="Dragon", type_line="Token Creature — Dragon",
                  is_creature=True, power=1, toughness=1, oracle_text="Devour 2")
    start_token_batch(engine.rules.context, [("a", dragon, 2)], source=None)
    engine.rules.resolve_choice(str(one.instance_id))
    engine.rules.resolve_choice("decline")
    assert all(not obj.is_token for obj in engine.state.battlefield)
    engine = GameEngine(engine.state.clone())
    engine.rules.resolve_choice("decline")
    first, second = [obj for obj in engine.state.battlefield if obj.is_token]
    assert first.counters["+1/+1"] == 2
    assert [iid for iid, _ in first.devoured_creature_visits] == [one.instance_id]
    assert second.devoured_creature_visits == ()
    assert "+1/+1" not in second.counters
    assert engine.state.find_object(two.instance_id).zone == Zone.BATTLEFIELD
