"""Hand-authored cards of the saved "Raggadragga, Goreguts Boss" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import battlefield_object, two_player_game


def test_wirewood_herald_fetches_an_elf_when_it_dies():
    engine, player = two_player_game()
    herald = battlefield_object(
        engine, "p1", "Wirewood Herald", "Creature — Elf", is_creature=True, power=1, toughness=1,
    )
    bind_from_catalogue(herald)
    elf = GameObject(Card(id="Elf", name="Llanowar Elf", type_line="Creature — Elf Druid", is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.LIBRARY)
    bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.LIBRARY)
    player.library.extend([bear, elf])

    engine.rules.destroy(herald)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        options = [o for o in choice["options"] if o["id"] != "decline"]
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_until_stable()
    assert elf in player.hand and bear not in player.hand  # only Elf cards qualify


def test_akromas_memorial_grants_every_creature_you_control_the_full_set():
    engine, player = two_player_game()
    memorial = battlefield_object(engine, "p1", "Akroma's Memorial", "Legendary Artifact")
    bind_from_catalogue(memorial)
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()

    for keyword in ("flying", "first_strike", "vigilance", "trample", "haste"):
        assert keyword in mine.granted_keywords, keyword
        assert keyword not in theirs.granted_keywords, keyword

    # protection from black and from red (RULE 702.16), read colour off the source
    from mtg_analyzer.game import combat

    black = battlefield_object(engine, "p2", "Black Zombie", "Creature — Zombie", is_creature=True, power=2, toughness=2, color_identity={"B"})
    red = battlefield_object(engine, "p2", "Red Goblin", "Creature — Goblin", is_creature=True, power=2, toughness=2, color_identity={"R"})
    green = battlefield_object(engine, "p2", "Green Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"G"})
    assert combat.is_protected_from(mine, black) and combat.is_protected_from(mine, red)
    assert not combat.is_protected_from(mine, green)
    assert not combat.is_protected_from(theirs, black)  # only my creatures


def test_saryth_grants_by_tapped_state_and_untaps_another_creature_or_land():
    engine, player = two_player_game()
    saryth = battlefield_object(
        engine, "p1", "Saryth, the Viper's Fang", "Legendary Creature — Human Warlock",
        is_creature=True, power=2, toughness=2,
    )
    bind_from_catalogue(saryth)
    saryth.summoning_sick = False
    tapped_bear = battlefield_object(engine, "p1", "Tapped Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    fresh_bear = battlefield_object(engine, "p1", "Fresh Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    forest = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    tapped_bear.tapped = True
    forest.tapped = True
    engine.recompute_continuous_effects()
    assert "deathtouch" in tapped_bear.granted_keywords and "hexproof" not in tapped_bear.granted_keywords
    assert "hexproof" in fresh_bear.granted_keywords and "deathtouch" not in fresh_bear.granted_keywords

    index = next(
        i for i, a in enumerate(saryth.activated_abilities)
        if any(getattr(e, "untap", False) for e in getattr(a, "effects", []))
    )
    player.mana_pool.add_many({"C": 1})
    engine.activate_ability(player, saryth, index, targets=[tapped_bear])
    engine.resolve_until_stable()
    assert not tapped_bear.tapped and saryth.tapped

    saryth.tapped = False
    player.mana_pool.add_many({"C": 1})
    engine.activate_ability(player, saryth, index, targets=[forest])
    engine.resolve_until_stable()
    assert not forest.tapped  # lands work too

    from mtg_analyzer.game import targeting
    assert saryth not in targeting.legal_targets(
        engine.state, player, targeting.TargetSpec(kind="another_creature_or_land_you_control"), source=saryth,
    )


def test_twitching_doll_taps_for_mana_with_a_nest_counter_then_sacrifices_for_spiders():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    card = CardDatabase(DB_PATH).get_card("Twitching Doll")
    doll = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    doll.controller_id = "p1"
    bind_from_catalogue(doll)
    doll.summoning_sick = False
    engine.state.add_to_battlefield(doll)
    engine.state.current_step = "main1"

    engine.tap_for_mana(player, doll)
    assert doll.counters.get("nest", 0) == 1  # the mana ability's own rider
    doll.counters["nest"] = 3
    doll.tapped = False

    index = next(i for i, a in enumerate(doll.activated_abilities) if getattr(a, "cost", None) is not None
                 and "sacrifice" in str(getattr(a.cost, "raw", getattr(a.cost, "text", a.cost))).lower())
    engine.activate_ability(player, doll, index)
    engine.resolve_until_stable()

    spiders = [o for o in engine.state.battlefield if "Spider" in (o.card.type_line or "")]
    assert doll not in engine.state.battlefield
    assert len(spiders) == 3  # one per nest counter
    assert all(s.power == 2 and s.toughness == 2 and "reach" in s.granted_keywords | set(getattr(s.card, "keywords", []) or []) for s in spiders)


def test_march_of_the_world_ooze_makes_my_creatures_6_6_oozes_and_rewards_off_turn_spells():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, player = two_player_game()  # p1 is the active player
    march = battlefield_object(engine, "p1", "March of the World Ooze", "Enchantment")
    bind_from_catalogue(march)
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (6, 6) and (theirs.power, theirs.toughness) == (2, 2)
    from mtg_analyzer.game.continuous import has_subtype

    assert has_subtype(mine, "Ooze") and not has_subtype(theirs, "Ooze")

    def elephants():
        return [o for o in engine.state.permanents_controlled_by("p1") if "Elephant" in (o.card.type_line or "")]

    def opponent_casts():
        engine.state.fire_event(GameEvent(
            EventType.SPELL_CAST, player_id="p2", controller_id="p2", object="Bolt",
            object_types=["instant"], mana_value=1,
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    opponent_casts()  # during MY turn: it's not their turn -> an Elephant
    assert len(elephants()) == 1

    engine.state.active_player_index = 1  # their own turn: nothing
    opponent_casts()
    assert len(elephants()) == 1
