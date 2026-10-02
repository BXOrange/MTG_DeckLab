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
