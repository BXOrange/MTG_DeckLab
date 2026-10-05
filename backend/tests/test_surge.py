"""RULE 702.117 Surge — an alternative cost payable only after another spell was cast this turn.

Covers the engine mechanic (the offer, its gate, the cost it charges, the `surge_cost_paid` flag)
and the oracle clauses that read it: Reckless Bushwhacker's and Tyrant of Valakut's ETB
intervening-if, Crush of Tentacles' resolving "if this spell's surge cost was paid".
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

BUSHWHACKER_TEXT = (
    "Surge {1}{R}\nHaste\nWhen this creature enters, if its surge cost was paid, "
    "other creatures you control get +1/+0 and gain haste until end of turn."
)
CRUSH_TEXT = (
    "Surge {3}{U}{U}\nReturn all nonland permanents to their owners' hands. "
    "If this spell's surge cost was paid, create an 8/8 blue Octopus creature token."
)


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state, engine.state.active_player


def _hand(player, card: Card) -> GameObject:
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def _bushwhacker() -> Card:
    return Card(
        id="rb", name="Reckless Bushwhacker", type_line="Creature — Goblin Warrior Ally",
        mana_cost_string="{2}{R}", converted_mana_cost=3, is_creature=True, power=3, toughness=3,
        keywords=["Surge", "Haste"], oracle_text=BUSHWHACKER_TEXT,
    )


def _cheap_spell() -> Card:
    return Card(
        id="bolt", name="Spark", type_line="Instant", mana_cost_string="{R}", converted_mana_cost=1,
        is_instant=True, oracle_text="Spark deals 1 damage to any target.",
    )


def _cast_another_spell(engine, state, player) -> None:
    """Cast (and resolve) a real spell — `spells_cast_this_turn` is derived from the event log."""
    spark = _hand(player, _cheap_spell())
    player.mana_pool.add_many({"R": 1})
    engine.cast_spell(player, spark, targets=[state.player_by_id("p2")])
    engine.resolve_until_stable()


def _ally(state, player) -> GameObject:
    obj = GameObject(
        Card(id="ally", name="Ally", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id=player.id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player.id
    state.add_to_battlefield(obj)
    return obj


def test_surge_is_not_offered_before_another_spell_is_cast():
    engine, state, player = _game()
    spell = _hand(player, _bushwhacker())
    player.mana_pool.add_many({"R": 2})
    assert spell.parametric_keywords["surge"] == {"cost": "{1}{R}"}
    assert not engine.can_cast(player, spell, surge=True)
    assert not any(a.get("surge") for a in engine.legal_actions(player))


def test_surge_cost_is_offered_and_charged_after_another_spell():
    engine, state, player = _game()
    spell = _hand(player, _bushwhacker())
    ally = _ally(state, player)
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"R": 2})  # surge {1}{R}; the printed cost {2}{R} is out of reach
    assert not engine.can_cast(player, spell)
    assert engine.can_cast(player, spell, surge=True)
    offers = [a for a in engine.legal_actions(player) if a.get("surge")]
    assert [a["instance_id"] for a in offers] == [spell.instance_id]
    assert offers[0]["surge_cost_label"] == "{1}{R}"

    engine.cast_spell(player, spell, surge=True)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert spell.zone == Zone.BATTLEFIELD
    assert spell.surge_cost_paid
    # "other creatures you control get +1/+0 and gain haste" — the Ally, not Bushwhacker itself.
    assert (ally.power, ally.toughness) == (3, 2)
    assert "haste" in ally.granted_keywords
    assert spell.power == 3


def test_a_plain_cast_does_not_count_as_surged():
    engine, state, player = _game()
    spell = _hand(player, _bushwhacker())
    ally = _ally(state, player)
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"R": 3})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert spell.zone == Zone.BATTLEFIELD and not spell.surge_cost_paid
    assert ally.power == 2  # the rider never fired


def test_surge_needs_a_spell_cast_this_turn_not_one_cast_last_turn():
    engine, state, player = _game()
    spell = _hand(player, _bushwhacker())
    player.mana_pool.add_many({"R": 3})
    assert not engine.can_cast(player, spell, surge=True)
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"R": 2})
    assert engine.can_cast(player, spell, surge=True)


def test_surge_rider_on_a_spell_gates_its_extra_effect():
    engine, state, player = _game()
    crush = _hand(player, Card(
        id="crush", name="Crush of Tentacles", type_line="Sorcery", mana_cost_string="{3}{U}{U}",
        converted_mana_cost=5, is_sorcery=True, keywords=["Surge"], oracle_text=CRUSH_TEXT,
    ))
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"U": 5})
    engine.cast_spell(player, crush, surge=True)
    engine.resolve_until_stable()
    octopi = [o for o in state.battlefield if o.name == "Octopus"]
    assert len(octopi) == 1


def test_crush_of_tentacles_without_surge_makes_no_octopus():
    engine, state, player = _game()
    crush = _hand(player, Card(
        id="crush", name="Crush of Tentacles", type_line="Sorcery", mana_cost_string="{3}{U}{U}",
        converted_mana_cost=5, is_sorcery=True, keywords=["Surge"], oracle_text=CRUSH_TEXT,
    ))
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"U": 5})
    engine.cast_spell(player, crush)  # the printed {3}{U}{U}, not the surge cost
    engine.resolve_until_stable()
    assert not [o for o in state.battlefield if o.name == "Octopus"]


def test_the_session_round_trips_the_surge_offer():
    """The wire path: the `surge` flag on the offered action is what makes the cast a surge cast."""
    from mtg_analyzer.services.game_session import GameSession

    engine, state, player = _game()
    spell = _hand(player, _bushwhacker())
    _cast_another_spell(engine, state, player)
    player.mana_pool.add_many({"R": 2})
    session = GameSession(engine)
    offer = next(a for a in engine.legal_actions(player) if a.get("surge"))
    session.apply_action(offer)
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and spell.surge_cost_paid


def _tyrant() -> Card:
    return Card(
        id="tov", name="Tyrant of Valakut", type_line="Creature — Dragon", mana_cost_string="{4}{R}{R}",
        converted_mana_cost=6, is_creature=True, power=5, toughness=4, keywords=["Surge", "Flying"],
        oracle_text=(
            "Surge {3}{R}{R}\nFlying\nWhen this creature enters, if its surge cost was paid, "
            "it deals 3 damage to any target."
        ),
    )


def test_tyrant_of_valakut_damage_only_when_surged():
    engine, state, player = _game()
    opponent = state.player_by_id("p2")
    plain = _hand(player, _tyrant())
    player.mana_pool.add_many({"R": 6})
    engine.cast_spell(player, plain)
    engine.resolve_until_stable()
    # RULE 603.4: the intervening-if fails, so the trigger never goes on the stack to ask for a target.
    assert plain.zone == Zone.BATTLEFIELD and state.pending_choice is None and opponent.life == 40

    engine2, state2, player2 = _game()
    opponent2 = state2.player_by_id("p2")
    _cast_another_spell(engine2, state2, player2)
    life_after_spark = opponent2.life
    surged = _hand(player2, _tyrant())
    player2.mana_pool.add_many({"R": 5})
    engine2.cast_spell(player2, surged, surge=True)
    engine2.resolve_until_stable()
    assert state2.pending_choice["kind"] == "trigger_target"
    engine2.resolve_pending_choice("p2")
    engine2.resolve_until_stable()
    assert surged.surge_cost_paid and opponent2.life == life_after_spark - 3
