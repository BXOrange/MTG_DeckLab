"""PAR-30 — `_NAMED_COUNTER_KINDS` widened.

The plain "put a `<kind>` counter on X" shape (`_ADD_NAMED_COUNTER_RE` /
`_add_named_counter`) recognized only {spore, burden, quest}. It now also
claims 26 pure card-text-driven counter kinds (charge, oil, storage, …) —
each verified to have *no* reader anywhere in `game/`, so the generic
free-string `AddCountersEffect.kind` path models them completely.

Keyword counters (RULE 122.1e — no layer-engine reader), subsystem
counters (age / time / level / loyalty / lore / rad / energy) and
replacement-carrying counters (stun / shield) stay out of the whitelist:
they would half-model.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse --------------------------------------------------------------------


def test_charge_counter_on_self_parses():
    assert match_clause("put a charge counter on ~") == [
        EffectSpec("add_counters", {"count": 1, "kind": "charge"})
    ]


def test_two_charge_counters_on_target_artifact_parses():
    assert match_clause("put 2 charge counters on target artifact") == [
        EffectSpec("add_counters", {"count": 2, "kind": "charge", "target_kind": "artifact"})
    ]


def test_various_new_kinds_parse():
    for kind in ("oil", "storage", "verse", "ki", "plague", "ice", "hour"):
        specs = match_clause(f"put a {kind} counter on ~")
        assert specs == [EffectSpec("add_counters", {"count": 1, "kind": kind})], kind


def test_keyword_counter_stays_unclaimed():
    # RULE 122.1e keyword counter — the layer engine has no reader, so this
    # must stay fail-closed rather than half-model.
    assert match_clause("put a flying counter on ~") is None
    assert match_clause("put an indestructible counter on ~") is None


def test_subsystem_counter_stays_unclaimed():
    # `age` (cumulative upkeep), `time` (vanishing), `level` (leveler) —
    # the engine keys off these by name; a generic bump would half-model.
    assert match_clause("put an age counter on ~") is None
    assert match_clause("put a level counter on ~") is None
    assert match_clause("put a stun counter on ~") is None


# --- real cards -------------------------------------------------------------


def test_long_range_sensor_modeled():
    c = Card(
        id="lrs", name="Long-Range Sensor", type_line="Artifact",
        oracle_text=(
            "Whenever you attack a player, put a charge counter on this artifact.\n"
            "{1}, Remove two charge counters from this artifact: Discover 4. "
            "Activate only as a sorcery."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_black_mana_battery_modeled():
    c = Card(
        id="bmb", name="Black Mana Battery", type_line="Artifact",
        oracle_text=(
            "{2}, {T}: Put a charge counter on this artifact.\n"
            "{T}, Remove any number of charge counters from this artifact: "
            "Add {B}, then add an additional {B} for each charge counter "
            "removed this way."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute --------------------------------------------------------------


def test_charge_counter_actually_lands_on_the_permanent():
    eng, state = _engine()
    art = GameObject(
        Card(id="a", name="Widget", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    art.controller_id = "p1"
    state.add_to_battlefield(art)

    build_effects([EffectSpec("add_counters", {"count": 2, "kind": "charge"})], art)[0].apply(
        GameContext(state, eng.rules), [art]
    )
    assert art.counters.get("charge", 0) == 2
