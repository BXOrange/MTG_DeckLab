"""Gift of Immortality returns a creature after it dies."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _gift_card():
    return Card(id="gi", name="Gift of Immortality", type_line="Enchantment — Aura",
                oracle_text=("Enchant creature\nWhen enchanted creature dies, return "
                             "that card to the battlefield under its owner's control. "
                             "Return this card to the battlefield attached to that "
                             "creature at the beginning of the next end step."))


def test_registered_and_binds():
    assert is_registered("Gift of Immortality")
    spec = _REGISTRY["gift of immortality"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "DIES"
    assert spec.trigger["condition"]["subject"] == "attached_permanent"
    assert [e.type for e in spec.effects] == ["gift_of_immortality_dies"]
    src = GameObject(_gift_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_gift_card())


def test_dying_creature_comes_back_immediately_and_aura_at_end_step():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    creature = GameObject(Card(id="c", name="Doomed Dissenter",
                               type_line="Creature — Human", is_creature=True,
                               power=1, toughness=1),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    creature.controller_id = "p1"
    eng.state.add_to_battlefield(creature)

    gift = GameObject(_gift_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    gift.controller_id = "p1"
    gift.attached_to = creature.instance_id
    eng.state.add_to_battlefield(gift)
    bind_from_catalogue(gift)
    eng.recompute_continuous_effects()

    eng.rules.destroy(creature)
    eng.resolve_until_stable()

    # the creature card is back on the battlefield (a fresh object with the
    # same underlying card), under its owner's control
    back = [o for o in eng.state.battlefield
            if o.card.name == "Doomed Dissenter" and o.controller_id == "p1"]
    assert len(back) == 1
    # the Aura is still in the graveyard until the end step
    assert gift.zone == Zone.GRAVEYARD

    # run to end step -> the delayed trigger returns the Aura
    eng.advance_to_phase("end") if hasattr(eng, "advance_to_phase") else None
    # generic: step through until an END step processes the delayed trigger
    for _ in range(40):
        eng.advance_step()
        eng.resolve_until_stable()
        if gift.zone == Zone.BATTLEFIELD:
            break
    assert gift.zone == Zone.BATTLEFIELD
    assert gift.attached_to == back[0].instance_id
