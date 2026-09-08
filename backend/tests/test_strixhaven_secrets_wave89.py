"""Secrets of Strixhaven — playability batch, wave 89 (PAR-60).

Ao, the Dawn Sky — new `budget_dig_onto_battlefield` effect (greedy
cheapest-first auto-selection under a total-MV budget) + modal DIES trigger.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _ao_card():
    return Card(id="ao", name="Ao, the Dawn Sky",
                type_line="Legendary Creature — Dragon Spirit", is_creature=True,
                power=5, toughness=4,
                oracle_text=("Flying, vigilance\nWhen Ao dies, choose one —\n• Look at "
                             "the top seven cards of your library. Put any number of "
                             "nonland permanent cards with total mana value 4 or less "
                             "from among them onto the battlefield. Put the rest on the "
                             "bottom of your library in a random order.\n• Put two +1/+1 "
                             "counters on each permanent you control that's a creature "
                             "or Vehicle."))


def test_registered_and_binds():
    assert is_registered("Ao, the Dawn Sky")
    spec = _REGISTRY["ao, the dawn sky"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "DIES"
    assert spec.modes["choose"] == 1
    assert spec.modes["options"][0][0].type == "budget_dig_onto_battlefield"
    src = GameObject(_ao_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ao_card())


def test_budget_dig_takes_cheap_permanents_up_to_budget():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    # top of library: a 2-MV creature, a 1-MV artifact, a 5-MV creature, 4 lands
    for name, tl, mv in [
        ("Land1", "Basic Land — Forest", 0), ("Land2", "Basic Land — Forest", 0),
        ("Land3", "Basic Land — Forest", 0), ("Land4", "Basic Land — Forest", 0),
        ("Big", "Creature — Dragon", 5),
        ("Rock", "Artifact", 1),
        ("Bear", "Creature — Bear", 2),
    ]:
        c = Card(id=name, name=name, type_line=tl, is_land="Land" in tl,
                 is_creature="Creature" in tl, converted_mana_cost=mv,
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None)
        p1.add_to_zone(GameObject(c, owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)

    src = GameObject(_ao_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    eng.rules._apply_effect_specs(
        [{"type": "budget_dig_onto_battlefield", "params": {"look": 7, "budget": 4}}], src,
    )
    eng.resolve_until_stable()

    names = {o.card.name for o in eng.state.battlefield if o.controller_id == "p1"}
    assert "Rock" in names and "Bear" in names   # 1 + 2 = 3 <= 4
    assert "Big" not in names                     # 5 alone > 4
    assert "Land1" not in names                   # lands excluded
