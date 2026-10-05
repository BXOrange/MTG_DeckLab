"""PAR-120 (sub-item (b), "sum-based counts" — combat-scoped sibling) —
"you attacked with creatures with total power N or greater this combat" as
an attack trigger's leading "if" condition (RULE 508.1/603.4).

No new condition kind: this is `control_count` again (the same kind this
session's board-wide "creatures you control have total power N or greater"
closure used) — only `continuous.count_selector` needed a new selector,
`total_power_attacking_creatures_you_control`, scoped to `GameObject.
attacking` the same way the pre-existing `attacking_creatures_you_control`
count scopes a plain count. The leading "if" on an ATTACKS trigger already
falls back to the shared `static_condition()` vocabulary generically
(segmenter.py's `_GENERIC_IF_PREFIX_RE`), so one new regex row closed the
whole Onslaught-block "Pack tactics" cluster at once.

`parser_probe.py diff`: +5 (Gnoll Hunter, Hobgoblin Captain, Intrepid
Outlander, Minion of the Mighty, Targ Nar, Demon-Fang Gnoll), 0 regressed.
Tiger-Tribe Hunter shares the identical condition but stays UNMODELED on
its own unrelated "you may sacrifice another creature. when you do, ..."
compound — confirmed via `parser_probe.py card`, out of scope here.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
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
    eng.state.current_step = "combat1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _creature(state, name, power, controller="p1", attacking=False):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=power),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.attacking = attacking
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER: the condition itself
# ---------------------------------------------------------------------------


def test_attacked_with_total_power_or_greater():
    assert static_condition(
        "you attacked with creatures with total power 6 or greater this combat"
    ) == {
        "kind": "control_count",
        "selector": "total_power_attacking_creatures_you_control", "min": 6,
    }


def test_attacked_with_total_power_without_this_combat_tail():
    assert static_condition(
        "you attacked with creatures with total power 6 or greater"
    ) == {
        "kind": "control_count",
        "selector": "total_power_attacking_creatures_you_control", "min": 6,
    }


def test_an_unrelated_phrase_fails_closed():
    assert static_condition(
        "you attacked with creatures with total toughness 6 or greater this combat"
    ) is None


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Gnoll Hunter", "Hobgoblin Captain", "Intrepid Outlander",
        "Minion of the Mighty", "Targ Nar, Demon-Fang Gnoll",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_gnoll_hunter_gets_a_counter_only_once_attacking_total_power_reaches_the_threshold():
    eng, state, p1, p2 = _engine()
    source = GameObject(_db().get_card("Gnoll Hunter"), owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    source.attacking = True
    bind_from_catalogue(source)
    state.add_to_battlefield(source)

    # Only Gnoll Hunter itself (2 power) is attacking — below the threshold.
    from mtg_analyzer.models.game.events import EventType, GameEvent

    def _fire_attacks():
        state.fire_event(GameEvent(
            EventType.ATTACKS, attacker=source.name, player_id="p1",
            instance_id=source.instance_id, object_types=sorted(source.type_words),
            defending_player_id="p2",
        ))

    _fire_attacks()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert source.counters.get("+1/+1", 0) == 0  # 2 power total — below 6

    # A second attacker brings the attacking total to 2 + 4 = 6 — at the threshold.
    _creature(state, "Wurm", power=4, attacking=True)
    _fire_attacks()
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert source.counters.get("+1/+1", 0) == 1
