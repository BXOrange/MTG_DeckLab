"""cEDH staples cube — batch B1: hand-authored `card_registry.py` entries
plus the small set of generic parser/engine extensions this batch found were
cheap enough to build as reusable primitives instead of one-off catalogue
entries.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/Reference/
11_CARD_CATALOGUE_AUTHORING_GUIDE.md. This batch's generic (non-card-specific)
additions, each proven here on the *real* card that motivated it:

1. `parser/oracle/catalogue/handlers.py`'s "put a +1/+1 counter on ~" self
   reference now also accepts "this creature"/"this artifact"/etc (not just
   the literal "~" a card's own name folds to) — Walking Ballista's own
   "{4}: Put a +1/+1 counter on this creature." reaches `MODELED` purely
   from this, no catalogue entry needed.
2. A new `TapEffect.selector="creatures_you_control"` mass-untap mode, plus
   a matching "untap all creatures you control" one-shot handler — Village
   Bell-Ringer's ETB reaches `MODELED` the same way.
3. `parser/oracle/catalogue/static_handlers.py`'s opponent-scoped "<type>
   your opponents control enter tapped" family now accepts two card types
   joined by "and" (Blind Obedience), plus a new unscoped sibling family
   for "<type> [and <type>] enter tapped" with no ownership restriction at
   all (Root Maze) — `continuous.enters_tapped_from_static` gained an
   `affects="all_permanents"` branch to match.
4. `targeting.TargetSpec.max_mana_value` — a target-offer-time mana-value
   cap — plus a `destroy_mv` handler for "destroy target X with mana value
   N or less" (Abrupt Decay).
5. A new `"forest"` target kind (Arbor Elf's "target Forest") — the first
   basic-land-subtype target kind; only Forest exists so far.
6. A new `GameEngine._step_untap` global untap cap (`continuous.
   untap_cap_for_lands`) for Winter Orb's "players can't untap more than
   one land during their untap steps."

Every other card below is a genuinely hand-authored `card_registry.py`
entry, several deliberately *partial* (documented drop of one sub-clause
neither the parser nor the effect library has a primitive for yet — Mana
Drain/Corpse Dance's delayed one-shot trigger, Eiganjo's activated-ability
cost reduction) per the file's existing Sword of Forge and Frontier/Timely
Ward precedent.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import card_registry as ac
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    """A card bound + added to ``state.battlefield`` (bind-on-load, mirroring
    `services.game_session.build_goldfish_engine`)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine(p1_cards=(), p2_cards=()) -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_cards)), ("p2", "Bob", list(p2_cards))],
        starting_life=40,
        starting_hand=max(len(p1_cards), len(p2_cards)) or 0,
    )
    # `new_game` doesn't bind-on-load (that's `services.game_session.
    # build_goldfish_engine`'s job in production) — bind every hand/library
    # object here too, so a spell cast straight from a test's starting hand
    # actually carries the abilities this batch's tests exercise.
    for player in eng.state.players:
        for obj in list(player.hand) + list(player.library):
            bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


# ---------------------------------------------------------------------------
# 1. Walking Ballista — generic parser fix (self-reference vocabulary)
# ---------------------------------------------------------------------------


def test_walking_ballista_fully_modeled():
    result = parse_oracle(_card("Walking Ballista"))
    assert result.modeled, result.unclaimed


def test_walking_ballista_removes_a_counter_to_deal_damage():
    from mtg_analyzer.game.binding.core import bind_from_catalogue as bind

    ballista = _card("Walking Ballista")
    eng = _engine()
    state = eng.state
    obj = GameObject(ballista, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind(obj)
    obj.counters["+1/+1"] = 2
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    p2 = state.players[1]

    remove_ability = next(
        a for a in obj.activated_abilities if a.cost.remove_counters is not None
    )
    idx = obj.activated_abilities.index(remove_ability)
    eng.activate_ability(state.players[0], obj, idx, targets=[p2])
    eng.resolve_until_stable()

    assert p2.life == 39
    assert obj.counters.get("+1/+1", 0) == 1


# ---------------------------------------------------------------------------
# 2. Village Bell-Ringer — generic parser fix (mass-untap selector)
# ---------------------------------------------------------------------------


def test_village_bell_ringer_fully_modeled():
    result = parse_oracle(_card("Village Bell-Ringer"))
    assert result.modeled, result.unclaimed


def test_village_bell_ringer_untaps_all_your_creatures_on_etb():
    eng = _engine()
    state = eng.state
    bear = Card(id="TapBear", name="TapBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    bear_obj = _battlefield(state, bear, controller="p1")
    bear_obj.tapped = True
    other_bear = _battlefield(state, bear, controller="p2")
    other_bear.tapped = True

    ringer = _card("Village Bell-Ringer")
    ringer_obj = GameObject(ringer, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(ringer_obj)
    state.players[0].hand.append(ringer_obj)
    state.players[0].mana_pool.add_many({"W": 1, "C": 2})
    eng.cast_spell(state.players[0], ringer_obj)
    eng.resolve_until_stable()

    assert bear_obj.tapped is False
    # "Creatures you control" — an opponent's tapped creature is unaffected.
    assert other_bear.tapped is True


# ---------------------------------------------------------------------------
# 3. Root Maze / Blind Obedience — static_handlers "and"/unscoped extension
# ---------------------------------------------------------------------------


def test_root_maze_and_blind_obedience_fully_modeled():
    for name in ("Root Maze", "Blind Obedience"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_root_maze_makes_every_players_artifacts_and_lands_enter_tapped():
    rock = Card(id="RootRock", name="RootRock", type_line="Artifact",
                mana_cost_string="{1}", converted_mana_cost=1)
    forest = Card(id="RootForest", name="RootForest", type_line="Basic Land — Forest", is_land=True)
    eng = _engine(p1_cards=[rock, forest])
    state = eng.state
    p1 = state.active_player
    _battlefield(state, _card("Root Maze"), controller="p1")

    rock_obj = next(o for o in p1.hand if o.name == "RootRock")
    p1.mana_pool.add("C", 1)
    eng.cast_spell(p1, rock_obj)
    eng.rules.resolve_top_of_stack()
    assert next(o for o in state.battlefield if o.name == "RootRock").tapped is True

    forest_obj = next(o for o in p1.hand if o.name == "RootForest")
    eng.play_land(p1, forest_obj)
    assert next(o for o in state.battlefield if o.name == "RootForest").tapped is True


def test_blind_obedience_makes_only_opponents_artifacts_and_creatures_enter_tapped():
    bear = Card(id="BlindBear", name="BlindBear", type_line="Creature — Bear",
                mana_cost_string="{1}{G}", converted_mana_cost=2, is_creature=True,
                power=2, toughness=2)
    eng = _engine(p1_cards=[bear])
    state = eng.state
    p1 = state.active_player
    _battlefield(state, _card("Blind Obedience"), controller="p2")

    bear_obj = p1.hand[0]
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, bear_obj)
    eng.rules.resolve_top_of_stack()
    assert next(o for o in state.battlefield if o.name == "BlindBear").tapped is True


# ---------------------------------------------------------------------------
# 4. Abrupt Decay — target-offer-time mana-value cap
# ---------------------------------------------------------------------------


def test_abrupt_decay_fully_modeled():
    result = parse_oracle(_card("Abrupt Decay"))
    assert result.modeled, result.unclaimed


def test_abrupt_decay_can_only_target_mana_value_3_or_less():
    cheap = Card(id="Cheap", name="Cheap", type_line="Artifact",
                 mana_cost_string="{3}", converted_mana_cost=3)
    pricey = Card(id="Pricey", name="Pricey", type_line="Artifact",
                  mana_cost_string="{4}", converted_mana_cost=4)
    eng = _engine()
    state = eng.state
    cheap_obj = _battlefield(state, cheap, controller="p2")
    pricey_obj = _battlefield(state, pricey, controller="p2")
    decay = _card("Abrupt Decay")
    decay_obj = GameObject(decay, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(decay_obj)
    state.players[0].hand.append(decay_obj)

    from mtg_analyzer.game import targeting

    spec = targeting.spell_target_specs(decay_obj)[0]
    legal_ids = {t["instance_id"] for t in targeting.legal_targets(state, "p1", spec)}
    assert cheap_obj.instance_id in legal_ids
    assert pricey_obj.instance_id not in legal_ids


# ---------------------------------------------------------------------------
# 5. Arbor Elf — new "forest" target kind
# ---------------------------------------------------------------------------


def test_arbor_elf_fully_modeled():
    result = parse_oracle(_card("Arbor Elf"))
    assert result.modeled, result.unclaimed


def test_arbor_elf_untaps_target_forest():
    forest = Card(id="ArborForest", name="ArborForest", type_line="Basic Land — Forest", is_land=True)
    island = Card(id="ArborIsland", name="ArborIsland", type_line="Basic Land — Island", is_land=True)
    eng = _engine()
    state = eng.state
    forest_obj = _battlefield(state, forest, controller="p1")
    forest_obj.tapped = True
    island_obj = _battlefield(state, island, controller="p1")
    island_obj.tapped = True
    elf_obj = _battlefield(state, _card("Arbor Elf"), controller="p1")

    from mtg_analyzer.game import targeting

    ability = elf_obj.activated_abilities[0]
    spec = ability.effects[0].target_spec
    legal_ids = {t["instance_id"] for t in targeting.legal_targets(state, "p1", spec)}
    assert forest_obj.instance_id in legal_ids
    assert island_obj.instance_id not in legal_ids

    eng.activate_ability(state.players[0], elf_obj, 0, targets=[forest_obj])
    eng.resolve_until_stable()
    assert forest_obj.tapped is False
    assert island_obj.tapped is True  # untouched


# ---------------------------------------------------------------------------
# 6. Mana Drain — partial: the counter half only
# ---------------------------------------------------------------------------


def test_mana_drain_registered():
    specs = ac.specs_for(_card("Mana Drain"))
    assert len(specs) == 1
    assert specs[0].ability_kind == "spell_effect"


def test_mana_drain_counters_the_targeted_spell():
    bolt = Card(id="DrainBolt", name="DrainBolt", type_line="Instant",
                mana_cost_string="{R}", converted_mana_cost=1, is_instant=True,
                oracle_text="DrainBolt deals 3 damage to any target.")
    eng = _engine(p1_cards=[bolt], p2_cards=[_card("Mana Drain")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    bolt_obj = p1.hand[0]
    drain_obj = p2.hand[0]
    p1.mana_pool.add("R", 1)
    p2.mana_pool.add_many({"U": 2})

    eng.cast_spell(p1, bolt_obj, targets=[p2])
    eng.cast_spell(p2, drain_obj, targets=[bolt_obj])
    eng.resolve_until_stable()

    assert bolt_obj.zone == Zone.GRAVEYARD
    assert p2.life == 40  # never resolved, so no damage happened


# ---------------------------------------------------------------------------
# 7. Corpse Dance — partial: return top graveyard creature + haste
# ---------------------------------------------------------------------------


def test_corpse_dance_registered():
    specs = ac.specs_for(_card("Corpse Dance"))
    assert any(s.ability_kind == "spell_effect" for s in specs)


def test_corpse_dance_returns_top_creature_with_haste():
    bear = Card(id="DanceBear", name="DanceBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    other = Card(id="DanceOther", name="DanceOther", type_line="Creature — Bear",
                 is_creature=True, power=1, toughness=1)
    eng = _engine(p1_cards=[_card("Corpse Dance")])
    state = eng.state
    p1 = state.active_player
    older = GameObject(other, owner_id="p1", zone=Zone.GRAVEYARD)
    newer = GameObject(bear, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(older)
    p1.graveyard.append(newer)  # last added = "top"

    dance_obj = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 2})
    eng.cast_spell(p1, dance_obj)
    eng.resolve_until_stable()

    assert newer.zone == Zone.BATTLEFIELD
    assert older.zone == Zone.GRAVEYARD
    assert "haste" in newer.temp_keywords


# ---------------------------------------------------------------------------
# 8. Feed the Swarm — new atomic effect
# ---------------------------------------------------------------------------


def test_feed_the_swarm_registered():
    specs = ac.specs_for(_card("Feed the Swarm"))
    assert len(specs) == 1 and specs[0].ability_kind == "spell_effect"


def test_feed_the_swarm_destroys_and_loses_life_equal_to_mana_value():
    victim = Card(id="Victim", name="Victim", type_line="Creature — Bear",
                   mana_cost_string="{3}{G}", converted_mana_cost=4, is_creature=True,
                   power=3, toughness=3)
    eng = _engine(p1_cards=[_card("Feed the Swarm")])
    state = eng.state
    p1 = state.active_player
    victim_obj = _battlefield(state, victim, controller="p2")

    swarm_obj = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 1})
    eng.cast_spell(p1, swarm_obj, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj.zone == Zone.GRAVEYARD
    assert p1.life == 36  # 40 - 4


# ---------------------------------------------------------------------------
# 9. Resculpt — new atomic effect
# ---------------------------------------------------------------------------


def test_resculpt_registered():
    specs = ac.specs_for(_card("Resculpt"))
    assert len(specs) == 1 and specs[0].ability_kind == "spell_effect"


def test_resculpt_exiles_and_gives_its_controller_a_4_4_elemental():
    victim = Card(id="ResculptVictim", name="ResculptVictim", type_line="Artifact",
                  mana_cost_string="{2}", converted_mana_cost=2)
    eng = _engine(p1_cards=[_card("Resculpt")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_obj = _battlefield(state, victim, controller="p2")

    resculpt_obj = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "R": 1})
    eng.cast_spell(p1, resculpt_obj, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj.zone == Zone.EXILE
    tokens = [o for o in state.battlefield if o.name == "Elemental" and o.controller_id == "p2"]
    assert len(tokens) == 1
    assert tokens[0].power == 4 and tokens[0].toughness == 4


def test_crib_swap_exiles_a_creature_and_gives_its_controller_changeling():
    victim = Card(id="CribSwapVictim", name="CribSwapVictim", type_line="Creature — Bear",
                  is_creature=True, power=2, toughness=2)
    eng = _engine(p1_cards=[_card("Crib Swap")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_obj = _battlefield(state, victim, controller="p2")

    spell = p1.hand[0]
    p1.mana_pool.add_many({"W": 1, "C": 2})
    eng.cast_spell(p1, spell, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj.zone == Zone.EXILE
    [token] = [o for o in state.battlefield if o.name == "Shapeshifter"]
    assert token.controller_id == p2.id
    assert (token.power, token.toughness) == (1, 1)
    assert "changeling" in token.intrinsic_keywords


# ---------------------------------------------------------------------------
# 10. Mirage Mirror — activated `become_copy_until_eot`
# ---------------------------------------------------------------------------


def test_mirage_mirror_registered():
    specs = ac.specs_for(_card("Mirage Mirror"))
    assert len(specs) == 1 and specs[0].ability_kind == "activated"


def test_mirage_mirror_becomes_a_copy_of_target_permanent_until_end_of_turn():
    bear = Card(id="MirrorBear", name="MirrorBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    bear_obj = _battlefield(state, bear, controller="p2")
    mirror_obj = _battlefield(state, _card("Mirage Mirror"), controller="p1")
    mirror_obj.summoning_sick = False

    state.players[0].mana_pool.add("C", 2)
    eng.activate_ability(state.players[0], mirror_obj, 0, targets=[bear_obj])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert mirror_obj.name == "MirrorBear"
    assert mirror_obj.power == 2 and mirror_obj.toughness == 2


# ---------------------------------------------------------------------------
# 11. Phyrexian Metamorph — enter_as_copy replacement
# ---------------------------------------------------------------------------


def test_phyrexian_metamorph_registered():
    specs = ac.specs_for(_card("Phyrexian Metamorph"))
    assert len(specs) == 1 and specs[0].ability_kind == "enter_replacement"


def test_phyrexian_metamorph_enters_as_a_copy_and_gains_artifact_type():
    bear = Card(id="MetaBear", name="MetaBear", type_line="Creature — Bear",
                is_creature=True, power=3, toughness=3)
    eng = _engine(p1_cards=[_card("Phyrexian Metamorph")])
    state = eng.state
    p1 = state.active_player
    bear_obj = _battlefield(state, bear, controller="p2")

    meta_obj = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 2})
    eng.cast_spell(p1, meta_obj)
    eng.rules.resolve_top_of_stack()
    # Interactive "enter as a copy" choice — answer it directly if opened.
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "enter_as_copy":
        eng.rules.resolve_choice(str(bear_obj.instance_id))

    resolved = next(o for o in state.battlefield if o.instance_id == meta_obj.instance_id)
    assert resolved.name == "MetaBear"
    assert resolved.card.is_artifact


# ---------------------------------------------------------------------------
# 12. Steal Enchantment — control_change static, attached_permanent
# ---------------------------------------------------------------------------


def test_steal_enchantment_registered():
    specs = ac.specs_for(_card("Steal Enchantment"))
    assert any(s.ability_kind == "static" for s in specs)


def test_steal_enchantment_takes_control_of_the_enchanted_enchantment():
    pact = Card(id="Pact", name="Pact", type_line="Enchantment",
                mana_cost_string="{1}{U}", converted_mana_cost=2)
    eng = _engine()
    state = eng.state
    pact_obj = _battlefield(state, pact, controller="p2")
    steal_obj = _battlefield(state, _card("Steal Enchantment"), controller="p1")
    steal_obj.attached_to = pact_obj.instance_id

    eng.recompute_continuous_effects()
    assert pact_obj.controller_id == "p1"


# ---------------------------------------------------------------------------
# 13. Grinding Station — sac-artifact mill + ETB untap trigger
# ---------------------------------------------------------------------------


def test_grinding_station_registered():
    specs = ac.specs_for(_card("Grinding Station"))
    assert len(specs) == 2
    kinds = {s.ability_kind for s in specs}
    assert kinds == {"activated", "triggered"}


def test_grinding_station_mills_three_when_sacrificing_an_artifact():
    fodder = Card(id="Fodder", name="Fodder", type_line="Artifact",
                  mana_cost_string="{1}", converted_mana_cost=1)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(10):
        lib_card = Card(id=f"Lib{i}", name=f"Lib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib_card, owner_id="p1", zone=Zone.LIBRARY))
    station_obj = _battlefield(state, _card("Grinding Station"), controller="p1")
    _battlefield(state, fodder, controller="p1")
    library_before = len(p1.library)

    eng.activate_ability(p1, station_obj, 0, targets=[p1])
    eng.resolve_until_stable()

    # The auto-picked sacrifice (station or fodder — either is a legal
    # "an artifact") isn't itself milled, so only the library shrinks by
    # exactly the mill count regardless of which was sacrificed.
    assert library_before - len(p1.library) == 3


def test_grinding_station_may_untap_when_an_artifact_enters():
    fodder = Card(id="Fodder2", name="Fodder2", type_line="Artifact",
                  mana_cost_string="{1}", converted_mana_cost=1)
    eng = _engine(p1_cards=[fodder])
    state = eng.state
    p1 = state.active_player
    station_obj = _battlefield(state, _card("Grinding Station"), controller="p1")
    station_obj.tapped = True

    fodder_obj = p1.hand[0]
    p1.mana_pool.add("C", 1)
    eng.cast_spell(p1, fodder_obj)
    eng.resolve_until_stable()

    # An optional "you may" trigger — resolve it if it opened a choice.
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "trigger_target":
        eng.rules.resolve_choice("do")
        eng.resolve_until_stable()

    assert station_obj.tapped is False


# ---------------------------------------------------------------------------
# 14. Goblin Engineer — ETB search-to-graveyard + reanimate activated
# ---------------------------------------------------------------------------


def test_goblin_engineer_registered():
    specs = ac.specs_for(_card("Goblin Engineer"))
    assert len(specs) == 2
    kinds = {s.ability_kind for s in specs}
    assert kinds == {"triggered", "activated"}


def test_goblin_engineer_returns_an_artifact_from_graveyard():
    gadget = Card(id="Gadget", name="Gadget", type_line="Artifact",
                  mana_cost_string="{2}", converted_mana_cost=2)
    fodder = Card(id="EngFodder", name="EngFodder", type_line="Artifact",
                  mana_cost_string="{1}", converted_mana_cost=1)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    engineer_obj = _battlefield(state, _card("Goblin Engineer"), controller="p1")
    _battlefield(state, fodder, controller="p1")
    gadget_obj = GameObject(gadget, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(gadget_obj)

    p1.mana_pool.add("R", 1)
    eng.activate_ability(p1, engineer_obj, 0, targets=[gadget_obj])
    eng.resolve_until_stable()

    assert gadget_obj.zone == Zone.BATTLEFIELD


# ---------------------------------------------------------------------------
# 15. Winds of Abandon — new atomic effect
# ---------------------------------------------------------------------------


def test_winds_of_abandon_registered():
    specs = ac.specs_for(_card("Winds of Abandon"))
    # Plus a separately-folded-in Overload keyword spec (RULE 702.96, no
    # behavioral effect yet — see the catalogue entry's docstring).
    spell_effect_specs = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effect_specs) == 1


def test_winds_of_abandon_exiles_and_opponent_searches_for_a_basic_land():
    victim = Card(id="WindsVictim", name="WindsVictim", type_line="Creature — Bear",
                  is_creature=True, power=2, toughness=2)
    forest = Card(id="WindsForest", name="WindsForest", type_line="Basic Land — Forest", is_land=True)
    eng = _engine(p1_cards=[_card("Winds of Abandon")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_obj = _battlefield(state, victim, controller="p2")
    p2_lib_card = forest
    p2_lib_obj = GameObject(p2_lib_card, owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(p2_lib_obj)

    winds_obj = p1.hand[0]
    p1.mana_pool.add_many({"W": 1, "C": 3})
    eng.cast_spell(p1, winds_obj, targets=[victim_obj])
    eng.rules.resolve_top_of_stack()

    assert victim_obj.zone == Zone.EXILE
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "search":
        eng.rules.resolve_choice(p2_lib_obj.instance_id)
    assert p2_lib_obj.zone == Zone.BATTLEFIELD
    assert p2_lib_obj.tapped is True


# ---------------------------------------------------------------------------
# 16. Eiganjo, Seat of the Empire — Channel activated ability
# ---------------------------------------------------------------------------


def test_eiganjo_registered():
    specs = ac.specs_for(_card("Eiganjo, Seat of the Empire"))
    assert len(specs) == 1 and specs[0].ability_kind == "activated"


def test_eiganjo_channels_to_deal_4_damage_to_a_creature():
    victim = Card(id="EiganjoVictim", name="EiganjoVictim", type_line="Creature — Bear",
                  is_creature=True, power=3, toughness=5)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    victim_obj = _battlefield(state, victim, controller="p2")
    eiganjo_obj = GameObject(_card("Eiganjo, Seat of the Empire"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(eiganjo_obj)
    p1.hand.append(eiganjo_obj)
    p1.mana_pool.add_many({"W": 1, "C": 2})

    ability = eiganjo_obj.activated_abilities[0]
    idx = eiganjo_obj.activated_abilities.index(ability)
    eng.activate_ability(p1, eiganjo_obj, idx, targets=[victim_obj])
    eng.resolve_until_stable()

    assert eiganjo_obj.zone == Zone.GRAVEYARD
    assert victim_obj.damage_marked == 4


# ---------------------------------------------------------------------------
# 17. Winter Orb — global untap cap
# ---------------------------------------------------------------------------


def test_winter_orb_registered():
    specs = ac.specs_for(_card("Winter Orb"))
    assert len(specs) == 1 and specs[0].ability_kind == "static"


def test_winter_orb_caps_lands_untapped_to_one():
    land1 = Card(id="OrbLand1", name="OrbLand1", type_line="Basic Land — Forest", is_land=True)
    land2 = Card(id="OrbLand2", name="OrbLand2", type_line="Basic Land — Island", is_land=True)
    eng = _engine()
    state = eng.state
    orb_obj = _battlefield(state, _card("Winter Orb"), controller="p2")
    orb_obj.tapped = False
    l1 = _battlefield(state, land1, controller="p1")
    l2 = _battlefield(state, land2, controller="p1")
    l1.tapped = True
    l2.tapped = True

    eng._step_untap()

    untapped_count = sum(1 for o in (l1, l2) if not o.tapped)
    assert untapped_count == 1


def test_winter_orb_no_cap_once_it_is_tapped():
    land1 = Card(id="OrbLand3", name="OrbLand3", type_line="Basic Land — Forest", is_land=True)
    land2 = Card(id="OrbLand4", name="OrbLand4", type_line="Basic Land — Island", is_land=True)
    eng = _engine()
    state = eng.state
    orb_obj = _battlefield(state, _card("Winter Orb"), controller="p2")
    orb_obj.tapped = True  # "as long as this artifact is untapped" — inactive
    l1 = _battlefield(state, land1, controller="p1")
    l2 = _battlefield(state, land2, controller="p1")
    l1.tapped = True
    l2.tapped = True

    eng._step_untap()

    assert l1.tapped is False and l2.tapped is False
