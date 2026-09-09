"""Secrets of Strixhaven Commander decks — playability batch, wave 1.

Wave 1: Fabled Passage — the Evolving Wilds fetch plus the trailing
"then if you control four or more lands, untap that land" conditional,
threaded through `SearchLibraryEffect` as `untap_if_lands_at_least`.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered, specs_for
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _card(name, type_line, **flags):
    return Card(id=name, name=name, type_line=type_line, mana_cost_string="",
               converted_mana_cost=0, color_identity=set(), **flags)


def _library(n_basics=4):
    lib = [_card(f"Forest{i}", "Basic Land — Forest", is_land=True) for i in range(n_basics)]
    return lib


def _engine(field_lands=0, library=None):
    eng = GameEngine.new_game(
        [("p1", "Alice", library if library is not None else _library())],
        starting_hand=0,
    )
    p1 = eng.state.active_player
    for i in range(field_lands):
        land = GameObject(_card(f"OnField{i}", "Basic Land — Plains", is_land=True),
                          owner_id=p1.id, zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(land)
    return eng, p1


def _source(p1):
    # Fabled Passage sacrifices itself as a cost, so it is NOT on the
    # battlefield when the search resolves — an off-battlefield stub.
    return GameObject(_card("Fabled Passage", "Land", is_land=True),
                      owner_id=p1.id, zone=Zone.GRAVEYARD)


def _fetch_spec_params():
    specs = specs_for(CardDatabase(DEFAULT_DB_PATH).get_card("Fabled Passage"))
    return specs[0].effects[0].params


def test_fabled_passage_is_registered_with_untap_threshold():
    assert is_registered("Fabled Passage")
    params = _fetch_spec_params()
    assert params["destination"] == "battlefield_tapped"
    assert params["untap_if_lands_at_least"] == 4
    assert params["criteria"] == {"basic": True}


def test_fetched_land_untaps_with_four_or_more_lands():
    # 3 lands already out; the fetched land is the 4th -> it counts itself.
    eng, p1 = _engine(field_lands=3)
    effect = EffectRegistry.create("search", dict(_fetch_spec_params()))
    effect.source = _source(p1)
    effect.apply(eng.rules.context)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    obj = eng.state.find_object(chosen)
    assert obj in eng.state.battlefield
    assert obj.is_land
    assert obj.tapped is False, "with 4 lands (incl. itself) it should untap"


def test_fetched_land_stays_tapped_below_threshold():
    # 2 lands already out; fetched land is only the 3rd -> stays tapped.
    eng, p1 = _engine(field_lands=2)
    effect = EffectRegistry.create("search", dict(_fetch_spec_params()))
    effect.source = _source(p1)
    effect.apply(eng.rules.context)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    obj = eng.state.find_object(chosen)
    assert obj in eng.state.battlefield
    assert obj.tapped is True, "with only 3 lands it should stay tapped"


def test_plain_battlefield_tapped_search_unaffected_without_param():
    eng, p1 = _engine(field_lands=9)
    effect = EffectRegistry.create(
        "search", {"criteria": {"basic": True}, "destination": "battlefield_tapped", "count": 1}
    )
    effect.apply(eng.rules.context)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    obj = eng.state.find_object(chosen)
    assert obj.tapped is True, "no untap param -> Evolving Wilds behaviour is unchanged"
