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

    legal_ids = {
        t["instance_id"]
        for t in targeting.legal_targets(
            engine.state, "p1", targeting.TargetSpec(kind="another_creature_or_land_you_control"), source=saryth,
        )
    }
    assert {tapped_bear.instance_id, fresh_bear.instance_id, forest.instance_id} <= legal_ids  # a real, non-empty pool
    assert saryth.instance_id not in legal_ids  # "another"
