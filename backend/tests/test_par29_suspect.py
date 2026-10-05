"""PAR-29 — RULE 701.60 Suspect (Murders at Karlov Manor).

A designation like goad: `GameObject.is_suspected` (`RulesEngine.suspect` /
`remove_suspected`), with RULE 701.60b's menace + can't-block read off the
flag at combat time (`combat.is_suspected`, `has_menace`,
`combat_mixin.can_block`). `effects.SuspectEffect` resolves *which* creature
(self / previous-clause pronoun / Aura host / target); `RemoveSuspectedEffect`
is Absolving Lammasu's "all suspected creatures are no longer suspected".

Reference: game/rules/misc_mixin.py (`suspect`), game/combat.py
(`is_suspected`), game/effects/core.py, parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_suspect_subject_shapes_parse():
    assert match_clause("suspect it", self_subject=True) == [EffectSpec("suspect", {})]
    assert match_clause("suspect it") is None
    assert match_clause("suspect it", previous_subject=True) == [
        EffectSpec("suspect", {"previous_subject": True})
    ]
    assert match_clause("suspect enchanted creature") == [
        EffectSpec("suspect", {"attached": True})
    ]
    assert match_clause("suspect target creature an opponent controls") == [
        EffectSpec("suspect", {"target_kind": "creature_you_dont_control"})
    ]


def test_remove_suspected_all_parses():
    assert match_clause("all suspected creatures are no longer suspected") == [
        EffectSpec("remove_suspected", {})
    ]


def test_real_suspect_cards_modeled_end_to_end():
    servitor = Card(id="BS", name="Barbed Servitor",
                    type_line="Artifact Creature — Construct", is_creature=True,
                    power=3, toughness=3, keywords=["Indestructible"],
                    oracle_text="Indestructible\nWhen this creature enters, suspect it. "
                                "(It has menace and can't block.)")
    assert parse_oracle(servitor).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(name, owner, power=2, tough=2):
    card = Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=tough)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    return obj


def test_suspect_sets_flag_and_fires_event():
    eng, state = _engine()
    c = _creature("C", "p1")
    state.add_to_battlefield(c)
    fired = []
    state.subscribe(lambda e: fired.append(e.get("instance_id"))
                    if e.type == EventType.SUSPECTED else None)

    eng.rules.suspect(c)

    assert c.is_suspected is True
    assert fired == [c.instance_id]
    assert combat.is_suspected(c) and combat.has_menace(c)


def test_suspect_non_creature_is_a_noop():
    eng, state = _engine()
    art_card = Card(id="A", name="Rock", type_line="Artifact")
    art = GameObject(art_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(art)

    eng.rules.suspect(art)

    assert art.is_suspected is False


def test_suspected_creature_cannot_block():
    eng, state = _engine()
    attacker = _creature("Attacker", "p1", power=2, tough=2)
    blocker = _creature("Blocker", "p2", power=2, tough=2)
    state.add_to_battlefield(attacker)
    state.add_to_battlefield(blocker)
    state.current_step = "declare_attackers"
    eng.declare_attackers(
        state.player_by_id("p1"),
        [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}],
    )

    p2 = state.player_by_id("p2")
    assert eng.can_block(p2, blocker, attacker) is True

    eng.rules.suspect(blocker)
    assert eng.can_block(p2, blocker, attacker) is False  # RULE 701.60b

    eng.rules.remove_suspected([blocker])
    assert eng.can_block(p2, blocker, attacker) is True


def test_suspected_attacker_has_menace_min_blockers():
    eng, state = _engine()
    a = _creature("A", "p1")
    assert combat.min_blockers(a) == 1
    a.is_suspected = True
    assert combat.min_blockers(a) == 2  # RULE 701.60b menace


def test_remove_suspected_effect_clears_all():
    eng, state = _engine()
    a, b, c = _creature("A", "p1"), _creature("B", "p1"), _creature("C", "p2")
    for o in (a, b, c):
        state.add_to_battlefield(o)
        eng.rules.suspect(o)
    assert all(o.is_suspected for o in (a, b, c))

    lam_card = Card(id="AL", name="Absolving Lammasu", type_line="Creature — Lammasu",
                    is_creature=True, power=4, toughness=4, keywords=["Flying"],
                    oracle_text="Flying\nWhen this creature enters, all suspected "
                                "creatures are no longer suspected.")
    lam = GameObject(lam_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lam)
    state.add_to_battlefield(lam)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=lam.instance_id,
        controller_id="p1", object_types=sorted(lam.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert not any(o.is_suspected for o in (a, b, c))


def test_real_card_suspects_self_on_etb_via_binder():
    eng, state = _engine()
    card = Card(id="BS", name="Barbed Servitor",
                type_line="Artifact Creature — Construct", is_creature=True,
                power=3, toughness=3, keywords=["Indestructible"],
                oracle_text="Indestructible\nWhen this creature enters, suspect it.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert obj.is_suspected is True


def test_aura_suspect_enchanted_creature_via_binder():
    eng, state = _engine()
    host = _creature("Host", "p2")
    state.add_to_battlefield(host)

    aura_card = Card(id="CT", name="Convenient Target", type_line="Enchantment — Aura",
                     oracle_text="Enchant creature\nWhen this Aura enters, suspect "
                                 "enchanted creature.")
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.attached_to = host.instance_id
    bind_from_catalogue(aura)
    state.add_to_battlefield(aura)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=aura.instance_id,
        controller_id="p1", object_types=sorted(aura.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert host.is_suspected is True


def test_leaving_battlefield_clears_suspected():
    eng, state = _engine()
    c = _creature("C", "p1")
    state.add_to_battlefield(c)
    eng.rules.suspect(c)
    assert c.is_suspected

    c.reset_as_new_object()  # RULE 400.7 — the new object isn't suspected
    assert c.is_suspected is False


# --- PAR-29 residue: "target suspected creature you control" -------------
#
# The "put a +1/+1 counter on target suspected creature you control" row and
# its `combat.matches_object_filter` ``is_suspected`` key. Deadly
# Complication's own second sentence ("You may have it become no longer
# suspected.") closed at PARSER_VERSION 210 — see
# `test_par30_suspect_one_off_shapes.py`.


def test_suspected_creature_target_filter_parses():
    assert match_clause("put a +1/+1 counter on target suspected creature you control") == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "+1/+1", "target_kind": "creature_you_control",
            "creature_filter": {"is_suspected": True},
        })
    ]


def test_matches_object_filter_is_suspected_key():
    eng, state = _engine()
    suspected = _creature("Suspected", "p1")
    plain = _creature("Plain", "p1")
    state.add_to_battlefield(suspected)
    state.add_to_battlefield(plain)
    eng.rules.suspect(suspected)

    assert combat.matches_object_filter(suspected, {"is_suspected": True}) is True
    assert combat.matches_object_filter(plain, {"is_suspected": True}) is False
    assert combat.matches_object_filter(plain, {}) is True  # empty filter matches everything


def test_add_counters_effect_only_offers_suspected_creatures_as_legal_targets():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    eng, state = _engine()
    suspected = _creature("Suspected", "p1")
    plain = _creature("Plain", "p1")
    state.add_to_battlefield(suspected)
    state.add_to_battlefield(plain)
    eng.rules.suspect(suspected)

    spec = TargetSpec(kind="creature_you_control", creature_filter={"is_suspected": True})
    offered = {o["instance_id"] for o in legal_targets(state, "p1", spec)}
    assert offered == {suspected.instance_id}


def test_add_counters_effect_puts_counter_on_the_suspected_target():
    from mtg_analyzer.game.effects.core import AddCountersEffect, GameContext

    eng, state = _engine()
    suspected = _creature("Suspected", "p1")
    state.add_to_battlefield(suspected)
    eng.rules.suspect(suspected)

    ctx = GameContext(state, eng.rules)
    AddCountersEffect(
        amount=1, kind="+1/+1", target_kind="creature_you_control",
        creature_filter={"is_suspected": True},
    ).apply(ctx, targets=[suspected])

    assert suspected.plus_one_counters == 1
