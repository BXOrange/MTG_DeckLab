"""PAR-32 / MEC-61 — Dungeon Delver's granted RULE 603.3d trigger doubler,
narrowed to dungeon room abilities:

    Commander creatures you own have "Room abilities of dungeons you own
    trigger an additional time."

Hand-authored (`ability_catalogue.entries_016._dungeon_delver`): a bare
``dungeon_room_trigger_doubler`` marker static (the `grant_escape`/
`grant_retrace`/`extra_etb_counter` out-of-band convention), consulted by
`continuous.dungeon_room_trigger_doubler_bonus` from `RulesEngine._collect_
dungeon_room_triggers` — the general `trigger_doubler_bonus` (Roaming
Throne) can't reach a dungeon-room trigger at all, since it's built off a
`Dungeon` in the command zone rather than a battlefield `GameObject`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.dungeon import Dungeon, DungeonRoom
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue


def test_dungeon_delver_registered_with_doubler_marker():
    specs = ability_catalogue.specs_for(
        Card(id="dd", name="Dungeon Delver",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    (grant,) = specs[0].effects
    assert grant.type == "grant_static_ability"
    assert grant.params["affects"] == "commander_creatures_you_own"
    (inner,) = grant.params["static_specs"]
    assert inner["type"] == "dungeon_room_trigger_doubler"


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _bf(st, card, controller="p1", commander=False):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.is_commander = commander
    st.add_to_battlefield(o)
    return o


def _put_player_in_dungeon(eng, player, effect_text="Draw a card."):
    room = DungeonRoom(name="Test Room", effect_text=effect_text, leads_to=[])
    dungeon = Dungeon(name="Test Dungeon", rooms=[room])
    dungeon.controller_id = player.id
    dungeon.owner_id = player.id
    player.dungeon = dungeon
    return dungeon, room


def test_room_ability_fires_twice_with_dungeon_delver():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="dd", name="Dungeon Delver",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(
            Card(id=f"c{i}", name=f"Card{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    hand0 = len(p1.hand)

    _put_player_in_dungeon(eng, p1)
    eng.rules.move_venture_marker(p1, "Test Room")
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert len(p1.hand) == hand0 + 2  # doubled: two "draw a card" firings
    assert p1.dungeon is None  # RULE 309.6 still completes exactly once


def test_room_ability_fires_once_without_dungeon_delver():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(
            Card(id=f"c{i}", name=f"Card{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    hand0 = len(p1.hand)

    _put_player_in_dungeon(eng, p1)
    eng.rules.move_venture_marker(p1, "Test Room")
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert len(p1.hand) == hand0 + 1
