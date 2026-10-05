"""Real gameplay for the Sultai Arisen (Tarkir: Dragonstorm Commander) catalogue entries."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=12):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _place(engine, obj, player, zone):
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    return _place(engine, GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone), player, zone)


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    return _place(engine, GameObject(card, owner_id=player, zone=zone), player, zone)


def _enter(engine, obj, from_cast=False):
    """Announce ``obj`` entering (the fillers are placed without the ENTERS_BATTLEFIELD event)."""
    obj.was_cast = from_cast
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))
    engine.resolve_until_stable()


def _cast(engine, card, pool, targets=None, **kw):
    p1 = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(pool)
    engine.cast_spell(p1, card, targets=targets, target_groups=None, **kw)
    engine.resolve_until_stable()


def _answer(engine, prefer=None, limit=8):
    """Answer pending choices, preferring the option whose id or instance id is in ``prefer`` (else the first)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if not choice:
            return
        options = choice["options"]
        pick = next((o for o in options if prefer and (o.get("instance_id") in prefer or o.get("id") in prefer)),
                    options[0])
        engine.rules.resolve_choice(str(pick["id"]))
        engine.resolve_until_stable()


def test_ob_nixilis_the_fallen_drains_three_and_grows_on_landfall():
    engine = _game()
    p1, p2 = engine.state.players
    ob = _card(engine, "Ob Nixilis, the Fallen")
    land = _filler(engine, "Swamp", "Basic Land — Swamp")
    _enter(engine, land)
    _answer(engine, prefer={"p2"})
    assert p2.life == 17 and ob.plus_one_counters == 3


def test_ob_nixilis_the_fallen_declined_does_nothing():
    engine = _game()
    p1, p2 = engine.state.players
    ob = _card(engine, "Ob Nixilis, the Fallen")
    _enter(engine, _filler(engine, "Swamp", "Basic Land — Swamp"))
    _answer(engine, prefer={"decline"})
    assert p2.life == 20 and ob.plus_one_counters == 0


def test_amphin_mutineer_exiles_a_non_salamander_and_gives_its_controller_a_salamander_warrior():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", "Creature — Elf", player="p2", power=2, toughness=2)
    salamander = _filler(engine, "Newt", "Creature — Salamander", player="p2", power=1, toughness=1)
    mutineer = _card(engine, "Amphin Mutineer")
    _enter(engine, mutineer)
    _answer(engine, prefer={victim.instance_id})
    assert victim.zone == Zone.EXILE and salamander.zone == Zone.BATTLEFIELD
    tokens = [o for o in engine.state.battlefield if o.name == "Salamander Warrior" and o.controller_id == "p2"]
    assert len(tokens) == 1 and (tokens[0].power, tokens[0].toughness) == (4, 3)


def test_amphin_mutineer_can_not_target_a_salamander():
    from mtg_analyzer.game.targeting import legal_targets

    engine = _game()
    _filler(engine, "Victim", "Creature — Elf", player="p2", power=2, toughness=2)
    newt = _filler(engine, "Newt", "Creature — Salamander", player="p2", power=1, toughness=1)
    mutineer = _card(engine, "Amphin Mutineer")
    spec = mutineer.triggered_abilities[0].effects[0].target_specs[0]
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=mutineer)}
    assert newt.instance_id not in offered and offered


def test_lethal_scheme_destroys_and_each_convoking_creature_connives():
    engine = _game()
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", "Creature — Elf", player="p2", power=2, toughness=2)
    helper = _filler(engine, "Helper", "Creature — Elf", power=1, toughness=1)
    helper.summoning_sick = False
    for _ in range(3):
        _filler(engine, "Pad", "Creature — Elf", power=1, toughness=1, player="p2")  # keep the board busy
    spell = _card(engine, "Lethal Scheme", zone=Zone.HAND)
    p1.mana_pool.add_many({"B": 2, "C": 1})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=[victim], target_groups=None, help_pay=True)
    engine.resolve_until_stable()
    assert helper.tapped and spell.convoked_by_ids == [helper.instance_id]
    assert victim.zone == Zone.GRAVEYARD
    _answer(engine)
    assert len(p1.hand) == 0 + 1 - 1  # connive: drew one, discarded one


def test_consuming_aberration_mills_each_opponent_through_their_first_land():
    engine = _game(3, library=0)
    p1, p2, p3 = engine.state.players
    _filler(engine, "Old", "Sorcery", player="p2", zone=Zone.GRAVEYARD)  # keeps its 0-toughness CDA alive
    aberration = _card(engine, "Consuming Aberration")
    # The *last* entry of a library is its top: p2 reveals two nonlands then a land, p3 a land straight away
    # (leaving the nonland beneath it untouched).
    for player, names in ((p2, ["Land2", "Spell2b", "Spell2a"]), (p3, ["Spell3", "Land3"])):
        for name in names:
            _filler(engine, name, "Basic Land — Forest" if name.startswith("Land") else "Sorcery",
                    player=player.id, zone=Zone.LIBRARY)
    spell = _filler(engine, "Cantrip", "Sorcery", mv=1, zone=Zone.HAND)
    p1.mana_pool.add_many({"C": 1})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert sorted(o.name for o in p2.graveyard) == ["Land2", "Old", "Spell2a", "Spell2b"]
    assert [o.name for o in p3.graveyard] == ["Land3"] and p3.library[-1].name == "Spell3"
    continuous.recompute(engine.state)
    assert aberration.power == aberration.toughness == len(p2.graveyard) + len(p3.graveyard) == 5


def test_grapple_with_the_past_mills_three_then_returns_a_creature_or_land():
    engine = _game()
    p1, _ = engine.state.players
    elf = _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    sorcery = _filler(engine, "Burn", "Sorcery", zone=Zone.GRAVEYARD)
    spell = _card(engine, "Grapple with the Past", zone=Zone.HAND)
    library = len(p1.library)
    _cast(engine, spell, {"G": 1, "C": 1})
    assert len(p1.library) == library - 3
    choice = engine.state.pending_choice
    offered = {o.get("instance_id") for o in choice["options"]}
    assert elf.instance_id in offered and sorcery.instance_id not in offered
    _answer(engine, prefer={elf.instance_id})
    assert elf.zone == Zone.HAND  # a milled Forest was also eligible, but the pick was the Elf


def test_junji_dies_mode_one_makes_each_opponent_discard_two_and_lose_two():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    for p in (p2, p3):
        for i in range(3):
            _filler(engine, f"{p.id}c{i}", "Sorcery", player=p.id, zone=Zone.HAND)
    junji = _card(engine, "Junji, the Midnight Sky")
    engine.rules.destroy(junji)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] != "trigger_target"
    _answer(engine, prefer={"0", 0})
    _answer(engine)
    assert (len(p2.hand), len(p3.hand)) == (1, 1) and (p2.life, p3.life, p1.life) == (18, 18, 20)


def test_junji_dies_mode_two_reanimates_a_non_dragon_creature_from_any_graveyard():
    engine = _game()
    p1, p2 = engine.state.players
    dragon = _filler(engine, "Drake", "Creature — Dragon", player="p2", power=4, toughness=4, zone=Zone.GRAVEYARD)
    bear = _filler(engine, "Bear", "Creature — Bear", player="p2", power=2, toughness=2, zone=Zone.GRAVEYARD)
    junji = _card(engine, "Junji, the Midnight Sky")
    engine.rules.destroy(junji)
    engine.resolve_until_stable()
    for _ in range(6):
        choice = engine.state.pending_choice
        if not choice:
            break
        pick = next((o for o in choice["options"] if o.get("instance_id") == bear.instance_id), None)
        if pick is None:
            pick = next((o for o in choice["options"] if "Nicht" in str(o.get("label", "")) or o["id"] == "1"),
                        choice["options"][-1])
        engine.rules.resolve_choice(str(pick["id"]))
        engine.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD and bear.controller_id == "p1" and dragon.zone == Zone.GRAVEYARD
    assert p1.life == 18


def test_welcome_the_dead_counts_cards_put_into_the_graveyard_from_hand_or_library():
    engine = _game()
    p1, _ = engine.state.players
    _filler(engine, "Spare", "Sorcery", zone=Zone.HAND)
    spell = _card(engine, "Welcome the Dead", zone=Zone.HAND)
    # One card milled earlier this turn also counts (from the library).
    engine.rules.mill(p1, 1)
    engine.resolve_until_stable()
    _cast(engine, spell, {"B": 1, "C": 3})
    _answer(engine)
    zombies = [o for o in engine.state.battlefield if o.name == "Zombie Druid"]
    # milled (1) + discarded (1); the cast spell itself came from the hand but goes to the graveyard *after*
    # resolving, so it does not count yet. Mana-payment auto-taps nothing here.
    assert p1.life == 18 and len(zombies) == 2 and all(z.tapped for z in zombies)
    assert (zombies[0].power, zombies[0].toughness) == (2, 2)


def test_meren_gains_experience_when_another_creature_you_control_dies():
    engine = _game()
    p1, _ = engine.state.players
    meren = _card(engine, "Meren of Clan Nel Toth")
    other = _filler(engine, "Other", "Creature — Elf", power=1, toughness=1)
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert p1.counters.get("experience") == 1
    engine.rules.destroy(meren)  # Meren herself dying is not "another creature"
    engine.resolve_until_stable()
    assert p1.counters.get("experience") == 1


def _meren_end_step(mana_value, experience):
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Meren of Clan Nel Toth")
    p1.counters["experience"] = experience
    dead = _filler(engine, "Dead", "Creature — Elf", mv=mana_value, power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.state.active_player_index = 0
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    _answer(engine, prefer={dead.instance_id, str(dead.instance_id)})
    return dead


def test_meren_end_step_returns_to_battlefield_when_mana_value_is_within_the_experience_count():
    assert _meren_end_step(mana_value=2, experience=2).zone == Zone.BATTLEFIELD


def test_meren_end_step_puts_it_into_hand_when_mana_value_exceeds_the_experience_count():
    assert _meren_end_step(mana_value=3, experience=2).zone == Zone.HAND


def test_kishla_skimmer_draws_once_per_turn_when_a_card_leaves_your_graveyard_on_your_turn():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Kishla Skimmer")
    a = _filler(engine, "A", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    b = _filler(engine, "B", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.state.active_player_index = 0
    hand = len(p1.hand)
    engine.rules.return_from_graveyard(a, "hand")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 1 + 1  # the returned card plus the draw
    engine.rules.return_from_graveyard(b, "hand")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 3  # the second exit this turn draws nothing


def test_kishla_skimmer_ignores_exits_during_an_opponents_turn():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Kishla Skimmer")
    a = _filler(engine, "A", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.state.active_player_index = 1
    hand = len(p1.hand)
    engine.rules.return_from_graveyard(a, "hand")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 1


def test_diviner_of_mist_mills_four_then_offers_a_cheap_instant_or_sorcery_for_free():
    engine = _game()
    p1, _ = engine.state.players
    diviner = _card(engine, "Diviner of Mist")
    cheap = _filler(engine, "Cheap", "Sorcery", mv=4, zone=Zone.GRAVEYARD)
    pricey = _filler(engine, "Pricey", "Instant", mv=5, zone=Zone.GRAVEYARD)
    creature = _filler(engine, "Bear", "Creature — Bear", mv=2, power=2, toughness=2, zone=Zone.GRAVEYARD)
    library = len(p1.library)
    engine.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=diviner.instance_id, controller_id="p1",
                                      object=diviner.name))
    engine.resolve_until_stable()
    assert len(p1.library) == library - 4
    choice = engine.state.pending_choice
    offered = {o.get("instance_id") for o in choice["options"]}
    assert offered - {None} == {cheap.instance_id}  # None is the decline option
    _answer(engine, prefer={cheap.instance_id})
    assert cheap.zone == Zone.EXILE and cheap.exile_after_free_cast
    assert cheap.instance_id in engine.state.free_cast_instance_ids
    assert pricey.zone == Zone.GRAVEYARD and creature.zone == Zone.GRAVEYARD


def test_shigeki_discards_itself_to_return_x_nonlegendary_cards_from_the_graveyard():
    engine = _game()
    p1, _ = engine.state.players
    shigeki = _card(engine, "Shigeki, Jukai Visionary", zone=Zone.HAND)
    a = _filler(engine, "A", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    b = _filler(engine, "B", "Sorcery", zone=Zone.GRAVEYARD)
    legend = _filler(engine, "Legend", "Legendary Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    c = _filler(engine, "C", "Instant", zone=Zone.GRAVEYARD)
    from mtg_analyzer.game.targeting import legal_targets

    ability = next(ab for ab in shigeki.activated_abilities if ab.cost.discard_self)
    spec = ability.effects[0].target_spec
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.state.current_step = "main1"
    offered = {t.get("instance_id") for t in legal_targets(engine.state, "p1", spec, source=shigeki)}
    assert legend.instance_id not in offered and {a.instance_id, b.instance_id, c.instance_id} <= offered
    index = shigeki.activated_abilities.index(ability)
    assert engine.can_activate(p1, shigeki, ability, x=2)
    engine.activate_ability(p1, shigeki, index, targets=[a, b], x=2)
    engine.resolve_until_stable()
    assert shigeki.zone == Zone.GRAVEYARD  # discarded as the cost
    assert a.zone == Zone.HAND and b.zone == Zone.HAND and c.zone == Zone.GRAVEYARD and legend.zone == Zone.GRAVEYARD


def test_tasigur_mill_two_then_the_opponent_picks_a_nonland_card_to_return():
    engine = _game(library=12)
    p1, p2 = engine.state.players
    tasigur = _card(engine, "Tasigur, the Golden Fang")
    good = _filler(engine, "Good", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    bad = _filler(engine, "Bad", "Sorcery", zone=Zone.GRAVEYARD)
    land = _filler(engine, "Isle", "Basic Land — Island", zone=Zone.GRAVEYARD)
    p1.mana_pool.add_many({"G": 2, "C": 2})
    engine.state.current_step = "main1"
    library = len(p1.library)
    engine.activate_ability(p1, tasigur, 0)
    engine.resolve_until_stable()
    assert len(p1.library) == library - 2
    chooser_seen = []
    for _ in range(4):
        choice = engine.state.pending_choice
        if not choice:
            break
        chooser_seen.append((choice["kind"], choice.get("player_id")))
        options = choice["options"]
        offered = {o.get("instance_id") for o in options}
        if good.instance_id in offered:
            assert land.instance_id not in offered  # no lands may be chosen
            pick = next(o for o in options if o.get("instance_id") == bad.instance_id)
        else:
            pick = options[0]
        engine.rules.resolve_choice(str(pick["id"]))
        engine.resolve_until_stable()
    assert ("choose_objects", "p2") in chooser_seen  # the opponent made the pick
    assert bad.zone == Zone.HAND and good.zone == Zone.GRAVEYARD and land.zone == Zone.GRAVEYARD


def test_necromantic_selection_destroys_all_then_reanimates_one_destroyed_creature_as_a_black_zombie():
    engine = _game()
    p1, p2 = engine.state.players
    mine = _filler(engine, "Mine", "Creature — Elf", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature — Bear", power=3, toughness=3, player="p2")
    old = _filler(engine, "Old", "Creature — Wurm", power=9, toughness=9, zone=Zone.GRAVEYARD)  # not "this way"
    spell = _card(engine, "Necromantic Selection", zone=Zone.HAND)
    _cast(engine, spell, {"B": 3, "C": 4})
    choice = engine.state.pending_choice
    offered = {o.get("instance_id") for o in choice["options"]}
    assert offered == {mine.instance_id, theirs.instance_id}  # only what was destroyed this way
    _answer(engine, prefer={theirs.instance_id})
    assert theirs.zone == Zone.BATTLEFIELD and theirs.controller_id == "p1"
    assert mine.zone == Zone.GRAVEYARD and old.zone == Zone.GRAVEYARD
    continuous.recompute(engine.state)
    assert continuous.has_subtype(theirs, "zombie") and continuous.has_subtype(theirs, "bear")
    assert "B" in theirs.colors
    assert spell.zone == Zone.EXILE


def test_afterlife_from_the_loam_takes_one_creature_per_player_and_makes_them_zombies():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    a = _filler(engine, "A", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    b = _filler(engine, "B", "Creature — Bear", power=2, toughness=2, player="p2", zone=Zone.GRAVEYARD)
    c = _filler(engine, "C", "Creature — Wurm", power=3, toughness=3, player="p3", zone=Zone.GRAVEYARD)
    extra = _filler(engine, "Extra", "Creature — Bear", power=2, toughness=2, player="p2", zone=Zone.GRAVEYARD)
    spell = _card(engine, "Afterlife from the Loam", zone=Zone.HAND)
    p1.mana_pool.add_many({"B": 3, "C": 5})
    engine.state.current_step = "main1"
    engine.cast_spell(p1, spell, targets=None, target_groups=[[a], [b], [c]])
    engine.resolve_until_stable()
    _answer(engine)
    assert all(o.zone == Zone.BATTLEFIELD and o.controller_id == "p1" for o in (a, b, c))
    assert extra.zone == Zone.GRAVEYARD  # one card per graveyard, not every creature card
    continuous.recompute(engine.state)
    assert all(continuous.has_subtype(o, "zombie") for o in (a, b, c))


def test_steward_of_the_harvest_lends_exiled_lands_mana_abilities_to_your_creatures():
    from mtg_analyzer.game import mana_abilities

    engine = _game()
    p1, _ = engine.state.players
    forest = _card(engine, "Forest", zone=Zone.GRAVEYARD)
    bear_card = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, zone=Zone.GRAVEYARD)
    creature = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    steward = _card(engine, "Steward of the Harvest")
    _enter(engine, steward)
    _answer(engine, prefer={forest.instance_id})
    assert forest.zone == Zone.EXILE and steward.exiled_with_ids == [forest.instance_id]
    assert bear_card.zone == Zone.GRAVEYARD  # only land cards can be exiled with it
    continuous.recompute(engine.state)
    assert {"G": 1} in mana_abilities.mana_options_for(creature)
    assert {"G": 1} in mana_abilities.mana_options_for(steward)  # "creatures you control" includes itself
    other_player = _filler(engine, "Theirs", "Creature — Bear", power=2, toughness=2, player="p2")
    continuous.recompute(engine.state)
    assert {"G": 1} not in mana_abilities.mana_options_for(other_player)


def _conduit_game():
    engine = _game()
    p1, _ = engine.state.players
    conduit = _card(engine, "Conduit of Worlds")
    conduit.summoning_sick = False
    elves = _card(engine, "Llanowar Elves", zone=Zone.GRAVEYARD)
    land = _filler(engine, "Isle", "Basic Land — Island", zone=Zone.GRAVEYARD)
    other = _card(engine, "Llanowar Elves", zone=Zone.HAND)
    engine.state.current_step = "main1"
    return engine, p1, conduit, elves, land, other


def test_conduit_of_worlds_plays_lands_from_the_graveyard_but_casts_no_spells_from_it():
    engine, p1, conduit, elves, land, other = _conduit_game()
    assert engine.can_play_land(p1, land)
    p1.mana_pool.add_many({"G": 2})
    assert not engine.can_cast(p1, elves)  # a lands-only permission (Crucible-shaped) never allows casting


def test_conduit_of_worlds_casts_a_nonland_permanent_card_and_then_locks_further_spells():
    engine, p1, conduit, elves, land, other = _conduit_game()
    index = next(i for i, a in enumerate(conduit.activated_abilities) if a.cost.sorcery_speed_only)
    engine.activate_ability(p1, conduit, index, targets=[elves])
    engine.resolve_until_stable()
    assert conduit.tapped
    p1.mana_pool.add_many({"G": 2})
    assert engine.can_cast(p1, elves) and engine.can_cast(p1, other)
    engine.cast_spell(p1, elves, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert elves.zone == Zone.BATTLEFIELD
    p1.mana_pool.add_many({"G": 2})
    assert not engine.can_cast(p1, other)  # "you can't cast additional spells this turn"


def test_conduit_of_worlds_grants_nothing_once_a_spell_has_been_cast_this_turn():
    engine, p1, conduit, elves, land, other = _conduit_game()
    p1.mana_pool.add_many({"G": 1})
    engine.cast_spell(p1, other, targets=None, target_groups=None)
    engine.resolve_until_stable()
    index = next(i for i, a in enumerate(conduit.activated_abilities) if a.cost.sorcery_speed_only)
    engine.activate_ability(p1, conduit, index, targets=[elves])
    engine.resolve_until_stable()
    p1.mana_pool.add_many({"G": 1})
    assert not engine.can_cast(p1, elves)


def _kotis_game(extra_graveyard_cards):
    engine = _game()
    p1, _ = engine.state.players
    kotis = _card(engine, "Kotis, Sibsig Champion")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, zone=Zone.GRAVEYARD)
    fodder = [_filler(engine, f"Fodder{i}", "Sorcery", zone=Zone.GRAVEYARD) for i in range(extra_graveyard_cards)]
    engine.state.active_player_index = 0
    engine.state.current_step = "main1"
    return engine, p1, kotis, bear, fodder


def test_kotis_casts_a_creature_from_the_graveyard_by_exiling_three_other_cards_and_grows():
    engine, p1, kotis, bear, fodder = _kotis_game(4)
    assert engine.can_cast(p1, bear)
    engine.cast_spell(p1, bear, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD
    exiled = [o for o in fodder if o.zone == Zone.EXILE]
    assert len(exiled) == 3 and len([o for o in fodder if o.zone == Zone.GRAVEYARD]) == 1
    assert kotis.plus_one_counters == 2  # cast from a graveyard
    # "Once during each of your turns": a second creature can't be cast this way the same turn.
    again = _filler(engine, "Again", "Creature — Bear", power=1, toughness=1, zone=Zone.GRAVEYARD)
    for i in range(3):
        _filler(engine, f"More{i}", "Sorcery", zone=Zone.GRAVEYARD)
    assert not engine.can_cast(p1, again)


def test_kotis_needs_three_other_graveyard_cards_and_a_creature_spell():
    engine, p1, kotis, bear, fodder = _kotis_game(2)
    assert not engine.can_cast(p1, bear)  # only two *other* cards
    engine, p1, kotis, bear, fodder = _kotis_game(3)
    spell = fodder[0]
    assert engine.can_cast(p1, bear) and not engine.can_cast(p1, spell)  # a sorcery can't use the permission


def test_kotis_grows_when_a_creature_enters_from_a_graveyard_but_not_from_elsewhere():
    engine, p1, kotis, bear, _ = _kotis_game(0)
    engine.rules.return_from_graveyard(bear, "battlefield")
    engine.resolve_until_stable()
    assert kotis.plus_one_counters == 2
    fresh = _filler(engine, "Fresh", "Creature — Elf", power=1, toughness=1)
    _enter(engine, fresh)
    assert kotis.plus_one_counters == 2  # an ordinary entry adds nothing


def _jarad_in_graveyard():
    engine = _game()
    p1, _ = engine.state.players
    jarad = _card(engine, "Jarad, Golgari Lich Lord", zone=Zone.GRAVEYARD)
    engine.state.current_step = "main1"
    index = next(i for i, a in enumerate(jarad.activated_abilities) if a.cost.sacrifice_also)
    return engine, p1, jarad, index


def test_jarad_returns_from_the_graveyard_by_sacrificing_a_swamp_and_a_forest():
    engine, p1, jarad, index = _jarad_in_graveyard()
    swamp = _filler(engine, "Swamp", "Basic Land — Swamp")
    forest = _filler(engine, "Forest", "Basic Land — Forest")
    ability = jarad.activated_abilities[index]
    assert (ability.cost.sacrifice, ability.cost.sacrifice_also) == ("swamp", "forest")
    assert engine.can_activate(p1, jarad, ability)
    engine.activate_ability(p1, jarad, index)
    engine.resolve_until_stable()
    assert jarad.zone == Zone.HAND
    assert swamp.zone == Zone.GRAVEYARD and forest.zone == Zone.GRAVEYARD


def test_jarad_needs_two_different_permanents_a_swamp_forest_dual_alone_cannot_pay_both_halves():
    engine, p1, jarad, index = _jarad_in_graveyard()
    ability = jarad.activated_abilities[index]
    _filler(engine, "Swamp", "Basic Land — Swamp")
    assert not engine.can_activate(p1, jarad, ability)  # no Forest
    engine, p1, jarad, index = _jarad_in_graveyard()
    ability = jarad.activated_abilities[index]
    _filler(engine, "Dual", "Land — Swamp Forest")
    assert not engine.can_activate(p1, jarad, ability)  # one permanent can't be both
    _filler(engine, "Forest", "Basic Land — Forest")
    assert engine.can_activate(p1, jarad, ability)  # the dual is the Swamp, the basic the Forest


def test_jarad_gets_plus_one_per_creature_card_in_the_graveyard_and_drains_on_sacrifice():
    engine = _game()
    p1, p2 = engine.state.players
    jarad = _card(engine, "Jarad, Golgari Lich Lord")
    jarad.summoning_sick = False
    for i in range(2):
        _filler(engine, f"Dead{i}", "Creature — Elf", power=1, toughness=1, zone=Zone.GRAVEYARD)
    fodder = _filler(engine, "Fodder", "Creature — Elf", power=3, toughness=3)
    continuous.recompute(engine.state)
    assert jarad.power == jarad.card.power + 2
    drain = next(a for a in jarad.activated_abilities if a.cost.sacrifice == "other_creature")
    p1.mana_pool.add_many({"B": 1, "G": 1, "C": 1})
    engine.state.current_step = "main1"
    engine.activate_ability(p1, jarad, jarad.activated_abilities.index(drain), sacrifice_choice=fodder.instance_id)
    engine.resolve_until_stable()
    assert p2.life == 17  # the sacrificed creature's power
