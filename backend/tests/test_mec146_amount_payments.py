"""Variable payments through the parser, stack, and live choice dispatch."""
from collections import Counter

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter.effect_body import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


NAMES = (
    "Alliance of Arms", "Mana-Charged Dragon", "Minds Aglow", "Shared Trauma",
    "Aether Spike", "Plague of Vermin", "Wrath of the Skies",
)


def _card(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} missing from the local Oracle cache")
    return card


def _engine():
    filler = Card(id="fill", name="Filler", type_line="Basic Land — Plains")
    engine = GameEngine.new_game(
        [(pid, pid, [filler] * 15) for pid in ("a", "b", "c")], starting_hand=0,
    )
    while engine.state.current_phase != "precombat_main":
        engine.advance_step()
    return engine


def _put(engine, card, who, zone=Zone.HAND):
    obj = GameObject(card, owner_id=who, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(who).add_to_zone(obj, zone)
    return obj


def _cast(engine, name, who="a", mana=None, **kwargs):
    player = engine.state.player_by_id(who)
    spell = _put(engine, _card(name), who)
    for color, amount in (mana or {}).items():
        player.mana_pool.add(color, amount)
    engine.cast_spell(player, spell, **kwargs)
    return spell


def _answer(engine, who, amount):
    assert engine.state.pending_choice["player_id"] == who
    engine.resolve_pending_choice(f"pay_x:{amount}" if amount else "decline")


@pytest.mark.parametrize("name", NAMES)
def test_named_oracle_is_modeled(name):
    assert parse_oracle(_card(name)).modeled


def test_incompatible_payment_referent_is_unclaimed():
    assert parse_effect_body(
        "starting with you, each player may pay any amount of mana. "
        "each player draws x cards, where x is the total amount of life paid this way."
    ) is None


@pytest.mark.parametrize("name,mana", [
    ("Alliance of Arms", {"W": 1}), ("Minds Aglow", {"U": 1}), ("Shared Trauma", {"B": 1}),
])
def test_join_forces_starts_with_controller_and_uses_total_after_restore(name, mana):
    engine = _engine()
    engine.state.active_player_index = 1
    _cast(engine, name, who="b", mana=mana)
    # Resolve on a different player's turn to distinguish controller order from APNAP.
    engine.state.active_player_index = 0
    for pid in ("a", "b", "c"):
        engine.state.player_by_id(pid).mana_pool.add("C", 3)
    old_sizes = {p.id: (len(p.hand), len(p.graveyard)) for p in engine.state.players}
    engine.rules.resolve_top_of_stack()
    _answer(engine, "b", 2)
    engine = GameEngine(engine.state.clone())
    assert engine.state.pending_choice["paid_amounts"]["b"] == 2
    _answer(engine, "c", 1)
    _answer(engine, "a", 0)
    assert engine.state.pending_choice is None
    if name == "Alliance of Arms":
        assert Counter(o.controller_id for o in engine.state.battlefield if o.is_token) == {"a": 3, "b": 3, "c": 3}
    elif name == "Minds Aglow":
        assert all(len(p.hand) - old_sizes[p.id][0] == 3 for p in engine.state.players)
    else:
        assert {p.id: len(p.graveyard) - old_sizes[p.id][1] for p in engine.state.players} == {"a": 3, "b": 4, "c": 3}


def test_plague_repeats_until_a_full_unpaid_round_and_uses_individual_totals():
    engine = _engine()
    _cast(engine, "Plague of Vermin", mana={"B": 7})
    engine.rules.resolve_top_of_stack()
    for who, amount in [("a", 2), ("b", 0), ("c", 3), ("a", 0), ("b", 1), ("c", 0),
                        ("a", 0), ("b", 0), ("c", 0)]:
        _answer(engine, who, amount)
    assert engine.state.pending_choice is None
    assert Counter(o.controller_id for o in engine.state.battlefield if o.name == "Rat") == {"a": 2, "b": 1, "c": 3}
    batches = [event.get("members") for event in engine.state.event_log
               if event.type == "EVENT_BATCH" and event.get("batch_of") == "ENTERS_BATTLEFIELD"]
    assert [len(batch) for batch in batches] == [6]


def test_wrath_uses_energy_spent_and_keeps_spell_x_separate():
    engine = _engine()
    player = engine.state.player_by_id("a")
    player.counters["energy"] = 1
    targets = [_put(engine, _card(name), "b", Zone.BATTLEFIELD)
               for name in ("Mox Amber", "Grizzly Bears", "Hill Giant", "Plains")]
    _cast(engine, "Wrath of the Skies", mana={"W": 3}, x=1)
    engine.rules.resolve_top_of_stack()
    assert player.counters["energy"] == 2
    _answer(engine, "a", 2)
    assert [obj.zone for obj in targets] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.BATTLEFIELD, Zone.BATTLEFIELD]
    assert player.counters.get("energy", 0) == 0


def test_aether_spike_announces_target_then_sets_tax_from_energy():
    engine = _engine()
    spell = _cast(engine, "Divination", mana={"U": 3})
    engine.state.active_player_index = 1
    target = engine.state.stack[-1]
    _cast(engine, "Aether Spike", who="b", mana={"U": 2}, targets=[target])
    engine.rules.resolve_top_of_stack()
    engine.state.player_by_id("a").mana_pool.add("C", 2)
    _answer(engine, "b", 2)
    assert engine.state.pending_choice["kind"] == "ward"
    assert engine.state.pending_ward["cost"].mana.resolved_value == 2
    engine.resolve_pending_choice("decline")
    assert spell.zone == Zone.GRAVEYARD
    assert not engine.state.stack


def test_discard_payment_draws_only_after_the_selected_cards_are_discarded():
    engine = _engine()
    card = Card(id="loot", name="Loot", type_line="Sorcery", mana_cost_string="{0}", is_sorcery=True,
                oracle_text="Discard any number of cards. Draw that many cards.")
    assert parse_oracle(card).modeled
    player = engine.state.player_by_id("a")
    spell = _put(engine, card, player.id)
    cards = [_put(engine, _card(name), player.id) for name in ("Plains", "Island", "Swamp")]
    hand_size = len(player.hand) - 1
    engine.cast_spell(player, spell)
    engine.rules.resolve_top_of_stack()
    _answer(engine, player.id, 2)
    assert engine.state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(str(cards[0].instance_id))
    engine.resolve_pending_choice(str(cards[1].instance_id))
    assert len(player.hand) == hand_size
    assert cards[2] in player.hand
    assert all(card in player.graveyard for card in cards[:2])


@pytest.mark.parametrize("event_type", ["ATTACKS", "BLOCKS"])
def test_dragon_pumps_from_both_combat_triggers(event_type):
    from mtg_analyzer.models.game.events import GameEvent

    engine = _engine()
    dragon = _put(engine, _card("Mana-Charged Dragon"), "b", Zone.BATTLEFIELD)
    engine.state.player_by_id("b").mana_pool.add("C", 2)
    engine.state.player_by_id("c").mana_pool.add("C", 1)
    engine.state.fire_event(GameEvent(event_type, instance_id=dragon.instance_id, controller_id="b"))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    _answer(engine, "b", 2)
    _answer(engine, "c", 1)
    engine.recompute_continuous_effects()
    assert dragon.power == dragon.card.power + 3
    assert dragon.toughness == dragon.card.toughness


def test_only_payer_can_activate_mana_or_answer_in_the_session():
    from mtg_analyzer.services.game_session import GameActionError, GameSession

    engine = _engine()
    spirit = _put(engine, _card("Elvish Spirit Guide"), "b")
    _cast(engine, "Minds Aglow", mana={"U": 1})
    engine.rules.resolve_top_of_stack()
    session = GameSession(engine, mode="multiplayer")
    assert engine.state.pending_choice["player_id"] == "b"
    assert engine.state.pending_choice["max_amount"] == 0
    assert not session.legal_actions("a")
    action = {"type": "activate_hand_mana", "instance_id": spirit.instance_id}
    assert any(a["type"] == action["type"] for a in session.legal_actions("b"))
    with pytest.raises(GameActionError, match="only the payer"):
        session.apply_action(action, "a")
    with pytest.raises(GameActionError, match="not the player making this choice"):
        session.apply_action({"type": "decline"}, "a")
    # An invalid source also rolls back the privately suspended choice.
    with pytest.raises(GameActionError, match="no game object"):
        session.apply_action({**action, "instance_id": -1}, "b")
    assert session.engine.state.pending_choice["player_id"] == "b"
    session.apply_action(action, "b")
    assert session.engine.state.pending_choice["max_amount"] == 1
    session.apply_action({"type": "choose", "option_id": "pay_x:1"}, "b")
    assert session.engine.state.pending_choice is None
    assert session.engine.state.find_object(spirit.instance_id).zone == Zone.EXILE
    assert all(p.hand for p in session.engine.state.players)


def test_conceding_during_payment_advances_to_the_next_payer():
    from mtg_analyzer.services.game_session import GameSession

    engine = _engine()
    _cast(engine, "Minds Aglow", mana={"U": 1})
    engine.state.player_by_id("b").mana_pool.add("C", 1)
    engine.state.player_by_id("c").mana_pool.add("C", 1)
    engine.rules.resolve_top_of_stack()
    session = GameSession(engine, mode="multiplayer")
    assert engine.state.pending_choice["player_id"] == "b"
    session.concede("b")
    _answer(session.engine, "c", 1)
    assert session.engine.state.pending_choice is None
    assert len(session.engine.state.player_by_id("c").hand) == 1


@pytest.mark.parametrize("graveyard_size,creates_spirit", [(5, False), (6, True)])
def test_illuminate_history_checks_graveyard_after_discarding_and_drawing(graveyard_size, creates_spirit):
    engine = _engine()
    player = engine.state.player_by_id("a")
    for _ in range(graveyard_size):
        _put(engine, _card("Plains"), player.id, Zone.GRAVEYARD)
    land = _put(engine, _card("Mountain"), player.id)
    _cast(engine, "Illuminate History", mana={"R": 4})
    engine.rules.resolve_top_of_stack()
    _answer(engine, player.id, 1)
    engine.resolve_pending_choice(str(land.instance_id))
    assert land.zone == Zone.GRAVEYARD
    assert len(player.hand) == 2  # Opening draw plus one from Illuminate History.
    assert any(o.name == "Spirit" and o.controller_id == player.id for o in engine.state.battlefield) == creates_spirit
