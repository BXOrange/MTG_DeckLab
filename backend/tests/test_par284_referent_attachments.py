"""PAR-284 milestone 20: counters and attachments on a referent, part two (RULE 122.1, 301.5, 603.10a, 608.2).

"for each fungus counter on that creature" under a group dies trigger reads the dying creature's last-known counters
(`counters` amount ``of: trigger_subject``); "where X is the number of age counters on it" in a source-subject body with
plural targets is the source; "for each lore counter among Sagas you control" is a summed counter selector; and
"deals 2 damage to each creature for each Aura attached to that creature" measures each member's own attachments
(`reference: iteration`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_referent_counts import _attach, _on_battlefield
from tests.test_par284_this_way_windows import _card, _engine


def _bear(eng, name, owner="p1", power=2, toughness=2):
    return _on_battlefield(eng, _card(name, "Creature — Bear", "", is_creature=True, power=power, toughness=toughness), owner=owner)


def _tokens(eng):
    return [o for o in eng.state.battlefield if o.is_token]


def test_sporogenesis_makes_a_saproling_per_fungus_counter_the_creature_had():
    eng = _engine()
    _on_battlefield(eng, _card(
        "Spore Probe", "Enchantment",
        "Whenever a creature with a fungus counter on it dies, create a 1/1 green Saproling creature token for each fungus counter on that creature."))
    victim = _bear(eng, "Victim", owner="p2")
    victim.counters = {"fungus": 3}
    bystander = _bear(eng, "Bystander", owner="p2")
    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    assert len(_tokens(eng)) == 3
    eng.rules.destroy(bystander)  # no fungus counter: the head does not match
    eng.resolve_until_stable()
    assert len(_tokens(eng)) == 3


def test_cleopatra_betrayal_draws_for_every_counter_kind_on_the_dying_legend():
    eng = _engine()
    _on_battlefield(eng, _card(
        "Betrayal Probe", "Enchantment",
        "Whenever a legendary creature with counters on it dies, draw a card for each counter on it. You lose 2 life."))
    legend = _on_battlefield(eng, _card("Legend", "Legendary Creature — Human", "", is_creature=True, power=1, toughness=1))
    legend.counters = {"+1/+1": 2, "oil": 1}  # not a shield counter: that would stop the destruction (RULE 122.1c)
    p1 = eng.state.players[0]
    for i in range(5):
        p1.library.append(GameObject(_card(f"Lib{i}", "Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    hand, life = len(p1.hand), p1.life
    eng.rules.destroy(legend)
    eng.resolve_until_stable()
    assert len(p1.hand) - hand == 3 and life - p1.life == 2


@pytest.mark.parametrize("oracle", [
    # the firing creature's counters only count for a dies / leaves / enters head
    "Whenever a creature attacks, draw a card for each +1/+1 counter on that creature.",
    "Whenever you cast a spell, draw a card for each +1/+1 counter on that creature.",
])
def test_other_heads_do_not_name_the_firing_creature(oracle):
    assert not parse_oracle(_card("Odd", "Enchantment", oracle)).modeled


def test_magmatic_core_deals_its_age_counters_divided_among_targets():
    core_card = _card(
        "Core Probe", "Enchantment",
        "At the beginning of your end step, this enchantment deals X damage divided as you choose among any number of target "
        "creatures, where X is the number of age counters on it.")
    result = parse_oracle(core_card)
    assert result.modeled, result.unclaimed
    bind = result.specs[0].effects[0]
    assert bind.type == "bind" and bind.params["amount"] == {"kind": "counters", "counter": "age", "of": "source"}
    assert bind.params["effects"][0]["params"]["divided"] is True

    eng = _engine()
    core = _on_battlefield(eng, core_card)
    core.counters = {"age": 3}
    victim = _bear(eng, "Victim", owner="p2", toughness=9)
    other = _bear(eng, "Other", owner="p2", toughness=9)
    eng.state.current_step = "end"
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_choice(str(victim.instance_id))
    eng.rules.resolve_choice("stop")
    eng.resolve_until_stable()
    assert (victim.damage_marked, other.damage_marked) == (3, 0)  # the whole age-counter pool on the one chosen target


def test_a_single_target_keeps_the_pronoun_open():
    oracle = ("At the beginning of your end step, this enchantment deals X damage to target creature, "
              "where X is the number of age counters on it.")
    assert not parse_oracle(_card("Odd", "Enchantment", oracle)).modeled


def test_counters_among_a_group_sum_over_its_members():
    result = parse_oracle(_card(
        "Chorus Probe", "Sorcery",
        "Creatures you control get +1/+0 until end of turn for each lore counter among Sagas you control.", is_sorcery=True))
    assert result.modeled, result.unclaimed
    eng = _engine()
    saga = _on_battlefield(eng, _card("Saga Probe", "Enchantment — Saga", ""))
    saga.counters = {"lore": 3}
    ally = _bear(eng, "Ally")
    card = _card("Chorus Probe", "Sorcery", "Creatures you control get +1/+0 until end of turn for each lore counter among Sagas you control.",
                 is_sorcery=True)
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell, parse_oracle(card).specs)
    p1 = eng.state.players[0]
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert ally.power == 5


def test_bakis_curse_damages_each_creature_by_its_own_auras():
    eng = _engine()
    plain = _bear(eng, "Plain", power=1, toughness=9)
    one = _bear(eng, "One", power=1, toughness=9)
    two = _bear(eng, "Two", power=1, toughness=9, owner="p2")
    _attach(eng, "Aura A", "Aura", one)
    for i in range(2):
        _attach(eng, f"Aura B{i}", "Aura", two)
    card = _card("Baki Probe", "Sorcery", "~ deals 2 damage to each creature for each Aura attached to that creature.", is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert (plain.damage_marked, one.damage_marked, two.damage_marked) == (0, 2, 4)


def test_an_iteration_reference_outside_a_loop_is_refused():
    from mtg_analyzer.parser.oracle.gate import _iteration_reference_ok
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
    stray = AbilitySpec(ability_kind="spell_effect", effects=[EffectSpec("bind", {
        "name": "n", "amount": {"kind": "count_selector", "selector": {"zone": "battlefield", "of": "any"}, "reference": "iteration"},
        "effects": []})])
    assert not _iteration_reference_ok(stray)
