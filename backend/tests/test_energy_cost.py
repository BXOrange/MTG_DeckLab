"""RULE 122 — Energy counters, the "Pay {E}" activated-ability cost side.

`Player.counters["energy"]` is the same generic per-player counter dict
"rad"/"poison"/"experience" already use (`RulesEngine.add_player_counters`,
see `test_rad_counters.py`); "you get {E} (an energy counter)" already works
through that existing primitive with no new plumbing. What was missing —
and is covered here — is the *cost* side: `game/costs.py`'s
`ActivationCost.pay_energy`, parsed from `{E}` pips (`_parse_text`'s brace
loop previously silently discarded them), and its actual charge/legality
check in `GameEngine._can_pay_activation_cost`/`_pay_activation_cost`.

The much larger "may pay {E}{E}. If you do, <effect>" resolve-time optional-
payment grammar (Aether Chaser/Guide of Souls-shaped triggered abilities)
is a separate, unmodeled shape — out of scope here; see
`backend/ToDo_Backend.md`.
"""

from __future__ import annotations

from mtg_analyzer.game.effects import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def test_activated_ability_cannot_be_paid_without_enough_energy():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    source = GameObject(
        Card(id="Aethersphere Harvester", name="Aethersphere Harvester", type_line="Vehicle"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=parse_activation_cost("Pay {E}: Draw a card."), source=source,
    )
    source.activated_abilities.append(ability)

    assert p1.counters.get("energy", 0) == 0
    assert not eng.can_activate(p1, source, ability)


def test_activated_ability_spends_energy_counters_when_paid():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    source = GameObject(
        Card(id="Aethersphere Harvester", name="Aethersphere Harvester", type_line="Vehicle"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=parse_activation_cost("Pay {E}{E}{E}{E}: Draw a card."), source=source,
    )
    source.activated_abilities.append(ability)

    eng.rules.add_player_counters(p1, 4, "energy")
    assert eng.can_activate(p1, source, ability)
    eng.activate_ability(p1, source)
    assert p1.counters.get("energy", 0) == 0


def test_activated_ability_leaves_excess_energy_unspent():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    source = GameObject(
        Card(id="Aether Theorist", name="Aether Theorist", type_line="Creature — Human Wizard",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=parse_activation_cost("{T}, Pay {E}: Scry 1."), source=source,
    )
    source.activated_abilities.append(ability)

    eng.rules.add_player_counters(p1, 3, "energy")
    eng.activate_ability(p1, source)
    assert p1.counters.get("energy", 0) == 2
    assert source.tapped is True


def test_pay_fifty_energy_matches_aetherflux_conduit():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    source = GameObject(
        Card(id="Aetherflux Conduit", name="Aetherflux Conduit", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    ability = ActivatedAbility(
        effects=[DrawCardEffect(7, player=p1)],
        cost=parse_activation_cost("{T}, Pay fifty {E}: Draw seven cards."), source=source,
    )
    source.activated_abilities.append(ability)

    eng.rules.add_player_counters(p1, 49, "energy")
    assert not eng.can_activate(p1, source, ability)
    eng.rules.add_player_counters(p1, 1, "energy")
    assert eng.can_activate(p1, source, ability)
    eng.activate_ability(p1, source)
    assert p1.counters.get("energy", 0) == 0
