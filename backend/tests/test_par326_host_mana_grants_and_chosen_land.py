"""PAR-326: a quoted "{T}, Sacrifice ~: Add ..." grant to an Aura/Equipment host (Lotus Ring, Minimus Containment)
and "Enchanted land is the chosen type." (Convincing Mirage, Phantasmal Terrain), executed on a real GameEngine."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

LOTUS_RING = (
    "Indestructible\nEquipped creature gets +3/+3 and has vigilance and "
    '"{T}, Sacrifice this creature: Add three mana of any one color."\nEquip {3}'
)
MINIMUS = (
    "Enchant nonland permanent\nEnchanted permanent is a Treasure artifact with "
    '"{T}, Sacrifice this artifact: Add one mana of any color," and it loses all other abilities. '
    "(If it was a creature, it's no longer a creature.)"
)
MIRAGE = "Enchant land\nAs this Aura enters, choose a basic land type.\nEnchanted land is the chosen type."


def _engine():
    return GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)


def _put(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _forest():
    return Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True)


@pytest.mark.parametrize("name,text,type_line", [
    ("Lotus Ring", LOTUS_RING, "Artifact — Equipment"),
    ("Minimus Containment", MINIMUS, "Enchantment — Aura"),
    ("Convincing Mirage", MIRAGE, "Enchantment — Aura"),
])
def test_cards_are_modeled(name, text, type_line):
    assert parse_oracle(Card(id=name, name=name, oracle_text=text, type_line=type_line)).modeled


def test_lotus_ring_host_taps_and_sacrifices_itself_for_three_mana():
    eng = _engine()
    host = _put(eng, _bear())
    ring = _put(eng, Card(id="r", name="Lotus Ring", oracle_text=LOTUS_RING, type_line="Artifact — Equipment"))
    ring.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (5, 5)
    player = eng.state.player_by_id("p1")
    gained = eng.tap_for_mana(player, host, option_index=2)  # option order WUBRG: index 2 = B
    assert gained == {"B": 3}
    assert host not in eng.state.battlefield  # RULE 113.7a: "~" is the host creature, not the Equipment
    assert ring in eng.state.battlefield
    # Detached, the grant is gone.
    other = _put(eng, _bear("Other"))
    eng.recompute_continuous_effects()
    with pytest.raises(Exception):
        eng.tap_for_mana(player, other)


def test_minimus_containment_makes_host_a_treasure_that_sacrifices_for_one_mana():
    eng = _engine()
    host = _put(eng, _bear())
    aura = _put(eng, Card(id="m", name="Minimus Containment", oracle_text=MINIMUS, type_line="Enchantment — Aura"))
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert not host.is_creature and "artifact" in host.type_words and host.has_subtype("Treasure")
    assert not host.has_subtype("Bear")
    gained = eng.tap_for_mana(eng.state.player_by_id("p1"), host, option_index=1)  # U
    assert gained == {"U": 1}
    assert host not in eng.state.battlefield  # the host sacrificed itself; the Aura then falls off (RULE 704.5m)


def test_minimus_containment_ends_with_the_aura():
    eng = _engine()
    host = _put(eng, _bear())
    aura = _put(eng, Card(id="m", name="Minimus Containment", oracle_text=MINIMUS, type_line="Enchantment — Aura"))
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.is_creature and host.has_subtype("Bear") and not host.has_subtype("Treasure")


def test_convincing_mirage_chosen_type_replaces_land_types_and_reverts():
    eng = _engine()
    land = _put(eng, _forest())
    aura = _put(eng, Card(id="c", name="Convincing Mirage", oracle_text=MIRAGE, type_line="Enchantment — Aura"))
    aura.attached_to = land.instance_id
    eng.recompute_continuous_effects()
    assert land.has_subtype("Forest")  # nothing chosen yet: no effect
    aura.chosen_type = "Island"
    eng.recompute_continuous_effects()
    assert land.has_subtype("Island") and not land.has_subtype("Forest")  # RULE 305.7
    gained = eng.tap_for_mana(eng.state.player_by_id("p1"), land)
    assert gained == {"U": 1}  # the Island's intrinsic mana ability replaces the Forest's
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert land.has_subtype("Forest") and not land.has_subtype("Island")


def test_unchosen_or_non_land_statement_fails_closed():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
    assert static_effect_specs("enchanted creature is the chosen type.") is None
