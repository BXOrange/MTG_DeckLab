"""PAR-284 milestone 10: counts of counters and attachments on a referent (RULE 122.1, 301.5, 303.4, 603.10a).

"for each counter on it" counts counters of every kind (`counters` amount, ``counter: "*"``), read as last-known
information for a dies trigger; "for each Equipment / Aura attached to ~ / it" is a selector over the battlefield with
the `attached_to_reference` filter (the host is the source, or the firing object under a group trigger).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _engine


def _on_battlefield(eng, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    attach_to_object(obj, result.specs)
    eng.state.battlefield.append(obj)
    return obj


def _attach(eng, name, subtype, host):
    gear = GameObject(_card(name, f"Artifact — {subtype}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    gear.parametric_keywords = {"equip": {"cost": "{1}"}}  # what keeps the attachment legal to the RULE 704.5n re-check
    gear.controller_id = "p1"
    gear.attached_to = host.instance_id
    eng.state.battlefield.append(gear)
    return gear


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Kinsbaile Dies", "Creature — Kithkin", "When this creature dies, create a 1/1 white Kithkin Soldier creature token for each counter on it."),
    ("Indominus Draw", "Creature — Dinosaur", "When this creature enters, draw a card for each counter on it."),
    ("Joraga Life", "Artifact", "{2}, {T}, Sacrifice this artifact: You gain 1 life for each counter on this artifact."),
    ("Kemba Cats", "Creature — Cat", "At the beginning of your upkeep, create a 2/2 white Cat creature token for each Equipment attached to this creature."),
    ("Catti Counter", "Creature — Human", "Whenever this creature attacks, put a +1/+1 counter on it for each Equipment attached to it."),
])
def test_real_wordings_are_modeled(name, type_line, oracle):
    result = parse_oracle(_card(name, type_line, oracle, is_creature="Creature" in type_line))
    assert result.modeled, result.unclaimed


def test_dies_trigger_counts_the_counters_it_had_on_the_battlefield():
    eng = _engine()
    card = _card("Kinsbaile Dies", "Creature — Kithkin",
                 "When this creature dies, create a 1/1 white Kithkin Soldier creature token for each counter on it.",
                 is_creature=True, power=1, toughness=1)
    creature = _on_battlefield(eng, card)
    creature.counters = {"+1/+1": 2, "flying": 1}
    before = len([o for o in eng.state.battlefield if o.is_token])
    eng.rules.destroy(creature)
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.is_token]) - before == 3  # every counter kind, as it died


def test_attack_trigger_adds_a_counter_per_attached_equipment():
    eng = _engine()
    card = _card("Catti Counter", "Creature — Human",
                 "Whenever this creature attacks, put a +1/+1 counter on it for each Equipment attached to it.",
                 is_creature=True, power=1, toughness=1)
    creature = _on_battlefield(eng, card)
    creature.summoning_sick = False
    for i in range(2):
        _attach(eng, f"Blade{i}", "Equipment", creature)
    _attach(eng, "Unrelated", "Equipment", _on_battlefield(eng, _card("Other", "Creature — Bear", "", is_creature=True, power=1, toughness=1)))
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.players[0], [creature])
    eng.resolve_until_stable()
    assert creature.counters.get("+1/+1", 0) == 2


def test_sacrificed_source_counts_its_counters_as_last_known_information():
    # Twitching Doll shape: the cost sacrificed ~, then "for each counter on ~" still sees the counters it had (RULE 608.2h).
    eng = _engine()
    card = _card("Doll Probe", "Artifact Creature — Spider",
                 "{T}, Sacrifice this creature: Create a 2/2 green Spider creature token with reach for each counter on this creature.",
                 is_creature=True, power=1, toughness=1)
    doll = _on_battlefield(eng, card)
    doll.summoning_sick = False
    doll.counters = {"nest": 3}
    eng.activate_ability(eng.state.players[0], doll, 0)
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.is_token]) == 3


def test_flay_essence_gains_life_for_the_counters_on_the_exiled_creature():
    eng = _engine()
    victim = _on_battlefield(eng, _card("Victim", "Creature — Bear", "", is_creature=True, power=1, toughness=1), owner="p2")
    victim.counters = {"+1/+1": 2, "flying": 1}
    card = _card("Flay Probe", "Sorcery", "Exile target creature or planeswalker. You gain life equal to the number of counters on it.",
                 is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 1})
    before = p1.life
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert p1.life - before == 3


def test_a_group_trigger_does_not_read_the_source_counters_for_it():
    card = _card("Noir Probe", "Creature — Human", "Whenever a creature you control attacks alone, put a +1/+1 counter on it. "
                 "Then surveil X, where X is the number of counters on it.", is_creature=True, power=1, toughness=1)
    assert not parse_oracle(card).modeled


def test_anthem_counts_the_attachments_on_its_own_source():
    # Kellan shape: other creatures get +1/+0 for each Aura and Equipment attached to ~ (re-measured every pass).
    eng = _engine()
    lord = _on_battlefield(eng, _card("Lord Probe", "Creature — Faerie",
                                      "Other creatures you control get +1/+0 for each Aura and Equipment attached to this creature.",
                                      is_creature=True, power=1, toughness=1))
    ally = _on_battlefield(eng, _card("Ally", "Creature — Bear", "", is_creature=True, power=2, toughness=2))
    eng.recompute_continuous_effects()
    assert ally.power == 2
    for i in range(2):
        _attach(eng, f"Blade{i}", "Equipment", lord)
    eng.recompute_continuous_effects()
    assert ally.power == 4 and lord.power == 1
