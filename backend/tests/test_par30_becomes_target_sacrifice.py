"""PAR-30 — the Illusion cycle's "When ~ becomes the target of a spell or
ability, sacrifice it."

`_BECOMES_TARGET_TRIGGER_RE` only accepted "Whenever"; the ~19-card Illusion
cycle (Phantasmal Bear, Frost Walker, Skulking Ghost, …) prints "When",
which is interchangeable here. The engine side (`EventType.BECOMES_TARGET`
+ `SacrificeSelfEffect`) is MEC-19.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.events import EventType
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present"
)

_PROV = ParserProvenance(version="test", source="rule:oracle", confidence=1.0)


def _card(name):
    c = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if c is None:
        pytest.skip(f"{name!r} not cached")
    return c


def test_when_and_whenever_parse_identically():
    specs = []
    for text in (
        "when ~ becomes the target of a spell or ability, sacrifice it.",
        "whenever ~ becomes the target of a spell or ability, sacrifice it.",
    ):
        seg = segment_line(text, allow_spell_effect=False, provenance=_PROV)
        assert seg.claimed
        assert seg.spec.trigger["event"] == "BECOMES_TARGET"
        assert seg.spec.trigger["condition"] == {"subject": "self"}
        assert [e.type for e in seg.spec.effects] == ["sacrifice_self"]
        specs.append(seg.spec)


def test_illusion_cycle_modeled():
    for name in (
        "Phantasmal Bear", "Frost Walker", "Illusionary Servant",
        "Skulking Ghost", "Phantom Beast",
    ):
        assert parse_oracle(_card(name)).modeled is True, name


def test_execute_illusion_sacrificed_when_targeted_by_a_spell():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    st = eng.state

    bear = GameObject(_card("Phantasmal Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    bind_from_catalogue(bear)
    st.add_to_battlefield(bear)

    bolt = GameObject(_card("Lightning Bolt"), owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(bolt)
    st.player_by_id("p2").hand.append(bolt)

    while st.current_phase != "precombat_main":
        eng.advance_step()
    st.player_by_id("p2").mana_pool.add("R", 1)

    before = len(st.event_log)
    eng.cast_spell(st.player_by_id("p2"), bolt, targets=[bear])
    eng.resolve_until_stable()

    assert any(e.type == EventType.BECOMES_TARGET for e in st.event_log[before:])
    assert bear.zone == Zone.GRAVEYARD
