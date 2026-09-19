"""PAR-29 — RULE 701.30 Clash (Lorwyn/Shadowmoor).

`RulesEngine.clash` reveals the top card of the instructed player's library
(and, for "clash with an opponent", one opponent's too) and returns whether
that player won (RULE 701.30d — strictly higher mana value than every other
card revealed). `effects.ClashEffect` (registered as ``clash``) stashes the
outcome on `GameContext.clash_won`; the "if you win, `<effect>`. otherwise,
`<effect>`." branch is a sibling `ConditionalEffect` gated on the
``"clash_won"`` key (`segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE`).
"whenever you clash" / "whenever you win a clash" ride `EventType.CLASHED` /
`WON_CLASH`.

RULE 701.30c's public reveal and optional top/bottom decisions are surfaced
as serial `pending_choice` prompts in APNAP order; the cards move only once
all clashing players have answered.

Reference: game/rules/misc_mixin.py (`clash`), game/effects/core.py
(`ClashEffect`, `ConditionalEffect._condition_holds`),
parser/oracle/segmenter.py, parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_clash_clause_parses_both_phrasings():
    assert match_clause("clash with an opponent") == [EffectSpec("clash", {})]
    assert match_clause("clash with defending player") == [EffectSpec("clash", {})]
    assert match_clause("clash") is None
    assert match_clause("clash with your opponent") is None


def test_if_you_win_branch_attaches_clash_won_condition():
    specs = parse_effect_body(
        "clash with an opponent. if you win, put a +1/+1 counter on ~"
    )
    assert [s.type for s in specs] == ["clash", "add_counters"]
    assert specs[0].condition is None
    assert specs[1].condition == {"kind": "clash_won"}


def test_if_you_win_and_otherwise_branches():
    specs = parse_effect_body(
        "clash with an opponent. if you win, draw a card. otherwise, you lose 1 life"
    )
    # clash, then the two mutually-exclusive branches in printed order.
    assert [s.type for s in specs] == ["clash", "draw", "lose_life"]
    assert specs[1].condition == {"kind": "clash_won"}
    assert specs[2].condition == {"kind": "not", "condition": {"kind": "clash_won"}}


def test_if_you_won_past_tense_also_recognised():
    specs = parse_effect_body("if you won, draw a card")
    assert [s.type for s in specs] == ["draw"]
    assert specs[0].condition == {"kind": "clash_won"}


def test_bare_otherwise_with_unmodeled_effect_fails_closed():
    assert parse_effect_body("otherwise, glorble the frobnicator") is None


def test_real_clash_creature_modeled_end_to_end():
    card = Card(
        id="OB", name="Oaken Brawler", type_line="Creature — Treefolk Shaman",
        is_creature=True, power=2, toughness=4,
        oracle_text=(
            "When this creature enters, clash with an opponent. If you win, "
            "put a +1/+1 counter on this creature. (Each clashing player "
            "reveals the top card of their library, then puts that card on "
            "their choice of the top or bottom.)"
        ),
    )
    assert parse_oracle(card).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _card(name, mv, land=False):
    return Card(
        id=name, name=name,
        type_line="Land" if land else "Creature — Bear",
        is_creature=not land, is_land=land,
        power=1, toughness=1, converted_mana_cost=mv,
    )


def _top(state, player_id, card):
    obj = GameObject(card, owner_id=player_id, zone=Zone.LIBRARY)
    state.player_by_id(player_id).add_to_zone(obj, Zone.LIBRARY)
    return obj


def test_clash_win_when_own_card_has_higher_mana_value():
    eng, state = _engine()
    _top(state, "p1", _card("Big", 5))
    _top(state, "p2", _card("Small", 2))
    fired = []
    state.subscribe(lambda e: fired.append(e.type)
                    if e.type in (EventType.CLASHED, EventType.WON_CLASH) else None)

    won = eng.rules.clash(state.player_by_id("p1"))

    assert won is True
    assert fired == [EventType.CLASHED, EventType.WON_CLASH]


def test_clash_loss_when_opponent_card_ties_or_beats():
    eng, state = _engine()
    _top(state, "p1", _card("Mine", 3))
    _top(state, "p2", _card("Theirs", 3))  # tie — RULE 701.30d needs *strictly* higher
    fired = []
    state.subscribe(lambda e: fired.append(e.type)
                    if e.type in (EventType.CLASHED, EventType.WON_CLASH) else None)

    won = eng.rules.clash(state.player_by_id("p1"))

    assert won is False
    assert fired == [EventType.CLASHED]  # no WON_CLASH


def test_clash_with_no_opponent_card_still_wins():
    eng, state = _engine()
    _top(state, "p1", _card("Mine", 1))
    # p2's library left empty — nothing else revealed, so p1 wins (701.30d).
    assert eng.rules.clash(state.player_by_id("p1")) is True


def test_clash_with_empty_own_library_cannot_win():
    eng, state = _engine()
    _top(state, "p2", _card("Theirs", 1))
    assert eng.rules.clash(state.player_by_id("p1")) is False


def test_clash_reveals_cards_publicly_and_moves_selected_cards_after_both_choices():
    eng, state = _engine()
    mine = _top(state, "p1", _card("Mine", 4))
    theirs = _top(state, "p2", _card("Theirs", 1))
    eng.rules.clash(state.player_by_id("p1"))
    assert state.pending_choice["kind"] == "clash"
    assert state.pending_choice["player_id"] == "p1"  # active player first (APNAP)
    assert {o["name"] for o in state.to_dict()["clash_revealed"]} == {"Mine", "Theirs"}

    eng.resolve_pending_choice("bottom")
    # The choice is recorded but no card moves until every clashing player
    # has decided (RULE 701.30c).
    assert state.player_by_id("p1").library[-1] is mine
    assert state.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("top")

    assert state.pending_choice is None
    assert state.clash_revealed == []
    assert state.player_by_id("p1").library[0] is mine
    assert state.player_by_id("p2").library[-1] is theirs


def test_clash_reveals_remain_public_while_the_other_player_is_deciding():
    """The multiplayer view may hide the choice, never the public reveal."""
    from mtg_analyzer.services.game_session import _redact_hidden_zones

    eng, state = _engine()
    _top(state, "p1", _card("Mine", 4))
    _top(state, "p2", _card("Theirs", 1))
    eng.rules.clash(state.player_by_id("p1"))

    opponent_view = state.to_dict()
    _redact_hidden_zones(opponent_view, "p2")
    assert opponent_view["pending_choice"] is None
    assert opponent_view["waiting_on_choice"]["player_id"] == "p1"
    assert {o["name"] for o in opponent_view["clash_revealed"]} == {"Mine", "Theirs"}


def _etb(eng, state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id=controller, object_types=sorted(obj.type_words),
    ))
    return obj


def test_clash_effect_end_to_end_grants_counter_on_win():
    eng, state = _engine()
    # Stack the libraries so p1's clash is a guaranteed win.
    _top(state, "p1", _card("Expensive", 8))
    _top(state, "p2", _card("Cheap", 0))

    card = Card(
        id="NE", name="Nath's Elite", type_line="Creature — Elf Warrior",
        is_creature=True, power=2, toughness=2,
        oracle_text=(
            "When this creature enters, clash with an opponent. If you win, "
            "put a +1/+1 counter on this creature."
        ),
    )
    obj = _etb(eng, state, card)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert state.pending_choice["kind"] == "clash"
    eng.resolve_pending_choice("top")
    assert state.pending_choice["kind"] == "clash"
    eng.resolve_pending_choice("top")

    assert obj.counters.get("+1/+1", 0) == 1


def test_clash_effect_end_to_end_no_counter_on_loss():
    eng, state = _engine()
    _top(state, "p1", _card("Cheap", 0))
    _top(state, "p2", _card("Expensive", 8))

    card = Card(
        id="NE2", name="Paperfin Rascal", type_line="Creature — Merfolk Rogue",
        is_creature=True, power=2, toughness=2,
        oracle_text=(
            "When this creature enters, clash with an opponent. If you win, "
            "put a +1/+1 counter on this creature."
        ),
    )
    obj = _etb(eng, state, card)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("top")
    eng.resolve_pending_choice("top")

    assert obj.counters.get("+1/+1", 0) == 0
