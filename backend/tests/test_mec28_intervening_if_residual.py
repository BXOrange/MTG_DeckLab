"""MEC-28: the intervening-if family's own residual, closed.

`test_group_subject_retarget.py`/`test_intervening_if_first_combat_phase.py`
already cover the two engine primitives an earlier pass built (`TapEffect`'s
``"trigger_subject"`` retarget mode and its ``"attacking_creatures"``
selector) and note that Karlach, Fury of Avernus/Finest Hour were left open —
each blocked on its own separate gap those primitives didn't touch. This file
covers what closes them:

- `handlers.EffectHandler.group_subject_only` / `segmenter.parse_effect_body`'s
  new ``group_subject`` parameter — "untap **that creature**" (Finest Hour),
  the ``"that creature"`` pronoun sibling of the already-modeled bare "it".
- `handlers.EffectHandler.previous_selector_only` / `effects.GameContext.
  previous_selector` — "**They** gain first strike until end of turn."
  (Karlach), the mass-selector sibling of `previous_subject`'s RULE 115
  target tracking (a selector clause is untargeted, so it never populates
  `previous_targets`).
- RULE 506.4's bare "whenever you attack" trigger condition (`PLAYER_
  ATTACKED`, already fired by the engine for a different, hand-authored
  consumer — only the oracle-text recognizer and `effect_binder._GROUP_
  CONTROLLER_EVENT_KEYS`'s ``attacking_player_id`` mapping were missing).
- `_EXTRA_COMBAT_PHASE_RE` widened to the subject-first word order ("there is
  an additional combat phase after this phase.") real cache cards also print.
- The "For Mirrodin!" ability word (`gate._expand_ability_word_reminders`) —
  its real rules text lives in reminder text, which `normalize` would
  otherwise discard before the segmenter ever sees it.
- Raiyuu, Storm's Edge's own stale hand-authored catalogue entry (predating
  the extra-combat-phase primitive, deliberately simplified to "untap it"
  only) deleted now that the oracle-text parser fully covers it, same as its
  Alchemy sibling A-Raiyuu — one shared implementation instead of two
  drifting ones.
- Raph & Leo, Sibling Rivals hand-authored with `TapEffect`'s new
  ``creature_filter`` param — at the time, further simplified to a single
  mandatory target since RULE 601.2c's "one or two target X" had no
  `TargetSpec` range field yet. ENG-30 (2026-08-12) built that range
  (`TargetSpec.count_max`) and this entry now uses it for real — see
  `test_raph_and_leo_untaps_up_to_two_chosen_attackers_and_grants_extra_
  combat` below, updated from the single-target version this docstring
  used to describe.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def bear_card(name="Bear", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness,
    )


def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"


# -- Finest Hour: the group_subject_only "that creature" pronoun -------------


FINEST_HOUR_TEXT = (
    "Exalted (Whenever a creature you control attacks alone, that creature "
    "gets +1/+1 until end of turn.)\nWhenever a creature you control attacks "
    "alone, if it's the first combat phase of the turn, untap that creature. "
    "After this phase, there is an additional combat phase."
)


def finest_hour_card():
    return Card(id="Finest Hour", name="Finest Hour", type_line="Enchantment", oracle_text=FINEST_HOUR_TEXT)


def test_finest_hour_is_modeled():
    result = parse_oracle(finest_hour_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_that_creature_pronoun_needs_group_subject_flag():
    # Fail-closed without the flag — "that creature" is genuinely ambiguous
    # (it also means an *earlier clause's own target* elsewhere) and must
    # not be guessed absent the caller confirming a real group-subject
    # trigger.
    assert parse_effect_body("untap that creature") is None
    assert parse_effect_body("untap that creature", group_subject=True) is not None


def test_finest_hour_untaps_the_attacking_alone_creature():
    eng = make_engine("p1", "p2")
    put(eng.state, finest_hour_card())
    bear = put(eng.state, bear_card())
    _to_declare_attackers(eng)

    eng.declare_attackers(eng.state.active_player, [bear])
    eng._fire_attacks_alone_event()
    eng.resolve_until_stable()

    assert bear.tapped is False  # untapped by the trigger
    assert len(eng.state.pending_extra_combats) == 1


# -- Karlach: the previous_selector_only "they" mass-selector tail -----------


KARLACH_TEXT = (
    "Whenever you attack, if it's the first combat phase of the turn, untap "
    "all attacking creatures. They gain first strike until end of turn. "
    "After this phase, there is an additional combat phase."
)


def karlach_card():
    return Card(id="Karlach, Fury of Avernus", name="Karlach, Fury of Avernus",
                type_line="Legendary Creature — Human", is_creature=True, power=4, toughness=4,
                oracle_text=KARLACH_TEXT)


def test_karlach_is_modeled():
    result = parse_oracle(karlach_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_they_gain_keyword_needs_previous_selector():
    # Standing alone it's unclaimed (no preceding mass-selector clause to
    # bind "they" to); after "untap all attacking creatures." in the same
    # body, the connector-split loop tracks the referent automatically.
    assert parse_effect_body("they gain first strike until end of turn") is None
    combined = parse_effect_body(
        "untap all attacking creatures. they gain first strike until end of turn"
    )
    assert combined is not None
    assert combined[-1].type == "pump"
    assert combined[-1].params.get("selector") == "previous_selector"


def test_karlach_untaps_and_buffs_every_attacker():
    eng = make_engine("p1", "p2")
    karlach = put(eng.state, karlach_card())
    ally = put(eng.state, bear_card("Ally"))
    _to_declare_attackers(eng)

    eng.declare_attackers(eng.state.active_player, [karlach, ally])
    eng._fire_player_attacked_events()
    eng.resolve_until_stable()

    assert karlach.tapped is False
    assert ally.tapped is False
    assert "first_strike" in karlach.temp_keywords
    assert "first_strike" in ally.temp_keywords
    assert len(eng.state.pending_extra_combats) == 1


def test_bare_whenever_you_attack_is_recognized():
    # RULE 506.4 — deliberately just the bare form; "with N creatures"/
    # "with `<qualifier>` creatures" is a much bigger, separate family.
    card = Card(
        id="Bard, Heir of Girion", name="Bard, Heir of Girion",
        type_line="Legendary Creature — Human Archer", is_creature=True, power=2, toughness=2,
        oracle_text="Whenever you attack, draw a card.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


# -- A-Raiyuu / Raiyuu: the compound type-or-type group filter already ------
# worked; the remaining blocker was the reversed extra-combat-phase word
# order, and the stale hand-authored Raiyuu entry shadowing the parser.


RAIYUU_TEXT = (
    "First strike\nWhenever a Samurai or Warrior you control attacks alone, "
    "untap it. If it's the first combat phase of the turn, there is an "
    "additional combat phase after this phase."
)


def raiyuu_card(name="Raiyuu, Storm's Edge"):
    return Card(id=name, name=name, type_line="Legendary Creature — Human Samurai",
                is_creature=True, power=2, toughness=2, keywords=["First strike"],
                oracle_text=RAIYUU_TEXT)


def test_raiyuu_is_modeled_by_the_parser():
    result = parse_oracle(raiyuu_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_raiyuu_no_longer_has_a_stale_hand_authored_entry():
    # The old catalogue entry predated the extra-combat-phase primitive and
    # was deliberately narrowed to "untap it" only — now that the parser
    # covers the card fully and correctly, the stale entry was deleted
    # rather than left to silently shadow the better behavior.
    assert is_registered("Raiyuu, Storm's Edge") is False


def test_subject_first_extra_combat_phase_word_order_parses():
    assert parse_effect_body("there is an additional combat phase after this phase") == parse_effect_body(
        "after this phase, there is an additional combat phase"
    )


def test_raiyuu_grants_extra_combat_via_the_parser():
    # Raiyuu's own trigger condition is scoped to "a Samurai or Warrior you
    # control" — Raiyuu itself qualifies (its own type line), so it attacks
    # alone rather than needing a second Samurai/Warrior creature.
    eng = make_engine("p1", "p2")
    raiyuu = put(eng.state, raiyuu_card())
    _to_declare_attackers(eng)

    eng.declare_attackers(eng.state.active_player, [raiyuu])
    eng._fire_attacks_alone_event()
    eng.resolve_until_stable()

    assert raiyuu.tapped is False
    assert len(eng.state.pending_extra_combats) == 1


# -- Hexplate Wallbreaker: "For Mirrodin!"'s reminder-text-only rules text --


FOR_MIRRODIN_TEXT = (
    "For Mirrodin! (When this Equipment enters, create a 2/2 red Rebel "
    "creature token, then attach this to it.)\nEquipped creature gets +2/+2.\n"
    "Equip {3}{R}"
)


def for_mirrodin_card(name="Hexplate Wallbreaker"):
    return Card(id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
                oracle_text=FOR_MIRRODIN_TEXT)


def test_for_mirrodin_is_modeled():
    result = parse_oracle(for_mirrodin_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_for_mirrodin_creates_and_attaches_a_boosted_rebel():
    eng = make_engine("p1", "p2")
    equipment = put(eng.state, for_mirrodin_card())

    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=equipment.instance_id,
        object=equipment.name, object_types=sorted(equipment.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    rebels = [o for o in eng.state.battlefield if o.name == "Rebel"]
    assert len(rebels) == 1
    assert equipment.attached_to == rebels[0].instance_id
    eng.recompute_continuous_effects()
    assert (rebels[0].power, rebels[0].toughness) == (4, 4)  # 2/2 base + the Equipment's own anthem


def test_for_mirrodin_reminder_survives_normalize():
    # Without `_expand_ability_word_reminders`, `normalize` would strip the
    # whole parenthetical before the segmenter ever saw the real rules text.
    from mtg_analyzer.parser.oracle.gate import _expand_ability_word_reminders

    expanded = _expand_ability_word_reminders(
        "For Mirrodin! (When this Equipment enters, create a 2/2 red Rebel "
        "creature token, then attach this to it.)"
    )
    assert expanded == "When this Equipment enters, create a 2/2 red Rebel creature token, then attach this to it."


# -- Raph & Leo, Sibling Rivals: hand-authored, documented simplification ---


def test_raph_and_leo_is_registered():
    assert is_registered("Raph & Leo, Sibling Rivals") is True


def test_raph_and_leo_untaps_up_to_two_chosen_attackers_and_grants_extra_combat():
    # ENG-30 (2026-08-12): "untap one or two target attacking creatures" is
    # now the real RULE 601.2c range (`TargetSpec.count_max=2`), gathered as
    # two rounds by `RulesEngine._continue_trigger_multi_target` — the first
    # mandatory, the second declinable. Two attacking allies here so both
    # halves of "one **or two**" are actually exercised, not just the
    # mandatory floor the old single-target simplification always tested.
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card("Raph & Leo, Sibling Rivals")
    assert card is not None

    eng = make_engine("p1", "p2")
    raph = put(eng.state, card)
    ally1 = put(eng.state, bear_card("Ally 1"))
    ally2 = put(eng.state, bear_card("Ally 2"))
    _to_declare_attackers(eng)
    eng.state.combats_this_turn = 1

    eng.declare_attackers(eng.state.active_player, [raph, ally1, ally2])
    eng.resolve_until_stable()

    pc = eng.state.pending_choice
    assert pc is not None and pc["kind"] == "trigger_target_multi"
    # Both attacking allies are offered — the creature_filter scopes the
    # target to attackers — and this first round is mandatory: no "Keine
    # weiteren"/decline option yet (RULE 601.2c's "at least one").
    option_ids = {opt["instance_id"] for opt in pc["options"] if "instance_id" in opt}
    assert option_ids == {ally1.instance_id, ally2.instance_id}
    assert not any(opt["id"] in ("stop", "decline") for opt in pc["options"])

    eng.resolve_pending_choice(str(ally1.instance_id))
    eng.resolve_until_stable()

    # Second round: only the not-yet-picked ally remains, alongside the
    # "stop early" option (declinable — the printed maximum is two).
    pc = eng.state.pending_choice
    assert pc is not None and pc["kind"] == "trigger_target_multi"
    option_ids = {opt["instance_id"] for opt in pc["options"] if "instance_id" in opt}
    assert option_ids == {ally2.instance_id}
    assert any(opt["id"] == "stop" for opt in pc["options"])

    eng.resolve_pending_choice(str(ally2.instance_id))
    eng.resolve_until_stable()

    assert ally1.tapped is False
    assert ally2.tapped is False
    assert len(eng.state.pending_extra_combats) == 1


def test_raph_and_leo_stopping_at_one_still_grants_extra_combat():
    # The declinable second round lets the caster stop after just one — RULE
    # 601.2c's minimum, not the maximum — without abandoning the ability.
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card("Raph & Leo, Sibling Rivals")
    assert card is not None

    eng = make_engine("p1", "p2")
    raph = put(eng.state, card)
    ally1 = put(eng.state, bear_card("Ally 1"))
    ally2 = put(eng.state, bear_card("Ally 2"))
    _to_declare_attackers(eng)
    eng.state.combats_this_turn = 1

    eng.declare_attackers(eng.state.active_player, [raph, ally1, ally2])
    eng.resolve_until_stable()

    pc = eng.state.pending_choice
    eng.resolve_pending_choice(str(ally1.instance_id))
    eng.resolve_until_stable()

    pc = eng.state.pending_choice
    assert pc is not None and pc["kind"] == "trigger_target_multi"
    eng.resolve_pending_choice("stop")
    eng.resolve_until_stable()

    assert ally1.tapped is False
    assert ally2.tapped is True  # never chosen — stays as declared
    assert len(eng.state.pending_extra_combats) == 1
