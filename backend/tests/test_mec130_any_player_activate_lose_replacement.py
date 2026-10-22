"""MEC-130: "Any player may activate this ability" + "~ loses <replacement> until end of turn".

Glittering Lion/Lynx: an opponent pays {3}/{2} at their own priority, the Lion loses its
"prevent all damage" replacement until end of turn (RULE 613.1f, ended by RULE 514.2).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle

LION_TEXT = (
    "Prevent all damage that would be dealt to this creature.\n"
    "{3}: Until end of turn, this creature loses \"Prevent all damage that would be dealt to this "
    "creature.\" Any player may activate this ability."
)


def _lion_card(text=LION_TEXT, name="Glittering Lion"):
    return Card(id=name, name=name, type_line="Creature — Cat", is_creature=True, power=3, toughness=3,
                oracle_text=text)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    return eng


def _lion(eng):
    obj = GameObject(_lion_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _hit(eng, lion, amount=2):
    eng.rules.deal_damage(lion, amount, source=None)
    eng.resolve_until_stable()


def test_real_cards_are_modeled_and_unknown_quoted_ability_is_refused():
    assert parse_oracle(_lion_card()).coverage == MODELED
    other = LION_TEXT.replace("loses \"Prevent all damage that would be dealt to this creature.\"",
                              "loses \"Flying.\"")
    assert parse_oracle(_lion_card(other)).coverage == UNMODELED


def test_activation_cost_is_open_to_every_player():
    spec = next(s for s in parse_oracle(_lion_card()).specs if s.ability_kind == "activated")
    assert spec.cost["any_player_may_activate"] is True


def test_prevention_holds_until_an_opponent_activates():
    eng = _engine()
    lion = _lion(eng)
    _hit(eng, lion)
    assert lion.damage_marked == 0

    p2 = eng.state.players[1]
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    p2.mana_pool.add("C", 3)
    assert eng.can_activate(p2, lion, lion.activated_abilities[0])
    eng.activate_ability(p2, lion)
    eng.resolve_until_stable()

    _hit(eng, lion)
    assert lion.damage_marked == 2


def test_controller_can_activate_too_and_must_pay():
    eng = _engine()
    lion = _lion(eng)
    p1 = eng.state.players[0]
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    assert not eng.can_activate(p1, lion, lion.activated_abilities[0])  # no mana
    p1.mana_pool.add("C", 3)
    assert eng.can_activate(p1, lion, lion.activated_abilities[0])


def test_ability_returns_at_cleanup():
    eng = _engine()
    lion = _lion(eng)
    p2 = eng.state.players[1]
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    p2.mana_pool.add("C", 3)
    eng.activate_ability(p2, lion)
    eng.resolve_until_stable()
    _hit(eng, lion)
    assert lion.damage_marked == 2

    eng._step_cleanup()
    lion.damage_marked = 0
    _hit(eng, lion)
    assert lion.damage_marked == 0
