"""MEC-12 continuation, fourth pass (2026-08-10/11) - the seven cEDH decks.

Re-measured baseline before this pass: 764 unique cards, 436 covered / 328
uncovered. The user asked for the *rest* of the pool, not just the
remaining high-frequency cards -- this pass worked the parser/engine gap
list itself (docs/implementation-state/BACKLOG.md's per-card unclaimed
clauses) rather than picking off single cards, closing 451/764 by the end.
Still real, ordinary open work per the ticket's own framing -- a residue
remains, tracked back in BACKLOG.md.

New general primitives, each reusable far past this pool:

* RULE 603.1 untyped player-subject cast triggers ("whenever you/an
  opponent/a player casts a spell[, <effect>]", optionally with a "mana
  value N or less" filter) -- parser/oracle/segmenter.py's
  _CAST_SPELL_TRIGGER_PLAIN_RE/_CAST_SPELL_TRIGGER_MV_RE, riding
  effect_binder's *existing* {"subject": "group", "controller": ...}
  scoping (proven working for a non-permanent, player-keyed event by
  Smothering Tithe's own DRAW-event use last pass) -- no new engine
  primitive needed for the trigger condition itself, just a missing
  recognizer plus one new spell_mana_value_at_most predicate reading
  SPELL_CAST's already-stamped mana_value field.
* DealDamageEffect's new "event_player" selector -- "~ deals N damage to
  that player" (Spellshock/Eidolon of the Great Revel/Pyrostatic
  Pillar-shaped punishers), the player named by the firing trigger's own
  event, read via the same _event_player helper PayCostThenEffect's
  payer="event_player" already uses.
* _EXILE_TOP_PLAY_RE widened (impulsive draw, RULE 601.3b) to the
  *leading*-duration word order real cards actually print ("Until the end
  of your next turn, you may play those cards." -- Light Up the Stage's
  own text, not the trailing form the row was first written against),
  plus "that card"/"those cards" pronouns, a singular "the top card" (no
  number), and count_or_x_of for "the top x cards" (Commune with Lava).
  ImpulsiveDrawEffect itself was already fully built (Light Up the Stage
  was its *hand-authored* namesake) -- this was purely a missing
  recognizer, caught by testing the card the effect was named after.
* A regex-precedence bug fix in the new "search for a <colour> <type>
  card" widening: (?:white|blue|black|red|green\\s+)? binds \\s+ to only
  the last alternative, so "green X" matched by accident while every
  other colour silently didn't -- caught by testing more than one colour
  word, not just the one that happened to work.
* models/card_query.py gains max_power/min_power/max_toughness/
  min_toughness criteria keys, mirroring max_mana_value's shape exactly
  (Imperial Recruiter/Recruiter of the Guard's own "with power/toughness
  N or less" tutor qualifier -- the parser still doesn't parse this
  phrasing, same documented gap as "with mana value X or less", so both
  cards are hand-authored directly onto the new keys).
* effects.WheelOfFortuneEffect -- "each player discards their hand, then
  draws seven cards.", the flat-draw-count sibling of the already-shipped
  WheelEffect (Timetwister)/WindfallEffect (Windfall).
* DestroyEffect's mass-wipe filter gains a "nonbasic" key ("destroy all
  nonbasic lands." -- Ruination), paired with the existing
  selector="all_lands" the same way every other qualified board wipe
  narrows its selector with filter.

Also fixed a stale regression test (tests/test_oracle_triggers.py's
test_whenever_you_cast_a_spell_stays_unmodeled, renamed to _is_modeled)
that had documented the untyped cast-trigger gap this pass closed.
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


def _vanilla(name="Filler", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string="{1}{G}",
        converted_mana_cost=2,
    )


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


def _stock_library(state, controller, count):
    player = state.player_by_id(controller)
    for i in range(count):
        player.library.append(GameObject(
            _vanilla(f"{controller} Lib {i}"), owner_id=controller, zone=Zone.LIBRARY,
        ))


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _reach_main(engine):
    engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


# ---------------------------------------------------------------------------
# Untyped cast-spell triggers + the new "event_player" damage selector
# ---------------------------------------------------------------------------


def test_spellshock_is_modeled_and_damages_whoever_casts_a_spell():
    card = _named("Spellshock")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    _bf(state, card)
    _reach_main(engine)

    bolt = _to_hand(engine, Card(
        id="Bolt", name="Bolt", type_line="Instant", mana_cost_string="{R}",
        is_instant=True,
    ), controller="p2")
    p2 = state.player_by_id("p2")
    p2.mana_pool.add("R", 1)

    life_before = p2.life
    engine.cast_spell(p2, bolt, targets=None)
    engine.resolve_until_stable()

    assert p2.life == life_before - 2


def test_eidolon_of_the_great_revel_only_punishes_cheap_spells():
    card = _named("Eidolon of the Great Revel")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    _bf(state, card)
    _reach_main(engine)

    expensive = _to_hand(engine, Card(
        id="Big Spell", name="Big Spell", type_line="Instant",
        mana_cost_string="{8}", converted_mana_cost=8,  # mana value well above 3
        is_instant=True,
    ), controller="p2")
    p2 = state.player_by_id("p2")
    p2.mana_pool.add("C", 8)

    life_before = p2.life
    engine.cast_spell(p2, expensive, targets=None)
    engine.resolve_until_stable()

    assert p2.life == life_before  # mana value 8 > 3 -> no trigger


# ---------------------------------------------------------------------------
# Impulsive draw -- widened word order, pronouns, singular, "x" count
# ---------------------------------------------------------------------------


def test_light_up_the_stage_is_modeled_and_grants_a_play_permission():
    card = _named("Light Up the Stage")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    _stock_library(state, "p1", 5)
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 2)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()

    assert len(p1.exile) == 2
    assert all(state.temp_play_permissions.get(o.instance_id) for o in p1.exile)


# ---------------------------------------------------------------------------
# Search widening: colour-scoped criteria (regression for the \s+ bug) +
# the "equipment" subtype word
# ---------------------------------------------------------------------------


def test_merchant_scroll_is_modeled_and_offers_a_search_for_instants():
    # The colour word ("a **blue** instant card") was consumed and dropped
    # by this pass's own `_SEARCH_COLOR_WORD` widening (documented on
    # `_SEARCH_CRITERIA` in handlers.py at the time) -- a real gap since
    # closed by MEC-12's fifth pass, which wires the captured colour word
    # into `SearchLibraryEffect.criteria["color"]` (`models.card_query`
    # already had the matcher; nothing was populating it). This now proves
    # *both* the type and colour filters reach the search: a red instant no
    # longer matches "a blue instant card", only a genuinely blue one does.
    card = _named("Merchant Scroll")
    assert parse_oracle(card).modeled

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    blue_instant = Card(
        id="Blue I", name="Blue I", type_line="Instant",
        mana_cost_string="{U}", color_identity={"U"},
    )
    red_instant = Card(
        id="Red I", name="Red I", type_line="Instant",
        mana_cost_string="{R}", color_identity={"R"},
    )
    a_land = Card(
        id="A Land", name="A Land", type_line="Basic Land — Island", is_land=True,
    )
    p1.library.append(GameObject(blue_instant, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(red_instant, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(a_land, owner_id="p1", zone=Zone.LIBRARY))
    spell = _to_hand(engine, card, controller="p1")
    _reach_main(engine)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"

    from mtg_analyzer.models import card_query
    matches = [
        o for o in p1.library if card_query.matches(o.card, choice["criteria"])
    ]
    assert {o.card.name for o in matches} == {"Blue I"}


def test_steelshapers_gift_is_modeled():
    assert parse_oracle(_named("Steelshaper's Gift")).modeled


# ---------------------------------------------------------------------------
# card_query power/toughness criteria -- Imperial Recruiter / Recruiter of
# the Guard hand-authored on the new keys
# ---------------------------------------------------------------------------


def test_imperial_recruiter_search_criteria_filters_by_power():
    from mtg_analyzer.models import card_query

    small = Card(id="Small", name="Small", type_line="Creature — Goblin",
                 is_creature=True, power=2, toughness=2)
    big = Card(id="Big", name="Big", type_line="Creature — Giant",
               is_creature=True, power=5, toughness=5)
    criteria = {"type": "Creature", "max_power": 2}
    assert card_query.matches(small, criteria)
    assert not card_query.matches(big, criteria)


def test_recruiter_of_the_guard_search_criteria_filters_by_toughness():
    from mtg_analyzer.models import card_query

    tough_enough = Card(id="T1", name="T1", type_line="Creature — Wall",
                         is_creature=True, power=0, toughness=2)
    too_tough = Card(id="T2", name="T2", type_line="Creature — Wall",
                      is_creature=True, power=0, toughness=5)
    criteria = {"type": "Creature", "max_toughness": 2}
    assert card_query.matches(tough_enough, criteria)
    assert not card_query.matches(too_tough, criteria)


def test_imperial_recruiter_and_recruiter_of_the_guard_are_registered():
    assert is_registered("Imperial Recruiter")
    assert is_registered("Recruiter of the Guard")


# ---------------------------------------------------------------------------
# Wheel of Fortune -- new WheelOfFortuneEffect
# ---------------------------------------------------------------------------


def test_wheel_of_fortune_discards_hands_and_draws_seven():
    assert is_registered("Wheel of Fortune")

    engine, state = _engine()
    _stock_library(state, "p1", 10)
    _stock_library(state, "p2", 10)
    spell = _to_hand(engine, _named("Wheel of Fortune"), controller="p1")
    _to_hand(engine, _vanilla("p2 old card"), controller="p2")
    _reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 2)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()

    p2 = state.player_by_id("p2")
    assert len(p1.hand) == 7
    assert len(p2.hand) == 7
    assert any(o.name == "p2 old card" for o in p2.graveyard)


# ---------------------------------------------------------------------------
# Ruination -- mass destroy's new "nonbasic" filter
# ---------------------------------------------------------------------------


def test_ruination_destroys_only_nonbasic_lands():
    assert is_registered("Ruination")

    engine, state = _engine()
    basic = _bf(state, Card(
        id="Real Forest", name="Real Forest", type_line="Basic Land — Forest",
        is_land=True, oracle_text="{T}: Add {G}.",
    ))
    nonbasic = _bf(state, Card(
        id="Nonbasic", name="Command Tower", type_line="Land", is_land=True,
        oracle_text="{T}: Add one mana of any color in your commander's color identity.",
    ))
    spell = _to_hand(engine, _named("Ruination"), controller="p1")
    _reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("R", 1)
    p1.mana_pool.add("C", 3)

    engine.cast_spell(p1, spell, targets=None)
    engine.resolve_until_stable()

    assert basic in state.battlefield
    assert nonbasic not in state.battlefield
