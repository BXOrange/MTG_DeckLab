"""PAR-71: "that spell's mana value" as a resolve-time amount referent,
extended across the already-shipped `amount_from_trigger_event`/
`count_from_trigger_event`/`pt_from_trigger_event` family (`DealDamageEffect.
amount_from_trigger_event` already proved the primitive real — every
`SPELL_CAST` event carries `mana_value=obj.card.converted_mana_cost`,
`casting_mixin.cast_spell`'s own "Shark Typhoon-shaped spell-cast payoffs"
comment) to `PumpEffect`, `GainLifeEffect`/`LoseLifeEffect`, `AddCountersEffect`,
`MillEffect` (new `count_from_trigger_event` param) and `DiscoverEffect` (new
`mana_value_from_trigger_event` param) — pure parser recognition, no new
*primitive* for the trigger-event half.

A second, genuinely new referent is needed for the sibling "Counter target
spell. `<effect>`, where X is that spell's mana value." template (Hurl into
History/Access Denied/Overwhelming Intellect/Spell Swindle): there "that
spell" is the *countered* RULE 115 target, not a cast-trigger event —
`context.trigger_event` is `None` for a plain resolving spell, so reusing the
trigger-event reading would silently resolve to 0. `DiscoverEffect` gained
`mana_value_from_subject` (mirroring `GainLifeEffect`/`DrawCardEffect.
amount_from_subject`, all backed by `effects.core._characteristic_of_subject`'s
existing `"previous_subject_mana_value"` reading of `GameContext.
previous_targets`); `CreateTokenEffect.count_from_subject`/`DrawCardEffect.
amount_from_subject` already supported it. `segmenter._announces_creature_
target` gained a `last.type == "counter"` case so the connector-split loop
passes `previous_subject=True` after a `counter` clause, unlocking the new
`previous_subject_only` handler rows — which is what keeps the identical
printed tail from misfiring on a genuine cast-trigger card (or vice versa):
each shape is offered only in its own structural context.

Two real cards were caught printing this exact trap and deliberately left
UNCLAIMED rather than guessed: Imp's Mischief ("Change the target of target
spell with a single target. You lose life equal to that spell's mana
value.") and Draining Whelk ("When this creature enters, counter target
spell. Put X +1/+1 counters on this creature, where X is that spell's mana
value.") — both need the `previous_subject` referent on `lose_life`/
`add_counters` respectively, which this batch didn't build (no real card
needed a *trigger-event* reading for either shape, so there was nothing to
disambiguate against; adding the `previous_subject` reading alone, unguarded,
risks nothing today but is out of this ticket's scope).

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-71 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(player, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


# ---------------------------------------------------------------------------
# PARSER: the trigger-event family (genuine "whenever you cast a spell")
# ---------------------------------------------------------------------------


def test_pump_symmetric_from_trigger_event():
    assert match_clause(
        "~ gets +x/+x until end of turn, where x is that spell's mana value"
    ) == [EffectSpec("pump", {"amount_from_trigger_event": "mana_value"})]


def test_pump_power_only_from_trigger_event():
    assert match_clause(
        "~ gets +x/+0 until end of turn, where x is that spell's mana value"
    ) == [EffectSpec("pump", {
        "amount_from_trigger_event": "mana_value", "amount_from_count_selector_axis": "power",
    })]


def test_pump_target_creature_from_trigger_event():
    assert match_clause(
        "target creature gets +x/+0 until end of turn, where x is that spell's mana value"
    ) == [EffectSpec("pump", {
        "amount_from_trigger_event": "mana_value", "amount_from_count_selector_axis": "power",
        "target_kind": "creature",
    })]


def test_gain_life_from_trigger_event():
    assert match_clause("gain life equal to that spell's mana value") == [
        EffectSpec("gain_life", {"amount_from_trigger_event": "mana_value"})
    ]


def test_lose_life_that_player_from_trigger_event():
    assert match_clause("that player loses life equal to that spell's mana value") == [
        EffectSpec("lose_life", {
            "selector": "event_player", "amount_from_trigger_event": "mana_value",
        })
    ]


def test_add_counters_target_from_trigger_event():
    assert match_clause(
        "put x +1/+1 counters on target creature you control, where x is that spell's mana value"
    ) == [EffectSpec("add_counters", {
        "kind": "+1/+1", "target_kind": "creature_you_control",
        "amount_from_trigger_event": "mana_value",
    })]


def test_mill_target_player_from_trigger_event():
    assert match_clause(
        "have target player mill x cards, where x is that spell's mana value"
    ) == [EffectSpec("mill", {"target_kind": "player", "count_from_trigger_event": "mana_value"})]


def test_discover_from_trigger_event():
    assert match_clause("discover x, where x is that spell's mana value") == [
        EffectSpec("discover", {"mana_value_from_trigger_event": "mana_value"})
    ]


# ---------------------------------------------------------------------------
# PARSER: the "counter target spell. <effect>" previous-target family
# ---------------------------------------------------------------------------


def test_discover_from_previous_target_when_gated():
    assert match_clause(
        "discover x, where x is that spell's mana value", previous_subject=True,
    ) == [EffectSpec("discover", {"mana_value_from_subject": "previous_subject_mana_value"})]
    # Ungated (no preceding counter clause) falls back to the trigger-event
    # reading instead of the previous_subject_only row.
    assert match_clause("discover x, where x is that spell's mana value") == [
        EffectSpec("discover", {"mana_value_from_trigger_event": "mana_value"})
    ]


def test_draw_from_previous_target_when_gated():
    assert match_clause(
        "draw cards equal to that spell's mana value", previous_subject=True,
    ) == [EffectSpec("draw", {"amount_from_subject": "previous_subject_mana_value"})]
    # Not offered at all without the gate (no ungated draw-from-MV sibling
    # exists — a plain spell with no antecedent target has no safe reading).
    assert match_clause("draw cards equal to that spell's mana value") is None


def test_create_inline_token_count_from_previous_target_when_gated():
    assert match_clause(
        "create x 1/1 colorless thopter artifact creature tokens with flying, "
        "where x is that spell's mana value",
        previous_subject=True,
    ) == [EffectSpec("create_token", {
        "colors": [], "subtypes": ["Thopter"], "keywords": ["flying"], "is_artifact": True,
        "token_name": "Thopter", "power": 1, "toughness": 1,
        "count_from_subject": "previous_subject_mana_value",
    })]


def test_create_named_token_count_from_previous_target_when_gated():
    assert match_clause(
        "create x treasure tokens, where x is that spell's mana value", previous_subject=True,
    ) == [EffectSpec("create_token", {
        "token_name": "Treasure", "count_from_subject": "previous_subject_mana_value",
    })]


# ---------------------------------------------------------------------------
# PARSER: adversarial cases — the trap two real cards print
# ---------------------------------------------------------------------------


def test_impish_mischief_shaped_card_stays_unmodeled():
    # "Change the target of target spell with a single target. You lose
    # life equal to that spell's mana value." — real Imp's Mischief text.
    # "that spell" is the targeted spell (previous_subject), not a trigger
    # event; no handler claims "you lose life equal to that spell's mana
    # value" at all (deliberately not built this batch — see module
    # docstring), so the card stays UNMODELED rather than silently losing 0
    # life.
    card = Card(
        id="Imp's Mischief", name="Imp's Mischief", type_line="Instant", is_instant=True,
        mana_cost_string="{U}", converted_mana_cost=1,
        oracle_text=(
            "Change the target of target spell with a single target. "
            "You lose life equal to that spell's mana value."
        ),
    )
    result = parse_oracle(card)
    assert not result.modeled, result.unclaimed


def test_draining_whelk_shaped_card_stays_unmodeled():
    card = Card(
        id="Draining Whelk", name="Draining Whelk", type_line="Creature — Serpent",
        is_creature=True, power=4, toughness=6,
        oracle_text=(
            "Flash\nFlying\nWhen this creature enters, counter target spell. "
            "Put X +1/+1 counters on this creature, where X is that spell's mana value."
        ),
    )
    result = parse_oracle(card)
    assert not result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_manaplasm_shaped_pump_scales_with_the_cast_spells_mana_value():
    eng, state, p1, p2 = _engine()
    watcher = _bf(state, _card(
        "Test Manaplasm", is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast a spell, this creature gets +X/+X "
                    "until end of turn, where X is that spell's mana value.",
    ))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{2}{G}{G}", cmc=4))

    p1.mana_pool.add_many({"C": 2, "G": 2})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert watcher.power == 1 + 4
    assert watcher.toughness == 1 + 4


def test_cloudhoof_kirin_shaped_mill_scales_with_the_cast_spells_mana_value():
    eng, state, p1, p2 = _engine()
    _bf(state, _card(
        "Test Cloudhoof Kirin", is_creature=True, power=3, toughness=3,
        oracle_text=(
            "Whenever you cast a spell, target player mills X cards, where "
            "X is that spell's mana value."
        ),
    ))
    for i in range(6):
        p2.library.append(GameObject(
            _card(f"Filler {i}"), owner_id="p2", zone=Zone.LIBRARY
        ))
    spell = _hand(p1, _card("Test Spell", "Sorcery", cost="{2}{G}{G}", cmc=4))

    p1.mana_pool.add_many({"C": 2, "G": 2})
    eng.rules.cast_spell(p1, spell)
    eng.rules.put_triggers_on_stack()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()

    assert len(p2.library) == 6 - 4
    assert len(p2.graveyard) == 4


def test_hurl_into_history_shaped_discover_reads_the_countered_spells_own_mana_value():
    eng, state, p1, p2 = _engine()
    caster = _card("Test Countered Spell", "Sorcery", cost="{3}{U}{U}", cmc=5)
    countered = _hand(p2, caster, controller="p2")

    counter_spell = _hand(p1, _card(
        "Test Hurl into History", "Instant", cost="{2}{U}",
        oracle_text=(
            "Counter target artifact or creature spell. Discover X, where X "
            "is that spell's mana value."
        ),
    ))
    # `resolve_spell_filter`'s "artifact or creature spell" needs a matching
    # target, but the effect under test is `discover`'s amount, not the
    # counter filter itself — make the countered spell a creature.
    countered.card.is_creature = True
    countered.card.type_line = "Creature — Bear"

    p2.mana_pool.add_many({"C": 3, "U": 2})
    eng.rules.cast_spell(p2, countered)

    p1.mana_pool.add_many({"C": 2, "U": 1})
    # Top of library: a mana-value-6 card first (too expensive even under
    # the countered spell's mana value of 5 — must be skipped), then a
    # mana-value-5 card (the exact boundary "N or less" hit). If the amount
    # were wrongly read as 0 (the `context.trigger_event` bug this test
    # guards against), neither card would ever match and no choice would
    # open at all.
    too_expensive = _card("Too Expensive", "Artifact", cmc=6)
    exact_hit = _card("Exact Hit", "Artifact", cmc=5)
    p1.library.append(GameObject(too_expensive, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(exact_hit, owner_id="p1", zone=Zone.LIBRARY))

    countered_stack_item = state.stack[-1]
    eng.rules.cast_spell(p1, counter_spell, targets=[countered_stack_item])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert len(state.stack) == 0
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "discover"
    hit = next(o for o in p1.exile if o.name == "Exact Hit")
    assert choice["matched_id"] == hit.instance_id
