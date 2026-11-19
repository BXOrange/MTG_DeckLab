"""PAR-288 (P1-F "at random"): "return a [type] card at random from your graveyard to your hand" (RULE 706).

Real cards on a real engine. The pick must come from the engine RNG (no player choice, no pending choice), must only
draw a card of the named type, must leave every other graveyard card alone, and must do nothing when the clause's
own condition (Viconia's four creature cards, Woodland Sleuth's morbid) did not hold or no card matches."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import activate, card, cast, filler, game, put_on_battlefield, step

NEWLY = ["Charmbreaker Devils", "Exalted Flamer of Tzeentch", "Ghoulraiser", "Haunted Fengraf", "Surreal Memoir",
         "Viconia, Drow Apostate", "Woodland Sleuth"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def test_parse_shapes():
    (one,) = match_clause("return a zombie card at random from your graveyard to your hand")
    assert one.params == {"target_kind": "graveyard_zombie_card", "destination": "hand", "at_random": 1}
    (two,) = match_clause("return 2 creature cards at random from your graveyard to the battlefield")
    assert two.params == {"target_kind": "graveyard_creature", "destination": "battlefield", "at_random": 2}
    assert match_clause("return a card at random from an opponent's graveyard to your hand") is None
    assert match_clause("return a card at random from your graveyard to your hand, then reorder your graveyard") is None


def _grave(engine, obj, player="p1"):
    engine.state.battlefield[:] = [o for o in engine.state.battlefield if o is not obj]
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.GRAVEYARD
    p.graveyard.append(obj)
    return obj


def _gy_creature(engine, name, player="p1", type_line="Creature"):
    return _grave(engine, filler(engine, name, type_line=type_line, power=1, toughness=1, player=player), player)


def _hand(engine, player="p1"):
    return [o.name for o in engine.state.player_by_id(player).hand]


def _gy(engine, player="p1"):
    return [o.name for o in engine.state.player_by_id(player).graveyard]


def test_ghoulraiser_returns_a_zombie_only_and_never_asks():
    engine = game()
    _gy_creature(engine, "ZombieA", type_line="Creature — Zombie")
    _gy_creature(engine, "Elf", type_line="Creature — Elf")                    # same-type bystander, wrong subtype
    put_on_battlefield(engine, "Ghoulraiser")
    assert engine.state.pending_choice is None
    assert _hand(engine) == ["ZombieA"] and "Elf" in _gy(engine)


def test_ghoulraiser_without_a_zombie_returns_nothing():
    engine = game()
    _gy_creature(engine, "Elf", type_line="Creature — Elf")
    put_on_battlefield(engine, "Ghoulraiser")
    assert _hand(engine) == [] and _gy(engine) == ["Elf"]


def test_ghoulraiser_ignores_an_opponents_graveyard():
    engine = game()
    _gy_creature(engine, "TheirZombie", player="p2", type_line="Creature — Zombie")
    put_on_battlefield(engine, "Ghoulraiser")
    assert _hand(engine) == [] and _hand(engine, "p2") == []


def test_the_pick_comes_from_the_engine_rng_and_reaches_every_candidate():
    seen = set()
    for seed in range(40):
        engine = game()
        engine.state.rng_seed = seed
        _gy_creature(engine, "ZombieA", type_line="Creature — Zombie")
        _gy_creature(engine, "ZombieB", type_line="Creature — Zombie")
        put_on_battlefield(engine, "Ghoulraiser")
        assert len(_hand(engine)) == 1 and engine.state.pending_choice is None
        seen.add(_hand(engine)[0])
    assert seen == {"ZombieA", "ZombieB"}


def test_the_same_seed_reproduces_the_same_pick():
    picks = []
    for _ in range(2):
        engine = game()
        engine.state.rng_seed = 7
        for i in range(5):
            _gy_creature(engine, f"Zombie{i}", type_line="Creature — Zombie")
        put_on_battlefield(engine, "Ghoulraiser")
        picks.append(_hand(engine))
    assert picks[0] == picks[1]


def test_charmbreaker_devils_upkeep_returns_an_instant_or_sorcery_not_a_creature():
    engine = game()
    card(engine, "Charmbreaker Devils")
    _grave(engine, filler(engine, "Bolt", type_line="Instant"))
    _gy_creature(engine, "Bear")
    step(engine, "upkeep")
    assert _hand(engine) == ["Bolt"] and _gy(engine) == ["Bear"]
    assert engine.state.pending_choice is None


def test_exalted_flamer_returns_a_sorcery_too():
    engine = game()
    card(engine, "Exalted Flamer of Tzeentch")
    _grave(engine, filler(engine, "Ritual", type_line="Sorcery"))
    step(engine, "upkeep")
    assert _hand(engine) == ["Ritual"]


def test_haunted_fengraf_sacrifices_and_returns_a_creature_card():
    engine = game()
    fengraf = card(engine, "Haunted Fengraf")
    _gy_creature(engine, "Bear")
    _grave(engine, filler(engine, "Bolt", type_line="Instant"))
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    activate(engine, fengraf, index=0)
    assert _hand(engine) == ["Bear"] and "Bolt" in _gy(engine)
    assert fengraf.zone == Zone.GRAVEYARD                                       # the sacrifice cost was paid


def test_surreal_memoir_returns_an_instant_only():
    engine = game()
    _grave(engine, filler(engine, "Bolt", type_line="Instant"))
    _grave(engine, filler(engine, "Ritual", type_line="Sorcery"))
    cast(engine, card(engine, "Surreal Memoir", zone=Zone.HAND))
    assert "Bolt" in _hand(engine) and "Ritual" in _gy(engine)


def _viconia(engine, creatures):
    card(engine, "Viconia, Drow Apostate")
    for i in range(creatures):
        _gy_creature(engine, f"Bear{i}")
    _grave(engine, filler(engine, "Bolt", type_line="Instant"))
    step(engine, "upkeep")


def test_viconia_does_nothing_below_four_creature_cards():
    engine = game()
    _viconia(engine, 3)                                                         # an instant does not count
    assert _hand(engine) == []


def test_viconia_returns_a_creature_at_four_creature_cards():
    engine = game()
    _viconia(engine, 4)
    assert len(_hand(engine)) == 1 and _hand(engine)[0].startswith("Bear")


def test_woodland_sleuth_needs_a_creature_to_have_died_this_turn():
    engine = game()
    _gy_creature(engine, "Bear")
    put_on_battlefield(engine, "Woodland Sleuth")
    assert _hand(engine) == []                                                  # morbid not met
    engine2 = game()
    _gy_creature(engine2, "Bear")
    victim = filler(engine2, "Victim", power=1, toughness=1)
    engine2.rules.destroy(victim)
    engine2.resolve_until_stable()
    put_on_battlefield(engine2, "Woodland Sleuth")
    assert len(_hand(engine2)) == 1


# --- the pre-authored / count-two readings the same row now produces ---------------------------------------------------

def test_make_a_wish_returns_two_distinct_cards_at_random_and_leaves_the_rest():
    engine = game()
    for i in range(4):
        _gy_creature(engine, f"Bear{i}")
    cast(engine, card(engine, "Make a Wish", zone=Zone.HAND))
    assert len(_hand(engine)) == 2 and len(set(_hand(engine))) == 2 and all(n.startswith("Bear") for n in _hand(engine))
    assert sorted(n for n in _gy(engine) if n.startswith("Bear")) == sorted(
        n for n in (f"Bear{i}" for i in range(4)) if n not in _hand(engine))  # the other two stay; the spell is not a candidate
    assert engine.state.pending_choice is None


def test_make_a_wish_with_one_card_returns_just_that_card():
    engine = game()
    _gy_creature(engine, "Bear")
    cast(engine, card(engine, "Make a Wish", zone=Zone.HAND))
    assert _hand(engine) == ["Bear"]
