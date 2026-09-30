"""PAR-134: a state / supertype / designation adjective in a static's (or a
"target …" phrase's) scope is a *filter*, not a creature subtype.

`static_handlers._scope` used to turn any word before "creatures you control"
into ``subtype: "<Word>"``, so "Tapped / Untapped / Legendary / Nonlegendary /
Nontoken / Multicolored / Commander creatures you control have …" granted to
creatures of a subtype nobody has (wrong-but-MODELED). The adjective now
becomes a `combat.matches_object_filter` dict (`subgrammars.scope_adjective`),
shipped as the static's ``object_filter`` param and applied by
`continuous.group_selector_objects`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs


def _static(clause: str):
    specs = static_effect_specs(clause)
    assert specs, f"not claimed: {clause!r}"
    return specs


def _params(clause: str, index: int = 0) -> dict:
    return _static(clause)[index].params


# ---------------------------------------------------------------------------
# Parsing — the adjective is a filter, never ``subtype``
# ---------------------------------------------------------------------------

# (clause, expected object_filter, expected `affects`)
ADJECTIVE_CASES = [
    ("untapped creatures you control get +0/+2.", {"tapped": False}, "creatures_you_control"),
    ("other tapped creatures you control have indestructible.", {"tapped": True},
     "other_creatures_you_control"),
    ("legendary creatures you control get +1/+1.", {"legendary": True}, "creatures_you_control"),
    ("nonlegendary creatures you control get +1/+1.", {"nonlegendary": True},
     "creatures_you_control"),
    ("other nontoken creatures you control get +1/+1.", {"nontoken": True},
     "other_creatures_you_control"),
    ("multicolored creatures you control have flying.", {"multicolored": True},
     "creatures_you_control"),
    ("commander creatures you control get +2/+2.", {"is_commander": True},
     "creatures_you_control"),
    ("modified creatures you control have lifelink.", {"modified": True},
     "creatures_you_control"),
    ("snow creatures you control get +1/+1.", {"snow": True}, "creatures_you_control"),
    ("nonblack creatures get -1/-1.", {"without_color": ["B"]}, "all_creatures"),
    ("nonhuman creatures you control get +1/+1.", {"without_subtype": "Human"},
     "creatures_you_control"),
    ("nonattacking creatures you control get +1/+1.", {"attacking": False},
     "creatures_you_control"),
    ("other historic creatures you control have double strike.",
     {"any_of": [{"legendary": True}, {"card_type": "artifact"}, {"subtype": "Saga"}]},
     "other_creatures_you_control"),
]


@pytest.mark.parametrize("clause,filt,affects", ADJECTIVE_CASES)
def test_adjective_becomes_an_object_filter_not_a_subtype(clause, filt, affects):
    for spec in _static(clause):
        assert spec.params["object_filter"] == filt
        assert spec.params["affects"] == affects
        assert "subtype" not in spec.params  # the bug: subtype == "Tapped"


def test_adjectives_combine_with_colour_and_card_type():
    params = _params("white legendary creatures you control have banding.")
    assert params["color"] == ["W"] and params["object_filter"] == {"legendary": True}
    assert "subtype" not in params
    params = _params("nonlegendary artifact creatures you control have myriad.")
    assert params["card_type"] == "artifact"
    assert params["object_filter"] == {"nonlegendary": True}
    assert "subtype" not in params


def test_adjective_combines_with_a_real_subtype():
    # General's Enforcer / Kashi-Tribe Elite: a *real* subtype plus a supertype.
    params = _params("legendary humans you control have indestructible.")
    assert params["subtype"] == "Human"
    assert params["object_filter"] == {"legendary": True}


def test_commanders_scope_is_every_permanent_not_only_creatures():
    # A planeswalker can be a commander (RULE 903.3), so "Commanders you
    # control have …" must not be limited to creatures.
    params = _params("commanders you control have protection from everything.")
    assert params["affects"] == "permanents_you_control"
    assert params["object_filter"] == {"is_commander": True}
    assert "subtype" not in params


@pytest.mark.parametrize("clause,alternatives", [
    ("other ninja and rogue creatures you control get +1/+1.",
     [{"subtype": "Ninja"}, {"subtype": "Rogue"}]),
    ("other snow and zombie creatures you control get +1/+1.",
     [{"snow": True}, {"subtype": "Zombie"}]),
    ("green creatures and white creatures have protection from gorgons.",
     [{"color": "G"}, {"color": "W"}]),
    ("saproling creatures and other treefolk creatures get +1/+1.",
     [{"subtype": "Saproling"}, {"subtype": "Treefolk", "not_reference": True}]),
])
def test_coordinated_list_is_an_or_of_its_parts(clause, alternatives):
    params = _params(clause)
    assert params["object_filter"] == {"any_of": alternatives}
    assert "subtype" not in params


def test_colour_connector_is_still_one_scope_not_a_list():
    params = _params("white and blue creatures you control get +1/+1.")
    assert params["color"] == ["W", "U"]
    assert "object_filter" not in params


def test_plain_subtype_scope_is_unchanged():
    params = _params("goblins you control get +1/+1.")
    assert params["subtype"] == "Goblin" and "object_filter" not in params


def test_a_list_with_a_controller_phrase_inside_fails_closed():
    # Rukarumel, Biologist: "Slivers you control and nontoken creatures you
    # control are the chosen type …" — this used to become subtype "Slivers
    # you control and nontoken". Not one expressible scope → not claimed.
    assert not static_effect_specs(
        "slivers you control and nontoken creatures you control are the chosen type "
        "in addition to their other creature types."
    )
    assert not parse_oracle(_card(
        "Rukarumel, Biologist",
        "As Rukarumel enters, choose a creature type.\n"
        "Slivers you control and nontoken creatures you control are the chosen type in "
        "addition to their other creature types.",
    )).coverage is MODELED


# "target <adjective> creature" — the second producer of the same bug
# (`_pump_subtype_target` read the adjective as a subtype).
@pytest.mark.parametrize("clause,filt", [
    ("target legendary creature gets +1/+1 until end of turn", {"legendary": True}),
    ("target multicolored creature gets +2/+2 until end of turn", {"multicolored": True}),
    ("target snow creature gets +1/+1 until end of turn", {"snow": True}),
    ("target colorless creature gains haste until end of turn", {"colorless": True}),
    ("target nonattacking creature gains reach until end of turn", {"attacking": False}),
])
def test_target_adjective_is_a_creature_filter(clause, filt):
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    (spec,) = match_clause(clause)
    assert spec.params["creature_filter"] == filt


def test_blocker_restriction_non_subtype_is_a_negated_subtype():
    # Flow of Maggots — "can't be blocked by non-Wall creatures" (the
    # `object_filter` caller of `_scope`, which merges the adjective filter).
    result = parse_oracle(_card(
        "Flow of Maggots", "This creature can't be blocked by non-Wall creatures.",
        type_line="Creature — Insect"))
    assert result.coverage is MODELED
    blob = repr(result.effect_specs)
    assert "without_subtype" in blob and "'subtype': 'Non-wall'" not in blob


def test_target_real_subtype_is_still_a_subtype():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    (spec,) = match_clause("target sliver creature gets +2/+2 until end of turn")
    assert spec.params["creature_filter"] == {"subtype": "Sliver"}


# ---------------------------------------------------------------------------
# Real cards end to end
# ---------------------------------------------------------------------------


def _card(name, text, *, type_line="Creature — Human", pt=(2, 2), **kw):
    kw.setdefault("is_creature", "Creature" in type_line)
    kw.setdefault("is_legendary", "Legendary" in type_line)
    power, toughness = pt if kw["is_creature"] else (None, None)
    return Card(
        id=name, name=name, type_line=type_line, power=power, toughness=toughness,
        oracle_text=text, **kw,
    )


@pytest.mark.parametrize("name,text", [
    ("Castle", "Untapped creatures you control get +0/+2."),
    ("Adept Watershaper", "Other tapped creatures you control have indestructible."),
    ("Always Watching", "Nontoken creatures you control get +1/+1 and have vigilance."),
    ("Bastion Protector", "Commander creatures you control get +2/+2 and have indestructible."),
])
def test_real_card_text_stays_modeled_without_a_bogus_subtype(name, text):
    result = parse_oracle(_card(name, text))
    assert result.coverage is MODELED
    for spec in result.effect_specs:
        for effect in spec.effects:
            assert effect.params.get("subtype") in (None, "")


# ---------------------------------------------------------------------------
# Execution — the filter is actually applied by the layer engine
# ---------------------------------------------------------------------------


def _engine():
    return GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1", **flags):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    for key, value in flags.items():
        setattr(obj, key, value)
    eng.state.add_to_battlefield(obj)
    return obj


def _vanilla(name, pt=(2, 2), type_line="Creature — Human", **kw):
    return _card(name, "", type_line=type_line, pt=pt, **kw)


def test_untapped_anthem_only_boosts_untapped_creatures():
    eng = _engine()
    _put(eng, _card("Castle", "Untapped creatures you control get +0/+2.",
                    type_line="Legendary Land", pt=(0, 0), is_creature=False))
    up = _put(eng, _vanilla("Up"))
    down = _put(eng, _vanilla("Down"), tapped=True)
    opp = _put(eng, _vanilla("Theirs"), controller="p2")
    eng.recompute_continuous_effects()
    assert (up.power, up.toughness) == (2, 4)
    assert (down.power, down.toughness) == (2, 2)
    assert (opp.power, opp.toughness) == (2, 2)  # "you control"


def test_tapped_grant_excludes_the_source_and_untapped_creatures():
    eng = _engine()
    src = _put(eng, _card(
        "Adept Watershaper", "Other tapped creatures you control have indestructible."))
    src.tapped = True
    tapped = _put(eng, _vanilla("Tapped"), tapped=True)
    untapped = _put(eng, _vanilla("Untapped"))
    eng.recompute_continuous_effects()
    assert combat.has(tapped, "indestructible")
    assert not combat.has(untapped, "indestructible")
    assert not combat.has(src, "indestructible")  # "Other"


def test_nontoken_and_legendary_filters_read_the_real_object():
    eng = _engine()
    _put(eng, _card("Always Watching", "Nontoken creatures you control get +1/+1.",
                    type_line="Enchantment", pt=(0, 0), is_creature=False))
    real = _put(eng, _vanilla("Real"))
    token = _put(eng, _vanilla("Token"), is_token=True)
    eng.recompute_continuous_effects()
    assert real.power == 3 and token.power == 2


def test_legendary_filter_applies_to_legendary_creatures_only():
    eng = _engine()
    _put(eng, _card("Lord", "Legendary creatures you control get +1/+1.", type_line="Enchantment",
                    pt=(0, 0), is_creature=False))
    legend = _put(eng, _vanilla("Legend", type_line="Legendary Creature — Human"))
    plain = _put(eng, _vanilla("Plain"))
    eng.recompute_continuous_effects()
    assert legend.power == 3 and plain.power == 2


def test_nonblack_global_anthem_hits_only_nonblack_creatures():
    eng = _engine()
    _put(eng, _card("Evincar", "Nonblack creatures get -1/-1.", pt=(3, 3)))
    black = _put(eng, _vanilla("Black", color_identity=["B"]))
    white = _put(eng, _vanilla("White", color_identity=["W"]))
    eng.recompute_continuous_effects()
    assert black.power == 2 and white.power == 1


def test_multicolored_grant():
    eng = _engine()
    _put(eng, _card("Glider", "Multicolored creatures you control have flying."))
    gold = _put(eng, _vanilla("Gold", color_identity=["W", "U"]))
    mono = _put(eng, _vanilla("Mono", color_identity=["W"]))
    eng.recompute_continuous_effects()
    assert combat.has(gold, "flying") and not combat.has(mono, "flying")


def test_commander_grant_reaches_a_noncreature_commander():
    eng = _engine()
    _put(eng, _card("Praetor", "Commanders you control have protection from everything."))
    walker = _put(eng, _card("Walker", "", type_line="Legendary Planeswalker", is_creature=False,
                             pt=(0, 0)), is_commander=True)
    other = _put(eng, _vanilla("Other"))
    eng.recompute_continuous_effects()
    assert [t["description"] for t in walker.static_trace] == ["gains protection from everything"]
    assert other.static_trace == []


def test_modified_creatures_are_those_with_counters_or_attachments():
    eng = _engine()
    _put(eng, _card("Envoy", "Modified creatures you control have lifelink."))
    countered = _put(eng, _vanilla("Countered"))
    countered.counters["+1/+1"] = 1
    equipped = _put(eng, _vanilla("Equipped"))
    gear = _put(eng, _card("Sword", "", type_line="Artifact — Equipment", is_creature=False))
    gear.attached_to = equipped.instance_id
    plain = _put(eng, _vanilla("Plain"))
    eng.recompute_continuous_effects()
    assert combat.has(countered, "lifelink") and combat.has(equipped, "lifelink")
    assert not combat.has(plain, "lifelink")


def test_modified_aura_must_share_the_permanents_controller():
    # RULE 700.9: only an Aura its controller controls modifies a permanent.
    eng = _engine()
    _put(eng, _card("Envoy", "Modified creatures you control have lifelink."))
    mine = _put(eng, _vanilla("Mine"))
    aura = _put(eng, _card("Aura", "", type_line="Enchantment — Aura", is_creature=False),
                controller="p2")
    aura.attached_to = mine.instance_id
    eng.recompute_continuous_effects()
    assert not combat.has(mine, "lifelink")
    aura.controller_id = "p1"
    eng.recompute_continuous_effects()
    assert combat.has(mine, "lifelink")


def test_coordinated_list_matches_either_part():
    eng = _engine()
    src = _put(eng, _card("Silver-Fur Master", "Other Ninja and Rogue creatures you control get +1/+1.",
                          type_line="Creature — Rat Ninja"))
    ninja = _put(eng, _vanilla("N", type_line="Creature — Human Ninja"))
    rogue = _put(eng, _vanilla("R", type_line="Creature — Human Rogue"))
    other = _put(eng, _vanilla("O", type_line="Creature — Human Warrior"))
    eng.recompute_continuous_effects()
    assert ninja.power == 3 and rogue.power == 3 and other.power == 2
    assert src.power == 2  # "Other": the source is a Ninja but not its own target


def test_object_filter_nonattacking_key_and_modified_key():
    eng = _engine()
    a = _put(eng, _vanilla("A"))
    b = _put(eng, _vanilla("B"), attacking=True)
    assert combat.matches_object_filter(a, {"attacking": False})
    assert not combat.matches_object_filter(b, {"attacking": False})
    assert combat.matches_object_filter(b, {"attacking": True})
    assert not combat.matches_object_filter(a, {"modified": True}, state=eng.state)
    assert not combat.matches_object_filter(a, {"modified": True})  # no state → no match


@pytest.mark.parametrize("effect_type,extra", [
    ("anthem", {"power": 1, "toughness": 1}),
    ("grant_keyword", {"keywords": ["flying"]}),
    ("grant_protection_static", {"protections": ["everything"]}),
])
def test_every_static_type_the_scope_parser_feeds_keeps_the_object_filter(effect_type, extra):
    # A factory that silently dropped ``object_filter`` would *broaden* the
    # effect to every creature you control — guard each consumer.
    from mtg_analyzer.game.effects import EffectRegistry

    filt = {"tapped": True}
    effect = EffectRegistry.create(
        effect_type, {"affects": "creatures_you_control", "object_filter": filt, **extra})
    assert effect.params["object_filter"] == filt
