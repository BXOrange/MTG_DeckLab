"""PAR-120 (shared condition vocabulary) — the referent-state and cast-
provenance residue named in `BACKLOG.md`'s own "(b) the other condition
shapes" bullet: "if it was a creature/a Human" (`previous_target`'s RULE
400.7 last-known card type/subtype — Scavenging Ooze/Cling to Dust/Avacyn's
Collar/Weatherseed Totem-shaped) and "if you cast it[ from your hand]"
(`GameObject.was_cast`/`was_cast_from_hand`, the "~ enters, if you cast it,
…" cluster — Coal Stoker/Furnace Dragon/Feasting Troll King/Scion of
Vitu-Ghazi-shaped).

Both route through the same generic ``static_condition`` vocabulary the
RULE 613.6 "as long as" statics and the resolving-effect "if <cond>," wrapper
already share (`parser/oracle/catalogue/static_handlers.py`). "it was a
`<type>`[ card]"/"it was a `<subtype>`" reuse `is_card_type`/`is_subtype` of
`previous_target` unchanged — both read straight off the immutable `Card`
reference (`continuous._has_card_type`/`_has_subtype`), so they answer
correctly even once the referent has already left its original zone (RULE
400.7 doesn't touch printed card type). "you cast it[ from your hand]"
reuses the ``flag`` condition kind against `was_cast` (already whitelisted)
and the newly-whitelisted `was_cast_from_hand` (`GameObject.
was_cast_from_hand`, already stamped by `GameEngine.cast_spell` for an
unrelated counter-amount gate — this is its first boolean-condition route),
both defaulting to ``of: "source"`` since for a self ETB trigger the
trigger's source *is* the entering permanent.

`parser_probe.py diff`: +11, 0 regressed (6 referent-state cards, 4 "cast it"
cards, 1 bonus — Zephyr Sentinel — sharing the "cast it" shape outside the
original search phrase).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

_PREVIOUS_TARGET = "previous_target"


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _spec_source(name, controller="p1", zone=Zone.STACK):
    src = GameObject(_db().get_card(name), owner_id=controller, zone=zone)
    src.controller_id = controller
    bind_from_catalogue(src)
    return src


def _spell_effect_spec(src):
    """The ``spell_effect``/``triggered`` `AbilitySpec` (not a leading
    keyword-line spec, e.g. Cling to Dust's own Escape) that carries the
    effects this test exercises."""
    for spec in parse_oracle(src.card).specs:
        if spec.effects:
            return spec.effects
    raise AssertionError(f"no effect-bearing spec for {src.card.name}")


def _run(eng, src, specs, targets=None):
    effs = build_effects(specs, src)
    _apply_effects_partitioned(effs, eng.rules.context, targets, None, source=src)


# ---------------------------------------------------------------------------
# PARSER: the condition vocabulary itself
# ---------------------------------------------------------------------------


def test_it_was_a_card_type_reads_previous_target():
    assert static_condition("it was a creature card") == {
        "kind": "is_card_type", "of": _PREVIOUS_TARGET, "card_type": "creature",
    }
    assert static_condition("it was a creature") == {
        "kind": "is_card_type", "of": _PREVIOUS_TARGET, "card_type": "creature",
    }
    assert static_condition("it was a land card") == {
        "kind": "is_card_type", "of": _PREVIOUS_TARGET, "card_type": "land",
    }


def test_it_wasnt_a_card_type_negates():
    assert static_condition("it wasn't a creature card") == {
        "kind": "not",
        "condition": {"kind": "is_card_type", "of": _PREVIOUS_TARGET, "card_type": "creature"},
    }


def test_it_was_a_subtype_reads_previous_target():
    assert static_condition("it was a human") == {
        "kind": "is_subtype", "of": _PREVIOUS_TARGET, "subtype": "human",
    }


def test_a_word_outside_either_whitelist_fails_closed():
    assert static_condition("it was a frobnicator") is None


def test_you_cast_it_reads_the_source_flag():
    assert static_condition("you cast it") == {"kind": "flag", "flag": "was_cast"}


def test_you_cast_it_from_your_hand_is_the_stricter_row():
    # Tried before the plainer "you cast it" row so it isn't swallowed by it.
    assert static_condition("you cast it from your hand") == {
        "kind": "flag", "flag": "was_cast_from_hand",
    }


def test_referent_condition_gates_a_resolving_effect():
    # Unlike the `_ITS_CONTROLLER_*` family, the generic "if <cond>," wrapper
    # isn't itself subject-mode-gated (`static_condition` returns a plain
    # dict with no notion of the enclosing trigger's subject mode) — it's
    # correct regardless of `previous_subject`, since a real card only ever
    # reaches this shape after an actual antecedent clause.
    expected = [EffectSpec("gain_life", {"amount": 3}, condition={
        "kind": "is_card_type", "of": _PREVIOUS_TARGET, "card_type": "creature",
    })]
    assert parse_effect_body(
        "if it was a creature card, you gain 3 life", previous_subject=True,
    ) == expected
    assert parse_effect_body("if it was a creature card, you gain 3 life") == expected


def test_cast_provenance_condition_gates_a_self_triggered_effect():
    assert parse_effect_body(
        "if you cast it from your hand, add {r}{r}{r}", self_subject=True,
    ) == [EffectSpec("add_mana", {"colors": ["R", "R", "R"]}, condition={
        "kind": "flag", "flag": "was_cast_from_hand",
    })]


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_referent_state_cards_become_modeled():
    for name in (
        "Avacyn's Collar", "Cling to Dust", "Ethereal Absolution", "Scavenging Ooze",
        "Slayer's Plate", "Weatherseed Totem",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


def test_cast_provenance_cards_become_modeled():
    for name in (
        "Coal Stoker", "Feasting Troll King", "Furnace Dragon", "Scion of Vitu-Ghazi",
        "Zephyr Sentinel",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board
# ---------------------------------------------------------------------------


def _graveyard_card(state, name, types="Creature — Bear", is_creature=True, owner="p2"):
    card = Card(id=name, name=name, type_line=types, is_creature=is_creature,
                power=1 if is_creature else None, toughness=1 if is_creature else None)
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


def test_cling_to_dust_gains_life_off_a_creature_card():
    eng, state, p1, p2 = _engine()
    victim = _graveyard_card(state, "Dead Bear")
    src = _spec_source("Cling to Dust")

    specs = _spell_effect_spec(src)
    life = p1.life
    _run(eng, src, specs, targets=[victim])

    assert p1.life == life + 3
    assert len(p1.hand) == 0  # the "otherwise" branch didn't also fire


def test_cling_to_dust_draws_off_a_noncreature_card():
    eng, state, p1, p2 = _engine()
    p1.library.append(GameObject(
        Card(id="L0", name="L0", type_line="Plains", is_land=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))
    victim = _graveyard_card(state, "Old Plains", types="Land", is_creature=False)
    src = _spec_source("Cling to Dust")

    specs = _spell_effect_spec(src)
    life = p1.life
    _run(eng, src, specs, targets=[victim])

    assert p1.life == life  # the "if" branch stayed closed
    assert len(p1.hand) == 1


def test_coal_stoker_adds_mana_only_when_cast_from_hand():
    eng, state, p1, p2 = _engine()
    src = _spec_source("Coal Stoker", zone=Zone.BATTLEFIELD)
    src.was_cast_from_hand = True
    state.add_to_battlefield(src)

    specs = _spell_effect_spec(src)
    _run(eng, src, specs)

    assert p1.mana_pool.pool["R"] == 3


def test_coal_stoker_adds_no_mana_when_not_cast_from_hand():
    eng, state, p1, p2 = _engine()
    src = _spec_source("Coal Stoker", zone=Zone.BATTLEFIELD)
    src.was_cast_from_hand = False  # e.g. put onto the battlefield, not cast
    state.add_to_battlefield(src)

    specs = _spell_effect_spec(src)
    _run(eng, src, specs)

    assert p1.mana_pool.pool["R"] == 0
