"""PAR-30 — Suspect (RULE 701.60) one-off shapes: the four
primitive-blocked singletons the PAR-29 keyword trail left behind.

- **Agrus Kos, Spirit of Justice** — `previous_target_is_suspected`: an
  if/else over the chosen creature's own suspected state, emitted as two
  mutually complementary condition-gated specs ("if it's suspected, exile
  it. otherwise, suspect it.").
- **Clandestine Meddler** — "suspect up to one **other** target creature you
  control" (a new `subgrammars` target row) + "whenever one or more
  **suspected** creatures you control attack, surveil 1"
  (`_batch_attack_group_filter` / `_any_attacking_matches` ``is_suspected``).
- **Deadly Complication** — `RemoveSuspectedEffect` gains a
  ``previous_subject`` / ``optional`` shape for "you may have it become no
  longer suspected." (routed through `_request_choose_objects`).
- **Airtight Alibi** — hand-authored: ETB untap + hexproof-EOT + un-suspect
  on the Aura host, plus a static +2/+2 and a ``cant_become_suspected``
  ``grant_keyword`` slug `RulesEngine.suspect` honours.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


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


def _spec_source(eng, name, zone=Zone.STACK):
    src = GameObject(_db().get_card(name), owner_id="p1", zone=zone)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    return src


def _run(eng, src, specs, targets=None):
    effs = build_effects(specs, src)
    _apply_effects_partitioned(effs, eng.rules.context, targets, None, source=src)


# --- all four are covered --------------------------------------------------


def test_all_four_covered():
    db = _db()
    parser = ("Agrus Kos, Spirit of Justice", "Clandestine Meddler", "Deadly Complication")
    for name in parser:
        r = parse_oracle(db.get_card(name))
        assert r.coverage != UNMODELED, (name, r.unclaimed)
    # Airtight Alibi is hand-authored, not parser-MODELED.
    from mtg_analyzer.game.ability_catalogue import specs_for
    assert specs_for(db.get_card("Airtight Alibi"))


# --- Agrus Kos, Spirit of Justice ----------------------------------------------


def test_agrus_kos_parse_emits_complementary_conditionals():
    specs = parse_oracle(_db().get_card("Agrus Kos, Spirit of Justice")).specs
    trig = next(s for s in specs if s.ability_kind == "triggered")
    assert [(e.type, e.condition) for e in trig.effects] == [
        ("exile", {"previous_target_is_suspected": True}),
        ("suspect", {"previous_target_is_suspected": False}),
    ]


def test_agrus_kos_exiles_a_suspected_target():
    eng, state = _engine()
    victim = _creature("Victim", "p2")
    state.add_to_battlefield(victim)
    eng.rules.suspect(victim)
    src = _spec_source(eng, "Agrus Kos, Spirit of Justice")

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    _run(eng, src, trig.effects, targets=[victim])

    assert victim not in state.battlefield          # exiled (it was suspected)
    assert victim.zone == Zone.EXILE


def test_agrus_kos_suspects_an_unsuspected_target():
    eng, state = _engine()
    victim = _creature("Victim", "p2")
    state.add_to_battlefield(victim)
    src = _spec_source(eng, "Agrus Kos, Spirit of Justice")

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    _run(eng, src, trig.effects, targets=[victim])

    assert victim in state.battlefield              # not exiled
    assert victim.is_suspected is True              # otherwise-branch fired


def test_agrus_kos_up_to_one_no_target_is_a_noop():
    eng, state = _engine()
    src = _spec_source(eng, "Agrus Kos, Spirit of Justice")
    bystander = _creature("Bystander", "p2")
    state.add_to_battlefield(bystander)

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    _run(eng, src, trig.effects, targets=[])

    assert bystander in state.battlefield and bystander.is_suspected is False


# --- Clandestine Meddler ------------------------------------------------------


def test_clandestine_meddler_suspect_up_to_one_other_target_parses():
    assert match_clause("suspect up to 1 other target creature you control") == [
        EffectSpec("suspect", {"target_kind": "other_creature_you_control", "optional": True})
    ]


def test_clandestine_meddler_batch_attack_trigger_wants_suspected():
    specs = parse_oracle(_db().get_card("Clandestine Meddler")).specs
    atk = next(s for s in specs if s.trigger and s.trigger.get("event") == "PLAYER_ATTACKED")
    assert atk.trigger["condition"]["group_filter"] == {"is_suspected": True}


def test_clandestine_meddler_surveil_trigger_fires_only_for_a_suspected_attacker():
    eng, state = _engine()
    meddler = GameObject(_db().get_card("Clandestine Meddler"), owner_id="p1",
                         zone=Zone.BATTLEFIELD)
    meddler.controller_id = "p1"
    bind_from_catalogue(meddler)
    state.add_to_battlefield(meddler)

    attacker = _creature("Attacker", "p1")
    state.add_to_battlefield(attacker)
    attacker.attacking = True

    def _fire():
        eng.rules.pending_triggers.clear()
        state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, controller_id="p1",
                                   attacking_player_id="p1"))
        return eng.rules.put_triggers_on_stack()

    assert _fire() == 0                       # plain attacker → no surveil trigger
    eng.rules.suspect(attacker)
    assert _fire() == 1                       # suspected attacker → RULE 508.3a batch trigger


# --- Deadly Complication -----------------------------------------------------


def _deadly_mode2_specs():
    modes = parse_oracle(_db().get_card("Deadly Complication")).specs[0].modes
    return modes["options"][1]  # "put a +1/+1 counter … you may have it become no longer suspected"


def test_deadly_complication_mode2_parse():
    got = [(e.type, e.params) for e in _deadly_mode2_specs()]
    assert got == [
        ("add_counters", {"count": 1, "kind": "+1/+1",
                          "target_kind": "creature_you_control",
                          "creature_filter": {"is_suspected": True}}),
        ("remove_suspected", {"previous_subject": True, "optional": True}),
    ]


def test_deadly_complication_mode2_counter_then_optional_unsuspect_taken():
    eng, state = _engine()
    target = _creature("Target", "p1")
    state.add_to_battlefield(target)
    eng.rules.suspect(target)
    src = _spec_source(eng, "Deadly Complication")

    _run(eng, src, _deadly_mode2_specs(), targets=[target])

    # the "you may" opens an interactive choose-objects pick; take it
    guard = 0
    while state.pending_choice and guard < 4:
        guard += 1
        eng.rules.resolve_choice(
            state.pending_choice["options"][0]["instance_id"]
        )
    assert target.plus_one_counters == 1
    assert target.is_suspected is False        # un-suspect taken


def test_deadly_complication_mode2_optional_unsuspect_declined():
    eng, state = _engine()
    target = _creature("Target", "p1")
    state.add_to_battlefield(target)
    eng.rules.suspect(target)
    src = _spec_source(eng, "Deadly Complication")

    _run(eng, src, _deadly_mode2_specs(), targets=[target])

    guard = 0
    while state.pending_choice and guard < 4:
        guard += 1
        eng.rules.resolve_choice(None)   # decline
    assert target.plus_one_counters == 1
    assert target.is_suspected is True         # declined → menace kept


# --- Airtight Alibi (hand-authored) ----------------------------------------


def _airtight_on(state, host):
    aura = GameObject(_db().get_card("Airtight Alibi"), owner_id="p1",
                      zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    aura.attached_to = host.instance_id
    bind_from_catalogue(aura)
    state.add_to_battlefield(aura)
    return aura


def test_airtight_alibi_etb_untaps_and_unsuspects_the_host():
    eng, state = _engine()
    host = _creature("Host", "p1")
    host.tapped = True
    state.add_to_battlefield(host)
    eng.rules.suspect(host)
    aura = _airtight_on(state, host)

    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=aura.instance_id,
        controller_id="p1", object_types=sorted(aura.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert host.tapped is False
    assert host.is_suspected is False
    eng.recompute_continuous_effects()
    assert "hexproof" in host.granted_keywords


def test_airtight_alibi_static_pumps_and_blocks_suspect():
    eng, state = _engine()
    host = _creature("Host", "p1", power=2, tough=2)
    state.add_to_battlefield(host)
    _airtight_on(state, host)
    eng.recompute_continuous_effects()

    assert (host.power, host.toughness) == (4, 4)      # +2/+2 anthem

    eng.rules.suspect(host)                            # RULE 701.60c — prohibited
    assert host.is_suspected is False
