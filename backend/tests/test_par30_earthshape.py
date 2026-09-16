"""PAR-30 — Earthshape, the last card of the Earthbend residue cluster.

Hand-authored (`card_registry`): "Earthbend 3. Then each creature you
control with power less than or equal to that land's power gains hexproof and
indestructible until end of turn. You gain hexproof until end of turn."

Two documented simplifications: "that land's power" is modeled as the literal
earthbend amount (3 — a freshly-animated land is 0/0 + three +1/+1 counters =
3/3), carried by `PumpEffect.creature_filter`'s `max_power`, which now also
narrows the effect's `selector`-group branch (not only the targeted one);
"You gain hexproof until end of turn" is dropped (player-level hexproof is
deliberately unmodeled in this engine).
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import is_registered, specs_for
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

_TEXT = (
    "Earthbend 3. Then each creature you control with power less than or equal "
    "to that land's power gains hexproof and indestructible until end of turn. "
    "You gain hexproof until end of turn."
)


def _card():
    return Card(id="ES", name="Earthshape", type_line="Instant", is_instant=True,
                oracle_text=_TEXT)


def test_earthshape_registered_with_earthbend_then_filtered_group_grant():
    assert is_registered("Earthshape")
    specs = specs_for(_card())
    assert len(specs) == 1
    kinds = [e.type for e in specs[0].effects]
    assert kinds == ["earthbend", "pump"]
    pump = specs[0].effects[1].params
    assert pump["selector"] == "creatures_you_control"
    assert pump["creature_filter"] == {"max_power": 3}
    assert set(pump["keywords"]) == {"hexproof", "indestructible"}


def test_earthshape_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state

    def mk(name, p, t, land=False):
        c = Card(id=name, name=name,
                 type_line="Basic Land — Forest" if land else "Creature — Bear",
                 is_land=land, is_creature=not land,
                 power=None if land else p, toughness=None if land else t)
        o = GameObject(c, owner_id="p1", zone=Zone.BATTLEFIELD)
        o.controller_id = "p1"
        st.add_to_battlefield(o)
        return o

    land = mk("Forest", 0, 0, land=True)
    small = mk("Small", 2, 2)
    big = mk("Big", 6, 6)

    src = GameObject(Card(id="ESsrc", name="Earthshape", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    effects = build_effects([e for s in specs_for(_card()) for e in s.effects], src)
    _apply_effects_partitioned(effects, eng.rules.context, [land], None, source=src)
    eng.recompute_continuous_effects()

    # the earthbent land is now a 3/3 creature and is itself protected
    assert land.is_creature and land.is_land and land.power == 3
    assert "hexproof" in land.granted_keywords

    # a small creature you control gains both keywords
    assert "hexproof" in small.granted_keywords
    assert "indestructible" in small.granted_keywords

    # a creature with power above the threshold does not
    assert "hexproof" not in big.granted_keywords
    assert "indestructible" not in big.granted_keywords
