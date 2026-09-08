"""Brudiclad, Telchor Engineer creates and copies tokens."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _brudiclad_card():
    return Card(id="br", name="Brudiclad, Telchor Engineer",
                type_line="Legendary Artifact Creature — Phyrexian Artificer",
                is_creature=True, power=4, toughness=4,
                oracle_text=("Creature tokens you control have haste.\nAt the beginning "
                             "of combat on your turn, create a 2/1 blue Phyrexian Myr "
                             "artifact creature token. Then you may choose a token you "
                             "control. If you do, each other token you control becomes a "
                             "copy of that token."))


def test_registered_and_binds():
    assert is_registered("Brudiclad, Telchor Engineer")
    specs = _REGISTRY["brudiclad, telchor engineer"]()
    assert len(specs) == 2
    assert specs[0].effects[0].type == "grant_keyword"
    assert specs[1].effects[0].type == "brudiclad_combat"
    src = GameObject(_brudiclad_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_brudiclad_card())


def test_makes_myr_and_turns_other_tokens_into_a_copy_of_the_chosen():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    bru = GameObject(_brudiclad_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bru.controller_id = "p1"
    bru.summoning_sick = False
    eng.state.add_to_battlefield(bru)
    bind_from_catalogue(bru)

    # an existing "good" token we want to copy onto everything
    dragon = GameObject(Card(id="drg", name="Dragon Illusion",
                             type_line="Creature — Dragon Illusion", is_creature=True,
                             power=4, toughness=4), owner_id="p1",
                        zone=Zone.BATTLEFIELD, is_token=True)
    dragon.controller_id = "p1"
    eng.state.add_to_battlefield(dragon)
    # a chump token
    goblin = GameObject(Card(id="gob", name="Goblin", type_line="Creature — Goblin",
                             is_creature=True, power=1, toughness=1),
                        owner_id="p1", zone=Zone.BATTLEFIELD, is_token=True)
    goblin.controller_id = "p1"
    eng.state.add_to_battlefield(goblin)
    eng.recompute_continuous_effects()

    eng.rules._apply_effect_specs([{"type": "brudiclad_combat", "params": {}}], bru)
    # a Myr token was made; now the "choose a token" prompt is open
    assert eng.state.pending_choice and eng.state.pending_choice["kind"] == "choose_objects"
    eng.resolve_pending_choice(str(dragon.instance_id))
    eng.resolve_until_stable()

    # every other token is now a Dragon Illusion copy
    tokens = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) >= 3
    non_dragon = [o for o in tokens if o is not dragon
                  and o.card.name != "Dragon Illusion"]
    assert not non_dragon
