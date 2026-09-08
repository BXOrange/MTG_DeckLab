"""MEC-12 (cEDH staples 2) — Necrotic Ooze's "as long as this creature is
on the battlefield, it has all activated abilities of all creature cards
in all graveyards."

New primitive: `grant_borrowed_activated_ability`'s third `source_mode`,
``"all_graveyards"`` — the ``exiled_with``/``group``/``chosen_permanent``
family (MEC-21/MEC-26) widened to read every player's live `Player.
graveyard` list directly, reusing the existing per-(grantee, donor,
ability-index) caching and RULE 113.7c source-redirect unchanged.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _necrotic_ooze():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card("Necrotic Ooze")


def red_pinger(name="Red Guy"):
    return Card(
        id=name, name=name, type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        oracle_text="{R}: This creature deals 1 damage to any target.",
    )


def test_necrotic_ooze_borrows_abilities_from_any_graveyard():
    eng = make_engine()
    ooze = put(eng.state, _necrotic_ooze())
    own_graveyard_donor = put(eng.state, red_pinger("Own Guy"), controller="p1", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p1").graveyard.append(own_graveyard_donor)
    opp_graveyard_donor = put(eng.state, red_pinger("Foe Guy"), controller="p2", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p2").graveyard.append(opp_graveyard_donor)

    eng.recompute_continuous_effects()

    assert len(ooze.granted_activated_abilities) == 2
    assert all(a.source is ooze for a in ooze.granted_activated_abilities)


def test_necrotic_ooze_ignores_noncreature_graveyard_cards():
    eng = make_engine()
    ooze = put(eng.state, _necrotic_ooze())
    instant = Card(
        id="Bolt", name="Bolt", type_line="Instant",
        is_instant=True, mana_cost_string="{R}",
        oracle_text="Deal 3 damage to any target.",
    )
    noncreature = put(eng.state, instant, controller="p1", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p1").graveyard.append(noncreature)

    eng.recompute_continuous_effects()

    assert ooze.granted_activated_abilities == []


def test_necrotic_ooze_grants_nothing_when_not_on_battlefield():
    eng = make_engine()
    ooze = put(eng.state, _necrotic_ooze(), zone=Zone.GRAVEYARD)
    donor = put(eng.state, red_pinger(), controller="p1", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p1").graveyard.extend([ooze, donor])

    eng.recompute_continuous_effects()

    assert ooze.granted_activated_abilities == []
