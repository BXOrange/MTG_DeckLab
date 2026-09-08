"""PAR-25 — the death/graveyard keyword family that was parser-recognized
but had zero engine implementation.

Covered here so far:

* **Undying** (702.93) / **Persist** (702.79) — "When this creature dies,
  if it had no +1/+1 (undying) / -1/-1 (persist) counters on it, return it
  to the battlefield under its owner's control with such a counter on it."
  Collected in `RulesEngine._collect_undying_persist_triggers` off the
  `combat._obj_keywords` union so a *granted* instance works too.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _creature(name, keywords=None, power=2, toughness=2, oracle_text="",
              type_line="Creature — Wolf"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _kill(eng, obj):
    eng.rules.destroy(obj)
    eng.rules.check_state_based_actions()
    eng.resolve_until_stable()


def test_undying_returns_with_a_plus_one_counter():
    eng = _engine()
    state = eng.state
    wolf = _put(state, _creature("Young Wolf", keywords=["Undying"], power=1, toughness=1))
    _kill(eng, wolf)

    assert wolf.zone == Zone.BATTLEFIELD
    assert wolf.counters.get("+1/+1", 0) == 1
    continuous.recompute(state)
    assert (wolf.power, wolf.toughness) == (2, 2)


def test_undying_does_not_return_a_creature_that_died_with_a_counter():
    eng = _engine()
    state = eng.state
    wolf = _put(state, _creature("Young Wolf", keywords=["Undying"], power=1, toughness=1))
    wolf.counters["+1/+1"] = 1  # already has one → undying does nothing
    _kill(eng, wolf)

    assert wolf.zone == Zone.GRAVEYARD
    assert wolf in state.player_by_id("p1").graveyard


def test_persist_returns_with_a_minus_one_counter():
    eng = _engine()
    state = eng.state
    redcap = _put(state, _creature("Murderous Redcap", keywords=["Persist"],
                                   power=2, toughness=2))
    _kill(eng, redcap)

    assert redcap.zone == Zone.BATTLEFIELD
    assert redcap.counters.get("-1/-1", 0) == 1
    continuous.recompute(state)
    assert (redcap.power, redcap.toughness) == (1, 1)


def test_persist_creature_dies_for_good_the_second_time():
    eng = _engine()
    state = eng.state
    redcap = _put(state, _creature("Murderous Redcap", keywords=["Persist"],
                                   power=2, toughness=2))
    _kill(eng, redcap)
    assert redcap.zone == Zone.BATTLEFIELD  # came back with -1/-1
    _kill(eng, redcap)
    assert redcap.zone == Zone.GRAVEYARD  # had a -1/-1 counter → stays dead


def test_granted_undying_works_off_the_layer_engine_union():
    # RULE 702.93 via a layer-6 grant rather than a printed keyword — the
    # ticket's headline gap.
    eng = _engine()
    state = eng.state
    from mtg_analyzer.game.effects.core import StaticAbility

    lord = _put(state, _creature("Undying Lord", power=2, toughness=2,
                                 type_line="Creature — Zombie"))
    bear = _put(state, _creature("Bear", power=2, toughness=2))
    lord.static_effects.append(
        StaticAbility(layer="ability", affects="other_creatures_you_control",
                     params={"keywords": ["undying"]}, source=lord)
    )
    continuous.recompute(state)
    assert "undying" in bear.granted_keywords

    _kill(eng, bear)
    assert bear.zone == Zone.BATTLEFIELD
    assert bear.counters.get("+1/+1", 0) == 1


# -- Unearth / Embalm / Eternalize (RULE 702.84 / 702.128 / 702.129) --------


def _in_graveyard(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    state.player_by_id(controller).add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def _main_phase(eng):
    eng.start()
    while eng.state.current_step != "main1":
        eng.advance_step()


def test_unearth_returns_the_card_with_haste_and_arms_end_step_exile():
    eng = _engine()
    state = eng.state
    grave_bear = _in_graveyard(state, _creature("Grave Bear", keywords=["Unearth"],
                                                oracle_text="Unearth {1}{B}"))
    _main_phase(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 1, "C": 1})
    idx = next(i for i, a in enumerate(grave_bear.activated_abilities)
              if a.cost.graveyard_zone)
    eng.activate_ability(p1, grave_bear, idx)
    eng.resolve_until_stable()

    assert grave_bear.zone == Zone.BATTLEFIELD
    continuous.recompute(state)
    assert "haste" in grave_bear.granted_keywords or "haste" in grave_bear.temp_keywords
    assert any("Unearth" in dt.description for dt in state.delayed_triggers)


def test_unearthed_creature_is_exiled_at_the_next_end_step():
    eng = _engine()
    state = eng.state
    grave_bear = _in_graveyard(state, _creature("Grave Bear", keywords=["Unearth"],
                                                oracle_text="Unearth {1}{B}"))
    _main_phase(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 1, "C": 1})
    idx = next(i for i, a in enumerate(grave_bear.activated_abilities)
              if a.cost.graveyard_zone)
    eng.activate_ability(p1, grave_bear, idx)
    eng.resolve_until_stable()
    assert grave_bear.zone == Zone.BATTLEFIELD

    while state.current_step != "end":
        eng.advance_step()
    eng.advance_step()  # process the end-step delayed trigger
    eng.resolve_until_stable()
    assert grave_bear.zone == Zone.EXILE


def test_unearthed_creature_that_dies_is_exiled_not_left_in_graveyard():
    eng = _engine()
    state = eng.state
    grave_bear = _in_graveyard(state, _creature("Grave Bear", keywords=["Unearth"],
                                                oracle_text="Unearth {1}{B}"))
    _main_phase(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 1, "C": 1})
    idx = next(i for i, a in enumerate(grave_bear.activated_abilities)
              if a.cost.graveyard_zone)
    eng.activate_ability(p1, grave_bear, idx)
    eng.resolve_until_stable()

    eng.rules.destroy(grave_bear)
    eng.rules.check_state_based_actions()
    eng.resolve_until_stable()
    assert grave_bear.zone == Zone.EXILE  # not re-unearthable


def test_embalm_makes_a_white_zombie_token_copy_and_exiles_the_card():
    eng = _engine()
    state = eng.state
    card = _creature("Embalm Bear", keywords=["Embalm"], power=2, toughness=3,
                     oracle_text="Embalm {2}{W}")
    ghost = _in_graveyard(state, card)
    _main_phase(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"W": 1, "C": 2})
    idx = next(i for i, a in enumerate(ghost.activated_abilities)
              if a.cost.graveyard_zone)
    eng.activate_ability(p1, ghost, idx)
    eng.resolve_until_stable()

    assert ghost.zone == Zone.EXILE
    tokens = [o for o in state.battlefield if o.is_token and o.card.name == "Embalm Bear"]
    assert len(tokens) == 1
    tok = tokens[0]
    continuous.recompute(state)
    assert (tok.power, tok.toughness) == (2, 3)  # same P/T as the card
    assert "zombie" in tok.card.type_line.lower()


def test_eternalize_makes_a_4_4_zombie_token_copy():
    eng = _engine()
    state = eng.state
    card = _creature("Wits Snake", keywords=["Eternalize"], power=2, toughness=1,
                     oracle_text="Eternalize {5}{U}{U}", type_line="Creature — Snake Wizard")
    ghost = _in_graveyard(state, card)
    _main_phase(eng)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 2, "C": 5})
    idx = next(i for i, a in enumerate(ghost.activated_abilities)
              if a.cost.graveyard_zone)
    eng.activate_ability(p1, ghost, idx)
    eng.resolve_until_stable()

    tokens = [o for o in state.battlefield if o.is_token]
    assert len(tokens) == 1
    continuous.recompute(state)
    assert (tokens[0].power, tokens[0].toughness) == (4, 4)
    assert "zombie" in tokens[0].card.type_line.lower()


# -- Dredge (RULE 702.52) -------------------------------------------------


def _stock_library(state, controller, n):
    p = state.player_by_id(controller)
    for i in range(n):
        c = Card(id=f"lib{i}", name=f"Lib {i}", type_line="Instant", is_instant=True)
        o = GameObject(c, owner_id=controller, zone=Zone.LIBRARY)
        p.add_to_zone(o, Zone.LIBRARY)


def test_dredge_replaces_a_draw_with_mill_and_return_to_hand():
    eng = _engine()
    state = eng.state
    troll = _in_graveyard(state, _creature("Grave-Troll", keywords=["Dredge"],
                                           power=0, toughness=0, oracle_text="Dredge 3"))
    _stock_library(state, "p1", 5)
    p1 = state.player_by_id("p1")

    eng.rules.draw(p1, 1)
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "dredge"
    eng.resolve_pending_choice(str(troll.instance_id))

    assert troll.zone == Zone.HAND
    assert len(p1.graveyard) == 3  # three milled
    assert len(p1.library) == 2
    assert troll in p1.hand


def test_dredge_can_be_declined_to_draw_normally():
    eng = _engine()
    state = eng.state
    troll = _in_graveyard(state, _creature("Grave-Troll", keywords=["Dredge"],
                                           power=0, toughness=0, oracle_text="Dredge 3"))
    _stock_library(state, "p1", 5)
    p1 = state.player_by_id("p1")

    eng.rules.draw(p1, 1)
    eng.resolve_pending_choice("draw")

    assert troll.zone == Zone.GRAVEYARD
    assert len(p1.hand) == 1 and len(p1.library) == 4


def test_dredge_not_offered_with_too_few_cards_in_library():
    eng = _engine()
    state = eng.state
    _in_graveyard(state, _creature("Grave-Troll", keywords=["Dredge"],
                                   power=0, toughness=0, oracle_text="Dredge 3"))
    _stock_library(state, "p1", 2)  # fewer than N=3
    p1 = state.player_by_id("p1")

    eng.rules.draw(p1, 1)
    assert state.pending_choice is None  # RULE 702.52c
    assert len(p1.hand) == 1 and len(p1.library) == 1
