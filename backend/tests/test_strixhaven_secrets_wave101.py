"""Secrets of Strixhaven — playability batch, wave 101 (PAR-60).

Unbound Flourishing — clause 2 is Owlin Spiralmancer's shape (SPELL_CAST +
``spell_has_x`` + `copy_spell` from the trigger event, ``spell_card_types``
narrowed to instant/sorcery). Clause 1 is a new `double_cast_x` effect that
doubles the announced X on a permanent spell's stack item.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem


def _uf_card():
    return Card(id="uf", name="Unbound Flourishing", type_line="Enchantment",
                oracle_text=("Whenever you cast a permanent spell with a mana cost that "
                             "contains {X}, double the value of X.\nWhenever you cast an "
                             "instant or sorcery spell or activate an ability, if that "
                             "spell's mana cost or that ability's activation cost "
                             "contains {X}, copy that spell or ability."))


def test_registered_and_binds():
    assert is_registered("Unbound Flourishing")
    specs = _REGISTRY["unbound flourishing"]()
    assert [s.effects[0].type for s in specs] == ["double_cast_x", "copy_spell"]
    src = GameObject(_uf_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_uf_card())


def test_double_cast_x_doubles_a_permanent_spells_announced_x():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_uf_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    spell_obj = GameObject(Card(id="hydra", name="Hydra", type_line="Creature — Hydra",
                                is_creature=True, mana_cost_string="{X}{G}"),
                           owner_id="p1", zone=Zone.STACK)
    spell_obj.x_paid = 3
    item = StackItem(kind="spell", controller_id="p1", effects=[], obj=spell_obj, x=3)
    eng.state.stack.append(item)

    eng.rules.context.trigger_event = {"instance_id": spell_obj.instance_id}
    eng.rules._apply_effect_specs([{"type": "double_cast_x", "params": {}}], src)
    assert item.x == 6
    assert spell_obj.x_paid == 6


def test_double_cast_x_ignores_a_nonpermanent_spell():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_uf_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    spell_obj = GameObject(Card(id="fb", name="Fireball", type_line="Sorcery",
                                is_sorcery=True, mana_cost_string="{X}{R}"),
                           owner_id="p1", zone=Zone.STACK)
    spell_obj.x_paid = 4
    item = StackItem(kind="spell", controller_id="p1", effects=[], obj=spell_obj, x=4)
    eng.state.stack.append(item)
    eng.rules.context.trigger_event = {"instance_id": spell_obj.instance_id}
    eng.rules._apply_effect_specs([{"type": "double_cast_x", "params": {}}], src)
    assert item.x == 4
