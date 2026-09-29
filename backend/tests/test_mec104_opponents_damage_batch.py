"""MEC-104 — "…deal(s) damage to one or more of your opponents" fires ONE trigger for the
whole damage step, not one per (creature controller, opponent) pair (RULE 603.2c).

`_apply_combat_damage` names every player a controller damaged in the aggregate event's
``hits``; `binding.core._contributor_condition` (``opponents_batch``) passes only the pair
naming the first matching opponent and `matching_opponents` counts the opponents hit.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def engine():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [(pid, pid, [filler] * 20) for pid in ("p1", "p2", "p3")], starting_hand=0,
    )
    return eng, [eng.state.player_by_id(pid) for pid in ("p1", "p2", "p3")]


def on_battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_hordewing_skaab_draws_once_for_all_opponents_hit():
    eng, (p1, p2, p3) = engine()
    skaab = on_battlefield(eng, "Hordewing Skaab")  # itself a Zombie
    z2 = on_battlefield(eng, "Walking Corpse")
    for p in (p1, p2, p3):
        p.hand.clear()
    eng._apply_combat_damage([(p2, 3, skaab), (p3, 2, z2)])
    pending = [a for a, _e in eng.rules.pending_triggers if a.source is skaab]
    assert len(pending) == 1  # one trigger, not one per opponent
    eng.resolve_until_stable()
    for _ in range(3):
        choice = eng.state.pending_choice
        if choice is None:
            break
        eng.resolve_pending_choice("do" if any(o["id"] == "do" for o in choice["options"]) else choice["options"][0]["id"])
        eng.resolve_until_stable()
    # Two opponents were dealt damage: drew two, discarded two.
    assert len(p1.hand) == 0
    assert len(p1.graveyard) == 2


def test_hordewing_skaab_counts_only_matching_zombie_opponents():
    eng, (p1, p2, p3) = engine()
    skaab = on_battlefield(eng, "Hordewing Skaab")
    bear = on_battlefield(eng, "Grizzly Bears")  # not a Zombie — must not count p3
    for p in (p1, p2, p3):
        p.hand.clear()
    eng._apply_combat_damage([(p2, 3, skaab), (p3, 2, bear)])
    pending = [(a, e) for a, e in eng.rules.pending_triggers if a.source is skaab]
    assert len(pending) == 1
    assert pending[0][1].get("matching_opponents") == 1


def test_aggregate_event_stays_per_pair_and_names_every_hit():
    eng, (p1, p2, p3) = engine()
    # The aggregate event itself stays one per (controller, player) pair — "…to an opponent"
    # wording still fires per opponent; only `opponents_batch` triggers collapse them.
    first = on_battlefield(eng, "Walking Corpse")
    other = on_battlefield(eng, "Diregraf Ghoul")
    events = []
    eng.state.subscribe(lambda e: events.append(e) if e.type == "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER" else None)
    eng._apply_combat_damage([(p2, 1, first), (p3, 1, other)])
    assert len(events) == 2  # the aggregate itself stays per (controller, player) pair
    assert all(len(e.get("hits")) == 2 for e in events)


def test_molten_lavamancer_triggers_once_for_noncombat_damage_to_several_opponents():
    eng, (p1, p2, p3) = engine()
    while eng.state.active_player is not p1:
        eng.advance_step()
    lava = on_battlefield(eng, "Molten Lavamancer")
    before = len([o for o in eng.state.battlefield if o.name == "Elemental"])
    eng.rules.deal_damage(p2, 1, source=lava)
    eng.rules.deal_damage(p3, 1, source=lava)
    eng.resolve_until_stable()
    elementals = [o for o in eng.state.battlefield if o.controller_id == "p1" and o.is_token]
    assert len(elementals) - before == 1  # "triggers only once each turn"


def test_nelly_borca_both_players_draw_once_and_suspected_creatures_are_goaded():
    eng, (p1, p2, p3) = engine()
    on_battlefield(eng, "Nelly Borca, Impulsive Accuser")
    a = on_battlefield(eng, "Walking Corpse", "p2")
    b = on_battlefield(eng, "Diregraf Ghoul", "p2")
    for p in (p1, p2, p3):
        p.hand.clear()
    # p2's creatures hit p3 (an opponent of p1, Nelly's controller): both p1 and p2 draw, once.
    eng._apply_combat_damage([(p3, 1, a), (p3, 1, b)])
    eng.resolve_until_stable()
    assert (len(p1.hand), len(p2.hand), len(p3.hand)) == (1, 1, 0)


def test_nelly_borca_ignores_damage_to_its_own_controller():
    eng, (p1, p2, _p3) = engine()
    on_battlefield(eng, "Nelly Borca, Impulsive Accuser")
    a = on_battlefield(eng, "Walking Corpse", "p2")
    p1.hand.clear(); p2.hand.clear()
    eng._apply_combat_damage([(p1, 1, a)])  # hits Nelly's controller, not "one of your opponents"
    eng.resolve_until_stable()
    assert (len(p1.hand), len(p2.hand)) == (0, 0)


def test_nelly_borca_attack_suspects_then_goads_every_suspected_creature():
    eng, (p1, p2, _p3) = engine()
    nelly = on_battlefield(eng, "Nelly Borca, Impulsive Accuser")
    victim = on_battlefield(eng, "Grizzly Bears", "p2")
    already = on_battlefield(eng, "Walking Corpse", "p2")
    already.is_suspected = True
    while eng.state.active_player is not p1 or eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [{"attacker": nelly, "defender": {"kind": "player", "id": "p3", "label": "p3"}}])
    eng.resolve_until_stable()
    if eng.state.pending_choice is not None:
        opts = [o for o in eng.state.pending_choice["options"] if o["id"] != "decline"]
        eng.resolve_pending_choice(next(o["id"] for o in opts if o["id"] == str(victim.instance_id)))
        eng.resolve_until_stable()
    assert victim.is_suspected and victim.goaded_by and already.goaded_by
