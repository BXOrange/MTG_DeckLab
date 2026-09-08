"""MEC-12 continuation, sixth pass (2026-08-11) -- the seven cEDH decks.

The fifth pass closed the tutor-family/Meltdown/Wishclaw/Ghostfire Slice
cluster and re-diagnosed the rest of BACKLOG.md's MEC-12 "specific,
already-diagnosed gaps" list. This repo's own "no half-implementations"
discipline means an item deferred a *second* time must be hand-authored or
explicitly promoted, not silently rolled to a third deferral -- these six
items were at exactly that point, so this pass closes every one of them:

* **Mox Diamond** -- RULE 614.12's own worked example ("if ~ would enter,
  you may discard a land card instead. If you do, put ~ onto the
  battlefield. If you don't, put it into its owner's graveyard.") as a new
  general primitive: `AbilitySpec.enter_or_graveyard_discard_land` +
  `RulesEngine._offer_enter_or_graveyard`, spliced into
  `_resolve_permanent_spell`'s existing continuation-passing chain
  *before* every other entry choice (enter-as-copy, enter-choice, Read
  Ahead) -- since declining means the object never becomes a permanent at
  all, none of those matter. A new `shuffle_into_library`-shaped mover,
  `_send_to_graveyard_unentered`, reuses the exact same "one of this
  spell's own effects already moved it off the stack" recognition
  `_apply_stack_item` already had for a trailing self-`ExileEffect`.
* **Mindbreak Trap** -- "exile any number of target spells" turned out to
  need one row, not a new primitive: `_multi_target_params`'s "any number
  of" idiom (`_ANY_NUMBER_TARGET_CAP`) was already fully general (Fire
  Covenant/Display of Power both already use it), just missing a "target
  spells" target-kind row. Kept *out* of the shared `_MULTI_TARGET_ROWS`
  every other multi-target family (destroy/damage/tap/...) also reads,
  since "destroy target spells"/"N damage to target spells" aren't real
  templates -- only `exile`'s own regex opts into the wider alternation
  (`_MULTI_TARGET_ALT_WITH_SPELL`), caught by a real regression test this
  pass had to fix (`test_multi_target.py`'s own "stays unclaimed" case).
* **Eye of Ugin** -- two independent gaps: `models.card_query`'s `color`
  key gained a `"colorless"` special case (empty colour identity, not a
  membership check -- kept local to the search vocabulary rather than
  widened into the shared WUBRG-only `resolve_color_word`, since "target
  colorless creature" isn't a valid substitute for any of *that*
  vocabulary's other consumers); `continuous.cost_reduction_for` gained a
  `spell_subtype` filter (creature subtype, e.g. "Eldrazi" -- orthogonal to
  the existing main-card-type-only `spell_type`) composed by plain AND
  with `spell_color="colorless"`. Hand-authored (both halves reach real
  primitives, but the combined shape is a singleton).
* **Stonehewer Giant / Quest for the Holy Relic** -- `SearchLibraryEffect`
  gained `attach_to_creature_you_control` (applied right after
  `extra_counters`, the same "extra step once the found card reaches the
  battlefield" slot Neoform's counter already uses), reached by a new,
  fully general oracle-text handler
  (`_SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE`) -- both cards MODELED outright,
  no hand-authoring. Quest for the Holy Relic's own trigger needed only a
  vocabulary word (`_NAMED_COUNTER_KINDS` gains "quest").
* **Tainted Pact** -- a genuinely new loop shape, `ExileUntilDuplicateName
  Effect`/`RulesEngine.exile_until_duplicate_name`: a real interactive
  `pending_choice` ("take" vs. "continue digging") on every non-duplicate
  hit with library left, not an auto-take -- the whole reason this card is
  played in cEDH is *declining* every hit (paired with Thassa's Oracle in
  a singleton deck) to mill the entire library on purpose.
* **Transmute Artifact** -- confirmed a singleton cost-comparison-gated
  placement; one self-contained bespoke `RulesEngine.transmute_artifact`
  sequence (three of its own `pending_choice` kinds: sacrifice, search,
  optional pay-the-difference) rather than composed from the general
  primitives, none of which can express "the cost is a number computed
  from what a different, just-made choice turned out to be".

Full backend suite: 3,556 passed, 238 skipped, 0 regressions (one
pre-existing flaky websocket test, unrelated, confirmed passing in
isolation).
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    return engine, state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _reach_main(engine, active="p1"):
    engine.begin_turn()
    while engine.state.active_player.id != active:
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


# ---------------------------------------------------------------------------
# Mox Diamond -- RULE 614.12 enter-or-graveyard replacement
# ---------------------------------------------------------------------------


def test_mox_diamond_discards_a_land_to_enter():
    card = _named("Mox Diamond")
    assert is_registered("Mox Diamond")

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    spell = _to_hand(engine, card, controller="p1")
    land = _to_hand(engine, Card(
        id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True,
    ), controller="p1")
    _reach_main(engine)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "enter_or_graveyard"
    engine.rules.resolve_enter_or_graveyard_choice(str(land.instance_id))
    engine.resolve_until_stable()

    assert any(o.name == "Mox Diamond" for o in state.battlefield)
    assert any(o.name == "Forest" for o in p1.graveyard)


def test_mox_diamond_declined_goes_to_graveyard_never_a_permanent():
    card = _named("Mox Diamond")
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    spell = _to_hand(engine, card, controller="p1")
    _to_hand(engine, Card(
        id="Forest2", name="Forest2", type_line="Basic Land — Forest", is_land=True,
    ), controller="p1")
    _reach_main(engine)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    engine.rules.resolve_enter_or_graveyard_choice("decline")
    engine.resolve_until_stable()

    assert not any(o.name == "Mox Diamond" for o in state.battlefield)
    assert any(o.name == "Mox Diamond" for o in p1.graveyard)


def test_mox_diamond_with_no_land_in_hand_skips_the_prompt():
    card = _named("Mox Diamond")
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()

    assert state.pending_choice is None
    assert any(o.name == "Mox Diamond" for o in p1.graveyard)


# ---------------------------------------------------------------------------
# Mindbreak Trap -- "exile any number of target spells"
# ---------------------------------------------------------------------------


def test_mindbreak_trap_is_modeled():
    assert parse_oracle(_named("Mindbreak Trap")).modeled


# ---------------------------------------------------------------------------
# Eye of Ugin -- colorless search + combined colour/subtype cost filter
# ---------------------------------------------------------------------------


def test_eye_of_ugin_cost_reduction_needs_colorless_and_eldrazi_together():
    from mtg_analyzer.game import continuous

    engine, state = _engine()
    _bf(state, _named("Eye of Ugin"), controller="p1")
    p1 = state.player_by_id("p1")

    colorless_eldrazi = Card(
        id="CE", name="Colorless Eldrazi Spell", type_line="Sorcery — Eldrazi",
        mana_cost_string="{5}", converted_mana_cost=5, is_sorcery=True,
    )
    ce_obj = GameObject(colorless_eldrazi, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(ce_obj)
    net, _ = continuous.cost_reduction_for(state, p1, ce_obj)
    assert net == 2

    colored_eldrazi = Card(
        id="RE", name="Colored Eldrazi Spell", type_line="Sorcery — Eldrazi",
        mana_cost_string="{3}{R}", converted_mana_cost=4, is_sorcery=True,
        color_identity={"R"},
    )
    re_obj = GameObject(colored_eldrazi, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(re_obj)
    net2, _ = continuous.cost_reduction_for(state, p1, re_obj)
    assert net2 == 0

    not_eldrazi = Card(
        id="NE", name="Not Eldrazi Spell", type_line="Sorcery",
        mana_cost_string="{5}", converted_mana_cost=5, is_sorcery=True,
    )
    ne_obj = GameObject(not_eldrazi, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(ne_obj)
    net3, _ = continuous.cost_reduction_for(state, p1, ne_obj)
    assert net3 == 0


def test_eye_of_ugin_search_finds_only_colorless_creatures():
    from mtg_analyzer.models import card_query

    engine, state = _engine()
    land = _bf(state, _named("Eye of Ugin"), controller="p1")
    p1 = state.player_by_id("p1")
    colorless = Card(id="ColorlessCr", name="ColorlessCr", type_line="Creature — Eldrazi",
                      is_creature=True, power=5, toughness=5, color_identity=set())
    colored = Card(id="ColoredCr", name="ColoredCr", type_line="Creature — Bear",
                    is_creature=True, power=2, toughness=2, color_identity={"G"})
    p1.library.append(GameObject(colorless, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(colored, owner_id="p1", zone=Zone.LIBRARY))
    _reach_main(engine)
    p1.mana_pool.add("C", 7)

    ability = land.activated_abilities[0]
    assert engine.can_activate(p1, land, ability)
    engine.activate_ability(p1, land, ability_index=0)
    engine.resolve_until_stable()
    choice = state.pending_choice
    matches = {o.card.name for o in p1.library if card_query.matches(o.card, choice["criteria"])}
    assert matches == {"ColorlessCr"}


# ---------------------------------------------------------------------------
# Stonehewer Giant / Quest for the Holy Relic -- search-then-attach
# ---------------------------------------------------------------------------


def test_stonehewer_giant_is_modeled_and_search_attaches_to_a_creature():
    card = _named("Stonehewer Giant")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    giant = _bf(state, card, controller="p1")
    p1 = state.player_by_id("p1")
    equipment = Card(id="SomeEquip", name="SomeEquip", type_line="Artifact — Equipment",
                      mana_cost_string="{2}", converted_mana_cost=2,
                      oracle_text="Equipped creature gets +1/+1.\nEquip {2}",
                      keywords=["Equip"])
    equip_obj_in_lib = GameObject(equipment, owner_id="p1", zone=Zone.LIBRARY)
    bind_from_catalogue(equip_obj_in_lib)
    p1.library.append(equip_obj_in_lib)
    _reach_main(engine)
    p1.mana_pool.add("W", 1)
    p1.mana_pool.add("C", 1)

    ability = giant.activated_abilities[0]
    assert engine.can_activate(p1, giant, ability)
    engine.activate_ability(p1, giant, ability_index=0)
    engine.resolve_until_stable()
    choice = state.pending_choice
    equip_id = next(e["instance_id"] for e in choice["eligible"] if e["name"] == "SomeEquip")
    engine.rules.resolve_search_choice(equip_id)
    engine.resolve_until_stable()

    equip_obj = next(o for o in state.battlefield if o.name == "SomeEquip")
    assert equip_obj.attached_to == giant.instance_id


def test_quest_for_the_holy_relic_is_modeled():
    assert parse_oracle(_named("Quest for the Holy Relic")).modeled


# ---------------------------------------------------------------------------
# Tainted Pact -- exile-until-duplicate-name loop
# ---------------------------------------------------------------------------


def test_tainted_pact_takes_a_fresh_name_when_declined_to_continue():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    top_card = Card(id="Fresh", name="Fresh", type_line="Creature — Bear",
                     is_creature=True, power=2, toughness=2,
                     mana_cost_string="{1}{G}", converted_mana_cost=2)
    p1.library.append(GameObject(top_card, owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, _named("Tainted Pact"), controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("B", 2)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    assert state.pending_choice is None  # empty library after taking it -- auto-resolved
    assert any(o.name == "Fresh" for o in p1.hand)


def test_tainted_pact_continuing_can_hit_a_duplicate_and_gain_nothing():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    dup = Card(id="Dup", name="Dup", type_line="Creature — Bear",
               is_creature=True, power=2, toughness=2,
               mana_cost_string="{1}{G}", converted_mana_cost=2)
    p1.library.append(GameObject(dup, owner_id="p1", zone=Zone.LIBRARY))  # bottom
    p1.library.append(GameObject(dup, owner_id="p1", zone=Zone.LIBRARY))  # top
    spell = _to_hand(engine, _named("Tainted Pact"), controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("B", 2)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "tainted_pact"
    engine.rules.resolve_tainted_pact_choice("continue")
    engine.resolve_until_stable()

    assert p1.hand == []
    assert len(p1.exile) == 2


# ---------------------------------------------------------------------------
# Transmute Artifact -- bespoke sacrifice/search/pay-X sequence
# ---------------------------------------------------------------------------


def test_transmute_artifact_cheap_find_enters_free():
    card = _named("Transmute Artifact")
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    _bf(state, Card(id="Sac4", name="Sac4", type_line="Artifact",
                     mana_cost_string="{4}", converted_mana_cost=4), controller="p1")
    p1.library.append(GameObject(Card(
        id="Cheap2", name="Cheap2", type_line="Artifact",
        mana_cost_string="{2}", converted_mana_cost=2,
    ), owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("U", 2)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice["kind"] == "transmute_search"
    found_id = next(o["instance_id"] for o in choice["options"] if o.get("label") == "Cheap2")
    engine.rules.resolve_transmute_search_choice(str(found_id))
    engine.resolve_until_stable()

    assert any(o.name == "Cheap2" for o in state.battlefield)
    assert state.pending_choice is None


def test_transmute_artifact_pricier_find_needs_the_difference_paid():
    card = _named("Transmute Artifact")
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    _bf(state, Card(id="Sac2b", name="Sac2b", type_line="Artifact",
                     mana_cost_string="{2}", converted_mana_cost=2), controller="p1")
    p1.library.append(GameObject(Card(
        id="Pricey6", name="Pricey6", type_line="Artifact",
        mana_cost_string="{6}", converted_mana_cost=6,
    ), owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("U", 2)
    p1.mana_pool.add("C", 4)  # the {4} difference, paid later

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    found_id = next(o["instance_id"] for o in state.pending_choice["options"] if o.get("label") == "Pricey6")
    engine.rules.resolve_transmute_search_choice(str(found_id))
    engine.resolve_until_stable()

    assert state.pending_choice["kind"] == "transmute_pay_x"
    engine.rules.resolve_transmute_pay_x_choice("decline")
    engine.resolve_until_stable()

    assert not any(o.name == "Pricey6" for o in state.battlefield)
    assert any(o.name == "Pricey6" for o in p1.graveyard)
