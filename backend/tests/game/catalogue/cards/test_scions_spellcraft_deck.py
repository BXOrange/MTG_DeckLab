"""Real gameplay for the Scions & Spellcraft (Final Fantasy Commander) catalogue entries."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
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


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "",
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=None, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _energy(engine, player="p1", amount=None):
    p = engine.state.player_by_id(player)
    if amount is not None:
        engine.rules.add_player_counters(p, amount - p.counters.get("energy", 0), "energy")
    return p.counters.get("energy", 0)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 3, "U": 3, "B": 3, "R": 3, "G": 3, "C": 5}


def _attack_and_damage(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p1 = state.player_by_id("p1")
    first = engine.legal_defenders_for(p1)[0]
    engine.declare_attackers(p1, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def _attack(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    first = engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()


def _cast_noncreature(engine, name="Zap", player="p1"):
    spell = _filler(engine, name, "Instant", mv=1, zone=Zone.HAND, player=player)
    _cast(engine, spell, {"C": 1})
    return spell


def _hero_like(engine, name="Lord", power=2, toughness=2, **kw):
    return _filler(engine, name, "Legendary Creature — Human", power=power, toughness=toughness, is_legendary=True, **kw)


def test_ardbert_pumps_every_legendary_creature_on_white_and_black_casts():
    engine = _game()
    _card(engine, "Ardbert, Warrior of Darkness")
    other = _hero_like(engine, "Other Legend")
    plain = _filler(engine, "Plain", power=1, toughness=1)
    white = _filler(engine, "White Spell", "Instant", mv=1, zone=Zone.HAND, color_identity={"W"})
    _cast(engine, white, {"C": 1})
    assert other.counters.get("+1/+1") == 1 and not plain.counters.get("+1/+1")
    assert combat.has(other, "vigilance") and not combat.has(plain, "vigilance")
    black = _filler(engine, "Black Spell", "Instant", mv=1, zone=Zone.HAND, color_identity={"B"})
    _cast(engine, black, {"C": 1})
    assert other.counters.get("+1/+1") == 2 and combat.has(other, "menace")


def test_champions_from_beyond_makes_heroes_scries_and_pumps_an_eight_creature_attack():
    engine = _game()
    p1, _ = engine.state.players
    champions = _card(engine, "Champions from Beyond", zone=Zone.HAND)
    _cast(engine, champions, RICH, x=2)
    attackers = [_filler(engine, f"A{i}", power=1, toughness=1) for i in range(8)]
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": a, "defender": engine.legal_defenders_for(p1)[0]} for a in attackers])
    engine._fire_player_attacked_events()  # the declaration locks in: ATTACKERS_DECLARED is fired here
    engine.resolve_until_stable()
    _answer(engine, limit=6)
    continuous.recompute(state)
    assert all(a.power == 5 and a.toughness == 5 for a in attackers)


def test_circle_of_power_draws_drains_and_makes_a_pinging_wizard():
    engine = _game()
    p1, p2 = engine.state.players
    old_wizard = _filler(engine, "Old Wizard", "Creature — Wizard", power=1, toughness=1)
    spell = _card(engine, "Circle of Power", zone=Zone.HAND)
    hand = len(p1.hand)
    _cast(engine, spell, RICH)
    continuous.recompute(engine.state)
    wizards = _named(engine, "Wizard")
    assert len(wizards) == 1 and p1.life == 18 and len(p1.hand) == hand - 1 + 2
    assert (wizards[0].power, wizards[0].toughness) == (1, 1)  # 0/1 with the +1/+0 of its own spell
    assert combat.has(wizards[0], "lifelink") and combat.has(old_wizard, "lifelink")
    zap = _filler(engine, "Zap", "Instant", mv=1, zone=Zone.HAND)
    _cast(engine, zap, {"C": 1})
    assert p2.life == 19  # the token's trigger: 1 damage to each opponent


def test_transpose_loots_loses_a_life_and_makes_a_wizard_only_when_cast_from_hand():
    engine = _game(library=6)
    p1, _ = engine.state.players
    _filler(engine, "Discardable", "Sorcery", zone=Zone.HAND)
    spell = _card(engine, "Transpose", zone=Zone.HAND)
    _cast(engine, spell, RICH)
    _answer(engine, limit=3)
    assert p1.life == 19 and len(_named(engine, "Wizard")) == 1
    assert spell.zone == Zone.EXILE  # rebound


def test_dancers_chakrams_job_select_attaches_a_hero_and_other_commanders_get_the_bonus():
    engine = _game()
    chakrams = _put_on_battlefield(engine, "Dancer's Chakrams")
    continuous.recompute(engine.state)
    heroes = _named(engine, "Hero")
    assert len(heroes) == 1 and chakrams.attached_to == heroes[0].instance_id
    assert (heroes[0].power, heroes[0].toughness) == (3, 3) and combat.has(heroes[0], "lifelink")
    commander = _filler(engine, "Commander", "Legendary Creature — Human", power=2, toughness=2)
    commander.is_commander = True
    continuous.recompute(engine.state)
    assert (commander.power, commander.toughness) == (4, 4) and combat.has(commander, "lifelink")
    assert "performer" in continuous.derived_subtype_words(heroes[0])


def test_demolition_field_destroys_a_nonbasic_land_and_both_players_fetch_a_basic():
    engine = _game(library=5)
    p1, p2 = engine.state.players
    field = _card(engine, "Demolition Field")
    theirs = _filler(engine, "Their Nonbasic", "Land", player="p2")
    p1.mana_pool.add_many({"C": 2})
    _activate(engine, field, 0, targets=[theirs])
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(ids[0] if ids else "decline")
    assert theirs.zone == Zone.GRAVEYARD and field.zone == Zone.GRAVEYARD
    mine = [o for o in engine.state.battlefield if o.controller_id == "p1" and o.name == "Forest"]
    theirs_now = [o for o in engine.state.battlefield if o.controller_id == "p2" and o.name == "Forest"]
    assert len(mine) == 1 and len(theirs_now) == 1  # each fetched a basic, theirs first


def test_estinien_varlineau_draws_for_opponents_hit_by_it_or_a_dragon():
    engine = _game(library=8)
    p1, p2 = engine.state.players
    estinien = _card(engine, "Estinien Varlineau")
    estinien.card.power = estinien.card.toughness = 2
    dragon = _filler(engine, "Drake", "Creature — Dragon", power=1, toughness=1)
    _attack_and_damage(engine, [estinien, dragon])
    hand, life = len(p1.hand), p1.life
    _step(engine, "main2", "p1")
    assert len(p1.hand) == hand + 1 and p1.life == life - 1  # one opponent was hit, however many dealers


def test_eye_of_nidhogg_makes_a_goaded_black_dragon_and_returns_to_hand():
    engine = _game()
    p1, p2 = engine.state.players
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, player="p2")
    eye = _card(engine, "Eye of Nidhogg", zone=Zone.HAND)
    _cast(engine, eye, RICH, targets=[bear])
    continuous.recompute(engine.state)
    assert (bear.power, bear.toughness) == (4, 2) and combat.has(bear, "flying") and combat.has(bear, "deathtouch")
    assert "B" in bear.colors and "dragon" in continuous.derived_subtype_words(bear)
    assert "bear" not in continuous.derived_subtype_words(bear)
    assert combat.goaders(bear)
    engine.rules.destroy(bear)
    engine.resolve_until_stable()
    assert eye.zone == Zone.HAND


def test_graha_tia_pays_life_equal_to_the_spells_value_for_a_hero_with_that_many_counters():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "G'raha Tia, Scion Reborn")
    spell = _filler(engine, "Costly", "Sorcery", mv=3, zone=Zone.HAND)
    spell.card.mana_cost = {"generic": 3}
    _cast(engine, spell, {"C": 3})
    engine.resolve_pending_choice("pay")
    hero = _named(engine, "Hero")[0]
    assert p1.life == 17 and hero.counters.get("+1/+1") == 3
    second = _filler(engine, "Another", "Sorcery", mv=2, zone=Zone.HAND)
    second.card.mana_cost = {"generic": 2}
    _cast(engine, second, {"C": 2})
    assert engine.state.pending_choice is None or engine.state.pending_choice.get("kind") != "pay_cost_then"
    assert len(_named(engine, "Hero")) == 1  # only once each turn


def test_hildibrand_buffs_tokens_and_can_be_cast_as_the_adventure_after_dying():
    engine = _game()
    p1, _ = engine.state.players
    hildibrand = _card(engine, "Hildibrand Manderville // Gentleman's Rise")
    token = _filler(engine, "Soldier", power=1, toughness=1)
    token.is_token = True
    continuous.recompute(engine.state)
    assert (token.power, token.toughness) == (2, 2)
    engine.rules.destroy(hildibrand)
    engine.resolve_until_stable()
    _answer(engine, pick=lambda c: "yes" if any(o["id"] == "yes" for o in c["options"]) else None, limit=3)
    assert hildibrand.zone == Zone.GRAVEYARD
    p1.mana_pool.add_many(RICH)
    engine.state.current_step = "main1"
    actions = engine.legal_actions(p1)
    adventure = [a for a in actions if a.get("type") == "cast_spell" and a.get("instance_id") == hildibrand.instance_id]
    assert adventure and all(a.get("face") == "back" for a in adventure)  # only the Adventure half is offered
    engine.cast_spell(p1, hildibrand, targets=None, target_groups=None, face="back")
    engine.resolve_until_stable()
    assert hildibrand.zone == Zone.EXILE and len(_named(engine, "Zombie")) == 1  # on an adventure, token made


def test_krile_returns_a_creature_with_the_same_mana_value_once_each_turn():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Krile Baldesion")
    match = _filler(engine, "Match", "Creature — Elf", mv=1, power=1, toughness=1, zone=Zone.GRAVEYARD)
    _filler(engine, "Other", "Creature — Elf", mv=3, power=1, toughness=1, zone=Zone.GRAVEYARD)
    _cast_noncreature(engine)
    for _ in range(3):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(str(match.instance_id) if str(match.instance_id) in ids else ids[0])
    assert match.zone == Zone.HAND


def test_observed_stasis_removes_from_combat_draws_per_tapped_creature_and_shuts_the_creature_down():
    engine = _game(library=8)
    p1, p2 = engine.state.players
    victim = _filler(engine, "Victim", "Creature — Ogre", power=3, toughness=3, player="p2")
    other = _filler(engine, "Other", power=1, toughness=1, player="p2")
    victim.tapped = other.tapped = True
    victim.attacking = True
    hand = len(p1.hand)
    aura = _card(engine, "Observed Stasis", zone=Zone.HAND)
    _cast(engine, aura, RICH, targets=[victim])
    continuous.recompute(engine.state)
    assert not victim.attacking and len(p1.hand) == hand + 2  # a card per tapped creature (two)
    assert combat.has(victim, "cant_attack") and combat.has(victim, "cant_block")


def test_papalymo_pings_on_noncreature_casts_and_makes_a_hurt_opponent_sacrifice_their_biggest():
    engine = _game()
    p1, p2 = engine.state.players
    papalymo = _card(engine, "Papalymo Totolymo")
    big = _filler(engine, "Big", power=5, toughness=5, player="p2")
    small = _filler(engine, "Small", power=1, toughness=1, player="p2")
    _cast_noncreature(engine)
    assert p2.life == 19 and p1.life == 21
    p1.mana_pool.add_many({"C": 4})
    _activate(engine, papalymo, 0)
    _answer(engine, limit=3)
    assert big.zone == Zone.GRAVEYARD and small.zone == Zone.BATTLEFIELD and papalymo.zone == Zone.GRAVEYARD


def test_papalymo_skips_an_opponent_who_lost_no_life():
    engine = _game()
    p1, p2 = engine.state.players
    papalymo = _card(engine, "Papalymo Totolymo")
    big = _filler(engine, "Big", power=5, toughness=5, player="p2")
    p1.mana_pool.add_many({"C": 4})
    _activate(engine, papalymo, 0)
    _answer(engine, limit=3)
    assert big.zone == Zone.BATTLEFIELD


def test_reapers_scythe_gets_soul_counters_per_player_who_lost_life_and_grows_the_wielder():
    engine = _game()
    p1, p2 = engine.state.players
    scythe = _put_on_battlefield(engine, "Reaper's Scythe")
    hero = _named(engine, "Hero")[0]
    engine.rules.lose_life(p2, 2)
    engine.rules.lose_life(p1, 1)
    _step(engine, "end", "p1")
    continuous.recompute(engine.state)
    assert scythe.counters.get("soul") == 2 and (hero.power, hero.toughness) == (3, 3)
    assert "assassin" in continuous.derived_subtype_words(hero)


def test_good_king_mog_makes_moogles_copies_a_token_on_noncreature_casts_and_pumps_moogles():
    engine = _game()
    p1, _ = engine.state.players
    mog = _card(engine, "Summon: Good King Mog XII")  # entering the battlefield fires chapter I
    engine.resolve_until_stable()
    assert len(_named(engine, "Moogle")) == 2
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, chapter=2, controller_id="p1",
                                      instance_id=mog.instance_id, object=mog.name))
    engine.resolve_until_stable()
    _cast_noncreature(engine)
    for _ in range(3):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(ids[0])
    assert len(_named(engine, "Moogle")) == 3
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, chapter=4, controller_id="p1",
                                      instance_id=mog.instance_id, object=mog.name))
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert all(m.counters.get("+1/+1") == 2 for m in _named(engine, "Moogle"))


def test_thancred_waters_protects_another_legend_while_it_stays_and_itself_on_noncreature_casts():
    engine = _game()
    legend = _hero_like(engine, "Legend")
    thancred = _put_on_battlefield(engine, "Thancred Waters")
    _answer(engine, pick=lambda c: str(legend.instance_id), limit=3)
    continuous.recompute(engine.state)
    assert combat.has(legend, "indestructible") and not combat.has(thancred, "indestructible")
    _cast_noncreature(engine)
    continuous.recompute(engine.state)
    assert combat.has(thancred, "indestructible")
    engine.rules.exile(thancred)
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert not combat.has(legend, "indestructible")


def test_torrential_gearhulk_casts_an_instant_from_your_graveyard_for_free_and_exiles_it():
    engine = _game()
    p1, p2 = engine.state.players
    bolt = _filler(engine, "Bolt", "Instant", mv=1, zone=Zone.GRAVEYARD)
    sorcery = _filler(engine, "Sorcery", "Sorcery", mv=1, zone=Zone.GRAVEYARD)
    theirs = _filler(engine, "Their Instant", "Instant", mv=1, zone=Zone.GRAVEYARD, player="p2")
    _put_on_battlefield(engine, "Torrential Gearhulk")
    for _ in range(3):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(str(bolt.instance_id) if str(bolt.instance_id) in ids else ids[0])
    assert str(sorcery.instance_id) not in map(str, engine.state.free_cast_instance_ids)
    assert theirs.zone == Zone.GRAVEYARD  # only *your* graveyard is a legal target
    assert bolt.zone == Zone.EXILE and bolt.instance_id in engine.state.free_cast_instance_ids
    engine.state.current_step = "main1"
    engine.cast_spell(p1, bolt, targets=None, target_groups=None)  # no mana in the pool: it is free
    engine.resolve_until_stable()
    assert bolt.zone == Zone.EXILE  # "if that spell would be put into your graveyard, exile it instead"


def test_blue_mage_cane_job_select_attaches_a_hero_that_steals_a_spell_to_cast_for_three():
    engine = _game()
    p1, p2 = engine.state.players
    cane = _put_on_battlefield(engine, "Blue Mage's Cane")
    hero = _named(engine, "Hero")[0]
    hero.summoning_sick = False
    continuous.recompute(engine.state)
    assert cane.attached_to == hero.instance_id and (hero.power, hero.toughness) == (1, 3)
    assert "wizard" in continuous.derived_subtype_words(hero)
    bolt = _filler(engine, "Their Bolt", "Instant", mv=2, zone=Zone.GRAVEYARD, player="p2")
    _attack(engine, [hero])
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(str(bolt.instance_id) if str(bolt.instance_id) in ids else ids[0])
    assert bolt.zone == Zone.EXILE
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 3})  # {3} rather than its {2} mana cost
    engine.cast_spell(p1, bolt, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert bolt.zone == Zone.GRAVEYARD  # cast (for exactly the {3}) and resolved


def test_urianger_gains_life_from_exile_plays_and_exiles_face_down_with_a_discount():
    engine = _game()
    p1, _ = engine.state.players
    urianger = _card(engine, "Urianger Augurelt")
    top = _filler(engine, "Top Spell", "Sorcery", mv=3, zone=Zone.LIBRARY)
    top.card.mana_cost = {"generic": 3}
    _activate(engine, urianger, 0)
    _answer(engine, pick=lambda c: "pay" if any(o["id"] == "pay" for o in c["options"]) else "yes", limit=3)
    assert top.zone == Zone.EXILE and top.instance_id in urianger.exiled_with_ids
    urianger.tapped = False
    _activate(engine, urianger, 1)
    assert top.instance_id in engine.state.temp_play_permissions
    p1.mana_pool.add_many({"C": 1})  # 3 − 2
    engine.state.current_step = "main1"
    engine.cast_spell(p1, top, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert top.zone == Zone.GRAVEYARD and p1.life == 22  # cast from exile: +2 life
