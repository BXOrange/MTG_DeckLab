"""Second saved-deck-priority batch (2026-08-05), continuing the first
(2026-08-04)'s cross-referenced ranking. Five more clusters:

* **"Whenever you gain life, <effect>."** (RULE 119.3, Ajani's Pridemate/
  Archangel of Thune-shaped) — `EventType.LIFE_GAINED` already existed as
  the post-replacement trigger source; only the oracle-text recognition
  (`segmenter._PLAYER_TRIGGER_CONDITIONS`) and the matching
  `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` entry were missing.
* **"destroy/exile target artifact, enchantment[, or land]" (2+ noun
  compounds)** (RULE 115 — Acidic Slime/Aftershock-shaped) — a general N-way
  sibling of the existing 2-way "target artifact or enchantment" row in
  `subgrammars._TARGET_ROWS`, same broad ``"permanent"`` kind that row
  already accepts.
* **"Commander creatures you own have \"<ability>\""** (cEDH support cards —
  Clan Crafter/Street Urchin-shaped for the subset `_quoted_ability_grant_
  effects` can already parse) — a new `affects="commander_creatures_you_own"`
  selector (ownership, not control — `GameObject.owner_id`) plus a dedicated
  fixed-phrase recognizer. Also **fixes a latent crash**: a quoted inner
  ability with a *compound* self-trigger ("enters or leaves the battlefield")
  stamps a list-valued `trigger["event"]`, and `_quoted_ability_grant_
  effects`'s `event not in _GRANTABLE_TRIGGER_EVENTS` membership check
  raised `TypeError: unhashable type: 'list'` on it — this batch's own new
  dispatch was the first caller to reach that shape, but the bug was already
  reachable through the pre-existing `_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_
  GRANT_RE` paths too.
* **"Whenever ~ attacks, it gets +N/+N [and gains `<keyword>`] until end of
  turn."** (Borderland Marauder/Charging Paladin-shaped — a genuinely common
  pre-modern template) — the bare-pronoun ("it", not "~") sibling of the
  existing untargeted self-pump row, `self_subject_only`-gated. The "for
  each `<count>`" scaling variant (Akroan Hoplite's actual text) stays
  unclaimed — `PumpEffect` has no count-scaled amount parameter yet.
* **"Prevent the next N damage that would be dealt to any target this
  turn."** (RULE 615 — Alabaster Wall/Amulet of Kroog-shaped, usually a
  `{cost}:` activated ability) — the plain single-target sibling of the
  already-shipped "…to any number of targets, divided as you choose" row;
  `PreventDamageEffect`'s `target_kind` branch already supported exactly
  this shape with no `divided` flag.

Reference: mtg_analyzer/parser/oracle/{segmenter,catalogue/{handlers,
static_handlers,subgrammars}}.py, mtg_analyzer/game/{effects,continuous,
effect_binder}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name="Grizzly Bears", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _bf(state, card, controller="p1", commander=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.is_commander = commander
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# "Whenever you gain life, <effect>."
# ---------------------------------------------------------------------------


def test_ajanis_pridemate_full_card_is_modeled():
    card = Card(
        id="Ajani's Pridemate", name="Ajani's Pridemate", type_line="Creature — Cat Soldier",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you gain life, put a +1/+1 counter on this creature.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.trigger == {"event": "LIFE_GAINED", "condition": {"subject": "you"}}


def test_life_gain_trigger_executes_and_adds_a_counter():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    pridemate_card = Card(
        id="Test Pridemate", name="Test Pridemate", type_line="Creature — Cat",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you gain life, put a +1/+1 counter on this creature.",
    )
    pridemate = _bf(state, pridemate_card)

    eng.rules.gain_life(p1, 3)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    continuous.recompute(state)
    assert pridemate.plus_one_counters == 1


def test_life_gain_trigger_does_not_fire_for_the_opponent():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    pridemate_card = Card(
        id="Test Pridemate 2", name="Test Pridemate 2", type_line="Creature — Cat",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you gain life, put a +1/+1 counter on this creature.",
    )
    _bf(state, pridemate_card)

    eng.rules.gain_life(p2, 3)
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# "destroy/exile target artifact, enchantment[, or land]" (2+ noun compound)
# ---------------------------------------------------------------------------


def test_target_artifact_enchantment_or_land_resolves_to_permanent():
    assert resolve_target_kind("target artifact, enchantment, or land") == "permanent"


def test_target_artifact_creature_or_land_resolves_to_permanent():
    assert resolve_target_kind("target artifact, creature, or land") == "permanent"


def test_acidic_slime_full_card_is_modeled():
    card = Card(
        id="Acidic Slime", name="Acidic Slime", type_line="Creature — Ooze",
        is_creature=True, power=2, toughness=2,
        oracle_text=(
            "Deathtouch\n"
            "When this creature enters, destroy target artifact, enchantment, or land."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled


def test_destroy_artifact_enchantment_or_land_executes():
    eng = _engine()
    state = eng.state
    target_land = _bf(state, Card(id="Forest", name="Forest", type_line="Land", is_land=True))

    obj = GameObject(
        Card(id="Test Acidic", name="Test Acidic", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.STACK,
    )
    from mtg_analyzer.game.effects.core import DestroyEffect
    from mtg_analyzer.models.game.game_state import StackItem
    effect = DestroyEffect(target_kind="permanent")
    obj.spell_effects = [effect]
    item = StackItem(kind="spell", controller_id="p1", obj=obj, description="Test Acidic",
                      effects=obj.spell_effects, targets=[target_land])
    state.stack.append(item)
    eng.rules.resolve_top_of_stack()

    assert target_land not in state.battlefield


# ---------------------------------------------------------------------------
# "Commander creatures you own have \"<ability>\""
# ---------------------------------------------------------------------------


def test_commander_creatures_quoted_grant_parses():
    assert static_effect_specs(
        'commander creatures you own have "when ~ enters, draw a card."'
    ) == [
        EffectSpec(
            "grant_triggered_ability",
            {
                "trigger_event": "ENTERS_BATTLEFIELD",
                "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                "optional": False,
                "affects": "commander_creatures_you_own",
            },
        )
    ]


def test_commander_creatures_grant_with_a_group_subject_inner():
    # PAR-32: a `{"subject": "group"}` inner trigger (Agent of the Iron
    # Throne — "whenever an artifact or creature you control dies, …") now
    # re-grants with a `group_condition` param, resolved per affected
    # object by `effect_binder._build_group_ok` against the granted-to
    # permanent.
    specs = static_effect_specs(
        'commander creatures you own have '
        '"whenever an artifact or creature you control dies, each opponent loses 1 life."'
    )
    assert specs is not None and len(specs) == 1
    gc = specs[0].params["group_condition"]
    assert gc["type"] == ["artifact", "creature"] and gc["controller"] == "you"
    # An exotic group filter tied to the source's own history still fails closed.
    assert static_effect_specs(
        'commander creatures you own have '
        '"whenever a creature dealt damage by ~ this turn dies, draw a card."'
    ) in (None, [])


def test_commander_creatures_grant_with_a_compound_event_inner():
    # Regression for the `TypeError: unhashable type: 'list'` crash, and
    # PAR-32 slice 1: a compound "enters or leaves the battlefield" inner
    # trigger now re-grants as one `grant_triggered_ability` per event
    # (`_quoted_ability_grant_effects_list`), no longer fail-closed.
    specs = static_effect_specs(
        'commander creatures you own have '
        '"when ~ enters or leaves the battlefield, draw a card."'
    )
    assert specs is not None
    assert {s.params["trigger_event"] for s in specs} == {
        "ENTERS_BATTLEFIELD", "LEAVES_BATTLEFIELD"
    }


def test_commander_creatures_selector_only_picks_owned_commander_creatures():
    eng = _engine()
    state = eng.state
    my_commander = _bf(state, _creature("My Commander"), commander=True)
    my_noncommander = _bf(state, _creature("My Bear"), commander=False)
    opp_commander = _bf(state, _creature("Opp Commander"), controller="p2", commander=True)

    picked = continuous.group_selector_objects(state, "p1", "commander_creatures_you_own")
    assert picked == [my_commander]
    assert my_noncommander not in picked
    assert opp_commander not in picked


def test_clan_crafter_full_card_is_modeled():
    card = Card(
        id="Clan Crafter", name="Clan Crafter", type_line="Creature — Dwarf Artificer",
        is_creature=True, power=1, toughness=3,
        oracle_text='Commander creatures you own have "When this creature enters, draw a card."',
    )
    result = parse_oracle(card)
    assert result.modeled


# ---------------------------------------------------------------------------
# "Whenever ~ attacks, it gets +N/+N until end of turn."
# ---------------------------------------------------------------------------


def test_it_gets_pt_delta_parses_with_self_subject():
    assert match_clause("it gets +2/+0 until end of turn", self_subject=True) == [
        EffectSpec("pump", {"power": 2, "toughness": 0})
    ]


def test_it_gets_pt_delta_is_not_claimed_without_self_subject():
    # Only offered from a genuinely self-subject trigger body — a bare "it"
    # elsewhere has no bound referent.
    assert match_clause("it gets +2/+0 until end of turn") is None


def test_borderland_marauder_full_card_is_modeled():
    card = Card(
        id="Borderland Marauder", name="Borderland Marauder", type_line="Creature — Human Warrior",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever this creature attacks, it gets +2/+0 until end of turn.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.trigger == {"event": "ATTACKS", "condition": {"subject": "self"}}
    assert spec.effects[0] == EffectSpec("pump", {"power": 2, "toughness": 0})


def test_attack_pump_executes_and_boosts_power():
    eng = _engine()
    state = eng.state
    marauder_card = Card(
        id="Test Marauder", name="Test Marauder", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever this creature attacks, it gets +2/+0 until end of turn.",
    )
    marauder = _bf(state, marauder_card)
    continuous.recompute(state)
    assert marauder.power == 2

    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=marauder.name, player_id="p1",
            instance_id=marauder.instance_id, object_types=sorted(marauder.type_words),
        )
    )
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()
    continuous.recompute(state)

    assert marauder.power == 4  # 2 base + 2 from the pump


# ---------------------------------------------------------------------------
# "Prevent the next N damage that would be dealt to any target this turn."
# ---------------------------------------------------------------------------


def test_prevent_damage_single_target_parses():
    assert match_clause("prevent the next 1 damage that would be dealt to any target this turn") == [
        EffectSpec("prevent_damage_shield", {"amount": 1, "target_kind": "any"})
    ]


def test_alabaster_wall_full_card_is_modeled():
    card = Card(
        id="Alabaster Wall", name="Alabaster Wall", type_line="Creature — Wall",
        is_creature=True, power=0, toughness=3, keywords=["Defender"],
        oracle_text=(
            "Defender\n"
            "{T}: Prevent the next 1 damage that would be dealt to any target this turn."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled


def test_prevent_damage_shield_executes_and_prevents_combat_damage():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    attacker = _bf(state, _creature("Attacker"), controller="p2")

    from mtg_analyzer.game.effects.core import PreventDamageEffect
    from mtg_analyzer.models.game.game_state import StackItem
    obj = GameObject(
        Card(id="Test Shield", name="Test Shield", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.STACK,
    )
    effect = PreventDamageEffect(amount=1, target_kind="any")
    obj.spell_effects = [effect]
    item = StackItem(kind="spell", controller_id="p1", obj=obj, description="Test Shield",
                      effects=obj.spell_effects, targets=[p2])
    state.stack.append(item)
    eng.rules.resolve_top_of_stack()

    life_before = p2.life
    eng.rules.deal_damage(p2, 1, source=attacker)
    assert p2.life == life_before  # prevented
