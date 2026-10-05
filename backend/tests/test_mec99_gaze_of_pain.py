"""MEC-99 — Gaze of Pain's reflexive "have it deal damage equal to its power"
grant plus RULE 510.1e's "assigns no combat damage" flag.

"Until end of turn, whenever a creature you control attacks and isn't
blocked, you may choose to have it deal damage equal to its power to a
target creature. If you do, it assigns no combat damage this turn." is a
RULE 603.7a turn-scoped trigger (PAR-124) whose group-subject "it" both
deals the damage (`effects.DamageEqualToPowerEffect`'s new
``dealer_kind="trigger_subject"``) and gets flagged out of the real combat
damage step (`PreventCombatDamageDealtEffect`'s new
``subject="trigger_subject"``) — both pre-existing primitives, widened to
read the RULE 603.1 group-subject referent instead of only the ability's own
source. Parse tests pin the recognition; execute tests attack for real,
answer the "you may" choice, and check both halves against a live
`GameEngine`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DamageEqualToPowerEffect, PreventCombatDamageDealtEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle

GAZE_OF_PAIN = (
    "Until end of turn, whenever a creature you control attacks and isn't blocked, you may "
    "choose to have it deal damage equal to its power to a target creature. If you do, it "
    "assigns no combat damage this turn."
)


def _sorcery(oracle: str, name: str = "Gaze of Pain") -> Card:
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=oracle,
                is_sorcery=True, converted_mana_cost=0, mana_cost_string="")


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_gaze_of_pain_is_modeled():
    result = parse_oracle(_sorcery(GAZE_OF_PAIN))
    assert result.coverage == MODELED, result.unclaimed
    [spec] = result.specs
    assert spec.ability_kind == "spell_effect"
    [effect] = spec.effects
    assert effect.type == "create_turn_trigger"
    trigger = effect.params["trigger"]
    assert trigger["event"] == "ATTACKER_UNBLOCKED"
    assert trigger["condition"]["subject"] == "group"
    [optional] = effect.params["effects"]
    assert optional["type"] == "optional"
    damage, prevent = optional["params"]["effects"]
    assert damage == {
        "type": "damage_equal_to_power",
        "params": {"dealer_kind": "trigger_subject", "target_kind": "creature"},
    }
    assert prevent == {
        "type": "prevent_combat_damage_dealt",
        "params": {"subject": "trigger_subject"},
    }


def test_the_ability_itself_is_not_ability_level_optional():
    # The "you may" is RULE 601.2b's resolve-time choice (an `optional` node
    # around the two effects), not RULE 603.5's whole-ability "you may" —
    # `_peel_optional` must leave this antecedent alone (guarded via
    # `handlers._MAY_EFFECT_THEN_ANTECEDENT_PHRASES`) or the trigger would
    # ask "put this on the stack at all?" instead of "deal the damage?".
    result = parse_oracle(_sorcery(GAZE_OF_PAIN))
    [spec] = result.specs
    assert spec.effects[0].params["optional"] is False


def test_a_self_subject_variant_is_not_claimed():
    # A hypothetical "~ attacks and isn't blocked" (self, not group) shares
    # no row with the group-subject one above — fails closed rather than
    # guessed, same as every other `group_subject_only` family.
    text = GAZE_OF_PAIN.replace("a creature you control attacks", "~ attacks")
    result = parse_oracle(_sorcery(text))
    assert result.coverage != MODELED


# ---------------------------------------------------------------------------
# Engine primitives, in isolation
# ---------------------------------------------------------------------------


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def _creature(engine, name, power, toughness, controller="p1"):
    card = Card(id=name, name=name, type_line="Creature — Beast", is_creature=True,
                power=power, toughness=toughness)
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    return obj


class _FakeContext:
    """The bare minimum `GameContext` surface `DamageEqualToPowerEffect`/
    `PreventCombatDamageDealtEffect` read: ``state`` and ``trigger_event``."""

    def __init__(self, engine, instance_id):
        self.state = engine.state
        self.engine = engine
        self.trigger_event = {"instance_id": instance_id}

    def deal_damage(self, target, amount, source):
        self.engine.rules.deal_damage(target, amount, source)


def test_damage_equal_to_power_reads_the_trigger_subject_not_the_source():
    engine = _engine()
    attacker = _creature(engine, "Raider", power=4, toughness=4)
    victim = _creature(engine, "Victim", power=1, toughness=6, controller="p2")
    fake_source = _creature(engine, "Gaze of Pain (spell)", power=0, toughness=0)
    effect = DamageEqualToPowerEffect(dealer_kind="trigger_subject", target_kind="creature")
    effect.source = fake_source
    context = _FakeContext(engine, attacker.instance_id)
    effect.apply(context, targets=[victim])
    assert victim.damage_marked == 4  # the attacker's power, not the spell's


def test_prevent_combat_damage_dealt_flags_the_trigger_subject_not_the_source():
    engine = _engine()
    attacker = _creature(engine, "Raider", power=4, toughness=4)
    fake_source = _creature(engine, "Gaze of Pain (spell)", power=0, toughness=0)
    effect = PreventCombatDamageDealtEffect(subject="trigger_subject")
    effect.source = fake_source
    context = _FakeContext(engine, attacker.instance_id)
    effect.apply(context)
    assert getattr(attacker, "temp_prevent_combat_damage_dealt", False) is True
    assert getattr(fake_source, "temp_prevent_combat_damage_dealt", False) is False


def test_the_flagged_attacker_assigns_no_real_combat_damage():
    engine = _engine()
    p2 = engine.state.player_by_id("p2")
    attacker = _creature(engine, "Raider", power=4, toughness=4)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    attacker.temp_prevent_combat_damage_dealt = True
    life = p2.life
    engine._deal_combat_damage_step(first_strike_step=False)
    assert p2.life == life  # RULE 510.1e: no combat damage assigned at all


def test_an_unflagged_attacker_still_deals_its_combat_damage():
    engine = _engine()
    p2 = engine.state.player_by_id("p2")
    attacker = _creature(engine, "Raider", power=4, toughness=4)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    life = p2.life
    engine._deal_combat_damage_step(first_strike_step=False)
    assert p2.life == life - 4


# ---------------------------------------------------------------------------
# End to end: cast the sorcery, attack for real, answer the choice
# ---------------------------------------------------------------------------


def _cast_gaze_of_pain(engine, controller="p1"):
    state = engine.state
    player = state.player_by_id(controller)
    spell = GameObject(_sorcery(GAZE_OF_PAIN), owner_id=controller, zone=Zone.HAND)
    spell.controller_id = controller
    bind_from_catalogue(spell)
    player.hand.append(spell)
    state.current_step = "main1"
    engine.rules.cast_spell(player, spell)
    engine.resolve_until_stable()


def _attack_unblocked(engine, attacker, controller="p1"):
    state = engine.state
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.player_by_id(controller), [attacker])
    engine._fire_unblocked_events()
    engine.resolve_until_stable()


def test_accepting_deals_damage_and_suppresses_the_real_combat_damage():
    engine = _engine()
    state = engine.state
    p2 = state.player_by_id("p2")
    attacker = _creature(engine, "Raider", power=3, toughness=3)
    attacker.summoning_sick = False
    victim = _creature(engine, "Victim", power=1, toughness=6, controller="p2")

    _cast_gaze_of_pain(engine)
    _attack_unblocked(engine, attacker)

    # RULE 601.2c: the recipient is announced when the trigger goes on the
    # stack, before the "you may" is even asked.
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    target_option = next(o for o in choice["options"] if o["instance_id"] == victim.instance_id)
    engine.rules.resolve_choice(target_option["id"])
    engine.resolve_until_stable()

    assert state.pending_choice["kind"] == "composite_optional"
    engine.rules.resolve_choice("yes")
    engine.resolve_until_stable()

    assert victim.damage_marked == 3  # Raider's power
    assert getattr(attacker, "temp_prevent_combat_damage_dealt", False) is True

    attacker.combat_defender = {"kind": "player", "id": "p2"}
    life = p2.life
    engine._deal_combat_damage_step(first_strike_step=False)
    assert p2.life == life  # the attacker assigns no combat damage this turn


def test_declining_does_neither():
    engine = _engine()
    state = engine.state
    p2 = state.player_by_id("p2")
    attacker = _creature(engine, "Raider", power=3, toughness=3)
    attacker.summoning_sick = False
    victim = _creature(engine, "Victim", power=1, toughness=6, controller="p2")

    _cast_gaze_of_pain(engine)
    _attack_unblocked(engine, attacker)

    target_option = next(
        o for o in state.pending_choice["options"] if o["instance_id"] == victim.instance_id
    )
    engine.rules.resolve_choice(target_option["id"])
    engine.resolve_until_stable()

    assert state.pending_choice["kind"] == "composite_optional"
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()

    assert victim.damage_marked == 0
    assert getattr(attacker, "temp_prevent_combat_damage_dealt", False) is False

    attacker.combat_defender = {"kind": "player", "id": "p2"}
    life = p2.life
    engine._deal_combat_damage_step(first_strike_step=False)
    assert p2.life == life - 3  # ordinary combat damage, unsuppressed
