"""PAR-30 — "create a … creature token that's tapped and attacking"
(RULE 508.4).

`RulesEngine.put_onto_battlefield_attacking` is the shared primitive: a
creature is put into the current combat *attacking* without being declared
(no tap for the attack, summoning sickness irrelevant), and RULE 508.4a's
defender choice is auto-made when there's one obvious defender. RULE 508.3a
means no `ATTACKS` event fires. `CreateTokenEffect` gained an `attacking` flag; the
inline-token regexes gained an optional "…that's/are tapped and attacking"
suffix.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse -----------------------------------------------------------------


def test_singular_tapped_and_attacking_token_parses():
    assert match_clause(
        "create a 1/1 white kor ally creature token that's tapped and attacking"
    ) == [EffectSpec("create_token", {
        "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
        "subtypes": ["Kor", "Ally"], "keywords": [], "token_name": "Kor Ally",
        "tapped": True, "attacking": True,
    })]


def test_plural_tapped_and_attacking_tokens_parse():
    specs = match_clause(
        "create 2 1/1 red goblin creature tokens that are tapped and attacking"
    )
    assert specs is not None and specs[0].params["tapped"] is True
    assert specs[0].params["attacking"] is True
    assert specs[0].params["count"] == 2


def test_plain_token_without_the_suffix_has_no_attacking_flag():
    specs = match_clause("create a 1/1 white soldier creature token")
    assert specs is not None
    assert "attacking" not in specs[0].params


def test_hanweir_garrison_modeled():
    c = Card(id="hg", name="Hanweir Garrison", type_line="Creature — Human Soldier",
             is_creature=True, power=2, toughness=3, oracle_text=(
                 "Whenever Hanweir Garrison attacks, create two 1/1 red Human "
                 "creature tokens that are tapped and attacking."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -------------------------------------------------------------------


def _make_attacking_token(eng, state):
    state.current_phase = "combat"
    state.current_step = "declare_attackers"
    src = GameObject(Card(id="src", name="Garrison", type_line="Creature — Soldier",
                          is_creature=True, power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    events: list = []
    state.subscribe(lambda e: events.append(e))
    build_effects([EffectSpec("create_token", {
        "count": 1, "power": 1, "toughness": 1, "colors": ["R"],
        "subtypes": ["Goblin"], "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(state, eng.rules), None)
    token = next(o for o in state.battlefield if o.is_token)
    return token, events


def test_token_enters_tapped_and_attacking_without_declaring_an_attack():
    eng, state = _engine()
    token, events = _make_attacking_token(eng, state)

    assert token.tapped is True
    assert token.attacking is True
    assert token.attacked_this_turn is False
    # RULE 508.4a: the sole opponent is auto-assigned as the defender.
    assert (token.combat_defender or {}).get("id") == "p2"
    assert not any(e.type == EventType.ATTACKS
                   and e.get("instance_id") == token.instance_id for e in events)


def test_non_attacking_token_is_untouched():
    eng, state = _engine()
    src = GameObject(Card(id="s2", name="Maker", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    build_effects([EffectSpec("create_token", {
        "count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
    })], src)[0].apply(GameContext(state, eng.rules), None)
    token = next(o for o in state.battlefield if o.is_token)

    assert token.attacking is False
    assert token.combat_defender is None


def test_entering_attacking_requires_a_valid_defender_and_active_controller():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cara", [])],
        starting_life=20, starting_hand=0,
    )
    state = eng.state
    state.current_phase = "combat"
    state.current_step = "declare_blockers"
    card = Card(id="tok", name="Soldier", type_line="Token Creature — Soldier",
                is_creature=True, power=1, toughness=1)
    token = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    token.controller_id = "p1"
    token.summoning_sick = True  # RULE 508.4: irrelevant without declaration
    state.add_to_battlefield(token)

    assert eng.rules.put_onto_battlefield_attacking(
        token, {"kind": "player", "id": "p3", "label": "Cara"}
    )
    assert token.attacking and token.combat_defender["id"] == "p3"

    other = GameObject(card, owner_id="p2", zone=Zone.BATTLEFIELD)
    other.controller_id = "p2"
    state.add_to_battlefield(other)
    assert not eng.rules.put_onto_battlefield_attacking(
        other, {"kind": "player", "id": "p1", "label": "Alice"}
    )
    assert not other.attacking
