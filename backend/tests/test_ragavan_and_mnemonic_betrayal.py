"""Tests for the two BACKLOG.md-flagged "impulsive draw" extensions:
Ragavan, Nimble Pilferer (exile from *the damaged player's* library, not its
own controller's) and Mnemonic Betrayal (exile a whole graveyard, "any type"
mana-wildcard). Both build on the shared `ImpulsiveDrawEffect`/
`RulesEngine.exile_with_play_permission` mechanism `test_impulsive_draw.py`
covers for the Light Up the Stage-shaped single-player case.

Engine side: `game/effects.py`'s `GraveyardImpulsiveCastEffect`/
`ReturnRemainingExiledEffect`, `RulesEngine._collect_impulsive_draw_triggers`/
`exile_graveyard_with_cast_permission`/`_grant_temp_play_permission`,
`GameState.temp_play_permission_player`/`mana_wildcard_permission`,
`ManaPool`'s ``wildcard`` param, `game/ability_catalogue.py`'s
`AbilitySpec.impulsive_draw_on_combat_damage` marker.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0,
    )


def _battlefield_obj(state, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _stock_library(player, cards):
    player.library.clear()
    for card in cards:
        player.library.append(GameObject(card, owner_id=player.id, zone=Zone.LIBRARY))


def _stock_graveyard(player, cards):
    player.graveyard.clear()
    for card in cards:
        player.graveyard.append(GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD))


# ---------------------------------------------------------------------------
# Ragavan, Nimble Pilferer
# ---------------------------------------------------------------------------


def _ragavan(state, controller="p1"):
    card = _card(
        "Ragavan, Nimble Pilferer", "Legendary Creature — Monkey Pirate",
        is_creature=True, power=2, toughness=1,
    )
    return _battlefield_obj(state, card, controller)


def test_ragavan_registered_and_binds_treasure_plus_marker():
    eng = _engine("p1", "p2")
    ragavan = _ragavan(eng.state)
    assert any(
        getattr(e, "token_name", None) == "Treasure" for e in ragavan.triggered_abilities[0].effects
    )
    assert ragavan.impulsive_draw_on_combat_damage == {"count": 1}


def test_ragavan_combat_damage_creates_treasure_and_exiles_from_damaged_players_library():
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    ragavan = _ragavan(eng.state, controller="p1")
    _stock_library(p2, [
        _card("Filler", "Creature", is_creature=True),
        _card("Bolt", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True),
    ])
    top_of_p2_library = p2.library[-1]
    assert top_of_p2_library.name == "Bolt"

    eng.rules.deal_damage(p2, 2, source=ragavan, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 2  # Treasure creation + the exile/cast-permission grant
    eng.resolve_until_stable()

    # A Treasure token for Ragavan's controller (p1), not the damaged player.
    treasures = [o for o in eng.state.battlefield if o.name == "Treasure" and o.controller_id == "p1"]
    assert len(treasures) == 1

    # The top card of p2's library (not p1's, and not p2's whole library) was exiled.
    assert top_of_p2_library.zone == Zone.EXILE
    assert top_of_p2_library in p2.exile
    assert eng.state.temp_play_permission_player[top_of_p2_library.instance_id] == "p1"


def test_ragavan_permission_belongs_to_its_controller_not_the_damaged_player():
    eng = _engine("p1", "p2")
    eng.state.current_step = "main1"
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    ragavan = _ragavan(eng.state, controller="p1")
    _stock_library(p2, [_card("Bolt", "Instant", mana_cost_string="{R}",
                               converted_mana_cost=1, is_instant=True)])

    eng.rules.deal_damage(p2, 2, source=ragavan, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    bolt = next(o for o in p2.exile if o.name == "Bolt")

    p1.mana_pool.add("R", 1)
    p2.mana_pool.add("R", 1)
    assert eng.can_cast(p1, bolt) is True   # Ragavan's controller may cast it
    assert eng.can_cast(p2, bolt) is False  # the damaged player (its owner) may not


def test_ragavan_permission_is_this_turn_only_not_next_turn():
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    ragavan = _ragavan(eng.state, controller="p1")
    _stock_library(p2, [_card("Bolt", "Instant", is_instant=True)])

    eng.rules.deal_damage(p2, 2, source=ragavan, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    bolt = next(o for o in p2.exile if o.name == "Bolt")
    assert bolt.instance_id in eng.state.temp_play_permissions

    # Unlike Light Up the Stage (survives through this turn's own cleanup
    # too), Ragavan's own "until end of turn" lapses at *this* cleanup.
    eng.state.current_step = "cleanup"
    eng._step_cleanup()
    assert bolt.instance_id not in eng.state.temp_play_permissions
    assert bolt.instance_id not in eng.state.temp_play_permission_player


def test_ragavan_does_not_trigger_on_noncombat_damage():
    eng = _engine("p1", "p2")
    p2 = eng.state.player_by_id("p2")
    ragavan = _ragavan(eng.state, controller="p1")
    _stock_library(p2, [_card("Bolt", "Instant", is_instant=True)])

    eng.rules.deal_damage(p2, 2, source=ragavan, combat=False)
    assert eng.rules.put_triggers_on_stack() == 0
    assert p2.library, "nothing was exiled off noncombat damage"


def test_ragavan_does_not_trigger_when_damaging_a_creature():
    eng = _engine("p1", "p2")
    state = eng.state
    ragavan = _ragavan(state, controller="p1")
    victim = _battlefield_obj(state, _card("Victim", "Creature", is_creature=True,
                                            power=2, toughness=2), controller="p2")

    eng.rules.deal_damage(victim, 2, source=ragavan, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# Mnemonic Betrayal
# ---------------------------------------------------------------------------


def _cast_mnemonic_betrayal(eng, caster):
    card = _card(
        "Mnemonic Betrayal", "Sorcery", mana_cost_string="{1}{U}{B}",
        converted_mana_cost=3, is_sorcery=True,
    )
    obj = GameObject(card, owner_id=caster.id, zone=Zone.HAND)
    from mtg_analyzer.game import ability_catalogue as ac

    attach_to_object(obj, ac.specs_for(card))
    caster.add_to_zone(obj, Zone.HAND)
    caster.mana_pool.add_many({"U": 1, "B": 1, "C": 1})
    eng.state.active_player_index = eng.state.players.index(caster)
    eng.state.current_step = "main1"
    eng.cast_spell(caster, obj)
    eng.resolve_until_stable()
    return obj


def test_mnemonic_betrayal_registered():
    from mtg_analyzer.game import ability_catalogue as ac

    assert ac.is_registered("Mnemonic Betrayal")


def test_mnemonic_betrayal_exiles_only_opponents_graveyards_with_cast_permission():
    eng = _engine("p1", "p2", "p3")
    p1, p2, p3 = (eng.state.player_by_id(pid) for pid in ("p1", "p2", "p3"))
    _stock_graveyard(p1, [_card("MyOwnCard", "Creature", is_creature=True)])
    _stock_graveyard(p2, [_card("Opp1Card", "Instant", mana_cost_string="{B}",
                                converted_mana_cost=1, is_instant=True)])
    _stock_graveyard(p3, [_card("Opp2Card", "Sorcery", mana_cost_string="{G}",
                                converted_mana_cost=1, is_sorcery=True)])

    _cast_mnemonic_betrayal(eng, p1)

    # p1's own graveyard is untouched.
    assert any(o.name == "MyOwnCard" for o in p1.graveyard)
    # Both opponents' graveyards were exiled into their own exile zones.
    opp1 = next(o for o in p2.exile if o.name == "Opp1Card")
    opp2 = next(o for o in p3.exile if o.name == "Opp2Card")
    assert not p2.graveyard and not p3.graveyard
    for exiled in (opp1, opp2):
        assert eng.state.temp_play_permission_player[exiled.instance_id] == "p1"
        assert eng.state.mana_wildcard_permission[exiled.instance_id] == "type"

    # Mnemonic Betrayal exiled itself instead of going to the graveyard.
    assert not any(o.name == "Mnemonic Betrayal" for o in p1.graveyard)
    assert any(o.name == "Mnemonic Betrayal" for o in p1.exile)


def test_mnemonic_betrayal_grants_any_type_mana_wildcard_for_casting():
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _stock_graveyard(p2, [_card("BlackSpell", "Instant", mana_cost_string="{B}",
                                converted_mana_cost=1, is_instant=True)])

    _cast_mnemonic_betrayal(eng, p1)
    black_spell = next(o for o in p2.exile if o.name == "BlackSpell")

    # p1 has no black mana at all, only green — the wildcard grant should
    # still let {B} be paid with it.
    p1.mana_pool.add("G", 1)
    assert eng.can_cast(p1, black_spell) is True
    eng.cast_spell(p1, black_spell)
    assert p1.mana_pool.pool["G"] == 0, "the green mana paid the {B} pip"


def test_mnemonic_betrayal_returns_leftover_exiled_cards_at_the_next_end_step():
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _stock_graveyard(p2, [
        _card("LeftoverA", "Creature", is_creature=True),
        _card("LeftoverB", "Creature", is_creature=True),
    ])

    _cast_mnemonic_betrayal(eng, p1)
    assert len(p2.exile) == 2, "both cards were exiled with cast permission"
    assert len(eng.state.delayed_triggers) == 1

    # Walk steps until the end step fires the delayed cleanup.
    for _ in range(16):
        ran = eng.advance_step()
        if ran and ran[1] == "end":
            break

    assert not eng.state.delayed_triggers
    assert {o.name for o in p2.graveyard} == {"LeftoverA", "LeftoverB"}
    assert not any(o.name in ("LeftoverA", "LeftoverB") for o in p2.exile)


def test_mnemonic_betrayal_is_unmodeled_before_this_change_stays_modeled_now():
    """Sanity check the oracle text itself still parses to what this hand-
    authored registration matches — guards against the two silently
    drifting apart (the catalogue registry always wins over the parser for
    a registered name, so nothing enforces this automatically)."""
    card = _card(
        "Mnemonic Betrayal", "Sorcery",
        is_sorcery=True, mana_cost_string="{1}{U}{B}", converted_mana_cost=3,
        oracle_text=(
            "Exile all opponents' graveyards. You may cast spells from among "
            "those cards this turn, and mana of any type can be spent to cast "
            "them. At the beginning of the next end step, if any of those "
            "cards remain exiled, return them to their owners' graveyards.\n"
            "Exile Mnemonic Betrayal."
        ),
    )
    result = parse_oracle(card)
    assert not result.modeled  # still unmodeled by the *parser* front-end
    assert not any(u == "exile ~." for u in result.unclaimed)
