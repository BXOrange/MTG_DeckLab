"""BUG-33 -- characteristic sums over discarded / sacrificed "this way" pools (RULE 608.2h / 608.2c).

The pools are event-backed: a sacrificed token leaves no object, and a discarded or sacrificed card is a new object
in another zone. The sum therefore reads the last-known power / toughness / mana value the events snapshot.
"""

from __future__ import annotations

from types import SimpleNamespace

from mtg_analyzer.game import effect_amounts
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

PUMP = 3  # temporary +3/+0 on the pumped creature


def _engine():
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Instant", is_instant=True) for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20, starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def _permanent(eng, p1, i, type_line, power=None, toughness=None, cmc=0, **kw):
    card = Card(id=f"c{i}", name=f"Perm {i}", type_line=type_line, power=power, toughness=toughness,
                converted_mana_cost=cmc, **kw)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    eng.state.battlefield.append(obj)
    return obj


def _total(eng, pool, characteristic, source, **kw):
    ctx = GameContext(eng.state, eng.rules)
    return effect_amounts.amount_of(
        {"kind": "this_way_sum", "pool": pool, "characteristic": characteristic, **kw}, ctx, source, None)


def _window():
    return SimpleNamespace(window_event_mark=None)


def test_sacrificed_creatures_sum_lki_power_including_pump_and_token():
    eng, p1 = _engine()
    bear = _permanent(eng, p1, 1, "Creature — Bear", 2, 2, 2, is_creature=True)
    pumped = _permanent(eng, p1, 2, "Creature — Elf", 1, 1, 1, is_creature=True)
    pumped.temp_power = PUMP
    token = _permanent(eng, p1, 3, "Creature — Goblin", 4, 4, 0, is_creature=True)
    token.is_token = True
    treasure = _permanent(eng, p1, 4, "Artifact — Treasure")
    eng.recompute_continuous_effects()
    src = _window()
    src.window_event_mark = len(eng.state.event_log)
    for obj in (bear, pumped, token, treasure):
        eng.rules.put_into_graveyard(obj)
    count = effect_amounts.amount_of({"kind": "this_way_count", "pool": "sacrificed"},
                                     GameContext(eng.state, eng.rules), src, None)
    assert count == 4
    assert _total(eng, "sacrificed", "power", src) == 2 + (1 + PUMP) + 4
    assert _total(eng, "sacrificed", "power", src, card_type="creature") == 2 + (1 + PUMP) + 4
    assert _total(eng, "sacrificed", "power", src, card_type="artifact") == 0
    assert _total(eng, "sacrificed", "toughness", src, card_type="creature") == 2 + 1 + 4
    assert _total(eng, "sacrificed", "mana_value", src, card_type="creature", negate=True) == 0
    assert _total(eng, "sacrificed", "power", src, card_type="creature", negate=True) == 0


def test_sacrificed_sum_ignores_events_before_the_window():
    eng, p1 = _engine()
    early = _permanent(eng, p1, 1, "Creature — Bear", 5, 5, is_creature=True)
    eng.rules.put_into_graveyard(early)
    late = _permanent(eng, p1, 2, "Creature — Bear", 2, 2, is_creature=True)
    src = _window()
    src.window_event_mark = len(eng.state.event_log)
    eng.rules.put_into_graveyard(late)
    assert _total(eng, "sacrificed", "power", src) == 2


def test_discarded_cards_sum_mana_value_unfiltered_and_by_type():
    eng, p1 = _engine()
    cards = [
        GameObject(Card(id="h1", name="Bolt", type_line="Instant", is_instant=True, converted_mana_cost=1),
                   owner_id="p1", zone=Zone.HAND),
        GameObject(Card(id="h2", name="Ogre", type_line="Creature — Ogre", is_creature=True, power=3, toughness=3,
                        converted_mana_cost=4), owner_id="p1", zone=Zone.HAND),
    ]
    for obj in cards:
        obj.controller_id = "p1"
        p1.hand.append(obj)
    src = _window()
    src.window_event_mark = len(eng.state.event_log)
    for obj in cards:
        eng.rules.discard_specific(obj)
    assert _total(eng, "discarded", "mana_value", src) == 5
    assert _total(eng, "discarded", "mana_value", src, card_type="creature") == 4
    assert _total(eng, "discarded", "mana_value", src, card_type="creature", negate=True) == 1
    assert _total(eng, "discarded", "power", src, card_type="creature") == 3


def test_subtype_filter_sums_the_event_snapshot_not_the_graveyard_object():
    eng, p1 = _engine()
    elf = _permanent(eng, p1, 1, "Creature — Elf", 1, 1, is_creature=True)
    elf.temp_power = PUMP
    eng.recompute_continuous_effects()
    src = _window()
    src.window_event_mark = len(eng.state.event_log)
    eng.rules.put_into_graveyard(elf)
    assert _total(eng, "sacrificed", "power", src, subtype="elf") == 1 + PUMP
