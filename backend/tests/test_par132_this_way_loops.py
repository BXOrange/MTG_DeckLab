"""PAR-132 row 2 — "for each <object> destroyed/exiled this way, <body>" (RULE 608.2c/608.2h).

`ForEachEffect` over ``{"this_way": verb}`` loops the objects the resolution actually destroyed/exiled;
"its controller creates" reads the loop item's last-known controller.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _spell(name: str, text: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text)


def _board():
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    st = eng.state
    for pid, count in (("p1", 1), ("p2", 2)):
        for i in range(count):
            c = GameObject(
                Card(id=f"{pid}{i}", name=f"Bear{pid}{i}", type_line="Creature — Bear",
                     is_creature=True, power=2, toughness=2),
                owner_id=pid, zone=Zone.BATTLEFIELD,
            )
            c.controller_id = pid
            st.add_to_battlefield(c)
    src = GameObject(Card(id="SP", name="Spell", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    return eng, st, src


def _specs(card: Card) -> list[EffectSpec]:
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    return result.specs[0].effects


def _tokens(st, pid):
    return [o for o in st.battlefield if o.is_token and o.controller_id == pid]


def test_each_controller_gets_one_token_per_destroyed_creature():
    card = _spell("March", "Destroy all creatures. For each creature destroyed this way, its controller "
                           "creates a 1/1 white Spirit creature token with flying.")
    eng, st, src = _board()
    _apply_effects_partitioned(build_effects(_specs(card), src), eng.rules.context, None, None, source=src)
    assert len(_tokens(st, "p1")) == 1
    assert len(_tokens(st, "p2")) == 2


def test_you_create_runs_once_per_nontoken_creature_destroyed():
    card = _spell("Money", "Destroy all creatures. For each nontoken creature destroyed this way, "
                           "you create a tapped Treasure token.")
    eng, st, src = _board()
    _apply_effects_partitioned(build_effects(_specs(card), src), eng.rules.context, None, None, source=src)
    assert len(_tokens(st, "p1")) == 3
    assert not _tokens(st, "p2")


def test_type_filter_only_counts_matching_objects():
    card = _spell("Filter", "Destroy all creatures. For each artifact or land destroyed this way, you create "
                            "a Treasure token.")
    eng, st, src = _board()
    _apply_effects_partitioned(build_effects(_specs(card), src), eng.rules.context, None, None, source=src)
    assert not _tokens(st, "p1")


def test_pronoun_body_is_not_claimed():
    card = _spell("Pronoun", "Destroy all creatures. For each creature destroyed this way, you gain control "
                             "of it.")
    assert parse_oracle(card).coverage == UNMODELED


# --- "that spell or ability's controller" under a becomes-the-target head ---------


def _event_effects(text: str):
    card = Card(id="c1", name="Foo", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                oracle_text=text)
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    return result.specs[0].effects


def test_targeted_controller_loses_life_and_takes_damage():
    eng, st, src = _board()
    ctx = eng.rules.context
    ctx.trigger_event = {"type": "BECOMES_TARGET", "player_id": "p2", "controller_id": "p2"}
    effects = _event_effects(
        "Whenever ~ becomes the target of a spell or ability an opponent controls, that player loses 4 life.")
    assert "event_player_events" not in effects[0].params
    _apply_effects_partitioned(build_effects(effects, src), ctx, None, None, source=src)
    assert st.player_by_id("p2").life == 16
    effects = _event_effects(
        "Whenever ~ becomes the target of a spell or ability, ~ deals 3 damage to that spell or ability's "
        "controller.")
    _apply_effects_partitioned(build_effects(effects, src), ctx, None, None, source=src)
    assert st.player_by_id("p2").life == 13
    assert st.player_by_id("p1").life == 20


def test_spell_controller_phrase_is_refused_under_other_heads():
    card = Card(id="c2", name="Bar", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                oracle_text="Whenever ~ attacks, that spell or ability's controller loses 4 life.")
    assert parse_oracle(card).coverage == UNMODELED
