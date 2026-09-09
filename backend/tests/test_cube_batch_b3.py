"""cEDH staples cube — batch B3: hand-authored `ability_catalogue.py` entries
plus the reusable engine/parser primitives this batch built along the way.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/Reference/
11_CARD_CATALOGUE_AUTHORING_GUIDE.md. This wave was authored by a subagent
that was cut off (session limit) after writing all 18 catalogue entries and
their supporting effects but *before* writing this test file; these tests were
added afterward to lock the behavior in. This batch's generic (non-card-
specific) additions, each proven here on the real card that motivated it:

1. `destroy_create_token` (`DestroyCreateTokenEffect`) — the destroy sibling
   of B1's `ExileCreateTokenEffect` (Beast Within).
2. A fixed-amount destroy-and-heal (Nature's Claim). Originally the welded
   `destroy_gain_life_to_controller` effect; ENG-37 retired it — the card is
   now a plain `destroy` plus a `gain_life` whose recipient names a referent
   (`effect_operands`).
3. `RulesEngine._substitute_x`'s new `"-x"` sentinel rewriting a `pump`
   effect's `power`/`toughness` for an X-scaled debuff paid as life
   (Toxic Deluge).
4. `EventType.LIBRARY_SEARCHED` now flows through the "group"/`"not_you"`
   trigger scope (Archivist of Oghma).
5. `ExileEffect(remember=True)` + `ReturnLinkedExileEffect` — an O-Ring-shaped
   linked exile/return pair (Leonin Relic-Warder).
6. A `count_selector` reading opponents' artifacts+enchantments feeding
   `CreateTokenEffect` (Dockside Extortionist).
7. `GainControlUntilEndOfTurnEffect` — a temporary control change + untap +
   haste grant on one shared target (Zealous Conscripts / Coercive Recruiter).
8. `draw_limit` static layer — the draw-side mirror of `cast_limit`
   (Spirit of the Labyrinth).
9. `TapEffect.count` for the "untap up to two lands" half via
   `StackItem.target_groups` (Snap).
10. `return_to_hand_draw_if_controlled` (Geistwave), `exile_library` +
    `shuffle_graveyard_into_library` (Paradigm Shift),
    `graveyard_to_library_bottom_random` (Endurance),
    `grant_flash_until_eot` (Borne Upon a Wind).

Two entries are deliberately *partial*, documented drops per the file's Sword
of Forge and Frontier precedent: Coercive Recruiter (drops the "or another
Pirate you control enters" trigger scope and the "becomes a Pirate" type
grant) and Endurance (whose Evoke is covered by MEC-65).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)

ALL_B3_REGISTERED = [
    "Elesh Norn, Grand Cenobite",
    "Paradigm Shift",
    "Spirit of the Labyrinth",
    "Beast Within",
    "Toxic Deluge",
    "Goblin Recruiter",
    "Zealous Conscripts",
    "Endurance",
    "Archivist of Oghma",
    "Leonin Relic-Warder",
    "Borne Upon a Wind",
    "Ponder",
    "Snap",
    "Mirrormade",
    "Geistwave",
    "Coercive Recruiter",
    "Dockside Extortionist",
    "Nature's Claim",
]


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _in_hand(state, card: Card, controller: str = "p1") -> GameObject:
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
# 0. All 18 register (the wave's headline claim)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_B3_REGISTERED)
def test_b3_card_registered(name):
    assert ac.is_registered(name)
    # A registered factory must produce at least one effect-bearing spec.
    specs = ac.specs_for(_card(name))
    assert specs, f"{name} produced no specs"


# ---------------------------------------------------------------------------
# 1. Elesh Norn — two-sided anthem (own +2/+2, opponents' -2/-2)
# ---------------------------------------------------------------------------


def test_elesh_norn_two_sided_anthem():
    bear = Card(id="ENBear", name="ENBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    my_bear = _battlefield(state, bear, controller="p1")
    opp_bear = _battlefield(state, bear, controller="p2")
    _battlefield(state, _card("Elesh Norn, Grand Cenobite"), controller="p1")
    eng.recompute_continuous_effects()

    assert (my_bear.power, my_bear.toughness) == (4, 4)   # +2/+2 to your others
    assert (opp_bear.power, opp_bear.toughness) == (0, 0)  # -2/-2 to opponents'


# ---------------------------------------------------------------------------
# 2. Beast Within — destroy any permanent, its controller gets a 3/3 Beast
# ---------------------------------------------------------------------------


def test_beast_within_destroys_and_gives_controller_a_beast_token():
    victim = Card(id="BWVictim", name="BWVictim", type_line="Enchantment")
    eng = _engine(p1_cards=[_card("Beast Within")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_obj = _battlefield(state, victim, controller="p2")

    bw_obj = p1.hand[0]
    p1.mana_pool.add_many({"G": 1, "C": 2})
    eng.cast_spell(p1, bw_obj, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj not in state.battlefield
    beasts = [o for o in state.permanents_controlled_by("p2")
              if "Beast" in (o.card.type_line or "") or "Beast" in getattr(o, "subtypes", [])]
    assert beasts, "controller of the destroyed permanent should get a Beast token"


# ---------------------------------------------------------------------------
# 3. Nature's Claim — destroy artifact/enchantment, its controller gains 4
# ---------------------------------------------------------------------------


def test_natures_claim_destroys_and_heals_controller():
    art = Card(id="NCArt", name="NCArt", type_line="Artifact",
               mana_cost_string="{2}", converted_mana_cost=2)
    eng = _engine(p1_cards=[_card("Nature's Claim")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    art_obj = _battlefield(state, art, controller="p2")
    life_before = p2.life

    nc_obj = p1.hand[0]
    p1.mana_pool.add("G", 1)
    eng.cast_spell(p1, nc_obj, targets=[art_obj])
    eng.resolve_until_stable()

    assert art_obj not in state.battlefield
    assert p2.life == life_before + 4


# ---------------------------------------------------------------------------
# 4. Toxic Deluge — pay X life, all creatures get -X/-X
# ---------------------------------------------------------------------------


def test_toxic_deluge_shrinks_all_creatures_by_x():
    bear = Card(id="TDBear", name="TDBear", type_line="Creature — Bear",
                is_creature=True, power=3, toughness=3)
    eng = _engine(p1_cards=[_card("Toxic Deluge")])
    state = eng.state
    p1 = state.active_player
    my_bear = _battlefield(state, bear, controller="p1")
    opp_bear = _battlefield(state, bear, controller="p2")
    life_before = p1.life

    td_obj = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 2})  # {2}{B}
    eng.cast_spell(p1, td_obj, x=2)
    eng.resolve_until_stable()

    assert p1.life == life_before - 2  # paid X=2 life
    # -2/-2 to every creature: a 3/3 becomes a 1/1 (state-based death only at 0).
    assert (my_bear.power, my_bear.toughness) == (1, 1)
    assert (opp_bear.power, opp_bear.toughness) == (1, 1)


# ---------------------------------------------------------------------------
# 5. Goblin Recruiter — ETB search for Goblins onto top
# ---------------------------------------------------------------------------


def test_goblin_recruiter_etb_can_find_goblins():
    goblin = Card(id="GRGob", name="GRGob", type_line="Creature — Goblin",
                  is_creature=True, power=1, toughness=1)
    non_goblin = Card(id="GRElf", name="GRElf", type_line="Creature — Elf",
                      is_creature=True, power=1, toughness=1)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    p1.library.append(GameObject(goblin, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(non_goblin, owner_id="p1", zone=Zone.LIBRARY))

    recruiter_obj = _in_hand(state, _card("Goblin Recruiter"))
    p1.mana_pool.add_many({"R": 1, "C": 1})
    eng.cast_spell(p1, recruiter_obj)
    eng.resolve_until_stable()

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    names = {e["name"] for e in choice["eligible"]}
    assert "GRGob" in names
    assert "GRElf" not in names


# ---------------------------------------------------------------------------
# 6. Archivist of Oghma — triggers on an OPPONENT's library search
# ---------------------------------------------------------------------------


def test_archivist_of_oghma_triggers_on_opponent_search_only():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(5):
        lib = Card(id=f"AoOLib{i}", name=f"AoOLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    _battlefield(state, _card("Archivist of Oghma"), controller="p1")
    life_before, hand_before = p1.life, len(p1.hand)

    # An opponent (p2) searches — should trigger p1's gain-life-and-draw.
    state.fire_event(GameEvent(EventType.LIBRARY_SEARCHED, player_id="p2"))
    eng.resolve_until_stable()
    assert p1.life == life_before + 1
    assert len(p1.hand) == hand_before + 1

    # Its own controller searching should NOT trigger it.
    life_mid, hand_mid = p1.life, len(p1.hand)
    state.fire_event(GameEvent(EventType.LIBRARY_SEARCHED, player_id="p1"))
    eng.resolve_until_stable()
    assert p1.life == life_mid
    assert len(p1.hand) == hand_mid


# ---------------------------------------------------------------------------
# 7. Leonin Relic-Warder — linked exile on ETB, return on leave
# ---------------------------------------------------------------------------


def test_leonin_relic_warder_exiles_then_returns_on_leaving():
    art = Card(id="LRWArt", name="LRWArt", type_line="Artifact",
               mana_cost_string="{2}", converted_mana_cost=2)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    warder_obj = _battlefield(state, _card("Leonin Relic-Warder"), controller="p1")
    art_obj = _battlefield(state, art, controller="p2")

    # Fire the ETB trigger and take the exile (optional "you may").
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=warder_obj.instance_id, player_id="p1"))
    eng.resolve_until_stable()
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "trigger_target":
        # Choose to exile the artifact.
        opt = next((o for o in choice.get("options", [])
                    if o.get("instance_id") == art_obj.instance_id), None)
        eng.rules.resolve_choice(opt["id"] if opt else "do")
        eng.resolve_until_stable()

    assert art_obj.zone == Zone.EXILE

    # Now the Warder leaves — the exiled card returns.
    eng.rules.destroy(warder_obj)
    eng.resolve_until_stable()
    assert art_obj.zone == Zone.BATTLEFIELD


# ---------------------------------------------------------------------------
# 8. Dockside Extortionist — X Treasures = opponents' artifacts+enchantments
# ---------------------------------------------------------------------------


def test_dockside_makes_treasures_for_opponents_nonland_permanents():
    art = Card(id="DEArt", name="DEArt", type_line="Artifact",
               mana_cost_string="{1}", converted_mana_cost=1)
    ench = Card(id="DEEnch", name="DEEnch", type_line="Enchantment")
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    _battlefield(state, art, controller="p2")
    _battlefield(state, ench, controller="p2")

    dockside_obj = _in_hand(state, _card("Dockside Extortionist"))
    p1.mana_pool.add_many({"R": 1, "C": 1})  # {1}{R}
    eng.cast_spell(p1, dockside_obj)
    eng.resolve_until_stable()

    treasures = [o for o in state.permanents_controlled_by("p1")
                 if "Treasure" in (o.card.type_line or "")
                 or "Treasure" in getattr(o, "subtypes", [])
                 or (o.card.name == "Treasure")]
    assert len(treasures) == 2  # one per opponent artifact/enchantment


# ---------------------------------------------------------------------------
# 9. Zealous Conscripts — gain control until end of turn (+ untap + haste)
# ---------------------------------------------------------------------------


def test_zealous_conscripts_steals_a_permanent_until_end_of_turn():
    bear = Card(id="ZCBear", name="ZCBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    conscripts_obj = _battlefield(state, _card("Zealous Conscripts"), controller="p1")
    victim = _battlefield(state, bear, controller="p2")
    victim.tapped = True

    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=conscripts_obj.instance_id, player_id="p1"))
    eng.resolve_until_stable()
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "trigger_target":
        opt = next((o for o in choice.get("options", [])
                    if o.get("instance_id") == victim.instance_id), None)
        eng.rules.resolve_choice(opt["id"] if opt else "do")
        eng.resolve_until_stable()

    assert victim.controller_id == "p1"
    assert victim.tapped is False          # untapped by the effect
    assert "haste" in victim.temp_keywords  # granted haste


# ---------------------------------------------------------------------------
# 10. Spirit of the Labyrinth — each player capped at one draw per turn
# ---------------------------------------------------------------------------


def test_spirit_of_the_labyrinth_caps_draws_at_one_per_turn():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(10):
        lib = Card(id=f"SoLLib{i}", name=f"SoLLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    _battlefield(state, _card("Spirit of the Labyrinth"), controller="p1")
    eng.recompute_continuous_effects()

    hand_before = len(p1.hand)
    eng.rules.draw(p1, 3)
    # Only the first draw is allowed this turn.
    assert len(p1.hand) == hand_before + 1


# ---------------------------------------------------------------------------
# 11. Snap — bounce a creature + untap up to two lands (two target groups)
# ---------------------------------------------------------------------------


def test_snap_bounces_a_creature_and_untaps_two_lands():
    bear = Card(id="SnapBear", name="SnapBear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    land = Card(id="SnapLand", name="SnapLand", type_line="Land", is_land=True)
    eng = _engine(p1_cards=[_card("Snap")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim = _battlefield(state, bear, controller="p2")
    l1 = _battlefield(state, land, controller="p1"); l1.tapped = True
    l2 = _battlefield(state, land, controller="p1"); l2.tapped = True

    snap_obj = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 1})  # {1}{U}
    eng.cast_spell(p1, snap_obj,
                   target_groups=[[victim], [l1, l2]])
    eng.resolve_until_stable()

    assert victim.zone == Zone.HAND
    assert l1.tapped is False and l2.tapped is False


# ---------------------------------------------------------------------------
# 12. Ponder — scry 3 then draw a card
# ---------------------------------------------------------------------------


def test_ponder_draws_a_card():
    """RULE 608.2: the scry is *finished* — including the player's own
    choice — before the draw happens. The draw parks behind the pending
    choice and resumes when it is answered; this test originally asserted
    the draw straight after `resolve_until_stable()` and so could only ever
    have passed if the two ran out of order (ENG-38).
    """
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(5):
        lib = Card(id=f"PLib{i}", name=f"PLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))

    ponder_obj = _in_hand(state, _card("Ponder"))
    hand_before = len(p1.hand) - 1  # minus Ponder itself, which leaves for the stack
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, ponder_obj)
    eng.resolve_until_stable()

    # The scry stops the resolution and the draw has *not* happened yet.
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "scry"
    assert len(p1.hand) == hand_before

    # "Put them back in any order": the scry runs two phases — which cards
    # go away, then how the kept ones are ordered. Decline both.
    for phase in ("away", "order"):
        assert state.pending_choice["phase"] == phase
        eng.rules.resolve_choice("decline")
        eng.resolve_until_stable()

    assert state.pending_choice is None
    assert len(p1.hand) == hand_before + 1


# ---------------------------------------------------------------------------
# 13. Geistwave — bounce nonland permanent, draw if you controlled it
# ---------------------------------------------------------------------------


def test_geistwave_draws_when_bouncing_your_own_permanent():
    art = Card(id="GWArt", name="GWArt", type_line="Artifact",
               mana_cost_string="{1}", converted_mana_cost=1)
    eng = _engine(p1_cards=[_card("Geistwave")])
    state = eng.state
    p1 = state.active_player
    for i in range(5):
        lib = Card(id=f"GWLib{i}", name=f"GWLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    own_art = _battlefield(state, art, controller="p1")

    gw_obj = p1.hand[0]
    hand_before = len(p1.hand) - 1  # minus Geistwave itself
    p1.mana_pool.add_many({"U": 1, "C": 1})  # {1}{U}
    eng.cast_spell(p1, gw_obj, targets=[own_art])
    eng.resolve_until_stable()

    assert own_art.zone == Zone.HAND
    # Bounced your own permanent → +1 card from the draw (net vs. pre-cast hand,
    # the returned artifact also enters hand, so expect +2 over hand_before).
    assert len(p1.hand) == hand_before + 2


def test_geistwave_no_draw_when_bouncing_an_opponents_permanent():
    art = Card(id="GWArt2", name="GWArt2", type_line="Artifact",
               mana_cost_string="{1}", converted_mana_cost=1)
    eng = _engine(p1_cards=[_card("Geistwave")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    for i in range(5):
        lib = Card(id=f"GWLibB{i}", name=f"GWLibB{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    opp_art = _battlefield(state, art, controller="p2")

    gw_obj = p1.hand[0]
    hand_before = len(p1.hand) - 1
    p1.mana_pool.add_many({"U": 1, "C": 1})  # {1}{U}
    eng.cast_spell(p1, gw_obj, targets=[opp_art])
    eng.resolve_until_stable()

    assert opp_art.zone == Zone.HAND
    assert opp_art in p2.hand
    # No draw (didn't control it), and the bounced card went to p2's hand.
    assert len(p1.hand) == hand_before


# ---------------------------------------------------------------------------
# 14. Paradigm Shift — exile library, shuffle graveyard in
# ---------------------------------------------------------------------------


def test_paradigm_shift_exiles_library_and_shuffles_graveyard_in():
    eng = _engine(p1_cards=[_card("Paradigm Shift")])
    state = eng.state
    p1 = state.active_player
    for i in range(6):
        lib = Card(id=f"PSLib{i}", name=f"PSLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    for i in range(4):
        gy = Card(id=f"PSGy{i}", name=f"PSGy{i}", type_line="Creature", is_creature=True)
        p1.graveyard.append(GameObject(gy, owner_id="p1", zone=Zone.GRAVEYARD))

    ps_obj = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 2})
    eng.cast_spell(p1, ps_obj)
    eng.resolve_until_stable()

    # The 6 original library cards are exiled; the 4 graveyard cards become the
    # new library. Paradigm Shift itself lands in the graveyard only *after*
    # resolving (it's a sorcery), so the graveyard holds exactly it and none of
    # the 4 pre-existing cards.
    gy_names = {o.name for o in p1.graveyard}
    assert not any(n.startswith("PSGy") for n in gy_names)
    assert "Paradigm Shift" in gy_names
    assert len(p1.library) == 4
    assert len(p1.exile) >= 6


# ---------------------------------------------------------------------------
# 15. Endurance — up to one player's graveyard to bottom of library
# ---------------------------------------------------------------------------


def test_endurance_puts_a_graveyard_on_the_bottom_of_library():
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(3):
        gy = Card(id=f"EndGy{i}", name=f"EndGy{i}", type_line="Creature", is_creature=True)
        p1.graveyard.append(GameObject(gy, owner_id="p1", zone=Zone.GRAVEYARD))
    lib_before = len(p1.library)

    endurance_obj = _battlefield(state, _card("Endurance"), controller="p1")
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=endurance_obj.instance_id, player_id="p1"))
    eng.resolve_until_stable()
    choice = state.pending_choice
    if choice is not None and choice.get("kind") == "trigger_target":
        opt = next((o for o in choice.get("options", [])
                    if o.get("player_id") == "p1" or o.get("id") == "p1"), None)
        eng.rules.resolve_choice(opt["id"] if opt else "do")
        eng.resolve_until_stable()

    assert len(p1.graveyard) == 0
    assert len(p1.library) == lib_before + 3


# ---------------------------------------------------------------------------
# 16. Borne Upon a Wind — grants flash this turn + draws
# ---------------------------------------------------------------------------


def test_borne_upon_a_wind_grants_flash_and_draws():
    sorcery_creature = Card(id="BUWCreature", name="BUWCreature",
                            type_line="Creature — Bear", is_creature=True,
                            power=2, toughness=2, mana_cost_string="{1}",
                            converted_mana_cost=1)
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    for i in range(3):
        lib = Card(id=f"BUWLib{i}", name=f"BUWLib{i}", type_line="Creature", is_creature=True)
        p1.library.append(GameObject(lib, owner_id="p1", zone=Zone.LIBRARY))
    creature_obj = _in_hand(state, sorcery_creature)

    buw_obj = _in_hand(state, _card("Borne Upon a Wind"))
    hand_before = len(p1.hand) - 1  # minus BUW itself, which leaves for the stack
    p1.mana_pool.add_many({"U": 1, "C": 1})  # {1}{U}
    eng.cast_spell(p1, buw_obj)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_before + 1  # drew a card

    # Now move to a step where a creature normally couldn't be cast (not a
    # main phase) — the flash-granting flag from Borne Upon a Wind should let
    # it be cast at instant speed anyway. Give p1 the mana for it so `can_cast`
    # isn't blocked on affordability rather than timing.
    state.current_step = "upkeep"
    p1.mana_pool.add("C", 1)  # the creature costs {1}
    assert eng.can_cast(p1, creature_obj) is True


# ---------------------------------------------------------------------------
# 17. Mirrormade — enters as a copy of an artifact/enchantment
# ---------------------------------------------------------------------------


def test_mirrormade_enters_as_a_copy():
    specs = ac.specs_for(_card("Mirrormade"))
    assert any(s.ability_kind == "enter_replacement" for s in specs)
    kinds = [e.type for s in specs for e in s.effects]
    assert "enter_as_copy" in kinds


# ---------------------------------------------------------------------------
# 18. Coercive Recruiter — same gain-control effect (partial model documented)
# ---------------------------------------------------------------------------


def test_coercive_recruiter_binds_the_gain_control_trigger():
    obj = GameObject(_card("Coercive Recruiter"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert len(obj.triggered_abilities) == 1
