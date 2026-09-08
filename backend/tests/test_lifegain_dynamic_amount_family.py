"""RULE 119.3 "whenever you gain life, <effect>" lifegain-payoff family,
the *dynamic*-amount half ("that much"/"that many", reading the firing
LIFE_GAINED event's own `amount` — `GameContext.trigger_event`) that
`test_batch_2026_08_05_attack_pump_grant_prevent.py`'s Ajani's Pridemate
case (a literal fixed amount) doesn't cover:

* `LoseLifeEffect`/`AddCountersEffect`/`PumpEffect.amount_from_trigger_event`
  — the same "read this firing's own payload" idiom `AddManaEffect.
  amount_from_trigger_event` already used for Raphael, Ninja Destroyer.
* The granted-ability sibling: `LIFE_GAINED` joins `_GRANTABLE_TRIGGER_
  EVENTS` as a second player-subject grantable event alongside `STEP_BEGIN`
  (`game/continuous.py`'s `_PLAYER_SUBJECT_GRANTED_EVENTS`), so "Equipped/
  enchanted creature has 'Whenever you gain life, ~ gets +X/+X …'" (Field-
  Tested Frying Pan/Light of Promise/Sunbond) resolves "you" against the
  *equipped creature's own controller*, not the Equipment's.
* `AttachEffect`'s `target_kind="created"` mode — "create a token and
  attach ~ to it." (Auxiliary Boosters/Field-Tested Frying Pan's own first
  sentence), reading `GameContext.created_objects`.
* The adversarial case that shipped alongside all of the above: the new
  `add_counters_from_trigger_amount` handler's ``(?P<selfref>...)`` branch
  matches the bare pronoun "it", which is only safe under a genuinely
  self/player-subject trigger (`EffectHandler.self_subject_only=True`) —
  under a *group*-subject trigger ("whenever a creature you control deals
  combat damage to a player, put that many +1/+1 counters on it" —
  Necropolis Regent) "it" means whichever group member fired it, so the
  clause must stay unclaimed rather than silently buff the wrong object.

Reference: mtg_analyzer/game/effects/core.py, mtg_analyzer/game/continuous.py,
mtg_analyzer/parser/oracle/{segmenter,catalogue/{handlers,static_handlers}}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _etb(obj):
    return GameEvent(
        EventType.ENTERS_BATTLEFIELD,
        instance_id=obj.instance_id,
        controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    )


# ---------------------------------------------------------------------------
# Parse-level: the dynamic-amount clauses themselves
# ---------------------------------------------------------------------------


def test_lose_life_that_much_parses_with_self_subject():
    specs = match_clause("target opponent loses that much life", self_subject=True)
    assert specs == [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "amount"})]


def test_add_counters_that_many_self_parses_with_self_subject():
    specs = match_clause("put that many +1/+1 counters on ~", self_subject=True)
    assert specs == [EffectSpec("add_counters", {"kind": "+1/+1", "amount_from_trigger_event": "amount"})]


def test_add_counters_that_many_self_is_unclaimed_without_self_subject():
    # The exact same clause text, but the caller didn't assert a self/
    # player-subject context — must not guess.
    assert match_clause("put that many +1/+1 counters on ~") is None


def test_group_subject_it_clause_is_unclaimed_not_mismodeled():
    # Necropolis Regent-shaped: "it" means the group member that dealt the
    # damage, not this ability's own source — the segmenter never offers
    # self_subject=True for this trigger shape, so the clause must stay
    # unclaimed rather than silently buffing the wrong object.
    assert match_clause("put that many +1/+1 counters on it", self_subject=False) is None


def test_necropolis_regent_is_still_unmodeled():
    card = Card(
        id="Necropolis Regent", name="Necropolis Regent", type_line="Creature — Dragon",
        is_creature=True, power=4, toughness=4,
        oracle_text=(
            "Flying\n"
            "Whenever a creature you control deals combat damage to a player, "
            "put that many +1/+1 counters on it."
        ),
    )
    assert parse_oracle(card).modeled is False


# ---------------------------------------------------------------------------
# Execute: LoseLifeEffect.amount_from_trigger_event (Sanguine Bond-shaped)
# ---------------------------------------------------------------------------


def test_sanguine_bond_drains_the_opponent_for_the_amount_gained():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    _bf(state, Card(
        id="Test Sanguine Bond", name="Test Sanguine Bond", type_line="Enchantment",
        oracle_text="Whenever you gain life, target opponent loses that much life.",
    ))

    eng.rules.gain_life(p1, 5)
    assert eng.rules.put_triggers_on_stack() == 1
    # "target opponent" resolves to the engine's broad "player" target kind
    # (a documented simplification, subgrammars._TARGET_ROWS), so both
    # players are offered — pick the actual opponent explicitly.
    option = next(o for o in state.pending_choice["options"] if o["id"] == "p2")
    eng.rules.resolve_trigger_target_choice(option["id"])
    eng.rules.resolve_top_of_stack()

    assert p1.life == 25
    assert p2.life == 15


# ---------------------------------------------------------------------------
# Execute: AddCountersEffect.amount_from_trigger_event (Ageless Entity-shaped)
# ---------------------------------------------------------------------------


def test_ageless_entity_gets_that_many_counters():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    entity = _bf(state, Card(
        id="Test Ageless Entity", name="Test Ageless Entity", type_line="Creature — Hydra",
        is_creature=True, power=0, toughness=0,
        oracle_text="Whenever you gain life, put that many +1/+1 counters on this creature.",
    ))

    eng.rules.gain_life(p1, 4)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    continuous.recompute(state)

    assert entity.plus_one_counters == 4


def test_zero_life_gain_replacement_adds_no_counters():
    # RULE 118.4 — a 0-life gain (e.g. fully replaced away) triggers nothing
    # to place, so `amount_from_trigger_event` reading 0 must not crash or
    # place a spurious zero-counter.
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    entity = _bf(state, Card(
        id="Test Ageless Entity 0", name="Test Ageless Entity 0", type_line="Creature — Hydra",
        is_creature=True, power=0, toughness=0,
        oracle_text="Whenever you gain life, put that many +1/+1 counters on this creature.",
    ))

    eng.rules.gain_life(p1, 0)
    assert eng.rules.put_triggers_on_stack() == 0
    continuous.recompute(state)
    assert entity.plus_one_counters == 0


# ---------------------------------------------------------------------------
# Execute: the granted-ability path (Field-Tested Frying Pan-shaped) —
# LIFE_GAINED as a player-subject grantable event, PumpEffect.
# amount_from_trigger_event, and AttachEffect's target_kind="created".
# ---------------------------------------------------------------------------


_FRYING_PAN_TEXT = (
    "When this Equipment enters, create a Food token, then create a 1/1 "
    "white Halfling creature token and attach this Equipment to it.\n"
    'Equipped creature has "Whenever you gain life, this creature gets '
    '+X/+X until end of turn, where X is the amount of life you gained."\n'
    "Equip {2}"
)


def test_field_tested_frying_pan_is_fully_modeled():
    card = Card(id="Field-Tested Frying Pan", name="Field-Tested Frying Pan",
                type_line="Artifact — Equipment", keywords=["Equip"], oracle_text=_FRYING_PAN_TEXT)
    assert parse_oracle(card).modeled is True


def test_frying_pan_etb_creates_food_then_halfling_and_attaches():
    eng = _engine()
    state = eng.state
    pan = _bf(state, Card(id="Test Frying Pan", name="Test Frying Pan",
                           type_line="Artifact — Equipment", keywords=["Equip"], oracle_text=_FRYING_PAN_TEXT))

    state.fire_event(_etb(pan))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    battlefield_names = sorted(o.name for o in state.battlefield)
    assert battlefield_names == sorted(["Test Frying Pan", "Food", "Halfling"])
    halfling = next(o for o in state.battlefield if o.name == "Halfling")
    assert pan.attached_to == halfling.instance_id


def test_frying_pan_granted_ability_pumps_the_equipped_creature_by_life_gained():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    pan = _bf(state, Card(id="Test Frying Pan 2", name="Test Frying Pan 2",
                           type_line="Artifact — Equipment", keywords=["Equip"], oracle_text=_FRYING_PAN_TEXT))
    bear = _bf(state, Card(id="Grizzly Bears", name="Grizzly Bears", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2))

    eng.rules.attach_to_target(pan, bear)
    continuous.recompute(state)

    eng.rules.gain_life(p1, 3)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    continuous.recompute(state)

    assert bear.power == 5
    assert bear.toughness == 5


def test_frying_pan_granted_ability_does_not_fire_for_a_different_controllers_lifegain():
    # The granted "whenever you gain life" means the *equipped creature's*
    # controller, not the Equipment's — control-changing edge case covered
    # by simply attaching to an opponent's creature and having the
    # Equipment's own controller (p1) gain life instead.
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    pan = _bf(state, Card(id="Test Frying Pan 3", name="Test Frying Pan 3",
                           type_line="Artifact — Equipment", keywords=["Equip"], oracle_text=_FRYING_PAN_TEXT))
    opp_bear = _bf(state, Card(id="Opp Bear", name="Opp Bear", type_line="Creature — Bear",
                                is_creature=True, power=2, toughness=2), controller="p2")

    eng.rules.attach_to_target(pan, opp_bear)
    continuous.recompute(state)

    eng.rules.gain_life(p1, 3)  # the Equipment's controller, not the bear's
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# Execute: AttachEffect target_kind="created" on its own (Auxiliary
# Boosters-shaped, no lifegain payoff involved)
# ---------------------------------------------------------------------------


def test_create_token_and_attach_targets_the_just_created_token():
    eng = _engine()
    state = eng.state
    booster = _bf(state, Card(
        id="Test Auxiliary Boosters", name="Test Auxiliary Boosters",
        type_line="Artifact — Equipment", keywords=["Equip"],
        oracle_text=(
            "When this Equipment enters, create a 2/2 colorless Robot "
            "artifact creature token and attach this Equipment to it.\n"
            "Equipped creature gets +1/+2 and has flying.\n"
            "Equip {3}"
        ),
    ))

    state.fire_event(_etb(booster))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    robot = next(o for o in state.battlefield if o.name == "Robot")
    assert booster.attached_to == robot.instance_id
