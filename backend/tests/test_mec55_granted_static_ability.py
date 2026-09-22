"""MEC-55 — granted *static* abilities: "X have '<static ability>'" where
the quoted body is itself an anthem / lord (Inspiring Leader —
"Commander creatures you own have 'Creature tokens you control get
+2/+2.'").

`_quoted_ability_grant_effects_list` claims a `static` inner body and
emits `grant_static_ability`; `continuous._apply_layer_6_ability` builds
one `StaticAbility` per affected object (sourced on it, so its own "you
control" selector resolves against the granted-to permanent's
controller), `_battlefield_static_abilities` yields it, and `recompute`
re-gathers after layer 6 so a granted anthem settles in the same pass.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


# --- parse -----------------------------------------------------------


def test_static_inner_body_emits_grant_static_ability():
    specs = static_effect_specs(
        'commander creatures you own have "creature tokens you control get +2/+2."'
    )
    assert specs is not None and len(specs) == 1
    s = specs[0]
    assert s.type == "grant_static_ability"
    assert s.params["affects"] == "commander_creatures_you_own"
    (inner,) = s.params["static_specs"]
    assert inner["type"] == "anthem"
    assert inner["params"]["power"] == 2 and inner["params"]["tokens"] is True
    assert inner["params"]["affects"] == "creatures_you_control"


def test_self_scoped_inner_static_resolves_per_granted_to_object():
    # "~ gets +1/+1", once regranted, means the affected object itself: the same
    # `continuous._apply_layer_6_ability` "sourced on it" mechanism that already
    # re-scopes "creature tokens you control" per granted-to permanent's own
    # controller (`test_static_inner_body_emits_grant_static_ability`) sources
    # the inner `StaticAbility` on each regrant target, so a bare "self" affects
    # resolves correctly per object rather than needing its own referent.
    specs = static_effect_specs('commander creatures you own have "~ gets +1/+1."')
    assert specs is not None and len(specs) == 1
    (inner,) = specs[0].params["static_specs"]
    assert inner == {"type": "anthem", "params": {"power": 1, "toughness": 1, "affects": "self"}}


# --- execute -------------------------------------------------------


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _bf(st, card, controller="p1", token=False, commander=False):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.is_token = token
    o.is_commander = commander
    st.add_to_battlefield(o)
    return o


def test_inspiring_leader_grants_token_anthem_via_commander_creature():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="il", name="Inspiring Leader", type_line="Enchantment",
        oracle_text='Commander creatures you own have "Creature tokens you '
                    'control get +2/+2."'))
    bind_from_catalogue(granter)

    cmd = _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                       is_creature=True, power=3, toughness=3), commander=True)
    tok = _bf(st, Card(id="t", name="Soldier", type_line="Token Creature — Soldier",
                       is_creature=True, power=1, toughness=1), token=True)
    non_tok = _bf(st, Card(id="b", name="Bear", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2))
    opp_tok = _bf(st, Card(id="o", name="Opp Soldier",
                           type_line="Token Creature — Soldier", is_creature=True,
                           power=1, toughness=1), controller="p2", token=True)

    eng.recompute_continuous_effects()
    assert (tok.power, tok.toughness) == (3, 3)         # +2/+2
    assert (non_tok.power, non_tok.toughness) == (2, 2)  # not a token
    assert (opp_tok.power, opp_tok.toughness) == (1, 1)  # not yours

    # no commander creature → no grant
    st.battlefield.remove(cmd)
    eng.recompute_continuous_effects()
    assert (tok.power, tok.toughness) == (1, 1)


def test_two_commander_creatures_stack_the_granted_anthem():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="il", name="Inspiring Leader", type_line="Enchantment",
        oracle_text='Commander creatures you own have "Creature tokens you '
                    'control get +2/+2."'))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k1", name="C1", type_line="Legendary Creature — Human",
                 is_creature=True, power=3, toughness=3), commander=True)
    _bf(st, Card(id="k2", name="C2", type_line="Legendary Creature — Elf",
                 is_creature=True, power=3, toughness=3), commander=True)
    tok = _bf(st, Card(id="t", name="Soldier",
                       type_line="Token Creature — Soldier", is_creature=True,
                       power=1, toughness=1), token=True)
    eng.recompute_continuous_effects()
    assert (tok.power, tok.toughness) == (5, 5)  # +2/+2 from each


def test_self_scoped_grant_boosts_each_commander_creature_not_just_one():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="il3", name="Inspiring Leader Clone", type_line="Enchantment",
        oracle_text='Commander creatures you own have "~ gets +1/+1."'))
    bind_from_catalogue(granter)
    c1 = _bf(st, Card(id="k3", name="C3", type_line="Legendary Creature — Human",
                      is_creature=True, power=3, toughness=3), commander=True)
    c2 = _bf(st, Card(id="k4", name="C4", type_line="Legendary Creature — Elf",
                      is_creature=True, power=3, toughness=3), commander=True)
    bear = _bf(st, Card(id="b3", name="Bear", type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2))
    eng.recompute_continuous_effects()
    assert (c1.power, c1.toughness) == (4, 4)
    assert (c2.power, c2.toughness) == (4, 4)
    assert (bear.power, bear.toughness) == (2, 2)  # not a commander creature


def test_inspiring_leader_modeled():
    c = Card(id="il2", name="Inspiring Leader", type_line="Enchantment",
             oracle_text='Commander creatures you own have "Creature tokens you '
                         'control get +2/+2."')
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed
