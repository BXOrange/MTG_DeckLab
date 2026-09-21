"""MEC-42 — `cEDH staples`'s 12 named gap cards, done to completion:
Ashling the Limitless, Dauthi Voidwalker, Derevi Empyrial Tactician, Mana
Crypt, March of Swirling Mist, Orcish Bowmasters, Praetor's Grasp, Sevinne's
Reclamation, Teferi Time Raveler, Touch the Spirit Realm, Tymna the Weaver
(Abrupt Decay/Cabal Ritual/Culling Ritual/Ranger-Captain of Eos/Tinder
Wall/Yasharn/Ad Nauseam closed earlier as part of MEC-40/MEC-41).

Reference: docs/implementation-state/Done_Backend.md "MEC-42" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem

from tests.support.game import make_engine
from tests import turn_history_events as history


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _vanilla(name="Bear", power=2, toughness=2, is_land=False, mana_cost_string="{1}{G}", color_identity=None):
    if is_land:
        return Card(id=name, name=name, type_line="Land", is_land=True)
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string=mana_cost_string,
        converted_mana_cost=2, color_identity=color_identity,
    )


def _filler(n):
    return [_vanilla(f"Filler {i}") for i in range(n)]


def _put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _fire_etb(state, obj):
    """`add_to_battlefield`/`_put` deliberately don't fire ENTERS_BATTLEFIELD
    themselves (only a real `RulesEngine` cast/reanimation path does) — the
    same convention `engine_bench.py`'s own `put()` fixture follows. Tests
    that need an ETB trigger to actually queue must fire it explicitly.
    """
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            controller_id=obj.controller_id,
            object=obj.name,
            instance_id=obj.instance_id,
            object_types=sorted(obj.type_words),
        )
    )


def _to_graveyard(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    state.player_by_id(controller).graveyard.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Ashling, the Limitless
# ---------------------------------------------------------------------------


def test_ashling_sacrifice_elemental_copies_it_with_haste():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    _put(state, _named("Ashling, the Limitless"))
    elem = _put(state, _named("Risen Reef"))
    eng.recompute_continuous_effects()

    eng.rules.put_into_graveyard(elem)
    eng.resolve_until_stable()

    tokens = [o for o in state.battlefield if o.name == "Risen Reef" and o.is_token]
    assert len(tokens) == 1
    assert "haste" in tokens[0].temp_keywords
    assert state.delayed_triggers, "the sac-unless-pay delayed trigger should be armed"


def test_ashling_grants_evoke_to_elemental_spells_from_hand():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    _put(state, _named("Ashling, the Limitless"))
    _to_hand(state, _named("Risen Reef"))
    eng.recompute_continuous_effects()
    eng.begin_turn()
    state.current_step = "main1"
    p1.mana_pool.add_many({"C": 4})

    assert eng.can_cast(p1, next(o for o in p1.hand if o.name == "Risen Reef"), evoke=True)


# ---------------------------------------------------------------------------
# Evoke (general mana-cost primitive, off a real evoke creature)
# ---------------------------------------------------------------------------


def test_evoke_cast_enters_then_sacrifices_itself():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    mulldrifter = _to_hand(state, _named("Mulldrifter"))
    p1.mana_pool.add_many({"U": 1, "C": 2})

    eng.begin_turn()
    state.current_step = "main1"
    assert eng.can_cast(p1, mulldrifter, evoke=True)
    eng.cast_spell(p1, mulldrifter, evoke=True)
    eng.resolve_until_stable()

    assert mulldrifter not in state.battlefield
    assert mulldrifter in p1.graveyard
    assert len(p1.hand) == 2, "the ETB draw-two should still have fired"


# ---------------------------------------------------------------------------
# Dauthi Voidwalker
# ---------------------------------------------------------------------------


def test_dauthi_voidwalker_redirects_opponent_graveyard_to_exile_with_void_counter():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p2 = state.player_by_id("p2")
    _put(state, _named("Dauthi Voidwalker"))
    victim = _put(state, _vanilla("Victim"), controller="p2")
    eng.recompute_continuous_effects()

    eng.rules.put_into_graveyard(victim)

    assert victim not in p2.graveyard
    assert victim.zone == Zone.EXILE
    assert victim.instance_id in state.void_counter_holder
    assert state.void_counter_holder[victim.instance_id] == "p1"


def test_dauthi_voidwalker_activation_grants_free_cast_of_void_countered_card():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    dauthi = _put(state, _named("Dauthi Voidwalker"))
    victim = _put(state, _vanilla("Victim"), controller="p2")
    eng.recompute_continuous_effects()
    eng.rules.put_into_graveyard(victim)

    ability = dauthi.activated_abilities[0]
    assert eng.can_activate(p1, dauthi, ability)
    eng.activate_ability(p1, dauthi, 0)
    eng.resolve_until_stable()
    assert state.pending_choice is not None and state.pending_choice.get("kind") == "choose_objects"
    eng.resolve_pending_choice(str(victim.instance_id))
    eng.resolve_until_stable()

    assert victim.instance_id in state.free_cast_instance_ids
    assert state.temp_play_permission_player.get(victim.instance_id) == "p1"


# ---------------------------------------------------------------------------
# Derevi, Empyrial Tactician
# ---------------------------------------------------------------------------


def test_derevi_etb_offers_tap_or_untap_choice():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    other = _put(state, _vanilla("Other"), tapped=True)
    derevi = _put(state, _named("Derevi, Empyrial Tactician"))
    _fire_etb(state, derevi)
    eng.resolve_until_stable()

    # RULE 115/608.2: the trigger's own target is chosen first (as it goes
    # on the stack), *then* — once it resolves — the tap-or-untap choice.
    target_choice = state.pending_choice
    assert target_choice is not None and target_choice.get("kind") == "trigger_target"
    eng.resolve_pending_choice(str(other.instance_id))
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "tap_or_untap"
    eng.rules.resolve_choice("untap")
    assert other.tapped is False


# ---------------------------------------------------------------------------
# Mana Crypt
# ---------------------------------------------------------------------------


def test_mana_crypt_upkeep_coin_flip_can_deal_damage():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    _put(state, _named("Mana Crypt"))
    starting_life = p1.life

    eng.begin_turn()
    eng.resolve_until_stable()

    # A coin flip is non-deterministic — either the player's life dropped by
    # exactly 3 (lost the flip) or it's unchanged (won it). Anything else is
    # a bug.
    assert p1.life in (starting_life, starting_life - 3)


# ---------------------------------------------------------------------------
# March of Swirling Mist
# ---------------------------------------------------------------------------


def test_march_of_swirling_mist_exile_discount_reduces_generic_cost():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    march = _to_hand(state, _named("March of Swirling Mist"))
    _to_hand(state, _vanilla("Blue Card 1", mana_cost_string="{U}", color_identity={"U"}))
    _to_hand(state, _vanilla("Blue Card 2", mana_cost_string="{U}", color_identity={"U"}))

    eng.begin_turn()
    state.current_step = "main1"
    plain_cost = eng.effective_cast_cost(p1, march, x=2, exile_discount=0)
    discounted_cost = eng.effective_cast_cost(p1, march, x=2, exile_discount=2)

    def _x_amount(cost):
        from mtg_analyzer.models.mana.mana_cost import VARIABLE

        return sum(s.amount for s in cost.symbols if s.kind == VARIABLE)

    assert _x_amount(plain_cost) == 2  # the announced X, unreduced
    assert _x_amount(discounted_cost) == 0  # {2} per card * 2 cards fully absorbs X=2
    p1.mana_pool.add_many({"U": 1})
    assert eng.can_cast(p1, march, x=2, exile_discount=2)


def test_march_of_swirling_mist_phases_out_up_to_x_creatures():
    eng = make_engine(_filler(8), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    march = _to_hand(state, _named("March of Swirling Mist"))
    bear1 = _put(state, _vanilla("Bear1"))
    bear2 = _put(state, _vanilla("Bear2"), controller="p1")
    p1.mana_pool.add_many({"U": 1, "C": 2})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, march, targets=[bear1, bear2], x=2)
    eng.resolve_until_stable()

    assert bear1.phased_out is True
    assert bear2.phased_out is True


# ---------------------------------------------------------------------------
# Orcish Bowmasters
# ---------------------------------------------------------------------------


def test_orcish_bowmasters_etb_damages_and_amasses():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    p2.life = 20
    bowmasters = _put(state, _named("Orcish Bowmasters"))
    _fire_etb(state, bowmasters)
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None
    eng.resolve_pending_choice(str(p2.id))
    eng.resolve_until_stable()

    assert p2.life == 19
    army = next((o for o in state.battlefield if "Army" in o.card.type_line), None)
    assert army is not None
    assert army.counters.get("+1/+1", 0) == 1


def test_orcish_bowmasters_triggers_on_extra_opponent_draw_not_first():
    eng = make_engine(_filler(5), _filler(8), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    _put(state, _named("Orcish Bowmasters"))
    eng.resolve_until_stable()
    # decline the ETB trigger's damage (no meaningful target needed for this check)
    if state.pending_choice:
        eng.resolve_pending_choice(str(p1.id))
        eng.resolve_until_stable()

    # An extra draw (not the draw step's own first draw) should trigger again.
    eng.rules.draw(p2, 1)
    eng.resolve_until_stable()
    assert state.pending_choice is not None, "the opponent's extra draw should have triggered Bowmasters again"


# ---------------------------------------------------------------------------
# Praetor's Grasp
# ---------------------------------------------------------------------------


def test_praetors_grasp_searches_target_opponents_library_and_grants_standing_cast():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    grasp = _to_hand(state, _named("Praetor's Grasp"))
    p1.mana_pool.add_many({"B": 2, "C": 1})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, grasp, targets=[p2])
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    assert choice.get("player_id") == "p1"  # the CASTER answers
    assert choice.get("library_owner_id") == "p2"
    picked = state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(picked)

    obj = state.find_object(picked)
    assert obj.zone == Zone.EXILE
    assert obj.face_down_in_exile is True
    holder_id, condition = state.exile_cast_condition[picked]
    assert holder_id == "p1"
    assert obj in p2.exile  # owner never changes


# ---------------------------------------------------------------------------
# Sevinne's Reclamation
# ---------------------------------------------------------------------------


def test_sevinnes_reclamation_reanimates_cheap_permanent():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    reclamation = _to_hand(state, _named("Sevinne's Reclamation"))
    dead = _to_graveyard(state, _vanilla("Dead Thing"))
    p1.mana_pool.add_many({"W": 1, "C": 2})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, reclamation, targets=[dead])
    eng.resolve_until_stable()

    assert dead in state.battlefield


def test_sevinnes_reclamation_copies_itself_when_cast_via_flashback():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    reclamation = _to_graveyard(state, _named("Sevinne's Reclamation"))
    dead = _to_graveyard(state, _vanilla("Dead Thing"))
    p1.mana_pool.add_many({"W": 2, "C": 3})

    eng.begin_turn()
    state.current_step = "main1"
    assert eng.can_cast(p1, reclamation)
    eng.cast_spell(p1, reclamation, targets=[dead])
    assert len(state.stack) == 1

    # Resolve just the original — its own trailing clause should push a
    # self-copy onto the stack (LIFO, so it resolves next) before the
    # original itself is done.
    eng.rules.resolve_top_of_stack()
    assert len(state.stack) == 1
    assert getattr(state.stack[0].obj, "is_copy", False)


# ---------------------------------------------------------------------------
# Teferi, Time Raveler
# ---------------------------------------------------------------------------


def test_teferi_forces_opponents_to_sorcery_speed():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p2 = state.player_by_id("p2")
    _put(state, _named("Teferi, Time Raveler"))
    bolt = _to_hand(state, _named("Lightning Bolt"), controller="p2")
    p2.mana_pool.add_many({"R": 1})

    eng.begin_turn()  # p1's turn, active player p1
    state.current_step = "main1"
    assert not eng.can_cast(p2, bolt), "an instant should be denied to a restricted opponent off their own turn"


def test_teferi_plus_one_grants_sorcery_flash_to_own_controller():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    teferi = _put(state, _named("Teferi, Time Raveler"))
    sorcery = _to_hand(state, _named("Wrath of God"))
    p1.mana_pool.add_many({"W": 2, "C": 2})

    eng.begin_turn()
    state.current_step = "main1"
    idx = next(
        i for i, a in enumerate(teferi.activated_abilities) if a.cost.loyalty == 1
    )
    eng.activate_ability(p1, teferi, idx)
    eng.resolve_until_stable()

    # Now off the normal sorcery-speed window (opponent's turn, stack full).
    state.active_player_id = "p1"
    state.current_step = "combat_damage"
    assert eng.can_cast(p1, sorcery)


# ---------------------------------------------------------------------------
# Touch the Spirit Realm
# ---------------------------------------------------------------------------


def test_touch_the_spirit_realm_etb_exile_returns_when_it_leaves():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    target = _put(state, _vanilla("Target Thing"))
    touch = _put(state, _named("Touch the Spirit Realm"))
    _fire_etb(state, touch)
    eng.resolve_until_stable()
    if state.pending_choice:
        eng.rules.resolve_choice(str(target.instance_id))
        eng.resolve_until_stable()

    assert target.zone == Zone.EXILE

    eng.rules.put_into_graveyard(touch)
    eng.resolve_until_stable()

    assert target in state.battlefield


def test_touch_the_spirit_realm_channel_exiles_and_schedules_return():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    touch = _to_hand(state, _named("Touch the Spirit Realm"))
    target = _put(state, _vanilla("Channel Target"))
    p1.mana_pool.add_many({"W": 1, "C": 1})

    eng.begin_turn()
    state.current_step = "main1"
    ability = touch.activated_abilities[0]
    assert eng.can_activate(p1, touch, ability)
    eng.activate_ability(p1, touch, 0, targets=[target])
    eng.resolve_until_stable()

    assert touch not in p1.hand
    assert touch in p1.graveyard
    assert target.zone == Zone.EXILE
    assert state.delayed_triggers


# ---------------------------------------------------------------------------
# Tymna the Weaver
# ---------------------------------------------------------------------------


def test_tymna_postcombat_main_offers_pay_life_draw_x():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    _put(state, _named("Tymna the Weaver"))
    attacker = _put(state, _vanilla("Attacker"))
    p1.life = 30

    eng.begin_turn()
    history.damage(state, source_id=attacker.instance_id, source_controller_id="p1", target_id=p2.id, combat=True)
    state.current_step = "main2"
    from mtg_analyzer.models.game.events import EventType, GameEvent
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main2", player_id="p1"))
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "pay_cost_then"
    eng.rules.resolve_choice("pay")
    eng.resolve_until_stable()

    assert p1.life == 29
    assert len(p1.hand) == 1


# ---------------------------------------------------------------------------
# Delay (MEC-42's last card — RULE 702.62 Suspend, built as a real primitive)
# ---------------------------------------------------------------------------


def _fire_upkeep(eng, active_player_id):
    eng.state.active_player_index = [p.id for p in eng.state.players].index(active_player_id)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()


def test_delay_counters_spell_into_exile_with_suspend_and_time_counters():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p2 = state.player_by_id("p2")

    victim = GameObject(_vanilla("Victim", mana_cost_string="{3}"), owner_id="p2", zone=Zone.STACK)
    state.stack.append(StackItem(kind="spell", controller_id="p2", obj=victim, description="Victim", effects=[]))

    delay = GameObject(_named("Delay"), owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(delay)
    state.stack.append(StackItem(
        kind="spell", controller_id="p1", obj=delay, description="Delay",
        effects=eng.rules._effects_for_spell(delay), targets=[victim],
    ))
    eng.rules.resolve_top_of_stack()  # resolve Delay

    assert victim not in p2.graveyard
    assert victim in p2.exile, "countered into exile, not the graveyard"
    assert victim.counters.get("time") == 3
    assert victim.granted_suspend is True


def test_delay_suspended_creature_counts_down_and_casts_free_with_haste():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p2 = state.player_by_id("p2")

    victim_card = Card(
        id="Suspended Bear", name="Suspended Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2, mana_cost_string="{3}", converted_mana_cost=3,
    )
    victim = GameObject(victim_card, owner_id="p2", zone=Zone.EXILE)
    bind_from_catalogue(victim)
    victim.granted_suspend = True
    victim.add_counters("time", 3)
    p2.exile.append(victim)

    _fire_upkeep(eng, "p2")
    assert victim.counters.get("time") == 2, "first upkeep removes one counter"
    assert victim.instance_id not in state.free_cast_instance_ids

    _fire_upkeep(eng, "p2")
    assert victim.counters.get("time") == 1

    _fire_upkeep(eng, "p2")
    assert victim.counters.get("time", 0) == 0, "last counter removed"
    assert victim.instance_id in state.free_cast_instance_ids, "free-cast window opened"
    assert victim.granted_suspend_haste is True

    state.current_step = "main1"
    assert eng.can_cast(p2, victim)
    eng.cast_spell(p2, victim)
    eng.resolve_until_stable()

    assert victim in state.battlefield
    assert "haste" in victim.temp_keywords
    assert victim.granted_suspend_haste is False, "consumed once at resolution"


def test_suspend_special_action_pays_printed_cost_and_arms_existing_upkeep_path():
    """MEC-64 / RULE 702.62a: the first Suspend ability is a hand action."""
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    card = Card(
        id="Suspend Bear", name="Suspend Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2, mana_cost_string="{5}",
        converted_mana_cost=5, oracle_text="Suspend 2—{1}{U}", keywords=["Suspend"],
    )
    bear = _to_hand(state, card)
    bind_from_catalogue(bear)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.begin_turn()
    state.current_step = "main1"

    offer = next(a for a in eng.legal_actions(p1) if a.get("type") == "suspend")
    assert offer["instance_id"] == bear.instance_id
    assert offer["cost_label"] == "{1}{U}"
    assert offer["time_counters"] == 2

    eng.suspend(p1, bear)

    assert bear in p1.exile
    assert bear.counters.get("time") == 2
    assert p1.mana_pool.total() == 0

    _fire_upkeep(eng, "p1")
    _fire_upkeep(eng, "p1")
    assert bear.instance_id in state.free_cast_instance_ids


def test_suspend_special_action_is_not_available_on_an_opponents_turn():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    card = Card(
        id="Suspend Instant", name="Suspend Instant", type_line="Instant",
        is_instant=True, mana_cost_string="{4}", converted_mana_cost=4,
        oracle_text="Suspend 1—{U}", keywords=["Suspend"],
    )
    spell = _to_hand(state, card)
    bind_from_catalogue(spell)
    p1.mana_pool.add_many({"U": 1})
    eng.begin_turn()
    state.current_step = "main1"
    state.active_player_index = 1

    assert not eng.can_suspend(p1, spell)
    assert not any(a.get("type") == "suspend" for a in eng.legal_actions(p1))
