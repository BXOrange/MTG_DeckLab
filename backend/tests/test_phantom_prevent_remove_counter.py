"""The Phantom cycle (Phantom Centaur / Phantom Flock / Phantom Nantuko /
Phantom Nishoba / Phantom Nomad / Phantom Tiger / Phantom Wurm): "If damage
would be dealt to ~, prevent that damage. Remove a +1/+1 counter from ~."

`replacements._PHANTOM_PREVENT_RE` → `EffectSpec("prevent_damage", {"to":
"self", "amount": "all", "rider": {"kind": "remove_self_counter", ...}})`;
`RulesEngine.apply_prevent_rider` gained the `remove_self_counter` kind
(a fixed count of 1, unscaled by the prevented amount). These creatures are
printed 0/0, so losing the last counter triggers the RULE 704.5g SBA.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _state():
    p1, p2 = Player(id="p1", name="A", life=20), Player(id="p2", name="B", life=20)
    return GameState(players=[p1, p2]), p1, p2


def _bf(state, card, controller="p1"):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    bind_from_catalogue(o)
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_phantom_clause_parses():
    assert replacement_clause_specs(
        "if damage would be dealt to ~, prevent that damage. "
        "remove a +1/+1 counter from ~."
    ) == [
        EffectSpec("prevent_damage", {
            "to": "self", "amount": "all",
            "rider": {"kind": "remove_self_counter", "counter": "+1/+1", "count": 1},
        })
    ]


def test_real_card_modeled():
    c = Card(
        id="pn", name="Phantom Nantuko", type_line="Creature — Insect Monk",
        mana_cost_string="{3}{G}", is_creature=True, power=0, toughness=0,
        oracle_text=("Phantom Nantuko enters with two +1/+1 counters on it.\n"
                     "If damage would be dealt to Phantom Nantuko, prevent that "
                     "damage. Remove a +1/+1 counter from Phantom Nantuko."),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -------------------------------------------------------------------


def _phantom(state, counters=3):
    c = Card(id="ph", name="Phantom Wurm", type_line="Creature — Phantom Wurm",
             is_creature=True, power=0, toughness=0,
             oracle_text="If damage would be dealt to Phantom Wurm, prevent that "
                         "damage. Remove a +1/+1 counter from Phantom Wurm.")
    o = _bf(state, c)
    o.plus_one_counters = counters
    return o


def test_damage_is_prevented_and_one_counter_is_removed_per_hit():
    state, p1, p2 = _state()
    phantom = _phantom(state, counters=3)
    attacker = _bf(state, Card(id="atk", name="Attacker", type_line="Creature — Ogre",
                               is_creature=True, power=5, toughness=5), controller="p2")
    eng = RulesEngine(state)

    eng.deal_damage(phantom, 5, source=attacker)
    assert phantom.damage_marked == 0          # fully prevented
    assert phantom.plus_one_counters == 2      # one counter paid

    eng.deal_damage(phantom, 1, source=attacker)
    assert phantom.plus_one_counters == 1


def test_losing_the_last_counter_kills_the_phantom():
    state, p1, p2 = _state()
    phantom = _phantom(state, counters=1)
    attacker = _bf(state, Card(id="atk", name="Attacker", type_line="Creature — Ogre",
                               is_creature=True, power=3, toughness=3), controller="p2")
    eng = RulesEngine(state)

    eng.deal_damage(phantom, 3, source=attacker)
    eng.check_state_based_actions()

    assert phantom.plus_one_counters == 0
    assert phantom not in state.battlefield   # 0/0 with no counters -> RULE 704.5g
