"""Tests for RULE 603.1 trigger-condition *subject* scoping (docs/09).

Covers the fix for a real over-firing bug: the oracle-text segmenter used to
map a trigger condition phrase to a bare `EventType` with no subject scoping
at all, so a parsed "When ~ enters the battlefield, draw a card." bound a
`TriggeredAbility` that fired when *any* permanent entered, not just its own
source. Two layers:

* `parser/oracle/segmenter.py`'s `_trigger_condition` — the condition phrase
  → `{"subject": "self"}` / `{"subject": "group", ...}` dict (or ``None``,
  fail-closed, for anything not one of those two shapes).
* `game/effect_binder.py`'s `_subject_condition` — that dict → the
  `TriggeredAbility.check_trigger` predicate, reading the identity/type
  facts the engine's event-firing sites now stamp onto `ENTERS_BATTLEFIELD`/
  `DIES`/`ATTACKS`/`BLOCKS` events (`instance_id`, `object_types`, and — for
  `DIES` — `controller_id`).
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _trigger_condition


# ---------------------------------------------------------------------------
# Card factories
# ---------------------------------------------------------------------------


def perm(name, text, **kw):
    return Card(
        id=name,
        name=name,
        type_line=kw.pop("type_line", "Creature — Test"),
        is_creature=True,
        power=kw.pop("power", 1),
        toughness=kw.pop("toughness", 1),
        mana_cost_string="",
        converted_mana_cost=0,
        oracle_text=text,
    )


def vanilla(name):
    return Card(
        id=name, name=name, type_line="Creature — Test", is_creature=True,
        power=1, toughness=1, mana_cost_string="", converted_mana_cost=0,
    )


def land_card(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


# ---------------------------------------------------------------------------
# SEGMENTER: condition phrase → condition dict
# ---------------------------------------------------------------------------


def test_self_subject_condition_shapes():
    for cond in (
        "~ enters the battlefield",
        "~ enters",
        "this creature enters the battlefield",
        "this permanent enters",
        "this artifact enters the battlefield",
        "this enchantment enters",
        "this land enters the battlefield",
        "this equipment enters",
        "~ dies",
        "this creature dies",
        "~ attacks",
        "this creature attacks",
        "~ blocks",
        "this creature blocks",
    ):
        assert _trigger_condition(cond) == {"subject": "self"}, cond


def test_group_subject_condition_shapes():
    assert _trigger_condition("a creature enters the battlefield under your control") == {
        "subject": "group", "type": "creature", "controller": "you", "other": False,
    }
    assert _trigger_condition("another creature enters the battlefield under your control") == {
        "subject": "group", "type": "creature", "controller": "you", "other": True,
    }
    assert _trigger_condition("a creature you control enters") == {
        "subject": "group", "type": "creature", "controller": "you", "other": False,
    }
    assert _trigger_condition("another creature you control enters") == {
        "subject": "group", "type": "creature", "controller": "you", "other": True,
    }
    assert _trigger_condition("a creature dies") == {
        "subject": "group", "type": "creature", "controller": "any", "other": False,
    }
    assert _trigger_condition("another creature dies") == {
        "subject": "group", "type": "creature", "controller": "any", "other": True,
    }
    assert _trigger_condition("a creature you control dies") == {
        "subject": "group", "type": "creature", "controller": "you", "other": False,
    }
    assert _trigger_condition("a creature you control attacks") == {
        "subject": "group", "type": "creature", "controller": "you", "other": False,
    }


def test_unrecognized_subject_stays_unclaimed():
    # A trigger condition this grammar doesn't model must fail closed —
    # `None`, not a guessed scope — so the whole ability is left unclaimed
    # (never a wrongly-scoped, or unscoped/over-firing, ability).
    assert _trigger_condition("you cast a spell") is None


def test_whenever_you_cast_a_spell_stays_unmodeled():
    r = parse_oracle(perm("Caster", "Whenever you cast a spell, draw a card."))
    assert r.coverage == UNMODELED
    assert not any(s.ability_kind == "triggered" for s in r.specs)


# ---------------------------------------------------------------------------
# BINDER + ENGINE: end-to-end over-firing fix
# ---------------------------------------------------------------------------


def _new_engine(*players):
    return GameEngine.new_game(list(players), starting_hand=0)


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


def test_self_etb_trigger_fires_only_for_its_own_entry():
    eng = _new_engine(("p1", "Alice", [land_card()] * 20))
    p1 = _ready_main_phase(eng)

    visionary = GameObject(
        perm("Visionary", "When Visionary enters the battlefield, draw a card."),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(visionary)
    p1.add_to_zone(visionary, Zone.HAND)
    hand_before = len(p1.hand)
    eng.cast_spell(p1, visionary)
    eng.resolve_until_stable()
    assert visionary in eng.state.battlefield
    # Casting removed it from hand (-1); its own ETB trigger drew 1 (+1).
    assert len(p1.hand) == hand_before - 1 + 1

    # A second, unrelated creature entering afterward must NOT re-trigger
    # Visionary's ability (the over-firing bug this scoping fixes).
    bystander = GameObject(vanilla("Bystander"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(bystander)
    p1.add_to_zone(bystander, Zone.HAND)
    hand_before2 = len(p1.hand)
    eng.cast_spell(p1, bystander)
    eng.resolve_until_stable()
    assert bystander in eng.state.battlefield
    assert len(p1.hand) == hand_before2 - 1  # no extra draw from Visionary


def _fire_dies(eng, obj):
    eng.state.fire_event(
        GameEvent(
            EventType.DIES,
            object=obj.name,
            owner_id=obj.owner_id,
            controller_id=obj.controller_id,
            instance_id=obj.instance_id,
            object_types=sorted(obj.type_words),
        )
    )


def test_self_dies_trigger_fires_only_for_its_own_death():
    # `DIES` is fired only *after* `RulesEngine._move_to_graveyard` has
    # already removed the object from the battlefield (RULE 603.6a's
    # "look back in time" for leaves-the-battlefield triggers isn't modeled —
    # a separate, pre-existing gap from the subject-scoping this test
    # covers), so `_collect_triggers`' battlefield scan wouldn't see a
    # departed object's own trigger either way. Firing the `DIES` event
    # directly, with the object still on the battlefield, isolates exactly
    # what's under test here: the "self" subject predicate reads the event's
    # `instance_id`, not "did this object literally still exist".
    eng = _new_engine(("p1", "Alice", [land_card()] * 20))
    p1 = _ready_main_phase(eng)

    reaper = GameObject(
        perm("Reaper", "When Reaper dies, draw a card."), owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    reaper.summoning_sick = False
    eng.state.add_to_battlefield(reaper)
    bind_from_catalogue(reaper)

    other = GameObject(vanilla("Other"), owner_id="p1", zone=Zone.BATTLEFIELD)
    other.summoning_sick = False
    eng.state.add_to_battlefield(other)

    # A different creature "dying" must not trigger Reaper's own "when this
    # dies" ability (the over-firing bug this scoping fixes).
    hand_before = len(p1.hand)
    _fire_dies(eng, other)
    eng.resolve_until_stable()
    assert len(p1.hand) == hand_before

    # Reaper's own DIES event does trigger it.
    _fire_dies(eng, reaper)
    eng.resolve_until_stable()
    assert len(p1.hand) == hand_before + 1


def test_soul_warden_shaped_group_trigger():
    eng = _new_engine(
        ("p1", "Alice", [land_card()] * 20),
        ("p2", "Bob", [land_card()] * 20),
    )
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")

    warden = GameObject(
        perm(
            "Warden",
            "Whenever another creature enters the battlefield under your control, "
            "you gain 1 life.",
        ),
        owner_id="p1", zone=Zone.HAND,
    )
    life_start = p1.life
    bind_from_catalogue(warden)
    p1.add_to_zone(warden, Zone.HAND)
    eng.cast_spell(p1, warden)
    eng.resolve_until_stable()
    assert warden in eng.state.battlefield
    # Its own entry must not gain life ("another creature").
    assert p1.life == life_start

    # Another creature entering under p1's control gains 1 life.
    ally = GameObject(vanilla("Ally"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(ally)
    p1.add_to_zone(ally, Zone.HAND)
    eng.cast_spell(p1, ally)
    eng.resolve_until_stable()
    assert p1.life == life_start + 1

    # An opponent's creature entering must not gain p1 any life.
    opp_life_start = p2.life
    eng.rules.create_token(controller_id="p2", token_card=vanilla("Opp Token"))
    eng.resolve_until_stable()
    assert p1.life == life_start + 1
    assert p2.life == opp_life_start
