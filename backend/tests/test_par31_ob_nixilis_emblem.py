"""PAR-31 — Ob Nixilis of the Black Oath's −8 emblem: an emblem carrying an
*activated* ability whose X scales off the sacrifice cost.

"{1}{B}, Sacrifice a creature: You gain X life and draw X cards, where X is
the sacrificed creature's power." — `_gain_life_and_draw_sac_power`
(`handlers.py`) emits `gain_life` + `draw` both reading
`continuous.count_selector`'s ``"sacrificed_cost_power"`` (Altar of
Dementia's idiom — stamped on the ability source when the "sacrifice a
creature" cost is paid). First real emblem with an activated ability
(`models/emblem.py`'s `activated_abilities`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


_EMBLEM_TEXT = (
    'You get an emblem with "{1}{B}, Sacrifice a creature: You gain X life '
    'and draw X cards, where X is the sacrificed creature\'s power."'
)


def test_ob_nixilis_emblem_parses():
    c = Card(id="obn", name="Ob Nixilis of the Black Oath",
             type_line="Legendary Planeswalker — Ob Nixilis",
             oracle_text=(
                 "+2: Each opponent loses 1 life. You gain life equal to the "
                 "life lost this way.\n"
                 "−2: Create a 5/5 black Demon creature token with flying. You "
                 "lose 2 life.\n"
                 "−8: " + _EMBLEM_TEXT + "\n"
                 "Ob Nixilis of the Black Oath can be your commander."))
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    inner = next(e for s in r.specs for e in s.effects
                 if e.type == "create_emblem").params["ability"]
    assert inner["ability_kind"] == "activated"
    assert [e["type"] for e in inner["effects"]] == ["gain_life", "draw"]
    assert inner["effects"][0]["params"]["count_selector"] == "sacrificed_cost_power"
    assert inner["effects"][1]["params"]["amount_from_count_selector"] == "sacrificed_cost_power"


def test_ob_nixilis_emblem_activated_ability_scales_off_the_sacrifice():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")

    src = Card(id="obult", name="Ob Nixilis Ult", type_line="Sorcery",
               is_sorcery=True, mana_cost_string="{1}{B}", converted_mana_cost=2,
               oracle_text=_EMBLEM_TEXT)
    r = parse_oracle(src)
    assert r.modeled, r.unclaimed
    o = GameObject(src, owner_id="p1", zone=Zone.HAND)
    attach_to_object(o, r.specs)
    p1.hand.append(o)
    p1.mana_pool.add_many({"B": 9})
    st.active_player_index = st.players.index(p1)
    st.current_step = "main1"
    eng.cast_spell(p1, o)
    eng.resolve_until_stable()
    assert len(p1.emblems) == 1
    emblem = p1.emblems[0]
    assert len(emblem.activated_abilities) == 1

    for i in range(5):
        p1.library.append(GameObject(
            Card(id=f"lib{i}", name=f"L{i}", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.LIBRARY))
    victim = GameObject(
        Card(id="v", name="Big Beast", type_line="Creature — Beast",
             is_creature=True, power=4, toughness=4),
        owner_id="p1", zone=Zone.BATTLEFIELD)
    victim.summoning_sick = False
    st.add_to_battlefield(victim)

    life0, hand0 = p1.life, len(p1.hand)
    eng.activate_ability(p1, emblem, 0, sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()

    assert p1.life - life0 == 4          # gained X = 4 (sacrificed power)
    assert len(p1.hand) - hand0 == 4     # drew X = 4
    assert victim in p1.graveyard
