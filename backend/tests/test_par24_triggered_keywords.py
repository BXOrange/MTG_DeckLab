"""PAR-24 — triggered keyword abilities that were parser-*recognized* (flag
keyword rows, docked onto `GameObject.intrinsic_keywords`) but had zero
engine consumer, so every cache card carrying only one of them was inert:

* **Prowess** (702.108a) — "whenever you cast a noncreature spell, ~ gets
  +1/+1 until end of turn."
* **Exalted** (702.83a) — "whenever a creature you control attacks alone,
  that creature gets +1/+1 until end of turn."
* **Battle cry** (702.92a) — "whenever ~ attacks, each other attacking
  creature gets +1/+0 until end of turn."
* **Mentor** (702.134a) — "whenever ~ attacks, put a +1/+1 counter on
  target attacking creature with lesser power."

Each is synthesized in `effect_binder._KEYWORD_TRIGGERED_BUILDERS` and
exercised here against a real `GameEngine` — bound, triggered, board
asserted — per the "parse-only verification masks runtime bugs" lesson.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, keywords=None, power=2, toughness=2, oracle_text="",
              type_line="Creature — Human"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _instant(name="Shock", cost="{R}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_instant=True,
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_attackers(eng):
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()


# -- Prowess (RULE 702.108a) --------------------------------------------


def test_prowess_pumps_on_noncreature_spell_but_not_creature_spell():
    eng = _engine()
    state = eng.state
    monk = _put(state, _creature("Monastery Swiftspear", keywords=["Prowess"],
                                 power=1, toughness=2))
    assert parse_oracle(monk.card).coverage != UNMODELED

    p1 = state.player_by_id("p1")
    state.current_step = "main1"
    state.active_player_index = 0

    shock = GameObject(_instant("Shock"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(shock, Zone.HAND)
    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, shock)
    eng.resolve_until_stable()

    assert (monk.power, monk.toughness) == (2, 3)  # +1/+1 from prowess

    # A creature spell must NOT trigger it.
    bear = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2, mana_cost_string="{1}{G}",
             converted_mana_cost=2),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.add_to_zone(bear, Zone.HAND)
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, bear)
    eng.resolve_until_stable()
    assert (monk.power, monk.toughness) == (2, 3)  # unchanged


# -- Exalted (RULE 702.83a) --------------------------------------------


def test_exalted_pumps_the_lone_attacker():
    eng = _engine()
    state = eng.state
    _put(state, _creature("Rafiq of the Many", keywords=["Exalted"], power=3, toughness=3))
    lone = _put(state, _creature("Lone Knight", power=2, toughness=2))
    _to_attackers(eng)
    eng.declare_attackers(state.active_player, [lone])
    eng.advance_step()  # leaving declare_attackers fires ATTACKS_ALONE
    eng.resolve_until_stable()

    assert (lone.power, lone.toughness) == (3, 3)  # +1/+1 from exalted


def test_exalted_does_not_pump_when_two_attack():
    eng = _engine()
    state = eng.state
    _put(state, _creature("Rafiq of the Many", keywords=["Exalted"], power=3, toughness=3))
    a = _put(state, _creature("Knight A", power=2, toughness=2))
    b = _put(state, _creature("Knight B", power=2, toughness=2))
    _to_attackers(eng)
    eng.declare_attackers(state.active_player, [a, b])
    eng.advance_step()
    eng.resolve_until_stable()

    assert (a.power, b.power) == (2, 2)  # not attacking alone → no exalted


# -- Battle cry (RULE 702.92a) ---------------------------------------


def test_battle_cry_pumps_each_other_attacker():
    eng = _engine()
    state = eng.state
    crier = _put(state, _creature("Accorder Paladin", keywords=["Battle Cry"],
                                  power=3, toughness=1))
    ally = _put(state, _creature("Ally", power=2, toughness=2))
    _to_attackers(eng)
    eng.declare_attackers(state.active_player, [crier, ally])
    eng.resolve_until_stable()

    assert (ally.power, ally.toughness) == (3, 2)  # +1/+0
    assert (crier.power, crier.toughness) == (3, 1)  # "each *other*" — not itself


# -- Mentor (RULE 702.134a) ----------------------------------------


def test_mentor_puts_counter_on_lesser_power_attacker():
    eng = _engine()
    state = eng.state
    mentor = _put(state, _creature("Mentor Captain", keywords=["Mentor"],
                                   power=3, toughness=2))
    smaller = _put(state, _creature("Goblin", power=1, toughness=1))
    _to_attackers(eng)
    eng.declare_attackers(state.active_player, [mentor, smaller])
    eng.advance_step()  # leaving declare_attackers places the queued trigger
    assert state.pending_choice is not None  # "target attacking creature with lesser power"
    eng.resolve_pending_choice(smaller.instance_id)
    eng.resolve_until_stable()

    assert smaller.counters.get("+1/+1", 0) == 1
    assert (smaller.power, smaller.toughness) == (2, 2)


def test_mentor_has_no_target_when_no_attacker_has_lesser_power():
    eng = _engine()
    state = eng.state
    mentor = _put(state, _creature("Mentor Captain", keywords=["Mentor"],
                                   power=2, toughness=2))
    bigger = _put(state, _creature("Ogre", power=4, toughness=4))
    _to_attackers(eng)
    eng.declare_attackers(state.active_player, [mentor, bigger])
    eng.advance_step()
    eng.resolve_until_stable()

    assert state.pending_choice is None  # RULE 603.3c: no legal target, dropped
    assert bigger.counters.get("+1/+1", 0) == 0  # 4 >= 2, illegal target
