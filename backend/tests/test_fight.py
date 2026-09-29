"""RULE 701.14 fight — the engine primitive and its parser handlers (MEC-1).

Two halves, as every mechanic batch has: `game/effects/core.py`'s `FightEffect`
(both creatures deal damage equal to their power to each other, 701.14a, and
neither does if either one has left or stopped being a creature, 701.14b), and
the `catalogue/handlers.py` rows that read the four printed subjects off real
oracle text — including the one this family is *deliberately* fail-closed on,
Epic Confrontation's "it", whose referent is a previously targeted creature
rather than the spell itself.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import FightEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(state, name, power, toughness, controller="p1"):
    return _bf(state, _card(name, power=power, toughness=toughness), controller)


def _resolve(engine, effect, targets=None):
    """Apply ``effect`` straight against the engine's context, then let the
    SBA pass run — the shape a resolving one-shot effect sees."""
    from mtg_analyzer.game.effects.core import GameContext

    effect.apply(GameContext(engine.state, engine.rules), targets)
    engine.rules.check_state_based_actions()


# ---------------------------------------------------------------------------
# The primitive (RULE 701.14)
# ---------------------------------------------------------------------------


def test_both_creatures_deal_damage_equal_to_their_power():
    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 5)
    theirs = _creature(state, "Theirs", 2, 4, controller="p2")

    effect = FightEffect(fighter_kind="creature_you_control",
                         other_kind="creature_you_dont_control")
    _resolve(engine, effect, [mine, theirs])

    assert theirs.damage_marked == 3
    assert mine.damage_marked == 2


def test_a_fight_announces_both_requirements():
    effect = FightEffect(fighter_kind="creature_you_control",
                         other_kind="creature_you_dont_control")
    assert [spec.kind for spec in effect.target_specs] == [
        "creature_you_control", "creature_you_dont_control",
    ]


def test_lethal_fight_damage_kills_through_the_sba_pass():
    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 5, 5)
    theirs = _creature(state, "Theirs", 1, 3, controller="p2")

    _resolve(engine, FightEffect(fighter_kind="creature_you_control",
                                 other_kind="creature_you_dont_control"),
             [mine, theirs])

    assert theirs not in state.battlefield and theirs in p2.graveyard
    assert mine in state.battlefield  # only 1 damage back


def test_neither_fights_when_one_has_left_the_battlefield():
    """RULE 701.14b — an illegal/absent participant cancels *both* halves,
    which is exactly why this is one effect and not two damage effects."""
    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _creature(state, "Theirs", 3, 3, controller="p2")
    state.battlefield.remove(theirs)

    _resolve(engine, FightEffect(fighter_kind="creature_you_control",
                                 other_kind="creature_you_dont_control"),
             [mine, theirs])

    assert mine.damage_marked == 0
    assert theirs.damage_marked == 0


def test_neither_fights_when_one_is_no_longer_a_creature():
    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _bf(state, _card("Rock", "Artifact", "{1}", 1), controller="p2")

    _resolve(engine, FightEffect(fighter_kind="creature_you_control",
                                 other_kind="creature"),
             [mine, theirs])

    assert mine.damage_marked == 0
    assert theirs.damage_marked == 0


def test_an_optional_fight_with_no_target_does_nothing():
    """"~ fights **up to one** target creature" (RULE 115.1a) resolving with
    no target chosen at all."""
    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 3)

    _resolve(engine, FightEffect(other_kind="creature_you_dont_control", optional=True,
                                 source=mine), [])

    assert mine.damage_marked == 0


def test_the_source_itself_fights_when_no_fighter_kind_is_given():
    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 4, 4)
    theirs = _creature(state, "Theirs", 1, 6, controller="p2")

    effect = FightEffect(other_kind="creature_you_dont_control", source=mine)
    assert [spec.kind for spec in effect.target_specs] == ["creature_you_dont_control"]
    _resolve(engine, effect, [theirs])

    assert theirs.damage_marked == 4
    assert mine.damage_marked == 1


def test_an_auras_host_fights_for_it():
    """"When this Aura enters, enchanted creature fights …" (Warbriar
    Blessing) — the host is re-read off ``attached_to`` at resolution."""
    engine, state, _, _ = _engine()
    host = _creature(state, "Host", 3, 3)
    theirs = _creature(state, "Theirs", 2, 5, controller="p2")
    aura = _bf(state, _card("Blessing", "Enchantment — Aura", "{G}", 1))
    aura.attached_to = host.instance_id

    _resolve(engine, FightEffect(fighter_kind="attached_permanent",
                                 other_kind="creature_you_dont_control",
                                 source=aura),
             [theirs])

    assert theirs.damage_marked == 3
    assert host.damage_marked == 2


def test_fight_damage_is_not_combat_damage():
    """RULE 701.14d — nothing about a fight may register as combat damage
    (which is what a "deals combat damage to a player" trigger reads)."""
    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _creature(state, "Theirs", 3, 3, controller="p2")

    seen = []
    state.subscribe(lambda e: seen.append(e) if str(e.type) == "DAMAGE" else None)
    _resolve(engine, FightEffect(fighter_kind="creature_you_control",
                                 other_kind="creature_you_dont_control"),
             [mine, theirs])

    assert seen and not any(e.data.get("combat") for e in seen)


# ---------------------------------------------------------------------------
# The parser (docs/09) — real oracle text off the cache
# ---------------------------------------------------------------------------


def test_prey_upon_parses_into_one_two_target_fight():
    result = parse_oracle(_named("Prey Upon"))
    assert result.modeled
    effects = [e for spec in result.specs for e in spec.effects]
    assert [e.type for e in effects] == ["fight"]
    assert effects[0].params == {
        "fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control",
    }


def test_koglas_etb_fights_with_the_source_as_the_fighter():
    result = parse_oracle(_named("Kogla, the Titan Ape"))
    fights = [e for spec in result.specs for e in spec.effects if e.type == "fight"]
    assert len(fights) == 1
    # "it" is Kogla itself — no ``fighter_kind``, and "up to one" is optional.
    assert fights[0].params == {"other_kind": "creature_you_dont_control", "optional": True}


def test_a_may_have_it_fight_trigger_is_modeled_and_optional():
    result = parse_oracle(_named("Somberwald Stag"))
    assert result.modeled
    spec = result.specs[0]
    assert spec.optional  # RULE 601.2's "you may", peeled off the body
    assert [e.type for e in spec.effects] == ["fight"]


def test_an_aura_host_fight_is_modeled():
    result = parse_oracle(_named("Warbriar Blessing"))
    assert result.modeled
    fights = [e for spec in result.specs for e in spec.effects if e.type == "fight"]
    assert fights[0].params["fighter_kind"] == "attached_permanent"


def test_a_pronoun_fight_is_only_claimed_when_it_means_the_source():
    """The whole point of `EffectHandler.self_subject_only`: the same clause
    is the source in a self-subject trigger body and a *previously targeted*
    creature in a spell's chained sentences."""
    clause = "it fights target creature you don't control"
    assert match_clause(clause) is None
    assert match_clause(clause, self_subject=True) is not None


def test_epic_confrontations_pronoun_binds_to_the_previous_clauses_target():
    """"It fights …" is the creature the sentence before it pumped — the
    referent `EffectHandler.previous_subject_only` unlocks, and the reason
    the same clause standing alone still claims nothing."""
    result = parse_oracle(_named("Epic Confrontation"))
    assert result.modeled
    effects = [e for spec in result.specs for e in spec.effects]
    assert [e.type for e in effects] == ["pump", "fight"]
    assert effects[1].params["fighter_kind"] == "previous_target"
    # Standing alone (no earlier clause), the same clause is still unclaimed.
    assert match_clause("it fights target creature you don't control") is None


def test_another_target_creature_reads_against_whoever_fights():
    """"Another" is relative to the *source* in Atzocan Archer's trigger
    (which the engine's ``creature`` kind already excludes) and to the *other
    target* in Pit Fight's two-target clause — there a genuine cross-
    requirement `TargetSpec.distinct_from_others`."""
    assert parse_oracle(_named("Atzocan Archer")).modeled
    fight = [
        e for spec in parse_oracle(_named("Pit Fight")).specs
        for e in spec.effects if e.type == "fight"
    ][0]
    assert fight.params["distinct"] is True


def test_prey_upon_is_castable_end_to_end_against_two_chosen_targets():
    """Parser → binder → stack: the spell announces both RULE 115
    requirements and each half of the fight lands on the right creature."""
    from mtg_analyzer.game.targeting import spell_target_specs

    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _creature(state, "Theirs", 2, 5, controller="p2")
    spell = GameObject(_named("Prey Upon"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 1)

    assert [spec.kind for spec in spell_target_specs(spell)] == [
        "creature_you_control", "creature_you_dont_control",
    ]
    engine.cast_spell(p1, spell, targets=[mine, theirs])
    engine.resolve_until_stable()

    assert theirs.damage_marked == 3
    assert mine.damage_marked == 2


def test_a_non_creature_fight_target_is_not_claimed():
    """RULE 701.14a: only creatures fight, so a `TARGET` row resolving to
    anything else leaves the clause unclaimed rather than widening it."""
    assert match_clause("~ fights target permanent") is None
    assert match_clause("target creature you control fights any target") is None


# ---------------------------------------------------------------------------
# MEC-10: whose creature fights — pronouns, "another", the chosen pair, and
# the one-sided sibling
# ---------------------------------------------------------------------------


def test_targets_are_partitioned_per_requirement_in_printed_order():
    from mtg_analyzer.game.targeting import TargetSpec, partition_targets

    specs = [TargetSpec(kind="creature_you_control"), TargetSpec(kind="creature")]
    assert partition_targets(specs, ["a", "b"]) == [["a"], ["b"]]
    # A count>1 requirement takes that many off the front.
    wide = [TargetSpec(kind="creature", count=2), TargetSpec(kind="player")]
    assert partition_targets(wide, ["a", "b", "p"]) == [["a", "b"], ["p"]]
    # Ambiguous (a declined "up to one" shifted everything) → no partition;
    # such a caller has to send explicit groups.
    assert partition_targets(specs, ["only-one"]) is None
    assert partition_targets([TargetSpec(kind="creature")], ["a"]) is None


def test_epic_confrontation_pumps_one_creature_and_fights_with_it():
    """The whole MEC-10 chain end to end: two requirements gathered in
    printed order, partitioned per effect, and a pronoun bound to the first
    of them at resolution."""
    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 1, 1)
    theirs = _creature(state, "Theirs", 2, 3, controller="p2")
    spell = GameObject(_named("Epic Confrontation"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 2)

    engine.cast_spell(p1, spell, targets=[mine, theirs])
    engine.resolve_until_stable()

    # The pump landed on the creature the spell's *first* requirement named
    # (a 1/1 becoming 2/3), and that same creature is what fought — so the
    # 2/3 opponent takes 2 and both survive. Had every effect read the shared
    # first target, the opponent's creature would have been pumped instead.
    assert (mine.power, mine.toughness) == (2, 3)
    assert mine.damage_marked == 2
    assert theirs.damage_marked == 2


def test_a_pronoun_fight_binds_to_the_previous_clauses_target_at_resolution():
    from mtg_analyzer.game.effects.core import GameContext

    engine, state, _, _ = _engine()
    pumped = _creature(state, "Pumped", 4, 4)
    theirs = _creature(state, "Theirs", 1, 9, controller="p2")

    context = GameContext(state, engine.rules)
    context.previous_targets = [pumped]
    FightEffect(fighter_kind="previous_target",
                other_kind="creature_you_dont_control").apply(context, [theirs])

    assert theirs.damage_marked == 4
    assert pumped.damage_marked == 1


def test_a_chosen_pair_fights_each_other():
    """Ancient Animus-shaped: "Choose target creature you control and target
    creature you don't control. … Then those creatures fight each other." —
    the fight clause announces no requirement of its own."""
    from mtg_analyzer.game.effects.core import ChooseTargetsEffect, _apply_effects_partitioned
    from mtg_analyzer.game.effects.core import GameContext

    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _creature(state, "Theirs", 2, 4, controller="p2")

    chooser = ChooseTargetsEffect(kinds=["creature_you_control", "creature_you_dont_control"])
    fight = FightEffect(fighter_kind="previous_target", other_kind="previous_target_2")
    assert fight.target_specs == []
    _apply_effects_partitioned(
        [chooser, fight], GameContext(state, engine.rules), None,
        [[mine], [theirs]],
    )

    assert theirs.damage_marked == 3
    assert mine.damage_marked == 2


def test_a_chosen_group_is_returned_to_hand():
    """Run Away Together-shaped (PAR-1): "Choose two target creatures
    controlled by different players. Return those creatures to their
    owners' hands." — the return clause announces no requirement of its
    own, unlike `test_a_chosen_pair_fights_each_other`'s two independently-
    kinded picks: this is one *quantified* group of the same kind."""
    from mtg_analyzer.game.effects.core import (
        ChooseTargetsEffect, GameContext, ReturnToHandEffect, _apply_effects_partitioned,
    )
    from mtg_analyzer.models.game.game_object import Zone

    engine, state, _, _ = _engine()
    mine = _creature(state, "Mine", 3, 3)
    theirs = _creature(state, "Theirs", 2, 4, controller="p2")

    chooser = ChooseTargetsEffect(kinds=["creature"], count=2, distinct_controllers=True)
    returner = ReturnToHandEffect(previous_subject=True)
    _apply_effects_partitioned(
        [chooser, returner], GameContext(state, engine.rules), None,
        [[mine, theirs]],
    )

    assert mine.zone == Zone.HAND
    assert theirs.zone == Zone.HAND


def test_another_target_creature_cannot_be_the_same_creature():
    """RULE 109.5's resolve-time backstop — the offer-time exclusion lives in
    `gameBoardView.js`, but a hand-posted action can't sneak past it."""
    engine, state, _, _ = _engine()
    lone = _creature(state, "Lone", 3, 3)

    effect = FightEffect(fighter_kind="creature_you_control", other_kind="creature",
                         distinct=True)
    assert effect.target_specs[1].distinct_from_others is True
    _resolve(engine, effect, [lone, lone])

    assert lone.damage_marked == 0


def test_an_ability_offers_both_requirements_of_a_two_target_fight():
    """Ulvenwald Tracker's "{1}{G}, {T}: Target creature you control fights
    another target creature." — one effect, two rounds of targeting."""
    engine, state, p1, _ = _engine()
    tracker = GameObject(_named("Ulvenwald Tracker"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(tracker)
    tracker.summoning_sick = False
    state.add_to_battlefield(tracker)
    mine = _creature(state, "Mine", 2, 2)
    theirs = _creature(state, "Theirs", 2, 2, controller="p2")
    p1.mana_pool.add("G", 2)

    action = next(
        a for a in engine.legal_actions(p1)
        if a["type"] == "activate_ability" and a["instance_id"] == tracker.instance_id
    )
    assert [req["kind"] for req in action["targets"]] == ["creature_you_control", "creature"]
    assert action["targets"][1]["distinct_from_others"] is True

    engine.activate_ability(p1, tracker, 0, targets=[mine, theirs])
    engine.resolve_until_stable()
    # 2 damage each way is lethal to both 2/2s (RULE 704.5g), so the trade
    # itself is the proof each requirement resolved against its own pick.
    assert mine not in state.battlefield and theirs not in state.battlefield


def test_a_declined_optional_target_never_turns_into_a_self_fight():
    """A caller that sends a *flat* list can't say which "up to one" it
    declined (`partition_targets` returns None), so the pronoun clause would
    otherwise read the previous clause's pick as its own target."""
    from mtg_analyzer.game.effects.core import GameContext

    engine, state, _, _ = _engine()
    pumped = _creature(state, "Pumped", 3, 3)

    context = GameContext(state, engine.rules)
    context.previous_targets = [pumped]  # what the pump clause chose
    FightEffect(fighter_kind="previous_target",
                other_kind="creature_you_dont_control", optional=True).apply(
        context, [pumped]  # the flat list's only entry — the *pump's* target
    )

    assert pumped.damage_marked == 0


def test_rabid_bite_deals_one_sided_damage_equal_to_power():
    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 4, 4)
    theirs = _creature(state, "Theirs", 2, 5, controller="p2")
    spell = GameObject(_named("Rabid Bite"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 2)

    engine.cast_spell(p1, spell, targets=[mine, theirs])
    engine.resolve_until_stable()

    assert theirs.damage_marked == 4
    assert mine.damage_marked == 0  # one-sided: no damage back


def test_a_dead_creature_still_deals_damage_equal_to_its_power():
    """RULE 608.2h last known information: the commonest printed form of this
    clause is a dies trigger, where the dealer is already in the graveyard as
    the ability resolves — unlike a fight, it isn't required to be around."""
    from mtg_analyzer.game.effects.core import DamageEqualToPowerEffect, GameContext

    engine, state, p1, p2 = _engine()
    dead = _creature(state, "Dead", 5, 5)
    state.battlefield.remove(dead)
    p1.graveyard.append(dead)

    DamageEqualToPowerEffect(target_kind="any", source=dead).apply(
        GameContext(state, engine.rules), [p2]
    )

    assert p2.life == 15


def test_damage_equal_to_power_can_hit_each_opponent():
    from mtg_analyzer.game.effects.core import DamageEqualToPowerEffect, GameContext

    engine, state, p1, p2 = _engine()
    mine = _creature(state, "Mine", 3, 3)

    effect = DamageEqualToPowerEffect(selector="each_opponent", target_kind=None, source=mine)
    assert effect.target_specs == []
    effect.apply(GameContext(state, engine.rules), None)

    assert (p1.life, p2.life) == (20, 17)


def test_the_one_sided_family_parses_off_real_cards():
    for name, params in [
        ("Rabid Bite", {"dealer_kind": "creature_you_control",
                        "target_kind": "creature_you_dont_control"}),
        # "target creature or planeswalker you don't control" — both halves
        # of the union kept (PAR-127).
        ("Bite Down", {"dealer_kind": "creature_you_control",
                       "target_kind": "creature_or_planeswalker_you_dont_control"}),
    ]:
        result = parse_oracle(_named(name))
        assert result.modeled, name
        effects = [e for spec in result.specs for e in spec.effects]
        assert [e.type for e in effects] == ["damage_equal_to_power"], name
        assert effects[0].params == params, name


def test_clear_shot_chains_a_pump_into_a_one_sided_bite():
    result = parse_oracle(_named("Clear Shot"))
    assert result.modeled
    effects = [e for spec in result.specs for e in spec.effects]
    assert [e.type for e in effects] == ["pump", "damage_equal_to_power"]
    assert effects[1].params["dealer_kind"] == "previous_target"


def test_a_posted_action_can_carry_the_per_requirement_partition():
    """The wire contract `gameBoardView.js` now uses: `target_groups` says
    which pick belongs to which requirement, which is the only way to express
    a *declined* "up to one" (a flat list would silently shift)."""
    from mtg_analyzer.services.game_session import GameSession

    engine, state, p1, _ = _engine()
    session = GameSession(engine)
    mine = _creature(state, "Mine", 1, 1)
    theirs = _creature(state, "Theirs", 2, 3, controller="p2")
    spell = GameObject(_named("Epic Confrontation"), owner_id=p1.id, zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("G", 2)
    state.current_step = "main1"

    session.apply_action({
        "type": "cast_spell",
        "instance_id": spell.instance_id,
        "target_groups": [
            [{"instance_id": mine.instance_id}],
            [{"instance_id": theirs.instance_id}],
        ],
    })
    session.engine.resolve_until_stable()

    assert (mine.power, mine.toughness) == (2, 3)
    assert theirs.damage_marked == 2


def test_a_bot_partitions_its_own_picks_and_honours_another():
    """A bot plays through the same client surface, so it has to send the
    same partition — and respect RULE 109.5 when the offer says "another"."""
    from mtg_analyzer.services.bots import GreedyBot

    action = {
        "type": "cast_spell",
        "requires_target": True,
        "targets": [
            {"kind": "creature_you_control", "count": 1, "optional": False,
             "options": [{"instance_id": 1, "name": "Mine"}]},
            {"kind": "creature", "count": 1, "optional": False, "distinct_from_others": True,
             "options": [{"instance_id": 1, "name": "Mine"},
                         {"instance_id": 2, "name": "Theirs"}]},
        ],
    }
    view = {"state": {"battlefield": []}}
    groups = GreedyBot("b1").pick_target_groups(view, action)

    assert groups == [[{"instance_id": 1, "name": "Mine"}], [{"instance_id": 2, "name": "Theirs"}]]


def test_a_pronoun_needs_a_creature_antecedent_to_claim_anything():
    """The gate `_announces_creature_target` enforces: a preceding clause
    that chose no creature leaves the pronoun unbound, so the card fails
    closed instead of pointing at nothing."""
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(
        "target creature you control gets +1/+1 until end of turn. "
        "it fights target creature you don't control"
    ) is not None
    assert parse_effect_body(
        "draw a card. it fights target creature you don't control"
    ) is None


# ---------------------------------------------------------------------------
# PAR-1: "choose N target creatures [+constraint]. Verb those creatures…" —
# the quantified-group sibling of the pair-pronoun family above (Run Away
# Together-shaped), sharing its "announce, then read back by pronoun"
# machinery but with one group instead of two independently-kinded picks.
# ---------------------------------------------------------------------------


def test_choose_targets_group_clause_is_recognized():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    specs = parse_effect_body("choose 2 target creatures controlled by different players")
    assert specs == [
        EffectSpec("choose_targets", {"kinds": ["creature"], "count": 2, "distinct_controllers": True})
    ]


def test_choose_targets_group_without_constraint_is_recognized():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    specs = parse_effect_body("choose 2 target creatures")
    assert specs == [EffectSpec("choose_targets", {"kinds": ["creature"], "count": 2})]


def test_return_previous_group_needs_a_group_antecedent():
    """Same `_announces_creature_target` gate as the fight/pump pronoun
    family — a "return those creatures" clause with no preceding "choose N
    target creatures" clause stays unclaimed rather than pointing at
    nothing."""
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(
        "choose 2 target creatures controlled by different players. "
        "return those creatures to their owners' hands"
    ) is not None
    assert parse_effect_body(
        "draw a card. return those creatures to their owners' hands"
    ) is None


def test_run_away_together_is_fully_modeled():
    from mtg_analyzer.parser.oracle import UNMODELED, parse_oracle

    card = _card(
        "Run Away Together Shaped",
        type_line="Instant",
        oracle_text=(
            "Choose two target creatures controlled by different players. "
            "Return those creatures to their owners' hands."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []
