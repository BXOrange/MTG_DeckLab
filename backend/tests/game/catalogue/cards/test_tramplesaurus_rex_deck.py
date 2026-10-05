"""Real gameplay for the Tramplesaurus Rex (Foundations Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game():
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(2)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def test_arachnogenesis_makes_a_spider_per_attacker_and_stops_non_spider_combat_damage():
    engine = _game()
    p1, p2 = engine.state.players
    a1 = _filler(engine, "A1", power=2, toughness=2)
    a2 = _filler(engine, "A2", power=3, toughness=3)
    for a in (a1, a2):
        a.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [a1, a2])
    spell = _card(engine, "Arachnogenesis", player="p2", zone=Zone.HAND)
    p2.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(p2, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    spiders = [o for o in engine.state.battlefield if o.card.name == "Spider" and o.controller_id == "p2"]
    assert len(spiders) == 2 and all((s.power, s.toughness) == (1, 2) and combat.has(s, "reach") for s in spiders)
    life = p2.life
    engine.rules.deal_damage(p2, 2, source=a1, combat=True)
    assert p2.life == life  # prevented: a non-Spider
    engine.rules.deal_damage(p1, 1, source=spiders[0], combat=True)
    assert p1.life == 19  # the Spiders still deal combat damage


def test_arachnogenesis_does_not_count_attackers_aimed_elsewhere():
    engine = _game()
    p1, p2 = engine.state.players
    a1 = _filler(engine, "A1", power=2, toughness=2)
    a1.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [a1])
    from mtg_analyzer.game import continuous

    assert continuous.count_selector(engine.state, "p2", "creatures_attacking_you") == 1
    assert continuous.count_selector(engine.state, "p1", "creatures_attacking_you") == 0


def test_overwhelming_stampede_pumps_every_creature_by_the_greatest_power_and_gives_trample():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    big = _filler(engine, "Big", power=5, toughness=5)
    small = _filler(engine, "Small", power=1, toughness=1)
    theirs = _filler(engine, "Theirs", player="p2", power=2, toughness=2)
    spell = _card(engine, "Overwhelming Stampede", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 2, "C": 3})
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (big.power, small.power) == (10, 6) and combat.has(small, "trample")
    assert theirs.power == 2 and not combat.has(theirs, "trample")


def test_rhonas_monument_discounts_green_creatures_and_pumps_on_creature_casts():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    _card(engine, "Rhonas's Monument")
    target = _filler(engine, "Bear", power=2, toughness=2)

    def hand_card(name, ident, color, mv):
        card = Card(id=ident, name=name, type_line="Creature — Bear", is_creature=True, converted_mana_cost=mv,
                    mana_cost_string="{%d}" % mv, power=2, toughness=2, color_identity=color)
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    green, red = hand_card("Green Bear", "G", {"G"}, 3), hand_card("Red Bear", "R", {"R"}, 3)
    assert engine.effective_cast_cost(p1, green).converted_mana_cost == 2
    assert engine.effective_cast_cost(p1, red).converted_mana_cost == 3
    p1.mana_pool.add("C", 2)
    engine.cast_spell(p1, green, targets=None, target_groups=None)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice(str(target.instance_id))
        engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert target.power == 4 and combat.has(target, "trample")


def test_yeva_lets_only_green_creature_spells_be_cast_at_instant_speed():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Yeva, Nature's Herald")
    engine.state.current_step = "declare_attackers"

    def hand(name, kind, color):
        card = Card(id=name, name=name, type_line=kind, is_creature="Creature" in kind,
                    is_instant="Instant" in kind, converted_mana_cost=1, mana_cost_string="{1}",
                    color_identity=color, power=1 if "Creature" in kind else None,
                    toughness=1 if "Creature" in kind else None)
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    green, red, green_artifact = hand("G", "Creature — Bear", {"G"}), hand("R", "Creature — Bear", {"R"}), hand("GA", "Artifact", {"G"})
    p1.mana_pool.add("C", 3)
    assert engine.can_cast(p1, green)
    assert not engine.can_cast(p1, red) and not engine.can_cast(p1, green_artifact)


def test_clifftop_lookout_puts_the_first_land_onto_the_battlefield_tapped_and_bottoms_the_rest():
    engine = _game()
    p1, _ = engine.state.players
    p1.library.clear()
    cards = []
    for i, kind in enumerate(["Land", "Creature", "Creature", "Instant"]):  # index -1 is the top
        card = Card(id=f"L{i}", name=f"Card {i}", type_line=kind, is_land=kind == "Land",
                    is_creature=kind == "Creature", converted_mana_cost=0 if kind == "Land" else 2)
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.LIBRARY)
        cards.append(obj)
    # top → bottom: Instant, Creature, Creature, Land; the land is the 4th card revealed
    engine.state.current_step = "main1"
    lookout = _card(engine, "Clifftop Lookout", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 1, "C": 2})
    engine.cast_spell(p1, lookout, targets=None, target_groups=None)
    engine.resolve_until_stable()
    land = cards[0]
    assert land in engine.state.battlefield and land.tapped
    assert not p1.exile and len(p1.library) == 3


def test_tangleweave_armor_scales_with_the_greatest_commander_mana_value():
    engine = _game()
    p1, _ = engine.state.players
    commander = _filler(engine, "Commander", power=3, toughness=3, mv=5)
    commander.is_commander = True
    armor = _card(engine, "Tangleweave Armor")
    germ = _filler(engine, "Germ", power=0, toughness=0)
    armor.attached_to = germ.instance_id
    engine.recompute_continuous_effects()
    assert (germ.power, germ.toughness) == (5, 5)


def test_scavenger_grounds_sacrifices_itself_to_exile_every_graveyard():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    land = _card(engine, "Scavenger Grounds")
    for owner, name in ((p1, "Mine"), (p2, "Theirs")):
        obj = GameObject(Card(id=name, name=name, type_line="Sorcery", is_sorcery=True), owner_id=owner.id,
                         zone=Zone.GRAVEYARD)
        owner.add_to_zone(obj, Zone.GRAVEYARD)
    p1.mana_pool.add("C", 2)
    idx = next(i for i, a in enumerate(land.activated_abilities) if not getattr(a, "mana_ability", False))
    engine.activate_ability(p1, land, ability_index=idx)
    engine.resolve_until_stable()
    # the sacrificed Desert went to the graveyard as a cost, then was exiled with every other card in it
    assert not p1.graveyard and not p2.graveyard
    assert land in p1.exile and len(p1.exile) == 2 and len(p2.exile) == 1
    assert land not in engine.state.battlefield


def test_witch_s_clinic_gives_a_commander_lifelink():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    clinic = _card(engine, "Witch's Clinic")
    commander = _filler(engine, "Commander", power=3, toughness=3)
    commander.is_commander = True
    other = _filler(engine, "Other", power=2, toughness=2)
    p1.mana_pool.add("C", 2)
    idx = next(i for i, a in enumerate(clinic.activated_abilities) if not getattr(a, "mana_ability", False))
    ability = clinic.activated_abilities[idx]
    engine.activate_ability(p1, clinic, ability_index=idx, targets=[commander])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert combat.has(commander, "lifelink") and not combat.has(other, "lifelink")


@pytest.mark.parametrize("other_dinosaur,stunned", [(False, True), (True, False)])
def test_pugnacious_hammerskull_stuns_itself_only_when_it_is_the_only_dinosaur(other_dinosaur, stunned):
    engine = _game()
    p1, _ = engine.state.players
    skull = _card(engine, "Pugnacious Hammerskull")
    skull.summoning_sick = False
    if other_dinosaur:
        _filler(engine, "Other Dino", "Creature — Dinosaur", power=2, toughness=2)
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [skull])
    engine.resolve_until_stable()
    assert (skull.counters.get("stun", 0) == 1) == stunned


def test_monstrous_onslaught_divides_the_greatest_power_among_the_chosen_creatures():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    _filler(engine, "Big", power=6, toughness=6)
    v1 = _filler(engine, "Victim One", player="p2", power=2, toughness=3)
    v2 = _filler(engine, "Victim Two", player="p2", power=2, toughness=3)
    spell = _card(engine, "Monstrous Onslaught", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 2, "C": 3})
    engine.cast_spell(p1, spell, targets=[v1, v2], target_groups=[[v1, v2]])
    engine.resolve_until_stable()
    assert v1 in p2.graveyard and v2 in p2.graveyard  # 6 damage split 3 + 3 kills both 2/3s


def test_loot_offers_only_creatures_up_to_the_land_count_and_bottoms_the_rest():
    engine = _game()
    p1, _ = engine.state.players
    engine.state.current_step = "main1"
    loot = _card(engine, "Loot, Exuberant Explorer")
    loot.summoning_sick = False
    for i in range(3):
        _filler(engine, f"Land {i}", "Land")
    p1.library.clear()
    cards = {}
    for name, kind, mv in [("Big", "Creature", 6), ("Fits", "Creature", 3), ("Spell", "Instant", 1), ("Also Fits", "Creature", 2)]:
        card = Card(id=name, name=name, type_line=kind, is_creature=kind == "Creature",
                    is_instant=kind == "Instant", converted_mana_cost=mv,
                    power=2 if kind == "Creature" else None, toughness=2 if kind == "Creature" else None)
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.LIBRARY)
        cards[name] = obj
    p1.mana_pool.add("C", 6)
    # a 6-mana cost needs green: pay {G}{G} from the pool
    p1.mana_pool.add("G", 2)
    idx = next(i for i, a in enumerate(loot.activated_abilities) if not getattr(a, "mana_ability", False))
    engine.activate_ability(p1, loot, ability_index=idx)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    offered = {engine.state.find_object(int(o["id"])).name for o in choice["options"] if str(o.get("id", "")).isdigit()}
    assert offered == {"Fits", "Also Fits"}  # lands controlled: 3 (plus the Loot itself is not a land)
    engine.resolve_pending_choice(str(cards["Fits"].instance_id))
    engine.resolve_until_stable()
    assert cards["Fits"] in engine.state.battlefield
    assert all(cards[n] in p1.library for n in ("Big", "Spell", "Also Fits"))


def test_ezuris_predation_makes_a_beast_per_opposing_creature_and_each_fights_a_different_one():
    engine = _game()
    p1, p2 = engine.state.players
    engine.state.current_step = "main1"
    small = _filler(engine, "Small", player="p2", power=2, toughness=2)
    mid = _filler(engine, "Mid", player="p2", power=3, toughness=4)
    huge = _filler(engine, "Huge", player="p2", power=2, toughness=9)
    mine = _filler(engine, "Mine", power=1, toughness=1)
    spell = _card(engine, "Ezuri's Predation", zone=Zone.HAND)
    p1.mana_pool.add_many({"G": 3, "C": 5})
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    engine.resolve_until_stable()
    beasts = [o for o in engine.state.battlefield if o.card.name == "Phyrexian Beast" and o.controller_id == "p1"]
    assert len(beasts) == 3 and all((b.power, b.toughness) == (4, 4) for b in beasts)
    assert small in p2.graveyard and mid in p2.graveyard  # 4 damage kills the 2/2 and the 3/4
    assert huge in engine.state.battlefield and huge.damage_marked == 4  # a different token fought each one
    assert mine in engine.state.battlefield  # only opposing creatures are involved
    assert sum(b.damage_marked for b in beasts) == 2 + 3 + 2
