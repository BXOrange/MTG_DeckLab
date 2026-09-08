"""Secrets of Strixhaven — playability batch, wave 90 (PAR-60).

Hofri Ghostforge — new `hofri_ghostforge_dies` effect (reuse
`copy_permanent` with ``add_subtypes=["Spirit"]``). Spirit anthem static
folds in. Documented simplification: the copy token's leave-return rider is
dropped.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _hofri_card():
    return Card(id="hf", name="Hofri Ghostforge",
                type_line="Legendary Creature — Dwarf Cleric", is_creature=True,
                power=4, toughness=5,
                oracle_text=("Spirits you control get +1/+1 and have trample and haste.\n"
                             "Whenever another nontoken creature you control dies, exile "
                             "it. If you do, create a token that's a copy of that "
                             "creature, except it's a Spirit in addition to its other "
                             "types and it has \"When this token leaves the battlefield, "
                             "return the exiled card to its owner's graveyard.\""))


def test_registered_and_binds():
    assert is_registered("Hofri Ghostforge")
    specs = _REGISTRY["hofri ghostforge"]()
    assert len(specs) == 2
    assert specs[0].effects[0].type == "anthem"
    assert specs[1].effects[0].type == "hofri_ghostforge_dies"
    assert specs[1].trigger["condition"]["nontoken"] is True
    src = GameObject(_hofri_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_hofri_card())


def test_nontoken_creature_death_exiles_it_and_makes_a_spirit_copy():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    hofri = GameObject(_hofri_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    hofri.controller_id = "p1"
    hofri.summoning_sick = False
    eng.state.add_to_battlefield(hofri)
    bind_from_catalogue(hofri)

    dude = GameObject(Card(id="d", name="Loyal Warhound", type_line="Creature — Dog",
                           is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    dude.controller_id = "p1"
    eng.state.add_to_battlefield(dude)
    eng.recompute_continuous_effects()

    eng.rules.destroy(dude)
    eng.resolve_until_stable()

    assert dude.zone == Zone.EXILE
    copies = [o for o in eng.state.battlefield
              if o.card.name == "Loyal Warhound" and getattr(o, "is_token", False)]
    assert len(copies) == 1
    assert "spirit" in (copies[0].card.type_line or "").lower()
