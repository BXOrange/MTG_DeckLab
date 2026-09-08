"""RULE 603.11 reflexive "When you do, <targeted payoff>." after an optional
keyword-action cost.

`pay_cost_then` already handled "you may <cost>. If you do, <effect>." but
its branch effects resolve **off the stack**, so a RULE 115 target could
never be chosen — the handler rejected any targeted follow-up outright.
That's the whole "when you do, <targeted payoff>" residue of the Collect
Evidence / Forage / Blight bullet (Sample Collector, Curious Forager,
Warren Torchmaster).

Now: a paid cost enqueues the payoff as its own `TriggeredAbility` on
`pending_triggers` (`RulesEngine._enqueue_pay_cost_then_trigger`), so the
ordinary placement path gathers its target and puts it on the stack.
`PayCostThenEffect.then_trigger_specs` carries the serialized payoff;
`_pay_cost_then_general` emits it when the follow-up is targeted.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _gy_card(pid, name, mv):
    return GameObject(
        Card(id=name[:8], name=name, type_line="Creature — Bear", is_creature=True,
             power=1, toughness=1, mana_cost_string="{%d}" % mv, converted_mana_cost=mv),
        owner_id=pid, zone=Zone.GRAVEYARD,
    )


# --- parse -------------------------------------------------------------------


def test_targeted_when_you_do_emits_then_trigger():
    specs = match_clause(
        "you may collect evidence 3. when you do, put a +1/+1 counter on target "
        "creature you control",
        self_subject=True,
    )
    assert specs is not None and specs[0].type == "pay_cost_then"
    p = specs[0].params
    assert p["cost"] == "collect evidence 3"
    assert p["then_trigger"] == [
        {"type": "add_counters", "params": {
            "count": 1, "kind": "+1/+1", "target_kind": "creature_you_control",
        }},
    ]
    assert "effects" not in p  # not the off-stack branch

    # an *untargeted* follow-up still uses the plain off-stack `effects`
    plain = match_clause(
        "you may collect evidence 3. when you do, you draw a card", self_subject=True
    )
    assert plain is not None and "effects" in plain[0].params
    assert "then_trigger" not in plain[0].params


def test_real_cards_modeled():
    db = _db()
    for name in ("Sample Collector", "Curious Forager", "Warren Torchmaster"):
        card = db.get_card(name)
        assert card is not None, name
        assert parse_oracle(card).coverage != UNMODELED, (name, parse_oracle(card).unclaimed)


# --- execute ---------------------------------------------------------------------


def test_sample_collector_reflexive_counter_goes_on_the_stack_and_targets():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    for i in range(2):
        p1.graveyard.append(_gy_card("p1", f"GY{i}", 2))  # total MV 4 ≥ 3

    collector = GameObject(_db().get_card("Sample Collector"), owner_id="p1", zone=Zone.BATTLEFIELD)
    collector.controller_id = "p1"
    collector.summoning_sick = False
    bind_from_catalogue(collector)
    st.add_to_battlefield(collector)

    ally = GameObject(Card(id="ally", name="Ally", type_line="Creature — Elf",
                           is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    ally.controller_id = "p1"
    st.add_to_battlefield(ally)

    # resolve the ATTACKS trigger's effect body directly
    trig = next(s for s in parse_oracle(collector.card).specs if s.ability_kind == "triggered")
    effs = build_effects(trig.effects, collector)
    _apply_effects_partitioned(effs, eng.rules.context, None, None, source=collector)

    # the pay-cost-then choice is open
    assert st.pending_choice is not None and st.pending_choice["kind"] == "pay_cost_then"
    eng.rules.resolve_pay_cost_then_choice("pay")

    # collect evidence 3 exiled from the graveyard
    assert sum(1 for c in p1.exile) >= 1
    # the reflexive counter ability is now queued / on the stack, wanting a target
    eng.resolve_until_stable()
    choice = st.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    opts = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert ally.instance_id in opts and collector.instance_id in opts

    eng.rules.resolve_trigger_target_choice(ally.instance_id)
    eng.resolve_until_stable()
    assert ally.counters.get("+1/+1") == 1


def test_no_reflexive_trigger_when_the_cost_is_declined():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    p1.graveyard.append(_gy_card("p1", "GY", 5))

    collector = GameObject(_db().get_card("Sample Collector"), owner_id="p1", zone=Zone.BATTLEFIELD)
    collector.controller_id = "p1"
    collector.summoning_sick = False
    bind_from_catalogue(collector)
    st.add_to_battlefield(collector)
    ally = GameObject(Card(id="ally", name="Ally", type_line="Creature — Elf",
                           is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    ally.controller_id = "p1"
    st.add_to_battlefield(ally)

    trig = next(s for s in parse_oracle(collector.card).specs if s.ability_kind == "triggered")
    _apply_effects_partitioned(build_effects(trig.effects, collector), eng.rules.context, None, None, source=collector)
    eng.rules.resolve_pay_cost_then_choice(None)  # decline
    eng.resolve_until_stable()

    assert not st.pending_choice
    assert ally.counters.get("+1/+1") in (None, 0)
    assert not p1.exile  # nothing collected


def test_mana_cost_variant_surgespanner_bounce():
    # the primitive is not collect-evidence-specific: "you may pay {1}{U}.
    # If you do, return target permanent to its owner's hand." is the same
    # reflexive-trigger shape, and the widest real family it unlocks.
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Surgespanner"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.summoning_sick = False
    bind_from_catalogue(src)
    st.add_to_battlefield(src)
    victim = GameObject(Card(id="tok", name="Bird", type_line="Creature — Bird",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    st.add_to_battlefield(victim)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    _apply_effects_partitioned(build_effects(trig.effects, src), eng.rules.context, None, None, source=src)
    assert st.pending_choice and st.pending_choice["kind"] == "pay_cost_then"
    eng.rules.resolve_pay_cost_then_choice("pay")
    eng.resolve_until_stable()

    assert st.pending_choice and st.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_trigger_target_choice(victim.instance_id)
    eng.resolve_until_stable()
    assert victim in p2.hand and victim not in st.battlefield


def test_warren_torchmaster_reflexive_haste_grant_resolves():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    for i in range(2):
        p1.graveyard.append(_gy_card("p1", f"GY{i}", 1))  # ≥1 card → blight payable? no
    # blight 1 = put a -1/-1 counter on a creature you control; needs a creature
    torch = GameObject(_db().get_card("Warren Torchmaster"), owner_id="p1", zone=Zone.BATTLEFIELD)
    torch.controller_id = "p1"
    torch.summoning_sick = False
    bind_from_catalogue(torch)
    st.add_to_battlefield(torch)
    goblin = GameObject(Card(id="gob", name="Goblin", type_line="Creature — Goblin",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    goblin.controller_id = "p1"
    goblin.summoning_sick = True
    st.add_to_battlefield(goblin)

    trig = next(s for s in parse_oracle(torch.card).specs if s.ability_kind == "triggered")
    _apply_effects_partitioned(build_effects(trig.effects, torch), eng.rules.context, None, None, source=torch)
    assert st.pending_choice and st.pending_choice["kind"] == "pay_cost_then"
    eng.rules.resolve_pay_cost_then_choice("pay")
    eng.resolve_until_stable()

    # reflexive "target creature gains haste until end of turn"
    if st.pending_choice and st.pending_choice["kind"] == "trigger_target":
        eng.rules.resolve_trigger_target_choice(goblin.instance_id)
        eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert "haste" in (goblin.granted_keywords or [])
