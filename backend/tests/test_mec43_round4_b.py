"""MEC-43 round 4B: cEDH staples 2 / K'rrik cEDH trigger-composition cluster
(ETB / cast / upkeep triggers).

New primitives, each proven here on the real card that needed it:

* `RulesEngine._collect_self_cast_triggers` + `TriggeredAbility.
  functions_from_stack` (RULE 601.2i) — "when you cast this spell,
  `<effect>`" is a triggered ability belonging to the *spell itself*,
  only ever on the stack when its own `SPELL_CAST` fires — Kozilek,
  Butcher of Truth. Also proven *not* to over-fire an ordinary battlefield
  "whenever you cast a spell" static off its own casting (Crypt Ghast's
  Extort) — the bug the `functions_from_stack` flag exists to prevent.
* `continuous.hand_size_modifier_for` (the numeric sibling of the shipped
  boolean `has_no_maximum_hand_size`) — Jin-Gitaxias, Core Augur.
* `ChooseObjectsEffect.player_selector="active_player"` — Sheoldred,
  Whispering One's "each opponent's upkeep, that player sacrifices…".
* `ConniveEffect` (RULE 701.47) + `request_choose_objects`'s new
  ``connive`` flag — Ledger Shredder.
* `effect_binder`'s new ``spell_characteristic_equals_chosen_number``
  trigger predicate, reusing the shipped `ChooseNumberReplacement`
  (Sanctum Prelate) — Talion, the Kindly Lord.

Bontu's Monument and Korvold, Fae-Cursed King needed no new primitives —
both are compositions of already-shipped machinery (`cost_reduction`'s
``spell_type``/``spell_color`` combination; `EventType.SACRIFICE` +
`ChooseObjectsEffect`). Crypt Ghast's Extort is likewise a pure
composition (`PayCostThenEffect` + `GainLifeEffect.count_selector=
"life_lost_this_way"`) — its own second ability (the triggered mana
ability) reuses Wild Growth's shape verbatim.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


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


def _catalogue_obj(name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


def _hand(player, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def _fill_library(player, n, controller):
    for i in range(n):
        player.library.append(
            GameObject(_card(f"Filler {i}"), owner_id=controller, zone=Zone.LIBRARY)
        )


# ---------------------------------------------------------------------------
# Bontu's Monument
# ---------------------------------------------------------------------------


def test_bontus_monument_cost_reduces_black_creature_spells():
    engine, state, p1, _ = _engine()
    _bf(state, _named("Bontu's Monument"), controller="p1")
    spell = _hand(p1, _card("Sac Fodder", "Creature — Bear", "{2}{B}", 3, color_identity={"B"}), "p1")

    net, _contributors = continuous.cost_reduction_for(state, p1, spell)
    assert net == 1


def test_bontus_monument_drains_on_a_creature_cast():
    engine, state, p1, p2 = _engine()
    _bf(state, _named("Bontu's Monument"), controller="p1")
    spell = _hand(p1, _card("Sac Fodder", "Creature — Bear", "{2}{B}", 3, color_identity={"B"}), "p1")
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("C", 2)

    engine.rules.cast_spell(p1, spell)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert p2.life == 19
    assert p1.life == 21


# ---------------------------------------------------------------------------
# Korvold, Fae-Cursed King
# ---------------------------------------------------------------------------


def test_korvold_sacs_on_etb_then_grows_and_draws():
    engine, state, p1, _ = _engine()
    korvold = _catalogue_obj("Korvold, Fae-Cursed King", zone=Zone.BATTLEFIELD)
    bear = _bf(state, _card("Fodder"), controller="p1")
    _fill_library(p1, 1, "p1")
    start_hand = len(p1.hand)

    # RULE 603.6a: fire ENTERS_BATTLEFIELD while the object is genuinely on
    # the battlefield, mirroring `GameState.add_to_battlefield`'s own
    # append-then-fire ordering.
    state.add_to_battlefield(korvold)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=korvold.instance_id,
            object_types=sorted(korvold.type_words),
        )
    )
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert bear not in state.battlefield
    assert korvold.counters.get("+1/+1") == 1
    assert len(p1.hand) == start_hand + 1


# ---------------------------------------------------------------------------
# Kozilek, Butcher of Truth — the self-cast trigger primitive
# ---------------------------------------------------------------------------


def test_kozilek_draws_four_on_cast_before_it_even_resolves():
    engine, state, p1, _ = _engine()
    kozilek = _hand(p1, _named("Kozilek, Butcher of Truth"), "p1")
    _fill_library(p1, 4, "p1")
    p1.mana_pool.add("C", 10)

    engine.rules.cast_spell(p1, kozilek)
    engine.rules.put_triggers_on_stack()

    # The draw trigger sits *above* the spell on the stack and resolves
    # first — proving RULE 601.2i timing, not just that the draw happens
    # eventually.
    assert len(state.stack) == 2
    engine.resolve_until_stable()

    assert len(p1.hand) == 4
    assert any(obj.name == "Kozilek, Butcher of Truth" for obj in state.battlefield)


def test_crypt_ghasts_extort_does_not_fire_off_its_own_casting():
    """The bug `TriggeredAbility.functions_from_stack` exists to prevent:
    an ordinary "whenever you cast a spell" battlefield static must not
    fire off the very spell that will *become* that permanent — Crypt
    Ghast isn't a permanent yet while its own SPELL_CAST is firing."""
    engine, state, p1, _ = _engine()
    ghast = _hand(p1, _named("Crypt Ghast"), "p1")
    p1.mana_pool.add("B", 4)

    engine.rules.cast_spell(p1, ghast)
    placed = engine.rules.put_triggers_on_stack()

    assert placed == 0
    assert state.pending_choice is None
    assert len(state.stack) == 1


# ---------------------------------------------------------------------------
# Jin-Gitaxias, Core Augur
# ---------------------------------------------------------------------------


def test_jin_gitaxias_reduces_each_opponents_max_hand_size():
    engine, state, p1, p2 = _engine()
    _bf(state, _named("Jin-Gitaxias, Core Augur"), controller="p1")

    assert continuous.hand_size_modifier_for(state, p2) == -7
    # Jin-Gitaxias' own controller is unaffected ("**each opponent's**
    # maximum hand size").
    assert continuous.hand_size_modifier_for(state, p1) == 0


def test_jin_gitaxias_draws_seven_at_end_step():
    engine, state, p1, _ = _engine()
    _bf(state, _named("Jin-Gitaxias, Core Augur"), controller="p1")
    _fill_library(p1, 7, "p1")
    state.active_player_index = 0  # "p1"

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="end"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert len(p1.hand) == 7


# ---------------------------------------------------------------------------
# Sheoldred, Whispering One
# ---------------------------------------------------------------------------


def test_sheoldred_makes_each_opponent_sacrifice_a_creature_on_their_upkeep():
    engine, state, p1, p2 = _engine()
    _bf(state, _named("Sheoldred, Whispering One"), controller="p1")
    victim = _bf(state, _card("Opponent Fodder"), controller="p2")
    state.active_player_index = 1  # "p2"

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert victim not in state.battlefield
    assert victim in p2.graveyard


def test_sheoldreds_upkeep_sacrifice_does_not_fire_on_her_own_controllers_upkeep():
    engine, state, p1, p2 = _engine()
    _bf(state, _named("Sheoldred, Whispering One"), controller="p1")
    mine = _bf(state, _card("My Fodder"), controller="p1")
    state.active_player_index = 0  # "p1"

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    # Only the reanimate-from-graveyard half (a no-op here, empty
    # graveyard) is this permanent's own upkeep trigger; no sacrifice.
    assert mine in state.battlefield


# ---------------------------------------------------------------------------
# Ledger Shredder — connive
# ---------------------------------------------------------------------------


def test_ledger_shredder_connives_but_does_not_grow_off_a_land_discard():
    engine, state, p1, _ = _engine()
    shredder = _bf(state, _named("Ledger Shredder"), controller="p1")
    first = _hand(p1, _card("Bolt", "Instant", "{R}", 1), "p1")
    second = _hand(p1, _card("Bolt 2", "Instant", "{R}", 1), "p1")
    # The one card connive draws is a land, so the discard (forced — the
    # post-draw hand has exactly one card, no interactive prompt) is that
    # same land, and RULE 701.47's "if **nonland**" must withhold the
    # +1/+1 counter.
    p1.library.append(
        GameObject(_card("Forest", "Basic Land — Forest", "", 0, is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    )
    p1.mana_pool.add("R", 2)

    engine.rules.cast_spell(p1, first)
    engine.rules.resolve_top_of_stack()

    engine.rules.cast_spell(p1, second)
    hand_after_cast = len(p1.hand)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert shredder.counters.get("+1/+1", 0) == 0
    # Drew one (the Forest), then discarded it right back out: net zero
    # against the hand connive itself started from.
    assert len(p1.hand) == hand_after_cast


def test_ledger_shredder_grows_when_the_discard_is_nonland():
    engine, state, p1, _ = _engine()
    shredder = _bf(state, _named("Ledger Shredder"), controller="p1")
    first = _hand(p1, _card("Bolt", "Instant", "{R}", 1), "p1")
    second = _hand(p1, _card("Bolt 2", "Instant", "{R}", 1), "p1")
    p1.library.append(GameObject(_card("Another Bear"), owner_id="p1", zone=Zone.LIBRARY))
    p1.mana_pool.add("R", 2)

    engine.rules.cast_spell(p1, first)
    engine.rules.resolve_top_of_stack()

    engine.rules.cast_spell(p1, second)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert shredder.counters.get("+1/+1") == 1


# ---------------------------------------------------------------------------
# Talion, the Kindly Lord
# ---------------------------------------------------------------------------


def test_talion_punishes_a_spell_matching_the_chosen_number():
    engine, state, p1, p2 = _engine()
    talion = _hand(p1, _named("Talion, the Kindly Lord"), "p1")
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("C", 2)

    engine.rules.cast_spell(p1, talion)
    engine.rules.resolve_top_of_stack()  # opens the RULE 601.2b choose_number pick
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_number"
    engine.rules.resolve_enter_choice("3")

    _fill_library(p1, 1, "p1")  # Talion's own controller draws on the payoff
    _fill_library(p2, 2, "p2")
    matching = _hand(p2, _card("Three-Drop", "Creature — Bear", "{2}{G}", 3), "p2")
    p2.mana_pool.add("G", 1)
    p2.mana_pool.add("C", 2)
    start_p1_hand = len(p1.hand)

    engine.rules.cast_spell(p2, matching)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()

    assert p2.life == 18
    assert len(p1.hand) == start_p1_hand + 1


def test_talion_ignores_a_spell_that_does_not_match_the_chosen_number():
    engine, state, p1, p2 = _engine()
    talion = _hand(p1, _named("Talion, the Kindly Lord"), "p1")
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("B", 1)
    p1.mana_pool.add("C", 2)

    engine.rules.cast_spell(p1, talion)
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_enter_choice("9")

    other = _hand(p2, _card("Three-Drop", "Creature — Bear", "{2}{G}", 3), "p2")
    p2.mana_pool.add("G", 1)
    p2.mana_pool.add("C", 2)

    engine.rules.cast_spell(p2, other)
    placed = engine.rules.put_triggers_on_stack()

    assert placed == 0
    assert p2.life == 20


# ---------------------------------------------------------------------------
# Crypt Ghast — Extort + the triggered Swamp mana ability
# ---------------------------------------------------------------------------


def test_crypt_ghasts_extort_drains_each_opponent_and_gains_that_much():
    engine, state, p1, p2 = _engine()
    _bf(state, _named("Crypt Ghast"), controller="p1")
    spell = _hand(p1, _card("Bolt", "Instant", "{R}", 1), "p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("W", 1)

    engine.rules.cast_spell(p1, spell)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()  # resolves the Extort trigger itself

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"
    engine.rules.resolve_pay_cost_then_choice("pay")

    assert p2.life == 19
    assert p1.life == 21


def test_crypt_ghast_adds_extra_black_when_tapping_a_swamp():
    engine, state, p1, _ = _engine()
    _bf(state, _named("Crypt Ghast"), controller="p1")
    swamp = _bf(state, _card("Swamp", "Basic Land — Swamp", "", 0, is_land=True), controller="p1")
    swamp.tapped = False

    produced = engine.tap_for_mana(p1, swamp)

    assert produced.get("B", 0) == 1
    assert p1.mana_pool.pool.get("B", 0) == 2
