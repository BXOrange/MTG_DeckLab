"""Tests for four cards hand-authored specifically to exercise RULE 603.7
delayed triggered abilities end to end — the frontend "planned" delayed-
trigger panel (`gameBoardView.js`, `GameSession.view()`'s `delayed_triggers`)
needed real examples to render against:

- Ephemerate's Rebound (RULE 702.88b) — exile-on-resolve + a free-cast
  window armed at the controller's next upkeep (`AbilitySpec.rebound`,
  `ReboundFreeCastWindowEffect`, `GameState.free_cast_instance_ids`).
- Marchesa, the Black Rose's "return a counter-bearing creature you control
  that died, at the beginning of the next end step" (`AbilitySpec.
  counter_death_return`, `RulesEngine._collect_counter_death_return_
  triggers`, `MarchesaDelayedReturnEffect`).
- Sneak Attack / Meek Attack's "put a creature from hand onto the
  battlefield with haste, sacrifice it at the beginning of the next end
  step" (`CheatCreatureFromHandEffect`, `SacrificeObjectEffect`).

Also covers `DelayedTrigger.to_dict()` and its wiring into
`GameSession.view()`'s new ``delayed_triggers`` key.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0,
    )


def _battlefield_obj(state, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _advance_until_step(eng, step_name, limit=20):
    for _ in range(limit):
        ran = eng.advance_step()
        if ran and ran[1] == step_name:
            return ran
    raise AssertionError(f"never reached step {step_name!r}")


# ---------------------------------------------------------------------------
# Ephemerate — Rebound
# ---------------------------------------------------------------------------


def _cast_ephemerate(eng, caster, target):
    card = _card("Ephemerate", "Instant", mana_cost_string="{W}",
                 converted_mana_cost=1, is_instant=True)
    obj = GameObject(card, owner_id=caster.id, zone=Zone.HAND)
    from mtg_analyzer.game import ability_catalogue as ac

    attach_to_object(obj, ac.specs_for(card))
    caster.add_to_zone(obj, Zone.HAND)
    caster.mana_pool.add("W", 1)
    eng.state.active_player_index = eng.state.players.index(caster)
    eng.state.current_step = "main1"
    eng.cast_spell(caster, obj, targets=[target])
    eng.resolve_until_stable()
    return obj


def test_ephemerate_registered_with_rebound_marker():
    from mtg_analyzer.game import ability_catalogue as ac

    assert ac.is_registered("Ephemerate")
    card = _card("Ephemerate", "Instant")
    specs = ac.specs_for(card)
    assert any(getattr(s, "rebound", False) for s in specs)


def test_ephemerate_blink_does_not_leave_a_phantom_duplicate_in_exile():
    """Found while end-to-end testing Ephemerate through the real HTTP API:
    `RulesEngine.blink` exiled the target, then routed it straight to the
    battlefield via `_put_searched_card` without ever removing it from
    `owner.exile` first — `_put_searched_card`'s battlefield branch only
    appends to `state.battlefield` (its usual callers, e.g. a tutor, already
    popped the card off whatever zone held it beforehand). The target ended
    up on the battlefield *and* stuck in the exile zone list forever — a
    genuine pre-existing bug, unrelated to Rebound itself, just never
    exercised by any prior test (none checked the exile zone after a blink)."""
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    _cast_ephemerate(eng, p1, target)

    assert target.zone == Zone.BATTLEFIELD
    assert target in eng.state.battlefield
    assert target not in p1.exile


def test_ephemerate_exiles_itself_instead_of_graveyard_when_cast_from_hand():
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    ephemerate = _cast_ephemerate(eng, p1, target)

    assert ephemerate.zone == Zone.EXILE
    assert ephemerate in p1.exile
    assert not any(o.name == "Ephemerate" for o in p1.graveyard)
    # The blink half still ran: a new object (RULE 400.7 — same instance_id,
    # summoning sickness reset).
    assert target.zone == Zone.BATTLEFIELD
    assert target.summoning_sick is True


def test_ephemerate_arms_a_delayed_trigger_for_the_controllers_next_upkeep():
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    ephemerate = _cast_ephemerate(eng, p1, target)

    assert len(eng.state.delayed_triggers) == 1
    dt = eng.state.delayed_triggers[0]
    assert dt.step == "upkeep"
    assert dt.scope == "controller"
    assert dt.controller_id == "p1"
    assert dt.description  # a human-readable label for the UI panel

    d = dt.to_dict()
    assert d["step"] == "upkeep"
    assert d["source"]["name"] == "Ephemerate"

    # Not castable yet — the window only opens once the delayed trigger fires.
    assert eng.can_cast(p1, ephemerate) is False
    assert ephemerate.instance_id not in eng.state.free_cast_instance_ids


def test_ephemerate_free_cast_window_is_actually_offered_by_legal_actions():
    """Found the same way as the blink duplicate-exile bug: `can_cast`
    returning True for a temp-play-permission-exiled card was never enough
    on its own — `GameEngine.legal_actions`'s own exile loop only checked
    `_castable_from_exile` (Adventure/prepared-copy shapes), so Light Up the
    Stage/Ragavan/Mnemonic Betrayal/Rebound's exiled cards could never
    actually appear as a real offered action, even though `can_cast`/
    `cast_spell` fully supported casting them. No prior test caught this
    because every impulsive-draw test asserted `can_cast` directly instead
    of going through `legal_actions` — the same gap a real UI/API caller
    would have hit."""
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    ephemerate = _cast_ephemerate(eng, p1, target)
    _advance_until_step(eng, "upkeep")

    offered = eng.legal_actions(p1)
    assert any(
        a["type"] == "cast_spell" and a["instance_id"] == ephemerate.instance_id
        for a in offered
    )


def test_ephemerate_free_cast_window_opens_at_next_upkeep_and_does_not_rebound_again():
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    ephemerate = _cast_ephemerate(eng, p1, target)

    _advance_until_step(eng, "upkeep")
    assert not eng.state.delayed_triggers
    assert ephemerate.instance_id in eng.state.free_cast_instance_ids
    assert ephemerate.instance_id in eng.state.temp_play_permissions

    # No mana in the pool at all — the free-cast window should still allow it.
    assert eng.can_cast(p1, ephemerate) is True
    eng.cast_spell(p1, ephemerate, targets=[target])
    assert ephemerate.instance_id not in eng.state.free_cast_instance_ids
    eng.resolve_until_stable()

    # Recast via Rebound doesn't rebound a second time — ordinary graveyard.
    assert ephemerate.zone == Zone.GRAVEYARD
    assert ephemerate in p1.graveyard
    assert not eng.state.delayed_triggers


def test_ephemerate_cast_directly_from_exile_by_some_other_means_does_not_rebound():
    """Guards `rebound_pending` only being armed when cast *from hand* —
    without that check, casting an already-exiled has_rebound card through
    any other permission would incorrectly re-exile it forever."""
    eng = _engine("p1")
    p1 = eng.state.player_by_id("p1")
    card = _card("Ephemerate", "Instant", mana_cost_string="{W}",
                 converted_mana_cost=1, is_instant=True)
    obj = GameObject(card, owner_id=p1.id, zone=Zone.EXILE)
    from mtg_analyzer.game import ability_catalogue as ac

    attach_to_object(obj, ac.specs_for(card))
    p1.exile.append(obj)
    eng.rules._grant_temp_play_permission(obj, p1, "Test", same_turn_only=False, mana_wildcard=None)
    target = _battlefield_obj(eng.state, _card("Fog Bank", "Creature", is_creature=True,
                                                power=0, toughness=3), controller="p1")
    p1.mana_pool.add("W", 1)
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    eng.cast_spell(p1, obj, targets=[target])
    eng.resolve_until_stable()

    assert obj.zone == Zone.GRAVEYARD
    assert not eng.state.delayed_triggers


# ---------------------------------------------------------------------------
# Marchesa, the Black Rose
# ---------------------------------------------------------------------------


def _marchesa(state, controller="p1"):
    card = _card("Marchesa, the Black Rose", "Legendary Creature — Human Wizard",
                 is_creature=True, power=3, toughness=3)
    return _battlefield_obj(state, card, controller)


def test_marchesa_registered_with_counter_death_return_marker():
    from mtg_analyzer.game import ability_catalogue as ac

    assert ac.is_registered("Marchesa, the Black Rose")
    card = _card("Marchesa, the Black Rose", "Legendary Creature")
    specs = ac.specs_for(card)
    assert any(getattr(s, "counter_death_return", None) for s in specs)


def test_marchesa_returns_a_dying_countered_creature_at_next_end_step():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    marchesa = _marchesa(eng.state, controller="p1")
    victim = _battlefield_obj(eng.state, _card("Loyal Pawn", "Creature", is_creature=True,
                                                power=1, toughness=1), controller="p1")
    eng.rules.add_counters(victim, 1, "+1/+1")

    eng.rules.put_into_graveyard(victim)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert victim in p1.graveyard
    assert len(eng.state.delayed_triggers) == 1
    dt = eng.state.delayed_triggers[0]
    assert dt.step == "end"
    assert dt.scope == "any"

    _advance_until_step(eng, "end")
    assert not eng.state.delayed_triggers
    assert victim.zone == Zone.BATTLEFIELD
    assert victim.controller_id == "p1"
    assert victim in eng.state.battlefield
    assert marchesa in eng.state.battlefield  # unaffected


def test_marchesa_return_applies_triskelions_entry_counters():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _marchesa(eng.state, controller="p1")
    triskelion = _battlefield_obj(
        eng.state,
        _card(
            "Triskelion",
            "Artifact Creature — Construct",
            oracle_text=(
                "Triskelion enters the battlefield with three +1/+1 counters on it.\n"
                "Remove a +1/+1 counter from Triskelion: It deals 1 damage to any target."
            ),
            is_creature=True,
            power=1,
            toughness=1,
        ),
        controller="p1",
    )
    eng.rules.add_counters(triskelion, 1, "+1/+1")

    eng.rules.put_into_graveyard(triskelion)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.resolve_until_stable()
    _advance_until_step(eng, "end")

    assert triskelion.zone == Zone.BATTLEFIELD
    assert triskelion.counters.get("+1/+1") == 3
    assert triskelion in eng.state.battlefield


def test_marchesa_return_fires_puppeteer_clique_etb():
    eng = _engine("p1", "p2")
    p2 = eng.state.player_by_id("p2")
    _marchesa(eng.state, controller="p1")
    clique = _battlefield_obj(
        eng.state,
        _card(
            "Puppeteer Clique",
            "Creature — Faerie Rogue",
            oracle_text=(
                "When Puppeteer Clique enters, put target creature card from an "
                "opponent's graveyard onto the battlefield under your control. "
                "It gains haste. At the beginning of your next end step, exile it."
            ),
            is_creature=True,
            power=3,
            toughness=2,
        ),
        controller="p1",
    )
    eng.rules.add_counters(clique, 1, "+1/+1")
    target = GameObject(
        _card("Graveyard Creature", "Creature", is_creature=True, power=2, toughness=2),
        owner_id="p2",
        zone=Zone.GRAVEYARD,
    )
    p2.add_to_zone(target, Zone.GRAVEYARD)

    eng.rules.put_into_graveyard(clique)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.resolve_until_stable()
    _advance_until_step(eng, "end")
    eng.resolve_until_stable()

    assert clique.zone == Zone.BATTLEFIELD
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(target.instance_id)
    eng.resolve_until_stable()

    assert target.zone == Zone.BATTLEFIELD
    assert target in eng.state.battlefield


def test_marchesa_does_not_trigger_for_a_creature_with_no_counter():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _marchesa(eng.state, controller="p1")
    victim = _battlefield_obj(eng.state, _card("Plain Bear", "Creature", is_creature=True,
                                                power=2, toughness=2), controller="p1")

    eng.rules.put_into_graveyard(victim)
    assert eng.rules.put_triggers_on_stack() == 0
    assert not eng.state.delayed_triggers
    assert victim in p1.graveyard


def test_marchesa_does_not_trigger_for_an_opponents_countered_creature():
    eng = _engine("p1", "p2")
    p2 = eng.state.player_by_id("p2")
    _marchesa(eng.state, controller="p1")
    victim = _battlefield_obj(eng.state, _card("Enemy Dude", "Creature", is_creature=True,
                                                power=1, toughness=1), controller="p2")
    eng.rules.add_counters(victim, 1, "+1/+1")

    eng.rules.put_into_graveyard(victim)
    assert eng.rules.put_triggers_on_stack() == 0
    assert victim in p2.graveyard


# ---------------------------------------------------------------------------
# Sneak Attack / Meek Attack
# ---------------------------------------------------------------------------


def _activate(eng, controller, permanent_name, mana):
    source = next(o for o in eng.state.battlefield if o.name == permanent_name)
    for color, amount in mana.items():
        controller.mana_pool.add(color, amount)
    eng.state.active_player_index = eng.state.players.index(controller)
    eng.state.current_step = "main1"
    eng.activate_ability(controller, source, 0)
    eng.resolve_until_stable()
    return source


def _choose_hand_creature(eng, creature):
    """Resolve a Sneak-Attack-shaped hand choice, then its stack work."""
    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    eng.resolve_pending_choice(str(creature.instance_id))
    eng.resolve_until_stable()


def test_sneak_attack_puts_a_hand_creature_into_play_with_haste_and_arms_sacrifice():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _battlefield_obj(eng.state, _card("Sneak Attack", "Enchantment",
                                       mana_cost_string="{3}{R}", converted_mana_cost=4),
                      controller="p1")
    creature = GameObject(
        _card("Big Beater", "Creature", is_creature=True, power=8, toughness=8),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.add_to_zone(creature, Zone.HAND)

    _activate(eng, p1, "Sneak Attack", {"R": 1})
    _choose_hand_creature(eng, creature)

    assert creature.zone == Zone.BATTLEFIELD
    assert creature in eng.state.battlefield
    assert "haste" in creature.temp_keywords
    assert len(eng.state.delayed_triggers) == 1
    dt = eng.state.delayed_triggers[0]
    assert dt.step == "end"
    assert dt.scope == "any"

    _advance_until_step(eng, "end")
    assert not eng.state.delayed_triggers
    assert creature.zone == Zone.GRAVEYARD
    assert creature in p1.graveyard


def test_sneak_attack_does_nothing_with_no_creature_in_hand():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _battlefield_obj(eng.state, _card("Sneak Attack", "Enchantment",
                                       mana_cost_string="{3}{R}", converted_mana_cost=4),
                      controller="p1")
    non_creature = GameObject(_card("Some Instant", "Instant", is_instant=True),
                               owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(non_creature, Zone.HAND)

    _activate(eng, p1, "Sneak Attack", {"R": 1})
    assert not eng.state.delayed_triggers
    assert non_creature.zone == Zone.HAND


def test_meek_attack_only_cheats_a_creature_within_the_total_pt_cap():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _battlefield_obj(eng.state, _card("Meek Attack", "Enchantment",
                                       mana_cost_string="{2}{R}", converted_mana_cost=3),
                      controller="p1")
    too_big = GameObject(
        _card("Huge Beater", "Creature", is_creature=True, power=6, toughness=6),
        owner_id="p1", zone=Zone.HAND,
    )
    small_enough = GameObject(
        _card("Little Guy", "Creature", is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.add_to_zone(too_big, Zone.HAND)
    p1.add_to_zone(small_enough, Zone.HAND)

    _activate(eng, p1, "Meek Attack", {"R": 1, "C": 1})
    choice = eng.state.pending_choice
    assert choice is not None
    assert [option["instance_id"] for option in choice["options"] if "instance_id" in option] == [
        small_enough.instance_id
    ]
    _choose_hand_creature(eng, small_enough)

    assert too_big.zone == Zone.HAND  # too big — skipped
    assert small_enough.zone == Zone.BATTLEFIELD
    assert "haste" in small_enough.temp_keywords
    assert len(eng.state.delayed_triggers) == 1


def test_incandescent_soulstoke_chooses_only_an_elemental_and_arms_sacrifice():
    """MEC-73: subtype filter and real hand choice, not first-card selection."""
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    soulstoke = _battlefield_obj(
        eng.state,
        _card(
            "Incandescent Soulstoke", "Creature — Elemental Shaman",
            mana_cost_string="{2}{R}", converted_mana_cost=3, is_creature=True,
            power=2, toughness=2,
            oracle_text=(
                "Other Elemental creatures you control get +1/+1.\n"
                "{1}{R}, {T}: You may put an Elemental creature card from your hand onto "
                "the battlefield. That creature gains haste until end of turn. Sacrifice it "
                "at the beginning of the next end step."
            ),
        ),
        controller="p1",
    )
    non_elemental = GameObject(
        _card("Off-Tribe Bear", "Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.HAND,
    )
    elemental = GameObject(
        _card("Flamekin", "Creature — Elemental", is_creature=True, power=3, toughness=1),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.add_to_zone(non_elemental, Zone.HAND)
    p1.add_to_zone(elemental, Zone.HAND)

    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 1)
    eng.state.active_player_index = eng.state.players.index(p1)
    eng.state.current_step = "main1"
    eng.activate_ability(p1, soulstoke, 0)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    assert [option["instance_id"] for option in choice["options"] if "instance_id" in option] == [
        elemental.instance_id
    ]
    _choose_hand_creature(eng, elemental)

    assert non_elemental.zone == Zone.HAND
    assert elemental.zone == Zone.BATTLEFIELD
    assert "haste" in elemental.temp_keywords
    assert len(eng.state.delayed_triggers) == 1

    _advance_until_step(eng, "end")
    assert elemental.zone == Zone.GRAVEYARD
