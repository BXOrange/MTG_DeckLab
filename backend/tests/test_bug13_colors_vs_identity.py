"""BUG-13: a permanent's actual colours (RULE 105.2/202.2) are not its Commander
colour identity (RULE 903.4). Rules-text mana symbols widen identity only."""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.targeting import TargetSpec, _color_ok
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.card_colors import printed_colors
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _obj(card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    return obj


def _forest():
    # Scryfall: Forest has colors [] but color_identity ["G"].
    return Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True,
                color_identity={"G"}, oracle_text="({T}: Add {G}.)")


def _offcolor_creature():
    # Mono-red cost, rules-text {G} activation: identity R+G, colour R only.
    return Card(id="x", name="Offcolor Beast", type_line="Creature — Beast", is_creature=True,
                power=2, toughness=2, mana_cost_string="{1}{R}", converted_mana_cost=2,
                color_identity={"R", "G"}, oracle_text="{G}: ~ gets +1/+1 until end of turn.")


def test_forest_is_colorless():
    assert _obj(_forest()).colors == set()


def test_costless_land_colorless_but_dryad_arbor_green():
    arbor = Card(id="da", name="Dryad Arbor", type_line="Land Creature — Forest Dryad",
                 is_land=True, is_creature=True, power=1, toughness=1, color_identity={"G"})
    assert _obj(arbor).colors == {"G"}


def test_offcolor_activated_cost_does_not_color_the_permanent():
    obj = _obj(_offcolor_creature())
    assert obj.colors == {"R"}
    assert obj.card.color_identity == {"R", "G"}


def test_hybrid_and_phyrexian_symbols_color_the_card():
    card = Card(id="h", name="Hybrid", type_line="Creature — Elf", is_creature=True, power=1,
                toughness=1, mana_cost_string="{G/W}{B/P}", color_identity={"G", "W", "B"})
    assert printed_colors(card) == {"G", "W", "B"}


def test_devoid_is_colorless():
    card = Card(id="d", name="Devoid Drone", type_line="Creature — Eldrazi Drone", is_creature=True,
                power=2, toughness=2, mana_cost_string="{1}{R}", color_identity={"R"},
                oracle_text="Devoid\nWhen this enters, do things.", keywords=["Devoid"])
    assert _obj(card).colors == set()


def test_colorless_cost_with_colored_text_symbol_is_colorless():
    card = Card(id="s", name="Sol-ish", type_line="Artifact", mana_cost_string="{2}",
                color_identity={"G"}, oracle_text="{T}: Add {G}.")
    assert _obj(card).colors == set()


def test_color_indicator_back_face_uses_its_own_indicator_not_front_identity():
    # Brutal Cathar // Moonrage Brute: front identity is W+R, the back's indicator is red only.
    front = Card(id="bc", name="Brutal Cathar", type_line="Creature — Human Soldier", is_creature=True,
                 power=2, toughness=2, mana_cost_string="{2}{W}", color_identity={"W", "R"},
                 layout="transform", back_name="Moonrage Brute", back_type_line="Creature — Werewolf",
                 back_power=3, back_toughness=3)
    back = front.back_face()
    assert back.mana_cost_string == ""
    assert _obj(back).colors == {"R"}
    assert _obj(front).colors == {"W"}


def test_colorless_back_face_is_colorless():
    front = Card(id="ua", name="Ulvenwald Mysteries Stand-in", type_line="Creature — Human", is_creature=True,
                 power=1, toughness=1, mana_cost_string="{1}{G}", color_identity={"G"}, layout="transform",
                 back_name="Ulvenwald Abomination", back_type_line="Creature — Eldrazi Werewolf",
                 back_power=4, back_toughness=4)
    assert _obj(front.back_face()).colors == set()


def test_zero_cost_indicator_card_is_its_indicator_color():
    # RULE 204: Slaughter Pact costs {0} but is black.
    pact = Card(id="sp", name="Slaughter Pact", type_line="Instant", is_instant=True,
                mana_cost_string="{0}", color_identity={"B"})
    assert _obj(pact).colors == {"B"}


def test_costless_card_without_indicator_is_colorless_even_with_identity():
    card = Card(id="cl", name="Plain Costless Thing", type_line="Creature — Spirit", is_creature=True,
                power=1, toughness=1, color_identity={"R"})
    assert printed_colors(card) == frozenset()


def test_token_keeps_its_recorded_colors():
    token = Card(id="t", name="Spirit", type_line="Token Creature — Spirit", is_creature=True,
                 power=1, toughness=1, color_identity={"W"})
    assert printed_colors(token) == {"W"}


def test_all_colors_cda_text():
    card = Card(id="tc", name="Transguild Courier", type_line="Artifact Creature — Golem", is_creature=True,
                power=3, toughness=3, mana_cost_string="{4}", color_identity=set(),
                oracle_text="Transguild Courier is all colors.")
    assert printed_colors(card) == {"W", "U", "B", "R", "G"}


def test_colorless_cda_text():
    card = Card(id="gf", name="Ghostfire", type_line="Instant", is_instant=True,
                mana_cost_string="{2}{R}", color_identity={"R"},
                oracle_text="Ghostfire is colorless.\nGhostfire deals 3 damage to any target.")
    assert printed_colors(card) == frozenset()


def test_land_back_face_of_modal_dfc_is_colorless():
    front = Card(id="mdfc", name="Spell Side", type_line="Instant", is_instant=True,
                 mana_cost_string="{2}{R}", color_identity={"R", "G"}, layout="modal_dfc",
                 back_name="Land Side", back_type_line="Land")
    assert _obj(front.back_face()).colors == set()
    assert _obj(front).colors == {"R"}


def test_layer5_add_color_adds_onto_printed_colors_not_identity():
    obj = _obj(_offcolor_creature())
    obj._derived_colors = obj.colors
    obj._derived_colors.update({"U"})
    assert obj.colors == {"R", "U"}
    forest = _obj(_forest())
    forest._derived_colors = forest.colors
    forest._derived_colors.update({"B"})
    assert forest.colors == {"B"}


def test_targeting_green_filter_ignores_identity_only_green():
    spec = TargetSpec(kind="creature", color="G")
    assert not _color_ok(spec, _obj(_offcolor_creature()).colors)
    green = Card(id="g", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                 toughness=2, mana_cost_string="{1}{G}", color_identity={"G"})
    assert _color_ok(spec, _obj(green).colors)


def test_protection_from_green_ignores_forest_identity():
    pro = Card(id="p", name="Knight", type_line="Creature — Knight", is_creature=True, power=2,
               toughness=2, mana_cost_string="{W}{W}", color_identity={"W"},
               oracle_text="Protection from green")
    holder = _obj(pro, "p2")
    assert not combat.is_protected_from(holder, _obj(_forest()))
    assert not combat.is_protected_from(holder, _obj(_offcolor_creature()))
    green = Card(id="g", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                 toughness=2, mana_cost_string="{1}{G}", color_identity={"G"})
    assert combat.is_protected_from(holder, _obj(green))


def test_card_query_color_search_uses_actual_colors():
    assert not card_query._color_matches(_offcolor_creature(), "G")
    assert card_query._color_matches(_forest(), "colorless")
    assert card_query._color_matches(_offcolor_creature(), "R")


def test_copy_with_set_colors_overrides_mana_cost_colors():
    from mtg_analyzer.models.cards.card_colors import with_color_override

    card = with_color_override(_offcolor_creature().as_copy(set_colors=["U"]), ["U"])
    assert printed_colors(card) == {"U"}
