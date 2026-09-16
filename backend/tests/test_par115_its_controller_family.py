"""PAR-115 (`14_` S4 residue): "…. its controller `<verb>` …" as a
connector-split referent, not a new engine primitive.

`segmenter._announces_creature_target` already flips `previous_subject=True`
after a destroy/exile/counter/return/tap clause (built across PAR-18/30/71),
and `EffectHandler.previous_subject_only` already gates a row on that flag —
this ticket only adds the rows themselves, reading the referent through
`game/effect_operands.py`'s ``{"of": "previous_target", "as": "controller"}``
(the same vocabulary `game/card_catalogue/swords_to_plowshares.py`/
`nature_s_claim.py` already spell out by hand for one card each) for
`gain_life`/`lose_life`/`draw`, and `MillEffect`'s own pre-existing
``selector="previous_subject_controller"`` (built for Broken Ambitions,
`test_mec50_clash_win_branches.py`) for `mill`.

Two amount forms beyond a flat number reuse ENG-37's `bind` node exactly the
way `swords_to_plowshares.py` already does by hand: "gains life equal to its
mana value" (Illumination) and "mills cards equal to that creature's power"
(Grisly Spectacle).

The one genuinely new engine surface is `DiscardEffect.player` accepting the
same referent dict `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect` already
read via `GameEffect._operand_player` — `MillEffect` needed no engine change
at all (its own selector already existed), and `GainLifeEffect`/
`LoseLifeEffect`/`DrawCardEffect` needed none either (docstring precedent:
`swords_to_plowshares.py`'s "its controller gains life" already exercises it).

+34 cards on the full ~35k-card cache, 0 regressed (`parser_probe.py diff`),
including two that needed no new grammar at all: Death Bomb (the pre-existing
`_NO_REGEN_SENTENCE_RE` "after" tail already threads `previous_subject`
through) and Zulaport Duelist (`_announces_creature_target`'s generic
`_CREATURE_TARGET_KINDS` scan already covers a `pump` clause's own
`target_kind`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_PREVIOUS_TARGET_CONTROLLER = {"of": "previous_target", "as": "controller"}


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _creature(name, power=3, toughness=3, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Ogre", is_creature=True,
             power=power, toughness=toughness, mana_cost_string="{2}{R}",
             converted_mana_cost=3),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _spec_source(name, controller="p1", zone=Zone.STACK):
    src = GameObject(_db().get_card(name), owner_id=controller, zone=zone)
    src.controller_id = controller
    bind_from_catalogue(src)
    return src


def _run(eng, src, specs, targets=None):
    effs = build_effects(specs, src)
    _apply_effects_partitioned(effs, eng.rules.context, targets, None, source=src)


# ---------------------------------------------------------------------------
# PARSER: the referent is only offered when a preceding clause announced one
# ---------------------------------------------------------------------------


def test_lose_life_gated_on_previous_subject():
    assert match_clause("its controller loses 2 life", previous_subject=True) == [
        EffectSpec("lose_life", {"amount": 2, "player": _PREVIOUS_TARGET_CONTROLLER})
    ]
    # Ungated — no antecedent clause chose anything this pronoun could name —
    # stays unclaimed rather than guessing whose life is lost.
    assert match_clause("its controller loses 2 life") is None


def test_gain_life_gated_on_previous_subject():
    assert match_clause("its controller gains 2 life", previous_subject=True) == [
        EffectSpec("gain_life", {"amount": 2, "player": _PREVIOUS_TARGET_CONTROLLER})
    ]
    assert match_clause("its controller gains 2 life") is None


def test_draws_gated_on_previous_subject():
    assert match_clause("its controller draws a card", previous_subject=True) == [
        EffectSpec("draw", {"count": 1, "player": _PREVIOUS_TARGET_CONTROLLER})
    ]
    assert match_clause("its controller draws 2 cards", previous_subject=True) == [
        EffectSpec("draw", {"count": 2, "player": _PREVIOUS_TARGET_CONTROLLER})
    ]
    assert match_clause("its controller draws a card") is None


def test_discards_gated_on_previous_subject():
    assert match_clause("its controller discards a card", previous_subject=True) == [
        EffectSpec("discard", {"count": 1, "player": _PREVIOUS_TARGET_CONTROLLER})
    ]
    assert match_clause("its controller discards a card") is None


def test_mills_gated_on_previous_subject():
    assert match_clause("its controller mills 4 cards", previous_subject=True) == [
        EffectSpec("mill", {"count": 4, "selector": "previous_subject_controller"})
    ]
    assert match_clause("its controller mills 4 cards") is None


def test_gains_life_equal_to_mana_value_via_bind():
    assert match_clause(
        "its controller gains life equal to its mana value", previous_subject=True,
    ) == [EffectSpec("bind", {
        "name": "mv",
        "amount": {"kind": "characteristic", "characteristic": "mana_value", "of": "previous_target"},
        "effects": [{
            "type": "gain_life",
            "params": {"amount": "$mv", "player": _PREVIOUS_TARGET_CONTROLLER},
        }],
    })]
    assert match_clause("its controller gains life equal to its mana value") is None


def test_mills_equal_to_power_via_bind():
    assert match_clause(
        "its controller mills cards equal to that creature's power", previous_subject=True,
    ) == [EffectSpec("bind", {
        "name": "power",
        "amount": {"kind": "characteristic", "characteristic": "power", "of": "previous_target"},
        "effects": [{
            "type": "mill",
            "params": {"count": "$power", "selector": "previous_subject_controller"},
        }],
    })]
    assert match_clause("its controller mills cards equal to that creature's power") is None


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Assassin's Strike", "Countermand", "Illumination", "Grisly Spectacle",
        "Certain Death", "Death Bomb", "Call to Heel", "Zulaport Duelist",
        "Ajani, Inspiring Leader",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def test_certain_death_hits_the_dead_creatures_controller_and_gains_you_life():
    eng, state, p1, p2 = _engine()
    victim = _creature("Hill Giant")
    state.add_to_battlefield(victim)
    src = _spec_source("Certain Death")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])

    assert victim not in state.battlefield
    assert p2.life == 18   # the dead creature's controller lost 2
    assert p1.life == 22   # the caster gained 2


def test_grisly_spectacle_mills_the_destroyed_creatures_controller_by_its_power():
    eng, state, p1, p2 = _engine()
    for _ in range(5):
        p2.library.append(GameObject(
            Card(id=f"pl{_}", name=f"L{_}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    victim = _creature("Hill Giant", power=4, toughness=3)
    state.add_to_battlefield(victim)
    src = _spec_source("Grisly Spectacle")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])

    assert victim not in state.battlefield
    assert len(p2.graveyard) == 4 + 1  # milled 4, plus the dead creature itself


def test_countermand_mills_the_countered_spells_controller():
    eng, state, p1, p2 = _engine()
    for _ in range(6):
        p2.library.append(GameObject(
            Card(id=f"pl{_}", name=f"L{_}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    spell = GameObject(
        Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
        owner_id="p2", zone=Zone.STACK,
    )
    spell.controller_id = "p2"
    state.stack.append(StackItem(
        kind="spell", controller_id="p2", obj=spell, description="Bolt", effects=[],
    ))
    src = _spec_source("Countermand")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[spell])

    assert spell not in [item.obj for item in state.stack]
    assert len(p2.graveyard) == 4 + 1  # milled 4, plus the countered Bolt


def test_illumination_gains_life_equal_to_the_countered_spells_mana_value():
    eng, state, p1, p2 = _engine()
    spell = GameObject(
        Card(id="wand", name="Wand", type_line="Artifact", converted_mana_cost=5),
        owner_id="p2", zone=Zone.STACK,
    )
    spell.controller_id = "p2"
    state.stack.append(StackItem(
        kind="spell", controller_id="p2", obj=spell, description="Wand", effects=[],
    ))
    src = _spec_source("Illumination")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[spell])

    assert spell not in [item.obj for item in state.stack]
    assert p2.life == 25  # the countered spell's controller gained its mana value


def test_assassins_strike_makes_the_destroyed_creatures_controller_discard():
    eng, state, p1, p2 = _engine()
    hand_card = GameObject(
        Card(id="c1", name="C1", type_line="Sorcery", is_sorcery=True),
        owner_id="p2", zone=Zone.HAND,
    )
    p2.add_to_zone(hand_card, Zone.HAND)
    victim = _creature("Hill Giant")
    state.add_to_battlefield(victim)
    src = _spec_source("Assassin's Strike")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])
    eng.resolve_until_stable()

    assert victim not in state.battlefield
    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 2  # the discarded card, plus the dead creature
