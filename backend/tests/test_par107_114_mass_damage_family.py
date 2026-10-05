"""PAR-107…114 residue batches, part 6 — mass-damage riders (PAR-110): "deals N damage to each creature without
flying and each planeswalker" (Magmaquake), "…to each creature dealt damage this turn" (Inflame) and the kicked
"instead" override (Cinderclasm).

Reference: parser/oracle/catalogue/handlers.py (`_DAMAGE_EACH_CREATURE_KEYWORD_RE`, `_DAMAGE_EACH_DAMAGED_CREATURE_RE`,
`_DAMAGE_EACH_CREATURE_KICKED_RE`), game/combat.py (`damaged_this_turn`), game/effects/damage_draw.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _creature(eng, name, toughness=4, keywords=None, controller="p2"):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=1, toughness=toughness,
                keywords=keywords or [], oracle_text=" ".join(keywords or []))
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _planeswalker(eng, name="Jace", loyalty=5):
    card = Card(id=name, name=name, type_line="Legendary Planeswalker — Jace", loyalty=loyalty)
    obj = GameObject(card, owner_id="p2", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p2"
    obj.counters["loyalty"] = loyalty
    eng.state.add_to_battlefield(obj)
    return obj


def _resolve(eng, text, name="Probe", **kw):
    card = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text, mana_cost_string="{R}",
                converted_mana_cost=1, **kw)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1 = eng.state.player_by_id("p1")
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"R": 6})
    return spell


def test_magmaquake_hits_ground_creatures_and_planeswalkers_but_not_fliers():
    eng = _engine()
    ground, flier = _creature(eng, "Ground", 4), _creature(eng, "Flier", 4, ["Flying"])
    walker = _planeswalker(eng)
    spell = _resolve(eng, "~ deals X damage to each creature without flying and each planeswalker.")
    eng.cast_spell(eng.state.player_by_id("p1"), spell, x=2)
    eng.resolve_until_stable()
    assert ground.damage_marked == 2 and flier.damage_marked == 0
    assert walker.counters["loyalty"] == 3


def test_inflame_only_hits_creatures_already_dealt_damage_this_turn():
    eng = _engine()
    hurt, fresh = _creature(eng, "Hurt", 4), _creature(eng, "Fresh", 4)
    hurt.damage_marked = 1
    spell = _resolve(eng, "~ deals 2 damage to each creature dealt damage this turn.")
    eng.cast_spell(eng.state.player_by_id("p1"), spell)
    eng.resolve_until_stable()
    assert hurt.damage_marked == 3 and fresh.damage_marked == 0


def test_cinderclasm_deals_two_to_each_creature_when_kicked():
    text = "Kicker {R}\n~ deals 1 damage to each creature. If it was kicked, it deals 2 damage to each creature instead."
    eng = _engine()
    target = _creature(eng, "Bear", 5)
    plain = _resolve(eng, text, keywords=["Kicker"])
    eng.cast_spell(eng.state.player_by_id("p1"), plain)
    eng.resolve_until_stable()
    assert target.damage_marked == 1
    kicked = _resolve(eng, text, name="Probe2", keywords=["Kicker"])
    eng.cast_spell(eng.state.player_by_id("p1"), kicked, kicked=1)
    eng.resolve_until_stable()
    assert target.damage_marked == 3  # 1 + 2


def test_a_broader_group_rider_stays_unclaimed():
    card = Card(id="Probe", name="Probe", type_line="Sorcery", is_sorcery=True,
                oracle_text="~ deals 2 damage to each creature dealt damage this turn and each planeswalker.")
    assert not parse_oracle(card).modeled
