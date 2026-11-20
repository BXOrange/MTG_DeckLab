"""ENG-67 -- keyword grants to cards outside the battlefield (RULE 113.6, 611.3).

"Each creature card in your graveyard has unearth {2}{B}." (Sedris, the Traitor King, Dregscape Sliver, Mishra, Tamer
of Mak Fawa, Solemn Doomguide) gives graveyard cards a real RULE 702.84a Unearth activated ability while the source is
on the battlefield; "Each instant and sorcery card in your hand has miracle {2}." (Lorehold, the Historian) feeds the
shared RULE 702.94a first-draw reveal. Encore, Jump-start and typecycling have no engine behaviour (BUG-75), so their
grants (Graywater's Fixer, Niv-Mizzet, Supreme, Homing Sliver) stay refused.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.static_rows.object_scope import zone_keyword_grant_specs
from tests.game.catalogue.cards.test_miracle_worker_deck import _card, _game, _lib
from tests.support.card_cache import get_cached_card


def _grave(engine, name, player="p1"):
    return _card(engine, name, player=player, zone=Zone.GRAVEYARD)


def _unearth_actions(engine, player, obj):
    return [a for a in engine.legal_actions(player)
            if a.get("type") == "activate_ability" and a["instance_id"] == obj.instance_id]


def _main(engine):
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


def _granted(obj):
    return [a for a in obj.granted_activated_abilities if getattr(a, "_zone_keyword_grant", False)]


# -- Sedris: "each creature card in your graveyard" --------------------------------------------------------------------


def test_sedris_grants_unearth_to_own_creature_cards_only():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    bolt = _grave(engine, "Lightning Bolt")
    theirs = _grave(engine, "Shambling Ghast", player="p2")
    _main(engine)
    p1.mana_pool.add_many({"B": 1, "G": 2})

    assert len(_granted(ghast)) == 1
    assert _granted(bolt) == [] and _granted(theirs) == []  # not a creature card / not "your" graveyard
    actions = _unearth_actions(engine, p1, ghast)
    assert [a["cost_label"] for a in actions] == ["{2}{B}"]
    assert _unearth_actions(engine, p1, bolt) == []


def test_granted_unearth_runs_end_to_end_haste_end_step_exile_and_exile_instead_of_dying():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    _main(engine)
    p1.mana_pool.add_many({"B": 1, "G": 2})
    index = _unearth_actions(engine, p1, ghast)[0]["ability_index"]
    engine.activate_ability(p1, ghast, index)
    engine.resolve_until_stable()

    assert ghast.zone == Zone.BATTLEFIELD and p1.mana_pool.total() == 0  # the grant's cost was really paid
    engine.recompute_continuous_effects()
    assert "haste" in ghast.granted_keywords or "haste" in ghast.temp_keywords
    assert any("Unearth" in dt.description for dt in engine.state.delayed_triggers)
    while engine.state.current_step != "end":
        engine.advance_step()
    engine.advance_step()
    engine.resolve_until_stable()
    assert ghast.zone == Zone.EXILE  # RULE 702.84a: exiled at the beginning of the next end step


def test_granted_unearth_exiles_instead_of_dying():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    _main(engine)
    p1.mana_pool.add_many({"B": 1, "G": 2})
    engine.activate_ability(p1, ghast, _unearth_actions(engine, p1, ghast)[0]["ability_index"])
    engine.resolve_until_stable()
    engine.rules.destroy(ghast)
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    assert ghast.zone == Zone.EXILE


def test_unearth_grant_ends_when_its_source_leaves():
    engine = _game()
    p1 = engine.state.players[0]
    sedris = _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    _main(engine)
    p1.mana_pool.add_many({"B": 1, "G": 2})
    assert _unearth_actions(engine, p1, ghast)

    engine.rules.exile(sedris)
    engine.recompute_continuous_effects()
    assert _granted(ghast) == []
    assert _unearth_actions(engine, p1, ghast) == []
    assert engine.state._zone_keyword_ability_cache == {}


def test_a_card_that_left_and_returned_to_the_graveyard_gets_a_fresh_grant():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    _main(engine)
    first = _granted(ghast)[0]
    engine.rules.exile(ghast)
    engine.rules.return_to_graveyard(ghast) if hasattr(engine.rules, "return_to_graveyard") else \
        p1.add_to_zone(ghast, Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    second = _granted(ghast)
    assert len(second) == 1 and second[0] is not first  # RULE 400.7: a new object, a new grant


def test_the_grant_does_not_duplicate_and_leaves_the_printed_unearth_alone():
    engine = _game()
    _card(engine, "Dregscape Sliver")
    twin = _grave(engine, "Dregscape Sliver")
    printed = len(twin.activated_abilities)
    for _ in range(3):
        engine.recompute_continuous_effects()
    assert len(_granted(twin)) == 1  # one per (grant, card), however often the layer pass re-runs
    assert len(twin.activated_abilities) == printed  # RULE 113.2c: the printed Unearth stays a separate ability


# -- Dregscape Sliver / Solemn Doomguide / Mishra: filters --------------------------------------------------------------


def test_dregscape_sliver_grants_unearth_two_to_sliver_creature_cards():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Dregscape Sliver")
    sliver = _grave(engine, "Sinew Sliver")
    other = _grave(engine, "Grizzly Bears")
    _main(engine)
    p1.mana_pool.add_many({"G": 2})
    assert len(_granted(sliver)) == 1 and _granted(other) == []
    assert [a["cost_label"] for a in _unearth_actions(engine, p1, sliver)] == ["{2}"]


def test_solemn_doomguide_grants_unearth_to_cleric_rogue_warrior_wizard_creatures():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Solemn Doomguide")
    cleric = _grave(engine, "Mother of Runes")
    rogue = _grave(engine, "Looter il-Kor")
    soldier = _grave(engine, "Elite Vanguard")
    spell = _grave(engine, "Lightning Bolt")
    _main(engine)
    assert len(_granted(cleric)) == len(_granted(rogue)) == 1
    assert _granted(soldier) == [] and _granted(spell) == []
    p1.mana_pool.add_many({"B": 1, "G": 1})
    assert [a["cost_label"] for a in _unearth_actions(engine, p1, cleric)] == ["{1}{B}"]


def test_mishra_grants_unearth_to_artifact_cards_and_ward_to_permanents():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Mishra, Tamer of Mak Fawa")
    retriever = _grave(engine, "Myr Retriever")
    sol = _grave(engine, "Sol Ring")
    ghast = _grave(engine, "Shambling Ghast")
    battlefield_ring = _card(engine, "Sol Ring")
    _main(engine)
    assert len(_granted(retriever)) == len(_granted(sol)) == 1 and _granted(ghast) == []
    assert battlefield_ring.granted_ward_cost == "sacrifice a permanent"  # the card's other clause
    p1.mana_pool.add_many({"B": 1, "R": 1, "G": 1})
    engine.activate_ability(p1, retriever, _unearth_actions(engine, p1, retriever)[0]["ability_index"])
    engine.resolve_until_stable()
    assert retriever.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("source,victim,mana", [
    ("Dregscape Sliver", "Sinew Sliver", {"G": 2}),
    ("Solemn Doomguide", "Looter il-Kor", {"B": 1, "G": 1}),
    ("Mishra, Tamer of Mak Fawa", "Sol Ring", {"B": 1, "R": 1, "G": 1}),
])
def test_each_claimed_graveyard_grant_card_unearths_a_matching_card(source, victim, mana):
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, source)
    obj = _grave(engine, victim)
    _main(engine)
    p1.mana_pool.add_many(mana)
    engine.activate_ability(p1, obj, _unearth_actions(engine, p1, obj)[0]["ability_index"])
    engine.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and p1.mana_pool.total() == 0


# -- clone / undo --------------------------------------------------------------------------------------------------------


def test_unearth_grant_survives_clone_and_is_usable_on_the_restored_state():
    engine = _game()
    p1 = engine.state.players[0]
    _card(engine, "Sedris, the Traitor King")
    ghast = _grave(engine, "Shambling Ghast")
    _main(engine)
    restored = GameEngine(engine.state.clone())
    restored.state.current_step = "main1"
    restored.recompute_continuous_effects()
    twin = restored.state.find_object(ghast.instance_id)
    assert twin is not ghast and len(_granted(twin)) == 1
    restored_p1 = restored.state.player_by_id("p1")
    restored_p1.mana_pool.add_many({"B": 1, "G": 2})
    restored.activate_ability(restored_p1, twin, _unearth_actions(restored, restored_p1, twin)[0]["ability_index"])
    restored.resolve_until_stable()
    assert twin.zone == Zone.BATTLEFIELD and ghast.zone == Zone.GRAVEYARD  # the original is untouched


# -- Lorehold: miracle in hand -------------------------------------------------------------------------------------------


def _lorehold_game():
    engine = _game()
    player = engine.state.players[0]
    lorehold = _card(engine, "Lorehold, the Historian")
    return engine, player, lorehold


def _reveal_and_cast(engine, player, spell):
    engine.rules.draw(player)
    assert engine.state.pending_choice["kind"] == "miracle_reveal"
    engine.rules.resolve_choice("reveal")
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    assert engine.state.resolution_play_choice["miracle"]
    engine.state.current_step = "main1"
    player.mana_pool.add_many({"G": 2})
    engine.play_resolution_card(player, spell, alt_cost=True)
    assert player.mana_pool.total() == 0  # exactly {2}, not Divination's {2}{U}


def test_lorehold_miracle_casts_a_drawn_sorcery_for_two():
    engine, player, _ = _lorehold_game()
    spell = _card(engine, "Divination", zone=Zone.LIBRARY)
    _reveal_and_cast(engine, player, spell)
    assert spell.zone == Zone.STACK
    engine.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD


def test_lorehold_miracle_ignores_creatures_opponents_hands_and_later_draws():
    engine, player, _ = _lorehold_game()
    _card(engine, "Shambling Ghast", zone=Zone.LIBRARY)
    engine.rules.draw(player)
    assert not engine.state.pending_choice  # a creature card has no miracle

    other = engine.state.players[1]
    _card(engine, "Divination", player="p2", zone=Zone.LIBRARY)
    engine.rules.draw(other)
    assert not engine.state.pending_choice  # "your hand" only

    _card(engine, "Divination", zone=Zone.LIBRARY)
    engine.rules.draw(player)
    assert not engine.state.pending_choice  # not the first card drawn this turn


def test_lorehold_miracle_ends_with_its_source():
    engine, player, lorehold = _lorehold_game()
    engine.rules.exile(lorehold)
    _card(engine, "Divination", zone=Zone.LIBRARY)
    engine.rules.draw(player)
    assert not engine.state.pending_choice


def test_molecule_man_grants_miracle_zero_to_nonland_cards_only():
    engine = _game()
    player = engine.state.players[0]
    _card(engine, "Molecule Man")
    spell = _card(engine, "Shambling Ghast", zone=Zone.LIBRARY)
    engine.rules.draw(player)
    assert engine.state.pending_choice["kind"] == "miracle_reveal"
    engine.rules.resolve_choice("reveal")
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.state.current_step = "main1"
    engine.play_resolution_card(player, spell, alt_cost=True)  # miracle {0}: no mana paid
    assert spell.zone == Zone.STACK
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD

    _card(engine, "Forest", zone=Zone.LIBRARY)
    engine.state.cards_drawn_this_turn.clear()
    engine.rules.draw(player)
    assert not engine.state.pending_choice  # a land is never cast


# -- Lorehold's other clause ----------------------------------------------------------------------------------------------


def test_lorehold_loots_at_each_opponents_upkeep():
    engine, player, _ = _lorehold_game()
    spare = _card(engine, "Shambling Ghast", zone=Zone.HAND)
    top = _lib(engine, "Top Card", "Creature")
    engine.state.active_player_index = 1
    engine.state.current_step = "untap"
    while engine.state.current_step != "upkeep":
        engine.advance_step()
    engine.resolve_until_stable()
    for _ in range(4):
        if engine.state.pending_choice is None:
            break
        options = [str(o["id"]) for o in engine.state.pending_choice.get("options", [])]
        engine.resolve_pending_choice(next((o for o in options if o != "decline"), "decline"))
        engine.resolve_until_stable()
    assert spare.zone == Zone.GRAVEYARD and top.zone == Zone.HAND  # may discard; if you do, draw


# -- the parser side ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Dregscape Sliver", "Sedris, the Traitor King", "Mishra, Tamer of Mak Fawa", "Solemn Doomguide",
    "Lorehold, the Historian", "Molecule Man",
])
def test_claimed_cards_are_modeled_by_the_parser(name):
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = get_cached_card(name)
    result = parse_oracle(card)
    assert result.modeled


@pytest.mark.parametrize("name", ["Graywater's Fixer", "Niv-Mizzet, Supreme", "Homing Sliver"])
def test_grants_of_keywords_without_engine_behaviour_stay_refused(name):
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    assert not parse_oracle(get_cached_card(name)).modeled


def test_zone_keyword_grant_specs_vocabulary():
    spec = zone_keyword_grant_specs("sliver creature", None, "unearth", "graveyard", "{2}")[0]
    assert spec.type == "grant_zone_keyword" and spec.params["card_types"] == ["creature"]
    assert spec.params["subtypes"] == ["Sliver"] and spec.params["cost"] == "{2}"
    assert zone_keyword_grant_specs("creature", None, "unearth", "hand", "{2}") is None  # wrong zone for the keyword
    assert zone_keyword_grant_specs("creature", None, "encore", "graveyard", "{2}") is None  # no engine behaviour
    nonland = zone_keyword_grant_specs("nonland", None, "miracle", "hand", "{0}")[0]
    assert nonland.type == "grant_miracle" and nonland.params == {"cost": "{0}"}
    assert zone_keyword_grant_specs("nonland", None, "unearth", "graveyard", "{2}") is None
    assert zone_keyword_grant_specs("flurb", None, "unearth", "graveyard", "{2}") is None  # unknown word
