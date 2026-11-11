"""PAR-266: goad variants -- "~ and that creature are goaded for as long as you control ~" (Kang, Suspicious
Captain), the static group form "All Tribbles get +1/+0 and are goaded" (Koloth, Tribble Hunter) and the batch head
"whenever 1 or more goaded creatures attack". RULE 701.15b (goaded designation), 611.2b ("for as long as" duration),
611.3a (a static effect lasts while its source is on the battlefield), 508.3a (batch attack trigger).

Real cached cards on a real `GameEngine`; the parser-shape tests use the same text through the real gate.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, vanilla

KANG = "Kang, Suspicious Captain"
KOLOTH = "Koloth, Tribble Hunter"


def _kang_enters(engine, player, kang, victim):
    """Cast Kang and answer the "choose target creature an opponent controls" prompt with ``victim``."""
    player.mana_pool.add_many({"C": 12, "R": 3})
    engine.cast_spell(player, kang)
    for _ in range(6):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if not choice:
            break
        engine.resolve_pending_choice(next(o["id"] for o in choice["options"]
                                           if str(o["id"]) == str(victim.instance_id)))
    engine.recompute_continuous_effects()


def _attack_and_settle(engine, player, *attackers):
    """Declare ``attackers`` and answer every trigger-target prompt with the first option offered."""
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    defender = engine.legal_defenders_for(player)[0]
    for obj in attackers:
        obj.summoning_sick = False
    engine.declare_attackers(player, [{"attacker": a, "defender": defender} for a in attackers])
    engine._fire_player_attacked_events()
    for _ in range(6):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if not choice:
            return
        engine.resolve_pending_choice(choice["options"][0]["id"])


@pytest.mark.parametrize("name", [KANG, KOLOTH])
def test_real_cards_are_modeled(name):
    card = get_cached_card(name)
    assert card is not None and parse_oracle(card).modeled


def test_while_controlling_clause_shape():
    card = get_cached_card(KANG)
    spec = parse_oracle(card).specs[0]
    grants = [e for e in spec.effects if e.type == "grant_until"]
    assert {bool(g.params.get("self_subject")) for g in grants} == {True, False}
    assert all(g.params["duration"] == "for_as_long_as" and g.params["static"]["type"] == "goaded" for g in grants)
    assert all(g.params["condition"] == {"kind": "source_controlled_by_you"} for g in grants)


def test_kang_goads_itself_and_the_chosen_creature_for_the_goader():
    eng, p1, p2 = game(KANG)
    victim = vanilla(eng, "p2", "Victim")
    other = vanilla(eng, "p2", "Bystander")
    kang = p1.hand[0]
    _kang_enters(eng, p1, kang, victim)
    assert combat.goaders(victim) == {"p1"}  # RULE 701.15b: goaded by the ability's controller
    assert combat.goaders(kang) == {"p1"}  # "Kang and that creature"
    assert not combat.is_goaded(other)  # only the chosen creature, not every opposing creature


def test_goad_ends_when_kang_leaves_the_battlefield():
    # RULE 611.2b: "for as long as you control ~" ends, for good, when the source stops being controlled.
    eng, p1, p2 = game(KANG)
    victim = vanilla(eng, "p2", "Victim")
    kang = p1.hand[0]
    _kang_enters(eng, p1, kang, victim)
    assert combat.is_goaded(victim)
    eng.rules._move_to_graveyard(kang)
    eng.recompute_continuous_effects()
    assert kang.zone != Zone.BATTLEFIELD
    assert not combat.is_goaded(victim)


def test_goad_ends_when_kang_changes_controller_and_does_not_return():
    eng, p1, p2 = game(KANG)
    victim = vanilla(eng, "p2", "Victim")
    kang = p1.hand[0]
    _kang_enters(eng, p1, kang, victim)
    kang.controller_id = "p2"
    eng.recompute_continuous_effects()
    assert not combat.is_goaded(victim)
    kang.controller_id = "p1"  # regaining Kang does not revive an effect that already ended
    eng.recompute_continuous_effects()
    assert not combat.is_goaded(victim)


def test_koloth_goads_every_tribble_of_every_controller_and_pumps_them():
    eng, p1, p2 = game(KOLOTH)
    koloth = on_battlefield(eng, "p1", KOLOTH)
    mine = vanilla(eng, "p1", "Bear")  # a non-Tribble creature: must not be goaded
    tribbles = []
    for owner in ("p1", "p2"):
        t = vanilla(eng, owner, "Tribble", 1, 1)
        t.card.type_line = "Token Creature — Tribble"
        tribbles.append(t)
    eng.recompute_continuous_effects()
    for t in tribbles:
        assert t.has_subtype("tribble")
        assert combat.goaders(t) == {"p1"}  # the static's controller is the goader, whoever owns the Tribble
        assert t.power == 2  # +1/+0 on a 1/1
    assert not combat.is_goaded(koloth) and not combat.is_goaded(mine)


def test_koloth_static_ends_with_koloth():
    # RULE 611.3a: the static effect lasts only while Koloth is on the battlefield.
    eng, p1, p2 = game(KOLOTH)
    koloth = on_battlefield(eng, "p1", KOLOTH)
    t = vanilla(eng, "p2", "Tribble", 1, 1)
    t.card.type_line = "Token Creature — Tribble"
    eng.recompute_continuous_effects()
    assert combat.is_goaded(t)
    eng.rules._move_to_graveyard(koloth)
    eng.recompute_continuous_effects()
    assert not combat.is_goaded(t)


def test_kang_counter_trigger_fires_once_per_declaration_for_goaded_attackers():
    # RULE 508.3a: "one or more" is one trigger per declaration, however many goaded creatures attack.
    eng, p1, p2 = game(KANG, via_steps=True)
    victim = vanilla(eng, "p2", "Victim")
    kang = p1.hand[0]
    _kang_enters(eng, p1, kang, victim)
    kang.summoning_sick = False
    bear = vanilla(eng, "p1", "Mine", 2, 2)
    # p1 attacks with Kang (goaded) and an ungoaded bear; the trigger puts one +1/+1 counter on a creature of p1.
    _attack_and_settle(eng, p1, kang, bear)
    counters = sum(o.counters.get("+1/+1", 0) for o in (kang, bear))
    assert counters == 1


def test_kang_counter_trigger_ignores_ungoaded_attackers():
    eng, p1, p2 = game(KANG, via_steps=True)
    victim = vanilla(eng, "p2", "Victim")
    kang = p1.hand[0]
    _kang_enters(eng, p1, kang, victim)
    bear = vanilla(eng, "p1", "Mine", 2, 2)
    _attack_and_settle(eng, p1, bear)
    assert sum(o.counters.get("+1/+1", 0) for o in (kang, bear)) == 0


def test_koloth_end_step_tokens_enter_goaded_and_pumped():
    # The tokens Koloth's own trigger makes are Tribbles, so the static reaches them as soon as they exist.
    from tests.support.star_trek import advance_to

    eng, p1, p2 = game(KOLOTH, via_steps=True)
    on_battlefield(eng, "p1", KOLOTH)
    advance_to(eng, "end")
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    tokens = [o for o in eng.state.battlefield if o.has_subtype("tribble")]
    assert len(tokens) == 2 * 2  # each of the two players creates two Tribbles
    assert all(combat.goaders(t) == {"p1"} and t.power == 2 for t in tokens)
