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


# -- "another" on a graveyard card --------------------------------------------


@pytest.mark.parametrize("clause, kind, dest, extra", [
    ("return another target artifact card from your graveyard to your hand",
     "graveyard_artifact", "hand", {}),
    ("return another target creature card with mana value 3 or less from your graveyard to the battlefield",
     "graveyard_creature", "battlefield", {"max_mana_value": 3}),
    ("return up to 1 other target creature card from your graveyard to the battlefield",
     "graveyard_creature", "battlefield", {"optional": True}),
])
def test_another_graveyard_target_is_the_plain_graveyard_kind(clause, kind, dest, extra):
    [spec] = match_clause(clause)
    assert spec.type == "return_from_graveyard"
    assert spec.params == {"target_kind": kind, "destination": dest, **extra}


def test_another_still_refuses_a_shape_the_row_does_not_claim():
    assert match_clause("return another card from your graveyard to your hand") is None


def test_another_graveyard_target_does_not_offer_the_source():
    """Junk Diver's dies trigger: the source is in the graveyard when it targets."""
    _, state = _engine()
    diver = GameObject(Card(id="jd", name="Junk Diver", type_line="Artifact Creature — Bird",
                            is_creature=True), owner_id="p1", zone=Zone.GRAVEYARD)
    rock = GameObject(Card(id="rk", name="Rock", type_line="Artifact"),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    state.player_by_id("p1").graveyard.extend([diver, rock])
    [spec] = match_clause("return another target artifact card from your graveyard to your hand")
    offered = {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=spec.params["target_kind"]), source=diver)}
    assert offered == {rock.instance_id}


@pytest.mark.parametrize("name, oracle", [
    ("Junk Diver", "Flying\nWhen this creature dies, return another target artifact card from your graveyard to your hand."),
    ("Deadwood Treefolk", "When this creature enters or leaves the battlefield, return another target creature card from your graveyard to your hand."),
])
def test_real_cards_with_a_graveyard_another_are_modeled(name, oracle):
    card = Card(id=name, name=name, type_line="Artifact Creature — Bird", is_creature=True,
                power=1, toughness=1, oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# -- "other" on a group selector ----------------------------------------------


def _run(engine, state, clause, source):
    from mtg_analyzer.game.effects.core import EffectRegistry

    [spec] = parse_effect_body(clause)
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()


def _bear(state, name, owner, power=2, toughness=5):
    return _bf(state, Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                           power=power, toughness=toughness), owner)


def test_all_other_creatures_pump_skips_the_source():
    engine, state = _engine()
    me, mine, theirs = _bear(state, "me", "p1"), _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    _run(engine, state, "all other creatures get -2/-2 until end of turn", me)
    assert (me.power, mine.power, theirs.power) == (2, 0, 0)


def test_other_attacking_creatures_pump_needs_attacking_and_skips_the_source():
    engine, state = _engine()
    me, ally, idle = _bear(state, "me", "p1"), _bear(state, "ally", "p1"), _bear(state, "idle", "p1")
    for o in (me, ally):
        o.attacking = True
    _run(engine, state, "other attacking creatures get +1/+0 until end of turn", me)
    assert (me.power, ally.power, idle.power) == (2, 3, 2)


def test_it_deals_damage_to_each_other_creature_skips_the_source():
    engine, state = _engine()
    me, mine, theirs = (_bear(state, n, o, toughness=9) for n, o in (("me", "p1"), ("mine", "p1"), ("theirs", "p2")))
    _run(engine, state, "it deals 3 damage to each other creature", me)
    assert (me.damage_marked, mine.damage_marked, theirs.damage_marked) == (0, 3, 3)


@pytest.mark.parametrize("name, oracle", [
    ("Shefet Archfiend", "Flying\nWhen this creature enters, all other creatures get -2/-2 until end of turn."),
    ("Honored Crop-Captain", "Whenever this creature attacks, other attacking creatures get +1/+0 until end of turn."),
    ("Chaos Maw", "Flying\nWhen this creature enters, it deals 3 damage to each other creature."),
])
def test_real_cards_with_an_other_group_are_modeled(name, oracle):
    card = Card(id=name, name=name, type_line="Creature — Demon", is_creature=True,
                power=3, toughness=3, oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# -- the controller scope around a quality filter, and on a plural target -----


@pytest.mark.parametrize("clause, filt", [
    ("destroy target creature with flying an opponent controls", {"keyword": "flying"}),
    ("destroy target creature an opponent controls with power 2 or less", {"max_power": 2}),
    ("destroy target creature with power 4 or greater an opponent controls", {"min_power": 4}),
])
def test_a_quality_filter_and_a_controller_scope_compose(clause, filt):
    [spec] = match_clause(clause)
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature_you_dont_control", "creature_filter": filt}


def test_a_scope_on_both_sides_of_the_filter_is_refused():
    assert match_clause(
        "destroy target creature an opponent controls with flying an opponent controls") is None


def test_scoped_quality_filter_offers_only_the_opponents_matching_creatures():
    _, state = _engine()
    mine = _bear(state, "mine", "p1", power=5)
    big = _bear(state, "big", "p2", power=5)
    small = _bear(state, "small", "p2", power=1)
    [spec] = match_clause("destroy target creature an opponent controls with power 2 or less")
    offered = {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=spec.params["target_kind"],
                                          creature_filter=spec.params["creature_filter"]))}
    assert offered == {small.instance_id} and mine.instance_id not in offered and big.instance_id not in offered


@pytest.mark.parametrize("clause, effect, kind, count", [
    ("tap up to 2 target creatures your opponents control", "tap", "creature_you_dont_control", 2),
    ("tap up to 2 target creatures you don't control", "tap", "creature_you_dont_control", 2),
    ("return up to 2 target creatures your opponents control to their owners' hands",
     "return_to_hand", "creature_you_dont_control", 2),
])
def test_plural_targets_take_the_controller_scope(clause, effect, kind, count):
    [spec] = match_clause(clause)
    assert spec.type == effect
    assert spec.params["target_kind"] == kind and spec.params["count"] == count
    assert spec.params["optional"] is True


def test_a_plural_row_with_no_scoped_pool_stays_unclaimed():
    assert match_clause("tap up to 2 target artifacts your opponents control") is None


def test_plural_scope_taps_only_the_opponents_creatures():
    engine, state = _engine()
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    [spec] = match_clause("tap up to 2 target creatures your opponents control")
    offered = {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=spec.params["target_kind"], count=2, optional=True))}
    assert offered == {theirs.instance_id}


@pytest.mark.parametrize("name, oracle", [
    ("Arbor Colossus", "Reach\n{3}{G}{G}{G}: Monstrosity 3.\nWhen this creature becomes monstrous, destroy target creature with flying an opponent controls."),
    ("Intrusive Packbeast", "Vigilance\nWhen this creature enters, tap up to 2 target creatures your opponents control."),
])
def test_real_cards_with_a_scoped_quality_or_plural_target_are_modeled(name, oracle):
    card = Card(id=name, name=name, type_line="Creature — Beast", is_creature=True,
                power=3, toughness=3, oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_dont_untap_takes_the_controller_scope():
    """Fogwalker: "target creature an opponent controls doesn't untap …"."""
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, state = _engine()
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    [spec] = match_clause(
        "target creature an opponent controls doesn't untap during its controller's next untap step")
    assert spec.type == "skip_next_untap" and spec.params == {"target_kind": "creature_you_dont_control"}
    offered = {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=spec.params["target_kind"]))}
    assert offered == {theirs.instance_id}
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = mine
    effect.apply(engine.rules.context, targets=[theirs])
    assert theirs.skip_next_untap and not mine.skip_next_untap
    assert match_clause("target creature you control doesn't untap during its controller's next untap step") is None


# -- the controller scope on a group filter and on divided damage -------------


def test_damage_to_each_creature_with_a_keyword_your_opponents_control_executes():
    engine, state = _engine()
    src = _bear(state, "src", "p1", toughness=9)
    mine_flyer = _bear(state, "mine_flyer", "p1", toughness=9)
    their_flyer = _bear(state, "their_flyer", "p2", toughness=9)
    their_bear = _bear(state, "their_bear", "p2", toughness=9)
    for o in (mine_flyer, their_flyer):
        o.card.keywords = ["Flying"]
    [spec] = parse_effect_body("it deals 1 damage to each creature with flying your opponents control")
    assert spec.params["selector"] == "each_creature_opponents_control"
    _run(engine, state, "it deals 1 damage to each creature with flying your opponents control", src)
    assert (mine_flyer.damage_marked, their_flyer.damage_marked, their_bear.damage_marked) == (0, 1, 0)


@pytest.mark.parametrize("clause, kind", [
    ("it deals 5 damage divided as you choose among any number of target creatures and/or "
     "planeswalkers your opponents control", "creature_or_planeswalker_you_dont_control"),
    ("it deals 3 damage divided as you choose among any number of target creatures "
     "your opponents control", "creature_you_dont_control"),
])
def test_divided_damage_takes_the_controller_scope(clause, kind):
    [spec] = match_clause(clause)
    assert spec.params["target_kind"] == kind and spec.params["divided"] is True


def test_divided_damage_to_bare_targets_has_no_scope():
    assert match_clause(
        "it deals 3 damage divided as you choose among any number of targets your opponents control") is None


# -- "each other player" as an edict subject ----------------------------------


def test_each_other_player_sacrifices_is_the_each_opponent_edict():
    [spec] = match_clause("each other player sacrifices a creature of their choice")
    assert spec.type == "sacrifice"
    assert spec.params == {"selector": "each_opponent", "what": "creature", "count": 1}


def test_each_other_player_edict_hits_the_opponent_and_not_the_controller():
    engine, state = _engine()
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    from mtg_analyzer.game.effects.core import EffectRegistry

    [spec] = match_clause("each other player sacrifices a creature of their choice")
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = mine
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()
    assert theirs not in state.battlefield and mine in state.battlefield


def test_grave_pact_is_modeled():
    card = Card(id="gp", name="Grave Pact", type_line="Enchantment",
                oracle_text="Whenever a creature you control dies, each other player sacrifices a creature.")
    assert parse_oracle(card).modeled is False  # no "of their choice": a different, unclaimed wording
    card = Card(id="gp2", name="Grave Pact", type_line="Enchantment",
                oracle_text="Whenever a creature you control dies, each other player sacrifices a creature of their choice.")
    assert parse_oracle(card).modeled


# -- the "opponents control" / "other" mass selectors -------------------------


def test_destroy_all_creatures_your_opponents_control_executes():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    [spec] = match_clause("destroy all creatures your opponents control")
    assert spec.params == {"selector": "opponents_creatures"}
    _run(engine, state, "destroy all creatures your opponents control", src)
    assert theirs not in state.battlefield and mine in state.battlefield and src in state.battlefield


def test_return_all_other_nonland_permanents_skips_the_source_and_lands():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    rock = _bf(state, Card(id="rk", name="Rock", type_line="Artifact"), "p2")
    land = _bf(state, Card(id="ln", name="Forest", type_line="Basic Land — Forest", is_land=True), "p2")
    [spec] = match_clause("return all other nonland permanents to their owners' hands")
    assert spec.type == "return_to_hand" and spec.params == {"selector": "all_other_nonland_permanents"}
    _run(engine, state, "return all other nonland permanents to their owners' hands", src)
    assert src in state.battlefield and land in state.battlefield and rock not in state.battlefield
    assert rock in state.player_by_id("p2").hand


def test_dread_cacodemon_and_kederekt_leviathan_are_modeled():
    for name, text in (
        ("Dread Cacodemon", "When this creature enters, if you cast it from your hand, destroy all creatures your opponents control, then tap all other creatures you control."),
        ("Kederekt Leviathan", "When this creature enters, return all other nonland permanents to their owners' hands."),
    ):
        card = Card(id=name, name=name, type_line="Creature — Demon", is_creature=True,
                    power=8, toughness=8, oracle_text=text)
        result = parse_oracle(card)
        assert result.modeled, (name, result.unclaimed)


# -- "those creatures" after a mass selector (the group referent) --------------


def _run_body(engine, body, source):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    specs = parse_effect_body(body)
    assert specs is not None, body
    _apply_effects_partitioned(build_effects(specs, source), engine.rules.context, None, None, source=source)
    engine.resolve_until_stable()
    return specs


def test_untap_those_creatures_replays_the_pump_group():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    for obj in (src, mine, theirs):
        obj.tapped = True
    specs = _run_body(engine, "creatures you control get +2/+1 until end of turn. untap those creatures", src)
    assert specs[-1].params == {"selector": "previous_selector", "untap": True}
    assert (mine.power, theirs.power) == (4, 2)
    assert not mine.tapped and not src.tapped and theirs.tapped


def test_untap_them_after_a_keyword_grant_to_a_group():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine = _bear(state, "mine", "p1")
    mine.tapped = True
    _run_body(engine, "creatures you control gain hexproof until end of turn. untap them", src)
    assert not mine.tapped


def test_those_creatures_needs_a_replayable_group():
    # a subtype-narrowed or targeted antecedent is not a selector group
    assert parse_effect_body("target creature gets +2/+2 until end of turn. tap those creatures") is None
    assert parse_effect_body("tap those creatures") is None


def test_war_flare_and_flying_crane_technique_are_modeled():
    for name, text in (
        ("War Flare", "Creatures you control get +2/+1 until end of turn. Untap those creatures."),
        ("Flying Crane Technique", "Untap all creatures you control. They gain flying and double strike until end of turn."),
    ):
        card = Card(id=name, name=name, type_line="Instant", is_instant=True, oracle_text=text)
        result = parse_oracle(card)
        assert result.modeled, (name, result.unclaimed)


def test_those_creatures_dont_untap_after_tapping_all_attackers():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    raider, idle = _bear(state, "raider", "p2"), _bear(state, "idle", "p2")
    raider.attacking = True
    specs = _run_body(engine, "tap all attacking creatures. those creatures don't untap during "
                              "their controller's next untap step", src)
    assert specs[-1].params == {"target_kind": None, "subject": "previous_selector"}
    assert raider.tapped and raider.skip_next_untap
    assert not idle.tapped and not idle.skip_next_untap


def test_tap_those_creatures_after_group_damage_taps_only_the_creatures_hit():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    flyer = _bf(state, Card(id="fl", name="Flyer", type_line="Creature — Bird", is_creature=True,
                            power=1, toughness=3, keywords=["Flying"]), "p2")
    ground = _bear(state, "ground", "p2", toughness=3)
    mine_flyer = _bf(state, Card(id="mf", name="Mine", type_line="Creature — Bird", is_creature=True,
                                 power=1, toughness=3, keywords=["Flying"]), "p1")
    specs = _run_body(engine, "~ deals 1 damage to each creature with flying your opponents control. "
                              "tap those creatures", src)
    assert specs[-1].params == {"selector": "previous_selector", "untap": False}
    assert flyer.tapped and not ground.tapped and not mine_flyer.tapped


def test_thundermaw_hellkite_is_modeled():
    text = ("Flying\nHaste\nWhen this creature enters, it deals 1 damage to each creature with "
            "flying your opponents control. Tap those creatures.")
    card = Card(id="tm", name="Thundermaw Hellkite", type_line="Creature — Dragon", is_creature=True,
                power=5, toughness=5, oracle_text=text)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_untap_those_creatures_after_counters_on_each_creature_you_control():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    for obj in (src, mine, theirs):
        obj.tapped = True
    specs = _run_body(engine, "put a +1/+1 counter on each creature you control. untap those creatures", src)
    assert specs[-1].params == {"selector": "previous_selector", "untap": True}
    assert not mine.tapped and not src.tapped and theirs.tapped


def test_group_pump_after_other_creature_counters_skips_the_source():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine = _bear(state, "mine", "p1")
    _run_body(engine, "put a +1/+1 counter on each other creature you control. "
                      "those creatures gain trample until end of turn", src)
    assert "trample" in mine.granted_keywords and "trample" not in src.granted_keywords


def test_narrowed_counter_group_is_not_a_referent():
    # "that didn't attack or enter this turn" narrows the group past a bare selector name
    assert parse_effect_body("put a +1/+1 counter on each blue creature you control. "
                             "untap those creatures") is None


# -- "target opponent <verb> for each …" (a bind keeps its body's target) -------


def _bind_for_each(clause):
    [spec] = parse_effect_body(clause)
    assert spec.type == "bind"
    return spec


def test_target_opponent_loses_life_for_each_keeps_its_target_and_scales():
    spec = _bind_for_each("target opponent loses 1 life for each vampire you control")
    assert spec.params["effects"][0]["params"] == {"amount": "$n", "target_kind": "opponent"}


def test_target_opponent_discard_for_each_targets_an_opponent_only():
    spec = _bind_for_each("target opponent discards a card for each shrine you control")
    assert spec.params["effects"][0]["params"] == {"count": "$n", "target_kind": "opponent"}


def test_target_opponent_life_loss_for_each_executes_against_the_chosen_target():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    _bear(state, "v1", "p1")
    _bear(state, "v2", "p1")
    for obj in state.battlefield:
        obj.card.type_line = "Creature — Vampire"
    specs = parse_effect_body("target opponent loses 1 life for each vampire you control")
    effects = build_effects(specs, src)
    assert [t.kind for e in effects for t in e.target_specs] == ["opponent"]
    opponent = state.player_by_id("p2")
    _apply_effects_partitioned(effects, engine.rules.context, [opponent], None, source=src)
    assert opponent.life == 20 - 3 and state.player_by_id("p1").life == 20


def test_targeted_for_each_bodies_on_real_cards_are_modeled():
    for name, type_line, text in (
        ("Honden of Night's Reach", "Enchantment — Shrine",
         "At the beginning of your upkeep, target opponent discards a card for each Shrine you control."),
        ("Gaea's Might", "Instant",
         "Target creature gets +1/+1 until end of turn for each basic land type among lands you control."),
    ):
        card = Card(id=name, name=name, type_line=type_line, oracle_text=text,
                    is_instant=type_line == "Instant")
        result = parse_oracle(card)
        assert result.modeled, (name, result.unclaimed)


# -- the Duress family: "target opponent" is an opponent, and the comma form ----


def test_duress_targets_an_opponent_not_any_player():
    [spec] = parse_effect_body("target opponent reveals their hand. you choose a nonland card from it. "
                               "that player discards that card")
    assert spec.type == "reveal_hand_choose_discard" and spec.params["target_kind"] == "opponent"
    [spec] = parse_effect_body("target player reveals their hand. you choose a nonland card from it. "
                               "that player discards that card")
    assert spec.params["target_kind"] == "player"


def test_hand_disruption_comma_form_reads_like_the_sentence_form():
    comma = parse_effect_body("target opponent reveals their hand, you choose a nonland card from it, "
                              "then that player discards that card")
    sentence = parse_effect_body("target opponent reveals their hand. you choose a nonland card from it. "
                                 "that player discards that card")
    assert comma == sentence


def test_devour_intellect_instead_override_shares_one_opponent_target():
    text = ("Target opponent discards a card. If mana from a Treasure was spent to cast this spell, "
            "instead that player reveals their hand, you choose a nonland card from it, "
            "then that player discards that card.")
    result = parse_oracle(Card(id="di", name="Devour Intellect", type_line="Sorcery", is_sorcery=True,
                               oracle_text=text))
    assert result.modeled, result.unclaimed
    [ability] = result.specs
    [spec] = ability.effects
    assert spec.type == "if_else"
    kinds = {e["params"]["target_kind"] for branch in ("then", "else") for e in spec.params[branch]}
    assert kinds == {"opponent"}


def test_creatures_without_flying_your_opponents_control_cant_block_executes():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    ground = _bear(state, "ground", "p2")
    flyer = _bf(state, Card(id="fl2", name="Flyer", type_line="Creature — Bird", is_creature=True,
                            power=1, toughness=1, keywords=["Flying"]), "p2")
    mine = _bear(state, "mine", "p1")
    [spec] = parse_effect_body("creatures without flying your opponents control can't block this turn")
    assert spec.params == {"selector": "opponents_permanents", "filter": {"without_keyword": "flying"}}
    _run(engine, state, "creatures without flying your opponents control can't block this turn", src)
    assert ground.temp_cant_block and not flyer.temp_cant_block and not mine.temp_cant_block


def test_stun_counter_on_each_of_them_hits_every_chosen_creature():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    a, b, other = _bear(state, "a", "p2"), _bear(state, "b", "p2"), _bear(state, "other", "p2")
    specs = parse_effect_body("tap up to 2 target creatures. put a stun counter on each of them")
    assert specs[-1].params["previous_group"] is True
    effects = build_effects(specs, src)
    _apply_effects_partitioned(effects, engine.rules.context, [a, b], None, source=src)
    assert a.counters.get("stun") == 1 and b.counters.get("stun") == 1
    assert not other.counters.get("stun")


def test_stun_on_each_of_them_needs_a_preceding_choice():
    assert parse_effect_body("put a stun counter on each of them") is None


def test_out_cold_is_modeled():
    text = "Tap up to two target creatures and put a stun counter on each of them. Investigate."
    card = Card(id="oc", name="Out Cold", type_line="Instant", is_instant=True, oracle_text=text)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# -- the general mass tap: "tap all <group>" as a structured selector ----------


def test_tap_all_creatures_your_opponents_control_taps_only_theirs():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs, theirs2 = _bear(state, "mine", "p1"), _bear(state, "t1", "p2"), _bear(state, "t2", "p2")
    specs = _run_body(engine, "tap all creatures your opponents control", src)
    assert specs[0].type == "tap" and specs[0].params["selector"]["of"] == "opponents"
    assert theirs.tapped and theirs2.tapped and not mine.tapped and not src.tapped


def test_tap_all_nonwhite_creatures_skips_white_ones():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    white = _bf(state, Card(id="wh", name="Knight", type_line="Creature — Human Knight", is_creature=True,
                            power=2, toughness=2, color_identity={"W"}), "p2")
    green = _bf(state, Card(id="gr", name="Elf", type_line="Creature — Elf", is_creature=True,
                            power=1, toughness=1, color_identity={"G"}), "p2")
    _run_body(engine, "tap all nonwhite creatures", src)
    assert green.tapped and not white.tapped


def test_stun_counter_on_each_of_those_creatures_after_a_mass_tap():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    specs = _run_body(engine, "tap all creatures your opponents control, then put a stun counter on "
                              "each of those creatures", src)
    assert specs[-1].params["previous_selector"] is True
    assert theirs.counters.get("stun") == 1 and not mine.counters.get("stun")


def test_monstrosity_of_the_lake_and_blinding_light_are_modeled():
    for name, tl, text in (
        ("Monstrosity of the Lake", "Creature — Leviathan",
         "When this creature enters, you may pay {5}. If you do, tap all creatures your opponents "
         "control, then put a stun counter on each of those creatures."),
        ("Blinding Light", "Sorcery", "Tap all nonwhite creatures."),
    ):
        card = Card(id=name, name=name, type_line=tl, oracle_text=text, is_sorcery=tl == "Sorcery")
        result = parse_oracle(card)
        assert result.modeled, (name, result.unclaimed)


def test_tap_all_creatures_target_opponent_controls_taps_the_chosen_players_only():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs, theirs2 = _bear(state, "mine", "p1"), _bear(state, "t1", "p2"), _bear(state, "t2", "p2")
    land = _bf(state, Card(id="ln2", name="Forest", type_line="Basic Land — Forest", is_land=True), "p2")
    specs = parse_effect_body("tap all creatures target opponent controls")
    assert specs[0].params["selector_player"] == "opponent"
    effects = build_effects(specs, src)
    assert [t.kind for e in effects for t in e.target_specs] == ["opponent"]
    _apply_effects_partitioned(effects, engine.rules.context, [state.player_by_id("p2")], None, source=src)
    assert theirs.tapped and theirs2.tapped and not mine.tapped and not land.tapped


def test_tap_all_lands_target_player_controls_is_modeled_and_a_player_target():
    [spec] = parse_effect_body("tap all lands target player controls")
    assert spec.params["selector_player"] == "player"
    assert spec.params["selector"]["filter"] == {"card_type": "land"}
    card = Card(id="gs", name="Gulf Squid", type_line="Creature — Squid", is_creature=True, power=3,
                toughness=3, oracle_text="When this creature enters, tap all lands target player controls.")
    assert parse_oracle(card).modeled


# -- a named counter on a mass group ------------------------------------------


def test_impostor_counter_on_each_creature_you_control_executes():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    mine, theirs = _bear(state, "mine", "p1"), _bear(state, "theirs", "p2")
    rock = _bf(state, Card(id="rk2", name="Rock", type_line="Artifact"), "p1")
    [spec] = _run_body(engine, "put an impostor counter on each creature you control", src)
    assert spec.params["kind"] == "impostor" and spec.params["group"]["of"] == "you"
    assert mine.counters.get("impostor") == 1 and src.counters.get("impostor") == 1
    assert not theirs.counters.get("impostor") and not rock.counters.get("impostor")


def test_hone_counter_on_each_equipment_you_control_needs_a_battlefield_group():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    sword = _bf(state, Card(id="sw", name="Sword", type_line="Artifact — Equipment"), "p1")
    _run_body(engine, "put a hone counter on each equipment you control", src)
    assert sword.counters.get("hone") == 1 and not src.counters.get("hone")
    assert parse_effect_body("put an impostor counter on each creature card in your graveyard") is None


def test_named_counter_group_cards_are_modeled():
    card = Card(id="im", name="Illicit Masquerade", type_line="Enchantment",
                oracle_text="When this enchantment enters, put an impostor counter on each creature you control.")
    assert parse_oracle(card).modeled


# -- the "without <keyword>" tail of the shared object phrase -----------------


def test_without_keyword_tail_in_the_count_phrase_grammar():
    from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase

    assert parse_count_phrase("creatures without flying")["filter"] == {
        "card_type": "creature", "without_keyword": "flying"}
    scoped = parse_count_phrase("creatures without flying your opponents control")
    assert scoped["of"] == "opponents" and scoped["filter"]["without_keyword"] == "flying"
    assert parse_count_phrase("creatures without flying or reach") is None
    assert parse_count_phrase("creatures without banana") is None


def test_deluge_taps_only_the_creatures_without_flying():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    ground = _bear(state, "ground", "p2")
    flyer = _bf(state, Card(id="fl3", name="Flyer", type_line="Creature — Bird", is_creature=True,
                            power=1, toughness=1, keywords=["Flying"]), "p2")
    _run_body(engine, "tap all creatures without flying", src)
    assert ground.tapped and src.tapped and not flyer.tapped


# -- "any player may activate this ability" (a parsed rider on RULE 602.2) -------

FAN_FAVORITE = Card(id="ff", name="Fan Favorite", type_line="Creature — Human", is_creature=True,
                    power=1, toughness=1,
                    oracle_text="{2}: Fan Favorite gets +1/+1 until end of turn. "
                                "Any player may activate this ability.".replace("Fan Favorite", "~"))


def _fan_favorite(engine, state):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = GameObject(FAN_FAVORITE, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def test_any_player_may_activate_is_parsed_into_the_cost():
    result = parse_oracle(FAN_FAVORITE)
    assert result.modeled, result.unclaimed
    [ability] = [a for a in result.specs if a.ability_kind == "activated"]
    assert ability.cost["any_player_may_activate"] is True


def test_an_opponent_may_activate_and_the_source_gets_the_pump():
    engine, state = _engine()
    ff = _fan_favorite(engine, state)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    state.current_step = "main1"
    p2.mana_pool.add("C", 2)
    assert engine.can_activate(p2, ff, ff.activated_abilities[0])
    engine.activate_ability(p2, ff)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert ff.power == 2 and ff.toughness == 2


def test_sorcery_speed_variant_keeps_its_timing_restriction():
    text = ("{4}: Return target creature card from a graveyard to its owner's hand. "
            "Any player may activate this ability but only as a sorcery.")
    result = parse_oracle(Card(id="er", name="Endbringer's Revel", type_line="Enchantment", oracle_text=text))
    assert result.modeled, result.unclaimed
    [ability] = [a for a in result.specs if a.ability_kind == "activated"]
    assert ability.cost["any_player_may_activate"] is True
    assert any(e.type == "sorcery_speed_marker" for e in ability.effects)


# -- "can't be regenerated this turn" (RULE 701.16) -----------------------------


def _shot(engine, state, body, target):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    src = _bear(state, "burner", "p1")
    effects = build_effects(parse_effect_body(body), src)
    _apply_effects_partitioned(effects, engine.rules.context, [target], None, source=src)
    engine.resolve_until_stable()


def test_a_regeneration_shield_saves_the_creature_without_the_rider():
    engine, state = _engine()
    victim = _bear(state, "victim", "p2", toughness=2)
    engine.rules.regenerate(victim)
    _shot(engine, state, "~ deals 3 damage to target creature", victim)
    assert victim in state.battlefield and victim.tapped


def test_incinerate_rider_defeats_the_regeneration_shield():
    engine, state = _engine()
    victim = _bear(state, "victim", "p2", toughness=2)
    engine.rules.regenerate(victim)
    specs = parse_effect_body("~ deals 3 damage to target creature. "
                              "a creature dealt damage this way can't be regenerated this turn")
    assert specs[-1].params == {"damaged_this_way": True}
    _shot(engine, state, "~ deals 3 damage to target creature. "
                         "a creature dealt damage this way can't be regenerated this turn", victim)
    assert victim not in state.battlefield


def test_gravebind_marks_the_target_and_the_pronoun_form_follows_a_target():
    engine, state = _engine()
    victim = _bear(state, "victim", "p2", toughness=2)
    _shot(engine, state, "target creature can't be regenerated this turn", victim)
    assert victim.temp_cant_be_regenerated
    other = _bear(state, "other", "p2", toughness=2)
    [_, rider] = parse_effect_body("~ deals 1 damage to target creature. it can't be regenerated this turn")
    assert rider.params == {"previous_subject": True}
    _shot(engine, state, "~ deals 1 damage to target creature. it can't be regenerated this turn", other)
    assert other.temp_cant_be_regenerated


def test_regeneration_rider_cards_are_modeled():
    for name, tl, text in (
        ("Gravebind", "Instant", "Target creature can't be regenerated this turn. Draw a card."),
        ("Incinerate", "Instant", "Incinerate deals 3 damage to any target. A creature dealt damage this way "
                                  "can't be regenerated this turn."),
    ):
        card = Card(id=name, name=name, type_line=tl, is_instant=True, oracle_text=text.replace(name, "~"))
        assert parse_oracle(card).modeled, name


CARBONIZE = ("~ deals 3 damage to any target. If it's a creature, it can't be regenerated this turn, "
             "and if it would die this turn, exile it instead.")


def test_carbonize_exiles_a_shielded_creature_it_kills():
    engine, state = _engine()
    victim = _bear(state, "victim", "p2", toughness=2)
    engine.rules.regenerate(victim)
    _shot(engine, state, CARBONIZE.lower(), victim)
    assert victim not in state.battlefield
    assert victim in state.player_by_id("p2").exile      # exiled, neither regenerated nor in the graveyard
    assert victim not in state.player_by_id("p2").graveyard


def test_carbonize_riders_ignore_a_player_target():
    engine, state = _engine()
    p2 = state.player_by_id("p2")
    _shot(engine, state, CARBONIZE.lower(), p2)
    assert p2.life == 17


def test_carbonize_family_is_modeled():
    for name, text in (
        ("Carbonize", CARBONIZE),
        ("Scorching Lava", "~ deals 2 damage to any target. If this spell was kicked, that creature can't be "
                           "regenerated this turn and if it would die this turn, exile it instead.\nKicker {O}"),
    ):
        card = Card(id=name, name=name, type_line="Instant", is_instant=True, oracle_text=text)
        assert parse_oracle(card).modeled, name


# -- damage to a mass group read through the shared noun-phrase grammar --------


def _fire(engine, state, body):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    src = _bear(state, "src", "p1", toughness=9)
    specs = parse_effect_body(body)
    assert specs is not None, body
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, None, None, source=src)
    engine.resolve_until_stable()
    return src


def _damage(obj):
    return obj.damage_marked


def test_damage_to_each_creature_you_dont_control_spares_your_own():
    engine, state = _engine()
    mine = _bear(state, "mine", "p1", toughness=9)
    theirs = _bear(state, "theirs", "p2", toughness=9)
    _fire(engine, state, "~ deals 1 damage to each creature you don't control")
    assert _damage(theirs) == 1 and _damage(mine) == 0


def test_damage_to_each_other_creature_you_control_skips_the_source():
    engine, state = _engine()
    mine = _bear(state, "mine", "p1", toughness=9)
    theirs = _bear(state, "theirs", "p2", toughness=9)
    src = _fire(engine, state, "~ deals 2 damage to each other creature you control")
    assert _damage(mine) == 2 and _damage(src) == 0 and _damage(theirs) == 0


def test_damage_to_each_other_creature_without_flying():
    engine, state = _engine()
    ground = _bear(state, "ground", "p2", toughness=9)
    flyer = _bf(state, Card(id="fl4", name="Flyer", type_line="Creature — Bird", is_creature=True,
                            power=1, toughness=9, keywords=["Flying"]), "p2")
    src = _fire(engine, state, "~ deals 1 damage to each other creature without flying")
    assert _damage(ground) == 1 and _damage(flyer) == 0 and _damage(src) == 0


def test_the_named_selectors_still_win_over_the_general_group_row():
    [spec] = parse_effect_body("~ deals 2 damage to each creature")
    assert spec.params == {"amount": 2, "selector": "each_creature"}
    # PAR-107…114 run 2 (Inflame): its own row, the `each_creature` selector narrowed by the marked-damage filter —
    # never the general group row, which still refuses a "dealt damage" qualifier.
    [filtered] = parse_effect_body("~ deals 2 damage to each creature dealt damage this turn")
    assert filtered.params == {"amount": 2, "selector": "each_creature", "selector_filter": {"damaged_this_turn": True}}


def test_damage_to_each_creature_target_opponent_controls_uses_the_chosen_player():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1", toughness=9)
    mine, theirs = _bear(state, "mine", "p1", toughness=9), _bear(state, "theirs", "p2", toughness=9)
    specs = parse_effect_body("~ deals 1 damage to each creature target opponent controls")
    assert specs[0].params["group_player"] == "opponent"
    effects = build_effects(specs, src)
    assert [t.kind for e in effects for t in e.target_specs] == ["opponent"]
    _apply_effects_partitioned(effects, engine.rules.context, [state.player_by_id("p2")], None, source=src)
    assert theirs.damage_marked == 1 and mine.damage_marked == 0 and src.damage_marked == 0


def test_damage_to_each_creature_defending_player_controls_hits_the_attacked_player_only():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    attacker = _bear(state, "attacker", "p1", toughness=9)
    mine = _bear(state, "mine", "p1", toughness=9)
    theirs = _bear(state, "theirs", "p2", toughness=9)
    text = "Whenever ~ attacks, it deals 1 damage to each creature defending player controls."
    attacker.card.oracle_text = text.replace("~", "Attacker")
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    attacker.card.name = "Attacker"
    bind_from_catalogue(attacker)
    attacker.summoning_sick = False
    engine.declare_attackers(state.active_player, [attacker])
    engine.resolve_until_stable()
    assert theirs.damage_marked == 1 and mine.damage_marked == 0


def test_that_player_after_a_creature_target_is_that_targets_controller():
    engine, state = _engine()
    specs = parse_effect_body("~ deals 4 damage to target creature an opponent controls. "
                              "then ~ deals 2 damage to each other creature that player controls")
    assert specs[-1].params["group_player"] == "previous_controller"


def test_x_damage_to_each_creature_and_each_player_is_parsed():
    [spec] = parse_effect_body("~ deals x damage to each creature and each player")
    assert spec.params == {"amount": "x", "selector": "each_creature_and_player"}


def test_damage_to_each_other_creature_and_each_player_spares_only_the_source():
    engine, state = _engine()
    mine = _bear(state, "mine", "p1", toughness=9)
    theirs = _bear(state, "theirs", "p2", toughness=9)
    src = _fire(engine, state, "it deals 2 damage to each other creature and each player")
    assert mine.damage_marked == 2 and theirs.damage_marked == 2 and src.damage_marked == 0
    assert state.player_by_id("p1").life == 18 and state.player_by_id("p2").life == 18


def test_damage_to_each_other_creature_without_flying_and_each_opponent():
    [spec] = parse_effect_body("~ deals 1 damage to each other creature without flying and each opponent")
    assert spec.params["group_and_players"] == "each_opponent"
    assert spec.params["group"]["filter"]["without_keyword"] == "flying"
