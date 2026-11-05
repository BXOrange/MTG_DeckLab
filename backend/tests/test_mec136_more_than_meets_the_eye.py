"""MEC-136 — More Than Meets the Eye (RULE 702.162): cast converted, back face up, for an alternative cost."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.game_session import GameSession

#: The five Transformers cards the parser counts as MODELED, with the cost the oracle text prints.
CARDS = {
    "Arcee, Sharpshooter // Arcee, Acrobatic Coupe": ("{R}{W}", {"R": 1, "W": 1}, 3),
    "Cyclonus, the Saboteur // Cyclonus, Cybertronian Fighter": ("{5}{U}{B}", {"U": 1, "B": 1, "C": 5}, 4),
    "Goldbug, Humanity's Ally // Goldbug, Scrappy Scout": ("{W}{U}", {"W": 1, "U": 1}, 3),
    "Starscream, Power Hungry // Starscream, Seeker Leader": ("{2}{B}", {"B": 1, "C": 2}, 4),
    "Ultra Magnus, Tactician // Ultra Magnus, Armored Carrier": ("{2}{R}{G}{W}", {"R": 1, "G": 1, "W": 1, "C": 2}, 7),
}


def synthetic(cost="{1}{R}", mana="{3}{R}{R}", cmc=5):
    return Card(
        id="robot", name="Robot Front // Robot Back", type_line="Artifact Creature — Robot", is_creature=True,
        layout="transform", mana_cost_string=mana, converted_mana_cost=cmc, power=2, toughness=2,
        keywords=["More Than Meets the Eye"], oracle_text=f"More Than Meets the Eye {cost}\nFlying",
        back_name="Robot Back", back_type_line="Artifact — Vehicle", back_oracle_text="Crew 2",
        back_power=4, back_toughness=4,
    )


def cached(name):
    with sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT data FROM cards WHERE name = ?", (name,)).fetchone()
    assert row is not None, name
    return Card.from_dict(json.loads(row[0]))


def board(printed, zone=Zone.HAND, mana=None):
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    player = engine.state.active_player
    obj = GameObject(printed, owner_id=player.id, zone=zone)
    player.zones[zone].append(obj)
    bind_from_catalogue(obj)
    if mana:
        player.mana_pool.add_many(mana)
    return engine, player, obj


def converted_offer(engine, player):
    return next((a for a in engine.legal_actions(player) if a.get("more_than_meets_the_eye")), None)


def plain_offer(engine, player):
    return next((a for a in engine.legal_actions(player)
                 if a["type"] == "cast_spell" and not a.get("face") and not a.get("more_than_meets_the_eye")), None)


# --- always-on tier: a synthetic card, no card cache needed ------------------------------------------------

def test_offer_resolution_and_mana_value():
    engine, player, obj = board(synthetic(), mana={"R": 1, "C": 1})
    offer = converted_offer(engine, player)
    assert offer["face"] == "converted" and offer["mtmte_cost_label"] == "{1}{R}"
    assert offer["cost_label"] == "{1}{R}" and offer["mana_value"] == 5 and offer["back_name"] == "Robot Back"
    assert plain_offer(engine, player) is None  # the {3}{R}{R} front cast is not payable
    GameSession(engine).apply_action(offer)
    assert player.mana_pool.total() == 0
    # RULE 712.8c: on the stack with only the back face's characteristics, but the front's mana value.
    assert engine.state.stack[-1].obj is obj and obj.zone == Zone.STACK
    assert obj.name == "Robot Back" and obj.transformed and "Vehicle" in obj.card.type_line
    assert obj.mana_value == 5
    engine.resolve_until_stable()
    # RULE 712.8e / ruling: the permanent enters with its back face up and keeps the front's mana value.
    assert obj in engine.state.battlefield and obj.transformed and obj.name == "Robot Back"
    assert obj.mana_value == 5
    assert "flying" not in obj.intrinsic_keywords  # the front face's abilities are not on the back


def test_normal_cast_is_front_face_up_and_listed_separately():
    engine, player, obj = board(synthetic(), mana={"R": 2, "C": 3})
    assert plain_offer(engine, player) is not None and converted_offer(engine, player) is not None
    engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    assert obj in engine.state.battlefield and not obj.transformed and obj.name == "Robot Front // Robot Back"
    assert player.mana_pool.total() == 0


def test_alternative_cost_cannot_combine_and_needs_a_transforming_card():
    engine, player, obj = board(synthetic(), mana={"R": 5, "C": 5})
    for flag in ("free", "alt_cost", "evoke", "surge", "mutate", "warp"):
        assert not engine.can_cast(player, obj, face="converted", **{flag: True}), flag
    assert not engine.can_cast(player, obj, face="converted", blitz=0)
    assert engine.can_cast(player, obj, face="converted")
    plain = Card(id="p", name="Plain", type_line="Artifact Creature — Robot", is_creature=True, power=1, toughness=1,
                 keywords=["More Than Meets the Eye"], oracle_text="More Than Meets the Eye {R}")
    engine2, player2, obj2 = board(plain, mana={"R": 3})
    assert converted_offer(engine2, player2) is None  # RULE 712.9: no back face to be converted into
    assert not engine2.can_cast(player2, obj2, face="converted")


def test_failed_cast_rolls_back_to_the_front_face():
    printed = synthetic()
    engine, player, obj = board(printed, mana={"R": 1})
    with pytest.raises(ValueError):
        engine.cast_spell(player, obj, face="converted")
    assert obj.zone == Zone.HAND and not obj.transformed and obj.name == "Robot Front // Robot Back"
    assert obj.card is printed and not hasattr(obj, "_mtmte_cast_cost")


def test_countered_spell_returns_to_the_graveyard_front_face_up():
    engine, player, obj = board(synthetic(), mana={"R": 1, "C": 1})
    engine.cast_spell(player, obj, face="converted")
    engine.rules.counter_spell(engine.state.stack[-1])
    assert obj in player.graveyard and not obj.transformed
    assert obj.name == "Robot Front // Robot Back" and obj.mana_value == 5  # RULE 712.8a / 400.7


def test_clone_mid_stack_keeps_the_converted_spell():
    engine, player, obj = board(synthetic(), mana={"R": 1, "C": 1})
    engine.cast_spell(player, obj, face="converted")
    clone = GameEngine(engine.state.clone())
    spell = clone.state.stack[-1].obj
    assert spell.transformed and spell.name == "Robot Back" and spell.mana_value == 5
    clone.resolve_until_stable()
    assert spell in clone.state.battlefield and spell.transformed and spell.name == "Robot Back"


def test_commander_tax_still_applies_from_the_command_zone():
    engine, player, obj = board(synthetic(), zone=Zone.COMMAND, mana={"R": 1, "C": 3})
    obj.is_commander = True
    player.commander_casts[obj.instance_id] = 1  # RULE 903.8: {2} more per earlier cast from the command zone
    offer = converted_offer(engine, player)
    assert offer["cost_label"] == "{3}{R}"
    engine.cast_spell(player, obj, face="converted")
    assert player.mana_pool.total() == 0 and obj.transformed


def test_converting_back_on_the_battlefield_returns_to_the_front():
    engine, player, obj = board(synthetic(), mana={"R": 1, "C": 1})
    engine.cast_spell(player, obj, face="converted")
    engine.resolve_until_stable()
    assert engine.rules.transform_permanent(obj)  # RULE 701.28a: convert = turn it over
    assert not obj.transformed and obj.name == "Robot Front // Robot Back" and obj.mana_value == 5
    assert engine.rules.transform_permanent(obj) and obj.transformed and obj.mana_value == 5


def test_session_snapshot_round_trip_carries_the_flag_on_the_wire():
    engine, player, obj = board(synthetic(), mana={"R": 1, "C": 1})
    session = GameSession(engine)
    offer = converted_offer(session.engine, player)
    session.apply_action(offer)
    view = session.view()
    spell = view["state"]["stack"][-1]["object"]
    assert spell["name"] == "Robot Back" and spell["transformed"] and spell["mana_value"] == 5


# --- full-cache tier: the five real cards ----------------------------------------------------------------

@pytest.mark.full_cache
@pytest.mark.parametrize("name", list(CARDS))
def test_real_cards_cast_converted(name):
    cost, mana, front_value = CARDS[name]
    printed = cached(name)
    assert parse_oracle(printed).modeled
    engine, player, obj = board(printed, mana=dict(mana))
    offer = converted_offer(engine, player)
    assert offer is not None and offer["mtmte_cost_label"] == cost and offer["mana_value"] == front_value
    assert offer["back_name"] == printed.back_name and offer["face"] == "converted"
    GameSession(engine).apply_action(offer)
    assert player.mana_pool.total() == 0  # exactly the More Than Meets the Eye cost was paid
    assert obj.name == printed.back_name and obj.mana_value == front_value
    engine.resolve_until_stable()
    assert obj in engine.state.battlefield and obj.transformed
    assert obj.name == printed.back_name and "Vehicle" in obj.card.type_line and obj.mana_value == front_value


@pytest.mark.full_cache
@pytest.mark.parametrize("name", list(CARDS))
def test_real_cards_plain_cast_is_front_face_up(name):
    printed = cached(name)
    engine, player, obj = board(printed, mana={"R": 9, "W": 9, "U": 9, "B": 9, "G": 9, "C": 9})
    offers = [a for a in engine.legal_actions(player) if a["type"] == "cast_spell" and a["instance_id"] == obj.instance_id]
    assert {bool(a.get("more_than_meets_the_eye")) for a in offers} == {True, False}
    plain = next(a for a in offers if not a.get("more_than_meets_the_eye"))
    assert not plain.get("face")
    GameSession(engine).apply_action(plain)
    engine.resolve_until_stable()
    assert obj in engine.state.battlefield and not obj.transformed and obj.name == printed.name
    for flag in ("free", "alt_cost", "evoke", "surge", "mutate", "warp"):
        assert not engine.can_cast(player, obj, face="converted", **{flag: True})


@pytest.mark.full_cache
def test_goldbug_front_convert_trigger_still_reaches_the_back_and_returns():
    printed = cached("Goldbug, Humanity's Ally // Goldbug, Scrappy Scout")
    engine, player, obj = board(printed, mana={"W": 1, "U": 1})
    engine.cast_spell(player, obj, face="converted")
    engine.resolve_until_stable()
    assert obj.transformed and obj.mana_value == 3
    assert engine.rules.transform_permanent(obj) and obj.name == printed.name and obj.mana_value == 3


# --- RULE 712.8a: a transformed permanent that leaves the battlefield shows its front face --------------------

def _on_battlefield(converted):
    printed = synthetic()
    engine, player, obj = board(printed, mana={"R": 1, "C": 1} if converted else {"R": 5, "C": 5})
    engine.cast_spell(player, obj, face="converted") if converted else engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    if not converted:
        engine.rules.transform_permanent(obj)
    assert obj.transformed and obj.name == "Robot Back"
    return engine, player, obj, printed


@pytest.mark.parametrize("converted", [True, False])
@pytest.mark.parametrize("leave", ["destroy", "sacrifice", "bounce", "exile"])
def test_transformed_permanent_leaving_play_is_front_face_up(converted, leave):
    engine, player, obj, printed = _on_battlefield(converted)
    if leave == "destroy":
        engine.rules.destroy(obj)
    elif leave == "sacrifice":
        engine.rules.put_into_graveyard(obj)
    elif leave == "bounce":
        engine.rules.return_to_hand(obj)
    else:
        engine.rules.exile(obj)
    assert obj.zone != Zone.BATTLEFIELD
    assert not obj.transformed and obj.card is printed and obj.name == printed.name
    assert obj.mana_value == 5
    assert obj.parametric_keywords.get("more_than_meets_the_eye")  # the front face's abilities are bound again


def test_clone_after_leaving_play_stays_front_face():
    engine, player, obj, printed = _on_battlefield(True)
    engine.rules.destroy(obj)
    clone = GameEngine(engine.state.clone())
    copy_obj = next(o for o in clone.state.player_by_id(player.id).graveyard)
    assert not copy_obj.transformed and copy_obj.name == printed.name


def test_returned_transformed_still_ends_up_on_the_back_face():
    engine, player, obj, printed = _on_battlefield(True)
    engine.rules.exile(obj)
    assert obj.name == printed.name  # exiled card is front face
    assert engine.rules.exile_return_transformed(obj)
    assert obj in engine.state.battlefield and obj.transformed and obj.name == "Robot Back"
