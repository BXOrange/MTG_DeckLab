"""Blight Curse batch C4 — Wickersmith's Tools (hand-authored,
`ability_catalogue/entries_017.py`).

* "{T}: Add one mana of any color." folds in from `mana_abilities_for`
  (independent of catalogue registration).
* "Whenever one or more -1/-1 counters are put on a creature, put a charge
  counter on this artifact." — the Flourishing Defenses `EventType.COUNTER`
  shape, ``add_counters`` with no target (self).
* "{5}, {T}, Sacrifice this artifact: Create X tapped 2/2 colorless
  Scarecrow artifact creature tokens, where X is the number of charge
  counters on this artifact." — ``create_token`` with the new
  ``count_selector="charge_counters_on_source"`` (`continuous.count_
  selector`), resolved once as the ability resolves.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WICKERSMITHS_TOOLS = Card(
    id="WT", name="Wickersmith's Tools", type_line="Artifact",
    oracle_text="Whenever one or more -1/-1 counters are put on a creature, put a charge "
                "counter on this artifact.\n{T}: Add one mana of any color.\n{5}, {T}, "
                "Sacrifice this artifact: Create X tapped 2/2 colorless Scarecrow artifact "
                "creature tokens, where X is the number of charge counters on this artifact.",
)

_SCARECROW_SPEC = EffectSpec("create_token", {
    "power": 2, "toughness": 2, "colors": [], "subtypes": ["Scarecrow"],
    "token_name": "Scarecrow", "is_artifact": True, "tapped": True,
    "count_selector": "charge_counters_on_source",
})


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def test_authored_with_trigger_and_activated_ability():
    kinds = [s.ability_kind for s in specs_for(WICKERSMITHS_TOOLS)]
    assert "triggered" in kinds and "activated" in kinds


def test_mana_ability_folds_in():
    o = GameObject(WICKERSMITHS_TOOLS, owner_id="p1", zone=Zone.BATTLEFIELD)
    ma = mana_abilities_for(o)
    assert ma and ma[0].options == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def test_charge_counter_accrues_on_minus_counter_placement_then_scarecrow_count():
    eng = _engine()
    st = eng.state
    wt = GameObject(WICKERSMITHS_TOOLS, owner_id="p1", zone=Zone.BATTLEFIELD)
    wt.controller_id = "p1"
    st.add_to_battlefield(wt)
    bind_from_catalogue(wt)

    src = GameObject(Card(id="S", name="Src", type_line="Creature — Rat", is_creature=True,
                          power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    victim = GameObject(Card(id="V", name="V", type_line="Creature — Rat", is_creature=True,
                             power=3, toughness=3), owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    st.add_to_battlefield(src)
    st.add_to_battlefield(victim)
    eng.begin_turn()

    eng.rules.add_counters(victim, 1, "-1/-1", source=src)
    eng.resolve_until_stable()
    eng.rules.add_counters(victim, 1, "-1/-1", source=src)
    eng.resolve_until_stable()
    assert wt.counters.get("charge", 0) == 2

    eff = build_effects([_SCARECROW_SPEC], wt)[0]
    eff.apply(GameContext(eng.state, eng.rules))
    scarecrows = [o for o in st.battlefield if o.name == "Scarecrow"]
    assert len(scarecrows) == 2
    assert all(o.tapped and o.card.is_artifact and o.is_creature for o in scarecrows)


def test_zero_charge_counters_makes_no_tokens():
    eng = _engine()
    wt = GameObject(WICKERSMITHS_TOOLS, owner_id="p1", zone=Zone.BATTLEFIELD)
    wt.controller_id = "p1"
    eng.state.add_to_battlefield(wt)
    bind_from_catalogue(wt)

    eff = build_effects([_SCARECROW_SPEC], wt)[0]
    eff.apply(GameContext(eng.state, eng.rules))
    assert not [o for o in eng.state.battlefield if o.name == "Scarecrow"]
