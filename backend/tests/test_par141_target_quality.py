"""PAR-141/PAR-142: a negated quality slot on a targeted creature.

"target creature without flying", "target creature you control that doesn't have a +1/+1 counter on
it" — `subgrammars.TARGET_QUALITY_TAIL`, read back as a `creature_filter` fragment; a handler that
drops it is refused by `EffectHandler.match`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import continuous
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
    resolve_target_creature_state_filter, resolve_target_kind, target_quality_filter,
)


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _card(name: str, text: str = "", type_line: str = "Creature — Bear") -> Card:
    return Card(
        id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
        is_sorcery=type_line.startswith("Sorcery"), power=2 if "Creature" in type_line else None,
        toughness=2 if "Creature" in type_line else None, oracle_text=text,
        keywords=["Flying"] if "Flying" in text else [],
    )


def _put(eng: GameEngine, card: Card, owner: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("phrase, kind, fragment", [
    ("target creature without flying", "creature", {"without_keyword": "flying"}),
    ("target creature you control without flying", "creature_you_control", {"without_keyword": "flying"}),
    ("target creature without flying you don't control", "creature_you_dont_control",
     {"without_keyword": "flying"}),
    ("target creature you control that doesn't have a +1/+1 counter on it", "creature_you_control",
     {"without_counter_kind": "+1/+1"}),
    ("target creature that doesn't have first strike", "creature", {"without_keyword": "first strike"}),
    ("target creature that has no counters on it", "creature", {"no_counters": True}),
])
def test_quality_slot_resolves_kind_and_filter(phrase, kind, fragment):
    assert resolve_target_kind(phrase) == kind
    assert resolve_target_creature_state_filter(phrase) == fragment
    assert target_quality_filter(phrase) == fragment


def test_quality_composes_with_the_combat_state_adjective():
    assert resolve_target_creature_state_filter("target attacking creature without flying") == {
        "attacking": True, "without_keyword": "flying",
    }


@pytest.mark.parametrize("phrase", [
    "target permanent without flying",        # a pool that applies no creature_filter
    "target creature without wings",          # unknown quality word
    "target creature without flying without reach",  # one slot only
])
def test_quality_fails_closed(phrase):
    assert resolve_target_kind(phrase) is None


def test_destroy_carries_the_quality():
    [spec] = match_clause("destroy target creature without flying")
    assert spec.params["creature_filter"] == {"without_keyword": "flying"}


def test_a_builder_that_drops_the_quality_is_refused():
    # "target creature without flying" is not a clause any row models with a meaning-preserving
    # filter except those that merge it; an unrelated phrase must simply stay unclaimed.
    assert match_clause("target creature without wings gets +1/+1 until end of turn") is None


def test_legal_targets_exclude_fliers_and_counter_holders():
    eng = _engine()
    ground = _put(eng, _card("Ground"))
    flier = _put(eng, _card("Flier", "Flying"))
    grown = _put(eng, _card("Grown"))
    eng.rules.add_counters(grown, 1, "+1/+1")

    def picks(kind: str, fragment: dict) -> set[str]:
        spec = TargetSpec(kind=kind, creature_filter=fragment)
        return {t["name"] for t in legal_targets(eng.state, "p1", spec) if "name" in t}

    assert picks("creature", {"without_keyword": "flying"}) == {"Ground", "Grown"}
    assert picks("creature_you_control", {"without_counter_kind": "+1/+1"}) == {"Ground", "Flier"}


def test_defenestrates_announced_target_spec_offers_only_ground_creatures():
    eng = _engine()
    flier = _put(eng, _card("Flier", "Flying"), owner="p2")
    ground = _put(eng, _card("Ground"), owner="p2")
    spell = GameObject(
        _card("Defenestrate", "Destroy target creature without flying.", "Sorcery"),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    [spec] = [s for e in spell.spell_effects for s in e.target_specs]
    offered = [t.get("instance_id") for t in legal_targets(eng.state, "p1", spec, spell)]
    assert ground.instance_id in offered and flier.instance_id not in offered


# --- PAR-142: an attached permanent that adds a type -------------------------------------------------


def _attach(eng: GameEngine, aura: Card, host: GameObject) -> GameObject:
    obj = GameObject(aura, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    return obj


def test_attached_type_addition_parses_every_part():
    specs = static_effect_specs(
        'enchanted creature gets +2/+2, has first strike, and is a knight in addition to its other types'
    )
    assert [s.type for s in specs] == ["anthem", "grant_keyword", "type_change"]
    assert specs[2].params == {"affects": "attached_permanent", "add_subtypes": ["Knight"]}


def test_attached_base_pt_needs_a_creature_and_a_known_word():
    [spec] = static_effect_specs(
        "enchanted artifact is a golem creature with base power and toughness 5/4 in addition to its other types"
    )
    assert spec.params == {
        "affects": "attached_permanent", "add_types": ["creature"], "add_subtypes": ["Golem"],
        "power": 5, "toughness": 4,
    }
    assert static_effect_specs(
        "enchanted artifact is a wizard with base power and toughness 5/4 in addition to its other types"
    ) is None
    assert static_effect_specs("enchanted creature is a blorp in addition to its other types") is None


def test_ensoul_artifact_animates_the_enchanted_artifact():
    eng = _engine()
    rock = _put(eng, _card("Rock", type_line="Artifact"))
    assert not rock.is_creature
    _attach(eng, _card("Ensoul Artifact", "Enchant artifact\nEnchanted artifact is a creature with base "
                       "power and toughness 5/5 in addition to its other types.", "Enchantment — Aura"), rock)
    assert rock.is_creature and (rock.power, rock.toughness) == (5, 5)
    assert "artifact" in rock.type_words


def test_dub_adds_the_type_the_pump_and_the_keyword():
    eng = _engine()
    bear = _put(eng, _card("Bear"))
    _attach(eng, _card("Dub", "Enchant creature\nEnchanted creature gets +2/+2, has first strike, and is a "
                       "knight in addition to its other types.", "Enchantment — Aura"), bear)
    assert (bear.power, bear.toughness) == (4, 4)
    assert "first_strike" in {str(k).replace(" ", "_") for k in bear.granted_keywords}
    assert "Knight" in bear._added_subtypes


def test_real_cards_are_modeled():
    for name, text, type_line in (
        ("Raven Wings", "Equipped creature gets +1/+0, has flying, and is a bird in addition to its other types.\nEquip {2}", "Artifact — Equipment"),
        ("Silverskin Armor", "Equipped creature gets +1/+1 and is an artifact in addition to its other types.\nEquip {2}", "Artifact — Equipment"),
    ):
        assert parse_oracle(_card(name, text, type_line)).coverage == MODELED, name


def test_becomes_body_forms():
    [spec] = match_clause(
        "~ becomes a 4/4 illusion creature with flying in addition to its other types until end of turn"
    )
    assert spec.params["duration"] == "end_of_turn" and spec.params["self_subject"] is True
    assert spec.params["static"]["params"] == {
        "add_types": ["creature"], "add_subtypes": ["Illusion"], "power": 4, "toughness": 4,
    }
    assert spec.params["extra_statics"] == [{"type": "grant_keyword", "params": {"keywords": ["flying"]}}]
    [several] = match_clause(
        "~ becomes a 5/5 demon creature with flying and haste in addition to its other types until end of turn"
    )
    assert several.params["extra_statics"][0]["params"]["keywords"] == ["flying", "haste"]


def test_becomes_body_fails_closed():
    assert match_clause("~ becomes a 4/4 illusion with flying in addition to its other types") is None  # P/T, no creature
    assert match_clause("~ becomes a 4/4 blorp creature in addition to its other types") is None


def test_call_a_surprise_witness_returns_the_creature_as_a_flying_spirit():
    eng = _engine()
    p1 = eng.state.players[0]
    bear = GameObject(_card("Bear"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bear)
    spell = GameObject(
        _card("Call a Surprise Witness",
              "Return target creature card with mana value 3 or less from your graveyard to the battlefield. "
              "Put a flying counter on it. It's a Spirit in addition to its other types.", "Sorcery"),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 4, "W": 4})
    eng.cast_spell(p1, spell, targets=[bear])
    eng.resolve_until_stable()
    assert bear in eng.state.battlefield
    eng.recompute_continuous_effects()
    assert bear.counters.get("flying") == 1
    assert "Spirit" in bear._added_subtypes


# --- the adjective slot ("target nontoken creature", "target Zombie creature") --------------------------


@pytest.mark.parametrize("phrase, kind, fragment", [
    ("target nontoken creature", "creature", {"nontoken": True}),
    ("target legendary creature you control", "creature_you_control", {"legendary": True}),
    ("another target nonlegendary creature you control", "other_creature_you_control", {"nonlegendary": True}),
    ("target non-human creature an opponent controls", "creature_you_dont_control", {"without_subtype": "Human"}),
    ("target zombie creature", "creature", {"subtype": "Zombie"}),
    ("target black creature", "creature", {"color": "B"}),
    ("target artifact creature", "creature", {"card_type": "artifact"}),
    ("target nonsnow creature", "creature", {"without_snow": True}),
    ("target nonattacking creature", "creature", {"attacking": False}),
])
def test_adjective_slot_resolves_kind_and_filter(phrase, kind, fragment):
    assert resolve_target_kind(phrase) == kind
    assert resolve_target_creature_state_filter(phrase) == fragment
    assert target_quality_filter(phrase) == fragment


@pytest.mark.parametrize("phrase", [
    "target nonbasic creature",      # a supertype negation is not a subtype
    "target blorp creature",         # not in any vocabulary
    "target nontoken blorp creature",
])
def test_adjective_slot_fails_closed(phrase):
    assert resolve_target_kind(phrase) is None


def test_adjective_reaches_the_spec_and_a_dropping_builder_is_refused():
    [spec] = match_clause("destroy target nonlegendary creature")
    assert spec.params["creature_filter"] == {"nonlegendary": True}
    # no row models a pump on "target legendary creature" without the filter: it must carry it or not match
    specs = match_clause("target legendary creature gets +1/+1 until end of turn")
    assert specs is None or specs[0].params["creature_filter"] == {"legendary": True}


def test_nonattacking_and_nonsnow_are_enforced_by_the_target_pool():
    eng = _engine()
    idle = _put(eng, _card("Idle"))
    attacker = _put(eng, _card("Attacker"))
    attacker.attacking = True
    snowy = _put(eng, _card("Snowy", type_line="Snow Creature — Bear"))

    def picks(fragment):
        spec = TargetSpec(kind="creature", creature_filter=fragment)
        return {t["name"] for t in legal_targets(eng.state, "p2", spec)}

    assert picks({"attacking": False}) == {"Idle", "Snowy"}
    assert picks({"without_snow": True}) == {"Idle", "Attacker"}
    assert picks({"attacking": True}) == {"Attacker"}


def test_attacking_you_only_offers_creatures_attacking_the_controller():
    eng = _engine()
    at_p1 = _put(eng, _card("AtAlice"), owner="p2")
    at_p1.attacking, at_p1.combat_defender = True, {"kind": "player", "id": "p1"}
    at_p2 = _put(eng, _card("AtBob"), owner="p1")
    at_p2.attacking, at_p2.combat_defender = True, {"kind": "player", "id": "p2"}
    src = _put(eng, _card("Fortress", type_line="Snow Land"))
    spec = TargetSpec(kind="creature", creature_filter={"attacking": True, "attacking_you": True})
    assert {t["name"] for t in legal_targets(eng.state, "p1", spec, src)} == {"AtAlice"}


def test_heros_demise_offers_only_legendary_creatures():
    eng = _engine()
    plain = _put(eng, _card("Plain"), owner="p2")
    legend = _put(eng, _card("Legend", type_line="Legendary Creature — Human"), owner="p2")
    legend.card.is_legendary = True  # flags are not derived from the type line
    spell = GameObject(
        _card("Hero's Demise", "Destroy target legendary creature.", "Sorcery"), owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    [spec] = [s for e in spell.spell_effects for s in e.target_specs]
    offered = {t["instance_id"] for t in legal_targets(eng.state, "p1", spec, spell)}
    assert offered == {legend.instance_id}
