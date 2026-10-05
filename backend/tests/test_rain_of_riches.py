"""Rain of Riches grants spell-owned cascade from real Treasure payments."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _game, _card
from tests.test_weathered_sentinels import _to


def _position():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    _to(engine, "p1", "main1")
    rain = _card(engine, "Rain of Riches", zone=Zone.HAND)
    p1.mana_pool.add("R", 5)
    engine.cast_spell(p1, rain)
    engine.resolve_until_stable()
    treasures = [obj for obj in engine.state.battlefield if obj.name == "Treasure"]
    assert len(treasures) == 2
    p1.library.clear()
    return engine, rain, treasures


def _treasure_cast(engine, treasure, name="Elvish Mystic"):
    p1 = engine.state.player_by_id("p1")
    engine.tap_for_mana(p1, treasure, option_index=4)  # green, sacrifice the actual Treasure
    spell = _card(engine, name, zone=Zone.HAND)
    engine.cast_spell(p1, spell)
    return spell


def test_entry_creates_two_treasures_and_first_treasure_cast_gets_cascade():
    engine, rain, treasures = _position()
    hit = _card(engine, "Memnite", zone=Zone.LIBRARY)
    spell = _treasure_cast(engine, treasures[0])
    assert spell.mana_spent_to_cast_treasure == 1
    assert treasures[0].zone != Zone.BATTLEFIELD
    engine.rules.destroy(rain)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "play_during_resolution"
    assert choice["instance_ids"] == [hit.instance_id]
    assert engine.state.stack[-1].obj is spell
    engine.play_resolution_card(engine.state.player_by_id("p1"), hit)
    assert [item.obj for item in engine.state.stack] == [spell, hit]
    engine.resolve_until_stable()
    assert spell.zone == hit.zone == Zone.BATTLEFIELD


def test_non_treasure_spell_does_not_consume_first_qualifying_cast():
    engine, _, treasures = _position()
    p1 = engine.state.player_by_id("p1")
    ordinary = _card(engine, "Llanowar Elves", zone=Zone.HAND)
    p1.mana_pool.add("G", 1)
    engine.cast_spell(p1, ordinary)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    hit = _card(engine, "Memnite", zone=Zone.LIBRARY)
    _treasure_cast(engine, treasures[0])
    engine.resolve_until_stable()
    assert engine.state.pending_choice["instance_ids"] == [hit.instance_id]
    engine.resolve_pending_choice("decline")
    assert hit.zone == Zone.LIBRARY
    engine.resolve_until_stable()
    _treasure_cast(engine, treasures[1], "Llanowar Elves")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None  # the second Treasure-funded spell has no cascade


def test_cascade_hit_keeps_ordinary_target_selection():
    engine, _, treasures = _position()
    p1, p2 = engine.state.players
    hit = _card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    p1.mana_pool.add("C", 1)
    _treasure_cast(engine, treasures[0], "Nature's Lore")
    engine.resolve_until_stable()
    offer = next(a for a in engine.resolution_play_actions(p1) if a["type"] == "cast_spell")
    assert offer["instance_id"] == hit.instance_id
    with pytest.raises(ValueError):
        engine.play_resolution_card(p1, hit)
    assert hit.zone == Zone.EXILE and engine.state.pending_choice
    engine.play_resolution_card(p1, hit, targets=[p2])
    assert p2.life == 20  # the free spell waits on the stack
    engine.rules.resolve_top_of_stack()
    assert p2.life == 17


def test_grant_does_not_consume_a_cast_before_the_enchantment_enters():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    _to(engine, "p1", "main1")
    earlier = _card(engine, "Llanowar Elves", zone=Zone.HAND)
    p1.mana_pool.add("G", 1, source_kind="treasure")
    engine.cast_spell(p1, earlier)
    engine.resolve_until_stable()
    _card(engine, "Rain of Riches")
    p1.library.clear()
    _card(engine, "Memnite", zone=Zone.LIBRARY)
    later = _card(engine, "Elvish Mystic", zone=Zone.HAND)
    p1.mana_pool.add("G", 1, source_kind="treasure")
    engine.cast_spell(p1, later)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None  # "first" counts casts even before Rain was present


def test_specs_are_fresh():
    engine = _game()
    rain = _card(engine, "Rain of Riches")
    first, second = specs_for(rain.card), specs_for(rain.card)
    first[1].effects[0].params["keywords"].clear()
    assert second[1].effects[0].params["keywords"] == ["cascade"]
    assert len(rain.triggered_abilities) == 1 and len(rain.static_effects) == 1


def test_first_qualifying_cast_resets_on_the_next_turn():
    engine, _, treasures = _position()
    hit = _card(engine, "Memnite", zone=Zone.LIBRARY)
    _treasure_cast(engine, treasures[0])
    engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    p1 = engine.state.player_by_id("p1")
    p1.library.clear()
    for _ in range(4):
        _card(engine, "Forest", zone=Zone.LIBRARY)
    _to(engine, "p2", "main1")
    _to(engine, "p1", "main1")
    hit = _card(engine, "Memnite", zone=Zone.LIBRARY)
    _treasure_cast(engine, treasures[1], "Llanowar Elves")
    engine.resolve_until_stable()
    assert engine.state.pending_choice["instance_ids"] == [hit.instance_id]


def test_two_enchantments_grant_two_separate_spell_owned_triggers():
    engine, _, treasures = _position()
    _card(engine, "Rain of Riches")
    spell = _treasure_cast(engine, treasures[0])
    firings = [ability for ability, _ in engine.rules.pending_triggers
               if ability.description == f"{spell.name}: Cascade"]
    assert len(firings) == 2
    assert all(ability.source is spell and ability.controller_id == "p1" for ability in firings)


def test_opponent_cast_does_not_receive_cascade():
    engine, _, _ = _position()
    p2 = engine.state.player_by_id("p2")
    _to(engine, "p2", "main1")
    spell = _card(engine, "Elvish Mystic", player="p2", zone=Zone.HAND)
    p2.mana_pool.add("G", 1, source_kind="treasure")
    engine.cast_spell(p2, spell)
    assert not any(ability.description == f"{spell.name}: Cascade"
                   for ability, _ in engine.rules.pending_triggers)


def test_cascade_threshold_captures_announced_x_even_after_spell_is_countered():
    engine, _, treasures = _position()
    p1 = engine.state.player_by_id("p1")
    hit = _card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    equal = _card(engine, "Solemn Simulacrum", zone=Zone.LIBRARY)
    engine.tap_for_mana(p1, treasures[0], option_index=4)
    p1.mana_pool.add("C", 3)
    spell = _card(engine, "Green Sun's Zenith", zone=Zone.HAND)
    engine.cast_spell(p1, spell, x=3)
    engine.rules.counter_spell(spell)
    assert spell.zone == Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert engine.state.pending_choice["instance_ids"] == [hit.instance_id]
    assert equal.zone == Zone.EXILE
    engine.resolve_pending_choice("decline")
    assert equal.zone == hit.zone == Zone.LIBRARY


@pytest.mark.parametrize("name,threshold", [
    ("Bala Ged Recovery // Bala Ged Sanctuary", 4),
    ("Valki, God of Lies // Tibalt, Cosmic Impostor", 3),
])
def test_cascade_rejects_land_or_expensive_back_face(name, threshold):
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    p1.library.clear()
    hit = _card(engine, name, zone=Zone.LIBRARY)
    engine.rules._request_cascade(p1, threshold)
    actions = engine.resolution_play_actions(p1)
    assert not any(a.get("face") == "back" for a in actions)
    with pytest.raises(ValueError):
        engine.play_resolution_card(p1, hit, face="back")
    assert hit.zone == Zone.EXILE
    engine.resolve_pending_choice("decline")
    assert hit.zone == Zone.LIBRARY
