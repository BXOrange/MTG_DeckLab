"""Summoning-sickness state exposed to the board (RULE 302.6 / 702.10)."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player


def _creature(*, keywords=None) -> Card:
    return Card(
        id="test-creature",
        name="Test Creature",
        type_line="Creature — Test",
        is_creature=True,
        power=2,
        toughness=2,
        keywords=keywords or [],
    )


def test_summoning_sickness_is_exposed_only_for_non_hasty_battlefield_creatures():
    ordinary = GameObject(_creature(), owner_id="p1", zone=Zone.BATTLEFIELD)
    ordinary.summoning_sick = True
    assert ordinary.to_dict()["summoning_sick"] is True

    printed_haste = GameObject(_creature(keywords=["Haste"]), owner_id="p1", zone=Zone.BATTLEFIELD)
    printed_haste.summoning_sick = True
    assert printed_haste.to_dict()["summoning_sick"] is False

    granted_haste = GameObject(_creature(), owner_id="p1", zone=Zone.BATTLEFIELD)
    granted_haste.summoning_sick = True
    granted_haste._granted_keywords.add("haste")
    assert granted_haste.to_dict()["summoning_sick"] is False


def test_personal_zones_clear_the_battlefield_only_sickness_marker():
    player = Player(id="p1", name="Player")
    for zone in (Zone.HAND, Zone.COMMAND):
        obj = GameObject(_creature(), owner_id=player.id, zone=zone)
        obj.summoning_sick = True
        player.add_to_zone(obj, zone)
        assert obj.summoning_sick is False
        assert obj.to_dict()["summoning_sick"] is False
