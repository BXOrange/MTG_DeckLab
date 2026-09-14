"""PAR-66 — "counters removed this way" as a resolve-time amount.

`RemoveCountersEffect` already stripped counters via `context.add_counters`
(so a counter-removed trigger fires correctly) but never told
`GameContext` *how many* it actually removed, so a following effect
scaled by "for each counter removed this way" (Coalition Relic/Ventifact
Bottle's own mana rider, Lily Bowen's life gain) had nothing to read — the
exact same shape `objects_exiled_this_way`/`permanents_destroyed_this_way`
already give exile/destroy. This batch:

* Adds `GameContext.counters_removed_this_way` (an `int` accumulator, the
  same save/reset/restore idiom as its two siblings, threaded through
  `_apply_effects_partitioned`/`composition.py`'s nested-resolution
  passthrough and the deferred-effects resume path) and bumps it from
  every `RemoveCountersEffect._strip` call site.
* Adds `RemoveCountersEffect.self_only`/`kind` — "Remove all `<kind>`
  counters from ~." (a permanent naming its own source, RULE 115 never
  applies) restricted to one named counter kind, so an unrelated counter
  type on the same permanent survives. New parser handler
  `_remove_all_named_counters_self`.
* Wires the accumulator into the effects that actually need it:
  `GainLifeEffect.count_selector="counters_removed_this_way"` (mirroring
  the existing `"life_lost_this_way"` special case) and two new
  `AddManaEffect` params — `amount_from_context` (the fixed-colour
  sibling of the existing `any_amount_from_context`, itself previously
  reachable only from hand-authored Culling Ritual) and reuse of
  `any_amount_from_context` for the "any color" form. New parser handler
  `_add_mana_per_counter_removed`.

`AddCountersEffect`/`extra turn` consumers (Garnet's multi-Saga removal,
Sage of Hours' "for each 5, take an extra turn") are each a further,
different shape on top of this primitive and stay open residue — the
primitive itself, and its two SOLO closes, are this ticket's whole scope.

Reference: mtg_analyzer/game/effects/core.py (`GameContext.
counters_removed_this_way`), mtg_analyzer/game/effects/counters_tokens.py
(`RemoveCountersEffect`), mtg_analyzer/game/effects/choices_actions.py
(`AddManaEffect`), mtg_analyzer/game/effects/life_sacrifice.py
(`GainLifeEffect`), mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    return GameEngine(state), state


# ---------------------------------------------------------------------------
# Parser recognition
# ---------------------------------------------------------------------------


def test_remove_all_named_counters_self_parses():
    assert match_clause("remove all charge counters from ~") == [
        EffectSpec("remove_counters", {"self_only": True, "kind": "charge"})
    ]


def test_remove_all_plus_one_counters_self_parses():
    assert match_clause("remove all +1/+1 counters from ~") == [
        EffectSpec("remove_counters", {"self_only": True, "kind": "+1/+1"})
    ]


def test_remove_all_counters_target_permanent_unchanged():
    # The pre-existing, unrelated "target permanent" shape must not be
    # swallowed by the new self-only row.
    assert match_clause("remove all counters from target permanent") == [
        EffectSpec("remove_counters", {"target_kind": "permanent"})
    ]


def test_add_mana_any_color_per_counter_removed_parses():
    specs = match_clause("add 1 mana of any color for each charge counter removed this way")
    assert specs == [EffectSpec("add_mana", {
        "colors": ["any"], "any_amount_from_context": "counters_removed_this_way",
    })]


def test_add_fixed_mana_per_counter_removed_parses():
    specs = match_clause("add {c} for each charge counter removed this way")
    assert specs == [EffectSpec("add_mana", {
        "color": "C", "amount_from_context": "counters_removed_this_way",
    })]


# ---------------------------------------------------------------------------
# Execute-level: the accumulator actually threads through a resolution
# ---------------------------------------------------------------------------


def test_remove_all_named_counters_self_bumps_accumulator_and_spares_other_kinds():
    engine, state = _engine("p1")
    source = GameObject(Card(id="s", name="s", type_line="Artifact"),
                        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    source.counters["charge"] = 3
    source.counters["+1/+1"] = 2  # an unrelated kind that must survive
    state.add_to_battlefield(source)

    from mtg_analyzer.game.effects.core import EffectRegistry

    eff = EffectRegistry.create("remove_counters", {"self_only": True, "kind": "charge"})
    eff.source = source
    context = engine.rules.context
    assert context.counters_removed_this_way == 0
    eff.apply(context)
    assert source.counters.get("charge", 0) == 0
    assert source.counters.get("+1/+1", 0) == 2
    assert context.counters_removed_this_way == 3


def test_add_mana_amount_from_context_reads_the_accumulator():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, state = _engine("p1")
    p1 = state.players[0]
    source = GameObject(Card(id="s2", name="s2", type_line="Artifact"),
                        owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    context = engine.rules.context
    context.counters_removed_this_way = 4

    eff = EffectRegistry.create("add_mana", {"color": "C", "amount_from_context": "counters_removed_this_way"})
    eff.source = source
    eff.apply(context)
    assert p1.mana_pool.pool["C"] == 4


def test_ventifact_bottle_trigger_produces_colorless_mana_equal_to_counters_removed():
    # Ventifact Bottle's fixed-colour "Add {C}" form (unlike Coalition
    # Relic's "any color", which opens a real player choice) resolves
    # synchronously, so it's the cleaner end-to-end proof of the whole
    # remove -> accumulate -> read chain in one pass.
    engine, state = _engine("p1")
    p1 = state.players[0]
    bottle = GameObject(_db().get_card("Ventifact Bottle"), owner_id="p1", controller_id="p1",
                        zone=Zone.BATTLEFIELD)
    bind_from_catalogue(bottle)
    state.add_to_battlefield(bottle)
    bottle.counters["charge"] = 3

    from mtg_analyzer.game.effects.counters_tokens import RemoveCountersEffect

    ability = next(
        a for a in bottle.triggered_abilities
        if any(isinstance(e, RemoveCountersEffect) for e in a.effects)
    )
    for effect in ability.effects:
        effect.apply(engine.rules.context)
    assert bottle.counters.get("charge", 0) == 0
    assert p1.mana_pool.pool["C"] == 3


# ---------------------------------------------------------------------------
# End-to-end: real cached cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Coalition Relic", "Ventifact Bottle"])
def test_counters_removed_this_way_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed
