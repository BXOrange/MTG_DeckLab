"""PAR-40 — the RULE 115/601.2c creature-quality target filter extended to
*damage*.

New `damage_creature_filter` handler (`_DAMAGE_CREATURE_FILTER_RE` +
`_damage_creature_filter`), registered before the plain `damage` row, reusing
`_CREATURE_FILTER_SUFFIX`/`_creature_quality_filter` — the same
power/toughness/keyword filter `destroy_creature_filter` /
`exile_creature_filter` already emit. `DealDamageEffect` gained a
`creature_filter` param threaded into its `TargetSpec`; `TargetSpec.
creature_filter` + `targeting` were already wired into `legal_targets`.

Real cards: Leaf Arrow / Pierce the Sky / Shredding Winds / Collision //
Colossus / Centaur Archer / Grapeshot Catapult / Skyway Sniper (+ the modal
"deals N damage to target creature with flying; or destroy target artifact"
family — Thunderbolt / Tangletrap / Shredded Sails).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, pid="p2", keywords=None, power=2, toughness=2):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bird",
             is_creature=True, power=power, toughness=toughness,
             keywords=list(keywords or [])),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def _stack_src(state, pid="p1"):
    src = GameObject(Card(id="src", name="Src", type_line="Instant", is_instant=True),
                     owner_id=pid, zone=Zone.STACK)
    src.controller_id = pid
    return src


# --- parse -----------------------------------------------------------------


def test_damage_with_flying_filter_parses():
    assert match_clause("~ deals 3 damage to target creature with flying") == [
        EffectSpec("damage", {
            "amount": 3, "target_kind": "creature",
            "creature_filter": {"keyword": "flying"},
        })
    ]


def test_damage_with_power_filter_parses():
    assert match_clause("~ deals 2 damage to target creature with power 4 or greater") == [
        EffectSpec("damage", {
            "amount": 2, "target_kind": "creature",
            "creature_filter": {"min_power": 4},
        })
    ]


def test_bare_damage_to_target_creature_still_plain():
    # No filter → the plain `damage` handler still owns it, no creature_filter key.
    assert match_clause("~ deals 2 damage to target creature") == [
        EffectSpec("damage", {"amount": 2, "target_kind": "creature"})
    ]


def test_unknown_filter_word_fails_closed():
    assert match_clause("~ deals 2 damage to target creature with shadow") is None


def test_real_cards_modeled():
    for name, text in [
        ("Leaf Arrow", "Leaf Arrow deals 3 damage to target creature with flying."),
        ("Pierce the Sky", "Pierce the Sky deals 7 damage to target creature with flying."),
        ("Thunderbolt",
         "Choose one —\n• Thunderbolt deals 3 damage to target player or planeswalker.\n"
         "• Thunderbolt deals 4 damage to target creature with flying."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Instant", is_instant=True,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_only_flyers_are_legal_targets():
    eng, state = _engine()
    src = _stack_src(state)
    flyer = _creature(state, "Cloud Sprite", keywords=["flying"])
    ground = _creature(state, "Grizzly Bear")
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("damage", {
        "amount": 3, "target_kind": "creature", "creature_filter": {"keyword": "flying"},
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert flyer.instance_id in offered
    assert ground.instance_id not in offered


def test_damage_resolves_on_a_flyer():
    eng, state = _engine()
    src = _stack_src(state)
    flyer = _creature(state, "Wind Drake", keywords=["flying"], toughness=3)
    eng.recompute_continuous_effects()

    build_effects([EffectSpec("damage", {
        "amount": 3, "target_kind": "creature", "creature_filter": {"keyword": "flying"},
    })], src)[0].apply(GameContext(state, eng.rules), [flyer])
    eng.rules.check_state_based_actions()

    # 3 damage to a 2/3 flyer → lethal, it's gone (RULE 704.5g).
    assert flyer not in state.battlefield


def test_power_filter_offers_only_big_creatures():
    eng, state = _engine()
    src = _stack_src(state)
    big = _creature(state, "Hill Giant", power=5, toughness=5)
    small = _creature(state, "Goblin", power=1, toughness=1)
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("damage", {
        "amount": 4, "target_kind": "creature", "creature_filter": {"min_power": 4},
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert big.instance_id in offered
    assert small.instance_id not in offered
