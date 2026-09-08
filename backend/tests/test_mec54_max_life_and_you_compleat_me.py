"""MEC-54 — "your maximum life total is N." — and its only driver,
You Compleat Me (PAR-31's last emblem card, hand-authored in
`ability_catalogue`).

- A permanent player-scoped cap on `Player.player_effects`
  (`RulesEngine._max_life_total` / `set_max_life_total`), honoured at
  `gain_life`'s single choke point: a gain raises the total only up to N.
- `SetLifeEffect(only_reduce=True)` — "if greater than N, it becomes N".
- One emblem carrying two quoted abilities via `CreateEmblemEffect.abilities`
  / `RulesEngine.create_emblem`'s list branch — the first emblem with a
  `pay_life` mana ability.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


_YCM_TEXT = (
    "If your life total is greater than 10, it becomes 10. For the rest of "
    "the game, your maximum life total is 10. You get an emblem with \"Pay 2 "
    "life: Add one mana of any color\" and \"At the beginning of your upkeep, "
    "you draw a card and you lose 1 life.\""
)


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _cast_ycm(eng):
    st = eng.state
    p1 = st.player_by_id("p1")
    c = Card(id="ycm", name="You Compleat Me", type_line="Sorcery",
             is_sorcery=True, mana_cost_string="{2}{B}", converted_mana_cost=3,
             oracle_text=_YCM_TEXT)
    specs = specs_for(c)
    assert specs, "You Compleat Me must be hand-authored in the catalogue"
    o = GameObject(c, owner_id="p1", zone=Zone.HAND)
    attach_to_object(o, specs)
    p1.hand.append(o)
    p1.mana_pool.add_many({"B": 5})
    st.active_player_index = st.players.index(p1)
    st.current_step = "main1"
    eng.cast_spell(p1, o)
    eng.resolve_until_stable()
    return p1


# --- MEC-54 primitive ------------------------------------------------


def test_max_life_total_caps_life_gain_at_choke_point():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    eng.rules.lose_life(p1, 15)          # 20 -> 5
    eng.rules.set_max_life_total(p1, 10)
    eng.rules.gain_life(p1, 3)           # 5 -> 8 (under the cap, full)
    assert p1.life == 8
    eng.rules.gain_life(p1, 9)           # would be 17, capped to 10
    assert p1.life == 10
    eng.rules.gain_life(p1, 4)           # already at cap, nothing
    assert p1.life == 10


def test_set_max_life_total_clamps_a_currently_higher_total():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")     # 20
    eng.rules.set_max_life_total(p1, 10)
    assert p1.life == 10


# --- You Compleat Me end to end ------------------------------------


def test_you_compleat_me_sets_life_to_ten_and_makes_one_emblem():
    eng = _engine()
    p1 = _cast_ycm(eng)
    assert p1.life == 10
    assert len(p1.emblems) == 1
    emblem = p1.emblems[0]
    assert len(emblem.activated_abilities) == 1
    assert len(emblem.triggered_abilities) == 1


def test_you_compleat_me_life_stays_capped_after_resolution():
    eng = _engine()
    p1 = _cast_ycm(eng)
    eng.rules.gain_life(p1, 20)
    assert p1.life == 10                  # cap holds post-resolution
    eng.rules.lose_life(p1, 6)
    eng.rules.gain_life(p1, 100)
    assert p1.life == 10


def test_you_compleat_me_below_ten_is_not_raised():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    eng.rules.lose_life(p1, 15)           # 20 -> 5, before the spell
    _cast_ycm(eng)
    assert p1.life == 5                   # only_reduce: never raised to 10


def test_you_compleat_me_emblem_upkeep_trigger_fires():
    eng = _engine()
    p1 = _cast_ycm(eng)
    for i in range(3):
        p1.library.append(GameObject(
            Card(id=f"l{i}", name=f"L{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    hand0, life0 = len(p1.hand), p1.life
    eng.state.active_player_index = eng.state.players.index(p1)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="BEGINNING"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()
    assert len(p1.hand) == hand0 + 1
    assert p1.life == life0 - 1
