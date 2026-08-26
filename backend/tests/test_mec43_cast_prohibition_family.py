"""MEC-43 — `cast_prohibition`'s two "shared primitive" clusters plus MEC-45
(Chandra's Incinerator, `Ojer cEDH`'s last real engine gap):

* Cluster 1 (literal/eq mana-value threshold): Gaddock Teeg, Sanctum
  Prelate, Chalice of the Void (built as a counter-trigger, not a third
  `cast_prohibition`), Ethersworn Canonist.
* Cluster 2 (activation-cost sacrifice-value stamping): Birthing Pod,
  Oswald Fiddlebender.
* MEC-45: Chandra's Incinerator.

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bear(name="Bear", cost="{1}{G}", cmc=2):
    return _card(name, "Creature — Bear", cost, cmc, is_creature=True, power=2, toughness=2)


def _bf(state, card, controller="p1", obj=None, bind=False):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    if bind:
        bind_from_catalogue(obj)
    return obj


def _catalogue_obj(state, name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Gaddock Teeg — literal mana-value threshold + independent {X}-cost clause
# ---------------------------------------------------------------------------


def test_gaddock_teeg_prohibits_noncreature_spells_mv_4_or_greater():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Gaddock Teeg", controller="p1")
    engine.recompute_continuous_effects()

    small = _card("Shock", "Instant", "{R}", 1, is_instant=True)
    big = _card("Wrath of God", "Sorcery", "{2}{W}{W}", 4, is_sorcery=True)

    assert continuous.cast_prohibited(state, p2, small) is False
    assert continuous.cast_prohibited(state, p2, big) is True
    # `scope="all"` — binds Gaddock Teeg's own controller too.
    assert continuous.cast_prohibited(state, p1, big) is True


def test_gaddock_teeg_prohibits_noncreature_spells_with_x_in_cost():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Gaddock Teeg", controller="p1")
    engine.recompute_continuous_effects()

    fireball = _card("Fireball", "Sorcery", "{X}{R}", 1, is_sorcery=True)
    creature = _card("Genesis Wave", "Sorcery", "{X}{G}{G}", 2, is_sorcery=True)

    assert continuous.cast_prohibited(state, p2, fireball) is True
    assert continuous.cast_prohibited(state, p2, creature) is True  # mv 2, no threshold trip needed


def test_gaddock_teeg_does_not_restrict_creature_spells():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Gaddock Teeg", controller="p1")
    engine.recompute_continuous_effects()

    huge_creature = _bear("Huge Beast", "{6}{G}{G}", 8)
    assert continuous.cast_prohibited(state, p2, huge_creature) is False


# ---------------------------------------------------------------------------
# Sanctum Prelate — "choose a number" ETB + eq-mode cast_prohibition
# ---------------------------------------------------------------------------


def test_sanctum_prelate_choose_number_stamps_chosen_number():
    engine, state, p1, _ = _engine()
    spell = _to_hand(state, _named("Sanctum Prelate"))
    p1.mana_pool.add_many({"W": 2, "C": 1})
    state.current_step = "main1"

    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "choose_number"
    assert choice.get("free_text") is True
    engine.rules.resolve_enter_choice("3")

    prelate = next(o for o in state.battlefield if o.name == "Sanctum Prelate")
    assert prelate.chosen_number == 3


def test_sanctum_prelate_prohibits_only_the_exact_chosen_mana_value():
    engine, state, p1, p2 = _engine()
    prelate = _catalogue_obj(state, "Sanctum Prelate", controller="p1")
    prelate.chosen_number = 3
    engine.recompute_continuous_effects()

    two = _card("Doom Blade", "Instant", "{1}{B}", 2, is_instant=True)
    three = _card("Counterspell", "Instant", "{U}{U}", 3, is_instant=True)

    assert continuous.cast_prohibited(state, p2, two) is False
    assert continuous.cast_prohibited(state, p2, three) is True


# ---------------------------------------------------------------------------
# Chalice of the Void — counter-trigger sibling, not a third cast_prohibition
# ---------------------------------------------------------------------------


def test_chalice_of_the_void_enters_with_x_charge_counters():
    engine, state, p1, _ = _engine()
    spell = _to_hand(state, _named("Chalice of the Void"))
    p1.mana_pool.add_many({"C": 4})
    state.current_step = "main1"

    engine.cast_spell(p1, spell, x=2)
    engine.resolve_until_stable()

    chalice = next(o for o in state.battlefield if o.name == "Chalice of the Void")
    assert chalice.counters.get("charge") == 2


def test_chalice_of_the_void_counters_a_matching_spell():
    engine, state, p1, p2 = _engine()
    chalice = _catalogue_obj(state, "Chalice of the Void", controller="p1")
    chalice.counters["charge"] = 2
    spell = _to_hand(state, _card("Doom Blade", "Instant", "{1}{B}", 2, is_instant=True), controller="p2")
    p2.mana_pool.add_many({"B": 1, "C": 1})
    state.current_step = "main1"
    engine.recompute_continuous_effects()

    engine.cast_spell(p2, spell)
    engine.resolve_until_stable()

    assert spell not in state.stack
    assert spell in p2.graveyard  # countered, not resolved


def test_chalice_of_the_void_does_not_counter_off_mana_value():
    engine, state, p1, p2 = _engine()
    chalice = _catalogue_obj(state, "Chalice of the Void", controller="p1")
    chalice.counters["charge"] = 2
    spell = _to_hand(state, _card("Shock", "Instant", "{R}", 1, is_instant=True), controller="p2")
    p2.mana_pool.add_many({"R": 1})
    state.current_step = "main1"
    engine.recompute_continuous_effects()

    engine.cast_spell(p2, spell)
    engine.resolve_until_stable()

    assert spell in p2.graveyard  # resolved normally, then hit the graveyard on its own


# ---------------------------------------------------------------------------
# Ethersworn Canonist — boolean-flag restriction, not a mana-value one
# ---------------------------------------------------------------------------


def test_ethersworn_canonist_allows_the_first_nonartifact_spell_each_turn():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Ethersworn Canonist", controller="p1")
    engine.recompute_continuous_effects()

    spell = _card("Shock", "Instant", "{R}", 1, is_instant=True)
    assert continuous.cast_prohibited(state, p2, spell) is False


def test_ethersworn_canonist_prohibits_a_second_nonartifact_spell():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Ethersworn Canonist", controller="p1")
    engine.recompute_continuous_effects()

    state.nonartifact_spells_cast_this_turn[p2.id] = 1
    spell = _card("Shock", "Instant", "{R}", 1, is_instant=True)
    artifact_spell = _card("Sol Ring", "Artifact", "{1}", 1)

    assert continuous.cast_prohibited(state, p2, spell) is True
    assert continuous.cast_prohibited(state, p2, artifact_spell) is False


# ---------------------------------------------------------------------------
# Birthing Pod / Oswald Fiddlebender — activation-cost sacrifice stamping
# ---------------------------------------------------------------------------


def test_activated_ability_sacrifice_cost_stamps_the_victims_mana_value():
    engine, state, p1, _ = _engine()
    state.current_step = "main1"
    pod = _catalogue_obj(state, "Birthing Pod", controller="p1")
    victim = _bf(state, _bear("Victim", "{1}{G}", 2))
    p1.mana_pool.add_many({"G": 1, "C": 1})
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, pod, sacrifice_choice=victim.instance_id)

    assert victim in p1.graveyard
    assert pod.sacrificed_cost_mana_value == 2


def test_birthing_pod_searches_for_one_plus_the_sacrificed_mana_value():
    engine, state, p1, _ = _engine()
    state.current_step = "main1"
    pod = _catalogue_obj(state, "Birthing Pod", controller="p1")
    victim = _bf(state, _bear("Victim", "{1}{G}", 2))
    p1.mana_pool.add_many({"G": 1, "C": 1})
    for name, cmc in (("TooCheap", 2), ("Exact", 3), ("TooBig", 4)):
        p1.add_to_zone(GameObject(_bear(name, f"{{{cmc}}}", cmc), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, pod, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    offered = {o["label"] for o in choice["options"] if o["id"] != "decline"}
    assert offered == {"Exact"}  # mana value equal to 1 + 2 = 3, exactly


def test_oswald_fiddlebender_searches_artifacts_for_one_plus_sacrificed_mv():
    engine, state, p1, _ = _engine()
    state.current_step = "main1"
    oswald = _catalogue_obj(state, "Oswald Fiddlebender", controller="p1")
    victim = _bf(state, _card("Signet", "Artifact", "{2}", 2))
    p1.mana_pool.add_many({"W": 1})
    for name, cmc in (("TooCheap", 2), ("Exact", 3)):
        p1.add_to_zone(
            GameObject(_card(name, "Artifact", f"{{{cmc}}}", cmc), owner_id="p1", zone=Zone.LIBRARY),
            Zone.LIBRARY,
        )
    engine.recompute_continuous_effects()

    engine.activate_ability(p1, oswald, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    offered = {o["label"] for o in choice["options"] if o["id"] != "decline"}
    assert offered == {"Exact"}


def test_sacrifice_stamp_resets_between_activations():
    """A stale value from a previous activation must not leak into a later
    one that sacrifices something else — MEC-43's own reset."""
    engine, state, p1, _ = _engine()
    state.current_step = "main1"
    pod = _catalogue_obj(state, "Birthing Pod", controller="p1")
    first = _bf(state, _bear("First", "{1}{G}", 2))
    p1.mana_pool.add_many({"G": 2, "C": 2})
    engine.recompute_continuous_effects()
    engine.activate_ability(p1, pod, sacrifice_choice=first.instance_id)
    assert pod.sacrificed_cost_mana_value == 2
    engine.rules.resolve_top_of_stack()  # clear the stack for the next sorcery-speed activation
    if state.pending_choice is not None:
        engine.rules.resolve_search_choice(None)  # decline — nothing to find in an empty library
    pod.tapped = False  # no untap step ran in this unit test; untap by hand for the 2nd activation

    second = _bf(state, _bear("Second", "{5}{G}", 6))
    engine.activate_ability(p1, pod, sacrifice_choice=second.instance_id)
    assert pod.sacrificed_cost_mana_value == 6


# ---------------------------------------------------------------------------
# Chandra's Incinerator (MEC-45)
# ---------------------------------------------------------------------------


def test_noncombat_damage_to_opponents_tracker_and_cost_reduction():
    engine, state, p1, p2 = _engine()
    burner = _bf(state, _bear("Burner", "{1}{R}", 2), controller="p1")
    incinerator = _to_hand(state, _named("Chandra's Incinerator"), controller="p1")
    engine.recompute_continuous_effects()

    engine.rules.deal_damage(p2, 3, source=burner, combat=False)

    assert state.noncombat_damage_to_opponents_this_turn.get("p1") == 3
    net, _contributors = continuous.self_cost_reduction_for(incinerator, state, caster_id="p1")
    assert net == 3


def test_chandras_incinerator_copies_noncombat_damage_at_a_named_target():
    engine, state, p1, p2 = _engine()
    chandra = _catalogue_obj(state, "Chandra's Incinerator", controller="p1")
    burner = _bf(state, _bear("Burner", "{1}{R}", 2), controller="p1")
    theirs = _bf(state, _bear("Theirs", "{1}{G}", 2), controller="p2")
    _bf(state, _bear("Mine", "{1}{G}", 2), controller="p1")  # not controlled by the hit player
    engine.recompute_continuous_effects()

    engine.rules.deal_damage(p2, 5, source=burner, combat=False)
    engine.rules.put_triggers_on_stack()

    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    option_ids = {o.get("instance_id") for o in choice["options"]}
    assert option_ids == {theirs.instance_id}  # only p2's own creature is legal
    option = next(o for o in choice["options"] if o["instance_id"] == theirs.instance_id)
    engine.rules.resolve_trigger_target_choice(option["id"])
    engine.rules.resolve_top_of_stack()
    engine.rules.check_state_based_actions()

    assert theirs.zone == Zone.GRAVEYARD  # 5 damage marked on a 2-toughness creature


def test_chandras_incinerator_does_not_trigger_off_combat_damage():
    engine, state, p1, p2 = _engine()
    _catalogue_obj(state, "Chandra's Incinerator", controller="p1")
    burner = _bf(state, _bear("Burner", "{1}{R}", 2), controller="p1")
    engine.recompute_continuous_effects()

    engine.rules.deal_damage(p2, 3, source=burner, combat=True)

    assert state.noncombat_damage_to_opponents_this_turn.get("p1", 0) == 0
    assert state.pending_choice is None
