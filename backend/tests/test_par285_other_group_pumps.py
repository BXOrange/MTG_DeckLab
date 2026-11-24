"""PAR-285 (v983): "other <quality> creatures [you control] get +N/+N until end of turn" (RULE 109.5, 611.2c).

The pump subject grammar knew "other creatures you control" and "other attacking creatures" but not the same group
with a subtype, a combat state or a joined subtype list in front of "creatures" ("other Faerie creatures you control",
"other Mercenary creatures", "other blocking creatures", "other Goblins and Orcs you control"). The group is the shared
`parse_count_phrase` selector (`not_reference` = the source is excluded), locked when the effect resolves.
Tests run parser -> binder -> engine on the real cards, with matching AND non-matching candidates (other controller,
other subtype, the source itself). Each behaviour test fails when the `_GROUP` alternation stops matching the phrase."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _hand, _put, _session

NEW_CARDS = [
    "Faerie Noble", "Phyrexian Driver", "Orc General", "Bolg, Erebor's Reckoning",
    "Qala, Ajani's Pridemate", "Márton Stromgald",
]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _body(name: str, type_line: str = "Creature — Bear", power: int = 2, toughness: int = 2) -> Card:
    return Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}", converted_mana_cost=1,
                is_creature=True, power=power, toughness=toughness)


def _stats(engine, *objs):
    engine.recompute_continuous_effects()
    return [(o.power, o.toughness) for o in objs]


def _combat_engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.start()
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    return engine, engine.state


@pytest.mark.parametrize("name", NEW_CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True, name


@pytest.mark.parametrize("clause, flt, scope", [
    ("other faerie creatures you control get +1/+0 until end of turn",
     {"subtype": "faerie", "card_type": "creature", "not_reference": True}, "you"),
    ("other mercenary creatures get +1/+1 until end of turn",
     {"subtype": "mercenary", "card_type": "creature", "not_reference": True}, "any"),
    ("other goblins and orcs you control get +2/+2 until end of turn",
     {"subtype_any": ["goblin", "orc"], "not_reference": True}, "you"),
    ("other blocking creatures get +1/+1 until end of turn",
     {"blocking": True, "card_type": "creature", "not_reference": True}, "any"),
])
def test_group_selector_shape(clause, flt, scope):
    (effect,) = match_clause(clause)
    assert effect.type == "pump"
    selector = effect.params["selector"]
    assert selector["of"] == scope and selector["filter"] == flt


def test_phyrexian_driver_pumps_every_other_mercenary_of_either_player():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    driver = _hand(state, _real("Phyrexian Driver"))
    mine = _put(state, _body("Mine", "Creature — Mercenary"))
    theirs = _put(state, _body("Theirs", "Creature — Mercenary"), "p2")
    bear = _put(state, _body("Bear"))
    p1.mana_pool.add_many({"B": 3, "C": 3})
    engine.cast_spell(p1, driver)
    engine.resolve_until_stable()
    assert _stats(engine, mine, theirs, bear) == [(3, 3), (3, 3), (2, 2)]
    # RULE 109.5: "other" leaves the entering Driver itself at its printed 1/1 (a Mercenary).
    assert _stats(engine, driver) == [(1, 1)]


def test_faerie_noble_boosts_only_other_faeries_you_control():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    noble = _put(state, _real("Faerie Noble"))
    mine = _put(state, _body("Mine", "Creature — Faerie"))
    theirs = _put(state, _body("Theirs", "Creature — Faerie"), "p2")
    bear = _put(state, _body("Bear"))
    # The static "+0/+1" half already modelled applies to the same group; only the activation adds +1/+0.
    before = _stats(engine, noble, mine, theirs, bear)
    engine.activate_ability(p1, noble, 0)
    engine.resolve_until_stable()
    after = _stats(engine, noble, mine, theirs, bear)
    assert [a[0] - b[0] for a, b in zip(after, before)] == [0, 1, 0, 0]


def test_qala_pumps_other_attackers_you_control_by_its_counters():
    engine, state = _combat_engine()
    p1 = state.player_by_id("p1")
    qala = _put(state, _real("Qala, Ajani's Pridemate"))
    qala.counters["+1/+1"] = 3
    other = _put(state, _body("Other"))
    idle = _put(state, _body("Idle"))
    enemy = _put(state, _body("Enemy"), "p2")
    qala_before = _stats(engine, qala)[0]
    engine.declare_attackers(p1, [qala, other])
    engine.resolve_until_stable()
    assert _stats(engine, qala) == [qala_before]  # "other" excludes Qala from its own +3/+0
    assert _stats(engine, other, idle, enemy) == [(5, 2), (2, 2), (2, 2)]


def test_marton_pumps_other_blockers_not_attackers_or_itself():
    engine, state = _combat_engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    marton = _put(state, _real("Márton Stromgald"), "p2")
    ally = _put(state, _body("Ally", power=1, toughness=5), "p2")
    attacker_a = _put(state, _body("AttA", power=1, toughness=5))
    attacker_b = _put(state, _body("AttB", power=1, toughness=5))
    before = _stats(engine, marton, ally, attacker_a, attacker_b)
    engine.declare_attackers(p1, [attacker_a, attacker_b])
    engine.advance_step()
    engine.declare_blockers(p2, [{"blocker": marton, "attacker": attacker_a}, {"blocker": ally, "attacker": attacker_b}])
    engine.resolve_until_stable()
    after = _stats(engine, marton, ally, attacker_a, attacker_b)
    # +1/+1 for the one other blocking creature, on the other blocker only (not Márton, not the attackers).
    assert [(a[0] - b[0], a[1] - b[1]) for a, b in zip(after, before)] == [(0, 0), (1, 1), (0, 0), (0, 0)]


def test_bolg_pumps_other_goblins_and_orcs_you_control_at_each_combat():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    engine.start()
    while engine.state.current_step != "main1":
        engine.advance_step()
    state = engine.state
    bolg = _put(state, _real("Bolg, Erebor's Reckoning"))
    goblin = _put(state, _body("Gob", "Creature — Goblin"))
    foreign_orc = _put(state, _body("Orc", "Creature — Orc"), "p2")
    bear = _put(state, _body("Bear"))
    before = _stats(engine, bolg, goblin, foreign_orc, bear)
    engine.advance_step()
    engine.resolve_until_stable()
    after = _stats(engine, bolg, goblin, foreign_orc, bear)
    # +2/+2 on your other Goblins/Orcs only; Bolg's own second sentence shrinks the opponent's creatures by 1.
    assert [(a[0] - b[0], a[1] - b[1]) for a, b in zip(after, before)] == [(0, 0), (2, 2), (-1, -1), (0, 0)]


def test_orc_general_pumps_every_other_orc_after_sacrificing_an_orc_or_goblin():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    general = _put(state, _real("Orc General"))
    goblin = _put(state, _body("Gob", "Creature — Goblin"))
    mine = _put(state, _body("Orc1", "Creature — Orc"))
    theirs = _put(state, _body("Orc2", "Creature — Orc"), "p2")
    bear = _put(state, _body("Bear"))
    engine.activate_ability(p1, general, 0)
    engine.resolve_until_stable()
    assert goblin not in state.battlefield  # the cost: sacrifice another Orc or Goblin
    assert _stats(engine, general, mine, theirs, bear) == [(2, 2), (3, 3), (3, 3), (2, 2)]
