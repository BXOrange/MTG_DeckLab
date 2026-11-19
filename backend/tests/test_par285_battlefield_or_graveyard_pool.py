"""PAR-285 class G: a target pool of battlefield creatures and/or creature cards in graveyards (RULE 115.1, 607.2a).

Angel of Serenity, Aurelia's Vindicator and Savior of Ollenbock exile "other target creatures from the battlefield
and/or creature cards from graveyards" and return the exiled cards when they leave. Tests run parser -> binder ->
`legal_targets` -> effect -> return half on the real cards' text with matching and non-matching candidates; the Training
keyword (RULE 702.149a) and its "trains" event, which Savior's trigger needs, are exercised through a real combat."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

CARDS = ["Angel of Serenity", "Aurelia's Vindicator", "Savior of Ollenbock"]
POOL = "creature_or_any_graveyard_creature"


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.state.current_step = "main1"
    return eng


def _creature(name, power=2, toughness=2, zone=Zone.BATTLEFIELD, owner="p1", type_line="Creature — Human"):
    return Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line, power=power,
                toughness=toughness)


def _put(eng, card, owner="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        getattr(eng.state.player_by_id(owner), zone.value).append(obj)
    return obj


def _specs(name, kind):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    return [e for ab in result.specs for e in (ab.effects or []) if e.type == kind]


@pytest.mark.parametrize("name", CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shapes():
    (three,) = match_clause("exile up to 3 other target creatures from the battlefield and/or creature cards from graveyards")
    assert three.params["target_kind"] == POOL and three.params["count"] == 3 and three.params["optional"] is True
    assert three.params["excludes_source"] is True
    (x,) = match_clause("exile up to x other target creatures from the battlefield and/or creature cards from graveyards")
    assert x.params["count_selector"] == "source_x_paid"
    (one,) = match_clause("exile up to 1 other target creature from the battlefield or creature card from a graveyard")
    assert one.params["count"] == 1
    # adversarial: another card type or a different zone pair is not this pool
    assert match_clause("exile up to 3 other target artifacts from the battlefield and/or artifact cards from graveyards") is None
    assert match_clause("exile up to 3 other target creatures from the battlefield and/or creature cards from your graveyard") is None
    assert POOL in ALLOWED_TARGET_KINDS


def test_pool_offers_battlefield_creatures_and_every_graveyard_but_not_the_source():
    eng = _engine()
    angel = _put(eng, _real("Angel of Serenity"))
    mine = _put(eng, _creature("Mine"))
    theirs = _put(eng, _creature("Theirs"), "p2")
    my_card = _put(eng, _creature("Dead Mine"), "p1", Zone.GRAVEYARD)
    their_card = _put(eng, _creature("Dead Theirs"), "p2", Zone.GRAVEYARD)
    _put(eng, Card(id="Rock", name="Rock", type_line="Artifact"), "p1", Zone.GRAVEYARD)
    _put(eng, Card(id="Rock2", name="Rock2", type_line="Artifact"), "p2")
    (exile,) = build_effects(_specs("Angel of Serenity", "exile"), angel)
    offered = {o["instance_id"] for o in legal_targets(eng.state, "p1", exile.target_spec, source=angel)}
    assert offered == {mine.instance_id, theirs.instance_id, my_card.instance_id, their_card.instance_id}
    assert angel.instance_id not in offered  # "other"


def test_angel_exiles_a_mixed_pool_and_returns_every_card_to_its_owner_hand():
    eng = _engine()
    angel = _put(eng, _real("Angel of Serenity"))
    field = _put(eng, _creature("Field"), "p2")
    grave = _put(eng, _creature("Grave"), "p1", Zone.GRAVEYARD)
    stay = _put(eng, _creature("Stay"), "p2")
    exile_effect = build_effects(_specs("Angel of Serenity", "exile"), angel)[0]
    ctx = GameContext(eng.state, eng.rules)
    exile_effect.apply(ctx, [field, grave])
    assert field.zone == Zone.EXILE and grave.zone == Zone.EXILE and stay.zone == Zone.BATTLEFIELD
    (back,) = build_effects(_specs("Angel of Serenity", "return_all_exiled_with"), angel)
    back.apply(GameContext(eng.state, eng.rules), [])
    eng.resolve_until_stable()
    assert field in eng.state.player_by_id("p2").hand
    assert grave in eng.state.player_by_id("p1").hand


def test_savior_returns_the_exiled_cards_to_the_battlefield():
    eng = _engine()
    savior = _put(eng, _real("Savior of Ollenbock"))
    grave = _put(eng, _creature("Grave", type_line="Creature — Elf"), "p2", Zone.GRAVEYARD)
    (exile_effect,) = build_effects(_specs("Savior of Ollenbock", "exile"), savior)
    assert exile_effect.target_spec.count == 1
    exile_effect.apply(GameContext(eng.state, eng.rules), [grave])
    assert grave.zone == Zone.EXILE
    (back,) = build_effects(_specs("Savior of Ollenbock", "return_all_exiled_with"), savior)
    back.apply(GameContext(eng.state, eng.rules), [])
    eng.resolve_until_stable()
    assert grave.zone == Zone.BATTLEFIELD and grave.owner_id == "p2"


def test_aurelia_x_count_is_the_announced_x():
    eng = _engine()
    aurelia = _put(eng, _real("Aurelia's Vindicator"))
    aurelia.x_paid = 2
    for index in range(4):
        _put(eng, _creature(f"Dead{index}"), "p2", Zone.GRAVEYARD)
    (exile_effect,) = build_effects(_specs("Aurelia's Vindicator", "exile"), aurelia)
    assert exile_effect.target_spec.count_selector == "source_x_paid"


# -- Training (RULE 702.149a) and the "trains" event ------------------------------------------------------------


def _to_attackers(eng):
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()


def _train(extra_power):
    eng = _engine()
    savior = _put(eng, _real("Savior of Ollenbock"))
    partner = _put(eng, _creature("Partner", power=extra_power))
    victim = _put(eng, _creature("Victim"), "p2", Zone.GRAVEYARD)
    _to_attackers(eng)
    eng.declare_attackers(eng.state.active_player, [savior, partner])
    eng.advance_step()
    return eng, savior, victim


def savior_power():
    return int(_real("Savior of Ollenbock").power)


def test_training_counter_and_trains_trigger_exile_a_graveyard_creature():
    eng, savior, victim = _train(extra_power=savior_power() + 1)
    steps = 0
    while eng.state.pending_choice is not None and steps < 5:
        eng.resolve_pending_choice(victim.instance_id)
        steps += 1
    eng.resolve_until_stable()
    assert savior.counters.get("+1/+1", 0) == 1  # RULE 702.149a
    assert victim.zone == Zone.EXILE  # "whenever ~ trains" fired (TRAINS) and its pool offered the graveyard card
    # RULE 607.2a: when Savior leaves, the exiled card is put onto the battlefield under its owner's control
    eng.rules.destroy(savior)
    eng.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD


def test_training_needs_an_attacker_with_greater_power():
    eng, savior, victim = _train(extra_power=savior_power())  # equal power is not "greater"
    eng.resolve_until_stable()
    assert savior.counters.get("+1/+1", 0) == 0
    assert eng.state.pending_choice is None and victim.zone == Zone.GRAVEYARD


# -- Aurelia's Vindicator: the {X} of its disguise turn-face-up cost is the trigger's X --------------------------


def _face_down_aurelia(eng):
    obj = GameObject(_real("Aurelia's Vindicator"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.rules.turn_face_down(obj, "disguise")
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_turn_face_up_with_x_pays_x_and_exiles_up_to_x_from_the_pool():
    eng = _engine()
    aurelia = _face_down_aurelia(eng)
    pool = [_put(eng, _creature(f"Dead{i}"), "p2", Zone.GRAVEYARD) for i in range(3)]
    player = eng.state.player_by_id("p1")
    for color, amount in (("W", 1), ("C", 5)):
        player.mana_pool.add(color, amount)  # {X}{3}{W} with X = 2
    (action,) = eng.turn_face_up_actions(player, aurelia)
    assert action["x_cost"] is True
    eng.turn_face_up(player, aurelia, action["option_index"], x=2)
    assert aurelia.face_down is False and aurelia.x_paid == 2
    assert player.mana_pool.total() == 0
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target_multi"
    eng.resolve_pending_choice(pool[0].instance_id)
    eng.resolve_pending_choice(pool[1].instance_id)  # the announced X = 2 caps the picks: no third one is offered
    eng.resolve_until_stable()
    assert [c.zone for c in pool] == [Zone.EXILE, Zone.EXILE, Zone.GRAVEYARD]
    # RULE 607.2a: when Aurelia leaves, both cards return to their owner's hand
    eng.rules.destroy(aurelia)
    eng.resolve_until_stable()
    assert pool[0] in eng.state.player_by_id("p2").hand and pool[1] in eng.state.player_by_id("p2").hand


def test_turn_face_up_x_cannot_exceed_the_mana_available():
    eng = _engine()
    aurelia = _face_down_aurelia(eng)
    player = eng.state.player_by_id("p1")
    player.mana_pool.add("W", 1)
    player.mana_pool.add("C", 3)  # only {3}{W}: X = 0 is payable, X = 1 is not
    with pytest.raises(ValueError):
        eng.turn_face_up(player, aurelia, 0, x=1)
    assert aurelia.face_down is True
