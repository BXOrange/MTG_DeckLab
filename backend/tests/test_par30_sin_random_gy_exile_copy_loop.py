"""PAR-30 "copy of a named card" body singletons (v198) — Sin, Spira's
Punishment.

`RandomGraveyardExileCopyLoopEffect` / `random_graveyard_exile_copy_loop`:
"Exile a permanent card from your graveyard at random, then create a
tapped token that's a copy of that card. If the exiled card is a land
card, repeat this process." — RULE 706 randomization + RULE 707.2 token
copy, looped while each exiled card is a land.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import EffectSpec, ParserProvenance


def _segment(text):
    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


# --- parse -----------------------------------------------------------


def test_sin_body_maps_to_loop_effect():
    seg = _segment(
        "whenever ~ enters or attacks, exile a permanent card from your "
        "graveyard at random, then create a tapped token that's a copy of "
        "that card. if the exiled card is a land card, repeat this process."
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == ["ENTERS_BATTLEFIELD", "ATTACKS"]
    assert [e.type for e in seg.spec.effects] == ["random_graveyard_exile_copy_loop"]


def test_sin_card_modeled():
    c = Card(
        id="sin", name="Sin, Spira's Punishment",
        type_line="Legendary Creature — Demon", is_creature=True,
        oracle_text=(
            "Flying\nWhenever Sin enters or attacks, exile a permanent card "
            "from your graveyard at random, then create a tapped token that's "
            "a copy of that card. If the exiled card is a land card, repeat "
            "this process."
        ),
    )
    assert parse_oracle(c).coverage != UNMODELED


# --- execute -------------------------------------------------------


def _engine_with_sin(gy):
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    sin = GameObject(
        Card(id="sin", name="Sin", type_line="Legendary Creature — Demon",
             is_creature=True, power=4, toughness=4),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    sin.controller_id = "p1"
    eng.state.add_to_battlefield(sin)
    p1 = eng.state.player_by_id("p1")
    for cid, name, tl in gy:
        o = GameObject(Card(id=cid, name=name, type_line=tl),
                       owner_id="p1", zone=Zone.GRAVEYARD)
        o.controller_id = "p1"
        p1.graveyard.append(o)
    return eng, sin, p1


def _run(eng, sin):
    build_effects([EffectSpec("random_graveyard_exile_copy_loop", {})], sin)[0].apply(
        eng.rules.context, None
    )


def test_stops_on_a_nonland_and_ignores_spell_cards():
    eng, sin, p1 = _engine_with_sin([
        ("cr", "Bear", "Creature — Bear"),
        ("ins", "Bolt", "Instant"),   # not a permanent card — never picked
    ])
    _run(eng, sin)
    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert [t.name for t in toks] == ["Bear"]
    assert toks[0].tapped
    assert [o.name for o in p1.exile] == ["Bear"]
    assert [o.name for o in p1.graveyard] == ["Bolt"]  # the instant stays


def test_loops_through_every_land():
    eng, sin, p1 = _engine_with_sin([
        ("l1", "Island", "Basic Land — Island"),
        ("l2", "Forest", "Basic Land — Forest"),
        ("l3", "Swamp", "Basic Land — Swamp"),
    ])
    _run(eng, sin)
    toks = sorted(
        o.name for o in eng.state.battlefield if getattr(o, "is_token", False)
    )
    assert toks == ["Forest", "Island", "Swamp"]
    assert p1.graveyard == []
    assert sorted(o.name for o in p1.exile) == ["Forest", "Island", "Swamp"]


def test_no_permanent_cards_is_a_noop():
    eng, sin, p1 = _engine_with_sin([("ins", "Bolt", "Instant")])
    _run(eng, sin)
    assert not [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert [o.name for o in p1.graveyard] == ["Bolt"]
