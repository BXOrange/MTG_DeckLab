"""PAR-137 — impulse draw ("Exile the top N cards of your library. You may play them …").

The ticket's premise ("no parser row emits `impulsive_draw`") was already stale: `exile_top_play`
existed. What was missing were its variants: the window word "until end of turn", and a *choice* of
one exiled card ("choose 1 of them. You may play that card …" / "you may play 1 of those cards"),
which keeps the permission on the pick alone (`ImpulsiveDrawEffect.choose_one`). Two general parser
fixes rode along: a clause row written for several sentences is now tried over a window of
consecutive sentences when a body is split on periods, and "…, where x is `<phrase>`. `<more>`"
(the definition mid-body) reads the same as with the definition last.

Reference: parser/oracle/catalogue/handlers.py (`_EXILE_TOP_PLAY_RE`), segmenter.py
(`_MAX_SENTENCE_WINDOW`, `_WHERE_X_MID_BODY_RE`), game/effects/library.py (`ImpulsiveDrawEffect`),
game/rules/misc_mixin.py (``grant_temp_play_*`` actions).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Sorcery", cost="{1}", cmc=1, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.players[0]


def _stock(player, *names):
    for name in reversed(names):
        player.library.append(GameObject(_card(name), owner_id="p1", zone=Zone.LIBRARY))


def _cast(eng, player, oracle_text):
    obj = GameObject(_card("Impulse Spell", cost="", cmc=0, oracle_text=oracle_text), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    eng.rules.cast_spell(player, obj)
    eng.resolve_until_stable()


def _playable(eng, player):
    return sorted(o.name for o in player.exile if o.instance_id in eng.state.temp_play_permissions)


# --- parse -----------------------------------------------------------------


@pytest.mark.parametrize(("clause", "params"), [
    ("exile the top 3 cards of your library. until end of turn, you may play those cards",
     {"count": 3, "same_turn_only": True}),
    ("exile the top 5 cards of your library. you may play cards exiled this way until the end of your next turn",
     {"count": 5, "same_turn_only": False}),
    ("exile the top card of your library. you may play it this turn", {"count": 1, "same_turn_only": True}),
    ("exile the top 2 cards of your library. choose 1 of them. until end of turn, you may play that card",
     {"count": 2, "same_turn_only": True, "choose_one": True}),
    ("exile the top 3 cards of your library, then choose 1 of them. you may play that card this turn",
     {"count": 3, "same_turn_only": True, "choose_one": True}),
    ("exile the top 2 cards of your library. you may play 1 of those cards until end of turn",
     {"count": 2, "same_turn_only": True, "choose_one": True}),
])
def test_impulse_variants_parse(clause, params):
    specs = match_clause(clause)
    assert [(s.type, s.params) for s in specs] == [("impulsive_draw", params)]


@pytest.mark.parametrize("clause", [
    # "that card" with several exiled and no choice names no particular card
    "exile the top 3 cards of your library. you may play that card this turn",
    # a choice must be followed by the pick, not "them"
    "exile the top 3 cards of your library. choose 1 of them. you may play them this turn",
])
def test_impulse_refuses_a_referent_it_cannot_resolve(clause):
    assert match_clause(clause) is None


def test_row_written_for_two_sentences_is_claimed_inside_a_longer_body():
    specs = parse_effect_body(
        "target creature gets +3/+1 and gains haste until end of turn. exile the top 2 cards of your library. "
        "until the end of your next turn, you may play those cards."
    )
    assert [s.type for s in specs] == ["pump", "impulsive_draw"]
    assert specs[1].params == {"count": 2, "same_turn_only": False}


def test_where_x_defined_mid_body_binds_the_count():
    specs = parse_effect_body(
        "exile the top x cards of your library, where x is the number of creatures you control. "
        "you may play those cards this turn."
    )
    assert [s.type for s in specs] == ["bind"]
    assert specs[0].params["effects"] == [
        {"type": "impulsive_draw", "params": {"count": "$n", "same_turn_only": True}}
    ]


# --- execute ---------------------------------------------------------------


def test_play_them_grants_permission_to_every_exiled_card():
    eng, p1 = _engine()
    _stock(p1, "A", "B", "C", "Deep")
    _cast(eng, p1, "Exile the top 3 cards of your library. Until end of turn, you may play those cards.")
    assert _playable(eng, p1) == ["A", "B", "C"]
    assert [o.name for o in p1.library] == ["Deep"]


def test_choose_one_keeps_permission_on_the_pick_alone():
    eng, p1 = _engine()
    _stock(p1, "A", "B", "C", "Deep")
    _cast(eng, p1, "Exile the top 3 cards of your library. Choose 1 of them. You may play that card this turn.")
    pending = eng.state.pending_choice
    assert pending is not None and pending["action"] == "grant_temp_play_same_turn"
    assert _playable(eng, p1) == []  # nothing is playable until the pick is made
    pick = next(o for o in pending["options"] if o.get("label") == "B")
    eng.rules.resolve_choice(pick["instance_id"])
    assert _playable(eng, p1) == ["B"]
    assert sorted(o.name for o in p1.exile) == ["A", "B", "C"]  # the other two stay exiled, unplayable
    assert eng.state.temp_play_permission_same_turn_only >= {o.instance_id for o in p1.exile if o.name == "B"}


def test_next_turn_window_is_not_marked_same_turn_only():
    eng, p1 = _engine()
    _stock(p1, "A", "B", "Deep")
    _cast(eng, p1, "Exile the top 2 cards of your library. You may play 1 of those cards until the end of your next turn.")
    pick = next(o for o in eng.state.pending_choice["options"] if o.get("label") == "A")
    eng.rules.resolve_choice(pick["instance_id"])
    a = next(o for o in p1.exile if o.name == "A")
    assert a.instance_id in eng.state.temp_play_permissions
    assert a.instance_id not in eng.state.temp_play_permission_same_turn_only
