"""BUG-64: a "Cumulative upkeep—<non-mana cost>" line is claimed only when its cost is recorded and payable.

RULE 702.24a/b: at the beginning of your upkeep, put an age counter on the permanent, then sacrifice it unless you
pay its upkeep cost for each age counter on it. The dash cost rides the keyword as text (the Ward/equip idiom) and
`CumulativeUpkeepEffect` multiplies it per counter. Costs the engine cannot pay (a joke, a coin flip, an opponent's
benefit, "Add {R}", a mixed cost) leave the line unclaimed so the card is UNMODELED rather than silently free.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.keywords import cumulative_upkeep_dash_payable
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
from mtg_analyzer.services.game_session import GameSession

#: Age counters on the permanent after the first / second / third upkeep (RULE 702.24b adds one each upkeep).
FIRST_AGE, SECOND_AGE = 1, 2
#: Life paid by Gallowbraid ("Pay 1 life" per age counter) over its first two upkeeps: 1 then 2.
GALLOWBRAID_LIFE_AFTER_TWO_UPKEEPS = 20 - (FIRST_AGE + SECOND_AGE)
STARTING_LIFE = 20
#: Creatures a controller needs on the second upkeep to pay Phyrexian Soulgorger's "Sacrifice a creature" twice.
SOULGORGER_SECOND_UPKEEP_SACRIFICES = 2
#: Aboroth's printed toughness; each age counter costs one -1/-1 counter.
ABOROTH_TOUGHNESS = 9


def real_card(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None, name
    return card


def filler() -> Card:
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", [filler()] * 8), ("p2", "Bob", [filler()] * 8)], starting_hand=0, starting_life=STARTING_LIFE,
    )


def put(eng: GameEngine, name: str, owner: str = "p1") -> GameObject:
    obj = GameObject(real_card(name), owner_id=owner, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def upkeep(target) -> None:
    """Fire p1's upkeep step on a `GameEngine` or a `GameSession` (whose engine is ``target.engine``)."""
    eng = getattr(target, "engine", target)
    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()


def keyword_cost(name: str):
    specs = parse_oracle(real_card(name)).specs
    costs = [s.keyword.get("cost") for s in specs if (s.keyword or {}).get("name") == "cumulative_upkeep"]
    return costs


# -- parser: what is claimed ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, cost",
    [
        ("Gallowbraid", "Pay 1 life"),
        ("Glacial Chasm", "Pay 2 life"),
        ("Phyrexian Soulgorger", "Sacrifice a creature"),
        ("Polar Kraken", "Sacrifice a land"),
        ("Aboroth", "Put a -1/-1 counter on this creature"),
        ("Vexing Sphinx", "Discard a card"),
        ("Arctic Wolves", "{2}"),
    ],
)
def test_payable_dash_cost_is_recorded_and_modeled(name, cost):
    assert keyword_cost(name) == [cost]
    assert parse_oracle(real_card(name)).modeled


@pytest.mark.parametrize(
    "name",
    [
        "Toy Boat",  # joke text
        "Karplusan Minotaur",  # flip a coin
        "Jötun Grunt",  # cards from a single graveyard to the library bottom
        "Sheltering Ancient",  # a counter on an opponent's creature
        "Varchild's War-Riders",  # an opponent creates a token
        "Wall of Shards",  # an opponent gains life
        "Psychic Vortex",  # draw a card
        "Braid of Fire",  # "Add {R}" is mana added, not mana spent
    ],
)
def test_unpayable_dash_cost_is_unmodeled(name):
    assert not parse_oracle(real_card(name)).modeled


def test_payable_grammar_rejects_a_mixed_cost():
    assert not cumulative_upkeep_dash_payable("Pay {B} and 1 life")
    assert cumulative_upkeep_dash_payable("Pay 3 life.")


def test_granted_life_cost_is_modeled():
    # Decomposition grants "Cumulative upkeep—Pay 1 life." to the enchanted creature.
    assert parse_oracle(real_card("Decomposition")).modeled


# -- engine: pay life ------------------------------------------------------------------------------------------------


def test_gallowbraid_pays_one_then_two_life_over_two_upkeeps():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng, "Gallowbraid")
    upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    assert obj.counters["age"] == FIRST_AGE
    eng.resolve_pending_choice("pay")
    assert p1.life == STARTING_LIFE - FIRST_AGE
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert obj.counters["age"] == SECOND_AGE
    assert p1.life == GALLOWBRAID_LIFE_AFTER_TWO_UPKEEPS
    assert obj in eng.state.battlefield


def test_gallowbraid_is_sacrificed_when_declined():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng, "Gallowbraid")
    upkeep(eng)
    eng.resolve_pending_choice("decline")
    assert obj not in eng.state.battlefield
    assert obj in p1.graveyard  # RULE 701.16c: sacrificed, not destroyed
    assert p1.life == STARTING_LIFE


def test_gallowbraid_is_sacrificed_without_a_choice_when_life_is_short():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng, "Gallowbraid")
    obj.counters["age"] = SECOND_AGE  # the next upkeep asks for three life
    p1.life = SECOND_AGE
    upkeep(eng)
    assert eng.state.pending_choice is None
    assert obj not in eng.state.battlefield  # RULE 119.4: cannot pay more life than you have


# -- engine: sacrifice -------------------------------------------------------------------------------------------------


def bear(eng: GameEngine, index: int) -> GameObject:
    card = Card(
        id=f"Bear{index}", name=f"Bear {index}", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def settle_sacrifice_picks(eng: GameEngine, keep: GameObject) -> None:
    """Answer each "which permanent" picker the sacrifice cost opens, never offering up ``keep`` itself."""
    while eng.state.pending_choice is not None:
        options = [o for o in eng.state.pending_choice["options"] if o["id"] != str(keep.instance_id)]
        eng.resolve_pending_choice(options[0]["id"])


def creature_count(eng: GameEngine) -> int:
    return len([o for o in eng.state.battlefield if o.is_creature])


def test_soulgorger_sacrifices_one_then_two_creatures():
    eng = engine()
    soulgorger = put(eng, "Phyrexian Soulgorger")
    bears = [bear(eng, i) for i in range(SOULGORGER_SECOND_UPKEEP_SACRIFICES + FIRST_AGE)]
    total = creature_count(eng)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    settle_sacrifice_picks(eng, soulgorger)
    assert creature_count(eng) == total - FIRST_AGE  # "Sacrifice a creature" once for the first age counter
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    settle_sacrifice_picks(eng, soulgorger)
    assert soulgorger in eng.state.battlefield
    assert soulgorger.counters["age"] == SECOND_AGE
    assert creature_count(eng) == total - FIRST_AGE - SECOND_AGE  # two more for the second
    assert len([b for b in bears if b in eng.state.battlefield]) == 0


def test_soulgorger_is_sacrificed_when_declined():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    soulgorger = put(eng, "Phyrexian Soulgorger")
    upkeep(eng)
    eng.resolve_pending_choice("decline")
    assert soulgorger not in eng.state.battlefield
    assert soulgorger in p1.graveyard


def test_soulgorger_with_too_few_creatures_is_sacrificed_without_a_choice():
    eng = engine()
    soulgorger = put(eng, "Phyrexian Soulgorger")
    soulgorger.counters["age"] = FIRST_AGE  # two creatures are required; only Soulgorger itself is on the board
    upkeep(eng)
    assert eng.state.pending_choice is None
    assert soulgorger not in eng.state.battlefield


# -- engine: counter on itself and discard ----------------------------------------------------------------------------


def test_aboroth_puts_one_minus_counter_per_age_counter():
    eng = engine()
    aboroth = put(eng, "Aboroth")
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert aboroth.counters["age"] == SECOND_AGE
    assert aboroth.counters["-1/-1"] == FIRST_AGE + SECOND_AGE


def test_vexing_sphinx_discards_a_card_per_age_counter():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    sphinx = put(eng, "Vexing Sphinx")
    for _ in range(SECOND_AGE):
        p1.add_to_zone(GameObject(filler(), owner_id="p1", zone=Zone.HAND), Zone.HAND)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    while eng.state.pending_choice is not None:
        eng.resolve_pending_choice(eng.state.pending_choice["options"][0]["id"])
    assert sphinx in eng.state.battlefield
    assert len(p1.hand) == SECOND_AGE - FIRST_AGE


# -- mana cumulative upkeep unchanged ----------------------------------------------------------------------------------


def test_mana_cumulative_upkeep_still_scales():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    obj = put(eng, "Arctic Wolves")
    p1.mana_pool.add("C", 6)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert p1.mana_pool.pool["C"] == 6 - 2 * FIRST_AGE  # {2} per age counter
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert p1.mana_pool.pool["C"] == 6 - 2 * (FIRST_AGE + SECOND_AGE)
    assert obj in eng.state.battlefield


# -- GameSession flow with undo ------------------------------------------------------------------------------------------


def test_session_choice_flow_and_undo():
    eng = engine()
    obj = put(eng, "Gallowbraid")
    session = GameSession(eng)
    p1 = eng.state.player_by_id("p1")
    upkeep(session)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    session.apply_action({"type": "choose", "option_id": "pay"}, "p1")
    assert session.engine.state.player_by_id("p1").life == STARTING_LIFE - FIRST_AGE
    session.rewind(1)  # undo the payment: the choice is open again and no life is lost
    state = session.engine.state
    assert state.player_by_id("p1").life == STARTING_LIFE
    assert state.pending_choice is not None and state.pending_choice["kind"] == "sacrifice_unless_pay"
    session.apply_action({"type": "choose", "option_id": "decline"}, "p1")
    assert not any(o.name == "Gallowbraid" for o in session.engine.state.battlefield)


# -- every other card that stays MODELED ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, life_per_age",
    [("Glacial Chasm", 2), ("Inner Sanctum", 2), ("Morinfen", 1)],
)
def test_life_cost_cards_pay_their_printed_life_per_age_counter(name, life_per_age):
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    put(eng, name)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert p1.life == STARTING_LIFE - life_per_age * FIRST_AGE


def test_polar_kraken_sacrifices_lands_per_age_counter():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    kraken = put(eng, "Polar Kraken")
    lands = [put(eng, "Forest") for _ in range(FIRST_AGE + SECOND_AGE)]
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    settle_sacrifice_picks(eng, kraken)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    settle_sacrifice_picks(eng, kraken)
    assert kraken in eng.state.battlefield
    assert not any(land in eng.state.battlefield for land in lands)
    assert len([o for o in p1.graveyard if o.name == "Forest"]) == len(lands)


def test_decomposition_grants_the_life_upkeep_to_the_enchanted_creature():
    eng = engine()
    p1 = eng.state.player_by_id("p1")
    host = bear(eng, 0)
    aura = put(eng, "Decomposition")
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    eng.resolve_pending_choice("pay")
    assert host.counters["age"] == FIRST_AGE
    assert p1.life == STARTING_LIFE - FIRST_AGE
