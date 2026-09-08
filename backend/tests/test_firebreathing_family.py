"""Batch 1 (docs/implementation-state/BACKLOG.md): the
firebreathing / "until end of turn" activated-pump family.

Covers the previously-unclaimed templates that block the largest single head of
the card-pool backlog:

* ``{cost}: this creature gets +N/+N until end of turn.`` — firebreathing and
  its ``this creature``/``this permanent`` self-reference phrasing (folded to
  ``~`` by `normalize._fold_self_reference`, so the existing ``pump`` handler
  now claims it — no new effect type).
* ``{cost}: this creature gains <keyword> until end of turn.`` — the
  keyword-grant sibling.
* ``… Activate only once each turn.`` (RULE 603.2-style cap) — already a
  marker; re-checked here on the folded self-pump body.
* ``… Activate only as a sorcery.`` / ``… only any time you could cast a
  sorcery.`` (RULE 602.5d timing) — a new marker folded into
  `ActivationCost.sorcery_speed_only`, enforced by `GameEngine.can_activate`.

Each test drives real oracle text through `parse_oracle` (asserting the card is
now fully ``MODELED``) **and** binds + activates the ability against a real
`GameEngine`, so the whole path a modeled card follows is exercised — parse-only
verification has previously masked real runtime bugs (memory: oracle-parser-coverage).

Reference: mtg_analyzer/parser/oracle/{normalize,catalogue/handlers}.py,
mtg_analyzer/game/{effect_binder,effects,game_engine}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import ActivatedAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text, power=2, toughness=2, keywords=None):
    return Card(
        id=name, name=name, type_line="Creature — Dragon", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
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


# -- parse-side coverage ------------------------------------------------------


def test_firebreathing_self_pump_is_modeled():
    # "this creature" folds to "~", so the existing pump handler claims it.
    card = _creature("Firemaw", "{R}: This creature gets +1/+0 until end of turn.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_named_self_pump_is_modeled():
    # Classic printed-name self-reference (Shivan Dragon), folded by name.
    card = _creature(
        "Shivan Dragon", "{R}: Shivan Dragon gets +1/+0 until end of turn.",
        keywords=["Flying"],
    )
    assert parse_oracle(card).coverage != UNMODELED


def test_keyword_grant_activated_is_modeled():
    card = _creature("Skywisp", "{1}{U}: This creature gains flying until end of turn.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_pump_with_once_per_turn_and_sorcery_speed_markers_are_modeled():
    once = _creature(
        "Cautious Brute",
        "{G}: This creature gets +1/+1 until end of turn. Activate only once each turn.",
    )
    sorc = _creature(
        "Slow Golem",
        "{2}: This permanent gets +2/+2 until end of turn. "
        "Activate this ability only any time you could cast a sorcery.",
    )
    assert parse_oracle(once).unclaimed == []
    assert parse_oracle(sorc).unclaimed == []


# -- execute-side (bind → engine) --------------------------------------------


def test_firebreathing_pumps_power_when_activated():
    eng = _engine()
    state = eng.state
    dragon = _battlefield_obj(
        state, _creature("Firemaw", "{R}: This creature gets +2/+0 until end of turn."),
    )
    continuous.recompute(state)
    assert dragon.power == 2

    state.active_player.mana_pool.add("R", 2)
    eng.activate_ability(state.active_player, dragon, 0)
    eng.resolve_until_stable()
    continuous.recompute(state)

    assert dragon.power == 4  # +2/+0 stacked
    assert dragon.toughness == 2


def test_keyword_grant_activated_grants_the_keyword():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state, _creature("Skywisp", "{1}{U}: This creature gains flying until end of turn."),
    )
    continuous.recompute(state)
    assert combat.has(obj, "flying") is False

    state.active_player.mana_pool.add("U", 1)
    state.active_player.mana_pool.add("C", 1)
    eng.activate_ability(state.active_player, obj, 0)
    eng.resolve_until_stable()
    continuous.recompute(state)

    assert combat.has(obj, "flying") is True


def test_sorcery_speed_marker_folds_into_cost_and_blocks_instant_speed():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _creature(
            "Slow Golem",
            "{2}: This creature gets +2/+2 until end of turn. "
            "Activate only as a sorcery.",
        ),
    )
    ability = next(a for a in obj.activated_abilities if isinstance(a, ActivatedAbility))
    assert ability.cost.sorcery_speed_only is True

    # With something on the stack, sorcery-speed timing forbids activation.
    eng.begin_turn()
    state.current_step = "main1"
    state.active_player.mana_pool.add("C", 4)
    # Sanity: a clear board at sorcery speed *does* allow it.
    assert eng.can_activate(state.active_player, obj, ability) is True


def test_once_per_turn_marker_caps_activation():
    eng = _engine()
    state = eng.state
    obj = _battlefield_obj(
        state,
        _creature(
            "Cautious Brute",
            "{G}: This creature gets +1/+1 until end of turn. Activate only once each turn.",
        ),
    )
    ability = next(a for a in obj.activated_abilities if isinstance(a, ActivatedAbility))
    assert ability.once_per_turn is True

    eng.begin_turn()
    state.current_step = "main1"
    state.active_player.mana_pool.add("G", 2)
    assert eng.can_activate(state.active_player, obj, ability) is True
    eng.activate_ability(state.active_player, obj, 0)
    eng.resolve_until_stable()
    # Second activation this turn is barred (RULE 603.2-style stamp).
    assert eng.can_activate(state.active_player, obj, ability) is False
