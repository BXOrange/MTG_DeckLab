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
