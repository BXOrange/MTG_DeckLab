"""PAR-261: quest-counter Missions -- "Whenever <event>, put a quest counter on ~. <effect>. If ~ has N or more quest
counters on it, <stronger effect> instead / <extra effect>." Conquest, Exploratory, Support and Vengeance Mission.

RULE 608.2c: the instructions are followed in order, so the counter is put first and the threshold is read after it
(the Nth counter already counts). RULE 122.1: a quest counter is a plain named counter with no inherent effect.
Real cached cards on a real `GameEngine`, below and at the threshold.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import cast, game, on_battlefield, vanilla

MISSIONS = ["Conquest Mission", "Exploratory Mission", "Support Mission", "Vengeance Mission"]

#: Each Mission's printed threshold (quest counters on it after the one this trigger puts).
CONQUEST_THRESHOLD = 6
EXPLORATORY_THRESHOLD = 5
SUPPORT_THRESHOLD = 5
VENGEANCE_THRESHOLD = 7


def _quest(mission: GameObject) -> int:
    return mission.counters.get("quest", 0)


def _settle(engine) -> None:
    for _ in range(8):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if not choice:
            return
        options = choice.get("options") or []
        engine.resolve_pending_choice(options[0]["id"] if options else None)


@pytest.mark.parametrize("name", MISSIONS)
def test_real_missions_are_modeled(name):
    card = get_cached_card(name)
    assert card is not None and parse_oracle(card).modeled


def test_threshold_gate_is_per_resolution_after_the_counter():
    # The condition is a resolution-time `if_else` on the source's own quest counters, placed after the put.
    spec = parse_oracle(get_cached_card("Conquest Mission")).specs[0]
    assert [e.type for e in spec.effects] == ["add_counters", "create_token", "if_else"] or [
        e.type for e in spec.effects] == ["add_counters", "if_else"]
    gate = spec.effects[-1].params["condition"]
    assert gate == {"kind": "source_counters", "counter": "quest", "min": CONQUEST_THRESHOLD}


def test_ungated_that_creature_after_a_source_counter_stays_unclaimed():
    # Adversarial: without a gate on the source's own counters, "that creature" after "put a counter on ~" is still
    # read as continuing the source (the exemption is Mission-shaped only), so the line fails closed.
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance
    seg = segment_line("whenever a creature you control enters, put a quest counter on ~. "
                       "put a +1/+1 counter on that creature.", allow_spell_effect=False, provenance=ParserProvenance())
    assert not seg.claimed


def test_conquest_mission_one_token_then_two_at_six():
    eng, p1, _ = game()
    mission = on_battlefield(eng, "p1", "Conquest Mission")
    for before, tokens in ((0, 1), (CONQUEST_THRESHOLD - 1, 2)):
        mission.counters["quest"] = before
        base = sum(1 for o in eng.state.battlefield if o.is_token and o.controller_id == "p1")
        art = GameObject(Card(id="a", name="Trinket", type_line="Artifact"),
                         owner_id="p1", zone=Zone.HAND)
        art.controller_id = "p1"
        p1.hand.append(art)
        eng.cast_spell(p1, art)
        _settle(eng)
        made = sum(1 for o in eng.state.battlefield if o.is_token and o.controller_id == "p1") - base
        assert _quest(mission) == before + 1
        assert made == tokens, (before, made)


def test_support_mission_one_counter_then_two_at_five():
    eng, p1, _ = game()
    mission = on_battlefield(eng, "p1", "Support Mission")
    for before, plus in ((1, 1), (SUPPORT_THRESHOLD - 1, 2)):
        mission.counters["quest"] = before
        bear = GameObject(
            Card(id=f"b{before}", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
            owner_id="p1", zone=Zone.HAND)
        bear.controller_id = "p1"
        p1.hand.append(bear)
        cast(eng, p1, bear)
        _settle(eng)
        assert _quest(mission) == before + 1
        assert bear.counters.get("+1/+1", 0) == plus, (before, bear.counters)
        assert _quest(bear) == 0  # the quest counter went on the Mission, not the creature


def test_vengeance_mission_one_life_then_two_at_seven():
    eng, p1, p2 = game()
    mission = on_battlefield(eng, "p1", "Vengeance Mission")
    for before, loss in ((0, 1), (VENGEANCE_THRESHOLD - 1, 2)):
        mission.counters["quest"] = before
        victim = vanilla(eng, "p2", f"Doomed{before}")
        life = p2.life
        eng.rules.destroy(victim)
        _settle(eng)
        assert _quest(mission) == before + 1
        assert life - p2.life == loss, (before, life, p2.life)


def test_exploratory_mission_extra_mana_only_at_five():
    eng, p1, _ = game()
    mission = on_battlefield(eng, "p1", "Exploratory Mission")
    for before, red in ((0, 0), (EXPLORATORY_THRESHOLD - 1, 2)):
        mission.counters["quest"] = before
        p1.library[:] = [
            GameObject(Card(id=f"hit{before}", name="Hit", type_line="Sorcery", mana_cost={"R": 1}),
                       owner_id="p1", zone=Zone.LIBRARY),
            GameObject(Card(id=f"l{before}", name="Island", type_line="Basic Land — Island", is_land=True),
                       owner_id="p1", zone=Zone.LIBRARY),
        ]
        land = GameObject(Card(id=f"f{before}", name="Forest", type_line="Basic Land — Forest", is_land=True),
                          owner_id="p1", zone=Zone.HAND)
        land.controller_id = "p1"
        p1.hand.append(land)
        p1.mana_pool.empty()
        p1.lands_played_this_turn = 0
        eng.play_land(p1, land)
        _settle(eng)
        assert _quest(mission) == before + 1
        assert p1.mana_pool.to_dict().get("R", 0) == red, (before, p1.mana_pool)
        # The nonland hit stays in exile under this turn's play permission (RULE 601.3 / 305.1).
        hit = next(o for o in p1.exile if o.name == "Hit")
        assert hit.instance_id in eng.state.temp_play_permissions
