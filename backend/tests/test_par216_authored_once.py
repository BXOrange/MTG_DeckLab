"""PAR-216: hand-authored "the next time a source of your choice ..." entries are one-shot (RULE 615.7)."""
from __future__ import annotations

import pytest

from tests.support.deck_batch import RICH, activate, answer, card, filler, game

ONE_SHOT_CARDS = [
    "Circle of Protection: Red", "Circle of Protection: Artifacts", "Rune of Protection: Lands",
    "Rune of Protection: Red", "Righteous Aura", "Invulnerability", "Haazda Shield Mate",
    "Penance", "Pilgrim of Justice", "Martyr's Cause", "Samite Blessing", "Circle of Solace",
]
WHOLE_TURN_CARDS = ["Consulate Surveillance", "Protective Sphere", "Samite Ministration", "Shieldmage Advocate"]


def _flat(spec_dict):
    out = []
    for e in spec_dict.get("effects", []):
        out.append(e)
        out.extend(_flat({"effects": e.get("params", {}).get("grant_effects", [])}))
    return out


def _chosen_source_params(name):
    from mtg_analyzer.game.card_registry.core import specs_for
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
    return [e["params"] for s in specs_for(CardDatabase(DEFAULT_DB_PATH).get_card(name)) for e in _flat(s.to_dict())
            if e["type"] == "request_prevent_damage_source"]


@pytest.mark.parametrize("name", ONE_SHOT_CARDS)
def test_next_time_cards_are_marked_once(name):
    params = _chosen_source_params(name)
    assert params and all(p.get("once") for p in params)


@pytest.mark.parametrize("name", WHOLE_TURN_CARDS)
def test_whole_turn_cards_stay_persistent(name):
    params = _chosen_source_params(name)
    assert params and not any(p.get("once") for p in params)


def test_circle_of_protection_red_prevents_only_the_next_hit():
    eng = game(library=0)
    circle = card(eng, "Circle of Protection: Red")
    src = filler(eng, "Src", player="p2", power=4, toughness=9, color_identity={"R"})
    me = eng.state.player_by_id("p1")
    life = me.life
    me.mana_pool.add_many(RICH)
    activate(eng, circle, 0)
    answer(eng)
    eng.rules.deal_damage(me, 3, source=src)  # the next time: prevented
    eng.rules.deal_damage(me, 2, source=src)  # the shield is spent: this one lands
    assert me.life == life - 2
