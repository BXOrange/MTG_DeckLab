"""Real gameplay for the Hope to the last (Final Fantasy Commander-style Lifegain) catalogue entries."""

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


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
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
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def _gy(engine, name, player="p1"):
    return _card(engine, name, player, zone=Zone.GRAVEYARD)


def _gy_filler(engine, type_line, name="GY", power=None, toughness=None, player="p1"):
    return _filler(engine, name=name, type_line=type_line, power=power, toughness=toughness, player=player,
                   zone=Zone.GRAVEYARD)


def _walker(engine, name, loyalty, player="p1"):
    pw = _card(engine, name, player)
    pw.counters["loyalty"] = loyalty
    return pw


def _loyalty(engine, pw, cost, player="p1", **kw):
    index = next(i for i, a in enumerate(pw.activated_abilities) if getattr(getattr(a, "cost", None), "loyalty", None) == cost)
    pw.activated_loyalty_this_turn = False
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.player_by_id(player), pw, index, **kw)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _gy_filler(engine, type_line, name="GY", power=None, toughness=None, player="p1", mv=0):
    return _filler(engine, name=name, type_line=type_line, power=power, toughness=toughness, player=player, mv=mv,
                   zone=Zone.GRAVEYARD)


def _declare(engine, attackers, player="p1"):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p = state.player_by_id(player)
    first = engine.legal_defenders_for(p)[0]
    engine.declare_attackers(p, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def _lib(engine, player, n, name="Lib"):
    """``n`` filler cards on top of ``player``'s library."""
    p = engine.state.player_by_id(player)
    for i in range(n):
        _filler(engine, f"{name}{i}", "Sorcery", player=player, zone=Zone.LIBRARY)
    return p


def test_resplendent_angel_makes_an_angel_at_end_step_after_gaining_five_and_pumps():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    angel = _card(engine, "Resplendent Angel")
    _step(engine, "end")
    assert not [o for o in _named(engine, "Angel")]  # no life gained yet
    engine.rules.gain_life(p1, 5)
    engine.resolve_until_stable()
    _step(engine, "end")
    assert len(_named(engine, "Angel")) == 1  # the 4/4 token
    p1.mana_pool.add_many({"W": 3, "C": 3})
    _activate(engine, angel)
    engine.recompute_continuous_effects()
    assert (angel.power, angel.toughness) == (5, 5) and "lifelink" in combat._obj_keywords(angel)


def test_shabraz_grows_on_draw_and_grants_flying_to_a_human_only():
    engine = _game(library=5)
    p1 = engine.state.player_by_id("p1")
    shabraz = _card(engine, "Shabraz, the Skyshark")
    human = _filler(engine, "Hum", "Creature — Human", power=1, toughness=1)
    goblin = _filler(engine, "Gob", "Creature — Goblin", power=1, toughness=1)
    life = p1.life
    engine.rules.draw(p1, 1)
    engine.resolve_until_stable()
    assert shabraz.counters.get("+1/+1") == 1 and p1.life == life + 1
    p1.mana_pool.add_many({"W": 1})
    _activate(engine, shabraz, 0, targets=[human])  # the draw trigger is bound first; the activation is index 0
    engine.recompute_continuous_effects()
    assert "flying" in combat._obj_keywords(human)
    assert "flying" not in combat._obj_keywords(goblin)


def test_sphinx_of_the_revelation_banks_energy_and_pays_x_to_draw():
    engine = _game(library=6)
    p1 = engine.state.player_by_id("p1")
    sphinx = _card(engine, "Sphinx of the Revelation")
    engine.rules.gain_life(p1, 3)
    engine.resolve_until_stable()
    assert p1.counters.get("energy") == 3
    hand = len(p1.hand)
    p1.mana_pool.add_many({"W": 1, "U": 2})
    _activate(engine, sphinx, x=2)
    assert len(p1.hand) == hand + 2 and p1.counters.get("energy") == 1


def test_starfield_shepherd_fetches_plains_or_a_cheap_creature():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    plains = CardDatabase(DB_PATH).get_card("Plains")
    _filler(engine, "Big", "Creature", mv=5, power=5, toughness=5, zone=Zone.LIBRARY)
    one = _filler(engine, "OneDrop", "Creature", mv=1, power=1, toughness=1, zone=Zone.LIBRARY)
    obj = GameObject(plains, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(obj)
    _put_on_battlefield(engine, "Starfield Shepherd")
    choice = engine.state.pending_choice
    ids = {str(o["id"]) for o in choice["options"]}
    assert ids - {"decline"} == {str(one.instance_id), str(obj.instance_id)}  # the 5-drop is not offered
    engine.resolve_pending_choice(str(one.instance_id))
    assert one in p1.hand


def test_gold_forged_thopteryx_gives_ward_to_legendary_permanents_only():
    engine = _game()
    _card(engine, "Gold-Forged Thopteryx")
    legend = _filler(engine, "Lord", "Legendary Creature — Human", power=1, toughness=1)
    plain = _filler(engine, "Plain", "Creature — Human", power=1, toughness=1)
    engine.recompute_continuous_effects()
    assert legend.granted_ward_cost == "{2}"
    assert not plain.granted_ward_cost


def test_guide_of_souls_gains_life_and_energy_then_pays_for_an_angel_on_an_attacker():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    guide = _card(engine, "Guide of Souls")
    life = p1.life
    bear = _put_on_battlefield(engine, "Grizzly Bears")
    assert p1.life == life + 1 and p1.counters.get("energy") == 1
    guide_self = _filler(engine, "Self", "Creature", power=1, toughness=1)  # another creature entering also counts
    _enter(engine, guide_self)
    assert p1.life == life + 2 and p1.counters.get("energy") == 2

    p1.counters["energy"] = 3
    _declare(engine, [bear])
    _answer(engine)  # pay {E}{E}{E}
    _answer(engine)  # the reflexive trigger's target (the lone attacker)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert p1.counters.get("energy", 0) == 0
    assert bear.counters.get("+1/+1") == 2 and bear.counters.get("flying") == 1
    assert continuous._has_subtype(bear, "angel")


def test_honor_the_fallen_exiles_creature_cards_from_every_graveyard_and_gains_life_per_card():
    engine = _game()
    p1, p2 = engine.state.players
    _gy_filler(engine, "Creature", "C1", power=1, toughness=1)
    _gy_filler(engine, "Creature", "C2", power=1, toughness=1, player="p2")
    spell = _gy_filler(engine, "Sorcery", "S1")
    honor = _card(engine, "Honor the Fallen", zone=Zone.HAND)
    life = p1.life
    _cast(engine, honor, {"W": 1, "C": 1})
    assert p1.life == life + 2
    assert [o.name for o in p1.graveyard if o is not honor] == ["S1"] and not p2.graveyard
    assert {o.name for o in p1.exile} | {o.name for o in p2.exile} >= {"C1", "C2"} and spell in p1.graveyard


def test_hope_estheim_mills_each_opponent_for_the_life_you_gained():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    _card(engine, "Hope Estheim")
    engine.rules.gain_life(p1, 4)
    engine.resolve_until_stable()
    before = len(p2.library)
    _step(engine, "end")
    assert len(p2.library) == before - 4 and len(p1.library) == 10


def test_memory_erosion_mills_the_caster_not_the_controller():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    _card(engine, "Memory Erosion")
    spell = _filler(engine, "Spell", "Sorcery", player="p2", zone=Zone.HAND)
    engine.state.current_step = "main1"
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", instance_id=spell.instance_id, spell="Spell"))
    engine.resolve_until_stable()
    assert len(p2.library) == 8 and len(p1.library) == 10


def test_minas_tirith_draws_only_after_attacking_with_two_creatures():
    engine = _game(library=6)
    p1 = engine.state.player_by_id("p1")
    tirith = _card(engine, "Minas Tirith")
    a, b = (_filler(engine, n, "Creature", power=1, toughness=1) for n in "AB")
    hand = len(p1.hand)

    def activate():
        p1.mana_pool.add_many({"W": 1, "C": 1})
        engine.state.current_step = "main2"
        engine.activate_ability(p1, tirith, 0)
        engine.resolve_until_stable()

    try:
        activate()  # nobody attacked: the activation is refused
    except ValueError:
        pass
    assert len(p1.hand) == hand
    _declare(engine, [a])
    try:
        activate()  # one attacker is not enough
    except ValueError:
        pass
    assert len(p1.hand) == hand
    engine.state.fire_event(GameEvent(EventType.ATTACKS, attacker="B", player_id="p1", instance_id=b.instance_id,
                                      object_types=sorted(b.type_words), declared=True))
    activate()
    assert len(p1.hand) == hand + 1


def test_nykthos_paragon_puts_that_many_counters_on_each_creature_once_per_turn():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    paragon = _card(engine, "Nykthos Paragon")
    other = _filler(engine, "Other", "Creature", power=1, toughness=1)
    engine.rules.gain_life(p1, 3)
    engine.resolve_until_stable()
    _answer(engine, lambda c: "yes" if any(o["id"] == "yes" for o in c["options"]) else None)
    assert paragon.counters.get("+1/+1") == 3 and other.counters.get("+1/+1") == 3
    engine.rules.gain_life(p1, 2)  # a second gain this turn does nothing
    engine.resolve_until_stable()
    _answer(engine)
    assert paragon.counters.get("+1/+1") == 3 and other.counters.get("+1/+1") == 3


def test_well_of_lost_dreams_pays_up_to_the_life_gained_to_draw():
    engine = _game(library=8)
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Well of Lost Dreams")
    p1.mana_pool.add_many({"C": 5})
    hand = len(p1.hand)
    engine.rules.gain_life(p1, 2)
    engine.resolve_until_stable()
    options = [str(o["id"]) for o in engine.state.pending_choice["options"]]
    assert "pay_x:2" in options and "pay_x:3" not in options  # capped by the 2 life gained
    engine.resolve_pending_choice("pay_x:2")
    assert len(p1.hand) == hand + 2 and p1.mana_pool.total() == 3


def test_protection_magic_puts_shield_counters_on_up_to_three_creatures():
    engine = _game()
    magic = _card(engine, "Protection Magic", zone=Zone.HAND)
    crs = [_filler(engine, f"C{i}", "Creature", power=1, toughness=1) for i in range(3)]
    _cast(engine, magic, {"W": 1, "C": 1}, targets=crs[:2])
    assert [c.counters.get("shield") for c in crs] == [1, 1, None]


def test_beacon_of_immortality_doubles_a_life_total_and_shuffles_into_the_library():
    engine = _game(library=3)
    p1, p2 = engine.state.players
    beacon = _card(engine, "Beacon of Immortality", zone=Zone.HAND)
    p2.life = 7
    _cast(engine, beacon, {"W": 1, "C": 5}, targets=[p2])
    assert p2.life == 14
    assert beacon in p1.library and beacon not in p1.graveyard


def test_the_water_crystal_adds_four_to_every_opponent_mill_and_mills_for_your_hand():
    engine = _game(library=20)
    p1, p2 = engine.state.players
    crystal = _card(engine, "The Water Crystal")
    engine.rules.mill(p2, 2)
    assert len(p2.library) == 20 - 6  # 2 + 4
    engine.rules.mill(p1, 2)
    assert len(p1.library) == 18  # your own mills are untouched
    for i in range(3):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "C": 4})
    before = len(p2.library)
    _activate(engine, crystal)
    assert len(p2.library) == before - (len(p1.hand) + 4)  # the mill is itself replaced


def test_riverchurn_monument_mills_two_then_exhaust_mills_a_graveyard_sized_amount_once():
    engine = _game(library=20)
    p1, p2 = engine.state.players
    monument = _card(engine, "Riverchurn Monument")
    p1.mana_pool.add_many({"C": 1})
    _activate(engine, monument, 0, targets=[p2])
    assert len(p2.library) == 18 and len(p2.graveyard) == 2
    p1.mana_pool.add_many({"U": 2, "C": 2})
    monument.tapped = False
    _activate(engine, monument, 1, targets=[p2])
    assert len(p2.library) == 16 and len(p2.graveyard) == 4  # as many cards as its graveyard held (2)
    p1.mana_pool.add_many({"U": 2, "C": 2})
    monument.tapped = False
    try:
        _activate(engine, monument, 1, targets=[p2])
    except ValueError:
        pass
    assert len(p2.library) == 16  # exhaust: only once


def test_angel_of_destiny_shares_combat_damage_as_life_with_the_damaged_player():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Angel of Destiny")
    bear = _filler(engine, "Bear", "Creature", power=3, toughness=3)
    life1, life2 = p1.life, p2.life
    _attack_and_damage(engine, [bear])
    assert p2.life == life2 - 3 + 3 and p1.life == life1 + 3


def test_angel_of_destiny_makes_the_players_it_attacked_lose_at_end_step_with_enough_life():
    engine = _game()
    p1, p2 = engine.state.players
    angel = _card(engine, "Angel of Destiny")
    angel.summoning_sick = False
    p1.life = p1.starting_life + 14
    _declare(engine, [angel])
    _step(engine, "end")
    assert not p2.has_lost  # 14 over the starting total is not enough
    p1.life = p1.starting_life + 15
    _step(engine, "end")
    assert p2.has_lost and not p1.has_lost


def test_angel_of_destiny_does_not_make_a_player_lose_that_it_never_attacked():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Angel of Destiny")
    p1.life = p1.starting_life + 20
    _step(engine, "end")
    assert not p2.has_lost


def test_ajani_gains_life_makes_a_growing_cat_and_exiles_opposing_boards_at_fifteen_over():
    engine = _game()
    p1, p2 = engine.state.players
    ajani = _walker(engine, "Ajani, Strength of the Pride", 5)
    _filler(engine, "Mine", "Creature", power=1, toughness=1)
    life = p1.life
    _loyalty(engine, ajani, 1)
    assert p1.life == life + 2  # one creature + Ajani himself

    _loyalty(engine, ajani, -2)
    cat = _named(engine, "Ajani's Pridemate")[0]
    engine.rules.gain_life(p1, 1)
    engine.resolve_until_stable()
    assert cat.counters.get("+1/+1") == 1

    theirs = _filler(engine, "Theirs", "Creature", power=1, toughness=1, player="p2")
    relic = _filler(engine, "Relic", "Artifact", player="p2")
    land = _filler(engine, "Land", "Land", player="p2")
    _loyalty(engine, ajani, 0)
    assert theirs in engine.state.battlefield and ajani in engine.state.battlefield  # not at 15 over yet
    p1.life = p1.starting_life + 15
    _loyalty(engine, ajani, 0)
    assert theirs not in engine.state.battlefield and relic not in engine.state.battlefield
    assert land in engine.state.battlefield and ajani not in engine.state.battlefield


def test_teferi_untaps_yours_taps_theirs_gains_two_and_the_emblem_untaps_and_draws_on_their_turn():
    engine = _game(library=10)
    p1, p2 = engine.state.players
    teferi = _walker(engine, "Teferi, Who Slows the Sunset", 5)
    relic = _filler(engine, "MyRelic", "Artifact")
    theirs = _filler(engine, "TheirsC", "Creature", power=1, toughness=1, player="p2")
    their_land = _filler(engine, "TheirLand", "Land", player="p2")
    mine = _filler(engine, "MineC", "Creature", power=1, toughness=1)
    relic.tapped = True
    life = p1.life
    _loyalty(engine, teferi, 1, targets=[relic, theirs, their_land], target_groups=[[relic], [theirs], [their_land]])
    assert not relic.tapped and theirs.tapped and their_land.tapped and p1.life == life + 2

    teferi.counters["loyalty"] = 7
    _loyalty(engine, teferi, -7)
    mine.tapped = True
    hand = len(p1.hand)
    engine.state.fire_event(GameEvent(EventType.UNTAP, player_id="p2", controller_id="p2"))
    engine.resolve_until_stable()
    assert not mine.tapped  # untapped during the opponent's untap step
    engine.state.active_player_index = 1  # p2's turn
    _step(engine, "draw", player="p2")
    assert len(p1.hand) == hand + 1


def test_tablet_of_the_guilds_chooses_two_colors_and_gains_life_per_shared_color():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    tablet = _card(engine, "Tablet of the Guilds", zone=Zone.HAND)
    _cast(engine, tablet, {"C": 2})
    for wanted in ("W", "U"):
        choice = engine.state.pending_choice
        assert choice is not None and choice["kind"] == "choose_color"
        assert wanted in {str(o["id"]) for o in choice["options"]}
        engine.resolve_pending_choice(wanted)
    assert tablet.chosen_colors == ["W", "U"]
    assert engine.state.pending_choice is None
    life = p1.life
    gold = _filler(engine, "Gold", "Creature", power=1, toughness=1, zone=Zone.HAND)
    gold.card.color_identity = {"W", "U"}
    green = _filler(engine, "Green", "Creature", power=1, toughness=1, zone=Zone.HAND)
    green.card.color_identity = {"G"}
    for spell in (green, gold):
        engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=spell.instance_id, spell=spell.name))
        engine.resolve_until_stable()
    assert p1.life == life + 2  # green shares none; the W/U spell shares both


def test_restoration_magic_tiers_price_and_grant_protection():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    magic = _card(engine, "Restoration Magic", zone=Zone.HAND)
    target = _filler(engine, "Pal", "Creature", power=1, toughness=1)
    life = p1.life
    # Cura ({1}): one permanent, and 3 life
    _cast(engine, magic, {"W": 1, "C": 1}, targets=[target], mode=1)
    engine.recompute_continuous_effects()
    assert {"hexproof", "indestructible"} <= set(combat._obj_keywords(target)) and p1.life == life + 3
    assert p1.mana_pool.total() == 0  # {W} printed + {1} tier


def test_restoration_magic_curaga_covers_every_permanent_you_control():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    magic = _card(engine, "Restoration Magic", zone=Zone.HAND)
    a = _filler(engine, "A", "Creature", power=1, toughness=1)
    theirs = _filler(engine, "T", "Creature", power=1, toughness=1, player="p2")
    life = p1.life
    _cast(engine, magic, {"W": 2, "C": 3}, mode=2)
    engine.recompute_continuous_effects()
    assert "indestructible" in combat._obj_keywords(a) and "indestructible" not in combat._obj_keywords(theirs)
    assert p1.life == life + 6


def test_minas_tirith_enters_tapped_unless_you_control_a_legendary_creature():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    engine.state.current_step = "main1"
    plain = _card(engine, "Minas Tirith", zone=Zone.HAND)
    engine.play_land(p1, plain)
    assert plain.tapped

    engine2 = _game()
    q = engine2.state.player_by_id("p1")
    _filler(engine2, "Legend", "Legendary Creature — Human", power=1, toughness=1)
    engine2.state.current_step = "main1"
    free = _card(engine2, "Minas Tirith", zone=Zone.HAND)
    engine2.play_land(q, free)
    assert not free.tapped
