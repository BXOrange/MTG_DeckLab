"""PAR-310: modal headers wrapped in something the plain "choose N —" grammar did not know.

One engine test per header shape, each choosing modes the way the rules say (RULE 700.2a / 700.2b: as the spell is
cast or the triggered ability is put on the stack; RULE 603.12 for a reflexive trigger) and then checking which
modes actually ran.  The modes' own specs are the ordinary modal specs; only the wrapper is new.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def make_engine(p1_library=(), p2_library=()):
    return GameEngine.new_game(
        [("p1", "Alice", list(p1_library)), ("p2", "Bob", list(p2_library))],
        starting_life=20, starting_hand=0,
    )


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def creature(name="Bear", power=2, toughness=2, oracle="", **kw):
    return Card(id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"), is_creature=True,
                power=power, toughness=toughness, oracle_text=oracle, **kw)


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _in_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _spec_with_modes(card):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    return next(s for s in result.specs if s.modes is not None)


def _put_trigger_on_stack(eng, obj, index=0):
    ability = [a for a in obj.triggered_abilities][index]
    eng.rules.pending_triggers = [(ability, None)]
    eng.rules.put_triggers_on_stack()
    return ability


# -- Spree: a mode's price may be several mana symbols (RULE 702.172a) --------------------------------------------


SPREE_ORACLE = (
    "Spree (Choose one or more additional costs.)\n"
    "+ {2} — Search your library for a card, then shuffle and put that card on top.\n"
    "+ {B}{B} — Target player draws three cards and loses three life."
)


def _spree_card():
    return Card(id="Avarice", name="Test Avarice", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{B}", converted_mana_cost=1, oracle_text=SPREE_ORACLE)


def test_spree_multi_symbol_mode_cost_is_parsed_whole():
    spec = _spec_with_modes(_spree_card())
    assert [c.upper() for c in spec.modes["mode_costs"]] == ["{2}", "{B}{B}"]


def test_spree_multi_symbol_mode_pays_base_plus_that_mode_only():
    eng = make_engine([land() for _ in range(5)])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _spree_card())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 3})  # {B} + {B}{B} for the second mode; nothing more
    life = p1.life
    eng.cast_spell(p1, obj, targets=[p1], mode=[1])
    assert p1.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert len(p1.hand) == 3 and p1.life == life - 3


def test_spree_multi_symbol_modes_together_cost_the_sum():
    eng = make_engine([land() for _ in range(5)])
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _spree_card())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 5})  # {B} + {2} + {B}{B}
    eng.cast_spell(p1, obj, targets=[p1], mode=[0, 1])
    assert p1.mana_pool.total() == 0
    short = make_engine([land() for _ in range(5)])
    p = _ready_main_phase(short)
    o = _in_hand(short, _spree_card())
    bind_from_catalogue(o)
    p.mana_pool.add_many({"B": 4})
    with pytest.raises(ValueError):
        short.cast_spell(p, o, targets=[p], mode=[0, 1])


# -- Conditional "you may choose both instead" (RULE 700.2, read as the spell is cast) ---------------------------


SOUL_TRANSFER_ORACLE = (
    "Choose one. If you control an artifact and an enchantment as you cast this spell, you may choose both instead.\n"
    "• Exile target creature or planeswalker.\n"
    "• Return target creature or planeswalker card from your graveyard to your hand."
)


def _soul_transfer():
    return Card(id="ST", name="Test Transfer", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{1}{B}{B}", converted_mana_cost=3, oracle_text=SOUL_TRANSFER_ORACLE)


def _soul_transfer_modes(eng, p1):
    obj = _in_hand(eng, _soul_transfer())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 3})
    return obj, {tuple(a["mode"]) if isinstance(a["mode"], (list, tuple)) else (a["mode"],)
                 for a in eng.legal_actions(p1)
                 if a.get("instance_id") == obj.instance_id and a.get("mode") is not None}


def test_choose_both_instead_needs_the_artifact_and_the_enchantment():
    spec = _spec_with_modes(_soul_transfer())
    assert spec.modes["override"]["condition"] == {
        "kind": "controls_card_types_as_cast", "types": ["artifact", "enchantment"]}
    assert spec.modes["override"]["choose"] == 2

    only_artifact = make_engine()
    p1 = _ready_main_phase(only_artifact)
    _put(only_artifact, Card(id="Ring", name="Ring", type_line="Artifact"))
    _put(only_artifact, creature("Victim"), controller="p2")
    _, offered = _soul_transfer_modes(only_artifact, p1)
    assert (0, 1) not in offered

    both = make_engine()
    p1 = _ready_main_phase(both)
    _put(both, Card(id="Ring", name="Ring", type_line="Artifact"))
    _put(both, Card(id="Ench", name="Ench", type_line="Enchantment"))
    _put(both, creature("Victim"), controller="p2")
    _, offered = _soul_transfer_modes(both, p1)
    assert (0, 1) in offered


def test_choose_both_instead_resolves_both_modes_in_printed_order():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    _put(eng, Card(id="Ring", name="Ring", type_line="Artifact"))
    _put(eng, Card(id="Ench", name="Ench", type_line="Enchantment"))
    victim = _put(eng, creature("Victim"), controller="p2")
    back = GameObject(creature("Back"), owner_id="p1")
    p1.add_to_zone(back, Zone.GRAVEYARD)
    obj = _in_hand(eng, _soul_transfer())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 3})
    eng.cast_spell(p1, obj, targets=[victim, back], mode=[0, 1])
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
    assert back in p1.hand


def test_choose_one_without_the_condition_rejects_two_modes():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    victim = _put(eng, creature("Victim"), controller="p2")
    back = GameObject(creature("Back"), owner_id="p1")
    p1.add_to_zone(back, Zone.GRAVEYARD)
    obj = _in_hand(eng, _soul_transfer())
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 3})
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, targets=[victim, back], mode=[0, 1])


# -- Intervening "if" in front of the header (RULE 603.4) ----------------------------------------------------------


WARDENS_ORACLE = (
    "Morbid — At the beginning of your end step, if a creature died this turn, choose one —\n"
    "• You gain 2 life.\n• You draw a card and you lose 1 life."
)


def _wardens():
    return Card(id="Wardens", name="Test Wardens", type_line="Creature — Elf Warlock", is_creature=True, power=3,
                toughness=4, keywords=["Morbid"], oracle_text=WARDENS_ORACLE)


def test_intervening_if_modal_trigger_keeps_its_condition_on_the_trigger():
    spec = _spec_with_modes(_wardens())
    assert spec.trigger["event"] == "STEP_BEGIN"
    assert spec.trigger["active_if"] == {"kind": "creatures_died_this_turn", "min": 1}
    assert spec.modes["choose"] == 1


def test_intervening_if_modal_trigger_runs_only_the_chosen_mode():
    eng = make_engine([land(), land()])
    p1 = _ready_main_phase(eng)
    obj = _put(eng, _wardens())
    bind_from_catalogue(obj)
    _put_trigger_on_stack(eng, obj)
    assert eng.state.pending_choice["kind"] == "trigger_mode"
    eng.rules.resolve_choice("1")  # draw a card and lose 1 life
    eng.resolve_until_stable()
    assert (p1.life, len(p1.hand)) == (19, 1)


# -- Trigger event with an "isn't that player's turn" if-clause, then the header -------------------------------------


VISION_ORACLE = (
    "Flying\nWhenever a player casts a spell, if it isn't that player's turn, choose one —\n"
    "• Put a +1/+1 counter on Vision.\n• Vision phases out."
)


def _vision():
    return Card(id="Vision", name="Vision", type_line="Legendary Artifact Creature — Synthezoid", is_creature=True,
                power=3, toughness=3, oracle_text=VISION_ORACLE)


def test_not_that_players_turn_spell_trigger_is_a_modal_trigger():
    spec = _spec_with_modes(_vision())
    assert spec.trigger["event"] == "SPELL_CAST"
    assert spec.trigger["not_controllers_turn"] is True


@pytest.mark.parametrize("mode, check", [
    ("0", lambda vision: vision.counters.get("+1/+1") == 1),
    ("1", lambda vision: getattr(vision, "phased_out", False)),
])
def test_not_that_players_turn_modes_are_chosen_when_the_trigger_is_put_on_the_stack(mode, check):
    eng = make_engine()
    _ready_main_phase(eng)
    vision = _put(eng, _vision())
    bind_from_catalogue(vision)
    ability = next(a for a in vision.triggered_abilities if a.modes)
    eng.rules.pending_triggers = [(ability, None)]
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice["kind"] == "trigger_mode"
    eng.rules.resolve_choice(mode)
    eng.resolve_until_stable()
    assert check(vision)


# -- Reflexive "When you do, choose N —" after a sacrifice (RULE 603.12) --------------------------------------------


CAESAR_ORACLE = (
    "Whenever you attack, you may sacrifice another creature. When you do, choose two —\n"
    "• Create two 1/1 red and white Soldier creature tokens with haste that are tapped and attacking.\n"
    "• You draw a card and you lose 1 life.\n"
    "• ~ deals damage equal to the number of creature tokens you control to target opponent."
)


def _caesar():
    return Card(id="Caesar", name="Test Caesar", type_line="Legendary Creature — Human Soldier", is_creature=True,
                power=4, toughness=4, oracle_text=CAESAR_ORACLE)


def test_reflexive_modal_after_a_sacrifice_cost_is_a_pay_cost_then_with_modes():
    result = parse_oracle(_caesar())
    assert result.modeled
    spec = result.specs[0]
    pay = spec.effects[0]
    assert pay.type == "pay_cost_then"
    assert pay.params["cost"] == "sacrifice another creature"
    assert pay.params["then_trigger_modes"]["choose"] == 2


def test_reflexive_modal_modes_are_chosen_only_after_the_sacrifice_was_paid():
    eng = make_engine([land(), land()])
    p1 = _ready_main_phase(eng)
    caesar = _put(eng, _caesar())
    fodder = _put(eng, creature("Fodder"))
    bind_from_catalogue(caesar)
    _put_trigger_on_stack(eng, caesar)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.rules.resolve_choice("pay")
    assert fodder not in eng.state.battlefield  # paid first
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_mode"  # RULE 603.12: modes chosen as the reflexive trigger goes on the stack
    eng.rules.resolve_choice("0")
    eng.rules.resolve_choice("1")  # create two tokens + draw and lose 1
    eng.resolve_until_stable()
    assert [o.name for o in eng.state.battlefield if o.name == "Soldier"] == ["Soldier", "Soldier"]
    assert (p1.life, len(p1.hand)) == (19, 1)
    assert eng.state.player_by_id("p2").life == 20  # the unchosen damage mode did not run


def test_reflexive_modal_declined_cost_never_reaches_the_modes():
    eng = make_engine([land()])
    p1 = _ready_main_phase(eng)
    caesar = _put(eng, _caesar())
    fodder = _put(eng, creature("Fodder"))
    bind_from_catalogue(caesar)
    _put_trigger_on_stack(eng, caesar)
    eng.resolve_until_stable()
    eng.rules.resolve_choice("decline")
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None
    assert fodder in eng.state.battlefield and not p1.hand


# -- Reflexive modal after "you may sacrifice it" under a group trigger -------------------------------------------


GORBAG_ORACLE = (
    "Whenever a Goblin or Orc you control deals combat damage to a player, you may sacrifice it. "
    "When you do, choose one —\n• Draw a card.\n• Create a Treasure token."
)


def _gorbag():
    return Card(id="Gorbag", name="Test Gorbag", type_line="Legendary Creature — Orc Soldier", is_creature=True,
                power=2, toughness=2, oracle_text=GORBAG_ORACLE)


def test_sacrifice_it_reflexive_modal_keeps_the_optional_sacrifice_and_a_modal_reflexive_trigger():
    spec = parse_oracle(_gorbag()).specs[0]
    assert spec.optional
    assert [e.type for e in spec.effects] == ["sacrifice_self", "reflexive_trigger"]
    assert spec.effects[1].params["then_trigger_modes"]["choose"] == 1


@pytest.mark.parametrize("mode, check", [
    ("0", lambda eng, p1: len(p1.hand) == 1),
    ("1", lambda eng, p1: any(o.name == "Treasure" for o in eng.state.battlefield)),
])
def test_sacrifice_it_reflexive_modal_runs_the_chosen_mode(mode, check):
    eng = make_engine([land(), land()])
    p1 = _ready_main_phase(eng)
    gorbag = _put(eng, _gorbag())
    bind_from_catalogue(gorbag)
    eng.state.current_step = "combat_damage"
    eng.rules.deal_damage(eng.state.player_by_id("p2"), 2, source=gorbag, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_choice("do")  # "you may sacrifice it"
    eng.resolve_until_stable()
    assert gorbag not in eng.state.battlefield
    assert eng.state.pending_choice["kind"] == "trigger_mode"
    eng.rules.resolve_choice(mode)
    eng.resolve_until_stable()
    assert check(eng, p1)


# -- Haunt: "When this creature enters or the creature it haunts dies, choose one —" (RULE 702.55) -----------------


PONTIFF_ORACLE = (
    "Haunt (When this creature dies, exile it haunting target creature.)\n"
    "When this creature enters or the creature it haunts dies, choose one —\n"
    "• Creatures you control get +1/+1 until end of turn.\n"
    "• Creatures you don't control get -1/-1 until end of turn."
)


def _pontiff():
    return Card(id="Pontiff", name="Test Pontiff", type_line="Creature — Human Cleric", is_creature=True, power=1,
                toughness=1, keywords=["Haunt"], oracle_text=PONTIFF_ORACLE)


def test_haunt_modal_wrapper_is_an_enters_trigger_and_a_linked_death_trigger():
    specs = [s for s in parse_oracle(_pontiff()).specs if s.modes is not None]
    assert [s.trigger["event"] for s in specs] == ["ENTERS_BATTLEFIELD", "DIES"]
    assert specs[1].effects[0].type == "haunt_linked_death"


def test_haunt_modal_death_trigger_fires_only_for_the_haunted_creature_and_chooses_its_mode():
    eng = make_engine()
    _ready_main_phase(eng)
    pontiff = _put(eng, _pontiff())
    bind_from_catalogue(pontiff)
    victim = _put(eng, creature("Victim", 3, 3), controller="p2")
    bystander = _put(eng, creature("Bystander", 1, 1), controller="p2")
    mine = _put(eng, creature("Mine", 2, 2))

    eng.rules.put_into_graveyard(pontiff)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"  # Haunt's own target; no spurious mode choice
    eng.resolve_pending_choice(victim.instance_id)
    eng.resolve_until_stable()
    assert pontiff.zone == Zone.EXILE and pontiff.haunting_instance_id == victim.instance_id

    eng.rules.put_into_graveyard(bystander)  # not the haunted creature
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None

    eng.rules.put_into_graveyard(victim)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_mode"
    eng.rules.resolve_choice("0")  # creatures you control get +1/+1
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (3, 3)


def test_haunt_modal_enters_half_chooses_a_mode_as_it_is_put_on_the_stack():
    eng = make_engine()
    _ready_main_phase(eng)
    pontiff = _put(eng, _pontiff())
    bind_from_catalogue(pontiff)
    enemy = _put(eng, creature("Enemy", 2, 2), controller="p2")
    ability = next(a for a in pontiff.triggered_abilities if a.modes and a.trigger_event == EventType.ENTERS_BATTLEFIELD)
    eng.rules.pending_triggers = [(ability, None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_choice("1")  # creatures you don't control get -1/-1
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (enemy.power, enemy.toughness) == (1, 1)


def test_three_symbol_spree_mode_destroys_for_base_plus_its_own_price():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    victim = _put(eng, creature("Victim"), controller="p2")
    card = Card(id="UA", name="Test Accident", type_line="Instant", is_instant=True, mana_cost_string="{B}",
                converted_mana_cost=1, oracle_text=(
                    "Spree (Choose one or more additional costs.)\n+ {2}{B} — Destroy target creature.\n"
                    "+ {1} — Create a 1/1 red Mercenary creature token."))
    obj = _in_hand(eng, card)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"B": 4})  # {B} + {2}{B}
    eng.cast_spell(p1, obj, targets=[victim], mode=[0])
    assert p1.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
