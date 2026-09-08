"""MEC-43 round 4, cluster F — five genuinely new small subsystems.

K'rrik, Son of Yawgmoth: a standing, unscoped alternative-payment
permission over *any* cost ("For each {B} in a cost, you may pay 2 life
rather than pay that mana.") — broader than every existing wildcard-color
mechanism (those only ever relax *which* mana pays a pip; this adds a way
to skip paying mana for a plain colored pip at all, the same life option a
printed Phyrexian pip already has). New: `ManaPool.can_pay`/`pay`'s
``extra_life_color`` param, `continuous.life_for_mana_pip_color`
(consulted at both real cost-payment sites — casting and activating), and
the `grant_life_for_mana_pip` static.

Maralen of the Mornsong: a mass draw prohibition ("Players can't draw
cards.") plus an ordinary per-player draw-step trigger
(search-shuffle-into-hand).

Keen Duelist: a simultaneous mutual reveal-and-compare upkeep trigger —
fully deterministic, one atomic effect.

Scroll Rack: reuses `GameObject.face_down_in_exile`, `RulesEngine.
request_choose_objects`, and the scry/surveil two-phase "order the rest
back on top" machinery — the genuinely new part is putting the *exiled*
cards back on top afterward.

Dance of the Dead: RULE 704.5n Necromancy-shaped — enchants a card in a
graveyard, reanimates it and re-attaches to the permanent it created.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game import continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
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


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1", obj=None):
    obj = obj or GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# K'rrik, Son of Yawgmoth
# ---------------------------------------------------------------------------


def test_krrik_pays_life_instead_of_black_mana_and_gains_a_counter():
    eng, state, p1, p2 = _engine()
    krrik = _bf(state, _named("K'rrik, Son of Yawgmoth"), controller="p1")
    assert krrik.counters.get("+1/+1", 0) == 0

    spell_card = _card(
        "Test Black Spell", type_line="Sorcery", cost="{B}", cmc=1, color_identity={"B"},
    )
    spell_obj = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell_obj)
    p1.hand.append(spell_obj)

    # No black mana in the pool at all — without K'rrik's permission this
    # cast would simply be illegal.
    assert p1.mana_pool.pool.get("B", 0) == 0
    assert eng.can_cast(p1, spell_obj)

    eng.cast_spell(p1, spell_obj)

    # KRRIK_LIFE_PER_BLACK_PIP life paid instead of the {B} pip; no mana
    # left the (empty) pool.
    assert p1.life == 18
    assert p1.mana_pool.total() == 0
    assert any(item.obj is spell_obj for item in state.stack)

    # K'rrik's own "whenever you cast a black spell" trigger put a +1/+1
    # counter on him — drain the pending trigger (and the spell itself)
    # off the stack.
    eng.resolve_until_stable()
    assert krrik.counters.get("+1/+1", 0) == 1


# ---------------------------------------------------------------------------
# Maralen of the Mornsong
# ---------------------------------------------------------------------------


def test_maralen_prohibits_draws_and_runs_the_draw_step_replacement():
    eng, state, p1, p2 = _engine()
    _bf(state, _named("Maralen of the Mornsong"), controller="p1")

    # "Players can't draw cards." — a plain draw simply does nothing now,
    # for either player (`draw_limit` at `max_per_turn=0`, unscoped).
    forest = _card("Library Forest", type_line="Basic Land — Forest", cost="", cmc=0)
    p2.library.append(GameObject(forest, owner_id="p2", zone=Zone.LIBRARY))
    before_hand = len(p2.hand)
    eng.rules.draw(p2, 1)
    assert len(p2.hand) == before_hand
    assert forest not in p2.hand

    # Fire p1's (the active player's) draw step: they lose 3 life and are
    # forced to search their own library, even though ordinary draws are
    # shut off.
    only_card = _card("Library Bear", type_line="Creature — Bear", cost="{1}{G}", cmc=2)
    p1.library.append(GameObject(only_card, owner_id="p1", zone=Zone.LIBRARY))
    p1.life = 20

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="draw", phase="draw"))
    eng.resolve_until_stable()

    assert p1.life == 17
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    found_id = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(found_id)
    assert any(o.name == "Library Bear" for o in p1.hand)


# ---------------------------------------------------------------------------
# Keen Duelist
# ---------------------------------------------------------------------------


def test_keen_duelist_mutual_reveal_compares_mana_values():
    eng, state, p1, p2 = _engine()
    _bf(state, _named("Keen Duelist"), controller="p1")

    # p1's own top card has mana value 1; p2's has mana value 4 — p1
    # should lose 4 life (p2's MV), p2 should lose 1 life (p1's MV).
    p1_card = _card("P1 Top", type_line="Creature — Bear", cost="{B}", cmc=1)
    p2_card = _card("P2 Top", type_line="Creature — Ogre", cost="{3}{R}", cmc=4)
    p1.library.append(GameObject(p1_card, owner_id="p1", zone=Zone.LIBRARY))
    p2.library.append(GameObject(p2_card, owner_id="p2", zone=Zone.LIBRARY))
    p1.life = 20
    p2.life = 20

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.rules.put_triggers_on_stack()

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.rules.resolve_trigger_target_choice("p2")
    eng.resolve_until_stable()

    assert p1.life == 16  # lost p2's revealed mana value (4)
    assert p2.life == 19  # lost p1's revealed mana value (1)
    assert any(o.name == "P2 Top" for o in p2.hand)
    assert any(o.name == "P1 Top" for o in p1.hand)


# ---------------------------------------------------------------------------
# Scroll Rack
# ---------------------------------------------------------------------------


def test_scroll_rack_exiles_hand_draws_and_reorders_onto_library():
    eng, state, p1, p2 = _engine()
    rack = _bf(state, _named("Scroll Rack"), controller="p1")
    eng.rules.add_mana(p1, "C", 1)

    hand_a = GameObject(_card("Hand A", cost="{1}", cmc=1), owner_id="p1", zone=Zone.HAND)
    hand_b = GameObject(_card("Hand B", cost="{1}", cmc=1), owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([hand_a, hand_b])

    # Library, bottom-first: Z on the bottom, Y, then X on top.
    lib_z = GameObject(_card("Lib Z"), owner_id="p1", zone=Zone.LIBRARY)
    lib_y = GameObject(_card("Lib Y"), owner_id="p1", zone=Zone.LIBRARY)
    lib_x = GameObject(_card("Lib X"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([lib_z, lib_y, lib_x])

    eng.activate_ability(p1, rack, ability_index=0)
    eng.resolve_until_stable()

    # Exile both hand cards (only 2 candidates, "any number" — pick each in
    # turn, then decline is unnecessary since the pool empties on its own).
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    assert choice["action"] == "exile"
    eng.rules.resolve_choose_objects_choice(hand_a.instance_id)
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    eng.rules.resolve_choose_objects_choice(hand_b.instance_id)

    # Both hand cards are now exiled, face down; two cards moved from the
    # top of the library into hand (not exiled — RULE 121.4, not a draw).
    assert hand_a.zone == Zone.EXILE and hand_a.face_down_in_exile is True
    assert hand_b.zone == Zone.EXILE and hand_b.face_down_in_exile is True
    assert lib_x in p1.hand and lib_y in p1.hand
    assert lib_x not in p1.library and lib_y not in p1.library

    # Now order the two exiled cards back onto the library — pick B first,
    # so it ends up on top (A goes automatically underneath it).
    order_choice = state.pending_choice
    assert order_choice is not None and order_choice["kind"] == "scroll_rack"
    eng.rules.resolve_scroll_rack_choice(hand_b.instance_id)

    assert state.pending_choice is None
    assert hand_a.zone == Zone.LIBRARY and hand_a.face_down_in_exile is False
    assert hand_b.zone == Zone.LIBRARY and hand_b.face_down_in_exile is False
    assert hand_a not in p1.exile and hand_b not in p1.exile
    # Bottom-first order: Z, then A, then B on top.
    assert p1.library == [lib_z, hand_a, hand_b]


# ---------------------------------------------------------------------------
# Dance of the Dead
# ---------------------------------------------------------------------------


def test_dance_of_the_dead_reanimates_tapped_with_anthem_and_sacrifices_on_leave():
    from tests.support.game import creature, make_engine

    dance = _named("Dance of the Dead")
    eng = make_engine([dance], [dance], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 2})  # {1}{B}

    bear = GameObject(creature("Bear", power=2, toughness=2), owner_id="p2", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p2").graveyard.append(bear)

    aura = p1.hand[0]
    bind_from_catalogue(aura)
    assert eng.can_cast(p1, aura, targets=[bear])
    eng.cast_spell(p1, aura, targets=[bear])
    eng.resolve_until_stable()

    reanimated = next(o for o in eng.state.battlefield if o.card.name == "Bear")
    assert reanimated.controller_id == "p1"  # under YOUR control, not the owner's
    assert reanimated.owner_id == "p2"
    assert reanimated.tapped is True  # "onto the battlefield tapped"
    assert aura.attached_to == reanimated.instance_id

    eng.recompute_continuous_effects()
    assert reanimated.power == 3 and reanimated.toughness == 3  # printed 2/2 +1/+1
    assert continuous.has_no_untap_static(eng.state, reanimated)

    eng.rules.put_into_graveyard(aura)
    eng.resolve_until_stable()

    assert aura not in eng.state.battlefield
    assert reanimated not in eng.state.battlefield
    assert reanimated in eng.state.player_by_id("p2").graveyard


def test_dance_of_the_dead_upkeep_pay_untaps_the_enchanted_creatures_controller_only():
    from tests.support.game import creature, make_engine

    dance = _named("Dance of the Dead")
    eng = make_engine([dance], [dance], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 4})  # {1}{B} to cast, {1}{B} to untap later

    bear = GameObject(creature("Bear", power=2, toughness=2), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bear)

    aura = p1.hand[0]
    bind_from_catalogue(aura)
    eng.cast_spell(p1, aura, targets=[bear])
    eng.resolve_until_stable()

    reanimated = next(o for o in eng.state.battlefield if o.card.name == "Bear")
    assert reanimated.tapped is True

    # The reanimated creature's controller's own upkeep — the ability lives
    # on the Aura, but "that player" is the enchanted creature's controller
    # (`phase_relation="attached_permanent"`), not the Aura's own controller
    # (here the same player, but resolved live off `attached_to`).
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    eng.rules.resolve_pay_cost_then_choice("pay")

    assert reanimated.tapped is False
