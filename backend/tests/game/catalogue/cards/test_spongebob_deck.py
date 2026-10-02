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
