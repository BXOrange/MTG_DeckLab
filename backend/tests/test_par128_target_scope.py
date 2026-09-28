"""PAR-128: the controller scope is a slot of the shared target grammar.

"target `<X>` an opponent controls / you don't control" used to be one
`_TARGET_ROWS` row per type × scope, and each verb carried its own whitelist of
target kinds — so "destroy target creature an opponent controls" failed while
"exile target creature an opponent controls until ~ leaves" worked, only
because one list had been widened and the other hadn't. Now:

* `TARGET` accepts the scope tail after any row and `resolve_target_kind`
  composes it onto the row's kind (`NOT_YOU_TARGET_KINDS`), mirroring
  `targeting.TARGET_FRAMES`' ``SCOPE_NOT_YOU`` over the same type pool.
* `target_kind_allowed` reads a verb's whitelist through `SCOPED_TARGET_BASE`:
  a scoped kind (or a type union) is a narrowing of its base, so a verb that
  takes the base takes it.
* The two-type unions sit above the N-way union row. It matched "X or Y" too,
  so Naturalize's "target artifact or enchantment" offered every permanent.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
    NOT_YOU_TARGET_KINDS,
    SCOPED_TARGET_BASE,
    resolve_target_kind,
    target_kind_allowed,
)
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


# -- grammar ------------------------------------------------------------------


@pytest.mark.parametrize("phrase, kind", [
    ("target creature an opponent controls", "creature_you_dont_control"),
    ("target creature you don't control", "creature_you_dont_control"),
    ("target enchantment you don't control", "enchantment_you_dont_control"),
    ("target artifact or enchantment an opponent controls", "artifact_or_enchantment_you_dont_control"),
    ("target artifact or creature an opponent controls", "artifact_or_creature_you_dont_control"),
    ("target tapped creature an opponent controls", "creature_you_dont_control"),
    # a row that names its own scope still wins
    ("target nonland permanent an opponent controls", "nonland_permanent_you_dont_control"),
])
def test_scope_tail_composes_onto_the_row_kind(phrase, kind):
    assert resolve_target_kind(phrase) == kind


def test_scope_on_a_kind_with_no_scoped_pool_stays_unresolved():
    assert resolve_target_kind("target spell an opponent controls") is None


def test_two_type_unions_are_not_swallowed_by_the_n_way_row():
    assert resolve_target_kind("target artifact or enchantment") == "artifact_or_enchantment"
    assert resolve_target_kind("target artifact or creature") == "artifact_or_creature"
    assert resolve_target_kind("target artifact, enchantment, or land") == "permanent"


def test_scoped_kind_is_allowed_where_its_base_is():
    assert target_kind_allowed("creature_you_dont_control", ("creature",))
    assert target_kind_allowed("artifact_or_enchantment_you_dont_control", ("permanent",))
    assert not target_kind_allowed("creature_you_dont_control", ("artifact",))
    assert not target_kind_allowed(None, ("creature",))


@pytest.mark.parametrize("clause, effect, kind", [
    ("destroy target creature an opponent controls", "destroy", "creature_you_dont_control"),
    ("return target creature an opponent controls to its owner's hand", "return_to_hand",
     "creature_you_dont_control"),
    ("destroy target artifact or enchantment an opponent controls", "destroy",
     "artifact_or_enchantment_you_dont_control"),
    ("put a +1/+1 counter on target creature you don't control", "add_counters",
     "creature_you_dont_control"),
])
def test_verbs_take_the_scoped_target(clause, effect, kind):
    [spec] = match_clause(clause)
    assert spec.type == effect
    assert spec.params["target_kind"] == kind


def test_a_state_qualifier_survives_the_scope_tail():
    """Seal Away: "exile target tapped creature an opponent controls until ~ leaves"."""
    [spec] = match_clause("exile target tapped creature an opponent controls until ~ leaves the battlefield")
    assert spec.params["target_kind"] == "creature_you_dont_control"
    assert spec.params["creature_filter"] == {"tapped": True}


# -- the parser's scope table agrees with the engine's frames -----------------


@pytest.mark.parametrize("base, scoped", sorted(NOT_YOU_TARGET_KINDS.items()))
def test_not_you_kinds_are_real_engine_frames_over_the_same_pool(base, scoped):
    assert scoped in targeting.ALLOWED_TARGET_KINDS
    frame = targeting.TARGET_FRAMES[scoped]
    assert frame.scope in (targeting.SCOPE_NOT_YOU, targeting.SCOPE_NOT_YOU_STRICT)
    base_frame = targeting.TARGET_FRAMES.get(base)
    expected_pool = base_frame.types if base_frame is not None else base
    assert frame.types == expected_pool


def test_every_scoped_base_is_a_real_kind():
    for scoped, base in SCOPED_TARGET_BASE.items():
        assert scoped in targeting.ALLOWED_TARGET_KINDS, scoped
        assert base in targeting.ALLOWED_TARGET_KINDS, base


# -- engine -------------------------------------------------------------------


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    return engine, engine.state


def _bf(state, card, owner):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    return obj


def _board(state):
    made = {}
    for owner in ("p1", "p2"):
        made[(owner, "artifact")] = _bf(state, Card(id=f"a{owner}", name=f"Rock {owner}",
                                                    type_line="Artifact"), owner)
        made[(owner, "enchantment")] = _bf(state, Card(id=f"e{owner}", name=f"Aura {owner}",
                                                       type_line="Enchantment"), owner)
        made[(owner, "creature")] = _bf(state, Card(id=f"c{owner}", name=f"Bear {owner}",
                                                    type_line="Creature — Bear", is_creature=True,
                                                    power=2, toughness=2), owner)
        made[(owner, "land")] = _bf(state, Card(id=f"l{owner}", name=f"Forest {owner}",
                                                type_line="Basic Land — Forest", is_land=True), owner)
    return made


def _offered(state, kind):
    return {d["instance_id"] for d in targeting.legal_targets(state, "p1", targeting.TargetSpec(kind=kind))}


def test_naturalize_offers_only_artifacts_and_enchantments():
    [spec] = parse_effect_body("destroy target artifact or enchantment")
    _, state = _engine()
    made = _board(state)
    offered = _offered(state, spec.params["target_kind"])
    assert offered == {made[(o, t)].instance_id for o in ("p1", "p2") for t in ("artifact", "enchantment")}


def test_gemrazer_scope_offers_only_the_opponents_artifacts_and_enchantments():
    _, state = _engine()
    made = _board(state)
    offered = _offered(state, "artifact_or_enchantment_you_dont_control")
    assert offered == {made[("p2", "artifact")].instance_id, made[("p2", "enchantment")].instance_id}


def test_ravenous_chupacabra_is_modeled_and_scoped():
    card = Card(id="chupa", name="Ravenous Chupacabra", type_line="Creature — Beast Horror",
                is_creature=True, power=2, toughness=2,
                oracle_text="When this creature enters, destroy target creature an opponent controls.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    [ability] = [a for a in result.specs if a.ability_kind == "triggered"]
    assert ability.effects[0].params["target_kind"] == "creature_you_dont_control"


# -- "If <cond>, <A>, then <B>." — one gate over the whole sentence -----------


def test_a_leading_condition_gates_both_halves_of_a_then_sentence():
    """Wistfulness / Canyon Crab / Statute of Denial discarded even when the
    condition was false: the connector split handed ", then <B>" over ungated."""
    specs = parse_effect_body("if you control a token, draw a card, then discard a card")
    assert [s.type for s in specs] == ["draw", "discard"]
    assert specs[0].condition is not None and specs[1].condition == specs[0].condition


def test_a_gated_exile_then_return_it_stays_one_blink():
    """Airbender Ascension: split, "return it" was read as returning the source."""
    [spec] = parse_effect_body(
        "if ~ has 4 or more quest counters on it, exile up to 1 target creature you control, "
        "then return it to the battlefield under its owner's control"
    )
    assert spec.type == "blink"
    assert spec.condition == {"kind": "source_counters", "counter": "quest", "min": 4}


# -- the player-subject slot --------------------------------------------------


def _library(state, owner, n):
    player = state.player_by_id(owner)
    for i in range(n):
        player.library.append(GameObject(Card(id=f"{owner}lib{i}", name=f"Card {i}", type_line="Instant"),
                                         owner_id=owner, zone=Zone.LIBRARY))


@pytest.mark.parametrize("clause, scope", [
    ("each player mills 3 cards", "each_player"),
    ("each opponent gains 10 life", "each_opponent"),
])
def test_each_player_subject_iterates_the_target_player_reading(clause, scope):
    [spec] = parse_effect_body(clause)
    assert spec.type == "for_each"
    assert spec.params["over"] == {"players": scope}
    [inner] = spec.params["effects"]
    assert inner["params"]["target_kind"] == "player"


def test_target_opponent_subject_narrows_the_target():
    [spec] = parse_effect_body("target opponent gains 2 life")
    assert spec.params == {"amount": 2, "target_kind": "opponent"}


def test_a_subject_whose_body_has_another_target_is_refused():
    assert parse_effect_body("each opponent sacrifices target creature") is None


def test_each_player_mills_executes_for_every_player():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, state = _engine()
    for owner in ("p1", "p2"):
        _library(state, owner, 5)
    [spec] = parse_effect_body("each player mills 3 cards")
    source = _bf(state, Card(id="src", name="Src", type_line="Artifact"), "p1")
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()
    assert [len(state.player_by_id(o).graveyard) for o in ("p1", "p2")] == [3, 3]


def test_each_opponent_gains_life_skips_you():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, state = _engine()
    [spec] = parse_effect_body("each opponent gains 10 life")
    source = _bf(state, Card(id="src", name="Src", type_line="Artifact"), "p1")
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()
    assert (state.player_by_id("p1").life, state.player_by_id("p2").life) == (20, 30)


def test_hunted_token_is_created_under_the_target_opponents_control():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, state = _engine()
    [spec] = parse_effect_body("target opponent creates a 4/4 black horror creature token")
    assert spec.params["creators"] == "target" and spec.params["target_kind"] == "opponent"
    source = _bf(state, Card(id="src", name="Src", type_line="Creature — Horror", is_creature=True,
                             power=1, toughness=1), "p1")
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context, targets=[state.player_by_id("p2")])
    horrors = [o for o in state.battlefield if o.name == "Horror"]
    assert [o.controller_id for o in horrors] == ["p2"]
    offered = targeting.legal_targets(state, "p1", targeting.TargetSpec(kind="opponent"), source=source)
    assert {d.get("player_id") for d in offered} == {"p2"}


# -- the "another / other" slot -----------------------------------------------


@pytest.mark.parametrize("phrase, kind", [
    ("another target attacking creature", "creature"),
    ("other target creature you control", "other_creature_you_control"),
    ("another target creature or artifact", "artifact_or_creature"),
    ("another target creature you don't control", "creature_you_dont_control"),
])
def test_another_prefix_composes_onto_the_row_kind(phrase, kind):
    assert resolve_target_kind(phrase) == kind


def test_another_keeps_the_combat_state_filter():
    [spec] = parse_effect_body("another target attacking creature gets +0/+2 until end of turn")
    assert spec.params["target_kind"] == "creature"
    assert spec.params["creature_filter"] == {"attacking": True}


def test_source_excluded_kinds_really_exclude_the_source():
    from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
        OTHER_TARGET_KINDS, SOURCE_EXCLUDED_TARGET_KINDS,
    )

    for kind in SOURCE_EXCLUDED_TARGET_KINDS | set(OTHER_TARGET_KINDS.values()):
        frame = targeting.TARGET_FRAMES.get(kind)
        if frame is None:
            assert kind in ("creature", "permanent"), kind  # the irreducible branches
        else:
            assert frame.exclude_source, kind


def test_another_target_creature_does_not_offer_the_source():
    _, state = _engine()
    source = _bf(state, Card(id="me", name="Me", type_line="Creature — Bear", is_creature=True,
                             power=2, toughness=2), "p1")
    other = _bf(state, Card(id="you", name="You", type_line="Creature — Bear", is_creature=True,
                            power=2, toughness=2), "p1")
    kind = resolve_target_kind("another target creature you control")
    offered = {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=kind), source=source)}
    assert offered == {other.instance_id}
