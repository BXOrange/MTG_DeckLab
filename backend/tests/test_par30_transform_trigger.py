"""PAR-30 (Threaten / O-Ring trailing items) — the "enters or transforms
into ~" compound trigger (Brutal Cathar).

New `EventType.TRANSFORMED` (fired by `RulesEngine.transform_permanent`
after the face flip + ability rebind, so the payload names the new face and
the freshly-bound trigger is already attached). `segmenter._SELF_MULTI_
EVENT_RE` accepts "transforms into ~" as a verb slot → the existing
`trigger["event"]`-list shape (one `TriggeredAbility` per event).
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine

_PROV = ParserProvenance(version="test", source="rule:oracle", confidence=1.0)


def test_segment_enters_or_transforms_into_self():
    seg = segment_line(
        "whenever ~ enters or transforms into ~, exile target creature an "
        "opponent controls until ~ leaves the battlefield.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == ["ENTERS_BATTLEFIELD", "TRANSFORMED"]
    assert seg.spec.trigger["condition"] == {"subject": "self"}
    # + the companion LEAVES_BATTLEFIELD return
    assert any(x.effects[0].type == "return_linked_exile" for x in seg.extra_specs)


def test_segment_fails_closed_on_unknown_verb_in_compound():
    seg = segment_line(
        "whenever ~ enters or glorbles, draw a card.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert not seg.claimed


def test_real_brutal_cathar_modeled():
    c = CardDatabase(DEFAULT_DB_PATH).get_card("Brutal Cathar")
    assert c is not None
    r = parse_oracle(c)
    assert r.modeled is True
    trig = next(s for s in r.specs if s.ability_kind == "triggered"
                and isinstance((s.trigger or {}).get("event"), list))
    assert set(trig.trigger["event"]) == {"ENTERS_BATTLEFIELD", "TRANSFORMED"}


def test_execute_transform_into_front_fires_the_trigger():
    # Huntmaster of the Fells: "Whenever this creature enters or transforms
    # into Huntmaster of the Fells, create a 2/2 green Wolf creature token
    # and you gain 2 life." (no Daybound, no target — a clean check that the
    # back->front flip fires TRANSFORMED and the bound trigger resolves).
    db = CardDatabase(DEFAULT_DB_PATH)
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    hm = GameObject(db.get_card("Huntmaster of the Fells"), owner_id="p1",
                    zone=Zone.BATTLEFIELD)
    hm.controller_id = "p1"
    st.add_to_battlefield(hm)
    bind_from_catalogue(hm)
    p1 = st.player_by_id("p1")
    life0 = p1.life

    assert eng.rules.transform_permanent(hm) is True   # front -> back (Ravager)
    assert hm.transformed is True
    eng.resolve_until_stable()
    wolves_after_back = [o for o in st.battlefield
                         if getattr(o, "is_token", False) and "Wolf" in o.name]
    assert wolves_after_back == []

    assert eng.rules.transform_permanent(hm) is True   # back -> "into Huntmaster"
    assert hm.transformed is False
    eng.resolve_until_stable()
    wolves = [o for o in st.battlefield
              if getattr(o, "is_token", False) and "Wolf" in o.name]
    assert len(wolves) == 1
    assert p1.life == life0 + 2


def test_transformed_event_carries_face_name_and_instance():
    from mtg_analyzer.models.events import EventType

    db = CardDatabase(DEFAULT_DB_PATH)
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    seen = []
    st.subscribe(lambda ev: seen.append(ev) if ev.type == EventType.TRANSFORMED else None)
    hm = GameObject(db.get_card("Huntmaster of the Fells"), owner_id="p1",
                    zone=Zone.BATTLEFIELD)
    hm.controller_id = "p1"
    st.add_to_battlefield(hm)
    bind_from_catalogue(hm)
    eng.rules.transform_permanent(hm)
    assert seen and seen[-1].get("instance_id") == hm.instance_id
    assert seen[-1].get("face_name") == hm.name
