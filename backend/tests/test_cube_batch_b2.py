"""cEDH staples cube — batch B2: hand-authored `ability_catalogue.py` entries
plus the small set of generic engine primitives this batch found were cheap
enough to build as reusable extensions instead of one-off catalogue entries.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/Reference/
11_CARD_CATALOGUE_AUTHORING_GUIDE.md. This batch's generic (non-card-specific)
additions, each proven here on the *real* card that motivated it:

1. A new activation-cost-reduction primitive (`continuous.
   activation_cost_reduction_for`, `GameEngine._reduced_activation_mana`) —
   unlike a spell's cast cost (`cost_reduction_for`), nothing in the ordinary
   activation-cost path consulted a reduction before this. Power Artifact's
   ``scope="activation"``/``min_total`` params ride the existing
   `cost_reduction` static shape.
2. `effect_binder._group_ok`'s new ``"not_you"`` controller mode (the mirror
   image of the existing ``"you"``) plus a new `TapEffect`
   ``"permanents_you_control"`` selector — Seedborn Muse.
3. `GameEngine.play_land`'s `LAND_PLAYED` event now carries an
   ``instance_id`` and a new `effect_binder._GROUP_CONTROLLER_EVENT_KEYS`
   entry (``"LAND_PLAYED": "player_id"``, also ``"UNTAP": "player_id"``) so
   "whenever you play another land" can scope by controller and exclude the
   land's own play — City of Traitors.
4. `RulesEngine.blink`/`game/effects/core.py`'s `BlinkEffect` — a new RULE 400.7
   "exile then immediately return" primitive (Ephemerate; Rebound stays
   unmodeled, a documented drop).
5. `RulesEngine.put_hand_cards_on_top`/`PutHandCardsOnTopEffect` — "put N
   cards from your hand on top of your library" (Brainstorm).
6. `RulesEngine.shuffle_hand_and_graveyard_into_library`/`WheelEffect` — the
   "each player shuffles their hand and graveyard into their library, then
   draws seven cards" template shared by Timetwister/Time Reversal/Echo of
   Eons (written generically, not Timetwister-specific).
7. `WindfallEffect` — Windfall's own "each player discards their hand, then
   draws cards equal to the greatest number discarded" shape.

Every other card below is a genuinely hand-authored `ability_catalogue.py`
entry, two deliberately *partial* (documented drop of one sub-clause neither
the parser nor the effect library has a primitive for yet — Damn's Overload,
Ephemerate's Rebound) per the file's existing Sword of Forge and
Frontier/Timely Ward precedent.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    """A card bound + added to ``state.battlefield`` (bind-on-load, mirroring
    `services.game_session.build_goldfish_engine`)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _in_hand(state, card: Card, controller: str = "p1") -> GameObject:
    """A card bound + placed straight into ``controller``'s hand (for a
    spell cast directly, bypassing `_engine`'s starting-hand draw)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _engine(p1_cards=(), p2_cards=()) -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_cards)), ("p2", "Bob", list(p2_cards))],
        starting_life=40,
        starting_hand=max(len(p1_cards), len(p2_cards)) or 0,
    )
    for player in eng.state.players:
        for obj in list(player.hand) + list(player.library):
            bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


# ---------------------------------------------------------------------------
# 1. Temur Sabertooth — bespoke "if you do" effect
# ---------------------------------------------------------------------------


def test_temur_sabertooth_registered():
    assert ac.is_registered("Temur Sabertooth")


def test_temur_sabertooth_returns_a_creature_and_gains_indestructible():
    bear = Card(id="TSBear", name="TSBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    saber_obj = _battlefield(state, _card("Temur Sabertooth"), controller="p1")
    bear_obj = _battlefield(state, bear, controller="p1")
    p1.mana_pool.add_many({"G": 1, "C": 1})

    ability = saber_obj.activated_abilities[0]
    idx = saber_obj.activated_abilities.index(ability)
    eng.activate_ability(p1, saber_obj, idx, targets=[bear_obj])
    eng.resolve_until_stable()

    assert bear_obj in p1.hand
    assert "indestructible" in saber_obj.temp_keywords


# ---------------------------------------------------------------------------
# 2. Helm of Awakening — unscoped ``affects="all_spells"`` cost reduction
# ---------------------------------------------------------------------------


def test_helm_of_awakening_registered():
    assert ac.is_registered("Helm of Awakening")


def test_helm_of_awakening_taxes_down_every_players_spells():
    bear = Card(id="HoABear", name="HoABear", type_line="Creature — Bear",
                mana_cost_string="{1}{G}", converted_mana_cost=2,
                is_creature=True, power=2, toughness=2)
    eng = _engine(p1_cards=[bear], p2_cards=[bear])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    _battlefield(state, _card("Helm of Awakening"), controller="p1")

    bear1 = p1.hand[0]
    bear2 = p2.hand[0]
    assert eng.effective_cast_cost(p1, bear1).raw == "{G}"
    # Unscoped — an opponent's spells are discounted too, no self-exemption.
    assert eng.effective_cast_cost(p2, bear2).raw == "{G}"


# ---------------------------------------------------------------------------
# 3. Brainstorm — new `put_hand_cards_on_top` effect
# ---------------------------------------------------------------------------


def test_brainstorm_registered():
    assert ac.is_registered("Brainstorm")


def test_brainstorm_draws_three_then_puts_two_back_on_top():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(10):
        lib_card = Card(id=f"BSLib{i}", name=f"BSLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib_card, owner_id="p1", zone=Zone.LIBRARY))
    library_before = len(p1.library)
    hand_before = len(p1.hand)

    bs_obj = _in_hand(state, _card("Brainstorm"))
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, bs_obj)
    eng.resolve_until_stable()

    # Net: drew 3, put 2 back — hand grows by 1, library shrinks by 1.
    assert len(p1.hand) == hand_before + 1
    assert len(p1.library) == library_before - 1


# ---------------------------------------------------------------------------
# 4. Timetwister — new `wheel` effect (shared "each player" template)
# ---------------------------------------------------------------------------


def test_timetwister_registered():
    assert ac.is_registered("Timetwister")


def test_timetwister_each_player_shuffles_hand_and_graveyard_then_draws_seven():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    gy_objs = {}
    for player in (p1, p2):
        for i in range(15):
            lib_card = Card(id=f"TTLib{player.id}{i}", name=f"TTLib{player.id}{i}",
                             type_line="Creature", is_creature=True)
            player.library.append(GameObject(lib_card, owner_id=player.id, zone=Zone.LIBRARY))
        gy_card = Card(id=f"TTGY{player.id}", name=f"TTGY{player.id}",
                        type_line="Creature", is_creature=True)
        gy_obj = GameObject(gy_card, owner_id=player.id, zone=Zone.GRAVEYARD)
        player.graveyard.append(gy_obj)
        gy_objs[player.id] = gy_obj
        junk = Card(id=f"TTJunk{player.id}", name=f"TTJunk{player.id}", type_line="Land", is_land=True)
        player.hand.append(GameObject(junk, owner_id=player.id, zone=Zone.HAND))

    tt_obj = _in_hand(state, _card("Timetwister"))
    p1.mana_pool.add_many({"U": 1, "C": 2})  # {2}{U}
    eng.cast_spell(p1, tt_obj)
    eng.resolve_until_stable()

    assert len(p1.hand) == 7
    assert len(p2.hand) == 7
    # The pre-existing graveyard cards got shuffled into the library, not
    # left behind (Timetwister itself lands in p1's graveyard only *after*
    # resolving, per the reminder text).
    assert gy_objs["p1"] not in p1.graveyard
    assert gy_objs["p2"] not in p2.graveyard


# ---------------------------------------------------------------------------
# 5. Damn — partial: destroy + can't-be-regenerated (Overload dropped)
# ---------------------------------------------------------------------------


def test_damn_registered():
    assert ac.is_registered("Damn")


def test_damn_destroys_target_creature_even_with_a_regeneration_shield():
    bear = Card(id="DamnBear", name="DamnBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine(p1_cards=[_card("Damn")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    bear_obj = _battlefield(state, bear, controller="p2")
    eng.rules.regenerate(bear_obj)  # an active shield — should NOT save it

    damn_obj = p1.hand[0]
    p1.mana_pool.add_many({"B": 2})
    eng.cast_spell(p1, damn_obj, targets=[bear_obj])
    eng.resolve_until_stable()

    assert bear_obj not in state.battlefield
    assert bear_obj in p2.graveyard


# ---------------------------------------------------------------------------
# 6. Power Artifact — new activation-cost-reduction primitive
# ---------------------------------------------------------------------------


def test_power_artifact_registered():
    assert ac.is_registered("Power Artifact")


def test_power_artifact_reduces_activation_cost_by_two_floored_at_one_mana():
    cheap_artifact = Card(id="ArtCheap", name="ArtCheap", type_line="Artifact",
                           mana_cost_string="{1}", converted_mana_cost=1,
                           oracle_text="{2}: Draw a card.")
    pricey_artifact = Card(id="ArtPricey", name="ArtPricey", type_line="Artifact",
                            mana_cost_string="{3}", converted_mana_cost=3,
                            oracle_text="{4}: Draw a card.")
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    cheap_obj = _battlefield(state, cheap_artifact, controller="p1")
    pricey_obj = _battlefield(state, pricey_artifact, controller="p1")
    power_obj = _battlefield(state, _card("Power Artifact"), controller="p1")
    power_obj.attached_to = pricey_obj.instance_id
    eng.recompute_continuous_effects()
    lib_card = Card(id="PALib", name="PALib", type_line="Creature", is_creature=True)
    p1.library.append(GameObject(lib_card, owner_id="p1", zone=Zone.LIBRARY))

    # Unattached artifact — no reduction at all.
    reduction, floor = continuous.activation_cost_reduction_for(state, cheap_obj)
    assert (reduction, floor) == (0, 0)
    # Attached artifact — {2} off, floored at 1 mana total.
    reduction, floor = continuous.activation_cost_reduction_for(state, pricey_obj)
    assert (reduction, floor) == (2, 1)

    ability = pricey_obj.activated_abilities[0]
    idx = pricey_obj.activated_abilities.index(ability)
    p1.mana_pool.add("C", 2)  # {4} reduced by {2} = {2}, not {0}
    hand_before = len(p1.hand)
    eng.activate_ability(p1, pricey_obj, idx)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_before + 1
    assert p1.mana_pool.total() == 0


# ---------------------------------------------------------------------------
# 7. Seedborn Muse — new "not_you" group-trigger scope + mass-untap selector
# ---------------------------------------------------------------------------


def test_seedborn_muse_registered():
    assert ac.is_registered("Seedborn Muse")


def test_seedborn_muse_untaps_your_permanents_only_during_opponents_untap_step():
    bear = Card(id="MuseBear", name="MuseBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    _battlefield(state, _card("Seedborn Muse"), controller="p1")
    bear_obj = _battlefield(state, bear, controller="p1")
    bear_obj.tapped = True
    opp_bear_obj = _battlefield(state, bear, controller="p2")
    opp_bear_obj.tapped = True

    state.fire_event(GameEvent(EventType.UNTAP, player_id="p2"))
    eng.resolve_until_stable()

    assert bear_obj.tapped is False  # p1's own permanents untapped
    assert opp_bear_obj.tapped is True  # p2's own untap step untaps p2's stuff, not this trigger

    bear_obj.tapped = True
    state.fire_event(GameEvent(EventType.UNTAP, player_id="p1"))
    eng.resolve_until_stable()
    assert bear_obj.tapped is True  # unaffected during Seedborn's own controller's untap step


# ---------------------------------------------------------------------------
# 8. Nether Void — reused counter+unless_pays, any-player SPELL_CAST trigger
# ---------------------------------------------------------------------------


def test_nether_void_registered():
    assert ac.is_registered("Nether Void")


def test_nether_void_counters_a_spell_unless_its_caster_pays_three():
    bolt = Card(id="NVBolt", name="NVBolt", type_line="Instant", mana_cost_string="{R}",
                converted_mana_cost=1, is_instant=True,
                oracle_text="NVBolt deals 2 damage to any target.")
    eng = _engine(p2_cards=[bolt])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    _battlefield(state, _card("Nether Void"), controller="p1")
    bolt_obj = p2.hand[0]
    p2.mana_pool.add("R", 1)

    eng.cast_spell(p2, bolt_obj, targets=[p1])
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    option = next(o for o in choice["options"] if o["instance_id"] == bolt_obj.instance_id)
    eng.rules.resolve_trigger_target_choice(option["id"])
    eng.resolve_until_stable()

    # p2 already spent its only mana casting the bolt, so it genuinely can't
    # pay {3} — `counter_unless_pays` skips the choice and counters outright
    # (RULE 601/`RulesEngine.counter_unless_pays`'s own "nothing to decide"
    # case) rather than opening a further `pending_choice`.
    assert state.pending_choice is None
    assert bolt_obj.zone == Zone.GRAVEYARD
    assert p1.life == 40  # never resolved — countered, not just discarded


# ---------------------------------------------------------------------------
# 9. Spellseeker — generic search grammar (type + max mana value)
# ---------------------------------------------------------------------------


def test_spellseeker_registered():
    assert ac.is_registered("Spellseeker")


def test_spellseeker_etb_searches_for_a_cheap_instant_or_sorcery():
    bolt = Card(id="SSBolt", name="SSBolt", type_line="Instant", mana_cost_string="{R}",
                converted_mana_cost=1, is_instant=True,
                oracle_text="SSBolt deals 2 damage to any target.")
    big_sorc = Card(id="SSBigSorc", name="SSBigSorc", type_line="Sorcery",
                     mana_cost_string="{3}{R}", converted_mana_cost=4, is_sorcery=True,
                     oracle_text="Draw a card.")
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    p1.library.append(GameObject(bolt, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(big_sorc, owner_id="p1", zone=Zone.LIBRARY))

    seeker_obj = _in_hand(state, _card("Spellseeker"))
    p1.mana_pool.add_many({"U": 1, "C": 2})
    eng.cast_spell(p1, seeker_obj)
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice["kind"] == "search"
    names = {e["name"] for e in choice["eligible"]}
    assert "SSBolt" in names  # mana value 1, eligible
    assert "SSBigSorc" not in names  # mana value 4, filtered out
    option = next(e for e in choice["eligible"] if e["name"] == "SSBolt")
    eng.rules.resolve_search_choice(option["instance_id"])
    eng.resolve_until_stable()

    assert any(o.name == "SSBolt" for o in p1.hand)


# ---------------------------------------------------------------------------
# 10. Windfall — new bespoke each-player-discard-then-draw-max effect
# ---------------------------------------------------------------------------


def test_windfall_registered():
    assert ac.is_registered("Windfall")


def test_windfall_each_player_discards_hand_then_draws_the_greatest_count():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    for i in range(3):
        junk = Card(id=f"WFJunk{i}", name=f"WFJunk{i}", type_line="Land", is_land=True)
        p1.hand.append(GameObject(junk, owner_id="p1", zone=Zone.HAND))
    p2_junk = Card(id="WFJunkP2", name="WFJunkP2", type_line="Land", is_land=True)
    p2.hand.append(GameObject(p2_junk, owner_id="p2", zone=Zone.HAND))
    for player in (p1, p2):
        for i in range(10):
            lib_card = Card(id=f"WFLib{player.id}{i}", name=f"WFLib{player.id}{i}",
                             type_line="Creature", is_creature=True)
            player.library.append(GameObject(lib_card, owner_id=player.id, zone=Zone.LIBRARY))

    windfall_obj = _in_hand(state, _card("Windfall"))
    p1.mana_pool.add_many({"U": 1, "C": 2})  # {2}{U}
    eng.cast_spell(p1, windfall_obj)
    eng.resolve_until_stable()

    # p1 had 3 (Windfall itself already left for the stack) → greatest = 3.
    assert len(p1.hand) == 3
    assert len(p2.hand) == 3


# ---------------------------------------------------------------------------
# 11. Ephemerate — new `blink` primitive (Rebound dropped)
# ---------------------------------------------------------------------------


def test_ephemerate_registered():
    assert ac.is_registered("Ephemerate")


def test_ephemerate_blinks_target_creature_you_control():
    bear = Card(id="EphBear", name="EphBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    bear_obj = _battlefield(state, bear, controller="p1")
    bear_obj.counters["+1/+1"] = 3

    eph_obj = _in_hand(state, _card("Ephemerate"))
    p1.mana_pool.add("W", 1)
    eng.cast_spell(p1, eph_obj, targets=[bear_obj])
    eng.resolve_until_stable()

    new_bear = next(o for o in state.battlefield if o.name == "EphBear")
    assert new_bear.controller_id == "p1"
    # RULE 400.7: a new object — counters don't carry over, summoning sick again.
    assert new_bear.counters.get("+1/+1", 0) == 0
    assert new_bear.summoning_sick is True


# ---------------------------------------------------------------------------
# 12. City of Traitors — new LAND_PLAYED "other" trigger scope
# ---------------------------------------------------------------------------


def test_city_of_traitors_registered():
    assert ac.is_registered("City of Traitors")


def test_city_of_traitors_produces_two_colorless_and_sacrifices_on_the_next_land():
    plains = Card(id="COTPlains", name="COTPlains", type_line="Basic Land — Plains", is_land=True)
    eng = _engine(p1_cards=[plains])
    state = eng.state
    p1 = state.active_player
    p1.max_lands_per_turn = 2

    city_obj = _in_hand(state, _card("City of Traitors"))
    eng.play_land(p1, city_obj)
    eng.resolve_until_stable()
    assert city_obj in state.battlefield

    produced = eng.tap_for_mana(p1, city_obj)
    assert produced == {"C": 2}

    plains_obj = p1.hand[0]
    eng.play_land(p1, plains_obj)
    eng.resolve_until_stable()

    assert city_obj not in state.battlefield
    assert city_obj in p1.graveyard
    assert plains_obj in state.battlefield  # the *other* land stays — only City sacrifices itself
