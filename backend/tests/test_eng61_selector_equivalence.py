"""ENG-61: the structured group selectors select exactly what the retired named strings selected.

The named group strings (creatures_you_control, all_lands, opponents_permanents, ...) and the flat
group params (subtype/tokens/exclude_self/card_type/...) are gone from the engine; every group is a
{"zone": "battlefield", "of": ..., "filter": {...}} selector. The expected object sets in
tests/support/eng61_selector_expected.json were recorded once from the named-string implementation on the boards
below (three board variants, each seen from both players' perspective), and each structured selector must
reproduce them. Fixed expected sets, not a live old-vs-new comparison: the old code no longer exists.
"""

from __future__ import annotations

import json
from pathlib import Path

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
def with_flat(structured_sel: dict, add: dict) -> dict:
    return {**structured_sel, "filter": {**structured_sel["filter"], **add}}


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------


def _card(name, type_line, cost="", power=None, toughness=None, **kw):
    kind = type_line.partition("—")[0].lower()
    symbols = [part for part in cost.replace("{", "").split("}") if part]
    kw.setdefault("converted_mana_cost", sum(int(sym) if sym.isdigit() else 1 for sym in symbols))
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

EXPECTED = json.loads((Path(__file__).parent / "support" / "eng61_selector_expected.json").read_text())


def _key(obj):
    """A board-independent identity (each side of a comparison builds its own board)."""
    return [obj.card.name, obj.controller_id, obj.zone.value]


def _keys(objs) -> list:
    return sorted(_key(o) for o in objs)


def _perspectives():
    for variant in VARIANTS:
        state, objs = _board(variant)
        for controller, src_key in PERSPECTIVES:
            src = objs.get(src_key)
            if src is not None:
                yield variant, controller, state, objs, src


def _check_group(selector: dict, expected: dict, flat: dict | None = None) -> int:
    seen = 0
    for variant, controller, state, _objs, src in _perspectives():
        got = _keys(continuous.group_selector_objects(state, controller, selector, dict(flat or {}), src=src))
        assert got == expected[f"{variant}/{controller}"], (selector, variant, controller)
        seen += len(got)
    return seen


@pytest.mark.parametrize("name", sorted(MAPPING))
def test_structured_selector_selects_the_recorded_set(name):
    assert _check_group(MAPPING[name], EXPECTED["group"][name]) > 0 or name in NEVER_POPULATED


#: Shapes the deliberately small boards cannot populate (the equality is still checked, as empty).
NEVER_POPULATED = frozenset()


def test_every_recorded_mapping_is_populated_somewhere():
    empty = [n for n in MAPPING if not any(EXPECTED["group"][n].values()) and n not in NEVER_POPULATED]
    assert empty == [], empty


FLAT_CASES = (
    # (retired named string, retired flat params) -> the filter additions that replaced the flat params
    ("creatures_you_control", {"subtype": "Elf"}, {"subtype": "Elf"}),
    ("creatures_you_control", {"subtype": "Cleric"}, {"subtype": "Cleric"}),
    ("creatures_you_control", {"tokens": True}, {"token": True}),
    ("creatures_you_control", {"subtype_from_source": True}, {"subtype_from_source": True}),
    ("other_creatures_you_control", {"subtype": "Elf"}, {"subtype": "Elf"}),
    ("other_creatures_you_control", {"subtype": "Human"}, {"subtype": "Human"}),
    ("all_creatures", {"subtype": "Elf"}, {"subtype": "Elf"}),
    ("all_creatures", {"exclude_self": True}, {"not_reference": True}),
    ("artifacts_you_control", {"subtype": "Vehicle"}, {"subtype": "Vehicle"}),
    ("permanents_you_control", {"exclude_self": True}, {"not_reference": True}),
    ("permanents_you_control", {"subtype": "Vehicle"}, {"subtype": "Vehicle"}),
    ("permanents_you_control", {"tokens": True}, {"token": True}),
    ("opponents_permanents", {"tokens": True}, {"token": True}),
)


@pytest.mark.parametrize("name,flat,add", FLAT_CASES, ids=lambda v: str(v))
def test_folded_flat_params_select_the_recorded_set(name, flat, add):
    expected = EXPECTED["flat"][json.dumps([name, flat], sort_keys=True)]
    _check_group(with_flat(MAPPING[name], add), expected)


@pytest.mark.parametrize("flat", (
    {"subtype": "Elf"}, {"tokens": True}, {"exclude_self": True}, {"card_type": "artifact"}, {"color": ["W"]},
    {"object_filter": {"attacking": True}}, {"card_name_from_source": True},
))
def test_a_retired_flat_group_param_selects_nothing(flat):
    """RETIRED_FLAT_GROUP_PARAMS: a stale flat param fails closed -- never a wider group than the spec names."""
    for _variant, controller, state, _objs, src in _perspectives():
        assert continuous.group_selector_objects(state, controller, MAPPING["creatures_you_control"], dict(flat),
                                                 src=src) == []


@pytest.mark.parametrize("stale", ("creatures_you_control", "all_creatures", "opponents_permanents",
                                   "each_creature", "not_a_selector"))
def test_a_named_group_string_selects_nothing(stale):
    for _variant, controller, state, _objs, src in _perspectives():
        assert continuous.group_selector_objects(state, controller, stale, src=src) == []


# ---------------------------------------------------------------------------
# Part (a): the one-shot destroy/exile/return group reader
# ---------------------------------------------------------------------------

from mtg_analyzer.game.continuous import StaticAbility  # noqa: E402
from mtg_analyzer.game import combat  # noqa: E402
from mtg_analyzer.game.effects.core import EffectRegistry  # noqa: E402
from mtg_analyzer.game.effects.damage_draw import _mass_group_objects  # noqa: E402

NAMED_SOURCES = structured("any", name_from_source=True)

#: retired mass name -> the structured group that replaced it
MASS_MAPPING = {
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


@pytest.mark.parametrize("name", sorted(MASS_MAPPING))
def test_mass_group_selects_the_recorded_set(name):
    populated = 0
    for variant, controller, state, _objs, src in _perspectives():
        context = GameContext(state, RulesEngine(state))
        got = _keys(_mass_group_objects(context, MASS_MAPPING[name], None, src))
        assert got == EXPECTED["mass"][name][f"{variant}/{controller}"], (name, variant, controller)
        populated += len(got)
    assert populated, f"{name} selected nothing on every board"


MASS_FILTER_CASES = (
    ("all_creatures", {"min_toughness": 2}),
    ("all_creatures", {"min_power": 2}),
    ("all_creatures", {"max_mana_value": 1}),
    ("all_creatures", {"min_mana_value": 2}),
    ("all_creatures", {"enchanted": False}),
    ("all_creatures", {"attacking": True}),
    ("all_creatures", {"token": True}),
    ("all_creatures", {"token": False}),
    ("all_creatures", {"subtype": "elf"}),
    ("all_nonland_permanents", {"max_mana_value": 2}),
    ("all_lands", {"nonbasic": True}),
    ("opponents_creatures", {"color": "G"}),
)


@pytest.mark.parametrize("name,filt", MASS_FILTER_CASES, ids=str)
def test_mass_group_with_filter_selects_the_recorded_set(name, filt):
    populated = 0
    expected = EXPECTED["mass_filter"][json.dumps([name, filt], sort_keys=True)]
    for variant, controller, state, _objs, src in _perspectives():
        context = GameContext(state, RulesEngine(state))
        got = _keys(_mass_group_objects(context, MASS_MAPPING[name], None, src, None, dict(filt)))
        assert got == expected[f"{variant}/{controller}"], (name, filt, variant, controller)
        populated += len(got)
    assert populated, f"{name} {filt} selected nothing on every board"


def test_mass_group_selects_battles_the_old_names_could_not():
    state, objs = _board(0)
    battle = _put(state, _card("Siege", "Battle — Siege"))
    context = GameContext(state, RulesEngine(state))
    group = structured("any", card_type="battle")
    assert [o.instance_id for o in _mass_group_objects(context, group, None, objs["source"])] == [battle.instance_id]


# ---------------------------------------------------------------------------
# Part (a): readers that compared named strings themselves
# ---------------------------------------------------------------------------


def _install(src, ability):
    """Make ability the one static src carries (and recompute, as the engine would)."""
    ability.source = src
    src.static_effects = [ability]


def _hand_card(state, name, owner=P2):
    obj = GameObject(_card(name, "Artifact", "{1}"), owner_id=owner, controller_id=owner, zone=Zone.HAND)
    state.players[1 if owner == P2 else 0].hand.append(obj)
    return obj


PROHIBITION_CASES = (
    # (structured affects, params, kwargs for activation_prohibited) -- index = EXPECTED["prohibition"] key
    (structured("any", card_type="planeswalker"), {"loyalty_only": True}, {"is_loyalty_ability": True}),
    (structured("opponents", card_type="artifact"), {}, {}),
    (structured("opponents", card_type="creature"), {}, {}),
    (NAMED_SOURCES, {"except_mana_abilities": True}, {}),
    (NAMED_SOURCES, {}, {"is_mana_ability": True}),
)


@pytest.mark.parametrize("index", range(len(PROHIBITION_CASES)))
def test_activation_prohibition_selects_the_recorded_set(index):
    affects, params, kwargs = PROHIBITION_CASES[index]
    seen = 0
    for chosen in (None, "Cleric", "Rock"):
        for variant in VARIANTS:
            for controller, src_key in PERSPECTIVES:
                state, objs = _board(variant)
                src = objs.get(src_key)
                if src is None:
                    continue
                src.chosen_card_name = chosen
                # A card in a hand is a source too (RULE 602.1): the named lock reaches it, a group does not.
                in_hand = _hand_card(state, "Rock")
                _install(src, StaticAbility("activation_prohibition", affects=affects, params=dict(params)))
                continuous.recompute(state)
                got = _keys(o for o in [*state.battlefield, in_hand]
                            if continuous.activation_prohibited(state, o, **kwargs))
                assert got == EXPECTED["prohibition"][str(index)][f"{chosen}/{variant}/{controller}"], (
                    index, chosen, variant, controller)
                seen += len(got)
    assert seen, "the prohibition silenced nothing on every board"


COST_CASES = (
    (structured("opponents"), {"generic": 1, "increase": True, "except_mana_abilities": True,
                               "active_if": {"kind": "your_turn"}}),
    (structured("any"), {"generic": 2, "increase": True, "except_mana_abilities": True}),
    (NAMED_SOURCES, {"generic": 2, "increase": True}),
)


@pytest.mark.parametrize("index", range(len(COST_CASES)))
def test_activation_cost_tax_selects_the_recorded_set(index):
    affects, params = COST_CASES[index]
    seen = 0
    for chosen in (None, "Cleric"):
        for variant in VARIANTS:
            for controller, src_key in PERSPECTIVES:
                state, objs = _board(variant)
                src = objs.get(src_key)
                if src is None:
                    continue
                src.chosen_card_name = chosen
                _install(src, StaticAbility("cost", affects=affects, params={"scope": "activation", **params}))
                continuous.recompute(state)
                row = []
                for o in state.battlefield:
                    for mana in (False, True):
                        row.append([_key(o), mana, [str(x) for x in continuous.activation_cost_changes(
                            state, o, is_mana_ability=mana, activating_player_id=o.controller_id)]])
                row.sort(key=lambda r: (r[0], r[1]))
                assert row == EXPECTED["cost"][str(index)][f"{chosen}/{variant}/{controller}"], (
                    index, chosen, variant, controller)
                seen += sum(1 for r in row if r[2][0] != "0")
    assert seen, "the tax applied to nothing on every board"


@pytest.mark.parametrize("index,affects", (
    (0, structured("opponents", card_type="artifact")),
    (1, structured("any", card_type="land", nonbasic=True)),
))
def test_enters_tapped_selects_the_recorded_set(index, affects):
    seen = 0
    for variant in VARIANTS:
        for controller, src_key in PERSPECTIVES:
            state, objs = _board(variant)
            src = objs.get(src_key)
            if src is None:
                continue
            _install(src, StaticAbility("enters_tapped", affects=affects, params={}))
            continuous.recompute(state)
            entering = []
            for holder in (P1, P2):
                for name, line in (("Rock", "Artifact"), ("Bear", "Creature — Bear"),
                                   ("Cave", "Land — Island Plains"), ("Isle", "Basic Land — Island")):
                    entering.append(GameObject(_card(name, line), owner_id=holder, controller_id=holder,
                                               zone=Zone.STACK))
            got = [bool(continuous.enters_tapped_from_static(state, o)) for o in entering]
            assert got == EXPECTED["tapped"][str(index)][f"{variant}/{controller}"], (index, variant, controller)
            seen += sum(got)
    assert seen


# ---------------------------------------------------------------------------
# Part (a): legendary filter keys read the layer-derived supertype (RULE 205.4)
# ---------------------------------------------------------------------------


def test_legendary_filter_reads_the_current_supertype():
    state, objs = _board(0)
    plain = objs["elf"]
    legend = objs["legend"]
    assert not combat.matches_object_filter(plain, {"legendary": True}, state=state)
    plain._granted_legendary = True  # a layer-4 grant (the Ring's emblem, "is legendary in addition")
    assert combat.matches_object_filter(plain, {"legendary": True}, state=state)
    assert not combat.matches_object_filter(plain, {"nonlegendary": True}, state=state)
    legend._removed_types = {"legendary"}  # a layer-4 removal
    assert not combat.matches_object_filter(legend, {"legendary": True}, state=state)
    assert combat.matches_object_filter(legend, {"nonlegendary": True}, state=state)


LEGENDARY_MAPPING = {
    "legendary_creatures_you_control": structured("you", card_type="creature", legendary=True),
    "legendary_permanents_you_control": structured("you", legendary=True),
    "nonlegendary_creatures_you_control": structured("you", card_type="creature", nonlegendary=True),
    "enchanted_or_equipped_creatures_you_control": structured(
        "you", card_type="creature", any_of=[{"enchanted": True}, {"equipped": True}]),
    "commander_creatures_you_own": structured("any", card_type="creature", is_commander=True, owned_by_you=True),
    "creatures_opponents_control_with_a_counter": structured("opponents", card_type="creature", has_counter=True),
    "artifacts_you_control": structured("you", card_type="artifact"),
}


@pytest.mark.parametrize("name", sorted(LEGENDARY_MAPPING))
def test_last_structured_selectors_select_the_recorded_set(name):
    seen = 0
    for variant in VARIANTS:
        state, objs = _board(variant)
        # An Aura on the commander and an Equipment on the elf make "enchanted or equipped" non-empty.
        aura = _put(state, _card("Pacifism", "Enchantment — Aura"))
        aura.attached_to = objs["legend"].instance_id if "legend" in objs else None
        gear = _put(state, _card("Sword", "Artifact — Equipment"))
        gear.attached_to = objs["source"].instance_id
        continuous.recompute(state)
        for controller, src_key in PERSPECTIVES:
            src = objs.get(src_key)
            if src is None:
                continue
            got = _keys(continuous.group_selector_objects(state, controller, LEGENDARY_MAPPING[name], src=src))
            assert got == EXPECTED["legendary"][name][f"{variant}/{controller}"], (name, variant, controller)
            seen += len(got)
    assert seen, name


# ---------------------------------------------------------------------------
# Execution through the real effects
# ---------------------------------------------------------------------------


def _specs(name, type_line):
    from mtg_analyzer.game import card_registry

    return card_registry.specs_for(Card(id=name, name=name, type_line=type_line))


def _run(spec, state, source, controller_id=None):
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    context = GameContext(state, RulesEngine(state))
    effect.apply(context)
    return context


def _bound(state, name, type_line, controller=P1, cost="", **kw):
    """A permanent bound from its hand-authored catalogue entry (so its real statics are installed)."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = _put(state, _card(name, type_line, cost, **kw), controller=controller)
    bind_from_catalogue(obj)
    return obj


def test_pithing_needle_names_a_card_in_hand_and_on_the_battlefield():
    state, objs = _board(0)
    needle = _bound(state, "Pithing Needle", "Artifact", cost="{1}")
    needle.chosen_card_name = "Rock"
    rock = _put(state, _card("Rock", "Artifact", "{2}"), controller=P2)
    hand_rock = _hand_card(state, "Rock")
    other = _put(state, _card("Pebble", "Artifact", "{1}"), controller=P2)
    continuous.recompute(state)
    assert continuous.activation_prohibited(state, rock)
    assert continuous.activation_prohibited(state, hand_rock)  # cycling/channel from a hand (RULE 602.1)
    assert not continuous.activation_prohibited(state, other)
    assert not continuous.activation_prohibited(state, rock, is_mana_ability=True)  # Needle's mana-ability carve-out
    needle.chosen_card_name = None  # nothing chosen yet silences nothing
    assert not continuous.activation_prohibited(state, rock)


def test_tithe_taker_taxes_opponents_abilities_on_your_turn_only():
    state, objs = _board(0)
    _bound(state, "Tithe Taker", "Creature — Human Soldier", cost="{1}{W}", power=2, toughness=1)
    foe = objs["o_bear"]
    mine = objs["elf"]
    state.active_player_index = 0  # p1's turn
    continuous.recompute(state)
    increase, reduction, _ = continuous.activation_cost_changes(state, foe, activating_player_id=P2)
    assert (increase, reduction) == (1, 0)
    assert continuous.activation_cost_changes(state, foe, is_mana_ability=True, activating_player_id=P2)[0] == 0
    assert continuous.activation_cost_changes(state, mine, activating_player_id=P1)[0] == 0
    state.active_player_index = 1  # "during your turn" -- not Tithe Taker's controller's
    assert continuous.activation_cost_changes(state, foe, activating_player_id=P2)[0] == 0


def test_dauntless_dismantler_makes_opposing_artifacts_enter_tapped():
    state, objs = _board(0)
    _bound(state, "Dauntless Dismantler", "Creature — Human Artificer", cost="{1}{W}", power=2, toughness=2)
    mine = GameObject(_card("Mine", "Artifact"), owner_id=P1, controller_id=P1, zone=Zone.STACK)
    theirs = GameObject(_card("Theirs", "Artifact"), owner_id=P2, controller_id=P2, zone=Zone.STACK)
    theirs_creature = GameObject(_card("TBear", "Creature — Bear", power=1, toughness=1),
                                 owner_id=P2, controller_id=P2, zone=Zone.STACK)
    assert continuous.enters_tapped_from_static(state, theirs)
    assert not continuous.enters_tapped_from_static(state, mine)
    assert not continuous.enters_tapped_from_static(state, theirs_creature)


def _modal_option(name, type_line, index):
    (spec,) = [s for s in _specs(name, type_line) if s.modes]
    return spec.modes["options"][index][0]


def test_austere_command_modes_destroy_by_mana_value_through_the_group_path():
    state, objs = _board(0)
    small = objs["elf"]       # mana value 1
    big = objs["golem"]       # mana value 3 (artifact creature)
    huge = _put(state, _card("Titan", "Creature — Giant", "{4}{R}", 6, 6))
    src = objs["source"]
    _run(_modal_option("Austere Command", "Sorcery", 2), state, src)  # creatures with mana value 3 or less
    assert small.zone == Zone.GRAVEYARD and big.zone == Zone.GRAVEYARD
    assert huge.zone == Zone.BATTLEFIELD
    _run(_modal_option("Austere Command", "Sorcery", 3), state, src)  # creatures with mana value 4 or greater
    assert huge.zone == Zone.GRAVEYARD


def test_martial_coup_destroy_spares_the_soldiers_it_just_created():
    state, objs = _board(0)
    (spec,) = [s for s in _specs("Martial Coup", "Sorcery") if s.ability_kind == "spell_effect"]
    create, destroy = spec.effects[0], spec.effects[1]
    assert destroy.params["exclude_created"] and "group" in destroy.params
    effect = EffectRegistry.create(create.type, {**create.params, "count": 5})  # X = 5
    effect.source = objs["source"]
    context = GameContext(state, RulesEngine(state))
    effect.apply(context)
    made = list(context.created_objects)
    assert made, "the Soldier tokens exist"
    wipe = EffectRegistry.create(destroy.type, destroy.params)
    wipe.source = objs["source"]
    wipe.apply(context)  # the X >= 5 gate is a ConditionalEffect around this; the filter is what is under test
    assert all(t.zone == Zone.BATTLEFIELD for t in made)
    assert objs["elf"].zone == Zone.GRAVEYARD and objs["o_bear"].zone == Zone.GRAVEYARD


def test_add_counters_group_each_creature_you_control_and_damage_each_other_creature():
    state, objs = _board(0)
    (counters_spec,) = [s for s in _specs("Mazirek, Kraul Death Priest", "Legendary Creature — Insect Shaman")
                        if s.effects and s.effects[0].type == "add_counters"]
    _run(counters_spec.effects[0], state, objs["source"])
    mine = [o for o in state.permanents() if o.is_creature and o.controller_id == P1]
    assert mine and all(o.counters.get("+1/+1") for o in mine)
    assert not any(o.counters.get("+1/+1") for o in state.permanents() if o.controller_id == P2
                   and o is not objs["o_countered"])
    # Territorial Aetherkite's damage: "each other creature" spares the source itself.
    spec = EffectSpec_for_damage = None
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    spec = EffectSpec("damage", {"amount": 1, "group": structured("any", card_type="creature", not_reference=True)})
    src = objs["source"]
    before = src.damage_marked if hasattr(src, "damage_marked") else None
    _run(spec, state, src)
    assert objs["elf"].damage_marked == 1 and objs["o_bear"].damage_marked == 1
    assert src.damage_marked == (before or 0)
