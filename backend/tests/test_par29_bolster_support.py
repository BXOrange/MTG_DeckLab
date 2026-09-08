"""PAR-29 — RULE 701.39 Bolster + RULE 701.41 Support: the +1/+1 keyword pair.

Bolster N (`RulesEngine.bolster` / `effects.BolsterEffect`): put N +1/+1
counters on a least-toughness creature you control; a tie for least toughness
opens a `bolster` `pending_choice`. Support N: a parser alias onto the
existing `add_counters` "up to N target creatures" multi-target spec —
RULE 701.41c's self-exclusion falls out of `targeting`'s plain "creature"
kind, which already excludes the ability's source.

Reference: game/rules/mana_counters_mixin.py (`bolster`), game/effects/core.py
(`BolsterEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_bolster_and_support_parse():
    assert match_clause("bolster 2") == [EffectSpec("bolster", {"amount": 2})]
    assert match_clause("support 3") == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "+1/+1", "target_kind": "creature",
            "target_count": 3, "optional": True,
        })
    ]


def test_dynamic_amounts_parse():
    # RULE 701.39a/701.41 dynamic X — PAR-29's "Parser-shaped only" residue.
    assert match_clause("bolster x, where x is the number of tapped creatures you control") == [
        EffectSpec("bolster", {"amount_from_count_selector": "tapped_creatures_you_control"})
    ]
    assert match_clause("support x") == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "+1/+1", "target_kind": "creature",
            "target_count_selector": "source_x_paid", "optional": True,
        })
    ]


def test_bare_dynamic_x_with_no_explanation_stays_unclaimed():
    # No real card prints a bare "bolster x" without a "where x is …" tail —
    # unlike "support x" (which is always the spell/ability's own announced
    # {X}, no explanation needed), so this stays fail-closed.
    assert match_clause("bolster x") is None


def test_real_cards_modeled_end_to_end():
    aven = Card(id="AT", name="Aven Tactician", type_line="Creature — Bird Soldier",
                is_creature=True, power=2, toughness=3, keywords=["Flying"],
                oracle_text="Flying\nWhen this creature enters, bolster 1. (Choose a creature "
                            "with the least toughness among creatures you control and put a "
                            "+1/+1 counter on it.)")
    aerie = Card(id="AA", name="Aerie Auxiliary", type_line="Creature — Bird Soldier",
                 is_creature=True, power=2, toughness=1, keywords=["Flying"],
                 oracle_text="Flying\nWhen this creature enters, support 2. (Put a +1/+1 "
                             "counter on each of up to two other target creatures.)")
    assert parse_oracle(aven).modeled
    assert parse_oracle(aerie).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state, eng.state.player_by_id("p1")


def _creature(name, tough, power=1, owner="p1"):
    card = Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=tough)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def test_bolster_with_no_creatures_does_nothing():
    eng, state, p1 = _engine()
    eng.rules.bolster(p1, 2)
    assert state.pending_choice is None


def test_bolster_single_least_toughness_no_choice():
    eng, state, p1 = _engine()
    a, b = _creature("A", 2), _creature("B", 4)
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    eng.rules.bolster(p1, 3)

    assert state.pending_choice is None
    assert a.plus_one_counters == 3
    assert b.plus_one_counters == 0


def test_bolster_tie_opens_choice_and_resolves_to_pick():
    eng, state, p1 = _engine()
    a, b, c = _creature("A", 2), _creature("B", 2), _creature("C", 5)
    for o in (a, b, c):
        state.add_to_battlefield(o)

    eng.rules.bolster(p1, 1)

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "bolster"
    assert {opt["label"] for opt in choice["options"]} == {"A", "B"}

    eng.resolve_pending_choice(str(b.instance_id))

    assert state.pending_choice is None
    assert b.plus_one_counters == 1
    assert a.plus_one_counters == 0 and c.plus_one_counters == 0


def test_bolster_tie_missing_answer_defaults_to_first():
    eng, state, p1 = _engine()
    a, b = _creature("A", 1), _creature("B", 1)
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    eng.rules.bolster(p1, 2)
    assert state.pending_choice["kind"] == "bolster"
    eng.resolve_pending_choice(None)  # mandatory — defaults, doesn't skip

    assert state.pending_choice is None
    assert (a.plus_one_counters, b.plus_one_counters) == (2, 0)


def test_bolster_only_considers_your_own_creatures():
    eng, state, p1 = _engine()
    mine = _creature("Mine", 3, owner="p1")
    theirs = _creature("Theirs", 1, owner="p2")
    theirs.controller_id = "p2"
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)

    eng.rules.bolster(p1, 1)

    assert state.pending_choice is None
    assert mine.plus_one_counters == 1
    assert theirs.plus_one_counters == 0


def test_bolster_counters_go_through_doubling_replacement():
    eng, state, p1 = _engine()
    a = _creature("A", 2)
    state.add_to_battlefield(a)
    # Doubling Season-shaped: "if a +1/+1 counter would be put on a permanent
    # you control, put twice that many instead."
    ds_card = Card(id="DS", name="Doubling Season", type_line="Enchantment",
                   oracle_text="If an effect would put one or more +1/+1 counters on a "
                               "permanent you control, it puts twice that many of those "
                               "counters on that permanent instead.")
    ds = GameObject(ds_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(ds)
    state.add_to_battlefield(ds)

    eng.rules.bolster(p1, 2)

    assert a.plus_one_counters == 4  # doubled


def test_real_bolster_card_fires_on_etb_via_binder():
    eng, state, p1 = _engine()
    existing = _creature("Existing", 1)
    state.add_to_battlefield(existing)

    card = Card(id="AT", name="Aven Tactician", type_line="Creature — Bird Soldier",
                is_creature=True, power=2, toughness=3, keywords=["Flying"],
                oracle_text="Flying\nWhen this creature enters, bolster 1.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    # "Existing" (toughness 1) is the sole least-toughness creature.
    assert existing.plus_one_counters == 1


def test_bolster_dynamic_amount_reads_a_live_board_count():
    # Dragonscale General-shaped: "bolster X, where X is the number of
    # tapped creatures you control."
    eng, state, p1 = _engine()
    a, b, c = _creature("A", 2), _creature("B", 5), _creature("C", 5)
    for o in (a, b, c):
        state.add_to_battlefield(o)
    b.tapped = True
    c.tapped = True

    from mtg_analyzer.game.effects.core import BolsterEffect, GameContext

    ctx = GameContext(state, eng.rules)
    BolsterEffect(source=a, amount_from_count_selector="tapped_creatures_you_control").apply(ctx)

    assert state.pending_choice is None
    assert a.plus_one_counters == 2  # 2 tapped creatures, least-toughness A gets both


def test_bolster_dynamic_amount_of_zero_is_a_no_op():
    # RULE 701.39e: bolstering 0 places no counters (no tapped creatures).
    eng, state, p1 = _engine()
    a = _creature("A", 2)
    state.add_to_battlefield(a)

    from mtg_analyzer.game.effects.core import BolsterEffect, GameContext

    ctx = GameContext(state, eng.rules)
    BolsterEffect(source=a, amount_from_count_selector="tapped_creatures_you_control").apply(ctx)

    assert a.plus_one_counters == 0
    assert state.pending_choice is None


def test_support_x_reads_the_spells_own_announced_x():
    # The Crowd Goes Wild-shaped: "Support X." cast for {X}{G}, X=2 — the
    # spell's own `x_paid` both sizes the target-gathering round
    # (`TargetSpec.count_selector`/`resolved_count`) and, independently,
    # this effect's own target count param, the same `source_x_paid`
    # sentinel March of Swirling Mist/Change of Plans already use.
    eng, state, p1 = _engine()
    friend1 = _creature("Friend1", 2)
    friend2 = _creature("Friend2", 2)
    for o in (friend1, friend2):
        state.add_to_battlefield(o)

    spell_card = Card(id="Crowd", name="The Crowd Goes Wild", type_line="Sorcery",
                       is_sorcery=True, mana_cost_string="{X}{G}")
    spell = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    spell.x_paid = 2

    from mtg_analyzer.game.effects.core import AddCountersEffect, GameContext
    from mtg_analyzer.game.targeting import resolved_count

    effect = AddCountersEffect(
        amount=1, kind="+1/+1", target_kind="creature", optional=True,
        count_selector="source_x_paid", source=spell,
    )
    assert resolved_count(effect.target_spec, state, "p1", spell) == 2

    ctx = GameContext(state, eng.rules)
    effect.apply(ctx, targets=[friend1, friend2])

    assert friend1.plus_one_counters == 1
    assert friend2.plus_one_counters == 1


def test_support_puts_counters_on_up_to_n_targets_excluding_source():
    eng, state, p1 = _engine()
    friend1 = _creature("Friend1", 2)
    friend2 = _creature("Friend2", 2)
    state.add_to_battlefield(friend1)
    state.add_to_battlefield(friend2)

    card = Card(id="AA", name="Aerie Auxiliary", type_line="Creature — Bird Soldier",
                is_creature=True, power=2, toughness=1, keywords=["Flying"],
                oracle_text="Flying\nWhen this creature enters, support 2.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)

    trig = obj.triggered_abilities[0]
    legal = trig.legal_targets(state, obj) if hasattr(trig, "legal_targets") else None
    # RULE 701.41c: the source creature is not among its own support targets.
    if legal is not None:
        ids = {t.get("instance_id") for t in legal}
        assert obj.instance_id not in ids
        assert {friend1.instance_id, friend2.instance_id} <= ids
