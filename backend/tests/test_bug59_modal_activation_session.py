"""BUG-59: a modal activated ability (RULE 700.2) must be playable through ``GameSession.apply_action``.

``_dispatch_activate_ability`` used to drop ``mode``, so every PAR-237/PAR-255 card (and Umezawa's Jitte) raised
"must choose a mode" through the session, the UI and bots; borrowed copies (Necrotic Ooze) lost their modes.
Every test drives the real session with real oracle text.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.bot_policies.greedy import GreedyBot
from mtg_analyzer.services.game_session import GameActionError, GameSession

CRATERMAKER = (
    "{1}, Sacrifice this creature: Choose one —\n• This creature deals 2 damage to target creature.\n"
    "• Destroy target colorless nonland permanent."
)
KARGAN = (
    "Cowards can't block Warriors.\n{1}: Choose one that hasn't been chosen this turn —\n"
    "• This creature gets +1/+1 until end of turn.\n"
    "• Target creature becomes a Coward until end of turn.\n"
    "• Target Warrior gains trample until end of turn."
)
OOZE = "As long as Necrotic Ooze is on the battlefield, it has all activated abilities of all creature cards in all graveyards."
JITTE_TEXT = (
    "Whenever equipped creature deals combat damage, put two charge counters on Umezawa's Jitte.\n"
    "Remove a charge counter from Umezawa's Jitte: Choose one —\n• Equipped creature gets +2/+2 until end of turn.\n"
    "• Target creature gets -1/-1 until end of turn.\n• You gain 2 life.\nEquip {2}"
)


def _card(name, type_line, oracle, **kw):
    creature = "creature" in type_line.lower()
    if creature:
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
                converted_mana_cost=1, is_creature=creature, **kw)


def _session():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return GameSession(engine, starting_hand=0), engine, engine.state


def _put(state, card, owner="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    else:
        state.player_by_id(owner).graveyard.append(obj)
    return obj


def _act(src, mode=None, index=0, targets=()):
    a = {"type": "activate_ability", "instance_id": src.instance_id, "ability_index": index}
    if mode is not None:
        a["mode"] = mode
    if targets:
        a["targets"] = [{"instance_id": t.instance_id} for t in targets]
    return a


def _pool(state, n):
    for _ in range(n):
        state.player_by_id("p1").mana_pool.add("C", 1)


def test_session_activates_chosen_cratermaker_mode_with_targets():
    session, engine, state = _session()
    maker = _put(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER))
    victim = _put(state, _card("Victim", "Creature — Bear", ""), "p2")
    _pool(state, 1)
    session.apply_action(_act(maker, mode=0, targets=[victim]), "p1")
    engine.resolve_until_stable()
    assert maker not in state.battlefield and victim not in state.battlefield


def test_session_activates_umezawas_jitte_mode():
    session, engine, state = _session()
    jitte = _put(state, _card("Umezawa's Jitte", "Artifact — Equipment", JITTE_TEXT))
    jitte.counters["charge"] = 1
    session.apply_action(_act(jitte, mode=2), "p1")
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 22


def test_modal_activation_without_mode_is_rejected_and_costs_stay_unpaid():
    session, engine, state = _session()
    maker = _put(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER))
    victim = _put(state, _card("Victim", "Creature — Bear", ""), "p2")
    _pool(state, 1)
    with pytest.raises(GameActionError, match="mode"):
        session.apply_action(_act(maker, targets=[victim]), "p1")
    assert maker in state.battlefield and state.player_by_id("p1").mana_pool.total() == 1


def test_non_modal_activation_still_works_without_mode():
    session, engine, state = _session()
    p1 = state.player_by_id("p1")
    pump = _put(state, _card("Firebreather", "Creature — Dwarf", "{R}: ~ gets +1/+0 until end of turn."))
    p1.mana_pool.add("R", 1)
    acts = [a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
            and a["instance_id"] == pump.instance_id]
    assert acts and "mode" not in acts[0]
    session.apply_action(acts[0], "p1")


def test_rewind_restores_a_spent_kargan_mode():
    session, engine, state = _session()
    k = _put(state, _card("Kargan Intimidator", "Creature — Human Warrior", KARGAN))
    _put(state, _card("Victim", "Creature — Bear", ""), "p2")
    _put(state, _card("Ally Warrior", "Creature — Human Warrior", ""))  # a source is never its own target
    engine.recompute_continuous_effects()
    _pool(state, 3)

    def modes():
        return sorted(a["mode"] for a in session.legal_actions("p1")
                      if a.get("type") == "activate_ability" and a["instance_id"] == k.instance_id
                      and not a.get("locked"))
    assert modes() == [0, 1, 2]
    session.apply_action(_act(k, mode=0), "p1")
    assert modes() == [1, 2]
    session.rewind(1)
    k = next(o for o in session.engine.state.battlefield if o.name == "Kargan Intimidator")
    assert sorted(a["mode"] for a in session.legal_actions("p1")
                  if a.get("type") == "activate_ability" and a["instance_id"] == k.instance_id
                  and not a.get("locked")) == [0, 1, 2]


def test_bot_replays_legal_action_entry_verbatim():
    session, engine, state = _session()
    maker = _put(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER))
    _put(state, _card("Victim", "Creature — Bear", ""), "p2")
    engine.recompute_continuous_effects()
    _pool(state, 1)
    entries = [a for a in session.legal_actions("p1") if a.get("type") == "activate_ability"
               and a["instance_id"] == maker.instance_id and not a.get("locked")]
    assert entries and entries[0]["mode"] == 0
    # The real bot policy completes the offer (targets) and echoes `mode` back untouched.
    view = session.view(perspective="p1")
    built = GreedyBot("p1")._fill_in(view, entries[0])
    assert built is not None and built["mode"] == 0
    entry = built
    session.apply_action(entry, "p1")
    engine.resolve_until_stable()
    assert maker not in state.battlefield


def test_necrotic_ooze_borrows_cratermaker_modes():
    session, engine, state = _session()
    ooze = _put(state, _card("Necrotic Ooze", "Creature — Ooze", OOZE))
    _put(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER), "p1", Zone.GRAVEYARD)
    victim = _put(state, _card("Victim", "Creature — Bear", ""), "p2")
    engine.recompute_continuous_effects()
    idx = next(i for i, a in enumerate(ooze.activated_abilities + ooze.granted_activated_abilities) if a.modes)
    _pool(state, 1)
    session.apply_action(_act(ooze, mode=0, index=idx, targets=[victim]), "p1")
    engine.resolve_until_stable()
    assert ooze not in state.battlefield and victim not in state.battlefield


def test_borrowed_exhaust_state_survives_recompute():
    session, engine, state = _session()
    ooze = _put(state, _card("Necrotic Ooze", "Creature — Ooze", OOZE))
    _put(state, _card("Kargan Intimidator", "Creature — Human Warrior", KARGAN), "p1", Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    idx = next(i for i, a in enumerate(ooze.activated_abilities + ooze.granted_activated_abilities) if a.modes)
    _pool(state, 3)
    session.apply_action(_act(ooze, mode=0, index=idx), "p1")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    modes = sorted(a["mode"] for a in session.legal_actions("p1")
                   if a.get("type") == "activate_ability" and a["instance_id"] == ooze.instance_id and "mode" in a)
    assert 0 not in modes
