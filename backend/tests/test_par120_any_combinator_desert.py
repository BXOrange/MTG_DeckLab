"""PAR-120 — the "any" (OR) combinator on `static_conditions.py`'s own
evaluator, plus "you control a desert or there is a desert card in your
graveyard" (the Amonkhet Desert-payoff cluster) as its first real use.

`effect_conditions.py` already had an `any` combinator (ENG-36) for the
resolution-time vocabulary, but `static_conditions.condition_holds` itself
— the evaluator a RULE 613.6 static's own `active_if` and an "activate only
if" gate call *directly*, bypassing `effect_conditions.py` — only had `all`/
`not`. A leading-"if"/trailing-"if" trigger condition (routed through
`effect_conditions.py`) already worked; "as long as …" statics and
"activate only if" didn't, and would have kept not working no matter how
many `static_condition()` rows recognized the phrase, since the resulting
`{"kind": "any", ...}` dict had nowhere to be evaluated for those two
surfaces. `static_condition()` also gained a generic "`<A>` or `<B>`"
fallback: split on the first " or ", recurse both halves through the same
function, and only build the combinator if BOTH independently resolve — so
a non-disjunctive "or" inside an unrelated, still-unmodeled phrase fails
closed exactly like a single unrecognized condition always has, rather than
silently misreading it.

`parser_probe.py diff`: +8 (Desert's Hold, Earth Rumble Wrestlers, Gilded
Cerodon, Sidewinder Naga, Solitary Camel, Unquenchable Thirst, Wall of
Forgotten Pharaohs, Wretched Camel), 0 regressed. Sand Strangler shares the
identical condition but stays UNMODELED on its own unrelated "you may have
~ deal N damage to target creature" composition gap — confirmed via
`parser_probe.py card`, out of scope here.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# PARSER: the OR-split + the "any" combinator shape
# ---------------------------------------------------------------------------


def test_desert_compound_condition():
    assert static_condition(
        "you control a desert or there is a desert card in your graveyard"
    ) == {"kind": "any", "conditions": [
        {"kind": "control_count",
         "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "desert"}}, "min": 1},
        {"kind": "subtype_in_graveyard", "subtype": "desert"},
    ]}


def test_a_non_disjunctive_or_inside_an_unmodeled_phrase_fails_closed():
    # Neither half resolves on its own, so no combinator is built — the same
    # fail-closed direction a single unrecognized condition always takes.
    assert static_condition("you rolled a 1 or a 2 on a d20") is None


def test_real_cards_become_modeled():
    for name in (
        "Desert's Hold", "Earth Rumble Wrestlers", "Gilded Cerodon",
        "Sidewinder Naga", "Solitary Camel", "Unquenchable Thirst",
        "Wall of Forgotten Pharaohs", "Wretched Camel",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: `condition_holds`'s own "any" evaluator, and a real static
# ---------------------------------------------------------------------------


def test_condition_holds_any_is_true_the_moment_one_sub_condition_holds():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    cond = {"kind": "any", "conditions": [
        {"kind": "life_at_most", "amount": 5},
        {"kind": "life_at_least", "amount": 100},
    ]}
    assert condition_holds(cond, state, source=None, controller_id="p1") is False
    state.players[0].life = 3
    assert condition_holds(cond, state, source=None, controller_id="p1") is True


def test_sidewinder_naga_gets_trample_from_either_desert_condition():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    naga = GameObject(_db().get_card("Sidewinder Naga"), owner_id="p1", zone=Zone.BATTLEFIELD)
    naga.controller_id = "p1"
    bind_from_catalogue(naga)
    state.add_to_battlefield(naga)
    eng.recompute_continuous_effects()

    from mtg_analyzer.game import combat

    assert not combat.has(naga, "trample")  # no desert anywhere yet

    # A Desert card in the graveyard (no Desert on the battlefield) is
    # enough on its own — this is an OR, not an AND.
    state.players[0].graveyard.append(GameObject(
        Card(id="d0", name="Desert", type_line="Land — Desert", is_land=True),
        owner_id="p1", zone=Zone.GRAVEYARD,
    ))
    eng.recompute_continuous_effects()
    assert combat.has(naga, "trample")
    assert naga.power == 4  # 3 printed + 1 anthem
