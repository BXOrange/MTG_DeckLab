"""PAR-29 — RULE 701.53 Incubate (Phyrexia: All Will Be One).

"Incubate N" creates an Incubator token — a power/toughness-less colourless
artifact token — with N +1/+1 counters on it. No new engine primitive: the
`Incubator` catalogue entry (`ability_catalogue/red_spells.py`) binds
"{2}: Transform this token" (→ a 0/0 Phyrexian artifact creature, whose
counters then make it N/N) onto every token so named, and `create_token`'s
`extra_counters` places the counters. The parser handler `incubate` emits
the same `create_token` spec Glissa, Herald of Predation's hand-authored
entry already uses.

Reference: parser/oracle/catalogue/handlers.py (`_incubate`),
game/ability_catalogue/red_spells.py (`_incubator_token`),
game/effects/core.py (`CreateTokenEffect.extra_counters`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import CreateTokenEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_incubate_clause_parses():
    assert match_clause("incubate 3") == [EffectSpec("create_token", {
        "count": 1, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count": 3},
    })]
    # "you incubate N" — the "when you do" continuation form.
    assert match_clause("you incubate 2") == [EffectSpec("create_token", {
        "count": 1, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count": 2},
    })]
    assert match_clause("incubate") is None
    assert match_clause("incubate a dragon") is None


def test_real_incubate_cards_modeled_end_to_end():
    sorcery = Card(id="EoG", name="Eyes of Gitaxias", type_line="Sorcery",
                   is_sorcery=True, oracle_text="Incubate 3.\nDraw a card.")
    assert parse_oracle(sorcery).modeled

    for name, text in [
        ("Converter Beast", "When this creature enters, incubate 5."),
        ("Tangled Skyline", "When this creature enters, you gain 5 life and incubate 5."),
    ]:
        card = Card(id=name[:3], name=name, type_line="Creature — Phyrexian",
                    is_creature=True, power=4, toughness=4, oracle_text=text)
        assert parse_oracle(card).modeled, name


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def test_incubate_creates_token_with_counters_and_transform_ability():
    eng, state = _engine()
    ctx = GameContext(state, eng.rules)
    CreateTokenEffect(count=1, token_name="Incubator",
                      extra_counters={"kind": "+1/+1", "count": 4}).apply(ctx)

    toks = [o for o in state.battlefield if o.card.name == "Incubator"]
    assert len(toks) == 1
    tok = toks[0]
    eng.recompute_continuous_effects()

    assert tok.counters.get("+1/+1") == 4
    assert "artifact" in tok.type_words and not tok.is_creature  # front face
    # `create_token` binds the token's own name-keyed catalogue abilities —
    # "{2}: Transform this token" is there without a second bind.
    assert len(tok.activated_abilities) == 1


def test_incubator_transforms_into_n_over_n_creature():
    eng, state = _engine()
    ctx = GameContext(state, eng.rules)
    CreateTokenEffect(count=1, token_name="Incubator",
                      extra_counters={"kind": "+1/+1", "count": 3}).apply(ctx)
    tok = [o for o in state.battlefield if o.card.name == "Incubator"][0]

    p1 = state.player_by_id("p1")
    p1.mana_pool.add("C", 2)
    eng.activate_ability(p1, tok, 0)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()

    assert tok.is_creature and (tok.power, tok.toughness) == (3, 3)  # 0/0 + 3 counters


def test_incubate_via_binder_on_etb():
    eng, state = _engine()
    card = Card(id="MD", name="Marauding Dreadship",
                type_line="Artifact Creature — Phyrexian Dreadnought",
                is_creature=True, power=6, toughness=6,
                oracle_text="When this creature enters, incubate 2.")
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

    toks = [o for o in state.battlefield if o.card.name == "Incubator"]
    assert len(toks) == 1 and toks[0].counters.get("+1/+1") == 2
