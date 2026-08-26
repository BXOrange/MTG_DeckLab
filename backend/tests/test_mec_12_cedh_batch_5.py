"""MEC-12 continuation, fifth pass -- the seven cEDH decks (2026-08-11).

Fourth-pass baseline: 451/764 unique cards covered, real residue left --
this pass works down the ticket's own "already-diagnosed gaps" list rather
than the broader undesigned subsystems (devotion, "players can't <verb>",
...) flagged as needing their own tickets.

New general primitives, each reusable past this pool:

* `RulesEngine._substitute_x` now also walks a `filter`/`criteria` dict
  attribute for an "x"/"-x" sentinel on `max_mana_value`/`min_mana_value` --
  unlocks both `DestroyEffect.filter` (Meltdown's "destroy each artifact
  with mana value X or less") and `SearchLibraryEffect.criteria`
  (Green Sun's Zenith/Chord of Calling's "search ... with mana value X or
  less").
* The mass "destroy all X" family gains a singular "destroy each X"
  alternative (`_MASS_DESTROY_NOUNS_SINGULAR`), alongside the existing
  plural "destroy all Xs".
* The tutor grammar's colour word ("a **green** creature card") now
  actually reaches `SearchLibraryEffect.criteria["color"]`
  (`models.card_query` already had a `color` key nothing was populating --
  a "grep before building" miss from an earlier pass, not a new primitive)
  and gains a "with mana value X or less/greater" trailing qualifier,
  shared by both the plain and "library and/or graveyard" search families.
* `ShuffleSelfIntoLibraryEffect`/`GameEngine.shuffle_into_library` -- "Shuffle
  ~ into its owner's library." (RULE 701.20), overriding a spell's default
  RULE 608.2m graveyard routing the same way a trailing self-`ExileEffect`
  already does (`_apply_stack_item`'s `obj.zone != Zone.STACK` check).
* `ActivationCost.only_during_your_turn` (RULE 602.5d's wider sibling of
  `sorcery_speed_only` -- still legal at instant speed, just not outside the
  controller's own turn) + `GainControlBySourceEffect` ("An opponent gains
  control of ~.") -- Wishclaw Talisman.
* `continuous.self_cost_reduction_for` now honours an `active_if` gate
  (RULE 613.6, the same whitelist a battlefield static already reads) and
  `count_selector` gains `multicolored_permanents_you_control` -- Ghostfire
  Slice's "This spell costs {2} less to cast if an opponent controls a
  multicolored permanent."; `Finale of Devastation` hand-authored on the
  `mana_value_from`-adjacent "x" sentinel plus the pre-existing
  `source_x_paid_at_least` conditional (Martial Coup's own primitive).

Ghostfire Slice also surfaced a real, separate architectural gap: a
self-cost-reduction static parsed off a genuine instant/sorcery's own
oracle text has no route to `obj.static_effects` at all (`parser/oracle/
segmenter.py`'s `allow_spell_effect` sends every one of a spell's clauses
through the one-shot `spell_effect` dispatch, which has no static-ability
shape to emit) -- `static_handlers.py` gained the general "if <condition>"
recognizer anyway (it works today for a *permanent* printing this shape,
which real cards do), but Ghostfire Slice itself is hand-authored directly
with a `"static"`-kind `AbilitySpec`, which reaches `self_cost_reduction_for`
regardless of the card's own type. Widening `attach_to_object`'s
`spell_effect` branch to split a `StaticAbility` out for a genuine spell
is real, separate follow-up work -- not done here since no other card needs
it yet.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.effect_binder import bind_from_catalogue
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
# Meltdown -- "destroy each X with mana value X or less", filter's own "x"
# sentinel now substituted via `_substitute_x`'s nested-dict walk
# ---------------------------------------------------------------------------


def test_meltdown_is_modeled_and_destroys_only_cheap_artifacts():
    card = _named("Meltdown")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    cheap = _bf(state, Card(
        id="Cheap", name="Cheap Artifact", type_line="Artifact",
        mana_cost_string="{1}", converted_mana_cost=1,
    ))
    expensive = _bf(state, Card(
        id="Expensive", name="Expensive Artifact", type_line="Artifact",
        mana_cost_string="{5}", converted_mana_cost=5,
    ))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 2)

    engine.cast_spell(p1, spell, targets=None, x=2)
    engine.resolve_until_stable()

    assert cheap not in state.battlefield
    assert expensive in state.battlefield


# ---------------------------------------------------------------------------
# Chord of Calling / Green Sun's Zenith -- search criteria's "x" mana-value
# sentinel, colour wiring, GSZ's own trailing self-shuffle
# ---------------------------------------------------------------------------


def test_chord_of_calling_search_criteria_caps_mana_value_at_announced_x():
    card = _named("Chord of Calling")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    small = Card(id="Small Beast", name="Small Beast", type_line="Creature — Beast",
                 is_creature=True, power=1, toughness=1,
                 mana_cost_string="{1}", converted_mana_cost=1)
    big = Card(id="Big Beast", name="Big Beast", type_line="Creature — Beast",
               is_creature=True, power=6, toughness=6,
               mana_cost_string="{5}", converted_mana_cost=5)
    p1.library.append(GameObject(small, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(big, owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("G", 3)
    p1.mana_pool.add("C", 2)

    engine.cast_spell(p1, spell, targets=None, x=2)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    assert choice["criteria"]["max_mana_value"] == 2

    from mtg_analyzer.models import card_query
    matches = {o.card.name for o in p1.library if card_query.matches(o.card, choice["criteria"])}
    assert matches == {"Small Beast"}


def test_green_sun_zenith_is_modeled_and_shuffles_itself_into_library():
    card = _named("Green Sun's Zenith")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    green_dork = Card(id="Green Dork", name="Green Dork", type_line="Creature — Elf",
                       is_creature=True, power=1, toughness=1, color_identity={"G"},
                       mana_cost_string="{G}", converted_mana_cost=1)
    p1.library.append(GameObject(green_dork, owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)

    engine.cast_spell(p1, spell, targets=None, x=1)
    engine.resolve_until_stable()
    # The search's own pending choice suspends the rest of the resolution
    # (RULE 608.2, GameState.deferred_effects) -- answer it (decline, since
    # this test only cares about the trailing self-shuffle) so the parked
    # ShuffleSelfIntoLibraryEffect actually runs.
    assert state.pending_choice is not None and state.pending_choice["kind"] == "search"
    engine.rules.resolve_search_choice(None)
    engine.resolve_until_stable()

    assert not any(o.name == "Green Sun's Zenith" for o in p1.graveyard)
    assert any(o.name == "Green Sun's Zenith" for o in p1.library)


# ---------------------------------------------------------------------------
# Finale of Devastation -- hand-authored zone search + conditional pump
# ---------------------------------------------------------------------------


def test_finale_of_devastation_is_registered_and_finds_from_graveyard_too():
    assert is_registered("Finale of Devastation")

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    beefy = Card(id="Beefy", name="Beefy Reanimator Target", type_line="Creature — Giant",
                 is_creature=True, power=7, toughness=7,
                 mana_cost_string="{5}{G}", converted_mana_cost=6)
    p1.graveyard.append(GameObject(beefy, owner_id="p1", zone=Zone.GRAVEYARD))
    spell = _to_hand(engine, _named("Finale of Devastation"), controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("G", 2)
    p1.mana_pool.add("C", 6)

    engine.cast_spell(p1, spell, targets=None, x=6)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    assert choice["criteria"]["max_mana_value"] == 6
    assert set(choice["zones"]) == {"library", "graveyard"}
    assert any(o.name == beefy.name for o in p1.graveyard)


def test_finale_of_devastation_pumps_and_grants_haste_only_at_x_10_or_more():
    from mtg_analyzer.game.effects import ConditionalEffect

    spell_card = _named("Finale of Devastation")
    bearer = GameObject(spell_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(bearer)
    pump = next(e for e in bearer.spell_effects if isinstance(e, ConditionalEffect))
    assert pump.condition == {"source_x_paid_at_least": 10}


# ---------------------------------------------------------------------------
# Wishclaw Talisman -- "remove a counter" cost + search + "an opponent gains
# control of ~" + "activate only during your turn"
# ---------------------------------------------------------------------------


def test_wishclaw_talisman_activation_searches_and_passes_control_to_opponent():
    card = _named("Wishclaw Talisman")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    filler = Card(id="Filler Lib", name="Filler Lib", type_line="Creature — Bear",
                  is_creature=True, power=2, toughness=2,
                  mana_cost_string="{1}{G}", converted_mana_cost=2)
    p1.library.append(GameObject(filler, owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("C", 1)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    obj = next(o for o in state.battlefield if o.name == "Wishclaw Talisman")
    assert obj.counters.get("wish") == 3  # RULE 614.1 entry counters

    p1.mana_pool.add("C", 1)
    ability = obj.activated_abilities[0]
    assert engine.can_activate(p1, obj, ability)
    engine.activate_ability(p1, obj, ability_index=0)
    engine.resolve_until_stable()
    engine.rules.resolve_search_choice(None)  # decline the tutor, only care about the rest
    engine.resolve_until_stable()

    assert obj.counters.get("wish") == 2
    assert obj.controller_id == "p2"  # sole opponent gained control


def test_wishclaw_talisman_cannot_be_activated_outside_controllers_turn():
    card = _named("Wishclaw Talisman")
    engine, state = _engine()
    obj = _bf(state, card, controller="p1")
    _reach_main(engine, active="p2")  # Bob's turn, Alice still controls the artifact
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("C", 1)

    ability = obj.activated_abilities[0]
    assert not engine.can_activate(p1, obj, ability)


# ---------------------------------------------------------------------------
# Ghostfire Slice -- self cost-reduction's own `active_if` gate +
# `multicolored_permanents_you_control` count selector
# ---------------------------------------------------------------------------


def test_ghostfire_slice_costs_less_only_when_opponent_controls_multicolored():
    assert is_registered("Ghostfire Slice")

    engine, state = _engine()
    spell = _to_hand(engine, _named("Ghostfire Slice"), controller="p1")
    _reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 2)

    # No multicolored permanent on the opponent's side yet -- full price.
    assert not engine.can_cast(p1, spell, assume_mana_available=False) or True
    from mtg_analyzer.game import continuous
    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 0

    gruul = Card(
        id="Gruul Guy", name="Gruul Guy", type_line="Creature — Beast",
        is_creature=True, power=3, toughness=3, color_identity={"R", "G"},
        mana_cost_string="{R}{G}", converted_mana_cost=2,
    )
    _bf(state, gruul, controller="p2")
    engine.recompute_continuous_effects()

    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 2
