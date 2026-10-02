"""PAR-107…114 residue batches, part 7 — "add X mana in any combination of colors" and its kin (PAR-113's kept-mana
cluster): `add_mana` with the ``"ANY"`` offer narrowed to named colours, sized by a fixed count (that many single
picks — exactly RULE 106.1), "that much" off a damage event (Photon), or off the whole attack declaration (Grand
Warlord Radha). The "that much" under "whenever one or more creatures you control attack" used to be read off
`PLAYER_ATTACKED`, which carries no amount (the mana was silently 0); it now measures `ATTACKERS_DECLARED`.

Reference: parser/oracle/catalogue/handlers.py (`_ADD_MANA_ANY_COMBINATION_RE`), segmenter.py (the
`PLAYER_ATTACKED` → `ATTACKERS_DECLARED` retarget), game/effects/choices_actions.py (`any_amount_from_trigger_event`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, text, type_line="Creature — Elf", power=2, toughness=2):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature,
                is_sorcery="Sorcery" in type_line, is_instant="Instant" in type_line, power=power if creature else None,
                toughness=toughness if creature else None)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _effects(text, **kw):
    result = parse_oracle(_card("Probe", text, **kw))
    assert result.modeled, result.unclaimed
    return result.specs[-1].effects


@pytest.mark.parametrize("text, params", [
    ("Add 2 mana in any combination of colors.", None),
    ("Add {R} or {G}.", {"colors": ["ANY"], "any_color_choices": ["R", "G"]}),
])
def test_parse(text, params):
    effects = _effects(text, type_line="Sorcery")
    if params is None:
        assert [e.params for e in effects] == [{"colors": ["ANY"]}] * 2  # two independent single picks
    else:
        assert effects[0].type == "add_mana" and effects[0].params == params


def test_manamorphose_two_mana_are_two_independent_picks():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_card("Manamorphose", "Add two mana in any combination of colors.\nDraw a card.", "Instant"),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "add_mana_any_color"
    eng.resolve_pending_choice("U")
    assert eng.state.pending_choice is not None  # the second mana is its own pick
    eng.resolve_pending_choice("G")
    assert p1.mana_pool.pool["U"] == 1 and p1.mana_pool.pool["G"] == 1  # different colours: a true combination


def test_radha_adds_one_mana_per_attacking_creature_and_keeps_it():
    text = ("Whenever one or more creatures you control attack, add that much mana in any combination of {R} and/or "
            "{G}. Until end of turn, you don't lose this mana as steps and phases end.")
    effects = _effects(text)
    assert effects[0].type == "bind" and effects[0].params["amount"] == {"kind": "attackers_declared"}
    eng = _engine()
    radha = _put(eng, _card("Radha", text))
    others = [_put(eng, _card(f"Bear{i}", "")) for i in range(2)]
    p1 = eng.state.player_by_id("p1")
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [radha, *others])
    eng._fire_player_attacked_events()
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "add_mana_any_color" and choice["amount"] == 3
    assert {o["id"] for o in choice["options"]} == {"R", "G"}
    eng.resolve_pending_choice("R")
    assert p1.mana_pool.pool["R"] == 3
    assert p1.mana_pool.kept  # survives the step ends until end of turn


def test_photon_adds_the_combat_damage_dealt_in_one_colour():
    text = ("Whenever ~ deals combat damage to a player, add that much mana of any 1 color. "
            "Until end of turn, you don't lose this mana as steps and phases end.")
    [effect] = _effects(text)
    assert effect.params == {"colors": ["ANY"], "any_amount_from_trigger_event": "amount", "keep_until": "end_of_turn"}


def test_a_group_filtered_attack_head_with_that_much_is_not_claimed():
    # `PLAYER_ATTACKED`'s group filter has no `ATTACKERS_DECLARED` equivalent, and it carries no amount: fail closed.
    card = _card("Probe", "Whenever one or more artifact creatures you control attack, you gain that much life.")
    assert not parse_oracle(card).modeled
