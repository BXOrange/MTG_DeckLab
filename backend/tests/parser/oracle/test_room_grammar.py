"""Rooms in the oracle-text front-end (RULE 709.5, MEC-111): door triggers, unlock instructions, door counts, and a
Room's verdict reading *both* halves."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.card_registry import is_authored_card
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_amount_phrase, parse_count_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body, segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase

_PROVENANCE = ParserProvenance(version="test", source="test")


def _segment(line):
    """One printed line through the same normalisation `parse_oracle` applies (self-references, ability words)."""
    return segment_line(normalize(line, "Test Room", None), allow_spell_effect=False, provenance=_PROVENANCE)


def test_unlock_this_door_is_a_door_scoped_self_trigger():
    seg = _segment("when you unlock this door, draw a card.")
    assert seg.claimed
    assert seg.spec.trigger == {"event": "DOOR_UNLOCKED", "condition": {"subject": "self"}, "filter": {"door": "this"}}
    assert [e.type for e in seg.spec.effects] == ["draw"]


def test_this_room_is_the_source():
    seg = _segment("when you unlock this door, this room deals 2 damage to target creature.")
    assert seg.claimed and seg.spec.effects[0].type == "damage"


def test_fully_unlocking_a_room_and_entering_enchantments_are_two_heads_of_one_ability():
    seg = _segment("eerie — whenever an enchantment you control enters and whenever you fully unlock a room, draw a card.")
    events = [seg.spec.trigger["event"], *[s.trigger["event"] for s in seg.extra_specs]]
    assert sorted(events) == ["ENTERS_BATTLEFIELD", "ROOM_FULLY_UNLOCKED"]


def test_unlock_instructions():
    [targeted] = parse_effect_body("unlock a locked door of up to 1 target room you control.")
    assert (targeted.type, targeted.params) == ("unlock_door", {"target_kind": "room_you_control", "optional": True})
    [chosen] = parse_effect_body("unlock a locked door of a room you control.")
    assert (chosen.type, chosen.params) == ("unlock_door", {})
    [either] = parse_effect_body("lock or unlock a door of target room you control.")
    assert either.params == {"target_kind": "room_you_control", "lock_or_unlock": True}


def test_unlocked_doors_among_rooms_you_control_are_counted_by_designation():
    amount = parse_amount_phrase("the number of unlocked doors among rooms you control")
    assert amount == {"zone": "battlefield", "of": "you", "filter": {"subtype": "room"},
                      "aggregate": "sum", "value": "unlocked_doors"}
    condition = parse_count_condition("there are 2 or more unlocked doors among rooms you control")
    assert condition["kind"] == "control_count" and condition["min"] == 2 and condition["selector"] == amount
    names = parse_count_condition("there are 8 or more different names among unlocked doors of rooms you control")
    assert names["selector"]["distinct"] == "door_name"


def test_a_rooms_coverage_reads_both_halves():
    db = CardDatabase(DB_PATH)
    # Charred Foyer's front half (an upkeep exile-and-play trigger) parses on its own; its back half does not.
    foyer = db.get_card("Charred Foyer // Warped Space")
    assert not parse_oracle(foyer).modeled
    # Grand Entryway // Elegant Rotunda: both halves are ordinary door triggers.
    assert parse_oracle(db.get_card("Grand Entryway // Elegant Rotunda")).modeled


def test_a_room_counts_as_authored_only_when_every_half_is_covered():
    db = CardDatabase(DB_PATH)
    assert is_authored_card(db.get_card("Experimental Lab // Staff Room"))  # both halves hand-authored
    assert not is_authored_card(db.get_card("Charred Foyer // Warped Space"))  # nothing registered
    assert not is_authored_card(db.get_card("Forest"))
