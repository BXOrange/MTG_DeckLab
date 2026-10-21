"""BUG-14: RULE 704.3 -- one state-based-action sweep freezes every applicable action from a single
derived state, applies them all as one event, then repeats.

Before the fix `_sba_pass` stopped at the first check that acted, so a zero-toughness Elesh Norn left
first and the opposing 2/2 that was at zero toughness only because of her -2/-2 survived.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)

NORN = "Elesh Norn, Grand Cenobite"
NORN_TOUGHNESS = 7  # printed toughness: that many -1/-1 counters put her at exactly 0
NORN_DEBUFF = 2  # her -2/-2 to opposing creatures


def _card(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _vanilla(name: str, power: int, toughness: int) -> Card:
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness)


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card: Card, controller: str) -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _norn_at_zero(eng) -> GameObject:
    norn = _put(eng, _card(NORN), "p1")
    norn.add_counters("-1/-1", NORN_TOUGHNESS)
    return norn


def _graveyard_names(eng, pid: str) -> list[str]:
    return [o.name for o in eng.state.player_by_id(pid).graveyard]


def test_elesh_norn_and_opposing_two_two_die_together():
    eng = _engine()
    norn = _norn_at_zero(eng)
    bear = _put(eng, _vanilla("OppBear", 2, 2), "p2")
    eng.recompute_continuous_effects()
    assert norn.toughness == 0 and bear.toughness == 2 - NORN_DEBUFF

    eng.rules.check_state_based_actions()

    assert norn not in eng.state.battlefield
    assert bear not in eng.state.battlefield, "the 2/2 was at 0 toughness in the same frozen state"


def test_single_sweep_applies_both_not_a_second_pass():
    eng = _engine()
    norn = _norn_at_zero(eng)
    bear = _put(eng, _vanilla("OppBear", 2, 2), "p2")
    assert eng.rules._sba_pass() is True
    assert norn not in eng.state.battlefield
    assert bear not in eng.state.battlefield


def test_lethal_damage_and_zero_toughness_in_one_batch():
    # The 3/3 bear is a 1/1 under Norn and carries 1 damage: lethal only while Norn is on the board.
    eng = _engine()
    norn = _norn_at_zero(eng)
    bear = _put(eng, _vanilla("OppBear", 3, 3), "p2")
    bear.damage_marked = 3 - NORN_DEBUFF
    eng.recompute_continuous_effects()

    eng.rules.check_state_based_actions()

    assert norn not in eng.state.battlefield
    assert bear not in eng.state.battlefield


def test_zero_life_player_and_creature_die_in_the_same_pass():
    eng = _engine()
    zero = _put(eng, _vanilla("ZeroZero", 0, 1), "p2")
    zero.add_counters("-1/-1", 1)
    eng.state.player_by_id("p2").life = 0
    eng.recompute_continuous_effects()

    assert eng.rules._sba_pass() is True

    assert eng.state.player_by_id("p2").has_lost
    assert zero not in eng.state.battlefield
    # The simultaneous death still occurs before the owner's objects leave
    # the game; its event remains evidence after RULE 800.4a empties the zone.
    assert any(e.type == EventType.DIES and e.get("instance_id") == zero.instance_id
               for e in eng.state.event_log)
    assert eng.state.player_by_id("p2").graveyard == []


def test_dies_triggers_for_both_creatures_fire_from_the_same_event():
    # Blood Artist and a vanilla creature both hit zero toughness: Blood Artist sees its own death and
    # the other creature's death (RULE 603.10a look-back), whatever order the batch applies them in.
    eng = _engine()
    artist = _put(eng, _card("Blood Artist"), "p1")
    artist.add_counters("-1/-1", 1)
    other = _put(eng, _vanilla("Doomed", 0, 1), "p1")
    other.add_counters("-1/-1", 1)
    life_before = eng.state.player_by_id("p2").life
    eng.recompute_continuous_effects()
    assert artist.toughness == 0 and other.toughness == 0

    eng.rules.check_state_based_actions()

    assert artist not in eng.state.battlefield and other not in eng.state.battlefield
    # The look-back source is the pre-batch snapshot of Blood Artist, so match by name.
    triggers = [i for i in eng.state.stack if getattr(i.source, "name", "") == "Blood Artist"] + [
        a for a, _ in eng.rules.pending_triggers if getattr(a.source, "name", "") == "Blood Artist"
    ]
    assert len(triggers) == 2, f"expected both deaths to trigger Blood Artist, got {len(triggers)}"
    del life_before


def test_legend_rule_runs_in_the_same_batch_as_a_zero_toughness_death():
    eng = _engine()
    legend = Card(id="Lg", name="Lg", type_line="Legendary Creature — Bear", is_creature=True, is_legendary=True,
                  power=2, toughness=2)
    first = _put(eng, legend, "p1")
    second = _put(eng, legend, "p1")
    doomed = _put(eng, _vanilla("Doomed", 0, 1), "p1")
    doomed.add_counters("-1/-1", 1)
    eng.recompute_continuous_effects()

    # BUG-26: the controller picks the surviving legend first; the batch then lands as one.
    assert eng.rules._sba_pass() is True
    assert doomed in eng.state.battlefield and eng.state.pending_choice["kind"] == "legend_rule"
    eng.rules.resolve_choice(str(first.instance_id))
    assert eng.rules._sba_pass() is True

    assert doomed not in eng.state.battlefield
    assert [o for o in eng.state.battlefield if o.name == "Lg"] == [first]
    assert second not in eng.state.battlefield
