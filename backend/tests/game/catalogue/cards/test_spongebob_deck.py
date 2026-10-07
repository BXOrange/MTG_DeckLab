"""Hand-authored cards of the saved "SpongeBob and the legendary Burger" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1


def _helga_with(spell_mv):
    engine, p1 = _game()
    helga_card = CardDatabase(DB_PATH).get_card("Helga, Skittish Seer")
    helga = GameObject(helga_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    helga.controller_id = "p1"
    bind_from_catalogue(helga)
    engine.state.add_to_battlefield(helga)
    spell = GameObject(
        Card(id="Big", name="Big Beast", type_line="Creature — Beast", is_creature=True, power=3, toughness=3,
             mana_cost_string="{" + str(spell_mv) + "}", converted_mana_cost=spell_mv),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"C": spell_mv})
    life_before, hand_before = p1.life, len(p1.hand)
    engine.cast_spell(p1, spell)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine, p1, helga, life_before, hand_before


def test_helga_triggers_only_for_creature_spells_with_mana_value_four_or_more():
    engine, p1, helga, life_before, hand_before = _helga_with(4)
    assert p1.life == life_before + 1
    assert len(p1.hand) == hand_before - 1 + 1  # the spell leaves the hand, one card is drawn
    assert helga.counters.get("+1/+1", 0) == 1

    engine, p1, helga, life_before, hand_before = _helga_with(3)
    assert p1.life == life_before and helga.counters.get("+1/+1", 0) == 0
    assert len(p1.hand) == hand_before - 1  # mana value 3: nothing


def test_captain_sisay_fetches_a_legendary_card_to_hand():
    engine, p1 = _game()
    sisay_card = CardDatabase(DB_PATH).get_card("Captain Sisay")
    sisay = GameObject(sisay_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    sisay.controller_id = "p1"
    bind_from_catalogue(sisay)
    sisay.summoning_sick = False
    engine.state.add_to_battlefield(sisay)
    legend = GameObject(
        Card(id="Legend", name="A Legend", type_line="Legendary Creature — Elf", is_creature=True, is_legendary=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.LIBRARY,
    )
    plain = GameObject(Card(id="Plain", name="Plain Elf", type_line="Creature — Elf", is_creature=True, power=1, toughness=1),
                       owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([plain, legend])

    index = next(i for i, a in enumerate(sisay.activated_abilities) if getattr(a, "cost", None) is not None)
    engine.activate_ability(p1, sisay, index)
    engine.resolve_until_stable()
    for _ in range(4):
        if not engine.state.pending_choice:
            break
        choice = engine.state.pending_choice
        wanted = [o for o in choice["options"] if o.get("instance_id") == legend.instance_id]
        offered_ids = {o.get("instance_id") for o in choice["options"]}
        assert plain.instance_id not in offered_ids  # only legendary cards are offered
        engine.resolve_pending_choice((wanted or choice["options"])[0]["id"])
        engine.resolve_until_stable()

    assert legend in p1.hand and plain not in p1.hand and sisay.tapped


def _venser_game(loyalty=3):
    card = CardDatabase(DB_PATH).get_card("Venser, the Sojourner")
    engine, p1 = _game()
    venser = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    venser.controller_id = "p1"
    bind_from_catalogue(venser)
    engine.state.add_to_battlefield(venser)
    venser.counters["loyalty"] = loyalty

    def activate(amount, **kwargs):
        venser.activated_loyalty_this_turn = False
        index = next(
            i for i, a in enumerate(venser.activated_abilities)
            if getattr(getattr(a, "cost", None), "loyalty", None) == amount
        )
        engine.activate_ability(p1, venser, index, **kwargs)
        engine.resolve_until_stable()

    return engine, p1, venser, activate


def test_venser_plus_two_exiles_a_permanent_you_own_and_returns_it_at_the_end_step():
    engine, p1, venser, activate = _venser_game()
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    mine.counters["+1/+1"] = 1  # gone after the round trip: it is a new object
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)

    from mtg_analyzer.game import targeting

    spec = targeting.TargetSpec(kind="permanent_you_own")
    legal_ids = {t["instance_id"] for t in targeting.legal_targets(engine.state, "p1", spec, source=venser)}
    assert mine.instance_id in legal_ids and theirs.instance_id not in legal_ids  # owner-scoped

    activate(2, targets=[mine])
    assert venser.counters["loyalty"] == 5
    assert mine.zone == Zone.EXILE and mine not in engine.state.battlefield

    engine.state.current_step = "end"
    engine._fire_delayed_triggers("end")
    for _ in range(3):
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
    assert mine in engine.state.battlefield and not mine.counters
    assert mine.controller_id == "p1"


def _shanid_game():
    card = CardDatabase(DB_PATH).get_card("Shanid, Sleepers' Scourge")
    engine, p1 = _game()
    shanid = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    shanid.controller_id = "p1"
    bind_from_catalogue(shanid)
    engine.state.add_to_battlefield(shanid)
    return engine, p1


def _play_land(engine, p1, name, legendary):
    land = GameObject(
        Card(id=name, name=name, type_line=("Legendary " if legendary else "") + "Land", is_land=True, is_legendary=legendary),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(land)
    p1.add_to_zone(land, Zone.HAND)
    p1.lands_played_this_turn = 0
    life, hand = p1.life, len(p1.hand)
    engine.play_land(p1, land)
    for _ in range(3):
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
    return p1.life - life, len(p1.hand) - hand


def test_shanid_draws_and_loses_life_for_a_legendary_land_but_not_an_ordinary_one():
    engine, p1 = _shanid_game()
    assert _play_land(engine, p1, "Plain Land", legendary=False) == (0, -1)  # just the land leaving the hand
    assert _play_land(engine, p1, "Legendary Land", legendary=True) == (-1, 0)  # -1 life, +1 card -1 land


def test_shanid_also_triggers_on_a_legendary_spell_only():
    engine, p1 = _shanid_game()

    def cast(legendary):
        spell = GameObject(
            Card(id="Sp", name="Spell", type_line=("Legendary " if legendary else "") + "Creature — Elf",
                 is_creature=True, is_legendary=legendary, power=1, toughness=1, mana_cost_string="{1}", converted_mana_cost=1),
            owner_id="p1", zone=Zone.HAND,
        )
        bind_from_catalogue(spell)
        p1.add_to_zone(spell, Zone.HAND)
        p1.mana_pool.add_many({"C": 1})
        life, hand = p1.life, len(p1.hand)
        engine.cast_spell(p1, spell)
        for _ in range(3):
            engine.rules.put_triggers_on_stack()
            engine.resolve_until_stable()
        return p1.life - life, len(p1.hand) - hand

    assert cast(False) == (0, -1)
    assert cast(True) == (-1, 0)


def test_desynchronization_bounces_only_nonland_nonhistoric_permanents_to_their_owners():
    engine, p1 = _game("Desynchronization")
    bear = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    enchantment = battlefield_object(engine, "p1", "Aura Thing", "Enchantment")
    legend = battlefield_object(engine, "p1", "A Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2)
    artifact = battlefield_object(engine, "p1", "Trinket", "Artifact")
    land = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    saga = battlefield_object(engine, "p1", "A Saga", "Enchantment — Saga")
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)

    p1.mana_pool.add_many({"U": 2, "C": p1.hand[0].card.converted_mana_cost - 2})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()

    on_battlefield = set(engine.state.battlefield)
    assert bear not in on_battlefield and enchantment not in on_battlefield and theirs not in on_battlefield
    assert bear in p1.hand and enchantment in p1.hand
    assert theirs in engine.state.player_by_id("p2").hand  # to *its* owner's hand
    assert {legend, artifact, land, saga} <= on_battlefield  # historic or land: stay


def _ruinous_blast_game(with_legendary_creature):
    engine, p1 = _game("Urza's Ruinous Blast")
    legend = None
    if with_legendary_creature:
        legend = battlefield_object(
            engine, "p1", "A Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2,
        )
    return engine, p1, legend


def test_urzas_ruinous_blast_needs_a_legendary_creature_or_planeswalker_to_be_cast():
    engine, p1, _ = _ruinous_blast_game(with_legendary_creature=False)
    p1.mana_pool.add_many({"W": 6})
    assert not engine.can_cast(p1, p1.hand[0])

    engine, p1, _ = _ruinous_blast_game(with_legendary_creature=True)
    p1.mana_pool.add_many({"W": 6})
    assert engine.can_cast(p1, p1.hand[0])


def test_urzas_ruinous_blast_exiles_every_nonland_nonlegendary_permanent():
    engine, p1, legend = _ruinous_blast_game(with_legendary_creature=True)
    bear = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    artifact = battlefield_object(engine, "p1", "Trinket", "Artifact")
    land = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    their_legend = battlefield_object(
        engine, "p2", "Their Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2,
    )

    p1.mana_pool.add_many({"W": 6})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()

    on_battlefield = set(engine.state.battlefield)
    assert not ({bear, artifact, theirs} & on_battlefield)
    assert all(o.zone == Zone.EXILE for o in (bear, artifact, theirs))  # exiled, not destroyed
    assert {legend, land, their_legend} <= on_battlefield


def test_shalai_gives_me_my_planeswalkers_and_my_other_creatures_hexproof():
    from mtg_analyzer.game import targeting

    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Shalai, Voice of Plenty")
    shalai = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    shalai.controller_id = "p1"
    bind_from_catalogue(shalai)
    engine.state.add_to_battlefield(shalai)
    bear = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    walker = battlefield_object(engine, "p1", "My Walker", "Planeswalker — Test", loyalty=4)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()

    assert "hexproof" in bear.granted_keywords and "hexproof" in walker.granted_keywords
    assert "hexproof" not in shalai.granted_keywords  # "other creatures"
    assert "hexproof" not in theirs.granted_keywords

    def player_pool(controller):
        return {t["player_id"] for t in targeting.legal_targets(engine.state, controller, targeting.TargetSpec(kind="player"))}

    assert player_pool("p2") == {"p2"}  # the opponent can no longer target me, only themself
    assert player_pool("p1") == {"p1", "p2"}  # I can still target anyone, myself included


def _orrery(on_battlefield):
    engine, p1 = _game()
    if on_battlefield:
        orrery = battlefield_object(engine, "p1", "Chromatic Orrery", "Legendary Artifact", is_legendary=True)
        bind_from_catalogue(orrery)
    spell = GameObject(
        Card(id="Bolt", name="Red Bolt", type_line="Sorcery", is_sorcery=True, mana_cost_string="{R}{R}",
             converted_mana_cost=2),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"U": 2})  # blue mana only: no red at all
    return engine, p1, spell


def test_chromatic_orrery_lets_any_mana_pay_for_colored_costs():
    engine, p1, spell = _orrery(on_battlefield=False)
    assert not engine.can_cast(p1, spell)  # {R}{R} with two blue mana: no

    engine, p1, spell = _orrery(on_battlefield=True)
    assert engine.can_cast(p1, spell)
    engine.cast_spell(p1, spell)
    assert p1.mana_pool.pool.get("U", 0) == 0  # the blue mana paid the red pips


def test_chromatic_orrery_draws_a_card_per_color_among_my_permanents():
    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Chromatic Orrery")
    orrery = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    orrery.controller_id = "p1"
    bind_from_catalogue(orrery)
    orrery.summoning_sick = False
    engine.state.add_to_battlefield(orrery)
    battlefield_object(engine, "p1", "Red Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"R"})
    battlefield_object(engine, "p1", "Blue Bird", "Creature — Bird", is_creature=True, power=1, toughness=1, color_identity={"U"})
    battlefield_object(engine, "p1", "Red Bear 2", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"R"})
    engine.recompute_continuous_effects()

    index = next(i for i, a in enumerate(orrery.activated_abilities) if getattr(a, "cost", None) is not None)
    p1.mana_pool.add_many({"C": 5})
    hand_before = len(p1.hand)
    engine.activate_ability(p1, orrery, index)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before + 2  # red and blue: two colors, not three permanents


def _sisay_game():
    card = CardDatabase(DB_PATH).get_card("Sisay, Weatherlight Captain")
    engine, p1 = _game()
    sisay = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    sisay.controller_id = "p1"
    bind_from_catalogue(sisay)
    sisay.summoning_sick = False
    engine.state.add_to_battlefield(sisay)
    return engine, p1, sisay


def test_sisay_gets_plus_one_per_color_among_other_legendary_permanents_only():
    engine, p1, sisay = _sisay_game()
    engine.recompute_continuous_effects()
    base = sisay.power
    battlefield_object(engine, "p1", "Red Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True,
                       power=1, toughness=1, color_identity={"R"})
    battlefield_object(engine, "p1", "Red Legend 2", "Legendary Creature — Elf", is_creature=True, is_legendary=True,
                       power=1, toughness=1, color_identity={"R"})
    battlefield_object(engine, "p1", "Blue Legend", "Legendary Artifact", is_legendary=True, color_identity={"U"})
    battlefield_object(engine, "p1", "Green Nonlegend", "Creature — Elf", is_creature=True, power=1, toughness=1, color_identity={"G"})
    battlefield_object(engine, "p2", "Their Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True,
                       power=1, toughness=1, color_identity={"B"})
    engine.recompute_continuous_effects()
    assert sisay.power == base + 2 and sisay.toughness == base + 2  # red + blue; not green (nonlegendary) or black (theirs)


def test_sisay_searches_for_a_legendary_permanent_with_mana_value_below_her_power():
    engine, p1, sisay = _sisay_game()
    for colors in ({"R"}, {"U"}, {"B"}):  # three colors among other legends: power = base + 3
        battlefield_object(engine, "p1", f"Legend {''.join(sorted(colors))}", "Legendary Creature — Elf",
                           is_creature=True, is_legendary=True, power=1, toughness=1, color_identity=colors)
    engine.recompute_continuous_effects()
    power = sisay.power

    def lib(name, mv, type_line, **kw):
        return GameObject(
            Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv, mana_cost_string="{" + str(mv) + "}", **kw),
            owner_id="p1", zone=Zone.LIBRARY,
        )

    small = lib("Small Legend", power - 1, "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=1, toughness=1)
    big = lib("Big Legend", power, "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=1, toughness=1)
    spell = lib("Legendary Sorcery", 1, "Legendary Sorcery", is_sorcery=True, is_legendary=True)
    p1.library.extend([big, spell, small])

    index = next(i for i, a in enumerate(sisay.activated_abilities) if getattr(a, "cost", None) is not None)
    p1.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    engine.activate_ability(p1, sisay, index)
    engine.resolve_until_stable()
    for _ in range(4):
        if not engine.state.pending_choice:
            break
        choice = engine.state.pending_choice
        offered = {o.get("instance_id") for o in choice["options"]}
        assert big.instance_id not in offered and spell.instance_id not in offered  # MV too high / not a permanent
        pick = next(o for o in choice["options"] if o.get("instance_id") == small.instance_id)
        engine.resolve_pending_choice(pick["id"])
        engine.resolve_until_stable()
    assert small in engine.state.battlefield and big not in engine.state.battlefield


def _kethis_game():
    card = CardDatabase(DB_PATH).get_card("Kethis, the Hidden Hand")
    engine, p1 = _game()
    kethis = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    kethis.controller_id = "p1"
    bind_from_catalogue(kethis)
    kethis.summoning_sick = False
    engine.state.add_to_battlefield(kethis)
    return engine, p1, kethis


def _graveyard_card(p1, name, type_line, **kw):
    obj = GameObject(Card(id=name, name=name, type_line=type_line, **kw), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(obj)
    return obj


def test_kethis_makes_legendary_spells_cost_one_less():
    from mtg_analyzer.game import continuous

    engine, p1, kethis = _kethis_game()

    def spell(name, legendary):
        obj = GameObject(
            Card(id=name, name=name, type_line=("Legendary " if legendary else "") + "Creature — Elf", is_creature=True,
                 is_legendary=legendary, power=1, toughness=1, mana_cost_string="{2}", converted_mana_cost=2),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    assert continuous.cost_reduction_for(engine.state, p1, spell("Legend", True))[0] == 1
    assert continuous.cost_reduction_for(engine.state, p1, spell("Plain", False))[0] == 0


def test_kethis_exiles_two_legends_to_let_the_rest_be_played_from_the_graveyard_this_turn():
    from mtg_analyzer.game import graveyard_cast

    engine, p1, kethis = _kethis_game()
    fuel_a = _graveyard_card(p1, "Fuel A", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=1, toughness=1)
    fuel_b = _graveyard_card(p1, "Fuel B", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=1, toughness=1)
    legend = _graveyard_card(p1, "Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2,
                             mana_cost_string="{1}", converted_mana_cost=1)
    legend_land = _graveyard_card(p1, "Legend Land", "Legendary Land", is_land=True, is_legendary=True)
    plain = _graveyard_card(p1, "Plain", "Creature — Elf", is_creature=True, power=1, toughness=1,
                            mana_cost_string="{1}", converted_mana_cost=1)

    assert not graveyard_cast.may_cast_spell_from_graveyard(p1, engine.state, legend.card)  # not yet

    index = next(i for i, a in enumerate(kethis.activated_abilities) if getattr(a, "cost", None) is not None)
    engine.activate_ability(p1, kethis, index)
    for _ in range(3):
        if engine.state.pending_choice:
            choice = engine.state.pending_choice
            engine.resolve_pending_choice(choice["options"][0]["id"])
        engine.resolve_until_stable()

    exiled = [o for o in (fuel_a, fuel_b, legend, legend_land) if o.zone == Zone.EXILE]
    assert len(exiled) == 2  # the cost: two legendary cards
    remaining_legends = [o for o in (fuel_a, fuel_b, legend, legend_land) if o.zone == Zone.GRAVEYARD]
    assert len(remaining_legends) == 2
    for card in remaining_legends:
        if card.is_land:
            assert graveyard_cast.graveyard_land_play_grant_for(p1, engine.state, card.card) is not None
        else:
            assert graveyard_cast.may_cast_spell_from_graveyard(p1, engine.state, card.card)
    assert not graveyard_cast.may_cast_spell_from_graveyard(p1, engine.state, plain.card)  # not legendary


def test_ramos_grows_by_one_for_each_color_of_a_spell_i_cast():
    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Ramos, Dragon Engine")
    ramos = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ramos.controller_id = "p1"
    bind_from_catalogue(ramos)
    engine.state.add_to_battlefield(ramos)

    def cast(colors, cost):
        spell = GameObject(
            Card(id="S", name="Spell", type_line="Sorcery", is_sorcery=True, color_identity=set(colors),
                 mana_cost_string="{" + str(cost) + "}", converted_mana_cost=cost),
            owner_id="p1", zone=Zone.HAND,
        )
        bind_from_catalogue(spell)
        p1.add_to_zone(spell, Zone.HAND)
        p1.mana_pool.add_many({"C": cost})
        engine.cast_spell(p1, spell)
        for _ in range(3):
            engine.rules.put_triggers_on_stack()
            engine.resolve_until_stable()
        return ramos.counters.get("+1/+1", 0)

    assert cast({"R"}, 1) == 1
    assert cast({"W", "U"}, 2) == 3  # +2 for a two-colored spell
    assert cast(set(), 1) == 3  # a colorless spell: nothing


def test_tam_gives_other_creatures_hexproof_only_from_sources_of_their_own_colors():
    from mtg_analyzer.game import targeting

    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Tam, Mindful First-Year")
    tam = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    tam.controller_id = "p1"
    bind_from_catalogue(tam)
    tam.summoning_sick = False
    engine.state.add_to_battlefield(tam)
    red = battlefield_object(engine, "p1", "Red Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"R"})
    engine.recompute_continuous_effects()

    def pool(source_colors):
        source = battlefield_object(engine, "p2", f"Opposing {''.join(sorted(source_colors)) or 'C'}", "Artifact",
                                    color_identity=set(source_colors))
        spec = targeting.TargetSpec(kind="creature")
        return {t["instance_id"] for t in targeting.legal_targets(engine.state, "p2", spec, source=source)}

    assert red.instance_id not in pool({"R"})  # a red source can't target the red creature
    assert red.instance_id in pool({"U"})  # a blue source can
    assert tam.instance_id in pool({"R"})  # "other" creatures only: Tam herself has no hexproof


def test_tam_turns_a_creature_into_all_colors_until_end_of_turn():
    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Tam, Mindful First-Year")
    tam = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    tam.controller_id = "p1"
    bind_from_catalogue(tam)
    tam.summoning_sick = False
    engine.state.add_to_battlefield(tam)
    bear = battlefield_object(engine, "p1", "Red Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"R"})
    engine.recompute_continuous_effects()
    assert set(bear.colors) == {"R"}

    index = next(i for i, a in enumerate(tam.activated_abilities) if getattr(a, "cost", None) is not None)
    engine.activate_ability(p1, tam, index, targets=[bear])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert set(bear.colors) == {"W", "U", "B", "R", "G"}

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert set(bear.colors) == {"R"}


def _dihada_game(loyalty):
    card = CardDatabase(DB_PATH).get_card("Dihada, Binder of Wills")
    engine, p1 = _game()
    dihada = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    dihada.controller_id = "p1"
    bind_from_catalogue(dihada)
    engine.state.add_to_battlefield(dihada)
    dihada.counters["loyalty"] = loyalty

    def activate(amount, **kwargs):
        dihada.activated_loyalty_this_turn = False
        index = next(
            i for i, a in enumerate(dihada.activated_abilities)
            if getattr(getattr(a, "cost", None), "loyalty", None) == amount
        )
        engine.activate_ability(p1, dihada, index, **kwargs)
        engine.resolve_until_stable()
        for _ in range(8):
            if not engine.state.pending_choice:
                break
            options = [o for o in engine.state.pending_choice["options"] if o["id"] != "decline"]
            engine.resolve_pending_choice((options or engine.state.pending_choice["options"])[0]["id"])
            engine.resolve_until_stable()
        engine.recompute_continuous_effects()

    return engine, p1, dihada, activate


def test_dihada_plus_two_protects_a_legendary_creature_until_my_next_turn():
    engine, p1, dihada, activate = _dihada_game(3)
    legend = battlefield_object(engine, "p1", "A Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2)
    activate(2, targets=[legend])
    assert dihada.counters["loyalty"] == 5
    assert {"vigilance", "lifelink", "indestructible"} <= set(legend.granted_keywords)


def test_dihada_minus_three_keeps_the_legends_and_turns_the_rest_into_treasures():
    engine, p1, dihada, activate = _dihada_game(5)
    p1.library.clear()
    cards = {
        "Legend A": ("Legendary Creature — Elf", True), "Legend B": ("Legendary Artifact", True),
        "Plain A": ("Creature — Elf", False), "Plain B": ("Instant", False),
    }
    for name, (type_line, legendary) in cards.items():
        p1.library.append(GameObject(Card(id=name, name=name, type_line=type_line, is_legendary=legendary), owner_id="p1", zone=Zone.LIBRARY))
    hand_before = {o.name for o in p1.hand}
    activate(-3)
    assert {o.name for o in p1.hand} - hand_before == {"Legend A", "Legend B"}
    assert {o.name for o in p1.graveyard} == {"Plain A", "Plain B"}
    treasures = [o for o in engine.state.permanents_controlled_by("p1") if "Treasure" in (o.card.type_line or "")]
    assert len(treasures) == 2  # one per card put into the graveyard this way


def test_dihada_minus_eleven_takes_every_nonland_permanent_until_end_of_turn():
    engine, p1, dihada, activate = _dihada_game(11)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    their_land = battlefield_object(engine, "p2", "Their Forest", "Basic Land — Forest", is_land=True)
    theirs.tapped = True
    activate(-11)
    assert theirs.controller_id == "p1" and not theirs.tapped and "haste" in theirs.granted_keywords
    assert their_land.controller_id == "p2"  # lands are not nonland permanents

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert theirs.controller_id == "p2"


def test_esika_gives_other_legendary_creatures_vigilance_and_an_any_color_mana_ability():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Esika, God of the Tree // The Prismatic Bridge")
    esika = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    esika.controller_id = "p1"
    bind_from_catalogue(esika)
    esika.summoning_sick = False
    engine.state.add_to_battlefield(esika)
    legend = battlefield_object(engine, "p1", "A Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2)
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Legend", "Legendary Creature — Elf", is_creature=True, is_legendary=True, power=2, toughness=2)
    for creature in (legend, plain, theirs):
        creature.summoning_sick = False
    engine.recompute_continuous_effects()

    assert "vigilance" in legend.granted_keywords
    assert "vigilance" not in plain.granted_keywords and "vigilance" not in theirs.granted_keywords
    assert mana_abilities_for(legend, engine.state) and not mana_abilities_for(plain, engine.state)
    assert not mana_abilities_for(theirs, engine.state)

    engine.tap_for_mana(p1, legend)
    assert sum(p1.mana_pool.pool.get(c, 0) for c in "WUBRG") == 1  # one mana of a chosen color


def test_serah_discounts_only_the_first_legendary_creature_spell_each_turn():
    from mtg_analyzer.game import continuous

    engine, p1 = _game()
    card = CardDatabase(DB_PATH).get_card("Serah Farron // Crystallized Serah")
    serah = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    serah.controller_id = "p1"
    bind_from_catalogue(serah)
    engine.state.add_to_battlefield(serah)

    def make(name, legendary, creature=True):
        obj = GameObject(
            Card(id=name, name=name, type_line=("Legendary " if legendary else "") + ("Creature — Elf" if creature else "Artifact"),
                 is_creature=creature, is_legendary=legendary, power=1 if creature else None, toughness=1 if creature else None,
                 mana_cost_string="{3}", converted_mana_cost=3),
            owner_id="p1", zone=Zone.HAND,
        )
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    def discount(obj):
        return continuous.cost_reduction_for(engine.state, p1, obj)[0]

    first, second = make("First Legend", True), make("Second Legend", True)
    plain, legendary_artifact = make("Plain", False), make("Legendary Artifact", True, creature=False)
    assert discount(first) == 2 and discount(second) == 2  # nothing cast yet
    assert discount(plain) == 0 and discount(legendary_artifact) == 0  # not a legendary creature spell

    p1.mana_pool.add_many({"C": 1})  # {3} - 2
    engine.cast_spell(p1, first)
    engine.resolve_until_stable()
    assert discount(second) == 0  # the first legendary creature spell this turn is gone


def test_atraxa_takes_at_most_one_card_of_each_card_type_from_the_top_ten():
    engine, p1 = _game("Atraxa, Grand Unifier")
    p1.library.clear()
    # drawn from the END of the library: the last ten appended are the "top ten"
    revealed = [
        ("Bear A", "Creature — Bear", dict(is_creature=True, power=2, toughness=2)),
        ("Bear B", "Creature — Bear", dict(is_creature=True, power=2, toughness=2)),
        ("Island A", "Basic Land — Island", dict(is_land=True)),
        ("Island B", "Basic Land — Island", dict(is_land=True)),
        ("Bolt A", "Instant", dict(is_instant=True)),
        ("Bolt B", "Instant", dict(is_instant=True)),
        ("Rock", "Artifact", {}),
        ("Aura", "Enchantment — Aura", {}),
        ("Walker", "Planeswalker — Test", {"loyalty": 3}),
        ("Spell", "Sorcery", dict(is_sorcery=True)),
    ]
    for name, type_line, kw in revealed:
        p1.library.append(GameObject(Card(id=name, name=name, type_line=type_line, **kw), owner_id="p1", zone=Zone.LIBRARY))
    filler = GameObject(Card(id="Deep", name="Deep Card", type_line="Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.insert(0, filler)  # below the top ten: never revealed

    p1.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "G": 1, "C": 3})  # {3}{G}{W}{U}{B}
    hand_before = {o.name for o in p1.hand}
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    picked_types = []
    for _ in range(20):
        choice = engine.state.pending_choice
        if not choice:
            break
        options = [o for o in choice["options"] if o["id"] != "decline"]
        if not options:
            break
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_until_stable()
        picked_types.append(options[0]["label"])

    gained = {o.name for o in p1.hand} - hand_before - {"Atraxa, Grand Unifier"}
    types_of = {name: type_line.split("—")[0].split()[-1].lower() for name, type_line, _ in revealed}
    gained_types = [types_of[n] for n in gained]
    seven_types = {"creature", "land", "instant", "artifact", "enchantment", "planeswalker", "sorcery"}  # no battle in the top ten
    assert len(gained) == 7 and set(gained_types) == seven_types  # exactly one card of each type that was there
    assert "Deep Card" not in {o.name for o in p1.hand}  # beyond the top ten: untouched
    assert len(p1.library) == (10 - 7) + 1  # the three unpicked revealed cards went to the bottom, plus the deep card


def _kellan_game():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    card = CardDatabase(DB_PATH).get_card("Kellan, the Kid")
    engine, p1 = _game()
    kellan = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    kellan.controller_id = "p1"
    bind_from_catalogue(kellan)
    engine.state.add_to_battlefield(kellan)

    def hand_card(name, type_line, mv, **kw):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv, mana_cost_string="{" + str(mv) + "}", **kw),
            owner_id="p1", zone=Zone.HAND,
        )
        bind_from_catalogue(obj)
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    cheap = hand_card("Cheap Bear", "Creature — Bear", 2, is_creature=True, power=2, toughness=2)
    dear = hand_card("Dear Dragon", "Creature — Dragon", 6, is_creature=True, power=5, toughness=5)
    bolt = hand_card("Bolt", "Instant", 1, is_instant=True)
    land = hand_card("Forest", "Basic Land — Forest", 0, is_land=True)

    def cast_from_elsewhere(mv, from_hand):
        engine.state.fire_event(GameEvent(
            EventType.SPELL_CAST, player_id="p1", controller_id="p1", object="Flashbacked", object_types=["sorcery"],
            mana_value=mv, from_hand=from_hand,
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    return engine, p1, cheap, dear, bolt, land, cast_from_elsewhere


def test_kellan_offers_a_free_permanent_spell_up_to_the_trigger_spells_mana_value():
    engine, p1, cheap, dear, bolt, land, cast_from_elsewhere = _kellan_game()
    cast_from_elsewhere(mv=3, from_hand=False)
    choice = engine.state.pending_choice
    offered = {o.get("instance_id") for o in choice["options"]} - {None}  # None is the decline option
    assert offered == {cheap.instance_id}  # not the MV 6 dragon, not the instant, not the land
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("instance_id") == cheap.instance_id))
    engine.resolve_until_stable()
    assert cheap.instance_id in engine.state.free_cast_instance_ids  # armed: castable without paying
    engine.state.current_step = "main1"
    engine.cast_spell(p1, cheap)  # no mana in the pool at all
    engine.resolve_until_stable()
    assert cheap in engine.state.battlefield


def test_kellan_puts_a_land_onto_the_battlefield_if_no_spell_was_cast_for_free():
    engine, p1, cheap, dear, bolt, land, cast_from_elsewhere = _kellan_game()
    cast_from_elsewhere(mv=3, from_hand=False)
    engine.resolve_pending_choice("decline")  # "if you don't"
    engine.resolve_until_stable()
    for _ in range(3):
        choice = engine.state.pending_choice
        if not choice:
            break
        pick = next((o for o in choice["options"] if o.get("instance_id") == land.instance_id), choice["options"][0])
        engine.resolve_pending_choice(pick["id"])
        engine.resolve_until_stable()
    assert land in engine.state.battlefield


def test_kellan_ignores_spells_cast_from_the_hand():
    engine, p1, cheap, dear, bolt, land, cast_from_elsewhere = _kellan_game()
    cast_from_elsewhere(mv=3, from_hand=True)
    assert engine.state.pending_choice is None


def _inga_game(creatures_for_mana):
    card = CardDatabase(DB_PATH).get_card("Inga and Esika")
    engine, p1 = _game()
    inga = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    inga.controller_id = "p1"
    bind_from_catalogue(inga)
    engine.state.add_to_battlefield(inga)
    elves = [
        battlefield_object(engine, "p1", f"Elf {i}", "Creature — Elf", is_creature=True, power=1, toughness=1)
        for i in range(creatures_for_mana)
    ]
    for elf in elves:
        elf.summoning_sick = False
    engine.recompute_continuous_effects()
    return engine, p1, inga, elves


def _creature_spell(p1, mv, name="Big Beast", type_line="Creature — Beast", **kw):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv, mana_cost_string="{" + str(mv) + "}", **kw),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    return obj


def test_inga_and_esika_gives_creatures_vigilance_and_a_creature_spell_only_mana_ability():
    engine, p1, inga, (elf,) = _inga_game(1)
    assert "vigilance" in elf.granted_keywords
    engine.tap_for_mana(p1, elf)
    assert sum(sum(lot["amounts"].values()) for lot in p1.mana_pool.restricted) == 1  # restricted mana, not plain pool

    # that mana is restricted: it can pay for a creature spell but not for a noncreature one
    creature = _creature_spell(p1, 1, is_creature=True, power=1, toughness=1)
    sorcery = _creature_spell(p1, 1, name="A Sorcery", type_line="Sorcery", is_sorcery=True)
    assert engine.can_cast(p1, creature)
    assert not engine.can_cast(p1, sorcery)


def test_inga_and_esika_draws_when_three_or_more_mana_from_creatures_paid_for_a_creature_spell():
    engine, p1, inga, elves = _inga_game(3)
    for elf in elves:
        engine.tap_for_mana(p1, elf)
    spell = _creature_spell(p1, 3, is_creature=True, power=3, toughness=3)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, spell)
    for _ in range(3):
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
    assert len(p1.hand) == hand_before - 1 + 1  # the spell leaves, one card is drawn

    engine, p1, inga, elves = _inga_game(2)
    for elf in elves:
        engine.tap_for_mana(p1, elf)
    p1.mana_pool.add_many({"C": 1})  # the third mana does not come from a creature
    spell = _creature_spell(p1, 3, is_creature=True, power=3, toughness=3)
    hand_before = len(p1.hand)
    engine.cast_spell(p1, spell)
    for _ in range(3):
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
    assert len(p1.hand) == hand_before - 1  # only two mana from creatures: no draw


def test_gogo_copies_a_targeted_ability_on_the_stack_x_times():
    engine, p1 = _game()
    gogo_card = CardDatabase(DB_PATH).get_card("Gogo, Master of Mimicry")
    gogo = GameObject(gogo_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    gogo.controller_id = "p1"
    bind_from_catalogue(gogo)
    gogo.summoning_sick = False
    engine.state.add_to_battlefield(gogo)
    asc_card = CardDatabase(DB_PATH).get_card("Simic Ascendancy")
    ascendancy = GameObject(asc_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ascendancy.controller_id = "p1"
    bind_from_catalogue(ascendancy)
    engine.state.add_to_battlefield(ascendancy)
    bear = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.state.current_step = "main1"

    # {1}{G}{U}: put a +1/+1 counter on target creature you control — activate it and leave it on the stack
    p1.mana_pool.add_many({"G": 1, "U": 1, "C": 1})
    counter_ability = next(
        i for i, a in enumerate(ascendancy.activated_abilities)
        if getattr(a, "cost", None) is not None
    )
    engine.activate_ability(p1, ascendancy, counter_ability, targets=[bear])
    pending = [item for item in engine.state.stack if item.kind == "ability"]
    assert len(pending) == 1

    # {X}{X}, {T} with X = 2: copy that ability twice
    p1.mana_pool.add_many({"C": 4})
    gogo_ability = next(i for i, a in enumerate(gogo.activated_abilities) if getattr(a, "cost", None) is not None)
    engine.activate_ability(p1, gogo, gogo_ability, x=2, targets=[{"stack_id": pending[0].stack_id}])
    engine.resolve_until_stable()
    while engine.state.pending_choice and engine.state.pending_choice["kind"] == "copy_targets":
        engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()

    assert bear.counters.get("+1/+1", 0) == 3  # the original plus two copies
    assert gogo.tapped
