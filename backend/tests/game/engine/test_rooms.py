"""Rooms (RULE 709.5, MEC-111): door designations, door-scoped abilities, casting either half."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import rooms
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=12):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, *, face="front", targets=None):
    player = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    player.mana_pool.add_many(pool)
    engine.cast_spell(player, card, targets=targets, target_groups=None, face=face)
    engine.resolve_until_stable()


def _tokens(engine, name):
    return [o for o in engine.state.battlefield if o.is_token and o.name == name]


GRAND_ENTRYWAY = "Grand Entryway // Elegant Rotunda"  # {1}{W} creates a Glimmer / {2}{W} two +1/+1 counters


def test_casting_the_left_half_unlocks_only_the_left_door_and_runs_its_trigger():
    engine = _game()
    room = _card(engine, GRAND_ENTRYWAY, zone=Zone.HAND)
    _cast(engine, room, {"W": 1, "C": 1})
    assert room.zone == Zone.BATTLEFIELD
    assert room.unlocked_doors == {rooms.LEFT}
    assert len(_tokens(engine, "Glimmer")) == 1
    assert all(getattr(a, "door", None) == rooms.LEFT for a in room.triggered_abilities)
    assert room.triggered_abilities  # the left door's own trigger is bound


def test_casting_the_right_half_unlocks_only_the_right_door():
    engine = _game()
    room = _card(engine, GRAND_ENTRYWAY, zone=Zone.HAND)
    _cast(engine, room, {"W": 1, "C": 2}, face="back")
    assert room.zone == Zone.BATTLEFIELD
    assert room.unlocked_doors == {rooms.RIGHT}
    assert room.card.name == GRAND_ENTRYWAY  # the whole Room again, not the half that was cast
    assert not _tokens(engine, "Glimmer")  # the left door's text is locked
    assert all(getattr(a, "door", None) == rooms.RIGHT for a in room.triggered_abilities)


def test_a_room_that_was_not_cast_enters_with_both_doors_locked():
    engine = _game()
    room = _card(engine, GRAND_ENTRYWAY, zone=Zone.GRAVEYARD)
    engine.state.player_by_id("p1").graveyard.remove(room)
    engine.state.add_to_battlefield(room)
    engine.resolve_until_stable()
    assert room.unlocked_doors == set()
    assert not room.triggered_abilities and not _tokens(engine, "Glimmer")
    assert rooms.locked_doors(room) == [rooms.LEFT, rooms.RIGHT]


def _on_board(engine, name, *, cast_face="front", pool=None):
    room = _card(engine, name, zone=Zone.HAND)
    _cast(engine, room, pool or {"W": 1, "C": 2}, face=cast_face)
    return room


def test_unlocking_the_other_door_is_a_special_action_that_binds_its_abilities_and_fires_the_events():
    engine = _game()
    room = _on_board(engine, GRAND_ENTRYWAY, pool={"W": 1, "C": 1})
    seen = []
    engine.state.subscribe(lambda e: seen.append(e.type) if e.type in ("DOOR_UNLOCKED", "ROOM_FULLY_UNLOCKED") else None)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 2})

    actions = [a for a in engine.legal_actions(p1) if a["type"] == "unlock_door"]
    assert [(a["door"], a["cost_label"]) for a in actions] == [(rooms.RIGHT, "{2}{W}")]

    engine.unlock_door(p1, room, rooms.RIGHT)
    engine.resolve_until_stable()
    assert room.unlocked_doors == {rooms.LEFT, rooms.RIGHT}
    assert seen == ["DOOR_UNLOCKED", "ROOM_FULLY_UNLOCKED"]
    assert not [a for a in engine.legal_actions(p1) if a["type"] == "unlock_door"]  # nothing left to unlock
    assert {a.door for a in room.triggered_abilities} == {rooms.LEFT, rooms.RIGHT}


def test_a_locked_door_cannot_be_unlocked_without_the_mana_or_at_the_wrong_time():
    engine = _game()
    room = _on_board(engine, GRAND_ENTRYWAY, pool={"W": 1, "C": 1})
    p1, p2 = engine.state.players
    try:
        engine.unlock_door(p1, room, rooms.RIGHT)  # no mana in the pool, no lands to tap
    except ValueError:
        pass
    else:
        raise AssertionError("an unaffordable unlock must be refused")
    p1.mana_pool.add_many({"W": 1, "C": 2})
    engine.state.current_step = "combat_damage"  # RULE 709.5e: only during a main phase
    assert not engine.can_unlock_door(p1, room, rooms.RIGHT)
    engine.state.current_step = "main1"
    assert not engine.can_unlock_door(p2, room, rooms.RIGHT)  # not its controller
    assert engine.can_unlock_door(p1, room, rooms.RIGHT)
    assert not engine.can_unlock_door(p1, room, rooms.LEFT)  # already unlocked


def _put_room(engine, name, doors):
    """A Room already on the battlefield with ``doors`` unlocked (entering without being cast gives neither)."""
    room = _card(engine, name, zone=Zone.BATTLEFIELD)
    for door in doors:
        rooms.unlock(engine.state, room, door)
    engine.resolve_until_stable()
    return room


def test_marina_vendrell_chooses_between_locking_and_unlocking_a_door():
    engine = _game()
    room = _put_room(engine, GRAND_ENTRYWAY, [rooms.LEFT])
    marina = _card(engine, "Marina Vendrell")
    p1 = engine.state.player_by_id("p1")
    engine.state.current_step = "main1"
    index = next(i for i, a in enumerate(marina.activated_abilities) if any(
        getattr(e, "lock_or_unlock", False) for e in a.effects))
    engine.activate_ability(p1, marina, index, targets=[room])
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "door_choice"
    labels = {o["id"]: o["label"] for o in choice["options"]}
    assert set(labels) == {f"unlock:{room.instance_id}:right", f"lock:{room.instance_id}:left"}
    engine.resolve_pending_choice(f"lock:{room.instance_id}:left")
    assert room.unlocked_doors == set() and not room.triggered_abilities  # the locked half's rules text is gone


def test_ghostly_keybearer_unlocks_the_only_locked_door_without_asking():
    engine = _game()
    room = _put_room(engine, GRAND_ENTRYWAY, [rooms.RIGHT])
    keybearer = _card(engine, "Ghostly Keybearer")
    engine.state.current_step = "combat_damage"
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=keybearer, combat=True)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"  # "up to one target Room you control": pick it
    assert [o["instance_id"] for o in choice["options"] if "instance_id" in o] == [room.instance_id]
    engine.resolve_pending_choice(str(room.instance_id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert room.unlocked_doors == {rooms.LEFT, rooms.RIGHT}


def _filler(engine, name, type_line="Creature — Bear", power=2, toughness=2, player="p1"):
    from mtg_analyzer.models.cards.card import Card

    creature = "Creature" in type_line
    card = Card(id=name, name=name, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None, mana_cost_string="")
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    return obj


def test_fully_unlocking_a_room_fires_eerie_triggers_only_when_the_second_door_opens():
    engine = _game()
    victim = _filler(engine, "Victim", player="p2")
    _card(engine, "Fear of Sleep Paralysis")
    room = _put_room(engine, GRAND_ENTRYWAY, [rooms.LEFT])
    # Entering the first door is not "fully unlocking"; Fear of Sleep has not triggered (no stun yet).
    assert engine.state.pending_choice is None and not victim.counters.get("stun")
    rooms.unlock(engine.state, room, rooms.RIGHT)
    engine.resolve_until_stable()
    for _ in range(6):  # Elegant Rotunda's own "up to two creatures" and Fear's "up to one" targets
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice["options"]]
        engine.resolve_pending_choice(str(victim.instance_id) if str(victim.instance_id) in ids else "stop" if "stop" in ids else ids[0])
        engine.resolve_until_stable()
    assert victim.tapped and victim.counters.get("stun") == 1


def test_rampaging_soulrager_counts_unlocked_doors_among_your_rooms():
    engine = _game()
    soulrager = _filler(engine, "Placeholder", power=3, toughness=3)
    soulrager = _card(engine, "Rampaging Soulrager")
    base = soulrager.power
    room = _put_room(engine, GRAND_ENTRYWAY, [rooms.LEFT])
    engine.recompute_continuous_effects()
    assert soulrager.power == base  # one unlocked door is not enough
    rooms.unlock(engine.state, room, rooms.RIGHT)
    engine.recompute_continuous_effects()
    assert soulrager.power == base + 3
    rooms.lock(engine.state, room, rooms.LEFT)
    engine.recompute_continuous_effects()
    assert soulrager.power == base


def test_torture_pit_adds_two_to_noncombat_damage_to_an_opponent_only_while_its_door_is_unlocked():
    engine = _game()
    p1, p2 = engine.state.players
    room = _put_room(engine, "Spiked Corridor // Torture Pit", [])
    src = _filler(engine, "Pinger", power=1, toughness=1)
    engine.rules.deal_damage(p2, 1, source=src)
    assert p2.life == 19  # both doors locked
    rooms.unlock(engine.state, room, rooms.RIGHT)
    engine.rules.deal_damage(p2, 1, source=src)
    assert p2.life == 19 - 3
    engine.rules.deal_damage(p2, 1, source=src, combat=True)
    assert p2.life == 19 - 3 - 1  # combat damage is untouched
    own = _filler(engine, "Their Bear", player="p2")
    engine.rules.deal_damage(own, 1, source=src)
    assert own.damage_marked == 1  # …and so is damage to a creature


def test_access_maze_lets_you_cast_one_spell_from_hand_for_life_each_turn():
    engine = _game()
    p1, _ = engine.state.players
    _put_room(engine, "Cramped Vents // Access Maze", [rooms.RIGHT])
    from mtg_analyzer.models.cards.card import Card
    spell = GameObject(Card(id="s", name="Costly One", type_line="Sorcery", is_sorcery=True,
                            converted_mana_cost=4, mana_cost_string="{4}"), owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    p1.add_to_zone(spell, Zone.HAND)
    engine.state.current_step = "main1"
    actions = [a for a in engine.legal_actions(p1) if a.get("instance_id") == spell.instance_id]
    assert any(a.get("alt_cost") for a in actions)


def test_staff_room_turns_the_creature_face_up_or_adds_a_counter():
    engine = _game()
    p2 = engine.state.player_by_id("p2")
    _put_room(engine, "Experimental Lab // Staff Room", [rooms.RIGHT])
    attacker = _filler(engine, "Attacker", power=2, toughness=2)
    engine.state.current_step = "combat_damage"
    engine.rules.deal_damage(p2, 2, source=attacker, combat=True)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_mode"
    assert "Whenever a creature you control deals combat damage" in choice["prompt"]  # the right door's own text
    assert "manifest dread" not in choice["prompt"]
    engine.resolve_pending_choice("1")  # "put a +1/+1 counter on it"
    engine.resolve_until_stable()
    assert attacker.counters.get("+1/+1") == 1


def test_misty_salon_makes_a_spirit_as_big_as_your_unlocked_doors():
    engine = _game()
    first = _put_room(engine, GRAND_ENTRYWAY, [rooms.LEFT, rooms.RIGHT])
    salon = _put_room(engine, "Smoky Lounge // Misty Salon", [rooms.LEFT])
    rooms.unlock(engine.state, salon, rooms.RIGHT)
    engine.resolve_until_stable()
    spirits = _tokens(engine, "Spirit")
    assert len(spirits) == 1 and spirits[0].power == spirits[0].toughness == 4  # 2 + 2 unlocked doors
    assert "Flying" in spirits[0].to_dict()["keywords"] or "flying" in {k.lower() for k in spirits[0].to_dict()["keywords"]}


def test_smoky_lounge_mana_pays_for_room_spells_and_unlocking_but_nothing_else():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    room = _put_room(engine, "Smoky Lounge // Misty Salon", [rooms.LEFT])
    engine.state.current_step = "main1"
    # The first-main-phase trigger: simulate its effect directly.
    from mtg_analyzer.game.effects.core import EffectRegistry
    effect = EffectRegistry.create("add_mana", {
        "colors": ["R", "R"],
        "restriction": {"kind": "type_spell", "types": ["room"], "allow_ability": False, "allow_unlock": True},
    })
    effect.source = room
    effect.apply(engine.rules.context, None)
    assert p1.mana_pool.restricted  # RR sits in a restricted lot, not the open pool
    assert not engine.can_unlock_door(p1, room, rooms.RIGHT)  # Misty Salon costs {3}{U}: RR alone cannot pay it
    p1.mana_pool.add_many({"U": 1, "C": 1})
    assert engine.can_unlock_door(p1, room, rooms.RIGHT)  # …but with the two restricted mana it can
    engine.unlock_door(p1, room, rooms.RIGHT)
    assert not p1.mana_pool.restricted or sum(sum(l["amounts"].values()) for l in p1.mana_pool.restricted) == 0


def test_ghostly_dancers_can_unlock_a_door_when_it_enters_and_makes_spirits_on_full_unlocks():
    engine = _game()
    room = _put_room(engine, GRAND_ENTRYWAY, [rooms.LEFT])
    dancers = _card(engine, "Ghostly Dancers", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    _cast(engine, dancers, {"W": 3, "C": 4})
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice["options"]]
        engine.resolve_pending_choice("1" if choice["kind"] == "trigger_mode" and "1" in ids else ids[0])
        engine.resolve_until_stable()
    assert room.unlocked_doors == {rooms.LEFT, rooms.RIGHT}  # "unlock a locked door of a Room you control"
    assert len(_tokens(engine, "Spirit")) >= 1  # the full unlock paid off Ghostly Dancers' own Eerie trigger


def test_room_characteristics_follow_doors_and_restore_outside_the_battlefield():
    from mtg_analyzer.game.combat import matches_object_filter
    from mtg_analyzer.game.continuous import count_selector
    from mtg_analyzer.game.effects.core import _characteristic_of_subject

    engine = _game()
    room = _card(engine, GRAND_ENTRYWAY)
    assert room.names == () and room.name == ""
    assert room.mana_value == 0 and room.mana_cost_string == ""
    assert room.colors == set() and room.effective_oracle_text == ""
    assert matches_object_filter(room, {"max_mana_value": 0})
    selector = {"zone": "battlefield", "of": "you", "filter": {"subtype": "room"}, "distinct": "name"}
    assert count_selector(engine.state, "p1", selector) == 0
    rooms.unlock(engine.state, room, rooms.RIGHT)
    assert room.names == ("Elegant Rotunda",) and room.name == "Elegant Rotunda"
    assert room.mana_value == 3 and room.mana_cost_string == "{2}{W}"
    assert room.colors == {"W"}
    assert "Glimmer" not in room.effective_oracle_text
    assert not matches_object_filter(room, {"max_mana_value": 2})
    assert _characteristic_of_subject(engine.rules.context, room, "self_mana_value") == 3
    rooms.unlock(engine.state, room, rooms.LEFT)
    assert set(room.names) == {"Grand Entryway", "Elegant Rotunda"}
    assert room.mana_value == 5
    assert count_selector(engine.state, "p1", selector) == 2
    rooms.lock(engine.state, room, rooms.RIGHT)
    assert room.mana_value == 2 and room.names == ("Grand Entryway",)
    engine.rules.put_into_graveyard(room)
    assert room.mana_value == 5 and set(room.names) == {"Grand Entryway", "Elegant Rotunda"}
    engine.rules.return_from_graveyard(room)
    assert room.mana_value == 0 and room.names == ()
    assert room.card.name == GRAND_ENTRYWAY  # printed identity remains available for Replay/art


def test_room_spells_have_only_the_cast_halfs_name_and_mana_value():
    for face, name, value in (("front", "Grand Entryway", 2), ("back", "Elegant Rotunda", 3)):
        engine = _game()
        room = _card(engine, GRAND_ENTRYWAY, zone=Zone.HAND)
        assert room.mana_value == 5
        player = engine.state.player_by_id("p1")
        engine.state.current_step = "main1"
        player.mana_pool.add_many({"W": 1, "C": 2})
        engine.cast_spell(player, room, face=face)
        assert room.names == (name,) and room.name == name
        assert room.mana_value == value


def test_a_copied_right_half_spell_enters_with_both_halves_but_neither_unlocked():
    engine = _game()
    room = _card(engine, GRAND_ENTRYWAY, zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    engine.state.current_step = "main1"
    player.mana_pool.add_many({"W": 1, "C": 2})
    engine.cast_spell(player, room, face="back")
    copied = engine.rules.copy_spell(engine.state.stack[-1], "p1")[0].obj
    assert copied.name == "Elegant Rotunda" and copied.mana_value == 3
    engine.rules.resolve_top_of_stack()
    assert copied.zone == Zone.BATTLEFIELD and rooms.has_doors(copied.card)
    assert copied.unlocked_doors == set() and copied.mana_value == 0
    assert not copied.triggered_abilities
    assert rooms.locked_doors(copied) == [rooms.LEFT, rooms.RIGHT]


def test_room_unlock_requires_priority_in_interactive_games():
    engine = _game()
    room = _put_room(engine, GRAND_ENTRYWAY, [])
    player = engine.state.player_by_id("p1")
    player.mana_pool.add_many({"W": 1, "C": 1})
    engine.state.current_step = "main1"
    engine.interactive_priority = True
    engine.give_priority(engine.state.player_by_id("p2"))
    assert not engine.can_unlock_door(player, room, rooms.LEFT)
    assert not engine.unlock_door_actions(player, room)
    engine.give_priority(player)
    assert engine.can_unlock_door(player, room, rooms.LEFT)


def test_unlock_auto_tap_combines_room_restricted_mana_with_an_untapped_land():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine = _game()
    player = engine.state.player_by_id("p1")
    room = _put_room(engine, "Smoky Lounge // Misty Salon", [rooms.LEFT])
    island = _card(engine, "Island")
    engine.state.current_step = "main1"
    effect = EffectRegistry.create("add_mana", {
        "colors": ["R", "R"],
        "restriction": {"kind": "type_spell", "types": ["room"], "allow_ability": False, "allow_unlock": True},
    })
    effect.source = room
    effect.apply(engine.rules.context, None)
    player.mana_pool.add_many({"C": 1})
    actions = engine.unlock_door_actions(player, room)
    assert len(actions) == 1 and actions[0]["auto_tap"]
    engine.unlock_door(player, room, rooms.RIGHT)
    assert island.tapped and room.unlocked_doors == {rooms.LEFT, rooms.RIGHT}


def test_room_spell_colours_exclude_the_uncast_halfs_mana_symbols():
    engine = _game()
    room = _card(engine, "Smoky Lounge // Misty Salon", zone=Zone.HAND)
    assert room.mana_value == 7
    assert room.mana_cost_string == "{2}{R}{3}{U}"
    player = engine.state.player_by_id("p1")
    engine.state.current_step = "main1"
    player.mana_pool.add_many({"R": 1, "C": 2})
    engine.cast_spell(player, room)
    assert room.colors == {"R"} and room.mana_value == 3
    engine.resolve_until_stable()
    assert room.colors == {"R"}
    rooms.unlock(engine.state, room, rooms.RIGHT)
    assert room.colors == {"R", "U"} and room.mana_value == 7
