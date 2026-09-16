"""MEC-43 round 4, cluster G — free-cast permissions, ability copying, and
one mass grant: The Tabernacle at Pendrell Vale, Rings of Brighthearth,
Isochron Scepter, Aluren, Knowledge Pool.

Each closes a real subsystem rather than a one-off card:

* **The Tabernacle at Pendrell Vale** needed no new group-scope primitive —
  `affects="all_creatures"` already exists for a quoted ability grant
  (`_QUOTED_GRANT_RE`) — only a new `"destroy_unless_pay"` verb alongside
  the existing `"sacrifice_unless_pay"` (RULE 701.16 destruction, so a
  regeneration shield can still save it, unlike sacrifice): `Destroy
  UnlessPayEffect`, `RulesEngine._request_destroy_unless_pay`/
  `_resume_destroy_unless_pay`. Fully parser-MODELED, no
  hand-authoring needed.
* **Rings of Brighthearth** (RULE 706.10) needed `CopyAbilityEffect`/
  `RulesEngine.copy_ability` — the ability-item sibling of the existing
  spell-copy machinery, identifying "that ability" via `StackItem.
  stack_id` remembered onto `GameObject.remembered_stack_id`
  (`PayCostThenEffect`'s new `remember_trigger_stack_id`), since the
  `context.trigger_event` window has closed by the time the "if you do"
  branch of its {2} payment actually runs.
* **Isochron Scepter** widened `ImprintEffect` with an inclusion filter
  (`include_card_type`/`max_mana_value`) and added `CopyImprintedCard
  Effect` — a fresh token copy built straight into exile (never touching
  the battlefield) and given a `grant_free_cast_window_from_exile` window,
  repeatable since the original stays exiled forever. Surfaced a real
  latent gap: `_remove_stranded_tokens` swept *any* non-battlefield token
  unconditionally, which would have reaped the copy before it could ever
  be cast — now exempted while `GameState.free_cast_instance_ids` covers it.
* **Aluren** is the first free-cast permission in this engine not scoped to
  one controller — a new standing `"free_cast_permission"` static
  (`continuous.has_standing_free_cast_permission`/
  `standing_free_cast_grants_flash`), consulted by `GameEngine.can_cast`'s
  `free=True` branch (widened to accept a standing permission alongside
  the existing per-object `free_cast_condition`) and offered by
  `_offer_cast`/`_castable_now_or_via_potential`. The bundled flash grant
  is deliberately gated on `free=True` — it's part of *this* permission,
  not a blanket flash grant on the card.
* **Knowledge Pool** is a cast-substitution mechanism riding
  `RulesEngine.move_spell_off_stack` (already built for Possibility
  Storm/Narset's Reversal) plus `GameObject.exiled_with_ids` (MEC-21) as
  the shared, ever-growing pool. Surfaced a second real gap: `legal_actions`
  only ever scanned the *acting* player's own exile zone for a temp-play-
  permission grant — every prior grant of that shape always exiled into
  the same player who'd cast it, but Knowledge Pool's shared pool can hand
  a player a free cast of a card sitting in *another* player's exile.

Reference: mtg_analyzer/game/{effects,continuous,card_registry}.py,
mtg_analyzer/game/engine/{casting_mixin,legal_actions_mixin,
activation_mixin}.py, mtg_analyzer/game/rules/{misc_mixin,copies_mixin,
sba_mixin}.py, mtg_analyzer/models/game_object.py.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase

from tests.support.game import creature, make_engine


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _artifact(name, cost="{2}", cmc=2):
    return Card(id=name, name=name, type_line="Artifact",
                mana_cost_string=cost, converted_mana_cost=cmc)


def _bf(state, card, controller="p1", summoning_sick=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_upkeep(eng, player_id="p1"):
    # RULE 613: a layer-6 granted triggered ability (Tabernacle's "All
    # creatures have '...'") is re-derived every `continuous.recompute`
    # pass, not bound once at object creation -- a test that boards
    # permanents by hand must recompute before a granted ability can ever
    # reach `put_triggers_on_stack`.
    continuous.recompute(eng.state)
    eng.state.active_player_index = [p.id for p in eng.state.players].index(player_id)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


# ---------------------------------------------------------------------------
# The Tabernacle at Pendrell Vale
# ---------------------------------------------------------------------------


def test_tabernacle_destroys_every_creature_unless_its_controller_pays():
    # RULE 613/500.7: the grant is unrestricted ("All creatures have...",
    # no "you control") and fires each creature's own trigger on its
    # *own* controller's upkeep -- so this exercises both p1's and p2's
    # upkeep separately, proving the mass grant really reaches an
    # opponent's creature too, not just the controller's own board.
    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _bf(eng.state, _named("The Tabernacle at Pendrell Vale"), controller="p1")
    mine = _bf(eng.state, creature("My Bear"), controller="p1")
    theirs = _bf(eng.state, creature("Their Bear"), controller="p2")
    p1.mana_pool.add("C", 1)  # can afford {1}
    # p2 has no mana at all -- can't afford, destroyed outright.

    _fire_upkeep(eng, "p1")
    assert eng.state.pending_choice["kind"] == "destroy_unless_pay"
    eng.resolve_pending_choice("pay")
    assert mine in eng.state.battlefield  # p1 paid {1}, kept it
    assert p1.mana_pool.total() == 0

    _fire_upkeep(eng, "p2")
    # p2 has no mana -- destroyed outright, no choice ever offered.
    assert eng.state.pending_choice is None
    assert theirs not in eng.state.battlefield
    assert theirs in p2.graveyard


# ---------------------------------------------------------------------------
# Rings of Brighthearth
# ---------------------------------------------------------------------------


def test_rings_of_brighthearth_copies_a_paid_for_activated_ability():
    from mtg_analyzer.game.costs import ActivationCost
    from mtg_analyzer.game.effects.core import ActivatedAbility, DealDamageEffect

    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _bf(eng.state, _artifact("Rings of Brighthearth", "{3}", 3), controller="p1")
    source = _bf(eng.state, _artifact("Shock Source", "{1}", 1), controller="p1")
    source.activated_abilities = [
        ActivatedAbility(
            effects=[DealDamageEffect(1, target_kind="player")],
            cost=ActivationCost(taps_self=True),
            description="{T}: deal 1 damage to any target.",
        )
    ]
    source.activated_abilities[0].source = source
    p1.mana_pool.add("C", 2)

    eng.activate_ability(p1, source, 0, targets=[p2])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()  # Rings' own trigger resolves first (LIFO)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")  # {2} -- copy the ability

    assert p1.mana_pool.total() == 0
    assert p2.life == 18  # 1 (original) + 1 (copy) = 2 damage total


def test_declining_the_copy_leaves_a_single_activation():
    from mtg_analyzer.game.costs import ActivationCost
    from mtg_analyzer.game.effects.core import ActivatedAbility, DealDamageEffect

    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _bf(eng.state, _artifact("Rings of Brighthearth", "{3}", 3), controller="p1")
    source = _bf(eng.state, _artifact("Shock Source", "{1}", 1), controller="p1")
    source.activated_abilities = [
        ActivatedAbility(
            effects=[DealDamageEffect(1, target_kind="player")],
            cost=ActivationCost(taps_self=True),
            description="{T}: deal 1 damage to any target.",
        )
    ]
    source.activated_abilities[0].source = source
    p1.mana_pool.add("C", 2)

    eng.activate_ability(p1, source, 0, targets=[p2])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_pending_choice("decline")

    assert p1.mana_pool.total() == 2  # nothing spent
    assert p2.life == 19  # only the original resolved


# ---------------------------------------------------------------------------
# Isochron Scepter
# ---------------------------------------------------------------------------


def test_isochron_scepter_imprints_and_repeatedly_casts_free_copies():
    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    bolt = _named("Lightning Bolt")
    p1.hand.append(GameObject(bolt, owner_id="p1", zone=Zone.HAND))
    scepter = _bf(eng.state, _artifact("Isochron Scepter"), controller="p1")

    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=scepter.instance_id,
        controller_id="p1", object=scepter.name, object_types=["artifact"],
    ))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects"
    eng.resolve_pending_choice(choice["options"][0]["id"])
    assert scepter.linked_exile_id is not None
    original_id = scepter.linked_exile_id

    scepter.tapped = False
    scepter.summoning_sick = False
    p1.mana_pool.add("C", 2)
    eng.activate_ability(p1, scepter, 0, targets=[])
    eng.resolve_until_stable()
    copy1 = next(o for o in p1.exile if o.is_token)
    eng.cast_spell(p1, copy1, targets=[p2])
    eng.resolve_until_stable()
    assert p2.life == 17  # one Bolt copy resolved

    # Repeatable: untap and do it again -- the original stays exiled.
    scepter.tapped = False
    p1.mana_pool.add("C", 2)
    eng.activate_ability(p1, scepter, 0, targets=[])
    eng.resolve_until_stable()
    copy2 = next(o for o in p1.exile if o.is_token)
    eng.cast_spell(p1, copy2, targets=[p2])
    eng.resolve_until_stable()
    assert p2.life == 14  # two Bolt copies total

    assert any(o.instance_id == original_id for o in p1.exile)  # never itself cast
    assert not any(o.is_token for o in p1.exile)  # each copy consumed itself


# ---------------------------------------------------------------------------
# Aluren
# ---------------------------------------------------------------------------


def test_aluren_lets_any_player_flash_in_a_cheap_creature_for_free():
    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _bf(eng.state, Card(
        id="Aluren", name="Aluren", type_line="Enchantment",
        mana_cost_string="{2}{G}{G}", converted_mana_cost=4,
    ), controller="p1")
    cheap = creature("Cheap Bear", cost="{2}{G}", power=3, toughness=3)
    cheap.converted_mana_cost = 3
    expensive = creature("Big Bear", cost="{5}{G}", power=6, toughness=6)
    expensive.converted_mana_cost = 6
    p2.hand.append(GameObject(cheap, owner_id="p2", zone=Zone.HAND))
    p2.hand.append(GameObject(expensive, owner_id="p2", zone=Zone.HAND))
    cheap_obj, expensive_obj = p2.hand[0], p2.hand[1]

    eng.state.active_player_index = 0  # p1's turn, not p2's -- flash needed
    # Any player (p2, not Aluren's own controller) with zero mana:
    assert eng.can_cast(p2, cheap_obj, free=True)
    assert not eng.can_cast(p2, expensive_obj, free=True)  # mana value too high
    offered = [
        a for a in eng.legal_actions(p2)
        if a.get("type") == "cast_spell" and a.get("free") and a.get("instance_id") == cheap_obj.instance_id
    ]
    assert len(offered) == 1

    eng.cast_spell(p2, cheap_obj, targets=[], free=True)
    eng.resolve_until_stable()
    assert any(o.name == "Cheap Bear" for o in eng.state.battlefield)
    assert p2.mana_pool.total() == 0  # truly free

    # Paying full price for a second copy on the opponent's turn is still
    # illegal -- Aluren's flash exemption is bundled with its own free-cast
    # method, not a blanket flash grant on the card.
    second = creature("Cheap Bear 2", cost="{2}{G}", power=3, toughness=3)
    second.converted_mana_cost = 3
    p2.hand.append(GameObject(second, owner_id="p2", zone=Zone.HAND))
    p2.mana_pool.add("G", 1)
    p2.mana_pool.add("C", 2)
    assert not eng.can_cast(p2, p2.hand[-1], free=False)


# ---------------------------------------------------------------------------
# Knowledge Pool
# ---------------------------------------------------------------------------


def test_knowledge_pool_imprints_and_lets_the_caster_free_cast_from_the_shared_pool():
    eng = make_engine([], [])
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    bolt = _named("Lightning Bolt")
    counterspell = _named("Counterspell")
    for _ in range(3):
        b1 = GameObject(bolt, owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(b1)
        p1.library.append(b1)
        b2 = GameObject(bolt, owner_id="p2", zone=Zone.LIBRARY)
        bind_from_catalogue(b2)
        p2.library.append(b2)

    kp = _bf(eng.state, _artifact("Knowledge Pool", "{6}", 6), controller="p1")
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=kp.instance_id,
        controller_id="p1", object=kp.name, object_types=["artifact"],
    ))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert len(kp.exiled_with_ids) == 6  # 3 cards x 2 players
    assert len(p1.exile) == 3 and len(p2.exile) == 3

    # p2 casts Counterspell from hand -- it never resolves as a counter; it
    # joins the shared pool instead, and p2 is offered a free cast from
    # among the *other* six cards.
    p2.hand.append(GameObject(counterspell, owner_id="p2", zone=Zone.HAND))
    counter_obj = p2.hand[0]
    p2.mana_pool.add("U", 2)
    eng.cast_spell(p2, counter_obj, targets=[])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()  # Knowledge Pool's own trigger (LIFO)

    assert any(o.name == "Counterspell" for o in p2.exile)  # exiled, not resolved
    assert len(kp.exiled_with_ids) == 7
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects"
    real_options = [o for o in choice["options"] if o["id"] != "decline"]
    assert len(real_options) == 6  # every pool card except the one just added

    pick = real_options[0]
    eng.resolve_pending_choice(pick["id"])
    picked = eng.state.find_object(pick["instance_id"])
    assert picked.zone == Zone.EXILE

    # The armed card is castable via ordinary legal_actions even though it
    # may sit in the *other* player's exile zone (the shared-pool gap).
    offered = [
        a for a in eng.legal_actions(p2)
        if a.get("type") == "cast_spell" and a.get("instance_id") == picked.instance_id
    ]
    assert len(offered) == 1

    before = p1.life
    eng.cast_spell(p2, picked, targets=[p1])
    eng.resolve_until_stable()
    assert p1.life == before - 3  # the free Lightning Bolt resolved
    assert p2.mana_pool.total() == 0  # truly free
    # Counterspell itself is never cast -- stays exiled with the artifact.
    assert any(o.name == "Counterspell" for o in p2.exile)
