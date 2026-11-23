"""PAR-284: "gets +A/+B for each <count>" pumps and statics (RULE 107.3, 611.2a, 613.4c).

One-shot "until end of turn" pumps bind the count once at resolution (RULE 611.2a) and stay separate from statics:
a static anthem keeps its per-unit amount plus a count selector that is re-measured at every layer pass (RULE 613.4c),
so it follows the count while the source stays on the battlefield.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _engine


def _bound_pump(oracle):
    specs = parse_effect_body(oracle)
    assert specs is not None and [s.type for s in specs] == ["bind"], specs
    return specs[0].params


def test_targeted_group_phrase_pump_binds_the_count():
    """The group-phrase reading used to win and was refused (a `for_each` body cannot hold the announced target)."""
    params = _bound_pump("target creature gets +1/+0 until end of turn for each artifact you control.")
    assert params["amount"]["selector"]["filter"] == {"card_type": "artifact"}
    assert params["effects"][0]["params"] == {"power": "$n", "toughness": 0, "target_kind": "creature"}
    shrink = _bound_pump("target creature gets -1/-1 until end of turn for each artifact you control.")
    assert shrink["effects"][0]["params"]["power"] == "-$n"


def test_leading_duration_reads_like_the_trailing_one():
    leading = _bound_pump("until end of turn, ~ gets +1/+1 for each permanent card in your graveyard.")
    trailing = _bound_pump("~ gets +1/+1 until end of turn for each permanent card in your graveyard.")
    assert leading == trailing
    doubled = _bound_pump("until end of turn, up to one target creature gets +2/+2 for each treasure you control.")
    assert doubled["amount"]["multiply"] == 2


def test_untargeted_group_pump_keeps_the_per_object_loop():
    specs = parse_effect_body("creatures you control get +1/+0 until end of turn for each creature you control.")
    assert specs is not None and specs[0].type == "for_each"


@pytest.mark.parametrize("oracle", [
    "enchanted creature gets +1/+1 for each +1/+1 counter on other creatures you control.",  # "other" than whom
    "enchanted creature gets +1/+1 for each word in its name.",
])
def test_unmeasurable_counts_stay_unclaimed(oracle):
    assert not parse_oracle(_card("Probe", "Enchantment", oracle)).modeled


def test_group_static_row_is_a_counted_anthem():
    result = parse_oracle(_card("Boon", "Enchantment", "Creatures you control get +1/+1 for each blessing counter on ~."))
    assert result.modeled, result.unclaimed
    anthem = result.specs[0].effects[0]
    assert anthem.type == "anthem"
    assert anthem.params["power_count"] == "source_blessing_counters" == anthem.params["toughness_count"]


def test_attached_shrink_static_is_modeled():
    result = parse_oracle(_card("Curse", "Enchantment - Aura", "Enchant creature\nEnchanted creature gets -1/-1 for each Swamp you control."))
    assert result.modeled, result.unclaimed


def _creature(eng, name, owner, power):
    obj = GameObject(_card(name, "Creature - Bear", is_creature=True, power=power, toughness=power),
                     owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


def test_group_static_follows_the_counter_count_as_it_changes():
    """Boon of the Spirit Realm shape: the bonus is re-measured on every pass (RULE 613.4c), not frozen when it entered."""
    eng = _engine()
    bear = _creature(eng, "Bear", "p1", 2)
    card = _card("Boon", "Enchantment", "Creatures you control get +1/+1 for each blessing counter on ~.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    boon = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    boon.controller_id = "p1"
    attach_to_object(boon, result.specs)
    eng.state.battlefield.append(boon)
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (2, 2)
    boon.counters["blessing"] = 3
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 5)
    boon.counters["blessing"] = 1
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)


def test_attached_shrink_follows_the_swamp_count():
    eng = _engine()
    bear = _creature(eng, "Bear", "p1", 5)
    card = _card("Curse", "Enchantment - Aura", "Enchant creature\nEnchanted creature gets -1/-1 for each Swamp you control.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    aura = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    attach_to_object(aura, result.specs)
    aura.attached_to = bear.instance_id
    eng.state.battlefield.append(aura)
    eng.recompute_continuous_effects()
    assert bear.power == 5
    for i in range(2):
        swamp = GameObject(_card(f"Swamp{i}", "Basic Land — Swamp"), owner_id="p1", zone=Zone.BATTLEFIELD)
        swamp.controller_id = "p1"
        eng.state.battlefield.append(swamp)
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)


def test_targeted_one_shot_pump_resolves_with_the_count_at_resolution():
    eng = _engine()
    bear = _creature(eng, "Bear", "p1", 1)
    for i in range(3):
        art = GameObject(_card(f"Art{i}", "Artifact"), owner_id="p1", zone=Zone.BATTLEFIELD)
        art.controller_id = "p1"
        eng.state.battlefield.append(art)
    card = _card("Probe Spell", "Instant", "Target creature gets +1/+0 until end of turn for each artifact you control.",
                 is_instant=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(spell, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 1)


# --- "add {C} for each <count>" host slot (RULE 106.4) ------------------------------------------------------------


def test_add_mana_for_each_binds_the_count_to_the_mana_amount():
    params = _bound_pump("add {r} for each card in your hand.")
    assert params["effects"] == [{"type": "add_mana", "params": {"color": "R", "amount": "$n"}}]
    doubled = _bound_pump("add {c}{c} for each card in your hand.")
    assert doubled["amount"]["multiply"] == 2
    assert doubled["effects"][0]["params"] == {"color": "C", "amount": "$n"}
    # mixed colours have no single colour to repeat
    assert parse_effect_body("add {w}{u} for each card in your hand.") is None


def test_add_mana_for_each_card_in_hand_adds_that_much_mana():
    from tests.test_par284_this_way_windows import _cast

    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(3):
        p1.hand.append(GameObject(_card(f"H{i}", "Instant"), owner_id="p1", zone=Zone.HAND))
    _cast(eng, "Add {R} for each card in your hand.")
    assert p1.mana_pool.pool["R"] == 3  # the spell itself left the hand when cast


def test_add_mana_for_each_counter_on_source_modeled_with_the_trigger():
    result = parse_oracle(_card("Vault", "Artifact", "At the beginning of your first main phase, add {B} for each charge counter on ~."))
    assert result.modeled, result.unclaimed
