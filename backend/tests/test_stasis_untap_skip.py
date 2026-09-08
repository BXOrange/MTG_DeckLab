"""RULE 502.3-adjacent "Players skip their untap steps." (Stasis) — the last
open member of the "players can't `<verb>`" family
(docs/implementation-state/BACKLOG.md's MEC-12 entry; untap's own *capped*
sibling shipped earlier as `active_untap_caps`/``untap_cap``).

Unlike a cap, this is unconditional and total: nothing about the untap step
happens at all for *any* player, so it gets the same "whole step skipped, no
bookkeeping either" treatment as `RulesEngine.should_skip_step`, not
`has_no_untap_static`'s "just don't untap this one permanent" — modeled as a
new `skip_untap_step` `StaticAbility` layer (`continuous.
all_untap_steps_skipped`, `GameEngine._step_untap`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def enchantment(name, oracle_text):
    return Card(id=name, name=name, type_line="Enchantment", oracle_text=oracle_text)


def creature(name, power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness,
    )


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_stasis_is_modeled():
    card = enchantment(
        "Stasis",
        "Players skip their untap steps.\n"
        "At the beginning of your upkeep, sacrifice this enchantment unless you pay {U}.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_stasis_stops_every_players_permanents_from_untapping():
    eng = make_engine("p1", "p2")
    put(eng.state, enchantment(
        "Stasis",
        "Players skip their untap steps.\n"
        "At the beginning of your upkeep, sacrifice this enchantment unless you pay {U}.",
    ))
    mine = put(eng.state, creature("Mine"), controller="p1")
    theirs = put(eng.state, creature("Theirs"), controller="p2")
    mine.tapped = True
    theirs.tapped = True

    eng.state.internal_turn.number = 1
    eng._step_untap()

    assert mine.tapped is True
    assert theirs.tapped is True


def test_without_stasis_untap_proceeds_normally():
    eng = make_engine("p1", "p2")
    mine = put(eng.state, creature("Mine"), controller="p1")
    mine.tapped = True

    eng._step_untap()

    assert mine.tapped is False
