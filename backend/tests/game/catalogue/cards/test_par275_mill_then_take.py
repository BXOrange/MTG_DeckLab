"""PAR-275: "Mill N cards. You may put a <filter> card from among them into your hand." plus First Contact's
first-spell-this-game rider (RULE 601.2). First Contact, Transwarp Hub and Temporal Anomaly on a real engine.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import cast, game, on_battlefield


def _stack_library(player, spec: list[tuple[str, str]]) -> dict[str, GameObject]:
    """``spec`` runs top → bottom as (name, type_line); the library list keeps its top at the end."""
    objs = [GameObject(Card(id=n, name=n, type_line=t, is_land=t == "Land",
                            is_creature="Creature" in t), owner_id=player.id, zone=Zone.LIBRARY) for n, t in spec]
    player.library[:] = list(reversed(objs))
    return {o.card.name: o for o in objs}


def _pick(engine, *names):
    """Answer the open 'from among them' choice one card at a time (the engine asks again until the count is met);
    no names declines."""
    if not names:
        engine.resolve_pending_choice("decline")
        return
    for name in names:
        choice = engine.state.pending_choice
        assert choice is not None, f"no choice left for {name}"
        engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == name))


_FOUR = [("Spell", "Sorcery"), ("Bear", "Creature — Bear"), ("Forest", "Land"), ("Rock", "Artifact"), ("Deep", "Sorcery")]


def test_first_contact_mills_four_and_offers_only_permanent_cards():
    engine, p1, p2 = game("First Contact")
    objs = _stack_library(p1, _FOUR)
    cast(engine, p1, p1.hand[0])
    offered = {o.get("label") for o in engine.state.pending_choice["options"]}
    assert "Spell" not in offered and {"Bear", "Forest", "Rock"} <= offered
    assert objs["Deep"].zone == Zone.LIBRARY  # only four were milled


def test_first_contact_takes_the_pick_into_hand_and_gains_life_as_the_first_spell():
    engine, p1, p2 = game("First Contact")
    objs = _stack_library(p1, _FOUR)
    cast(engine, p1, p1.hand[0])
    _pick(engine, "Bear")
    engine.resolve_until_stable()
    assert objs["Bear"] in p1.hand and objs["Forest"].zone == Zone.GRAVEYARD
    assert p1.life == 22


def test_first_contact_gains_no_life_when_it_is_not_the_first_spell():
    engine, p1, p2 = game("First Contact", "First Contact")
    _stack_library(p1, _FOUR)
    first, second = p1.hand[0], p1.hand[1]
    cast(engine, p1, first)
    _pick(engine, "Bear")
    engine.resolve_until_stable()
    assert p1.life == 22
    _stack_library(p1, _FOUR)
    cast(engine, p1, second)
    _pick(engine)
    engine.resolve_until_stable()
    assert p1.life == 22  # second spell: no rider


def test_first_contact_declining_the_pick_still_gains_life():
    engine, p1, p2 = game("First Contact")
    _stack_library(p1, _FOUR)
    cast(engine, p1, p1.hand[0])
    _pick(engine)
    engine.resolve_until_stable()
    assert p1.life == 22 and not any(o.card.name == "Bear" for o in p1.hand)


def test_transwarp_hub_takes_up_to_two_milled_artifacts():
    engine, p1, p2 = game("Transwarp Hub")
    objs = _stack_library(p1, [("A1", "Artifact"), ("Bear", "Creature — Bear"), ("A2", "Artifact"),
                               ("A3", "Artifact"), ("A4", "Artifact"), ("Deep", "Sorcery")])
    cast(engine, p1, p1.hand[0])
    offered = {o.get("label") for o in engine.state.pending_choice["options"]}
    assert {"A1", "A2", "A3", "A4"} <= offered and not offered & {"Bear", "Deep"}
    _pick(engine, "A1", "A2")
    engine.resolve_until_stable()
    assert objs["A1"] in p1.hand and objs["A2"] in p1.hand
    assert objs["A3"].zone == Zone.GRAVEYARD and objs["Bear"].zone == Zone.GRAVEYARD


def test_temporal_anomaly_mills_offers_a_permanent_and_makes_a_tapped_planet():
    engine, p1, p2 = game()
    anomaly = on_battlefield(engine, "p1", "Temporal Anomaly")
    objs = _stack_library(p1, _FOUR)
    p1.mana_pool.add_many({"C": 3, "G": 1})
    engine.activate_ability(p1, anomaly)
    engine.resolve_until_stable()
    _pick(engine, "Rock")
    engine.resolve_until_stable()
    assert objs["Rock"] in p1.hand and anomaly.zone == Zone.GRAVEYARD
    planet = next(o for o in engine.state.battlefield if o.is_token and o.card.name == "New Planet")
    assert planet.tapped and planet.is_land
