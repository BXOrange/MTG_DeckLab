"""BUG-1: an "Equip ..." line that is more than a bare equip cost was claimed as a keyword line and its text dropped
(RULE 702.6). It now parses to a ``cost_reduction`` (``scope="activation"``, ``attach_kind="equip"``) row, or stays unclaimed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line

BASE = {"scope": "activation", "attach_kind": "equip"}


def _row(text):
    return static_effect_specs(text.rstrip(".").lower())


def test_discount_rows_parse():
    assert _row("Equip abilities you activate cost {1} less to activate.")[0].params == {**BASE, "generic": 1}
    assert _row("Equip abilities you activate of other Equipment cost {1} less to activate.")[0].params == {
        **BASE, "generic": 1, "other_equipment": True}
    assert _row("Equip abilities you activate that target ~ cost {2} less to activate.")[0].params == {
        **BASE, "generic": 2, "targets_source": True}
    assert _row("Equip {3}. This ability costs {1} less to activate for each other Equipment you control.")[0].params[
        "per"] == "other_permanents_you_control_of_subtype_equipment"
    assert _row("Equip {3}. This ability costs {1} less to activate for each +1/+1 counter on the creature it targets.")[
        0].params["per_target_plus_one_counter"] is True


def test_riders_are_no_longer_keyword_lines():
    for line in (
        "Equip abilities you activate that target enchanted creature cost {3} less to activate.",
        "Equip {3}. This ability costs {1} less to activate for each artifact you control.",
    ):
        seg = segment_line(line.lower(), allow_spell_effect=False, provenance=None)
        assert not seg.keyword_line
        assert not seg.claimed


@pytest.mark.parametrize("line", ["Equip {2}", "Equip legendary creature {3}", "Equip—Pay 3 life.", "Equip {1}{W}"])
def test_bare_equip_lines_stay_keyword_lines(line):
    seg = segment_line(line.lower(), allow_spell_effect=False, provenance=None)
    assert seg.keyword_line and seg.claimed


def test_unknown_target_slot_fails_the_card_closed():
    card = Card(id="x", name="Strong Back", type_line="Enchantment — Aura",
                oracle_text="Equip abilities you activate that target enchanted creature cost {3} less to activate.")
    assert parse_oracle(card).coverage != "MODELED"


# --- execute ----------------------------------------------------------------


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _equipment(name, cost, extra=""):
    return Card(id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=f"Equipped creature gets +1/+1.\nEquip {cost}{extra}")


def _creature(eng, name, text="", controller="p1"):
    return _bf(eng, Card(id=name, name=name, type_line="Creature — Human", is_creature=True, power=2, toughness=2,
                         oracle_text=text), controller)


def _equip(eng, equip_obj, targets):
    [ability] = [a for a in equip_obj.activated_abilities if a.attach_kind == "equip"]
    mana = eng._reduced_activation_mana(equip_obj, ability.cost.mana, ability.cost, targets=targets, activating_player_id="p1")
    return mana.converted_mana_cost


def test_global_discount_applies_to_every_equip_and_floors_at_zero():
    eng = _engine()
    _creature(eng, "Headmaster", "Equip abilities you activate cost {1} less to activate.")
    host = _creature(eng, "Host")
    assert _equip(eng, _bf(eng, _equipment("Sword", "{3}")), [host]) == 2
    assert _equip(eng, _bf(eng, _equipment("Cheap", "{0}")), [host]) == 0
    other = _bf(eng, _equipment("Opp Sword", "{3}"), "p2")
    [ability] = [a for a in other.activated_abilities if a.attach_kind == "equip"]
    assert eng._reduced_activation_mana(other, ability.cost.mana, ability.cost, targets=[host],
                                        activating_player_id="p2").converted_mana_cost == 3


def test_other_equipment_slot_excludes_the_source_itself():
    eng = _engine()
    whip = _bf(eng, Card(id="w", name="Whip", type_line="Artifact — Equipment", keywords=["Equip"],
                         oracle_text="Equip abilities you activate of other Equipment cost {1} less to activate.\nEquip {3}"))
    sword = _bf(eng, _equipment("Sword", "{3}"))
    host = _creature(eng, "Host")
    assert _equip(eng, whip, [host]) == 3
    assert _equip(eng, sword, [host]) == 2


def test_targets_source_slot_needs_the_creature_as_target():
    eng = _engine()
    mauler = _creature(eng, "Mauler", "Equip abilities you activate that target ~ cost {2} less to activate.")
    other = _creature(eng, "Other")
    sword = _bf(eng, _equipment("Sword", "{3}"))
    assert _equip(eng, sword, [mauler]) == 1
    assert _equip(eng, sword, [other]) == 3


def test_plate_armor_counts_other_equipment_only():
    eng = _engine()
    armor = _bf(eng, _equipment("Armor", "{3}", ". This ability costs {1} less to activate for each other Equipment you control."))
    host = _creature(eng, "Host")
    assert _equip(eng, armor, [host]) == 3
    _bf(eng, _equipment("A", "{1}"))
    _bf(eng, _equipment("B", "{1}"))
    assert _equip(eng, armor, [host]) == 1


def test_warriors_blades_counts_counters_on_the_target():
    eng = _engine()
    blades = _bf(eng, _equipment("Blades", "{3}",
                                 ". This ability costs {1} less to activate for each +1/+1 counter on the creature it targets."))
    plain, counted = _creature(eng, "Plain"), _creature(eng, "Counted")
    counted.plus_one_counters = 2
    assert _equip(eng, blades, [plain]) == 3
    assert _equip(eng, blades, [counted]) == 1
    counted.plus_one_counters = 9
    assert _equip(eng, blades, [counted]) == 0


def test_war_whip_keeps_its_printed_equip_cost():
    # The discount line precedes "Equip {3}{R}{W}"; the keyword cost must not be read off the discount's "{1}".
    card = Card(id="w", name="Whip", type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text="Equip abilities you activate of other Equipment cost {1} less to activate.\n"
                            "Equipped creature has double strike.\nEquip {3}{R}{W}")
    [kw] = [s for s in parse_oracle(card).specs if s.ability_kind == "keyword"]
    assert kw.keyword["cost"] == "{3}{R}{W}"


def test_equip_once_each_turn_rider_is_carried_not_dropped():
    # Leather Armor: "Equip {0}. Activate only once each turn." stays a keyword line, now with the cap on the ability.
    text = "Equipped creature gets +0/+1.\nEquip {0}. Activate only once each turn."
    card = Card(id="l", name="Leather", type_line="Artifact — Equipment", keywords=["Equip"], oracle_text=text)
    assert parse_oracle(card).coverage == "MODELED"
    eng = _engine()
    armor = _bf(eng, card)
    [ability] = [a for a in armor.activated_abilities if a.attach_kind == "equip"]
    assert ability.once_per_turn is True
    # A choice cost with the same rider stays unclaimed.
    seg = segment_line("equip\u2014pay {3} or discard a card. activate only once each turn.", allow_spell_effect=False, provenance=None)
    assert not seg.claimed


# --- non-mana equip costs (BUG-1: "Equip--<cost>" must never bind as a free equip) ------------------------------------------------


def _dash_equipment(cost_line, name="Axe"):
    return Card(id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=f"Equipped creature gets +2/+2.\n{cost_line}")


@pytest.mark.parametrize("line,cost", [
    ("Equip—Sacrifice a creature.", "Sacrifice a creature"),
    ("Equip—Pay 3 life.", "Pay 3 life"),
    ("Equip—Discard a card.", "Discard a card"),
    ("Equip—Pay {E}{E}.", "Pay {E}{E}"),
    ("Equip—{2}, Pay 2 life.", "{2}, Pay 2 life"),
    ("Equip—Sacrifice another nonland permanent. Activate only once each turn.", "Sacrifice another nonland permanent"),
])
def test_non_mana_equip_cost_is_carried_as_text(line, cost):
    card = _dash_equipment(line)
    result = parse_oracle(card)
    assert result.coverage == "MODELED", result.unclaimed
    [kw] = [s for s in result.specs if s.ability_kind == "keyword"]
    assert kw.keyword["cost"] == cost
    assert bool(kw.keyword.get("once_per_turn")) == ("once each turn" in line)


@pytest.mark.parametrize("line", [
    "Equip—Pay {3} or discard a card.",
    "Equip—Pay {3} or remove a counter from this Equipment.",
    "Equip—Pay 1 life for each card in your hand.",
])
def test_unrepresentable_equip_cost_fails_closed_and_never_binds_free(line):
    card = _dash_equipment(line)
    result = parse_oracle(card)
    assert result.coverage != "MODELED"
    [kw] = [s for s in result.specs if s.ability_kind == "keyword"]
    assert "cost" not in kw.keyword
    obj = _bf(_engine(), card)
    assert not [a for a in obj.activated_abilities if a.attach_kind == "equip"]


def test_sacrifice_equip_cost_is_paid_and_gates_the_activation():
    eng = _engine()
    player = eng.state.player_by_id("p1")
    axe = _bf(eng, _dash_equipment("Equip—Sacrifice a creature."))
    host, fodder = _creature(eng, "Host"), _creature(eng, "Fodder")
    [ability] = [a for a in axe.activated_abilities if a.attach_kind == "equip"]
    assert ability.cost.sacrifice == "creature" and ability.cost.mana.converted_mana_cost == 0
    _to_main(eng)
    assert eng.can_activate(player, axe, ability, targets=[host])
    eng.activate_ability(player, axe, 0, targets=[host], sacrifice_choice=fodder.instance_id)
    eng.resolve_until_stable() if hasattr(eng, "resolve_until_stable") else None
    assert fodder.zone == Zone.GRAVEYARD
    assert axe.attached_to == host.instance_id
    # With no creature left to sacrifice but the host, the cost cannot be paid on a second equipment... sacrifice the host itself.
    axe2 = _bf(eng, _dash_equipment("Equip—Sacrifice a creature.", "Axe2"))
    eng.state.battlefield[:] = [o for o in eng.state.battlefield if o is not host and o is not fodder]
    [ability2] = [a for a in axe2.activated_abilities if a.attach_kind == "equip"]
    assert not eng.can_activate(player, axe2, ability2, targets=[host])


def test_life_equip_cost_is_paid_and_unaffordable_is_illegal():
    eng = _engine()
    player = eng.state.player_by_id("p1")
    lash = _bf(eng, _dash_equipment("Equip—Pay 3 life.", "Lash"))
    host = _creature(eng, "Host")
    [ability] = [a for a in lash.activated_abilities if a.attach_kind == "equip"]
    _to_main(eng)
    life = player.life
    assert eng.can_activate(player, lash, ability, targets=[host])
    eng.activate_ability(player, lash, 0, targets=[host])
    assert player.life == life - 3
    player.life = 2
    assert not eng.can_activate(player, lash, ability, targets=[host])


def _to_main(eng):
    eng.state.current_step = "main1"


# --- the claim and the binder agree: a MODELED Equip card always binds an equip ability -------------------------------------------

_REAL_EQUIP_TEXTS = {
    "Dark Knight's Greatsword": (
        "Job select (When this Equipment enters, create a 1/1 colorless Hero creature token, then attach this to it.)\n"
        "Equipped creature gets +3/+0 and is a Knight in addition to its other types.\n"
        "Chaosbringer — Equip—Pay 3 life. Activate only once each turn."),
    "Shredder's Armor": (
        "Equipped creature gets +2/+1.\nWhen this Equipment enters, attach it to target creature you control.\n"
        "Equip—Sacrifice another nonland permanent. Activate only once each turn."),
    "Leather Armor": "Equipped creature gets +0/+1 and has ward {1}.\nEquip {0}. Activate only once each turn.",
    "Nightmare Lash": "Equipped creature gets +1/+1 for each Swamp you control.\nEquip—Pay 3 life.",
    "Demonmail Hauberk": "Equipped creature gets +4/+2.\nEquip—Sacrifice a creature.",
}


@pytest.mark.parametrize("name", sorted(_REAL_EQUIP_TEXTS))
def test_modeled_equip_card_binds_an_equip_ability(name):
    card = Card(id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=_REAL_EQUIP_TEXTS[name])
    assert parse_oracle(card).coverage == "MODELED"
    [ability] = [a for a in _bf(_engine(), card).activated_abilities if a.attach_kind == "equip"]
    assert ability.cost.mana.converted_mana_cost == 0 or name == "Leather Armor"


def test_greatsword_binds_pay_life_and_once_per_turn():
    card = Card(id="g", name="Dark Knight's Greatsword", type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=_REAL_EQUIP_TEXTS["Dark Knight's Greatsword"])
    [ability] = [a for a in _bf(_engine(), card).activated_abilities if a.attach_kind == "equip"]
    assert ability.cost.pay_life == 3 and ability.once_per_turn is True


@pytest.mark.parametrize("name,line", [
    ("Bloodthorn Flail", "Equip—Pay {3} or discard a card."),
    ("Gavel of the Righteous", "Equip—Pay {3} or remove a counter from this Equipment."),
    ("Hand of Vecna", "Equip—Pay 1 life for each card in your hand.\nEquip {2}"),
    ("Cost-less", "Equip"),
])
def test_equip_card_without_a_representable_cost_is_unmodeled(name, line):
    card = Card(id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=f"Equipped creature gets +2/+2.\n{line}")
    assert parse_oracle(card).coverage == "UNMODELED"
