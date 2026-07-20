"""Batch 10 (docs/implementation-state/CARDPOOL_MODELING_BATCHES.md):
Monarch / Initiative / Emblem — three greenfield subsystems (deprioritized
per `10_COMPLETION_ROADMAP.md` M6 until a batch needed them).

* **Monarch (RULE 725)** — `GameState.monarch_id` + `RulesEngine.
  become_monarch`; both inherent, source-less triggered abilities (RULE
  725.2 — the monarch's own end step draws a card, a creature dealing
  combat damage to the monarch swaps it to that creature's controller) are
  checked fresh off live state each event by `RulesEngine.
  _collect_inherent_triggers`, since neither is attached to any permanent
  for the ordinary object-scan in `_collect_triggers` to find.
* **Initiative (RULE 726)** — the same designation/swap shape
  (`GameState.initiative_id`/`RulesEngine.take_initiative`). RULE 726.2's
  "venture into the dungeon" companion trigger is a deliberate gap: dungeons
  (RULE 309) aren't modeled in this engine at all yet, so it isn't fired —
  see `TakeInitiativeEffect`'s docstring. A card whose only clause is "You
  take the initiative." still becomes fully MODELED regardless, since the
  designation swap and its own combat-damage-steal trigger are real RULE
  726 behaviour on their own.
* **Emblem (RULE 114)** — "[Player] get[s] an emblem with '[ability]'."
  creates a command-zone marker with no characteristics beyond the quoted
  ability (`models/emblem.py`'s `Emblem`, a minimal `source` stand-in
  carrying just `controller_id`/`timestamp`). The quoted ability is
  recursively parsed at parse time into a full nested `AbilitySpec`
  (`parser/oracle/catalogue/handlers.py`'s `_emblem_ability_spec`, mirroring
  `static_handlers._quoted_ability_grant_effects`'s recursive-`segment_line`
  idiom) and bound once, at resolve time, against that synthetic source
  (`RulesEngine.create_emblem`) — an emblem has no permanent to bind onto at
  bind-on-load like every other ability. `game/continuous.py`'s static-
  ability scan and `RulesEngine._collect_triggers` both read every player's
  `Player.emblems` alongside the battlefield so a static/triggered emblem
  ability applies exactly like a permanent's own (RULE 114.4).

Reference: mtg_analyzer/models/{game_state,player,emblem}.py,
mtg_analyzer/game/{effects,rules_engine,continuous}.py,
mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, type_line="Creature — Bear"):
    return Card(
        id=name, name=name, type_line=type_line,
        is_creature=True, power=power, toughness=toughness, oracle_text=oracle_text,
    )


def _sorcery(name, oracle_text):
    return Card(
        id=name, name=name, type_line="Sorcery", oracle_text=oracle_text,
        mana_cost_string="{1}{W}", converted_mana_cost=2, is_sorcery=True,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _battlefield_obj(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _cast(engine, player, card, targets=None):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    player.hand.append(obj)
    player.mana_pool.add_many({"W": 5})
    engine.state.active_player_index = engine.state.players.index(player)
    engine.state.current_step = "main1"
    engine.cast_spell(player, obj, targets=targets)
    engine.resolve_until_stable()
    return result


# ---------------------------------------------------------------------------
# Parse-side coverage
# ---------------------------------------------------------------------------


def test_you_become_the_monarch_is_modeled():
    card = _sorcery("Palace Jailer Shaped", "You become the monarch.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].type == "become_monarch"
    assert spell.effects[0].params == {}


def test_target_player_becomes_the_monarch_is_modeled():
    card = _sorcery("Throne Shaped", "Target player becomes the monarch.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].params == {"target_kind": "player"}


def test_you_take_the_initiative_is_modeled():
    card = _sorcery(
        "Undercity Cavalier Shaped",
        "You take the initiative.",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].type == "take_initiative"


def test_target_player_takes_the_initiative_is_modeled():
    card = _sorcery("Coerced Initiative Shaped", "Target player takes the initiative.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].params == {"target_kind": "player"}


def test_emblem_with_static_anthem_is_modeled():
    card = _sorcery(
        "Gideon Ultimate Shaped", 'You get an emblem with "Creatures you control get +1/+1."'
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    effect = spell.effects[0]
    assert effect.type == "create_emblem"
    ability = effect.params["ability"]
    assert ability["ability_kind"] == "static"
    assert ability["effects"][0]["type"] == "anthem"


def test_emblem_with_triggered_ability_is_modeled():
    card = _sorcery(
        "Elspeth Ultimate Shaped",
        'You get an emblem with "Whenever a creature you control dies, you gain 3 life."',
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    ability = spell.effects[0].params["ability"]
    assert ability["ability_kind"] == "triggered"
    assert ability["trigger"]["event"] == "DIES"


def test_target_player_gets_an_emblem_is_modeled():
    card = _sorcery(
        "Forced Emblem Shaped",
        'Target player gets an emblem with "Creatures you control get +1/+1."',
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].params["target_kind"] == "player"


def test_emblem_with_self_subject_stays_unclaimed():
    # Fail-closed: "this creature"-shaped quoted text means nothing without
    # a host permanent for the emblem's synthetic source to stand in for.
    card = _sorcery(
        "Nonsense Emblem Shaped",
        'You get an emblem with "Whenever ~ attacks, draw a card."',
    )
    assert parse_oracle(card).coverage == UNMODELED


# ---------------------------------------------------------------------------
# Execute-side
# ---------------------------------------------------------------------------


def test_become_monarch_sets_designation_and_swaps():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    _cast(eng, p1, _sorcery("Palace Jailer Shaped", "You become the monarch."))
    assert state.monarch_id == "p1"

    _cast(eng, p2, _sorcery("Throne Shaped 2", "You become the monarch."))
    assert state.monarch_id == "p2"


def test_target_player_becomes_the_monarch():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    _cast(eng, p1, _sorcery("Throne Shaped", "Target player becomes the monarch."), targets=[p2])
    assert state.monarch_id == "p2"


def test_monarchs_end_step_draws_a_card():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(_creature("Topdeck"), owner_id="p1", zone=Zone.LIBRARY))
    eng.rules.become_monarch(p1)
    before = len(p1.hand)

    state.active_player_index = 0  # p1's own turn
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == before + 1


def test_non_monarchs_end_step_does_not_draw():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    eng.rules.become_monarch(p1)

    state.active_player_index = 1  # p2's own end step — p1 is still monarch
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    assert eng.rules.put_triggers_on_stack() == 0


def test_combat_damage_to_the_monarch_swaps_it():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    eng.rules.become_monarch(p1)

    attacker = _battlefield_obj(state, _creature("Raider"), controller="p2")
    eng.rules.deal_damage(p1, 3, source=attacker, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert state.monarch_id == "p2"


def test_noncombat_damage_to_the_monarch_does_not_swap_it():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    eng.rules.become_monarch(p1)

    burn_source = _battlefield_obj(state, _creature("Not a combatant"), controller="p2")
    eng.rules.deal_damage(p1, 3, source=burn_source, combat=False)
    assert eng.rules.put_triggers_on_stack() == 0
    assert state.monarch_id == "p1"


def test_take_initiative_sets_designation_and_swaps():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    _cast(eng, p1, _sorcery("Undercity Cavalier Shaped", "You take the initiative."))
    assert state.initiative_id == "p1"

    _cast(eng, p2, _sorcery("Undercity Cavalier Shaped 2", "You take the initiative."))
    assert state.initiative_id == "p2"


def test_combat_damage_to_the_initiative_holder_swaps_it():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    eng.rules.take_initiative(p1)

    attacker = _battlefield_obj(state, _creature("Raider"), controller="p2")
    eng.rules.deal_damage(p1, 2, source=attacker, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert state.initiative_id == "p2"


def test_emblem_static_anthem_applies_via_layer_engine():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    bear = _battlefield_obj(
        state, _creature("Vanilla Bear", oracle_text=""), controller="p1"
    )

    _cast(
        eng, p1,
        _sorcery("Gideon Ultimate Shaped", 'You get an emblem with "Creatures you control get +1/+1."'),
    )
    assert len(p1.emblems) == 1
    from mtg_analyzer.game import continuous

    continuous.recompute(state)
    assert bear.power == 3
    assert bear.toughness == 3


def test_emblem_anthem_does_not_affect_opponents_creatures():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    opp_bear = _battlefield_obj(state, _creature("Opposing Bear"), controller="p2")

    _cast(
        eng, p1,
        _sorcery("Gideon Ultimate Shaped", 'You get an emblem with "Creatures you control get +1/+1."'),
    )
    from mtg_analyzer.game import continuous

    continuous.recompute(state)
    assert opp_bear.power == 2
    assert opp_bear.toughness == 2


def test_emblem_triggered_ability_fires_off_a_dies_event():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")

    _cast(
        eng, p1,
        _sorcery(
            "Elspeth Ultimate Shaped",
            'You get an emblem with "Whenever a creature you control dies, you gain 3 life."',
        ),
    )
    assert len(p1.emblems) == 1
    life_before = p1.life

    dying = _battlefield_obj(state, _creature("Fodder"), controller="p1")
    eng.rules._move_to_graveyard(dying)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    assert p1.life == life_before + 3


def test_emblem_triggered_ability_does_not_fire_for_opponents_permanent():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    _cast(
        eng, p1,
        _sorcery(
            "Elspeth Ultimate Shaped",
            'You get an emblem with "Whenever a creature you control dies, you gain 3 life."',
        ),
    )
    dying = _battlefield_obj(state, _creature("Opponent's Fodder"), controller="p2")
    eng.rules._move_to_graveyard(dying)
    assert eng.rules.put_triggers_on_stack() == 0
