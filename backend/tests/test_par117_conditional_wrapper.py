"""PAR-117 (conditional-wrapper residue) — "`<effect>`. if `<predicate>`,
its controller `<verb>` …" (Acolyte Hybrid/Faller's Faithful/Gloomlance/
Ringwraiths/Gloomwidow's Feast/Smashing Success-shaped).

`BACKLOG.md`'s own note on this bullet ("may fall out for free … since the
suffix-if peel already recurses into `parse_effect_body` on the remainder")
turned out to be wrong on re-verification: every one of the five named cards
still failed to parse, each on a genuinely unrecognized *predicate* text
(`segmenter._GENERIC_IF_PREFIX_RE`/`_GENERIC_IF_SUFFIX_RE` already peel the
"if …," shape and already hand the gated remainder back into
`parse_effect_body` with `previous_subject=True` — the referent plumbing
PAR-115/PAR-117 built for the *unconditional* "its controller `<verb>`"
family — but `static_conditions.static_condition` had no row for "that
creature is legendary"/"that creature was `<color>`[ or `<color2>`]"/"that
creature wasn't dealt damage this turn"/"an `<type>` is destroyed this way").

Four new predicates, each reusing an existing engine reading rather than
adding a new one:

* ``is_legendary`` — `GameObject.is_legendary` (printed supertype or a
  granted one), a new `static_conditions.py` kind since neither
  `is_card_type`/`is_subtype` covers a supertype.
* ``was_dealt_damage_this_turn`` — `GameObject.damage_marked` is cleared
  only at RULE 514.2 cleanup, so nonzero marked damage at any other point
  in the same turn already *means* "dealt damage this turn"; no separate
  per-turn tracker needed.
* The colour predicate needed no new kind at all — `is_color` already
  existed — just an OR of it (the `any` combinator, ENG-36) for Gloomlance's
  "green or white", pointed at `previous_target` instead of the default
  `source`.
* "an `<type>` is destroyed this way" reuses the already-shipped RULE 608.2
  resolution tally (`GameContext.permanents_destroyed_this_way`, ENG-37's
  `this_way` amount kind) through the generic `amount_compare` context
  condition, rather than re-reading `previous_target`: a "destroy up to N"
  clause that chose zero targets leaves no referent to filter by card type,
  but the tally already answers "did the destroy actually happen" directly.

`parser_probe.py diff`: +6 (the 4 named cards plus 2 bonus — Gloomwidow's
Feast shares Gloomlance's colour shape, Smashing Success shares Acolyte
Hybrid's "destroyed this way" shape), 0 regressed.

Soul Reap ("its controller loses 3 life if you've cast another black spell
this turn.") now uses the per-colour, per-turn spell count which excludes
the resolving spell's own cast by requiring two casts at resolution.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle, UNMODELED
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
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


def _creature(
    name, power=3, toughness=3, controller="p2", is_legendary=False, color_identity=None,
):
    obj = GameObject(
        Card(
            id=name, name=name, type_line="Creature — Ogre", is_creature=True,
            power=power, toughness=toughness, mana_cost_string="{2}{R}",
            converted_mana_cost=3, is_legendary=is_legendary,
            color_identity=color_identity,
        ),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _artifact(name, controller="p2"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Artifact", is_creature=False,
             mana_cost_string="{2}", converted_mana_cost=2),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = controller
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
# PARSER: the new predicates, gated on previous_subject like the rest of the
# "its controller <verb>" family
# ---------------------------------------------------------------------------


def test_legendary_predicate_gated_on_previous_subject():
    assert parse_effect_body(
        "if that creature is legendary, its controller loses 3 life", previous_subject=True,
    ) == [EffectSpec("lose_life", {
        "amount": 3, "player": _PREVIOUS_TARGET_CONTROLLER,
    }, condition={"kind": "is_legendary", "of": "previous_target"})]
    # No antecedent clause chose anything "that creature" could name.
    assert parse_effect_body("if that creature is legendary, its controller loses 3 life") is None


def test_color_or_predicate_via_any_combinator():
    assert parse_effect_body(
        "if that creature was green or white, its controller discards a card",
        previous_subject=True,
    ) == [EffectSpec("discard", {
        "count": 1, "player": _PREVIOUS_TARGET_CONTROLLER,
    }, condition={
        "kind": "any",
        "conditions": [
            {"kind": "is_color", "color": "G", "of": "previous_target"},
            {"kind": "is_color", "color": "W", "of": "previous_target"},
        ],
    })]


def test_not_dealt_damage_predicate():
    assert parse_effect_body(
        "if that creature wasn't dealt damage this turn, its controller draws 2 cards",
        previous_subject=True,
    ) == [EffectSpec("draw", {
        "count": 2, "player": _PREVIOUS_TARGET_CONTROLLER,
    }, condition={
        "kind": "not",
        "condition": {"kind": "was_dealt_damage_this_turn", "of": "previous_target"},
    })]


def test_destroyed_this_way_predicate():
    assert parse_effect_body(
        "if an artifact is destroyed this way, its controller draws a card",
        previous_subject=True,
    ) == [EffectSpec("draw", {
        "count": 1, "player": _PREVIOUS_TARGET_CONTROLLER,
    }, condition={
        "kind": "amount_compare",
        "left": {"kind": "this_way", "tally": "permanents_destroyed_this_way"},
        "right": {"kind": "fixed", "amount": 1},
        "op": "ge",
    })]


# ---------------------------------------------------------------------------
# PARSER: end-to-end, real cards
# ---------------------------------------------------------------------------


def test_real_cards_become_modeled():
    for name in (
        "Acolyte Hybrid", "Faller's Faithful", "Gloomlance", "Ringwraiths",
        "Gloomwidow's Feast", "Smashing Success",
    ):
        card = _db().get_card(name)
        result = parse_oracle(card)
        assert result.modeled, f"{name}: {result.unclaimed}"


def test_soul_reap_models_the_another_black_spell_count():
    card = _db().get_card("Soul Reap")
    result = parse_oracle(card)
    assert result.modeled
    rider = result.specs[0].effects[1]
    assert rider.condition == {"kind": "another_spell_cast_this_turn", "color": "B"}


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, real board — one positive/negative pair per predicate
# ---------------------------------------------------------------------------


def test_ringwraiths_only_drains_life_off_a_legendary_target():
    eng, state, p1, p2 = _engine()
    legend = _creature("Legend", is_legendary=True)
    state.add_to_battlefield(legend)
    src = _spec_source("Ringwraiths")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[legend])

    assert p2.life == 17  # -3/-3 pump doesn't kill a 3/3 by itself; life lost


def test_ringwraiths_no_life_loss_off_a_nonlegendary_target():
    eng, state, p1, p2 = _engine()
    plain = _creature("Plain Ogre", is_legendary=False)
    state.add_to_battlefield(plain)
    src = _spec_source("Ringwraiths")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[plain])

    assert p2.life == 20  # no legendary referent — the gate stays closed


def test_gloomlance_discards_off_a_green_or_white_target():
    eng, state, p1, p2 = _engine()
    hand_card = GameObject(
        Card(id="c1", name="C1", type_line="Sorcery", is_sorcery=True),
        owner_id="p2", zone=Zone.HAND,
    )
    p2.add_to_zone(hand_card, Zone.HAND)
    victim = _creature("Green Thing", color_identity={"G"})
    state.add_to_battlefield(victim)
    src = _spec_source("Gloomlance")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])
    eng.resolve_until_stable()

    assert victim not in state.battlefield
    assert len(p2.hand) == 0  # discarded the one card it had


def test_gloomlance_no_discard_off_an_off_color_target():
    eng, state, p1, p2 = _engine()
    hand_card = GameObject(
        Card(id="c1", name="C1", type_line="Sorcery", is_sorcery=True),
        owner_id="p2", zone=Zone.HAND,
    )
    p2.add_to_zone(hand_card, Zone.HAND)
    victim = _creature("Red Thing", color_identity={"R"})
    state.add_to_battlefield(victim)
    src = _spec_source("Gloomlance")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])
    eng.resolve_until_stable()

    assert victim not in state.battlefield
    assert len(p2.hand) == 1  # red — the OR gate stays closed, no discard


def test_fallers_faithful_draws_off_an_undamaged_target():
    eng, state, p1, p2 = _engine()
    for i in range(2):
        p2.library.append(GameObject(
            Card(id=f"pl{i}", name=f"L{i}", type_line="Plains", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    victim = _creature("Untouched")
    state.add_to_battlefield(victim)
    src = _spec_source("Faller's Faithful")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])

    assert len(p2.hand) == 2


def test_fallers_faithful_no_draw_off_a_damaged_target():
    eng, state, p1, p2 = _engine()
    victim = _creature("Already Hit")
    victim.damage_marked = 1
    state.add_to_battlefield(victim)
    src = _spec_source("Faller's Faithful")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[victim])

    assert len(p2.hand) == 0  # damaged this turn — the negated gate stays closed


def test_acolyte_hybrid_draws_when_an_artifact_is_actually_destroyed():
    eng, state, p1, p2 = _engine()
    p2.library.append(GameObject(
        Card(id="pl0", name="L0", type_line="Plains", is_land=True),
        owner_id="p2", zone=Zone.LIBRARY,
    ))
    artifact = _artifact("Signet")
    state.add_to_battlefield(artifact)
    src = _spec_source("Acolyte Hybrid")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[artifact])

    assert artifact not in state.battlefield
    assert len(p2.hand) == 1


def test_acolyte_hybrid_no_draw_when_up_to_one_chooses_nothing():
    eng, state, p1, p2 = _engine()
    src = _spec_source("Acolyte Hybrid")

    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[])

    assert len(p2.hand) == 0  # nothing destroyed this way — the gate stays closed
