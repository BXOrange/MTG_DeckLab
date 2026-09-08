"""Secrets of Strixhaven — playability batch, wave 52 (PAR-60).

Creative Technique — ``shuffle`` + the generalized ``dig_until`` cascade dig
("reveal from the top until a nonland card, free-cast the hit, rest to the
bottom in a random order").
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def test_creative_technique_registered_and_binds():
    assert is_registered("Creative Technique")
    specs = _REGISTRY["creative technique"]()
    assert len(specs) == 1
    eff_types = [e.type for e in specs[0].effects]
    assert eff_types == ["shuffle", "dig_until"]
    dig = specs[0].effects[1]
    assert dig.params["criteria"] == {"without_type": "land"}
    assert dig.params["hit_destination"] == "cast_free_window"
    assert dig.params["rest_destination"] == "library_bottom_random"
    src = GameObject(card=Card(id="ct", name="Creative Technique", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_creative_technique_digs_to_nonland_and_grants_free_cast():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    for nm, tl in [("Forest", "Basic Land — Forest"), ("Island", "Basic Land — Island"),
                   ("Lightning Bolt", "Instant"), ("Mountain", "Basic Land — Mountain"),
                   ("Plains", "Basic Land — Plains")]:
        p1.library.append(GameObject(card=Card(id=nm[:3] + str(len(p1.library)), name=nm,
                                              type_line=tl),
                                     owner_id=p1.id, zone=Zone.LIBRARY))
    p1.library.reverse()  # Forest, Island now on top

    src = GameObject(card=Card(id="ct", name="Creative Technique", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    for spec in _REGISTRY["creative technique"]():
        bound = bind_ability(spec, src)
        for e in (bound if isinstance(bound, list) else [bound]):
            e.source = src
            e.apply(eng.rules.context)
    eng.resolve_until_stable()

    exiled = [o for o in p1.exile]
    assert [o.name for o in exiled] == ["Lightning Bolt"]
    assert len(p1.library) == 4  # the two lands went back to the bottom
    # A free-cast window was granted on the exiled nonland card.
    assert exiled[0].instance_id in eng.state.temp_play_permissions
