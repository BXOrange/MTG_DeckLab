"""BUG-11: the parse-cache key must cover every card attribute the parser reads."""
import re
from pathlib import Path

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import gate
from mtg_analyzer.parser.oracle.gate import _parse_cache_key, parse_oracle

# Attributes gate.py reads that are deliberately not part of the key (derived or unused for parsing).
_NOT_KEYED: frozenset[str] = frozenset()


def _card(**kw):
    base = dict(id="x", name="Atmospheric Greenhouse", type_line="Artifact — Spacecraft",
                oracle_text="Station", keywords=["Station"])
    base.update(kw)
    return Card(**base)


def test_key_distinguishes_vehicle_pt_and_layout():
    assert _parse_cache_key(_card(vehicle_power=5)) != _parse_cache_key(_card(vehicle_power=10))
    assert _parse_cache_key(_card(vehicle_toughness=4)) != _parse_cache_key(_card(vehicle_toughness=5))
    assert _parse_cache_key(_card(layout="split")) != _parse_cache_key(_card(layout="normal"))


def test_station_pt_not_shared_via_cache():
    text = "Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 8+.)\nSTATION 8+\nFlying\nWhenever you cast a spell, draw a card."
    a = parse_oracle(_card(oracle_text=text, vehicle_power=5, vehicle_toughness=4))
    b = parse_oracle(_card(oracle_text=text, vehicle_power=10, vehicle_toughness=4))
    pw = lambda r: [e.params.get("power") for s in r.specs for e in (s.effects or []) if e.type == "type_change"]
    assert pw(a) and pw(b)
    assert pw(a) != pw(b)


def test_every_getattr_card_field_is_keyed():
    src = Path(gate.__file__).read_text()
    read = set(re.findall(r'getattr\(card, "([a-z_]+)"', src))
    keyed = set(re.findall(r'getattr\(card, "([a-z_]+)"',
                           src[src.index("def _parse_cache_key"):src.index("_NAMED_MODE_STATIC_EFFECTS")]))
    assert read - keyed - _NOT_KEYED == set()
