"""PAR-243 (RULE 120.4a): "is dealt excess noncombat damage" trigger heads.

Fall of Cair Andros, Magmatic Galleon and Toralf, God of Fury use their exact Oracle text. Every damage in
here is dealt by a real ability or spell through a real `GameEngine` (the damage sources are activated through
`GameSession.apply_action`), so the `DAMAGE` event's ``excess_damage`` is what the trigger reads.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.game_session import GameSession

FALL = (
    "Whenever a creature an opponent controls is dealt excess noncombat damage, amass Orcs X, where X is that "
    "excess damage. (Put X +1/+1 counters on an Army you control. It's also an Orc. If you don't control an "
    "Army, create a 0/0 black Orc Army creature token first.)\n"
    "{7}{R}: This enchantment deals 7 damage to target creature."
)
GALLEON = (
    "When this Vehicle enters, it deals 5 damage to target creature an opponent controls.\n"
    "Whenever one or more creatures your opponents control are dealt excess noncombat damage, create a Treasure token.\n"
    "Crew 2"
)
TORALF = (
    "Trample\nWhenever a creature or planeswalker an opponent controls is dealt excess noncombat damage, "
    "Toralf deals damage equal to the excess to any target other than that permanent."
)
BLASTER = "{R}: ~ deals 6 damage to target creature."
SWEEPER = "{R}: ~ deals 3 damage to each creature."
POKER = "{R}: ~ deals 3 damage to target creature."
DEATHTOUCHER = "Deathtouch\n{R}: ~ deals 3 damage to target creature."
WALKER_POKER = "{R}: ~ deals 7 damage to any target."


def _card(name, type_line, oracle, power=None, toughness=None, **kw):
    creature = "creature" in type_line.lower()
    if creature:
        power = 2 if power is None else power
        toughness = 2 if toughness is None else toughness
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
                converted_mana_cost=1, is_creature=creature, power=power, toughness=toughness, **kw)


def _session():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return GameSession(engine, starting_hand=0), engine, engine.state


def _put(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fall(state):
    return _put(state, _card("Fall of Cair Andros", "Enchantment", FALL))


def _blast(session, engine, source, target):
    """Activate ``source``'s first ability at ``target`` through the real session and let it resolve."""
    session.apply_action({
        "type": "activate_ability", "instance_id": source.instance_id, "ability_index": 0,
        "targets": [{"instance_id": target.instance_id}],
    }, "p1")
    engine.resolve_until_stable()


def _mana(state, amount):
    for _ in range(amount):
        state.player_by_id("p1").mana_pool.add("R", 1)


def _armies(state):
    return [o for o in state.battlefield if o.controller_id == "p1" and "Army" in o.card.type_line]


def _excess_of(state, target):
    return [e.get("excess_damage") for e in state.event_log
            if e.type == EventType.DAMAGE and e.get("target_id") == target.instance_id]


def test_all_three_cards_are_modeled():
    for name, type_line, text in (("Fall of Cair Andros", "Enchantment", FALL),
                                  ("Magmatic Galleon", "Artifact — Vehicle", GALLEON),
                                  ("Toralf, God of Fury", "Legendary Creature — God", TORALF)):
        assert parse_oracle(_card(name, type_line, text)).coverage == MODELED, name


def test_fall_of_cair_andros_amasses_the_excess_through_its_own_ability():
    session, engine, state = _session()
    fall = _fall(state)
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 4), "p2")
    _mana(state, 8)
    _blast(session, engine, fall, victim)
    assert _excess_of(state, victim) == [3]  # 7 damage, 4 toughness
    (army,) = _armies(state)
    assert army.counters.get("+1/+1") == 3 and "Orc" in army.card.type_line


def test_exact_lethal_damage_has_no_excess_and_no_trigger():
    session, engine, state = _session()
    _fall(state)
    maker = _put(state, _card("Poker", "Creature — Goblin", POKER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 3), "p2")
    _mana(state, 1)
    _blast(session, engine, maker, victim)
    assert _excess_of(state, victim) == [0]
    assert _armies(state) == []


def test_damage_already_marked_counts_toward_lethal():
    session, engine, state = _session()
    _fall(state)
    maker = _put(state, _card("Poker", "Creature — Goblin", POKER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 5), "p2")
    _mana(state, 2)
    _blast(session, engine, maker, victim)  # 3 of 5: no excess
    assert _armies(state) == []
    _blast(session, engine, maker, victim)  # 3 more: 2 left to lethal, 1 excess
    assert _excess_of(state, victim) == [0, 1]
    (army,) = _armies(state)
    assert army.counters.get("+1/+1") == 1


def test_deathtouch_source_makes_anything_above_one_excess():
    session, engine, state = _session()
    _fall(state)
    snake = _put(state, _card("Snake", "Creature — Snake", DEATHTOUCHER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 9), "p2")
    _mana(state, 1)
    _blast(session, engine, snake, victim)
    assert _excess_of(state, victim) == [2]  # 3 damage, lethal is 1 from deathtouch
    (army,) = _armies(state)
    assert army.counters.get("+1/+1") == 2


def test_a_creature_that_survives_still_has_excess():
    session, engine, state = _session()
    _fall(state)
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    victim = _put(state, _card("Victim", "Creature — Golem", "Indestructible", 2, 2), "p2")
    _mana(state, 1)
    _blast(session, engine, maker, victim)
    assert victim in state.battlefield
    (army,) = _armies(state)
    assert army.counters.get("+1/+1") == 4  # 6 damage, 2 toughness


def test_combat_damage_never_fires_the_noncombat_head():
    session, engine, state = _session()
    _fall(state)
    attacker = _put(state, _card("Attacker", "Creature — Ogre", "", 6, 6))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 2), "p2")
    engine.rules.deal_combat_damage([(victim, 6, attacker)])
    engine.resolve_until_stable()
    assert _excess_of(state, victim) == [4]  # the event still knows its excess ...
    assert _armies(state) == []              # ... but the head says noncombat


def test_your_own_creature_does_not_trigger_the_opponent_scoped_head():
    session, engine, state = _session()
    _fall(state)
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    mine = _put(state, _card("Mine", "Creature — Bear", "", 2, 2))
    _mana(state, 1)
    _blast(session, engine, maker, mine)
    assert _excess_of(state, mine) == [4] and _armies(state) == []


def test_galleon_fires_once_for_a_whole_simultaneous_batch():
    session, engine, state = _session()
    _put(state, _card("Magmatic Galleon", "Artifact — Vehicle", GALLEON))
    sweeper = _put(state, _card("Sweeper", "Creature — Elemental", SWEEPER, 9, 9))
    for index in range(3):
        _put(state, _card(f"Victim {index}", "Creature — Bear", "", 1, 1), "p2")
    _mana(state, 1)
    session.apply_action({"type": "activate_ability", "instance_id": sweeper.instance_id, "ability_index": 0}, "p1")
    engine.resolve_until_stable()
    treasures = [o for o in state.battlefield if o.name == "Treasure"]
    assert len(treasures) == 1


def test_galleon_ignores_noncombat_damage_without_excess_or_to_its_own_side():
    session, engine, state = _session()
    _put(state, _card("Magmatic Galleon", "Artifact — Vehicle", GALLEON))
    poker = _put(state, _card("Poker", "Creature — Goblin", POKER))
    mine = _put(state, _card("Mine", "Creature — Bear", "", 1, 1))
    theirs = _put(state, _card("Theirs", "Creature — Bear", "", 2, 3), "p2")
    _mana(state, 2)
    _blast(session, engine, poker, mine)
    _blast(session, engine, poker, theirs)
    assert [o for o in state.battlefield if o.name == "Treasure"] == []


def test_toralf_deals_the_excess_to_another_target_never_the_damaged_permanent():
    session, engine, state = _session()
    toralf = _put(state, _card("Toralf, God of Fury", "Legendary Creature — God", TORALF, 5, 4))
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 4), "p2")
    _mana(state, 1)
    _blast(session, engine, maker, victim)
    pending = state.pending_choice
    assert pending["kind"] == "trigger_target"
    offered = {o.get("instance_id", o.get("id")) for o in pending["options"]}
    assert victim.instance_id not in offered and "p2" in offered
    session.apply_action({"type": "choose", "option_id": "p2"}, "p1")
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == 20 - 2  # 6 damage, 4 toughness: the excess is 2
    assert toralf in state.battlefield


def test_toralf_uses_the_event_excess_even_after_the_permanent_has_left():
    session, engine, state = _session()
    _put(state, _card("Toralf, God of Fury", "Legendary Creature — God", TORALF, 5, 4))
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    victim = _put(state, _card("Victim", "Creature — Bear", "", 2, 4), "p2")
    _mana(state, 1)
    _blast(session, engine, maker, victim)
    assert victim not in state.battlefield  # destroyed by the damage before the trigger resolves
    session.apply_action({"type": "choose", "option_id": "p2"}, "p1")
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == 18


def test_toralf_triggers_on_a_planeswalker_beyond_its_loyalty():
    session, engine, state = _session()
    _put(state, _card("Toralf, God of Fury", "Legendary Creature — God", TORALF, 5, 4))
    maker = _put(state, _card("Walker Poker", "Creature — Goblin", WALKER_POKER))
    walker = _put(state, _card("Test Walker", "Legendary Planeswalker — Test", "", loyalty="3"), "p2")
    walker.counters["loyalty"] = 3
    _mana(state, 1)
    _blast(session, engine, maker, walker)
    assert _excess_of(state, walker) == [4]  # 7 damage, 3 loyalty
    session.apply_action({"type": "choose", "option_id": "p2"}, "p1")
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life == 16


def test_toralf_ping_pong_between_indestructible_creatures_waits_for_a_player_choice_each_time():
    session, engine, state = _session()
    _put(state, _card("Toralf, God of Fury", "Legendary Creature — God", TORALF, 5, 4))
    maker = _put(state, _card("Blaster", "Creature — Goblin", BLASTER))
    left = _put(state, _card("Left", "Creature — Golem", "Indestructible", 1, 1), "p2")
    right = _put(state, _card("Right", "Creature — Golem", "Indestructible", 1, 1), "p2")
    _mana(state, 1)
    _blast(session, engine, maker, left)
    for hit, other in ((left, right), (right, left), (left, right)):
        # Each retrigger is a mandatory ability whose target the controller picks; nothing loops unattended.
        assert state.pending_choice["kind"] == "trigger_target"
        offered = {o.get("instance_id", o.get("id")) for o in state.pending_choice["options"]}
        assert hit.instance_id not in offered and other.instance_id in offered
        session.apply_action({"type": "choose", "option_id": str(other.instance_id)}, "p1")
        engine.resolve_until_stable()
    assert state.pending_choice is not None


def test_an_unbound_amass_x_and_a_players_excess_stay_unmodeled():
    from mtg_analyzer.parser.oracle.gate import UNMODELED

    spell = _card("Test Spell", "Sorcery", "Amass Orcs X.")
    assert parse_oracle(spell).coverage == UNMODELED  # no announced X for AmassEffect to read
    player = _card("Test Enchantment", "Enchantment", "Whenever an opponent is dealt excess damage, draw a card.")
    assert parse_oracle(player).coverage == UNMODELED  # excess damage is a permanent notion (RULE 120.4a)


def test_a_creature_planeswalker_is_measured_by_the_smaller_lethal_amount():
    session, engine, state = _session()
    both = _put(state, _card("Creature Walker", "Legendary Artifact Creature — Test Planeswalker", "", 5, 5,
                             loyalty="3"), "p2")
    both.counters["loyalty"] = 3
    engine.rules.deal_damage(both, 4, source=None)  # ruling: 4 damage to a 5/5 with 3 loyalty is 1 excess
    assert _excess_of(state, both) == [1]
