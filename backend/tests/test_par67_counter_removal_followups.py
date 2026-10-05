"""PAR-67 — counter-removal follow-ups beyond the plain "counters removed
this way" accumulator (PAR-66). Three singleton-shaped cards, confirmed via
`parser_probe.py blocked` to have no nearby cluster, hand-authored into
`game/card_registry/` per the extend-parser skill's own guidance rather
than given new generic parser grammar:

- Garnet, Princess of Alexandria (`value.py`) — a *chosen set* of the
  controller's own Sagas, each losing one lore counter, scaling a +1/+1
  payoff. New `RemoveLoreCounterFromChosenSagasThenAddCountersEffect` +
  `AddCountersFromSagaLoreRemovedDeltaEffect` (`counters_tokens.py`), reusing
  the existing `strip_all_counters` `_request_choose_objects` action and the
  same before/after-delta `then_specs` idiom `RemoveCountersFromAmongThen
  DrawLoseLifeEffect` (Eventide's Shadow) already established.
- Lily Bowen, Raging Grandma (`value.py`) — an `if_else` (RULE 603.4) on the
  source's own power, reusing `double_counters_on_target(mode="self")`
  unchanged for the "then" branch and pairing a new `RemoveCountersEffect.
  keep` partial-removal count ("remove all but N") with `GainLifeEffect`'s
  pre-existing ``count_selector="counters_removed_this_way"`` reader
  (PAR-66) for the "else" branch.
- Sage of Hours (`value.py`) — a mandatory "remove all `<kind>` counters"
  activation *cost* (new `costs.REMOVE_COUNTERS_ALL` sentinel, distinct from
  the existing player-chosen `REMOVE_COUNTERS_ANY`), stamping how many it
  removed onto `GameObject.counters_removed_as_cost` (the cost-paid sibling
  of `x_paid` — a cost has no resolving `GameContext` for the ordinary
  "this way" tallies to land in). The effect reads that stamp back through a
  `bind` (RULE 608.2) with a new `effect_amounts` "counters_removed_as_cost"
  kind and a ``divide=5`` modifier, scaling `TakeExtraTurnEffect`. Along the
  way, `TakeExtraTurnEffect.count` moved to the "store raw, coerce lazily in
  apply()" idiom every other `bind`-composable effect already uses — its
  eager `int()` cast in `__init__` broke on `bind`'s own uncoerced "$n"
  sentinel the one time `target_specs` builds every composed effect before
  substitution runs.
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

from mtg_analyzer.game.costs import REMOVE_COUNTERS_ALL


GARNET = Card(
    id="GAR", name="Garnet, Princess of Alexandria",
    type_line="Legendary Creature — Human Noble Cleric", is_creature=True,
    mana_cost_string="{G}{W}", converted_mana_cost=2, power=2, toughness=2,
    keywords=["Lifelink"],
    oracle_text=(
        "Lifelink\n"
        "Whenever Garnet attacks, you may remove a lore counter from each of "
        "any number of Sagas you control. Put a +1/+1 counter on Garnet for "
        "each lore counter removed this way."
    ),
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _garnet(eng):
    o = GameObject(GARNET, owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    eng.state.add_to_battlefield(o)
    bind_from_catalogue(o)
    return o


def _saga(eng, cid, ctrl, lore):
    o = GameObject(
        Card(id=cid, name=cid, type_line="Enchantment — Saga"),
        owner_id=ctrl, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = ctrl
    if lore:
        o.counters["lore"] = lore
    eng.state.add_to_battlefield(o)
    return o


def test_garnet_specs():
    specs = specs_for(GARNET)
    # Lifelink is a plain printed keyword — only the attack trigger is a
    # hand-authored spec.
    triggered = [s for s in specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    assert triggered[0].effects[0].type == (
        "remove_lore_counter_from_chosen_sagas_then_add_counters"
    )


def test_removing_from_chosen_sagas_scales_the_payoff():
    eng = _engine()
    garnet = _garnet(eng)
    s1 = _saga(eng, "S1", "p1", 1)
    s2 = _saga(eng, "S2", "p1", 2)
    _saga(eng, "S3", "p2", 3)  # not the controller's — never offered
    eng.begin_turn()

    build_effects(
        [EffectSpec("remove_lore_counter_from_chosen_sagas_then_add_counters", {})],
        garnet,
    )[0].apply(GameContext(eng.state, eng.rules), targets=None)

    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "choose_objects"
    assert {o.get("instance_id") for o in pc["options"] if o.get("instance_id")} == {
        s1.instance_id, s2.instance_id,
    }
    eng.rules.resolve_choice(s1.instance_id)
    eng.rules.resolve_choice(s2.instance_id)
    eng.resolve_until_stable()

    # `strip_all_counters` removes every lore counter from each pick.
    assert not s1.counters.get("lore")
    assert not s2.counters.get("lore")
    assert garnet.counters.get("+1/+1") == 3  # 1 + 2 lore counters removed


def test_declining_adds_no_counters():
    eng = _engine()
    garnet = _garnet(eng)
    _saga(eng, "S1", "p1", 1)
    eng.begin_turn()

    build_effects(
        [EffectSpec("remove_lore_counter_from_chosen_sagas_then_add_counters", {})],
        garnet,
    )[0].apply(GameContext(eng.state, eng.rules), targets=None)
    eng.rules.resolve_choice(None)
    eng.resolve_until_stable()

    assert not garnet.counters.get("+1/+1")


def test_no_sagas_is_a_noop():
    eng = _engine()
    garnet = _garnet(eng)
    eng.begin_turn()

    build_effects(
        [EffectSpec("remove_lore_counter_from_chosen_sagas_then_add_counters", {})],
        garnet,
    )[0].apply(GameContext(eng.state, eng.rules), targets=None)

    assert eng.state.pending_choice is None
    assert not garnet.counters.get("+1/+1")


LILY_BOWEN = Card(
    id="LILY", name="Lily Bowen, Raging Grandma",
    type_line="Legendary Creature — Mutant Warrior", is_creature=True,
    mana_cost_string="{3}{G}", converted_mana_cost=4, power=0, toughness=0,
    keywords=["Vigilance"],
    oracle_text=(
        "Vigilance\n"
        "Lily Bowen enters with two +1/+1 counters on it.\n"
        "At the beginning of your upkeep, double the number of +1/+1 "
        "counters on Lily Bowen if its power is 16 or less. Otherwise, "
        "remove all but one +1/+1 counter from it, then you gain 1 life "
        "for each +1/+1 counter removed this way."
    ),
)

_LILY_UPKEEP_SPEC = EffectSpec("if_else", {
    "condition": {"kind": "power", "max": 16},
    "then": [
        {"type": "double_counters_on_target", "params": {"mode": "self", "kind": "+1/+1"}},
    ],
    "else": [
        {"type": "remove_counters", "params": {"self_only": True, "kind": "+1/+1", "keep": 1}},
        {"type": "gain_life", "params": {"amount": 1, "count_selector": "counters_removed_this_way"}},
    ],
})


def _lily(eng, lore=2):
    o = GameObject(LILY_BOWEN, owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    if lore:
        o.counters["+1/+1"] = lore
    eng.state.add_to_battlefield(o)
    bind_from_catalogue(o)
    eng.recompute_continuous_effects()
    return o


def test_lily_bowen_specs():
    specs = specs_for(LILY_BOWEN)
    triggered = [s for s in specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    assert triggered[0].effects[0].type == "if_else"


def test_lily_bowen_doubles_when_power_16_or_less():
    eng = _engine()
    lily = _lily(eng, lore=2)
    eng.begin_turn()

    build_effects([_LILY_UPKEEP_SPEC], lily)[0].apply(
        GameContext(eng.state, eng.rules), targets=None
    )

    assert lily.counters.get("+1/+1") == 4


def test_lily_bowen_prunes_and_gains_life_when_power_over_16():
    eng = _engine()
    lily = _lily(eng, lore=20)
    p1 = next(p for p in eng.state.players if p.id == "p1")
    eng.begin_turn()
    life0 = p1.life

    build_effects([_LILY_UPKEEP_SPEC], lily)[0].apply(
        GameContext(eng.state, eng.rules), targets=None
    )

    assert lily.counters.get("+1/+1") == 1
    assert p1.life == life0 + 19


SAGE_OF_HOURS = Card(
    id="SOH", name="Sage of Hours", type_line="Creature — Human Wizard",
    is_creature=True, mana_cost_string="{1}{U}", converted_mana_cost=2,
    power=1, toughness=1, keywords=["Heroic"],
    oracle_text=(
        "Heroic — Whenever you cast a spell that targets this creature, "
        "put a +1/+1 counter on it.\n"
        "Remove all +1/+1 counters from this creature: For each five "
        "counters removed this way, take an extra turn after this one."
    ),
)


def _sage(eng, lore=0):
    o = GameObject(SAGE_OF_HOURS, owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    o.summoning_sick = False
    if lore:
        o.counters["+1/+1"] = lore
    eng.state.add_to_battlefield(o)
    bind_from_catalogue(o)
    return o


def test_sage_of_hours_specs():
    specs = specs_for(SAGE_OF_HOURS)
    kinds = [s.ability_kind for s in specs]
    assert kinds == ["triggered", "activated"]
    assert specs[0].effects[0].type == "add_counters"
    assert specs[0].trigger["requires_spell_targets_source"] is True
    assert specs[1].effects[0].type == "bind"
    assert specs[1].cost == {"remove_counters": ("+1/+1", REMOVE_COUNTERS_ALL)}


def test_sage_of_hours_heroic_trigger_adds_a_counter():
    eng = _engine()
    sage = _sage(eng)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1})
    gg = GameObject(
        Card(id="gg", name="Giant Growth", type_line="Instant", is_instant=True,
             mana_cost_string="{G}",
             oracle_text="Target creature gets +3/+3 until end of turn."),
        owner_id="p1", zone=Zone.HAND,
    )
    gg.controller_id = "p1"
    bind_from_catalogue(gg)
    p1.hand.append(gg)

    eng.cast_spell(p1, gg, targets=[sage])
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert sage.counters.get("+1/+1") == 1


def test_sage_of_hours_removes_all_and_takes_extra_turns_per_five():
    eng = _engine()
    sage = _sage(eng, lore=12)
    eng.begin_turn()
    p1 = eng.state.active_player

    eng.activate_ability(p1, sage, ability_index=0)
    eng.resolve_until_stable()

    assert not sage.counters.get("+1/+1")
    assert sage.counters_removed_as_cost == 12
    assert eng.state.extra_turns == [p1.id, p1.id]  # floor(12 / 5) == 2


def test_sage_of_hours_fewer_than_five_grants_no_extra_turn():
    eng = _engine()
    sage = _sage(eng, lore=3)
    eng.begin_turn()
    p1 = eng.state.active_player

    eng.activate_ability(p1, sage, ability_index=0)
    eng.resolve_until_stable()

    assert not sage.counters.get("+1/+1")
    assert eng.state.extra_turns == []


def test_sage_of_hours_no_counters_is_still_a_legal_activation():
    eng = _engine()
    sage = _sage(eng, lore=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    eng.activate_ability(p1, sage, ability_index=0)
    eng.resolve_until_stable()

    assert eng.state.extra_turns == []
