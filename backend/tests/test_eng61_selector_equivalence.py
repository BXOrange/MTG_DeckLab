"""ENG-61: the structured group selector reproduces the old named strings.

Every named group-selector string (and flat group param combination) the
hand-written ``card_catalogue`` entries were migrated off is replaced by
``{"zone": "battlefield", "of": ..., "filter": {...}}``. This file proves each
mapping once, per shape, on several real boards instead of per card:

* ``group_selector_objects`` (the static ``affects`` / one-shot ``selector``
  reader) returns the same object set for the old form and the new one;
* ``mass_selector_objects`` (the one-shot ``destroy``/``exile``/``return``
  ``selector`` reader) agrees with the structured ``group`` form.

``MAPPING`` / ``flat_params_to_filter`` are the single source of truth the
migration used, so the test covers exactly what was rewritten.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effects.damage_draw import _mass_selector_objects
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player

P1, P2 = "p1", "p2"


def structured(of: str, **filt) -> dict:
    return {"zone": "battlefield", "of": of, "filter": filt}


#: old named string -> the structured selector that replaces it.
MAPPING: dict[str, dict] = {
    "creatures_you_control": structured("you", card_type="creature"),
    "other_creatures_you_control": structured("you", card_type="creature", not_reference=True),
    "all_creatures": structured("any", card_type="creature"),
    "all_other_creatures": structured("any", card_type="creature", not_reference=True),
    "lands_you_control": structured("you", card_type="land"),
    "all_lands": structured("any", card_type="land"),
    "artifacts_you_control": structured("you", card_type="artifact"),
    "permanents_you_control": structured("you"),
    "nonland_permanents_you_control": structured("you", without_card_type="land"),
    "all_permanents": structured("any"),
    "opponents_permanents": structured("opponents"),
    "creatures_opponents_control": structured("opponents", card_type="creature"),
    "nontoken_creatures_you_control": structured("you", card_type="creature", nontoken=True),
    "non_human_creatures_you_control": structured("you", card_type="creature", without_subtype="human"),
    "other_nonhuman_creatures_you_control": structured(
        "you", card_type="creature", not_reference=True, without_subtype="human"),
    # RULE 108.3: ownership, not control, for "creatures you own".
    "commander_creatures_you_own": structured(
        "any", card_type="creature", is_commander=True, owned_by_you=True),
    "attacking_creatures": structured("any", card_type="creature", attacking=True),
    "attacking_creatures_you_control": structured("you", card_type="creature", attacking=True),
    "other_attacking_creatures": structured("any", card_type="creature", attacking=True, not_reference=True),
    "creatures_opponents_control_with_a_counter": structured("opponents", card_type="creature", has_counter=True),
    # The named subtype families carry their subtype in the string.
    "creatures_you_control_of_type_elf": structured("you", card_type="creature", subtype="elf"),
    "creatures_you_control_of_type_cleric": structured("you", card_type="creature", subtype="cleric"),
    "creatures_you_control_of_type_phyrexian": structured("you", card_type="creature", subtype="phyrexian"),
    "creatures_you_control_of_type_halfling": structured("you", card_type="creature", subtype="halfling"),
    "lands_you_control_of_type_island": structured("you", card_type="land", subtype="island"),
    "lands_you_control_of_type_plains": structured("you", card_type="land", subtype="plains"),
    "lands_you_control_of_type_mountain": structured("you", card_type="land", subtype="mountain"),
    "lands_you_control_of_type_swamp": structured("you", card_type="land", subtype="swamp"),
    "lands_you_control_of_type_forest": structured("you", card_type="land", subtype="forest"),
}

#: The strings the one-shot mass ``destroy``/``exile``/``return_to_hand`` reader
#: (`_mass_selector_objects`) names, mapped to its ``group`` replacement.
MASS_MAPPING: dict[str, dict] = {
    "all_creatures": structured("any", card_type="creature"),
    "all_artifacts": structured("any", card_type="artifact"),
    "all_enchantments": structured("any", card_type="enchantment"),
    "all_artifacts_and_enchantments": structured("any", card_type_any=["artifact", "enchantment"]),
    "all_planeswalkers": structured("any", card_type="planeswalker"),
    "all_permanents": structured("any"),
    "all_lands": structured("any", card_type="land"),
    "all_nonland_permanents": structured("any", without_card_type="land"),
    "all_other_creatures": structured("any", card_type="creature", not_reference=True),
    "opponents_creatures": structured("opponents", card_type="creature"),
    "opponents_artifacts": structured("opponents", card_type="artifact"),
    "other_permanents_you_control": structured("you", not_reference=True),
}


def flat_params_to_filter(params: dict) -> tuple[dict, dict]:
    """Fold the flat group params that map one-to-one onto filter keys.

    Returns ``(filter_additions, remaining_params)``; anything not listed stays flat
    (`continuous.group_selector_objects` still applies it after the structured branch).
    """
    add: dict = {}
    rest = dict(params)
    if "subtype" in rest and isinstance(rest["subtype"], str):
        add["subtype"] = rest.pop("subtype")
    if rest.get("tokens") is True:
        add["token"] = True
        rest.pop("tokens")
    if rest.get("exclude_self") is True:
        add["not_reference"] = True
        rest.pop("exclude_self")
    if rest.get("subtype_from_source") is True:
        add["subtype_from_source"] = True
        rest.pop("subtype_from_source")
    return add, rest


def with_flat(structured_sel: dict, add: dict) -> dict:
    return {**structured_sel, "filter": {**structured_sel["filter"], **add}}


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


def _card(name, type_line, cost="", power=None, toughness=None, **kw):
    kind = type_line.partition("—")[0].lower()
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        is_creature="creature" in kind, is_land="land" in kind,
        power=power, toughness=toughness, **kw,
    )


def _put(state, card, controller=P1, owner=None, **attrs):
    obj = GameObject(card, owner_id=owner or controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    for key, value in attrs.items():
        setattr(obj, key, value)
    state.add_to_battlefield(obj)
    return obj


def _board(variant: int):
    """A two-player board; variant 0 is rich, later ones shift roles/subsets."""
    state = GameState(players=[Player(id=P1, life=20), Player(id=P2, life=20)])
    objs: dict[str, GameObject] = {}
    objs["source"] = _put(state, _card("Source", "Legendary Creature — Elf Warrior", "{1}{G}", 2, 2))
    objs["source"].chosen_type = "Elf"
    objs["elf"] = _put(state, _card("Elf", "Creature — Elf", "{G}", 1, 1))
    objs["cleric"] = _put(state, _card("Cleric", "Creature — Human Cleric", "{W}", 1, 1))
    objs["changeling"] = _put(state, _card(
        "Changeling", "Creature — Shapeshifter", "{1}{B}", 1, 1,
        keywords=["Changeling"], oracle_text="Changeling"))
    objs["token"] = _put(state, _card("Elf Token", "Token Creature — Elf Warrior", "", 1, 1), is_token=True)
    objs["golem"] = _put(state, _card("Golem", "Artifact Creature — Golem", "{3}", 3, 3))
    objs["vehicle"] = _put(state, _card("Ride", "Artifact — Vehicle", "{2}", None, None))
    objs["forest"] = _put(state, _card("Forest", "Basic Land — Forest"))
    objs["nonbasic"] = _put(state, _card("Cave", "Land — Island Plains"))
    objs["swamp"] = _put(state, _card("Swamp", "Basic Land — Swamp"))
    objs["mountain"] = _put(state, _card("Mountain", "Basic Land — Mountain"))
    objs["ench"] = _put(state, _card("Aura", "Enchantment", "{1}{W}"))
    objs["walker"] = _put(state, _card("Jace", "Legendary Planeswalker — Jace", "{2}{U}{U}"))
    objs["legend"] = _put(state, _card("Legend", "Legendary Creature — Phyrexian", "{B}{B}", 2, 2))
    objs["attacker"] = _put(state, _card("Attacker", "Creature — Halfling", "{R}", 1, 1), attacking=True)
    objs["countered"] = _put(state, _card("Counterer", "Creature — Human", "{U}", 1, 1))
    objs["countered"].counters["+1/+1"] = 2
    objs["commander"] = _put(state, _card("Cmdr", "Legendary Creature — Cleric", "{W}{U}", 2, 2), is_commander=True)
    objs["phased"] = _put(state, _card("Ghost", "Creature — Elf", "{G}", 1, 1), phased_out=True)
    # Opponent
    objs["o_bear"] = _put(state, _card("OBear", "Creature — Bear", "{1}{G}", 2, 2), controller=P2)
    objs["o_human"] = _put(state, _card("OHuman", "Creature — Human Soldier", "{W}", 1, 1), controller=P2)
    objs["o_elf_tok"] = _put(state, _card("OToken", "Token Creature — Elf", "", 1, 1), controller=P2, is_token=True)
    objs["o_artifact"] = _put(state, _card("OArt", "Artifact", "{2}"), controller=P2)
    objs["o_land"] = _put(state, _card("OIsland", "Basic Land — Island"), controller=P2)
    objs["o_ench"] = _put(state, _card("OEnch", "Enchantment", "{2}"), controller=P2)
    objs["o_cmdr"] = _put(state, _card("OCmdr", "Legendary Creature — Cleric", "{B}", 1, 1),
                          controller=P2, is_commander=True)
    objs["o_attacker"] = _put(state, _card("OAtk", "Creature — Elf", "{G}", 1, 1), controller=P2, attacking=True)
    objs["o_countered"] = _put(state, _card("OCnt", "Creature — Bear", "{G}", 1, 1), controller=P2)
    objs["o_countered"].counters["+1/+1"] = 1
    # Stolen: p2 owns it, p1 controls it; and p1's commander under p2's control.
    objs["stolen"] = _put(state, _card("Stolen", "Creature — Cleric", "{W}", 2, 2), controller=P1, owner=P2)
    objs["stolen_cmdr"] = _put(state, _card("StolenCmdr", "Legendary Creature — Cleric", "{W}", 2, 2),
                               controller=P2, owner=P1, is_commander=True)
    # A noncreature permanent that is not a creature even though it has P/T-less type (extra land of a type).
    objs["o_source"] = _put(state, _card("OSource", "Creature — Elf Warrior", "{G}", 2, 2), controller=P2)
    objs["o_source"].chosen_type = "Cleric"
    if variant == 1:
        # Sparse board: only the sources and a few lands.
        for key in list(objs):
            if key not in ("source", "o_source", "forest", "o_land", "stolen"):
                state.battlefield.remove(objs.pop(key))
    elif variant == 2:
        # No opponent permanents except the source; the attacker is the source itself.
        for key in [k for k in objs if k.startswith("o_") and k != "o_source"]:
            state.battlefield.remove(objs.pop(key))
        objs["source"].attacking = True
    continuous.recompute(state)
    return state, objs


VARIANTS = (0, 1, 2)
#: (controller, source key): each perspective is evaluated, so "you"/"opponents"/"own" all flip.
PERSPECTIVES = ((P1, "source"), (P2, "o_source"))


def _ids(objs):
    return sorted(o.instance_id for o in objs)


def _check(old: str, new: dict, flat: dict | None = None, new_flat: dict | None = None) -> int:
    seen = 0
    for variant in VARIANTS:
        state, objs = _board(variant)
        for controller, src_key in PERSPECTIVES:
            src = objs.get(src_key)
            if src is None:
                continue
            expected = continuous.group_selector_objects(state, controller, old, dict(flat or {}), src=src)
            actual = continuous.group_selector_objects(state, controller, new, dict(new_flat or {}), src=src)
            assert _ids(actual) == _ids(expected), (old, new, variant, controller)
            seen += len(expected)
    return seen


@pytest.mark.parametrize("name", sorted(MAPPING))
def test_named_string_equals_structured_selector(name):
    _check(name, MAPPING[name])


def test_mapping_is_not_vacuous():
    """Each mapping selects something on at least one board, so equality is not 0 == 0."""
    empty = [name for name in MAPPING if _check(name, MAPPING[name]) == 0]
    # Only the shapes the rich board deliberately cannot populate may be empty.
    assert empty == [], empty


FLAT_CASES = (
    # (named string, flat params)
    ("creatures_you_control", {"subtype": "Elf"}),
    ("creatures_you_control", {"subtype": "Cleric"}),
    ("creatures_you_control", {"tokens": True}),
    ("creatures_you_control", {"subtype_from_source": True}),
    ("other_creatures_you_control", {"subtype": "Elf"}),
    ("other_creatures_you_control", {"subtype": "Human"}),
    ("all_creatures", {"subtype": "Elf"}),
    ("all_creatures", {"exclude_self": True}),
    ("artifacts_you_control", {"subtype": "Vehicle"}),
    ("permanents_you_control", {"exclude_self": True}),
    ("permanents_you_control", {"subtype": "Vehicle"}),
    ("permanents_you_control", {"tokens": True}),
    ("opponents_permanents", {"tokens": True}),
)


@pytest.mark.parametrize("name,flat", FLAT_CASES, ids=lambda v: str(v))
def test_flat_params_fold_into_filter(name, flat):
    add, rest = flat_params_to_filter(flat)
    assert rest == {}, "case must be fully foldable"
    _check(name, with_flat(MAPPING[name], add), flat=flat)


def test_unfolded_flat_params_still_apply_to_a_structured_selector():
    """Flat params the migration leaves in place keep narrowing the structured result."""
    flat = {"card_type": "artifact"}
    _check("creatures_you_control", MAPPING["creatures_you_control"], flat=flat, new_flat=flat)
    flat = {"color": ["W"]}
    _check("creatures_you_control", MAPPING["creatures_you_control"], flat=flat, new_flat=flat)
    flat = {"has_counter_kind": "+1/+1"}
    _check("creatures_you_control", MAPPING["creatures_you_control"], flat=flat, new_flat=flat)


@pytest.mark.parametrize("name", sorted(MASS_MAPPING))
def test_mass_selector_equals_structured_group(name):
    populated = 0
    for variant in VARIANTS:
        state, objs = _board(variant)
        for controller, src_key in PERSPECTIVES:
            src = objs.get(src_key)
            if src is None:
                continue
            context = GameContext(state, RulesEngine(state))
            expected = _mass_selector_objects(context, name, None, source=src)
            actual = continuous.group_selector_objects(state, controller, MASS_MAPPING[name], src=src)
            assert _ids(actual) == _ids(expected), (name, variant, controller)
            populated += len(expected)
    assert populated, f"{name} selected nothing on every board"
