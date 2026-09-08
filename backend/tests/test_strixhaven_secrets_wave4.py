"""Secrets of Strixhaven — playability batch, wave 4.

Wave 4: Quandrix {X} hydras whose only gap was a "dies, do X equal to its
power" trigger body.
- `DrawCardEffect.amount_from_subject` — "draw cards equal to its power".
- `CreateTokenEffect.count_from_subject` — "create a number of tapped
  Treasure tokens equal to its power".
Both read `_characteristic_of_subject` (DIES → RULE 400.7 snapshot).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, GameEvent  # noqa: F401
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_lifeblood_and_goldvein_hydra_modeled():
    for name in ("Lifeblood Hydra", "Goldvein Hydra"):
        r = parse_oracle(_db().get_card(name))
        assert r.coverage != UNMODELED, (name, r.unclaimed)


def test_lifeblood_hydra_dies_body_specs():
    r = parse_oracle(_db().get_card("Lifeblood Hydra"))
    spec = [s for s in r.specs if s.trigger and s.trigger["event"] == "DIES"][0]
    types = {(e.type, e.params.get("amount_from_subject")) for e in spec.effects}
    assert types == {("gain_life", "trigger_subject_power"), ("draw", "trigger_subject_power")}


def test_goldvein_hydra_dies_body_specs():
    r = parse_oracle(_db().get_card("Goldvein Hydra"))
    spec = [s for s in r.specs if s.trigger and s.trigger["event"] == "DIES"][0]
    e = spec.effects[0]
    assert e.type == "create_token"
    assert e.params.get("token_name") == "Treasure"
    assert e.params.get("count_from_subject") == "trigger_subject_power"
    assert e.params.get("tapped") is True


def _dies_ctx(eng, source, power):
    ctx = eng.rules.context
    ctx.trigger_event = GameEvent(
        EventType.DIES, instance_id=source.instance_id, power=power, toughness=power,
    )
    return ctx


def test_draw_amount_from_subject_reads_dies_snapshot():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"c{i}", name=f"Card{i}", type_line="Instant",
                                          is_instant=True), owner_id=p1.id, zone=Zone.LIBRARY))
    src = GameObject(Card(id="h", name="Hydra", type_line="Creature — Hydra",
                          is_creature=True, power=1, toughness=1),
                     owner_id=p1.id, zone=Zone.GRAVEYARD)
    eff = EffectRegistry.create("draw", {"amount_from_subject": "trigger_subject_power"})
    eff.source = src
    eff.apply(_dies_ctx(eng, src, power=4))
    assert len(p1.hand) == 4


def test_create_token_count_from_subject_reads_dies_snapshot():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(Card(id="h", name="Hydra", type_line="Creature — Hydra",
                          is_creature=True, power=1, toughness=1),
                     owner_id=p1.id, zone=Zone.GRAVEYARD)
    eff = EffectRegistry.create(
        "create_token", {"token_name": "Treasure", "tapped": True,
                         "count_from_subject": "trigger_subject_power"}
    )
    eff.source = src
    eff.apply(_dies_ctx(eng, src, power=3))
    treasures = [o for o in eng.state.battlefield
                 if getattr(o, "is_token", False) and "Treasure" in (o.name or "")]
    assert len(treasures) == 3
    assert all(o.tapped for o in treasures)


def test_lifeblood_hydra_end_to_end_dies_trigger():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    for i in range(6):
        p1.library.append(GameObject(Card(id=f"l{i}", name=f"L{i}", type_line="Forest",
                                          is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))
    hydra = GameObject(_db().get_card("Lifeblood Hydra"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    hydra.summoning_sick = False
    eng.state.add_to_battlefield(hydra)
    bind_from_catalogue(hydra)
    hydra.counters["+1/+1"] = 4  # X=4
    eng.recompute_continuous_effects()

    trig = [t for t in hydra.triggered_abilities if t.trigger_event == "DIES"][0]
    ctx = eng.rules.context
    ctx.trigger_event = GameEvent(EventType.DIES, instance_id=hydra.instance_id,
                                  power=4, toughness=4)
    for eff in trig.effects:
        eff.source = hydra
        eff.apply(ctx)
    assert p1.life == 24
    assert len(p1.hand) == 4
