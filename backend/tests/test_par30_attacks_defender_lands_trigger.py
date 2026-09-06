"""PAR-30 "Tapped and attacking" trail — the qualified attack trigger
"whenever ~ attacks a player who controls N or more lands" (Owlbear Cub).

Still a `{"subject": "self"}` ATTACKS trigger, but carries a
`defender_controls_lands_at_least` key, gated in
`effect_binder._trigger_condition` off the ATTACKS event's
`defending_player_id`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import GameEvent, EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _segment(text):
    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


# --- parse ---------------------------------------------------------------


def test_qualified_attack_trigger_parses():
    seg = _segment(
        "whenever ~ attacks a player who controls 8 or more lands, draw a card"
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "ATTACKS"
    assert seg.spec.trigger["condition"] == {"subject": "self"}
    assert seg.spec.trigger["defender_controls_lands_at_least"] == 8


def test_plain_attacks_a_player_has_no_land_key():
    seg = _segment("whenever ~ attacks a player, draw a card")
    assert seg.claimed
    assert "defender_controls_lands_at_least" not in seg.spec.trigger


def test_owlbear_cub_modeled():
    c = Card(
        id="oc", name="Owlbear Cub", type_line="Creature — Bear", is_creature=True,
        oracle_text=(
            "Whenever Owlbear Cub attacks a player who controls "
            "8 or more lands, look at the top 8 cards of your library. You "
            "may put a creature card from among them onto the battlefield tapped "
            "and attacking that player. Put the rest on the bottom of your library "
            "in a random order."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute: the binder predicate ------------------------------------


def _bound(threshold):
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    src = GameObject(Card(id="s", name="S", type_line="Creature", is_creature=True,
                          power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    spec = AbilitySpec(
        "triggered", effects=[EffectSpec("draw", {"count": 1})],
        trigger={"event": "ATTACKS", "condition": {"subject": "self"},
                 "defender_controls_lands_at_least": threshold},
    )
    return eng, st, src, bind_ability(spec, src)


class _Ctx:
    def __init__(self, st):
        self.state = st


def _add_lands(st, pid, n):
    for i in range(n):
        land = GameObject(Card(id=f"{pid}l{i}", name="Forest",
                               type_line="Basic Land — Forest"),
                          owner_id=pid, zone=Zone.BATTLEFIELD)
        land.controller_id = pid
        st.add_to_battlefield(land)


def test_predicate_false_below_threshold():
    eng, st, src, ab = _bound(3)
    _add_lands(st, "p2", 2)
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is False


def test_predicate_true_at_threshold():
    eng, st, src, ab = _bound(3)
    _add_lands(st, "p2", 3)
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is True


def test_predicate_counts_only_the_defenders_lands():
    eng, st, src, ab = _bound(3)
    _add_lands(st, "p1", 5)   # attacker's own lands don't count
    _add_lands(st, "p2", 1)
    ev = GameEvent(EventType.ATTACKS, player_id="p1",
                   instance_id=src.instance_id, defending_player_id="p2")
    assert ab.condition(ev, _Ctx(st)) is False
