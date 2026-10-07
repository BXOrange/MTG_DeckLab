"""cEDH cube batch 25, wave 3 — control & zone effects.

Five shapes the engine could not express before:

* `ExchangeControlEffect` — a two-way, permanent control **swap** (RULE
  701.10), distinct from both the layer-2 `control_change` static and the
  one-way `GainControlUntilEndOfTurnEffect`. Gilded Drake.
* `PhaseOutAllYouControlEffect`/`PlayerShieldEffect` — mass phasing (RULE
  702.26b) plus a player-scoped life lock (RULE 119.6) and protection from
  everything (RULE 702.16e). Teferi's Protection.
* `RulesEngine.return_spell_to_hand` — pulling a `StackItem` off the stack
  into hand (RULE 400.1), not bouncing a permanent. Narset's Reversal.
* `ReturnSharedTypePermanentEffect` — a bounce whose legal set depends on
  the *entering* permanent. Cloudstone Curio.
* `PutFromHandOntoBattlefieldEffect` — putting cards onto the battlefield
  from **hand**. Tooth and Nail.

Plus Reiterate (Buyback + copy: both already built, never registered) and
Wandering Archaic (`pay_cost_then` with an event-named payer and an
"if they don't" branch).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="", cmc=0, **kw):
    # `Card`'s type booleans are explicit fields, not derived from the type
    # line, so fill them in from it here rather than at every call site.
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bear(name="Bear"):
    return _card(name, "Creature — Bear", "{1}{G}", 2, is_creature=True, power=2, toughness=2)


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _catalogue_obj(state, name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# Gilded Drake — a genuine control exchange (RULE 701.10)
# ---------------------------------------------------------------------------


def test_gilded_drake_swaps_control_both_ways():
    engine, state, p1, p2 = _engine()
    drake = _catalogue_obj(state, "Gilded Drake")
    state.add_to_battlefield(drake)
    theirs = _bf(state, _bear("Grizzly"), controller="p2")

    state.fire_event(_etb(drake))
    engine.rules.put_triggers_on_stack()
    choice = state.pending_choice
    option = next(o for o in choice["options"] if o.get("instance_id") == theirs.instance_id)
    engine.rules.resolve_choice(option["id"])
    engine.rules.resolve_top_of_stack()

    assert drake.controller_id == "p2"
    assert theirs.controller_id == "p1"


def test_the_exchange_survives_the_drake_leaving():
    """RULE 701.10c: an exchange is a one-shot change of control, not a
    continuous effect — the drake dying must not hand the creature back.
    That is the entire reason the card is played."""
    engine, state, p1, p2 = _engine()
    drake = _catalogue_obj(state, "Gilded Drake")
    state.add_to_battlefield(drake)
    theirs = _bf(state, _bear("Grizzly"), controller="p2")

    state.fire_event(_etb(drake))
    engine.rules.put_triggers_on_stack()
    option = next(
        o for o in state.pending_choice["options"] if o.get("instance_id") == theirs.instance_id
    )
    engine.rules.resolve_choice(option["id"])
    engine.rules.resolve_top_of_stack()

    engine.rules.destroy(drake)

    assert theirs.controller_id == "p1"  # still yours


def test_gilded_drake_sacrifices_itself_with_no_creature_to_exchange():
    """RULE 701.10d: an exchange with only one exchangeable permanent doesn't
    happen — and the drake's own failure clause then fires."""
    engine, state, p1, p2 = _engine()
    drake = _catalogue_obj(state, "Gilded Drake")
    state.add_to_battlefield(drake)

    state.fire_event(_etb(drake))
    engine.resolve_until_stable()

    assert drake not in state.battlefield
    assert drake in p1.graveyard


# ---------------------------------------------------------------------------
# Teferi's Protection — mass phasing + a player-scoped shield
# ---------------------------------------------------------------------------


def _cast_teferis(engine, state, p1):
    spell = _catalogue_obj(state, "Teferi's Protection", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("W", 3)
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    return spell


def test_teferis_protection_phases_out_everything_you_control():
    engine, state, p1, p2 = _engine()
    mine = _bf(state, _bear("Mine"))
    theirs = _bf(state, _bear("Theirs"), controller="p2")

    _cast_teferis(engine, state, p1)

    assert mine.phased_out is True
    assert theirs.phased_out is False
    # RULE 702.26b: a phased-out permanent is treated as not existing.
    assert mine not in state.permanents()


def test_teferis_protection_keeps_an_aura_attached_through_the_phase():
    """RULE 702.26e — host and attachment phase out together, unlike the
    single-permanent `PhaseOutEffect`, which unattaches. Board preservation
    is the whole point of the card."""
    engine, state, p1, _ = _engine()
    host = _bf(state, _bear("Host"))
    aura = _bf(state, _card("Rancor", "Enchantment — Aura", oracle_text="Enchant creature"))
    aura.attached_to = host.instance_id

    _cast_teferis(engine, state, p1)

    assert host.phased_out is True
    assert aura.phased_out is True
    assert aura.attached_to == host.instance_id


def test_teferis_protection_locks_the_life_total_both_directions():
    engine, state, p1, _ = _engine()
    _cast_teferis(engine, state, p1)
    before = p1.life

    engine.rules.lose_life(p1, 5)
    engine.rules.gain_life(p1, 5)

    assert p1.life == before  # RULE 119.6: it can't change at all


def test_teferis_protection_makes_the_player_undamageable():
    engine, state, p1, p2 = _engine()
    attacker = _bf(state, _bear("Attacker"), controller="p2")
    _cast_teferis(engine, state, p1)
    before = p1.life

    engine.rules.deal_damage(p1, 7, source=attacker, combat=True)

    assert p1.life == before  # RULE 702.16e


def test_teferis_protections_shield_lapses_at_your_next_turn():
    engine, state, p1, _ = _engine()
    _cast_teferis(engine, state, p1)
    state.internal_turn.number = 1  # p1 is active, so their *next* turn is two away

    engine.begin_turn()
    assert p1.player_effects
    engine.begin_turn()
    assert p1.player_effects == []

    engine.rules.lose_life(p1, 3)
    assert p1.life == 17  # the lock is gone


def test_teferis_protection_exiles_itself():
    engine, state, p1, _ = _engine()
    spell = _cast_teferis(engine, state, p1)

    assert spell not in p1.graveyard
    assert spell.zone == Zone.EXILE


# ---------------------------------------------------------------------------
# Narset's Reversal — copy, then pull the original off the stack
# ---------------------------------------------------------------------------


def test_narsets_reversal_copies_the_spell_and_returns_it_to_hand():
    engine, state, p1, p2 = _engine()
    victim = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, victim)

    reversal = _catalogue_obj(state, "Narset's Reversal", zone=Zone.HAND)
    p1.add_to_zone(reversal, Zone.HAND)
    p1.mana_pool.add("U", 2)
    engine.rules.cast_spell(p1, reversal, targets=[victim])
    engine.rules.resolve_top_of_stack()

    # The original is back in its owner's hand, and a copy is on the stack
    # in its place — a "counter" that leaves the card in hand, which is why
    # it beats "can't be countered".
    assert victim in p2.hand
    assert victim not in [i.obj for i in state.stack]
    copies = [i for i in state.stack if i.obj is not None and getattr(i.obj, "is_copy", False)]
    assert len(copies) == 1


def test_returning_a_spell_copy_to_hand_just_makes_it_cease_to_exist():
    """RULE 707.10a/111.7: a copy on the stack isn't a card — there is no
    hand for it to go to."""
    engine, state, p1, p2 = _engine()
    victim = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, victim)
    copy_item = engine.rules.copy_spell(victim, "p2", 1)[0]

    assert engine.rules.return_spell_to_hand(copy_item) is True
    assert copy_item.obj not in p2.hand
    assert copy_item not in state.stack


# ---------------------------------------------------------------------------
# Reiterate — already-built pieces, previously just unregistered
# ---------------------------------------------------------------------------


def test_reiterate_copies_a_spell_and_buyback_returns_it_to_hand():
    engine, state, p1, p2 = _engine()
    victim = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, victim)

    reiterate = _catalogue_obj(state, "Reiterate", zone=Zone.HAND)
    p1.add_to_zone(reiterate, Zone.HAND)
    p1.mana_pool.add("R", 6)  # {1}{R}{R} + Buyback {3}

    engine.cast_spell(p1, reiterate, targets=[victim], buyback=True)
    engine.rules.resolve_top_of_stack()

    assert reiterate in p1.hand  # RULE 702.27a
    assert any(i.obj is not None and getattr(i.obj, "is_copy", False) for i in state.stack)


# ---------------------------------------------------------------------------
# Cloudstone Curio — a bounce keyed to the entering permanent's types
# ---------------------------------------------------------------------------


def test_cloudstone_curio_bounces_a_permanent_sharing_a_type():
    engine, state, p1, _ = _engine()
    curio = _catalogue_obj(state, "Cloudstone Curio")
    state.add_to_battlefield(curio)
    old_bear = _bf(state, _bear("Old"))
    new_bear = _bf(state, _bear("New"))

    state.fire_event(_etb(new_bear))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_choice("do")   # RULE 603.5's "you may"
    engine.rules.resolve_top_of_stack()

    # RULE 601.2c: *which* matching permanent to return is a real choice.
    assert state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(str(old_bear.instance_id))

    assert old_bear in p1.hand
    assert new_bear in state.battlefield  # never itself


def test_cloudstone_curio_ignores_an_artifact_entering():
    engine, state, p1, _ = _engine()
    curio = _catalogue_obj(state, "Cloudstone Curio")
    state.add_to_battlefield(curio)
    _bf(state, _card("Sol Ring", "Artifact"))
    entering = _bf(state, _card("Signet", "Artifact"))

    state.fire_event(_etb(entering))

    assert engine.rules.pending_triggers == []  # "nonartifact permanent"


def test_cloudstone_curio_only_looks_at_shared_permanent_types():
    engine, state, p1, _ = _engine()
    curio = _catalogue_obj(state, "Cloudstone Curio")
    state.add_to_battlefield(curio)
    enchantment = _bf(state, _card("Rancor", "Enchantment"))
    new_bear = _bf(state, _bear("New"))

    state.fire_event(_etb(new_bear))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_choice("do")
    engine.rules.resolve_top_of_stack()

    assert enchantment in state.battlefield  # shares no permanent type
    assert enchantment not in p1.hand


# ---------------------------------------------------------------------------
# Tooth and Nail — putting cards onto the battlefield from hand
# ---------------------------------------------------------------------------


def test_tooth_and_nail_puts_creatures_from_hand_onto_the_battlefield():
    engine, state, p1, _ = _engine()
    fatty = GameObject(_bear("Fatty"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(fatty, Zone.HAND)
    p1.add_to_zone(
        GameObject(_card("Ritual", "Instant", "{B}", 1), owner_id="p1", zone=Zone.HAND),
        Zone.HAND,
    )

    spell = _catalogue_obj(state, "Tooth and Nail", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 9)
    engine.cast_spell(p1, spell, mode=1)
    engine.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    offered = {o["label"] for o in choice["options"] if o["id"] != "decline"}
    assert offered == {"Fatty"}   # creature cards in hand only

    engine.resolve_pending_choice(str(fatty.instance_id))
    engine.resolve_until_stable()
    if state.pending_choice:              # "up to two" re-asks; decline the second
        engine.resolve_pending_choice("decline")

    assert fatty in state.battlefield
    assert fatty not in p1.hand


def test_a_hand_pick_never_shuffles_the_library():
    """`_request_search` keys both its shuffle (RULE 701.19e) and its
    `LIBRARY_SEARCHED` event to the ``"library"`` zone, so reusing its
    machinery for a hand pick correctly does neither."""
    engine, state, p1, _ = _engine()
    for i in range(3):
        p1.add_to_zone(
            GameObject(_card(f"Lib{i}", "Instant", "{U}", 1), owner_id="p1", zone=Zone.LIBRARY),
            Zone.LIBRARY,
        )
    order_before = [o.name for o in p1.library]
    fatty = GameObject(_bear("Fatty"), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(fatty, Zone.HAND)

    from mtg_analyzer.game.effects.core import GameContext, PutFromHandOntoBattlefieldEffect

    PutFromHandOntoBattlefieldEffect(criteria={"type": "Creature"}, count=1).apply(
        GameContext(state, engine.rules)
    )
    engine.resolve_pending_choice(str(fatty.instance_id))

    assert [o.name for o in p1.library] == order_before
    assert not [e for e in state.event_log if e.type == "LIBRARY_SEARCHED"]


# ---------------------------------------------------------------------------
# Wandering Archaic — an event-named payer + an "if they don't" branch
# ---------------------------------------------------------------------------


def test_wandering_archaic_taxes_the_opponent_who_cast_the_spell():
    engine, state, p1, p2 = _engine()
    archaic = _catalogue_obj(state, "Wandering Archaic")
    state.add_to_battlefield(archaic)

    spell = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(spell, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, spell)
    p2.mana_pool.add("R", 2)  # enough to pay the {2} tax

    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    choice = state.pending_choice
    assert choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == "p2"      # the *caster* pays, not the Archaic's controller

    # Resolved directly rather than through `resolve_pending_choice`, which
    # would also drain the stack before the copy could be observed.
    engine.rules.resolve_choice("pay")
    assert not [i for i in state.stack if i.obj is not None and getattr(i.obj, "is_copy", False)]
    assert p2.mana_pool.total() == 0  # the {2} was charged


def test_declining_wandering_archaics_tax_lets_you_copy_the_spell():
    engine, state, p1, p2 = _engine()
    archaic = _catalogue_obj(state, "Wandering Archaic")
    state.add_to_battlefield(archaic)

    spell = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(spell, Zone.HAND)
    p2.mana_pool.add("R", 3)
    engine.rules.cast_spell(p2, spell)

    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice("decline")
    assert state.pending_choice["kind"] == "composite_optional"
    engine.rules.resolve_choice("yes")

    copies = [i for i in state.stack if i.obj is not None and getattr(i.obj, "is_copy", False)]
    assert len(copies) == 1
    assert copies[0].controller_id == "p1"  # RULE 707.10c: the copier controls it


def test_wandering_archaic_never_triggers_off_a_creature_spell():
    engine, state, p1, p2 = _engine()
    archaic = _catalogue_obj(state, "Wandering Archaic")
    state.add_to_battlefield(archaic)

    creature = GameObject(_bear("Grizzly"), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(creature, Zone.HAND)
    p2.mana_pool.add("G", 2)
    engine.rules.cast_spell(p2, creature)

    assert engine.rules.pending_triggers == []  # "instant or sorcery spell"


def _etb(obj):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    return GameEvent(
        EventType.ENTERS_BATTLEFIELD,
        instance_id=obj.instance_id,
        controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    )
