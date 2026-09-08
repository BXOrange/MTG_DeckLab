"""Blight Curse batch C5 wave 14 — Puca's Covenant
(hand-authored, `ability_catalogue/entries_017.py`).

DIES trigger over the C3a "creature you control with a counter on it" group
subject, ``limit`` (RULE 603.2 once each turn). The graveyard return targets
a `graveyard_permanent` bound by the new dynamic
``max_mana_value="trigger_dying_counters"`` — resolved in
`targeting.legal_targets` from the DIES event's snapshotted counter total.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


PUCAS_COVENANT = Card(
    id="PUC", name="Puca's Covenant", type_line="Enchantment",
    oracle_text="Whenever a creature you control with a counter on it dies, you may "
                "return another target permanent card with mana value less than or equal "
                "to the number of counters on that creature from your graveyard to your "
                "hand. Do this only once each turn.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _gy_card(pl, cid, mv, is_creature=True):
    c = Card(id=cid, name=cid, type_line="Creature — Ox" if is_creature else "Artifact",
             is_creature=is_creature, converted_mana_cost=mv, mana_cost_string="{%d}" % mv,
             power=2, toughness=2)
    o = GameObject(c, owner_id=pl.id, zone=Zone.GRAVEYARD)
    pl.graveyard.append(o)
    return o


def _setup(eng, counters=3):
    p1 = eng.state.players[0]
    pc = GameObject(PUCAS_COVENANT, owner_id="p1", zone=Zone.BATTLEFIELD)
    pc.controller_id = "p1"
    eng.state.add_to_battlefield(pc)
    bind_from_catalogue(pc)
    dyer = GameObject(Card(id="D", name="Dyer", type_line="Creature — Rat", is_creature=True,
                           power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    dyer.controller_id = "p1"
    dyer.counters["-1/-1"] = counters
    eng.state.add_to_battlefield(dyer)
    eng.begin_turn()
    return p1, pc, dyer


def test_pucas_covenant_authored():
    specs = specs_for(PUCAS_COVENANT)
    assert len(specs) == 1
    t = specs[0].trigger
    assert t["event"] == "DIES" and t["limit"] is True
    assert t["condition"]["has_counter"] is True and t["condition"]["controller"] == "you"
    assert specs[0].effects[0].params["max_mana_value"] == "trigger_dying_counters"


def test_only_cards_within_the_counter_count_are_targetable():
    eng = _engine()
    p1, pc, dyer = _setup(eng, counters=3)
    cheap = _gy_card(p1, "Cheap", 2)
    dear = _gy_card(p1, "Dear", 5)

    eng.rules.destroy(dyer)
    eng.rules.put_triggers_on_stack()

    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "trigger_target"
    ids = {o.get("instance_id") for o in choice["options"] if o.get("instance_id")}
    assert cheap.instance_id in ids and dear.instance_id not in ids

    eng.rules.resolve_trigger_target_choice(str(cheap.instance_id))
    eng.resolve_until_stable()
    assert cheap in p1.hand and cheap not in p1.graveyard


def test_limit_stops_a_second_trigger_the_same_turn():
    eng = _engine()
    p1, pc, dyer = _setup(eng, counters=2)
    _gy_card(p1, "A", 1)

    eng.rules.destroy(dyer)
    eng.rules.put_triggers_on_stack()
    # decline the first (optional) target choice
    if eng.state.pending_choice:
        eng.rules.resolve_trigger_target_choice(None)
    eng.resolve_until_stable()

    dyer2 = GameObject(Card(id="D2", name="Dyer2", type_line="Creature — Rat", is_creature=True,
                            power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    dyer2.controller_id = "p1"
    dyer2.counters["-1/-1"] = 2
    eng.state.add_to_battlefield(dyer2)
    eng.rules.destroy(dyer2)
    eng.rules.put_triggers_on_stack()

    assert eng.state.pending_choice is None and not eng.state.stack


def test_no_trigger_when_the_dying_creature_had_no_counter():
    eng = _engine()
    p1, pc, dyer = _setup(eng, counters=0)
    dyer.counters.clear()
    _gy_card(p1, "A", 1)

    eng.rules.destroy(dyer)
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None and not eng.state.stack
