"""Tragic Arrogance keeps selected permanent types and sacrifices the rest."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ta_card():
    return Card(id="ta", name="Tragic Arrogance", type_line="Sorcery", is_sorcery=True,
                oracle_text=("For each player, you choose from among the permanents that "
                             "player controls an artifact, a creature, an enchantment, "
                             "and a planeswalker. Then each player sacrifices all other "
                             "nonland permanents they control."))


def test_registered_and_binds():
    assert is_registered("Tragic Arrogance")
    spec = _REGISTRY["tragic arrogance"]()[0]
    spec.validate()
    assert spec.effects[0].type == "tragic_arrogance"
    src = GameObject(_ta_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ta_card())


def _perm(eng, name, type_line, owner, mv=0, is_creature=False):
    o = GameObject(Card(id=name, name=name, type_line=type_line,
                        is_creature=is_creature, converted_mana_cost=mv,
                        power=1 if is_creature else None,
                        toughness=1 if is_creature else None),
                   owner_id=owner, zone=Zone.BATTLEFIELD)
    o.controller_id = owner
    eng.state.add_to_battlefield(o)
    return o


def test_keeps_one_of_each_type_and_sacrifices_the_rest():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    src = _perm(eng, "src", "Enchantment", "p1")
    # caster's creatures: keep the higher MV
    big = _perm(eng, "BigCat", "Creature — Cat", "p1", mv=5, is_creature=True)
    small = _perm(eng, "SmallCat", "Creature — Cat", "p1", mv=1, is_creature=True)
    rock = _perm(eng, "Rock", "Artifact", "p1", mv=2)
    land = GameObject(Card(id="land", name="Forest", type_line="Basic Land — Forest",
                           is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    eng.state.add_to_battlefield(land)

    # opponent's creatures: keep the lower MV
    opp_big = _perm(eng, "OppBig", "Creature — Ox", "p2", mv=6, is_creature=True)
    opp_small = _perm(eng, "OppSmall", "Creature — Ox", "p2", mv=2, is_creature=True)

    eng.rules._apply_effect_specs([{"type": "tragic_arrogance", "params": {}}],
                                  next(o for o in eng.state.battlefield if o.card.name == "src"))
    eng.resolve_until_stable()

    bf = {o.card.name for o in eng.state.battlefield}
    assert "BigCat" in bf and "SmallCat" not in bf     # caster keeps best
    assert "Rock" in bf                                # only artifact -> kept
    assert "src" in bf                                 # only enchantment -> kept
    assert "Forest" in bf                             # lands untouched
    assert "OppSmall" in bf and "OppBig" not in bf     # opponent keeps worst
