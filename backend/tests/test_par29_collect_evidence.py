"""PAR-29 — RULE 701.59 Collect Evidence (Murders at Karlov Manor).

`ActivationCost.collect_evidence` is a non-mana cost sized by a **total
mana value threshold** (the MV-sum sibling of Escape's
`exile_from_graveyard` card count). `RulesEngine.collect_evidence(player,
N)` exiles graveyard cards totalling MV >= N (auto-picked, highest MV
first — documented simplification) and fires
`EventType.COLLECTED_EVIDENCE`. Wired into `_can/_pay_activation_cost`
(for `{cost}, collect evidence N:` abilities), `_can/_pay_player_cost`
(for `pay_cost_then` — "you may collect evidence N. if you do, ..."), and
a `whenever you collect evidence` trigger condition.

Reference: game/costs.py (`collect_evidence`, `_COLLECT_EVIDENCE_RE`),
game/rules/misc_mixin.py (`collect_evidence` / `collect_evidence_possible`),
game/engine/activation_mixin.py, game/effects/core.py (`CollectEvidenceEffect`).
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_collect_evidence_cost_text_parses():
    cost = parse_activation_cost({"text": "{2}, {t}, collect evidence 3"})
    assert cost.collect_evidence == 3
    assert cost.mana.raw == "{2}"


def test_collect_evidence_clause_forms():
    assert match_clause("collect evidence 4") == [
        EffectSpec("collect_evidence", {"amount": 4})
    ]
    assert match_clause("you may collect evidence 4") == [
        EffectSpec("pay_cost_then", {"cost": "collect evidence 4", "effects": []})
    ]


def test_collect_evidence_cost_roundtrips_through_dict():
    cost = parse_activation_cost({"text": "collect evidence 6"})
    restored = parse_activation_cost(cost.to_dict())
    assert restored.collect_evidence == 6


def test_real_collect_evidence_cards_modeled():
    izoni = Card(
        id="IZ", name="Izoni, Center of the Web", type_line="Legendary Creature — Insect",
        is_creature=True, power=2, toughness=3,
        oracle_text=("Whenever this creature enters or attacks, you may collect "
                     "evidence 4. If you do, create two 2/1 black and green Spider "
                     "creature tokens with menace and reach."),
    )
    assert parse_oracle(izoni).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _gy(state, pid, *mvs):
    p = state.player_by_id(pid)
    for i, mv in enumerate(mvs):
        c = Card(id=f"{pid}G{i}", name=f"Gy{i}", type_line="Creature — Bear",
                 is_creature=True, power=1, toughness=1, converted_mana_cost=mv)
        p.add_to_zone(GameObject(c, owner_id=pid, zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    return p


def test_collect_evidence_possible_checks_mv_sum():
    eng, state = _engine()
    p = _gy(state, "p1", 2, 3, 1)  # total 6
    assert eng.rules.collect_evidence_possible(p, 6) is True
    assert eng.rules.collect_evidence_possible(p, 7) is False


def test_collect_evidence_exiles_fewest_cards_and_fires_event():
    eng, state = _engine()
    p = _gy(state, "p1", 1, 2, 5)  # total 8
    fired = []
    state.subscribe(lambda e: fired.append(e.get("amount"))
                    if e.type == EventType.COLLECTED_EVIDENCE else None)

    met = eng.rules.collect_evidence(p, 4)

    assert met is True
    assert fired == [4]
    # highest-MV-first: the 5 alone clears 4 — only one card leaves.
    assert [o.name for o in p.exile] == ["Gy2"]
    assert {o.name for o in p.graveyard} == {"Gy0", "Gy1"}


def test_collect_evidence_short_graveyard_does_not_meet_but_still_fires():
    eng, state = _engine()
    p = _gy(state, "p1", 1, 1)  # total 2, below 4
    fired = []
    state.subscribe(lambda e: fired.append(e.get("amount"))
                    if e.type == EventType.COLLECTED_EVIDENCE else None)

    met = eng.rules.collect_evidence(p, 4)

    assert met is False
    assert fired == [4]  # RULE 701.59b — process-complete regardless


def test_activated_ability_with_collect_evidence_cost_pays_it():
    eng, state = _engine()
    p1 = _gy(state, "p1", 3, 3)  # total 6
    p1.mana_pool.add("C", 2)
    card = Card(id="art", name="Polygraph Rig", type_line="Artifact",
                oracle_text="{2}, Collect evidence 3: Draw a card.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(obj)

    assert obj.activated_abilities, "ability bound"
    ok = eng.activate_ability(p1, obj, 0)
    assert ok is not False
    # one card (MV 3) exiled to pay collect evidence 3
    assert len(p1.exile) == 1
    eng.rules.resolve_top_of_stack()
