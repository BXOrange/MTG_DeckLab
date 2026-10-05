"""Currency Converter tracks exiled cards and mana abilities."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    else:
        state.player_by_id(controller).add_to_zone(obj, zone)
    bind_from_catalogue(obj)
    return obj


def _converter():
    return Card(id="cc", name="Currency Converter", type_line="Artifact",
                oracle_text=(
                    "Whenever you discard a card, you may exile that card from your "
                    "graveyard.\n{2}, {T}: Draw a card, then discard a card.\n"
                    "{T}: Put a card exiled with this artifact into its owner's "
                    "graveyard. If it's a land card, create a Treasure token. If "
                    "it's a nonland card, create a 2/2 black Rogue creature token."))


def test_registered_with_three_abilities():
    assert is_registered("Currency Converter")
    specs = _REGISTRY["currency converter"]()
    kinds = [(s.ability_kind, s.effects[0].type) for s in specs]
    assert ("triggered", "exile_triggering_discard_may_play_this_turn") in kinds
    assert ("activated", "currency_converter_cash_out") in kinds
    trig = next(s for s in specs if s.ability_kind == "triggered")
    assert trig.effects[0].params == {"play_permission": False, "track_exiled_with": True}
    for s in specs:
        s.validate()


def test_specs_for_real_card_binds():
    specs = specs_for(_converter())
    assert specs
    obj = GameObject(_converter(), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)


def test_discard_banks_card_and_tap_cashes_out_nonland_to_rogue():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    cc = _put(eng.state, _converter())
    eng.recompute_continuous_effects()

    spell = _put(eng.state, Card(id="s", name="Bolt", type_line="Instant",
                                 is_instant=True),
                 controller="p1", zone=Zone.HAND)
    eng.rules.discard(p1, 1)  # sole hand card
    eng.resolve_until_stable()

    # banked, not in graveyard, not playable
    assert spell.zone == Zone.EXILE
    assert spell.instance_id in cc.exiled_with_ids
    assert spell.instance_id not in eng.state.temp_play_permissions

    # {T} cash-out: nonland -> 2/2 black Rogue, card goes to graveyard
    idx = next(i for i, a in enumerate(cc.activated_abilities)
               if any(e.__class__.__name__ == "CurrencyConverterCashOutEffect"
                      for e in getattr(a, "effects", [])))
    eng.activate_ability(p1, cc, ability_index=idx)
    eng.resolve_until_stable()

    assert spell in p1.graveyard
    assert spell.instance_id not in cc.exiled_with_ids
    rogues = [o for o in eng.state.battlefield
              if o.controller_id == "p1" and "Rogue" in (o.card.type_line or "")]
    assert len(rogues) == 1
    assert (rogues[0].power, rogues[0].toughness) == (2, 2)


def test_cash_out_land_makes_a_treasure():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    cc = _put(eng.state, _converter())
    eng.recompute_continuous_effects()

    land = _put(eng.state, Card(id="L", name="Forest",
                                type_line="Basic Land — Forest", is_land=True),
                controller="p1", zone=Zone.HAND)
    eng.rules.discard(p1, 1)  # sole hand card
    eng.resolve_until_stable()
    assert land.instance_id in cc.exiled_with_ids

    idx = next(i for i, a in enumerate(cc.activated_abilities)
               if any(e.__class__.__name__ == "CurrencyConverterCashOutEffect"
                      for e in getattr(a, "effects", [])))
    eng.activate_ability(p1, cc, ability_index=idx)
    eng.resolve_until_stable()

    assert land in p1.graveyard
    treasures = [o for o in eng.state.battlefield
                 if o.controller_id == "p1" and "Treasure" in (o.card.name or "")]
    assert len(treasures) == 1
