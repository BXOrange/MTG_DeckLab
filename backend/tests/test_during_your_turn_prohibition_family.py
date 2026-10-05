"""ENG-28 — RULE 613.6's "During your turn, …" gate reaching a
`cast_prohibition`/`activation_prohibition` static.

`continuous.cast_prohibited` never consulted `active_if` at all (a card-text
gate silently dropped, unlike `activation_prohibited`'s own path through
`affected_objects`/`group_selector_objects`, which already checked it); the
`cast_prohibition` `EffectRegistry` factory didn't even thread the param
through to the `StaticAbility` in the first place. Grand Abolisher/Myrel,
Shield of Argive need both halves fixed at once (one clause, one `cast_
prohibition` + one `activation_prohibition` spec, both carrying the same
gate); Linvala, Keeper of Silence exercises the *ungated*, opponent-scoped
`activation_prohibition` shape the parser gained alongside it
(`affects="opponents_permanents"`, `card_type="creature"`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _named(name):
    """The real cached card, parsed+bound through `specs_for`'s oracle-text
    fallback (Grand Abolisher/Myrel/Linvala are all MODELED, not
    hand-authored — see `card_registry.specs_for`)."""
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


# ---------------------------------------------------------------------------
# Grand Abolisher — cast_prohibition + activation_prohibition, both gated
# ---------------------------------------------------------------------------


def test_grand_abolisher_blocks_opponent_casting_only_during_your_turn():
    engine, state, p1, p2 = _engine()
    abolisher = GameObject(_named("Grand Abolisher"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(abolisher)
    _bf(state, None, obj=abolisher)
    engine.state.current_step = "main1"

    spell = GameObject(_card("Lightning Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(spell, Zone.HAND)
    p2.mana_pool.add("R", 5)

    state.active_player_index = 0  # p1's (the Abolisher controller's) turn
    assert engine.can_cast(p2, spell) is False

    state.active_player_index = 1  # p2's own turn — the gate is off
    assert engine.can_cast(p2, spell) is True


def test_grand_abolisher_never_touches_its_own_controllers_casting():
    engine, state, p1, p2 = _engine()
    abolisher = GameObject(_named("Grand Abolisher"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(abolisher)
    _bf(state, None, obj=abolisher)
    engine.state.current_step = "main1"

    spell = GameObject(_card("Lightning Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("R", 5)

    state.active_player_index = 0  # p1's own turn
    assert engine.can_cast(p1, spell) is True


def test_grand_abolisher_blocks_opponent_activating_artifact_creature_or_enchantment_only_during_your_turn():
    engine, state, p1, p2 = _engine()
    abolisher = GameObject(_named("Grand Abolisher"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(abolisher)
    _bf(state, None, obj=abolisher)

    elves = _named("Llanowar Elves")
    opp_dork = GameObject(elves, owner_id="p2", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(opp_dork)
    _bf(state, None, obj=opp_dork)

    # A mana ability isn't in `source.activated_abilities` (it's derived
    # fresh by `mana_abilities_for`), so `can_activate` refuses it on that
    # unrelated ground regardless of any prohibition — `tap_for_mana` is the
    # real consult point (`continuous.activation_prohibited(...,
    # is_mana_ability=True)`), and raises rather than returning `False`.
    state.active_player_index = 0  # p1's (the Abolisher controller's) turn
    with pytest.raises(ValueError):
        engine.tap_for_mana(p2, opp_dork)
    assert opp_dork.tapped is False  # refused before payment, not left half-paid

    state.active_player_index = 1  # p2's own turn — the gate is off
    produced = engine.tap_for_mana(p2, opp_dork)
    assert produced.get("G") == 1


# ---------------------------------------------------------------------------
# Linvala, Keeper of Silence — the ungated, opponent-scoped shape the same
# parser handler now also recognises (`_ACTIVATION_PROHIBITION_OPPONENTS_RE`)
# ---------------------------------------------------------------------------


def test_linvala_blocks_opponents_creature_abilities_regardless_of_whose_turn_it_is():
    engine, state, p1, p2 = _engine()
    linvala = GameObject(_named("Linvala, Keeper of Silence"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(linvala)
    _bf(state, None, obj=linvala)

    elves = _named("Llanowar Elves")
    opp_dork = GameObject(elves, owner_id="p2", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(opp_dork)
    _bf(state, None, obj=opp_dork)

    state.active_player_index = 1  # p2's own turn — Linvala's lock still holds
    with pytest.raises(ValueError):
        engine.tap_for_mana(p2, opp_dork)

    state.active_player_index = 0
    with pytest.raises(ValueError):
        engine.tap_for_mana(p2, opp_dork)


def test_linvala_never_touches_its_own_controllers_creatures():
    engine, state, p1, p2 = _engine()
    linvala = GameObject(_named("Linvala, Keeper of Silence"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(linvala)
    _bf(state, None, obj=linvala)

    elves = _named("Llanowar Elves")
    my_dork = GameObject(elves, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(my_dork)
    _bf(state, None, obj=my_dork)

    produced = engine.tap_for_mana(p1, my_dork)
    assert produced.get("G") == 1
