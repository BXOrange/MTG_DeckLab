"""PAR-29 — RULE 701.61 Forage (Bloomburrow).

`ActivationCost.forage` is a compound "exile three cards from your
graveyard OR sacrifice a Food" non-mana cost (a bool). `RulesEngine.forage
(player)` auto-picks between the two halves — a Food is sacrificed whenever
`player` controls one (keeping the three graveyard cards), otherwise the
three oldest graveyard cards are exiled (documented simplification) — then
fires `EventType.FORAGED`. Wired into `_can/_pay_activation_cost`,
`_can/_pay_player_cost` (`pay_cost_then`), and a "whenever you forage"
trigger. `effects.ForageEffect` is the segmenter-peeled "you may forage"
triggered-ability body.

Reference: game/costs.py (`forage`, `_FORAGE_RE`), game/rules/misc_mixin.py
(`forage` / `forage_possible`), game/effects/core.py (`ForageEffect`).
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_forage_cost_text_parses_and_roundtrips():
    cost = parse_activation_cost({"text": "{2}, forage"})
    assert cost.forage is True and cost.mana.raw == "{2}"
    assert parse_activation_cost(cost.to_dict()).forage is True


def test_forage_clause_forms():
    assert match_clause("forage") == [EffectSpec("forage", {})]
    assert match_clause("you may forage") == [
        EffectSpec("pay_cost_then", {"cost": "forage", "effects": []})
    ]


def test_real_forage_cards_modeled():
    for name, text in [
        ("Treetop Sentries",
         "When this creature enters, you may forage. If you do, draw a card."),
        ("Bushy Bodyguard",
         "When this creature enters, you may forage. If you do, put two "
         "+1/+1 counters on it."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Creature — Rabbit",
                 is_creature=True, power=2, toughness=2, oracle_text=text)
        assert parse_oracle(c).modeled, name


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _gy(state, pid, n):
    p = state.player_by_id(pid)
    for i in range(n):
        c = Card(id=f"{pid}G{i}", name=f"Gy{i}", type_line="Creature — Bear",
                 is_creature=True, power=1, toughness=1)
        p.add_to_zone(GameObject(c, owner_id=pid, zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    return p


def _food(state, pid):
    c = Card(id=f"{pid}Food", name="Food", type_line="Artifact — Food")
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_forage_possible():
    eng, state = _engine()
    p = _gy(state, "p1", 2)
    assert eng.rules.forage_possible(p) is False
    _gy(state, "p1", 1)  # now 3
    assert eng.rules.forage_possible(p) is True


def test_forage_exiles_three_graveyard_cards_when_no_food():
    eng, state = _engine()
    p = _gy(state, "p1", 4)
    fired = []
    state.subscribe(lambda e: fired.append(e.type)
                    if e.type == EventType.FORAGED else None)

    assert eng.rules.forage(p) is True
    assert len(p.exile) == 3 and len(p.graveyard) == 1
    assert fired == [EventType.FORAGED]


def test_forage_prefers_sacrificing_a_food():
    eng, state = _engine()
    p = _gy(state, "p1", 5)
    food = _food(state, "p1")

    assert eng.rules.forage(p) is True
    assert food not in state.battlefield  # Food sacrificed
    assert len(p.graveyard) == 6  # 5 + the sacrificed Food; nothing exiled
    assert p.exile == []


def test_forage_impossible_still_fires_event():
    eng, state = _engine()
    p = _gy(state, "p1", 1)  # <3, no Food
    fired = []
    state.subscribe(lambda e: fired.append(e.type)
                    if e.type == EventType.FORAGED else None)

    assert eng.rules.forage(p) is False
    assert fired == [EventType.FORAGED]  # RULE 701.61b


def test_forage_via_binder_on_etb_with_rider():
    eng, state = _engine()
    p1 = _gy(state, "p1", 4)
    # a library card to draw
    lib = Card(id="lib", name="LibCard", type_line="Creature — Bear",
               is_creature=True, power=1, toughness=1)
    p1.add_to_zone(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)

    card = Card(id="TS", name="Treetop Sentries", type_line="Creature — Rabbit Scout",
                is_creature=True, power=3, toughness=1,
                oracle_text="When this creature enters, you may forage. If you do, draw a card.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    # pay_cost_then choice: pay the forage cost
    assert state.pending_choice and state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")

    assert len(p1.exile) == 3  # foraged
    assert len(p1.hand) == 1   # drew
