"""PAR-120 (sub-item (b), "sum-based counts") — "creatures you control have
total power N or greater/less" as a standing condition (RULE 613.6/603.4).

No new engine primitive: `continuous.count_selector`'s own `"total_power_
creatures_you_control"` branch already existed (PAR-60, Volcanic Salvo's
cost reduction), and `static_conditions.py`'s `control_count` kind already
calls `count_selector` generically for whatever selector name it's given —
a `min`/`max` threshold on a *sum* needs no different condition kind than
one on a plain count. The gap was purely recognition.

Two rows, not one: `static_condition()` (the single function "as long
as"/leading-"if"/trigger-"while" all hand their condition text to) covers
three of the four surfaces this phrase appears on. "Activate only if …" is
a genuinely *separate*, narrower vocabulary
(`catalogue.handlers._ACTIVATION_CONDITION_RES`) that already duplicates a
few of `_STATIC_CONDITION_RES`'s own rows by hand rather than falling back
to it — a real, pre-existing instance of the duplication this whole ticket
is about, just not fixed at the architecture level here, only given its
own matching row for this one phrase.

`parser_probe.py diff`: +91 (vs. +78 before this closure), 0 regressed.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _creature(state, name, power, controller="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=power),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER: the condition itself
# ---------------------------------------------------------------------------


def test_total_power_or_greater():
    assert static_condition("creatures you control have total power 8 or greater") == {
        "kind": "control_count", "selector": "total_power_creatures_you_control", "min": 8,
    }


def test_total_power_or_less():
    assert static_condition("creatures you control have total power 4 or less") == {
        "kind": "control_count", "selector": "total_power_creatures_you_control", "max": 4,
    }


def test_an_unrelated_phrase_fails_closed():
    assert static_condition("creatures you control have total toughness 8 or greater") is None


def test_activation_condition_surface_reads_the_same_condition():
    # "Activate only if …" doesn't route through `static_condition()` at all
    # — it's a *separate*, narrower vocabulary
    # (`catalogue.handlers._ACTIVATION_CONDITION_RES`) that already
    # duplicates a few of `_STATIC_CONDITION_RES`'s own rows by hand rather
    # than falling back to it, so this phrase needed its own row there too,
    # not just in `static_condition`'s table.
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(
        "activate only if creatures you control have total power 8 or greater"
    ) == [EffectSpec("activation_condition_marker", {"condition": {
        "kind": "control_count", "selector": "total_power_creatures_you_control", "min": 8,
    }})]


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards, each surface this condition reaches
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Owlbear Shepherd",  # leading "if" on a phase trigger
        "Kirk, Enterprising Captain",  # trigger "while" tail
        "La'An Noonien-Singh, Security",  # trigger "while" tail, second card
        "Cantankerous Captain",  # trailing "if" on a resolving effect
        "Atarka Beastbreaker",  # "activate only if" on an activated ability
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_owlbear_shepherd_draws_only_once_total_power_reaches_the_threshold():
    eng, state, p1, p2 = _engine()
    p1.library.append(GameObject(
        Card(id="l0", name="L0", type_line="Plains", is_land=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))
    source = GameObject(_db().get_card("Owlbear Shepherd"), owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    bind_from_catalogue(source)
    state.add_to_battlefield(source)
    _creature(state, "Bear", power=3)

    state.active_player_index = 0  # p1's own turn
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 0  # 3 power total — below the threshold of 8

    _creature(state, "Wurm", power=6)
    p1.library.append(GameObject(
        Card(id="l1", name="L1", type_line="Plains", is_land=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == 1  # 3 + 6 = 9 — at or above 8 now
