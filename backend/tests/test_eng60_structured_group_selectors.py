"""ENG-60: a static group scope ("Other Elves you control get +1/+1", "Attacking creatures have ...") compiles to ONE
structured ``affects`` selector -- ``{"zone": "battlefield", "of": "you"|"any", "filter": <matches_object_filter dict>}``
-- instead of flat ``subtype``/``color``/``tokens``/``card_type``/``exclude_self`` params plus a named selector string.

`continuous.group_selector_objects` reads it through `combat.matches_object_filter`; the layer results (RULE 613) must be
exactly what the retired flat vocabulary produced, which these tests run through the real engine."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle


def _card(name, text="", type_line="Creature — Bear", colors=(), **kw):
    creature = "Creature" in type_line
    return Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=2 if creature else None, toughness=2 if creature else None,
                mana_cost_string="".join(f"{{{c}}}" for c in colors), **kw)


def _place(engine, card, player="p1", token=False):
    obj = GameObject(card, owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    obj.is_token = token
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)


def _pt(engine, obj):
    engine.recompute_continuous_effects()
    return obj.power, obj.toughness


# --- parse: one structured selector, no flat group params ----------------------------------------------------------

FLAT_GROUP_KEYS = {"subtype", "color", "tokens", "card_type", "exclude_self", "object_filter",
                   "subtype_from_source", "color_from_source", "card_name_from_source"}


@pytest.mark.parametrize("clause,of,filt", [
    ("creatures you control get +1/+1.", "you", {"card_type": "creature"}),
    ("all creatures get +1/+1.", "any", {"card_type": "creature"}),
    ("other creatures you control get +1/+1.", "you", {"card_type": "creature", "not_reference": True}),
    ("other creatures get +1/+1.", "any", {"card_type": "creature", "not_reference": True}),
    ("elves you control get +1/+1.", "you", {"card_type": "creature", "subtype": "Elf"}),
    ("black creatures get +1/+1.", "any", {"card_type": "creature", "color": "B"}),
    ("white and blue creatures get +1/+1.", "any", {"card_type": "creature", "color_any": ["W", "U"]}),
    ("creature tokens you control get +1/+1.", "you", {"card_type": "creature", "token": True}),
    ("other artifact creatures you control get +1/+1.", "you",
     {"card_type_all": ["creature", "artifact"], "not_reference": True}),
    ("attacking creatures you control get +1/+1.", "you", {"card_type": "creature", "attacking": True}),
    ("attacking elves you control get +1/+1.", "you", {"card_type": "creature", "subtype": "Elf", "attacking": True}),
    ("creatures you control with flying get +1/+1.", "you", {"card_type": "creature", "keyword": "flying"}),
    ("creatures you control of the chosen type get +1/+1.", "you",
     {"card_type": "creature", "subtype_from_source": True}),
    ("commanders you control have haste.", "you", {"is_commander": True}),
    ("artifacts you control have hexproof.", "you", {"card_type": "artifact"}),
    ("other enchantments have shroud.", "any", {"card_type": "enchantment", "not_reference": True}),
    ("lands you control have hexproof.", "you", {"card_type": "land"}),
    ("vehicles you control get +1/+1.", "you", {"card_type": "artifact", "subtype": "Vehicle"}),
])
def test_group_scope_is_one_structured_selector(clause, of, filt):
    specs = static_effect_specs(clause)
    assert specs, clause
    for spec in specs:
        assert spec.params["affects"] == {"zone": "battlefield", "of": of, "filter": filt}
        assert not FLAT_GROUP_KEYS & spec.params.keys()


def test_repeated_filter_key_nests_instead_of_overwriting():
    # "Elf Warrior" style stacked adjectives plus a list would collide on one key; both operands must survive (RULE 115.1).
    from mtg_analyzer.parser.oracle.catalogue.static_rows.object_scope import _and_filters

    merged = _and_filters({"any_of": [{"subtype": "A"}]}, {"any_of": [{"subtype": "B"}]})
    assert merged == {"all_of": [{"any_of": [{"subtype": "A"}]}, {"any_of": [{"subtype": "B"}]}]}
    assert _and_filters({"card_type": "creature"}, {"token": True}) == {"card_type": "creature", "token": True}


def test_colourless_and_mixed_colour_scopes():
    from mtg_analyzer.parser.oracle.catalogue.static_rows.object_scope import _scope_color_filter

    assert _scope_color_filter(["C"]) == {"colorless": True}
    assert _scope_color_filter(["R"]) == {"color": "R"}
    assert _scope_color_filter(["C", "R", "G"]) == {"any_of": [{"colorless": True}, {"color_any": ["R", "G"]}]}


# --- engine: the structured selector picks out exactly what the flat vocabulary did ---------------------------------

def test_creatures_you_control_anthem_is_layer_correct_and_controller_scoped():
    eng = _engine()
    _place(eng, _card("Lord", "Creatures you control get +1/+1."))
    mine = _place(eng, _card("Mine"))
    theirs = _place(eng, _card("Theirs"), "p2")
    land = _place(eng, _card("Forest", type_line="Basic Land — Forest"))
    assert _pt(eng, mine) == (3, 3)
    assert _pt(eng, theirs) == (2, 2)
    assert land.power is None or _pt(eng, land) in ((None, None), (0, 0))


def test_other_excludes_the_source_for_you_control_and_global_scopes():
    eng = _engine()
    local = _place(eng, _card("Local", "Other creatures you control get +1/+1."))
    glob = _place(eng, _card("Global", "Other creatures get +2/+2."))
    ally = _place(eng, _card("Ally"))
    foe = _place(eng, _card("Foe"), "p2")
    assert _pt(eng, local) == (4, 4)   # only the global lord's +2/+2
    assert _pt(eng, glob) == (3, 3)    # only the local lord's +1/+1
    assert _pt(eng, ally) == (5, 5)
    assert _pt(eng, foe) == (4, 4)


def test_tribal_anthem_matches_subtype_including_changeling_but_not_others():
    eng = _engine()
    _place(eng, _card("Lord", "Other Elves you control get +1/+1.", "Creature — Elf"))
    elf = _place(eng, _card("Elf", type_line="Creature — Elf Warrior"))
    changeling = _place(eng, _card("Changeling", type_line="Creature — Shapeshifter", keywords=["Changeling"]))
    bear = _place(eng, _card("Bear"))
    enemy_elf = _place(eng, _card("Enemy Elf", type_line="Creature — Elf"), "p2")
    assert _pt(eng, elf) == (3, 3)
    assert _pt(eng, changeling) == (3, 3)
    assert _pt(eng, bear) == (2, 2)
    assert _pt(eng, enemy_elf) == (2, 2)


def test_colour_scoped_global_anthem_follows_the_current_colour():
    eng = _engine()
    _place(eng, _card("Bad Moon", "Black creatures get +1/+1.", "Enchantment"))
    black = _place(eng, _card("Black", colors=["B"]))
    white = _place(eng, _card("White", colors=["W"]))
    foe_black = _place(eng, _card("Foe Black", colors=["B"]), "p2")
    colorless = _place(eng, _card("Golem", type_line="Artifact Creature — Golem"))
    assert _pt(eng, black) == (3, 3) and _pt(eng, foe_black) == (3, 3)
    assert _pt(eng, white) == (2, 2) and _pt(eng, colorless) == (2, 2)


def test_tokens_only_anthem():
    eng = _engine()
    _place(eng, _card("Anointed", "Creature tokens you control get +1/+1.", "Enchantment"))
    token = _place(eng, _card("Spirit"), token=True)
    card = _place(eng, _card("Card"))
    assert _pt(eng, token) == (3, 3)
    assert _pt(eng, card) == (2, 2)


def test_artifact_creature_scope_needs_both_types():
    eng = _engine()
    _place(eng, _card("Chief", "Other artifact creatures you control get +1/+1.", "Artifact Creature — Goblin"))
    golem = _place(eng, _card("Golem", type_line="Artifact Creature — Golem"))
    bear = _place(eng, _card("Bear"))
    assert _pt(eng, golem) == (3, 3)
    assert _pt(eng, bear) == (2, 2)


def test_attacking_scope_reads_the_live_combat_state():
    eng = _engine()
    _place(eng, _card("Banner", "Attacking creatures you control have first strike.", "Enchantment"))
    attacker = _place(eng, _card("Attacker"))
    idle = _place(eng, _card("Idle"))
    enemy = _place(eng, _card("Enemy"), "p2")
    attacker.attacking = True
    enemy.attacking = True
    eng.recompute_continuous_effects()
    assert "first_strike" in attacker.granted_keywords
    assert "first_strike" not in idle.granted_keywords
    assert "first_strike" not in enemy.granted_keywords
    attacker.attacking = False
    eng.recompute_continuous_effects()
    assert "first_strike" not in attacker.granted_keywords


def test_keyword_grant_with_a_tribe_and_a_chosen_type():
    eng = _engine()
    lord = _place(eng, _card("Chooser", "Creatures you control of the chosen type have haste.", "Enchantment"))
    elf = _place(eng, _card("Elf", type_line="Creature — Elf"))
    goblin = _place(eng, _card("Goblin", type_line="Creature — Goblin"))
    eng.recompute_continuous_effects()
    assert "haste" not in elf.granted_keywords  # nothing chosen yet: the group is empty
    lord.chosen_type = "Elf"
    eng.recompute_continuous_effects()
    assert "haste" in elf.granted_keywords and "haste" not in goblin.granted_keywords


def test_filter_qualifier_and_adjective_compose():
    eng = _engine()
    _place(eng, _card("Banner", "Legendary creatures you control with flying get +1/+1.", "Enchantment"))
    flier = _place(eng, _card("Flier", type_line="Legendary Creature — Bird", keywords=["Flying"], is_legendary=True))
    grounded = _place(eng, _card("Grounded", type_line="Legendary Creature — Bear", is_legendary=True))
    plain_flier = _place(eng, _card("Plain", keywords=["Flying"]))
    assert _pt(eng, flier) == (3, 3)
    assert _pt(eng, grounded) == (2, 2)
    assert _pt(eng, plain_flier) == (2, 2)


def test_group_protection_scope_resolves():
    eng = _engine()
    _place(eng, _card("Warden", "White creatures you control have protection from black.", "Enchantment"))
    white = _place(eng, _card("White", colors=["W"]))
    green = _place(eng, _card("Green", colors=["G"]))
    eng.recompute_continuous_effects()
    assert white.granted_protections == {"B"} and not green.granted_protections


@pytest.mark.parametrize("text", [
    "Other Elves you control get +1/+1 and have haste.",
    "Attacking creatures you control get +1/+1.",
    "Creatures you control of the chosen color have flying.",
])
def test_oracle_texts_stay_modeled(text):
    assert parse_oracle(_card("Probe", text, "Enchantment")).coverage is MODELED


def test_structured_group_without_a_controller_still_resolves_an_unscoped_group():
    # ``of: any`` names every player's permanents: it needs no reference player (a bare fixture), unlike "you".
    from mtg_analyzer.game import continuous

    eng = _engine()
    mine = _place(eng, _card("Mine"))
    theirs = _place(eng, _card("Theirs"), "p2")
    group = continuous.group_selector_objects(
        eng.state, None, {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}})
    assert {o.instance_id for o in group} == {mine.instance_id, theirs.instance_id}
    assert continuous.group_selector_objects(
        eng.state, None, {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}) == []


def test_board_summary_labels_a_structured_selector_as_text():
    from mtg_analyzer.game import continuous

    eng = _engine()
    _place(eng, _card("Lord", "Other Elves you control get +1/+1.", "Creature — Elf"))
    eng.recompute_continuous_effects()
    rows = continuous.active_static_abilities(eng.state)
    assert rows and all(isinstance(row["affects"], str) for row in rows)
    assert continuous._affects_label({"zone": "battlefield", "of": "you", "filter": {"subtype": "Elf"}}) == "you: subtype=Elf"
    assert continuous._affects_label("creatures_you_control") == "creatures_you_control"


def test_emblem_guard_accepts_a_structured_selector():
    from mtg_analyzer.parser.oracle.catalogue.effect_rows.tokens_animate_misc import _emblem_unsupported_affects

    assert _emblem_unsupported_affects({"zone": "battlefield", "of": "you", "filter": {}}) is False
    assert _emblem_unsupported_affects(None) is False


# --- bare permanent-type and Vehicle scopes (the non-creature siblings) ---------------------------------------------

def test_artifacts_you_control_grant_reaches_only_my_artifacts():
    eng = _engine()
    _place(eng, _card("Abunas", "Artifacts you control have hexproof.", "Artifact Creature — Golem"))
    mine = _place(eng, _card("Rock", type_line="Artifact"))
    theirs = _place(eng, _card("Their Rock", type_line="Artifact"), "p2")
    creature = _place(eng, _card("Bear"))
    eng.recompute_continuous_effects()
    assert "hexproof" in mine.granted_keywords
    assert "hexproof" not in theirs.granted_keywords and "hexproof" not in creature.granted_keywords


def test_other_enchantments_global_grant_excludes_only_the_source():
    eng = _engine()
    src = _place(eng, _card("Sterling", "Other enchantments have shroud.", "Enchantment"))
    mine = _place(eng, _card("Ench", type_line="Enchantment"))
    theirs = _place(eng, _card("Their Ench", type_line="Enchantment"), "p2")
    eng.recompute_continuous_effects()
    assert "shroud" in mine.granted_keywords and "shroud" in theirs.granted_keywords
    assert "shroud" not in src.granted_keywords


def test_vehicles_scope_selects_my_artifact_vehicles_even_uncrewed():
    from mtg_analyzer.game import continuous

    eng = _engine()
    src = _place(eng, _card("Balthier", "Vehicles you control get +1/+1.", "Creature — Human"))
    vehicle = _place(eng, _card("Ride", type_line="Artifact — Vehicle"))
    rock = _place(eng, _card("Rock", type_line="Artifact"))
    enemy_vehicle = _place(eng, _card("Their Ride", type_line="Artifact — Vehicle"), "p2")
    (spec,) = static_effect_specs("vehicles you control get +1/+1.")
    group = continuous.group_selector_objects(eng.state, "p1", spec.params["affects"], spec.params, src=src)
    assert group == [vehicle]
    assert rock not in group and enemy_vehicle not in group
