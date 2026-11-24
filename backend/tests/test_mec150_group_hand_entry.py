"""MEC-150: private APNAP selections, simultaneous entry and repeat rounds."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.game_session import _redact_hidden_zones

SHOW = "Each player may put an artifact, creature, enchantment, or land card from their hand onto the battlefield."
EUREKA = (
    "Starting with you, each player may put a permanent card from their hand onto the battlefield. "
    "Repeat this process until no one puts a card onto the battlefield."
)
WURM = (
    "When this creature enters, each opponent may put any number of artifact, creature, enchantment, "
    "and/or land cards from their hand onto the battlefield."
)
LAND = "Each player may put a land card from their hand onto the battlefield"
WORLDS = (
    "Exile all creatures. Each player may put any number of creature cards from their hand onto the battlefield. "
    "Then put all cards exiled this way into their owners' hands. Exile Worlds Within Worlds."
)
AURORA = (
    "Each player shuffles all cards from their hand and all permanents they own into their library, "
    "then draws that many cards. Each player may put any number of land cards from their hand onto "
    "the battlefield. Exile The Great Aurora."
)


def _engine():
    return GameEngine.new_game([(pid, pid, []) for pid in ("a", "b", "c")],
                               starting_life=20, starting_hand=0)


def _object(engine, player, name, type_line="Creature", text="", zone=Zone.HAND):
    creature = type_line.startswith("Creature")
    obj = GameObject(Card(id=name, name=name, type_line=type_line, oracle_text=text,
                          is_creature=creature, power=2 if creature else None,
                          toughness=2 if creature else None, is_sorcery=type_line == "Sorcery",
                          is_land="Land" in type_line, mana_cost_string="{1}" if type_line == "Sorcery" else ""),
                     owner_id=player, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _apply(engine, source):
    parsed = parse_oracle(source.card)
    assert parsed.modeled, parsed.unclaimed
    for effect in build_effects(parsed.effect_specs[-1].effects, source):
        effect.apply(engine.rules.context)


def _pick(engine, player, card=None):
    assert engine.state.pending_choice["player_id"] == player
    engine.resolve_pending_choice(str(card.instance_id) if card is not None else "decline")


def test_show_and_tell_apnap_private_and_simultaneous_across_clone():
    engine = _engine()
    engine.state.active_player_index = 1
    source = _object(engine, "a", "Show and Tell", "Sorcery", SHOW)
    a, b, c = [_object(engine, pid, f"{pid} Bear") for pid in ("a", "b", "c")]
    _apply(engine, source)
    _pick(engine, "b", b)
    assert b.zone == Zone.HAND
    view = engine.state.to_dict()
    _redact_hidden_zones(view, "c")
    assert "group_hand_entry" not in view["pending_choice"]
    assert view["players"][1]["hand"] == []

    saved = engine.state.clone()
    _pick(engine, "c", c)
    assert not engine.state.battlefield
    _pick(engine, "a", a)
    assert {obj.controller_id for obj in engine.state.battlefield} == {"a", "b", "c"}
    assert all(obj.zone == Zone.HAND for player in saved.players for obj in player.hand)
    assert saved.pending_choice["player_id"] == "c"
    restored = GameEngine(saved)
    _pick(restored, "c")
    _pick(restored, "a", a)
    assert {obj.controller_id for obj in restored.state.battlefield} == {"a", "b"}


def test_eureka_starts_with_controller_and_stops_after_an_empty_round():
    engine = _engine()
    source = _object(engine, "b", "Eureka", "Sorcery", EUREKA, Zone.GRAVEYARD)
    a, b, c = [_object(engine, pid, f"{pid} Bear") for pid in ("a", "b", "c")]
    _apply(engine, source)
    _pick(engine, "b", b)
    assert b in engine.state.battlefield
    _pick(engine, "c")
    _pick(engine, "a", a)
    _pick(engine, "c")
    assert c.zone == Zone.HAND
    assert engine.state.pending_choice is None


def test_wurm_selects_multiple_from_each_opponent_and_keeps_them_in_hand_until_commit():
    engine = _engine()
    source = _object(engine, "a", "Tempting Wurm", text=WURM, zone=Zone.BATTLEFIELD)
    a = _object(engine, "a", "Caster's Bear")
    first, second = [_object(engine, "b", name) for name in ("First Bear", "Second Bear")]
    c = _object(engine, "c", "c Bear")
    _apply(engine, source)
    _pick(engine, "b", first)
    _pick(engine, "b", second)
    assert first.zone == second.zone == Zone.HAND
    _pick(engine, "c", c)
    assert all(obj.zone == Zone.BATTLEFIELD for obj in (first, second, c))
    assert a.zone == Zone.HAND


def test_opponents_draw_only_if_they_did_not_put_a_land():
    engine = _engine()
    source = _object(engine, "a", "Land offer", "Sorcery",
                     LAND + ", then each opponent who didn't draws a card.", Zone.GRAVEYARD)
    b, c = [_object(engine, pid, f"{pid} Forest", "Basic Land — Forest") for pid in ("b", "c")]
    draws = [_object(engine, pid, f"{pid} Draw", zone=Zone.LIBRARY) for pid in ("a", "b", "c")]
    _apply(engine, source)
    _pick(engine, "b", b)
    _pick(engine, "c")
    assert b.zone == Zone.BATTLEFIELD and c.zone == Zone.HAND
    assert [obj.zone for obj in draws] == [Zone.LIBRARY, Zone.LIBRARY, Zone.HAND]


def test_worlds_returns_its_exiled_creatures_after_the_new_creatures_enter():
    engine = _engine()
    source = _object(engine, "a", "Worlds Within Worlds", "Sorcery", WORLDS)
    old = _object(engine, "b", "Old Bear", zone=Zone.BATTLEFIELD)
    new = _object(engine, "b", "New Bear")
    engine.state.current_phase = "precombat_main"
    engine.state.current_step = "main1"
    caster = engine.state.player_by_id("a")
    caster.mana_pool.add("C", 1)
    engine.cast_spell(caster, source)
    engine.resolve_until_stable()
    assert old.zone == Zone.EXILE
    _pick(engine, "b", new)
    assert new.zone == Zone.BATTLEFIELD
    assert old.zone == Zone.HAND
    assert source.zone == Zone.EXILE


def test_aurora_counts_owned_permanents_and_tokens_but_does_not_draw_tokens():
    engine = _engine()
    source = _object(engine, "a", "The Great Aurora", "Sorcery", AURORA)
    stolen_land = _object(engine, "a", "Forest", "Basic Land — Forest", zone=Zone.BATTLEFIELD)
    stolen_land.controller_id = "b"
    token = _object(engine, "a", "Bear token", zone=Zone.BATTLEFIELD)
    token.is_token = True
    card = _object(engine, "a", "Library Bear", zone=Zone.LIBRARY)
    engine.state.current_phase = "precombat_main"
    engine.state.current_step = "main1"
    caster = engine.state.player_by_id("a")
    caster.mana_pool.add("C", 1)
    engine.cast_spell(caster, source)
    engine.resolve_until_stable()
    assert card.zone == stolen_land.zone == Zone.HAND
    assert token not in engine.state.player_by_id("a").hand
    _pick(engine, "a", stolen_land)
    assert engine.state.pending_choice["options"] == [{"id": "decline", "label": "Auswahl abschließen"}]
    _pick(engine, "a")
    assert stolen_land.controller_id == "a" and stolen_land.zone == Zone.BATTLEFIELD
    assert source.zone == Zone.EXILE


def test_aurora_commander_replacement_does_not_count_as_shuffled():
    engine = _engine()
    source = _object(engine, "a", "The Great Aurora", "Sorcery", AURORA)
    commander = _object(engine, "b", "Commander", zone=Zone.BATTLEFIELD)
    commander.is_commander = True
    library_card = _object(engine, "b", "Undrawn Bear", zone=Zone.LIBRARY)
    _apply(engine, source)
    assert engine.state.pending_choice["player_id"] == "b"
    assert commander.zone == Zone.BATTLEFIELD
    engine.resolve_pending_choice("command")
    assert commander.zone == Zone.COMMAND
    assert library_card.zone == Zone.LIBRARY
    _pick(engine, "a")



def test_aura_can_enchant_an_existing_host_but_not_a_simultaneous_entrant():
    engine = _engine()
    source = _object(engine, "a", "Show and Tell", "Sorcery", SHOW)
    host = _object(engine, "a", "Existing Bear", zone=Zone.BATTLEFIELD)
    entrant = _object(engine, "b", "New Bear")
    aura = _object(engine, "a", "Test Aura", "Enchantment — Aura", "Enchant creature")
    _apply(engine, source)
    _pick(engine, "a", aura)
    _pick(engine, "b", entrant)
    assert engine.state.pending_choice["kind"] == "hand_entry_attachment"
    assert [option["instance_id"] for option in engine.state.pending_choice["options"]] == [host.instance_id]
    _pick(engine, "a", host)
    assert aura.attached_to == host.instance_id
    assert entrant.zone == aura.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("text", [
    "Each player may put a creature card from their graveyard onto the battlefield.",
    "Each opponent may put a blue creature card from their hand onto the battlefield.",
    "Starting with you, each player may put a creature card from their hand onto the battlefield.",
])
def test_unsupported_group_shapes_fail_closed(text):
    assert match_clause(text.lower().rstrip(".")) is None


def test_gateway_offers_historic_permanents_including_battles():
    engine = _engine()
    source = _object(engine, "a", "Thran Temporal Gateway", "Legendary Artifact",
                     "{4}, {T}: You may put a historic permanent card from your hand onto the battlefield.",
                     Zone.BATTLEFIELD)
    battle = _object(engine, "a", "Legendary Battle", "Legendary Battle — Siege")
    _object(engine, "a", "Legendary Spell", "Legendary Sorcery")
    _object(engine, "a", "Ordinary Bear")
    _apply(engine, source)
    assert [option["instance_id"] for option in engine.state.pending_choice["options"]
            if "instance_id" in option] == [battle.instance_id]


def test_bird_from_graveyard_enters_with_finality_counter():
    engine = _engine()
    bird = _object(engine, "a", "Bird", "Creature — Bird", zone=Zone.GRAVEYARD)
    _object(engine, "a", "Bird kindred spell", "Kindred Instant — Bird")
    specs = match_clause("you may put a bird creature card from your hand or graveyard "
                         "onto the battlefield with a finality counter on it")
    build_effects(specs, None)[0].apply(engine.rules.context)
    _pick(engine, "a", bird)
    assert bird.zone == Zone.BATTLEFIELD
    assert bird.counters["finality"] == 1
