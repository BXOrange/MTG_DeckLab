"""PAR-285: "X target <qualified things>" and "any number of target ..." on the shared counted-target operand.

"Destroy X target nonblack creatures", "Tap X target nonland permanents", "Exile X target attacking creatures" used to
stay unclaimed: the shared operand grammar knew numeric counts only, while every X-count row wrote its own pool
vocabulary. The operand now carries the announced X as `choose_targets.count_selector` (RULE 601.2c), read by
`targeting.resolved_count` when the spell is announced. Tests run parser -> binder -> targeting -> engine on the real
cards' text."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _card, _put, _session


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _hand_real(state, name: str, owner: str = "p1"):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    obj = GameObject(_real(name), owner_id=owner, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(owner).hand.append(obj)
    return obj


def _announce(name: str) -> dict:
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    for ability in result.specs:
        for effect in ability.effects:
            inner = effect.params.get("effects") if effect.type == "seq" else [effect.to_dict()]
            for spec in inner or []:
                if spec["type"] == "choose_targets":
                    return spec["params"]
    raise AssertionError(f"{name}: no choose_targets announcement")


def test_x_count_rides_the_announcement_with_its_quality():
    (seq,) = match_clause("destroy x target nonblack creatures")
    announce = seq.params["effects"][0]["params"]
    assert announce["count_selector"] == "source_x_paid" and announce["optional"] is True
    assert announce["creature_filter"]["without_color"] == "B"
    (attacking,) = match_clause("exile x target attacking creatures")
    assert attacking.params["effects"][0]["params"]["creature_filter"]["attacking"] is True


def test_numeric_counts_carry_no_selector():
    (seq,) = match_clause("destroy 2 target nonblack creatures")
    assert "count_selector" not in seq.params["effects"][0]["params"]


def test_range_and_pronoun_forms():
    (seq,) = match_clause("return 1 or 2 target attacking creatures to their owner's hand")
    announce = seq.params["effects"][0]["params"]
    assert (announce["count"], announce["count_max"]) == (1, 2)


def test_x_range_is_not_claimed():
    assert match_clause("destroy 1 or x target nonblack creatures") is None


@pytest.mark.parametrize("name", [
    "Gridlock", "Dregs of Sorrow", "Avalanche", "Vengeful Dreams", "Synod Artificer", "Command of Unsummoning",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_gridlock_offers_only_nonland_permanents_and_x_of_them():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Gridlock")
    bear = _put(state, _card("Bear", "Creature — Bear"), "p2")
    rock = _put(state, _card("Rock", "Artifact"), "p2")
    forest = _put(state, _card("Forest", "Land"), "p2")
    spell.x_paid = 2
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    assert entry["count"] == 2 and entry["count_from_x"] == 1
    assert {o["instance_id"] for o in entry["options"]} == {bear.instance_id, rock.instance_id}
    bear.tapped = rock.tapped = forest.tapped = False
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, spell, targets=[bear, rock], x=2)
    engine.rules.resolve_top_of_stack()
    assert bear.tapped and rock.tapped and not forest.tapped


def test_gridlock_x_one_announces_a_single_target():
    _, engine, state = _session()
    spell = _hand_real(state, "Gridlock")
    _put(state, _card("Bear", "Creature — Bear"), "p2")
    _put(state, _card("Rock", "Artifact"), "p2")
    spell.x_paid = 1
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    assert entry["count"] == 1


def test_dregs_of_sorrow_never_offers_a_black_creature():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Dregs of Sorrow")
    white = _put(state, _card("Knight", "Creature — Human Knight"), "p2")
    black = _put(state, _card("Zombie", "Creature — Zombie"), "p2")
    black.card.mana_cost_string = "{B}"  # RULE 202.2: printed colour comes from the mana cost
    spell.x_paid = 1
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    ids = {o["instance_id"] for o in entry["options"]}
    assert white.instance_id in ids and black.instance_id not in ids
    for n in ("Lib A", "Lib B"):
        p1.library.append(GameObject(_card(n, "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"B": 1, "C": 5})
    hand_before = len(p1.hand)
    engine.cast_spell(p1, spell, targets=[white], x=1)
    engine.rules.resolve_top_of_stack()
    assert white.zone == Zone.GRAVEYARD and black.zone == Zone.BATTLEFIELD
    assert len(p1.hand) == hand_before - 1 + 1  # the spell left the hand, X = 1 card drawn
    assert len(p1.library) == 1


def test_command_of_unsummoning_offers_attackers_only():
    _, engine, state = _session()
    spell = _hand_real(state, "Command of Unsummoning")
    attacker = _put(state, _card("Attacker", "Creature — Bear"), "p2")
    idle = _put(state, _card("Idle", "Creature — Bear"), "p2")
    attacker.attacking = True
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    assert {o["instance_id"] for o in entry["options"]} == {attacker.instance_id}
    assert entry["count"] == 1 and entry["count_max"] == 2


def test_where_x_rebinds_the_nested_announcement():
    # "destroy up to X target nonblack creatures, where X is the number of verse counters on ~" (Vile Requiem): the
    # cast {X} on the nested `choose_targets` becomes the source's counters, read as the targets are announced.
    announce = _announce("Vile Requiem")
    assert announce["count_selector"] == "source_verse_counters"
    assert announce["creature_filter"]["without_color"] == "B"


def test_vile_requiem_offers_as_many_targets_as_verse_counters():
    _, engine, state = _session()
    requiem = _put(state, _real("Vile Requiem"))
    requiem.counters["verse"] = 2
    destroy = [e for a in parse_oracle(requiem.card).specs for e in a.effects if e.type == "seq"]
    effects = build_effects(destroy, requiem)
    spec = next(s for e in effects for s in e.target_specs)
    assert targeting.resolved_count(spec, state, "p1", requiem) == 2
    requiem.counters["verse"] = 3
    assert targeting.resolved_count(spec, state, "p1", requiem) == 3


def test_any_number_of_target_permanents_doubles_non_creature_counters_too():
    # The Thing's "double the number of each kind of counter on any number of target permanents you control": the
    # unbounded count rides the operand grammar and the loop body must act on a non-creature permanent as well.
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    text = "Double the number of each kind of counter on any number of target permanents you control."
    spell = GameObject(_card("Doubler", "Instant", text), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    rock = _put(state, _card("Rock", "Artifact"))
    bear = _put(state, _card("Bear", "Creature — Bear"))
    foe = _put(state, _card("Foe", "Creature — Bear"), "p2")
    rock.counters["charge"], bear.counters["+1/+1"], foe.counters["+1/+1"] = 2, 1, 1
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    assert {o["instance_id"] for o in entry["options"]} == {rock.instance_id, bear.instance_id}
    p1.mana_pool.add("C", 1)
    engine.cast_spell(p1, spell, targets=[rock, bear])
    engine.rules.resolve_top_of_stack()
    assert rock.counters["charge"] == 4 and bear.counters["+1/+1"] == 2 and foe.counters["+1/+1"] == 1


def _land(name: str, type_line: str):
    card = _card(name, type_line)
    card.is_land = True
    return card


def _cast_real(name: str, mana: dict, targets_for, x: int):
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, name)
    targets = targets_for(state)
    p1.mana_pool.add_many(mana)
    engine.cast_spell(p1, spell, targets=targets, x=x)
    engine.rules.resolve_top_of_stack()
    return engine, state, p1


def test_avalanche_destroys_only_snow_lands():
    state_ref = {}

    def targets(state):
        snow = _put(state, _land("Snow-Covered Mountain", "Basic Snow Land — Mountain"), "p2")
        plain = _put(state, _land("Mountain", "Basic Land — Mountain"), "p2")
        state_ref.update(snow=snow, plain=plain)
        spell = next(o for o in state.player_by_id("p1").hand if o.name == "Avalanche")
        spell.x_paid = 1
        (entry,) = targeting.requirements_with_targets(state, "p1", spell)
        assert {o["instance_id"] for o in entry["options"]} == {snow.instance_id}
        return [snow]

    _cast_real("Avalanche", {"R": 2, "C": 3}, targets, 1)
    assert state_ref["snow"].zone == Zone.GRAVEYARD and state_ref["plain"].zone == Zone.BATTLEFIELD


def test_malicious_advice_taps_x_and_costs_x_life():
    held = {}

    def targets(state):
        held["bear"] = _put(state, _card("Bear", "Creature — Bear"), "p2")
        held["rock"] = _put(state, _card("Rock", "Artifact"), "p2")
        return [held["bear"], held["rock"]]

    _, state, p1 = _cast_real("Malicious Advice", {"U": 1, "B": 1, "C": 4}, targets, 2)
    assert held["bear"].tapped and held["rock"].tapped and p1.life == 18


def test_mass_manipulation_steals_the_chosen_creatures():
    held = {}

    def targets(state):
        held["a"] = _put(state, _card("Ogre", "Creature — Ogre"), "p2")
        return [held["a"]]

    _, state, p1 = _cast_real("Mass Manipulation", {"U": 4, "C": 2}, targets, 1)
    assert held["a"].controller_id == "p1"


def test_wave_of_indifference_stops_x_creatures_blocking():
    # RULE 509.1a: after resolution the chosen creature cannot be declared as a blocker (the engine's own can_block
    # check, reading `temp_cant_block`), an unchosen one still can.
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Wave of Indifference")
    attacker = _put(state, _card("Raider", "Creature — Bear"))
    chosen = _put(state, _card("Ogre", "Creature — Ogre"), "p2")
    spared = _put(state, _card("Elf", "Creature — Elf"), "p2")
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    p2 = state.player_by_id("p2")
    assert engine.can_block(p2, chosen, attacker) and engine.can_block(p2, spared, attacker)
    p1.mana_pool.add_many({"R": 2, "C": 3})
    engine.cast_spell(p1, spell, targets=[chosen], x=1)
    engine.rules.resolve_top_of_stack()
    assert not engine.can_block(p2, chosen, attacker)
    assert engine.can_block(p2, spared, attacker)



def test_noncreature_artifact_pool_excludes_artifact_creatures():
    # The single-type pools (`artifact`/`land`/`enchantment`) used to ignore the parsed quality, so "noncreature
    # artifact" offered Golems and "snow land" any land (Synod Artificer, Crush, Sculptor of Winter).
    _, engine, state = _session()
    synod = _put(state, _real("Synod Artificer"))
    rock = _put(state, _card("Rock", "Artifact"), "p2")
    golem = _put(state, _card("Golem", "Artifact Creature — Golem"), "p2")
    announce = _announce("Synod Artificer")
    spec = targeting.TargetSpec(kind=announce["kinds"][0], creature_filter=announce["creature_filter"])
    ids = {o["instance_id"] for o in targeting.legal_targets(state, "p1", spec, source=synod)}
    assert rock.instance_id in ids and golem.instance_id not in ids


# --- the five single-type frames now apply `creature_filter`: every filter dict an already-modelled card carries ---
#
# Distinct (kind, filter) pairs found on the cached pool (parser specs and authored bindings) when the frames started
# applying their filter. Each row: a matching permanent and non-matching ones that share the kind's pool, so the result
# must be exactly the matching one (an unreadable key would empty or widen the pool).

def _typed(name: str, type_line: str, mv: int = 2):
    card = _card(name, type_line)
    card.converted_mana_cost = mv
    card.is_land = "land" in type_line.lower()
    return card


FILTER_CASES = [
    # (id, kind, filter, matching card builders, non-matching card builders)
    ("noncreature-artifact", "artifact", {"card_type": "artifact", "without_card_type": "creature"},
     [("Rock", "Artifact")], [("Golem", "Artifact Creature — Golem")]),
    ("plain-artifact", "artifact", {"card_type": "artifact"},
     [("Rock", "Artifact"), ("Golem", "Artifact Creature — Golem")], [("Pacifism", "Enchantment")]),
    ("noncreature-artifact-mv", "artifact", {"max_mana_value": 3, "without_type": ["creature"]},
     [("Rock", "Artifact")], [("Golem", "Artifact Creature — Golem"), ("Big Rock", "Artifact", 5)]),
    ("token-artifact", "artifact", {"card_type": "artifact", "token": True},
     [("Treasure", "Token Artifact — Treasure")], [("Rock", "Artifact")]),
    ("snow-land", "land", {"card_type": "land", "snow": True},
     [("Snow Mountain", "Basic Snow Land — Mountain")], [("Mountain", "Basic Land — Mountain")]),
    ("basic-land", "land", {"basic": True, "card_type": "land"},
     [("Mountain", "Basic Land — Mountain")], [("Tavern", "Land")]),
    ("land-without-counter", "land", {"card_type": "land", "without_counter_kind": "blaze"},
     [("Plain Land", "Land")], [("Blazing Land", "Land")]),
    ("plain-land", "land", {"card_type": "land"}, [("Plains", "Land")], [("Rock", "Artifact")]),
    ("nonaura-enchantment", "enchantment", {"card_type": "enchantment", "without_subtype": "aura"},
     [("Shrine", "Enchantment — Shrine")], [("Pacifism", "Enchantment — Aura")]),
]


@pytest.mark.parametrize("case", FILTER_CASES, ids=[c[0] for c in FILTER_CASES])
def test_single_type_frames_apply_their_parsed_filter(case):
    _, kind, filt, matching, non_matching = case
    _, engine, state = _session()
    source = _put(state, _card("Src", "Creature — Bear"))
    good, bad = [], []
    for group, out in ((matching, good), (non_matching, bad)):
        for entry in group:
            name, type_line, *rest = entry
            card = _typed(name, type_line, *(rest or [2]))
            obj = _put(state, card, "p2")
            if type_line.startswith("Token"):
                obj.is_token = True
            if name == "Blazing Land":
                obj.counters["blaze"] = 1
            out.append(obj)
    spec = targeting.TargetSpec(kind=kind, creature_filter=dict(filt))
    ids = {o["instance_id"] for o in targeting.legal_targets(state, "p1", spec, source=source)}
    assert ids == {o.instance_id for o in good}, (case[0], ids)


@pytest.mark.parametrize("name,kind,filt", [
    ("Rhino's Rampage", "artifact", {"max_mana_value": 3, "without_type": ["creature"]}),
    ("Sculptor of Winter", "land", {"card_type": "land", "snow": True}),
    ("Earthcraft", "land", {"basic": True, "card_type": "land"}),
    ("Emerald Charm", "enchantment", {"card_type": "enchantment", "without_subtype": "aura"}),
])
def test_real_cards_carry_the_filters_the_table_covers(name, kind, filt):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("creature_filter") and (kind in (node.get("kinds") or []) or node.get("target_kind") == kind):
                found.append(node["creature_filter"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for ability in parse_oracle(_real(name)).specs:
        walk(ability.to_dict())
    assert filt in found
    assert any(filt == case[2] for case in FILTER_CASES)
