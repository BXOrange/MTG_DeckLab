"""cEDH cube batch 25, wave 1 — the *state-tracking* primitives.

Six cards whose only real blocker was that the engine kept no record of
something that had already happened. Each new piece of state gets an
engine-level test plus an end-to-end, catalogue-driven one:

* `GameObject.mana_spent_to_cast` + the `SPELL_CAST` event's ``mana_spent``
  key (RULE 202.1/601.2h) — Lavinia, Azorius Renegade / Boromir, Warden of
  the Tower.
* `continuous.cast_prohibited`'s new ``cast_prohibition`` static (RULE
  601.3a) — Lavinia's other half.
* `GameState.combat_damage_to_players_this_turn` + the
  ``player_dealt_combat_damage_by_source`` target kind + the player-scoped
  `PlayerCastRestrictionEffect` — Hope of Ghirapur.
* `continuous.count_selector`'s ``devotion_to_<colour>`` (RULE 202.2f) and
  `LookTopKeepOneOnTopEffect`'s RULE 104.2a win — Thassa's Oracle.
* `GameObject.sacrificed_cost_mana_value` + `SearchLibraryEffect.
  mana_value_from`/``extra_counters`` — Eldritch Evolution / Neoform.
* ``cards_named_source_in_all_graveyards`` + `AddManaEffect.amount_selector`
  — Rite of Flame.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import GameContext, LookTopKeepOneOnTopEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return RulesEngine(state), state, p1, p2


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, **kw,
    )


def _bear(name="Bear", cost="{1}{G}", cmc=2):
    return _card(name, "Creature — Bear", cost, cmc, is_creature=True, power=2, toughness=2)


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _named(name):
    """The real cached card, bound from the hand-authored catalogue."""
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


# ---------------------------------------------------------------------------
# mana_spent_to_cast (RULE 202.1/601.2h) — Lavinia / Boromir
# ---------------------------------------------------------------------------


def test_paid_cast_records_the_mana_actually_spent():
    rules, state, p1, _ = _rules()
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(bolt, Zone.HAND)
    p1.mana_pool.add("R", 1)

    rules.cast_spell(p1, bolt)

    assert bolt.mana_spent_to_cast == 1
    cast_events = [e for e in state.event_log if e.type == "SPELL_CAST"]
    assert cast_events[-1].get("mana_spent") == 1
    assert cast_events[-1].get("from_hand") is True


def test_free_cast_records_no_mana_spent():
    rules, state, p1, _ = _rules()
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(bolt, Zone.HAND)

    rules.cast_without_paying(p1, bolt)

    assert bolt.mana_spent_to_cast == 0
    assert [e for e in state.event_log if e.type == "SPELL_CAST"][-1].get("mana_spent") == 0


def test_a_zero_cost_paid_cast_also_counts_as_no_mana_spent():
    """RULE 202.1: "no mana was spent" is about the *payment*, not about the
    `free` flag — an Ornithopter-shaped {0} cast is a paid cast that spent
    nothing, and Lavinia catches it. This is the distinction the whole
    separate ``mana_spent`` key exists for."""
    rules, _, p1, _ = _rules()
    thopter = GameObject(_card("Ornithopter", "Artifact Creature", "{0}", 0, is_creature=True),
                         owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(thopter, Zone.HAND)

    rules.cast_spell(p1, thopter)

    assert thopter.mana_spent_to_cast == 0


def test_lavinia_counters_an_opponents_free_spell():
    engine, state, p1, p2 = _engine()
    lavinia = GameObject(_named("Lavinia, Azorius Renegade"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lavinia)
    _bf(state, None, obj=lavinia)

    free_spell = GameObject(_card("Gitaxian Probe", "Sorcery", "{0}", 0), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(free_spell, Zone.HAND)
    engine.rules.cast_spell(p2, free_spell)

    engine.rules.put_triggers_on_stack()
    # Lavinia's own trigger sits above the spell it counters (RULE 603.3b).
    engine.rules.resolve_top_of_stack()

    assert free_spell not in [i.obj for i in state.stack]
    assert free_spell in p2.graveyard


def test_lavinia_leaves_her_controllers_own_free_spell_alone():
    """RULE 603.1's "an *opponent* casts" scoping — the trigger is
    controller-filtered, not a blanket tax on everyone."""
    engine, state, p1, _ = _engine()
    lavinia = GameObject(_named("Lavinia, Azorius Renegade"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lavinia)
    _bf(state, None, obj=lavinia)

    mine = GameObject(_card("Gitaxian Probe", "Sorcery", "{0}", 0), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(mine, Zone.HAND)
    engine.rules.cast_spell(p1, mine)

    assert engine.rules.put_triggers_on_stack() == 0


def test_boromir_shares_lavinias_no_mana_spent_trigger():
    engine, state, p1, p2 = _engine()
    boromir = GameObject(_named("Boromir, Warden of the Tower"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(boromir)
    _bf(state, None, obj=boromir)

    free_spell = GameObject(_card("Manamorphose", "Instant", "{0}", 0), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(free_spell, Zone.HAND)
    engine.rules.cast_spell(p2, free_spell)

    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    assert free_spell in p2.graveyard


# ---------------------------------------------------------------------------
# cast_prohibition (RULE 601.3a) — Lavinia's static half
# ---------------------------------------------------------------------------


def test_lavinias_static_blocks_an_opponents_oversized_noncreature_spell():
    engine, state, p1, p2 = _engine()
    lavinia = GameObject(_named("Lavinia, Azorius Renegade"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lavinia)
    _bf(state, None, obj=lavinia)
    _bf(state, _card("Island", "Basic Land — Island", is_land=True), controller="p2")

    big = GameObject(_card("Cyclonic Rift", "Instant", "{1}{U}", 2), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(big, Zone.HAND)
    p2.mana_pool.add("U", 5)
    state.active_player_index = 1
    engine.state.current_step = "main1"

    # One land, mana value 2 > 1 → prohibited.
    assert engine.can_cast(p2, big) is False

    _bf(state, _card("Island2", "Basic Land — Island", is_land=True), controller="p2")
    assert engine.can_cast(p2, big) is True  # two lands now, 2 <= 2


def test_lavinias_static_never_touches_creature_spells_or_her_own_controller():
    engine, state, p1, p2 = _engine()
    lavinia = GameObject(_named("Lavinia, Azorius Renegade"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lavinia)
    _bf(state, None, obj=lavinia)
    engine.state.current_step = "main1"

    creature = GameObject(_bear("Grizzly", "{1}{G}", 2), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(creature, Zone.HAND)
    p2.mana_pool.add("G", 5)
    state.active_player_index = 1
    assert engine.can_cast(p2, creature) is True  # noncreature-only

    mine = GameObject(_card("Cyclonic Rift", "Instant", "{1}{U}", 2), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(mine, Zone.HAND)
    p1.mana_pool.add("U", 5)
    state.active_player_index = 0
    assert engine.can_cast(p1, mine) is True  # "each *opponent*", not you


# ---------------------------------------------------------------------------
# Combat-damage history + player-scoped cast restriction — Hope of Ghirapur
# ---------------------------------------------------------------------------


def test_combat_damage_history_records_the_source_and_the_player_hit():
    rules, state, p1, p2 = _rules()
    hitter = _bf(state, _bear("Hitter"))

    rules.deal_damage(p2, 1, source=hitter, combat=True)

    assert state.combat_damage_to_players_this_turn[hitter.instance_id] == {"p2"}


def test_noncombat_damage_is_not_recorded_as_combat_history():
    rules, state, _, p2 = _rules()
    zapper = _bf(state, _bear("Zapper"))

    rules.deal_damage(p2, 1, source=zapper, combat=False)

    assert state.combat_damage_to_players_this_turn == {}


def test_hope_of_ghirapur_has_no_legal_target_before_it_connects():
    _, state, _, _ = _rules()
    hope = GameObject(_named("Hope of Ghirapur"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(hope)
    _bf(state, None, obj=hope)

    spec = TargetSpec(kind="player_dealt_combat_damage_by_source")
    assert legal_targets(state, "p1", spec, source=hope) == []


def test_hope_of_ghirapur_locks_a_player_it_connected_with_out_of_noncreature_spells():
    engine, state, p1, p2 = _engine()
    hope = GameObject(_named("Hope of Ghirapur"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(hope)
    _bf(state, None, obj=hope)
    engine.rules.deal_damage(p2, 1, source=hope, combat=True)

    spec = TargetSpec(kind="player_dealt_combat_damage_by_source")
    assert [t["player_id"] for t in legal_targets(state, "p1", spec, source=hope)] == ["p2"]

    engine.activate_ability(p1, hope, 0, targets=[p2])
    engine.resolve_until_stable()

    engine.state.current_step = "main1"
    state.active_player_index = 1
    instant = GameObject(_card("Counterspell", "Instant", "{U}{U}", 2), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(instant, Zone.HAND)
    p2.mana_pool.add("U", 5)
    assert engine.can_cast(p2, instant) is False

    creature = GameObject(_bear("Bear", "{1}{G}", 2), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(creature, Zone.HAND)
    p2.mana_pool.add("G", 5)
    assert engine.can_cast(p2, creature) is True  # noncreature-only lock


def test_the_lock_lapses_when_its_controllers_next_turn_begins():
    """RULE 611.2b's "until your next turn" — keyed to Hope's *controller*,
    not to the restricted player."""
    engine, state, p1, p2 = _engine()
    hope = GameObject(_named("Hope of Ghirapur"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(hope)
    _bf(state, None, obj=hope)
    engine.rules.deal_damage(p2, 1, source=hope, combat=True)
    engine.activate_ability(p1, hope, 0, targets=[p2])
    engine.resolve_until_stable()
    assert p2.player_effects

    state.turn_number = 1          # p1 (Hope's controller) is the active player
    engine.begin_turn()            # → p2's turn; p1's next turn hasn't come yet
    assert p2.player_effects
    engine.begin_turn()            # → p1's turn: the duration is up
    assert p2.player_effects == []


# ---------------------------------------------------------------------------
# Devotion + the RULE 104.2a win — Thassa's Oracle
# ---------------------------------------------------------------------------


def test_devotion_counts_coloured_pips_on_permanents_you_control():
    _, state, _, _ = _rules()
    _bf(state, _card("Thassa's Oracle", "Creature — Merfolk", "{U}{U}", 2, is_creature=True))
    _bf(state, _card("Island", "Basic Land — Island", is_land=True))
    _bf(state, _card("Opposing", "Creature — Bear", "{U}", 1, is_creature=True), controller="p2")

    assert continuous.count_selector(state, "p1", "devotion_to_blue") == 2
    assert continuous.count_selector(state, "p1", "devotion_to_red") == 0
    assert continuous.count_selector(state, "p2", "devotion_to_blue") == 1


def test_devotion_counts_a_hybrid_pip_toward_both_of_its_colours():
    """RULE 202.2f — `Card.mana_cost` already tallies a {G/W} pip under both
    G and W, which is exactly devotion's rule."""
    _, state, _, _ = _rules()
    _bf(state, _card("Kitchen Finks", "Creature — Ouphe", "{1}{G/W}{G/W}", 3, is_creature=True))

    assert continuous.count_selector(state, "p1", "devotion_to_green") == 2
    assert continuous.count_selector(state, "p1", "devotion_to_white") == 2


def test_thassas_oracle_wins_when_devotion_meets_the_library_size():
    engine, state, p1, p2 = _engine()
    for i in range(2):
        p1.add_to_zone(GameObject(_card(f"Lib{i}", "Instant", "{U}", 1), owner_id="p1",
                                  zone=Zone.LIBRARY), Zone.LIBRARY)
    oracle_card = _named("Thassa's Oracle")
    oracle = GameObject(oracle_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(oracle)
    _bf(state, None, obj=oracle)  # its own {U}{U} is devotion 2

    LookTopKeepOneOnTopEffect(
        count_selector="devotion_to_blue", win_if_count_at_least_library=True, source=oracle,
    ).apply(GameContext(state, engine.rules))

    assert state.game_over is True
    assert state.winner_id == "p1"


def test_thassas_oracle_only_digs_when_the_library_is_bigger_than_devotion():
    engine, state, p1, _ = _engine()
    for i in range(5):
        p1.add_to_zone(GameObject(_card(f"Lib{i}", "Instant", "{U}", 1), owner_id="p1",
                                  zone=Zone.LIBRARY), Zone.LIBRARY)
    oracle = GameObject(_named("Thassa's Oracle"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(oracle)
    _bf(state, None, obj=oracle)
    top_before = p1.library[-1]

    LookTopKeepOneOnTopEffect(
        count_selector="devotion_to_blue", win_if_count_at_least_library=True, source=oracle,
    ).apply(GameContext(state, engine.rules))

    assert state.game_over is False
    assert len(p1.library) == 5           # nothing left the library
    # "Put **up to one** of them on top" is the player's choice now.
    choice = state.pending_choice
    assert choice["kind"] == "choose_objects"
    engine.rules.resolve_choose_objects_choice(top_before.instance_id)
    assert p1.library[-1] is top_before


# ---------------------------------------------------------------------------
# Sacrificed-cost mana value — Eldritch Evolution / Neoform
# ---------------------------------------------------------------------------


def test_additional_sacrifice_cost_records_the_victims_mana_value():
    engine, state, p1, _ = _engine()
    victim = _bf(state, _bear("Victim", "{2}{G}", 3))
    spell = GameObject(_named("Eldritch Evolution"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 5)
    engine.state.current_step = "main1"

    engine.cast_spell(p1, spell)

    assert victim in p1.graveyard
    assert spell.sacrificed_cost_mana_value == 3


def test_eldritch_evolution_searches_for_two_plus_the_sacrificed_mana_value():
    engine, state, p1, _ = _engine()
    _bf(state, _bear("Victim", "{2}{G}", 3))
    for name, cmc in (("Cheap", 4), ("Exact", 5), ("TooBig", 6)):
        obj = GameObject(_bear(name, f"{{{cmc}}}", cmc), owner_id="p1", zone=Zone.LIBRARY)
        p1.add_to_zone(obj, Zone.LIBRARY)
    spell = GameObject(_named("Eldritch Evolution"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 5)
    engine.state.current_step = "main1"

    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    offered = {o["label"] for o in choice["options"] if o["id"] != "decline"}
    assert offered == {"Cheap", "Exact"}   # 2 + 3 = 5 or less


def test_neoform_searches_for_an_exact_mana_value_and_adds_a_counter():
    engine, state, p1, _ = _engine()
    _bf(state, _bear("Victim", "{2}{G}", 3))
    for name, cmc in (("Three", 3), ("Four", 4), ("Five", 5)):
        p1.add_to_zone(
            GameObject(_bear(name, f"{{{cmc}}}", cmc), owner_id="p1", zone=Zone.LIBRARY),
            Zone.LIBRARY,
        )
    spell = GameObject(_named("Neoform"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("U", 1)
    engine.state.current_step = "main1"

    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    choice = state.pending_choice
    offered = {o["label"] for o in choice["options"] if o["id"] != "decline"}
    assert offered == {"Four"}  # exactly 1 + 3

    pick = next(o for o in choice["options"] if o["label"] == "Four")
    engine.resolve_pending_choice(pick["id"])

    found = next(o for o in state.battlefield if o.name == "Four")
    assert found.counters.get("+1/+1") == 1


# ---------------------------------------------------------------------------
# Rite of Flame — a name-keyed, cross-graveyard count driving a mana amount
# ---------------------------------------------------------------------------


def test_rite_of_flame_adds_two_red_plus_one_per_copy_in_any_graveyard():
    engine, state, p1, p2 = _engine()
    rite_card = _named("Rite of Flame")
    for owner, player in (("p1", p1), ("p2", p2)):
        copy = GameObject(rite_card, owner_id=owner, zone=Zone.GRAVEYARD)
        player.add_to_zone(copy, Zone.GRAVEYARD)

    spell = GameObject(rite_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("R", 1)
    engine.state.current_step = "main1"

    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    # {R}{R} printed + one {R} for each of the two copies already in a
    # graveyard; the resolving copy is on the stack, so it never counts
    # itself. The {R} paid to cast it is gone.
    assert p1.mana_pool.total() == 4


def test_named_card_count_selector_is_keyed_to_the_effects_own_source():
    _, state, p1, p2 = _rules()
    rite = _named("Rite of Flame")
    source = GameObject(rite, owner_id="p1", zone=Zone.STACK)
    p1.add_to_zone(GameObject(rite, owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    p2.add_to_zone(
        GameObject(_card("Other", "Sorcery", "{R}", 1), owner_id="p2", zone=Zone.GRAVEYARD),
        Zone.GRAVEYARD,
    )

    count = continuous.count_selector(
        state, "p1", "cards_named_source_in_all_graveyards", source=source
    )
    assert count == 1  # the unrelated card in p2's graveyard doesn't match


# ---------------------------------------------------------------------------
# Eiganjo — a per-count activation-cost reduction
# ---------------------------------------------------------------------------


def test_eiganjo_channel_costs_one_less_per_legendary_creature():
    engine, state, p1, _ = _engine()
    eiganjo = GameObject(_named("Eiganjo, Seat of the Empire"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(eiganjo)
    p1.add_to_zone(eiganjo, Zone.HAND)

    cost = eiganjo.activated_abilities[0].cost
    assert engine._reduced_activation_mana(eiganjo, cost.mana, cost).converted_mana_cost == 3

    _bf(state, _card("Legend", "Legendary Creature — Human", "{W}", 1, is_creature=True))
    assert engine._reduced_activation_mana(eiganjo, cost.mana, cost).converted_mana_cost == 2

    _bf(state, _card("Legend2", "Legendary Creature — Human", "{W}", 1, is_creature=True))
    _bf(state, _bear("Plain"))  # nonlegendary — doesn't count
    assert engine._reduced_activation_mana(eiganjo, cost.mana, cost).converted_mana_cost == 1


def test_legendary_creature_count_selector_ignores_opponents_and_noncreatures():
    _, state, _, _ = _rules()
    _bf(state, _card("Legend", "Legendary Creature — Human", "{W}", 1, is_creature=True))
    _bf(state, _card("LegendArt", "Legendary Artifact", "{2}", 2))
    _bf(state, _card("TheirLegend", "Legendary Creature — Human", "{W}", 1, is_creature=True),
        controller="p2")

    assert continuous.count_selector(state, "p1", "legendary_creatures_you_control") == 1
