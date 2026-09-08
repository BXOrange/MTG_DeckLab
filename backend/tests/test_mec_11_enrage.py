"""Tests for BACKLOG MEC-11 — "whenever ~ is dealt damage" (Enrage), and the
eleven real Enrage cards hand-authored to close out the ticket ("do not
defer, author all missing cards that use enrage").

RULE 603.1's *recipient* side of a damage trigger was entirely unrecognized
before this batch — `segmenter._DAMAGE_TRIGGER_RE` only ever matched a
permanent **dealing** damage. Three small, general changes closed it:

1. `normalize._ABILITY_WORD_RE` strips the "Enrage — " label (RULE 207.2c —
   no rules meaning of its own).
2. `segmenter._DAMAGE_RECIPIENT_TRIGGER_RE` recognizes "whenever ~/a
   `<type>` [you control]/enchanted-or-equipped `<type>` is dealt [combat]
   damage, …", marking its condition ``{"recipient": True}``.
3. `effect_binder._subject_event_key`/`_build_group_ok` read that marker to
   switch from the `DAMAGE` event's `source_id`/`source_controller_id`
   (who dealt it) to `target_id`/`target_controller_id` (who took it) —
   the latter a new field `RulesEngine.deal_damage` now stamps.

This is *not* Enrage-specific — far more cards use the recipient shape than
print the ability word (Boros Reckoner/Fungusaur/Rite of Passage-shaped),
which is why the fix lives in the general trigger grammar, not gated on the
label.

Eleven real Enrage cards remained UNMODELED after that (each blocked on its
own *effect body*, not the trigger) and are hand-authored in
`game/ability_catalogue.py`, closing the whole ~25-card Enrage population
(one further "Enrage" hit, Borborygmos Enraged, doesn't actually have the
ability — a name-only false positive, correctly left alone). Several needed
a small, reusable new primitive rather than being purely bespoke — each
documented at its own definition:

- `AddCountersEffect`/`DealDamageEffect` widened selector vocabulary
  (`each_other_creature_you_control`, `each_creature_and_planeswalker`).
- `targeting.py`'s new `opponent`/`opponent_or_planeswalker` target kinds.
- `DamageEqualToCountersEffect` (Red Hulk) — `damage_equal_to_power`'s
  counter-count sibling.
- `AddManaEffect.amount_from_trigger_event` (Raphael, Ninja Destroyer) —
  reads "that much" off the firing `DAMAGE` event via `GameContext.
  trigger_event`.
"""

from __future__ import annotations

from mtg_analyzer.game import ability_catalogue, combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.events import GameEvent
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import _DAMAGE_RECIPIENT_TRIGGER_RE, segment_line, ParserProvenance


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(name, power, toughness, **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=kw.pop("mana_cost_string", "{1}{G}"),
        converted_mana_cost=kw.pop("converted_mana_cost", 2),
        is_creature=True, power=power, toughness=toughness, **kw,
    )


def _segment(raw):
    return segment_line(
        raw, allow_spell_effect=True,
        provenance=ParserProvenance(version="test", source="rule:oracle"),
    )


def _answer_trigger_target(engine, state, label):
    """Pick the pending trigger-target choice's option matching ``label``
    (a permanent name or a player id) and resolve it."""
    pc = state.pending_choice
    option = next(o for o in pc["options"] if o.get("label") == label)
    engine.rules.resolve_trigger_target_choice(option["id"])


# ---------------------------------------------------------------------------
# normalize.py: the "Enrage — " ability-word label
# ---------------------------------------------------------------------------


def test_enrage_label_is_stripped():
    text = normalize("Enrage — Whenever this creature is dealt damage, draw a card.")
    assert text == "whenever ~ is dealt damage, draw a card."
    assert "enrage" not in text


# ---------------------------------------------------------------------------
# segmenter.py: the recipient-side damage trigger, all three subject shapes
# ---------------------------------------------------------------------------


def test_recipient_trigger_regex_self():
    m = _DAMAGE_RECIPIENT_TRIGGER_RE.match("whenever ~ is dealt damage, draw a card.")
    assert m is not None
    assert m.group("self") == "~"


def test_recipient_trigger_regex_group_you_control():
    m = _DAMAGE_RECIPIENT_TRIGGER_RE.match(
        "whenever a creature you control is dealt damage, put a +1/+1 counter on it."
    )
    assert m is not None
    assert m.group("type") == "creature"
    assert m.group("yours") == " you control"


def test_recipient_trigger_regex_attached():
    m = _DAMAGE_RECIPIENT_TRIGGER_RE.match(
        "whenever enchanted creature is dealt damage, destroy it."
    )
    assert m is not None
    assert m.group("attached") == "enchanted creature"


def test_recipient_trigger_regex_combat_qualifier():
    m = _DAMAGE_RECIPIENT_TRIGGER_RE.match(
        "whenever ~ is dealt combat damage, you gain that much life."
    )
    assert m is not None
    assert m.group("combat") == "combat "


def test_segment_line_self_recipient_produces_recipient_condition():
    seg = _segment(normalize("Enrage — Whenever this creature is dealt damage, draw a card."))
    assert seg.claimed is True
    assert seg.spec is not None
    assert seg.spec.trigger["event"] == "DAMAGE"
    assert seg.spec.trigger["condition"] == {"subject": "self", "recipient": True}


# ---------------------------------------------------------------------------
# binding/core.py: target_id/target_controller_id vs source_id/
# source_controller_id
# ---------------------------------------------------------------------------


def test_self_recipient_trigger_fires_only_for_the_object_actually_hit():
    engine, state = _engine("p1")
    victim = _bf(state, _creature("Victim", 2, 4))
    bystander = _bf(state, _creature("Bystander", 2, 4))
    fired = []
    victim.triggered_abilities[:] = []  # no catalogue entry on a plain Bear
    from mtg_analyzer.game.effects.core import TriggeredAbility, GainLifeEffect
    from mtg_analyzer.game.binding.core import _subject_condition

    trigger = {"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}}
    ability = TriggeredAbility(
        trigger_event="DAMAGE",
        effects=[GainLifeEffect(amount=1)],
        condition=_subject_condition(trigger, victim),
        source=victim,
        controller_id=victim.controller_id,
    )
    victim.triggered_abilities.append(ability)

    engine.rules.deal_damage(bystander, 1, source=None)
    engine.resolve_until_stable()
    p1 = state.players[0]
    assert p1.life == 20  # the OTHER creature was hit — must not fire

    engine.rules.deal_damage(victim, 1, source=None)
    engine.resolve_until_stable()
    assert p1.life == 21


def test_source_side_damage_trigger_is_unaffected_by_the_recipient_addition():
    """Regression guard: `_subject_event_key`'s override must not leak into
    the "deals damage" (source) family it shares `_SUBJECT_EVENT_KEYS` with."""
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    dealer = _bf(state, _creature("Dealer", 2, 2))
    victim = _bf(state, _creature("Victim2", 2, 2), controller="p2")
    seg = _segment("Whenever ~ deals damage to a creature, you gain 1 life.")
    assert seg.claimed and seg.spec is not None
    from mtg_analyzer.game.binding.core import attach_to_object

    attach_to_object(dealer, [seg.spec])
    engine.rules.deal_damage(victim, 3, source=dealer)
    engine.resolve_until_stable()
    assert p1.life == 21


# ---------------------------------------------------------------------------
# End-to-end: a real cached card exercising the group ("you control")
# recipient shape — Rite of Passage.
# ---------------------------------------------------------------------------


def _rite_of_passage():
    return Card(
        id="Rite of Passage", name="Rite of Passage", type_line="Enchantment",
        mana_cost_string="{2}{G}{G}", converted_mana_cost=4,
        oracle_text="Whenever a creature you control is dealt damage, put a +1/+1 "
                    "counter on it. (It must survive the damage to get the counter.)",
    )


def test_rite_of_passage_parses_fully_modeled():
    assert parse_oracle(_rite_of_passage()).modeled is True


def test_rite_of_passage_end_to_end_group_recipient_you_control():
    engine, state = _engine("p1", "p2")
    _bf(state, _rite_of_passage())
    mine = _bf(state, _creature("Mine", 2, 4))
    theirs = _bf(state, _creature("Theirs", 2, 4), controller="p2")

    engine.rules.deal_damage(theirs, 1, source=None)
    engine.resolve_until_stable()
    assert theirs.plus_one_counters == 0  # not "you control" — must not fire

    engine.rules.deal_damage(mine, 1, source=None)
    engine.resolve_until_stable()
    assert mine.plus_one_counters == 1


# ---------------------------------------------------------------------------
# New primitives, exercised directly
# ---------------------------------------------------------------------------


def test_add_counters_each_other_creature_you_control_excludes_source():
    engine, state = _engine("p1")
    source = _bf(state, _creature("Source", 3, 3))
    other = _bf(state, _creature("Other", 2, 2))
    from mtg_analyzer.game.effects.core import AddCountersEffect, GameContext

    effect = AddCountersEffect(selector="each_other_creature_you_control", source=source)
    effect.apply(GameContext(state, engine.rules))
    assert source.plus_one_counters == 0
    assert other.plus_one_counters == 1


def test_deal_damage_each_creature_and_planeswalker_hits_both_once_each():
    engine, state = _engine("p1", "p2")
    source = _bf(state, _creature("Bolter", 1, 1))
    victim = _bf(state, _creature("Victim3", 2, 5), controller="p2")
    from mtg_analyzer.game.effects.core import DealDamageEffect, GameContext

    effect = DealDamageEffect(amount=1, selector="each_creature_and_planeswalker", source=source)
    effect.apply(GameContext(state, engine.rules))
    assert victim.damage_marked == 1


def test_damage_equal_to_counters_reads_source_plus_one_counters():
    engine, state = _engine("p1", "p2")
    source = _bf(state, _creature("Counters", 2, 6))
    source.plus_one_counters = 3
    victim = _bf(state, _creature("Victim4", 2, 8), controller="p2")
    from mtg_analyzer.game.effects.core import DamageEqualToCountersEffect, GameContext

    effect = DamageEqualToCountersEffect(target=victim, target_kind=None, source=source)
    effect.apply(GameContext(state, engine.rules))
    assert victim.damage_marked == 3


def test_add_mana_amount_from_trigger_event():
    engine, state = _engine("p1")
    source = _bf(state, _creature("Manadin", 2, 2))
    from mtg_analyzer.game.effects.core import AddManaEffect, GameContext
    from mtg_analyzer.models.game.events import GameEvent

    context = GameContext(state, engine.rules)
    context.trigger_event = GameEvent("DAMAGE", amount=4, target_id=source.instance_id)
    effect = AddManaEffect(color="R", amount_from_trigger_event="amount", source=source)
    effect.apply(context)
    assert state.players[0].mana_pool.pool["R"] == 4


def test_targeting_opponent_and_opponent_or_planeswalker_kinds():
    from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS

    assert "opponent" in ALLOWED_TARGET_KINDS
    assert "opponent_or_planeswalker" in ALLOWED_TARGET_KINDS


# ---------------------------------------------------------------------------
# The eleven hand-authored Enrage stragglers
# ---------------------------------------------------------------------------


def test_bellowing_aegisaur_mass_counters_excludes_self():
    engine, state = _engine("p1")
    aeg = _bf(state, Card(
        id="Bellowing Aegisaur", name="Bellowing Aegisaur", type_line="Creature — Dinosaur",
        mana_cost_string="{5}{W}", converted_mana_cost=6, is_creature=True, power=3, toughness=5,
    ))
    other = _bf(state, _creature("Other Bear", 2, 2))
    engine.rules.deal_damage(aeg, 1, source=None)
    engine.resolve_until_stable()
    assert aeg.plus_one_counters == 0
    assert other.plus_one_counters == 1


def test_frilled_deathspitter_damages_chosen_opponent_or_planeswalker():
    engine, state = _engine("p1", "p2")
    p2 = state.players[1]
    fd = _bf(state, Card(
        id="Frilled Deathspitter", name="Frilled Deathspitter", type_line="Creature — Dinosaur",
        mana_cost_string="{2}{R}", converted_mana_cost=3, is_creature=True, power=3, toughness=2,
    ))
    engine.rules.deal_damage(fd, 1, source=None)
    engine.resolve_until_stable()
    _answer_trigger_target(engine, state, "p2")
    engine.resolve_until_stable()
    assert p2.life == 18


def test_indoraptor_damage_equal_to_power_hits_chosen_opponent():
    engine, state = _engine("p1", "p2")
    p2 = state.players[1]
    indo = _bf(state, Card(
        id="Indoraptor, the Perfect Hybrid", name="Indoraptor, the Perfect Hybrid",
        type_line="Legendary Creature — Dinosaur Mutant", mana_cost_string="{1}{B/G}{R}",
        converted_mana_cost=3, is_creature=True, power=5, toughness=1,
    ))
    engine.rules.deal_damage(indo, 1, source=None)
    engine.resolve_until_stable()
    _answer_trigger_target(engine, state, "p2")
    engine.resolve_until_stable()
    assert p2.life == 15


def test_polyraptor_copies_itself():
    engine, state = _engine("p1")
    poly = _bf(state, Card(
        id="Polyraptor", name="Polyraptor", type_line="Creature — Dinosaur",
        mana_cost_string="{6}{G}{G}", converted_mana_cost=8, is_creature=True, power=5, toughness=5,
    ))
    before = len(state.battlefield)
    engine.rules.deal_damage(poly, 1, source=None)
    engine.resolve_until_stable()
    assert len(state.battlefield) == before + 1
    copies = [o for o in state.battlefield if o.name == "Polyraptor" and o is not poly]
    assert len(copies) == 1
    assert copies[0].is_token


def test_raphael_gains_mana_equal_to_damage_and_must_be_blocked():
    engine, state = _engine("p1")
    raph = _bf(state, Card(
        id="Raphael, Ninja Destroyer", name="Raphael, Ninja Destroyer",
        type_line="Legendary Creature — Mutant Ninja Turtle", mana_cost_string="{2}{R}{R}",
        converted_mana_cost=4, is_creature=True, power=4, toughness=4,
    ))
    continuous.recompute(state)
    assert combat.has(raph, "must_be_blocked")
    engine.rules.deal_damage(raph, 3, source=None)
    engine.resolve_until_stable()
    assert state.players[0].mana_pool.pool["R"] == 3


def test_red_hulk_counters_then_damages_chosen_target():
    engine, state = _engine("p1", "p2")
    hulk = _bf(state, Card(
        id="Red Hulk", name="Red Hulk", type_line="Legendary Creature — Gamma Berserker Villain",
        mana_cost_string="{4}{R}{R}", converted_mana_cost=6, is_creature=True, power=6, toughness=7,
    ))
    victim = _bf(state, _creature("Victim5", 2, 5), controller="p2")
    engine.rules.deal_damage(hulk, 2, source=None)
    engine.resolve_until_stable()
    _answer_trigger_target(engine, state, "Victim5")
    engine.resolve_until_stable()
    assert hulk.plus_one_counters == 1
    assert victim.damage_marked == 1


def test_silverclad_ferocidons_each_opponent_sacrifices():
    engine, state = _engine("p1", "p2", "p3")
    silverclad = _bf(state, Card(
        id="Silverclad Ferocidons", name="Silverclad Ferocidons", type_line="Creature — Dinosaur",
        mana_cost_string="{5}{R}{R}", converted_mana_cost=7, is_creature=True, power=8, toughness=5,
    ))
    only_p2 = _bf(state, _creature("Only P2 Permanent", 1, 1), controller="p2")
    only_p3 = _bf(state, _creature("Only P3 Permanent", 1, 1), controller="p3")
    engine.rules.deal_damage(silverclad, 1, source=None)
    engine.resolve_until_stable()
    assert only_p2 not in state.permanents()
    assert only_p3 not in state.permanents()
    assert silverclad in state.permanents()


def test_stalwart_speartail_attacks_damages_creatures_and_planeswalkers_once_each():
    engine, state = _engine("p1", "p2")
    speartail = _bf(state, Card(
        id="Stalwart Speartail", name="Stalwart Speartail", type_line="Creature — Dinosaur",
        mana_cost_string="{1}{R}{G}", converted_mana_cost=3, is_creature=True, power=4, toughness=4,
    ))
    victim = _bf(state, _creature("Victim6", 2, 5), controller="p2")
    walker = _bf(state, Card(
        id="Some Planeswalker", name="Some Planeswalker", type_line="Planeswalker — Test",
        mana_cost_string="{3}{U}", converted_mana_cost=4, loyalty=5,
    ), controller="p2")
    speartail.attacking = True
    state.fire_event(GameEvent(
        "ATTACKS", instance_id=speartail.instance_id, controller_id="p1", player_id="p1",
    ))
    engine.resolve_until_stable()
    assert victim.damage_marked == 1
    assert walker.loyalty == 4


def test_trapjaw_tyrant_exiles_and_returns_when_it_leaves():
    engine, state = _engine("p1", "p2")
    tyrant = _bf(state, Card(
        id="Trapjaw Tyrant", name="Trapjaw Tyrant", type_line="Creature — Dinosaur",
        mana_cost_string="{3}{W}{W}", converted_mana_cost=5, is_creature=True, power=5, toughness=5,
    ))
    foe = _bf(state, _creature("Foe", 2, 2), controller="p2")
    engine.rules.deal_damage(tyrant, 1, source=None)
    engine.resolve_until_stable()
    _answer_trigger_target(engine, state, "Foe")
    engine.resolve_until_stable()
    assert foe.zone == Zone.EXILE
    engine.rules.destroy(tyrant)
    engine.resolve_until_stable()
    assert foe.zone == Zone.BATTLEFIELD


def test_vrondiss_creates_optional_dragon_spirit_token():
    engine, state = _engine("p1")
    vrondiss = _bf(state, Card(
        id="Vrondiss, Rage of Ancients", name="Vrondiss, Rage of Ancients",
        type_line="Legendary Creature — Dragon Barbarian", mana_cost_string="{3}{R}{G}",
        converted_mana_cost=5, is_creature=True, power=5, toughness=4,
    ))
    before = len(state.battlefield)
    engine.rules.deal_damage(vrondiss, 1, source=None)
    engine.resolve_until_stable()
    # A targetless "you may" trigger (RULE 603.5) opens a do/decline choice
    # (`RulesEngine._trigger_may_choice`) rather than just happening.
    pc = state.pending_choice
    assert pc is not None and pc["kind"] == "trigger_target"
    assert {o["id"] for o in pc["options"]} == {"do", "decline"}
    engine.rules.resolve_trigger_target_choice("do")
    engine.resolve_until_stable()
    assert len(state.battlefield) == before + 1
    tokens = [o for o in state.battlefield if o.name == "Dragon Spirit"]
    assert len(tokens) == 1
    assert tokens[0].power == 5 and tokens[0].toughness == 4


# ---------------------------------------------------------------------------
# The full Enrage population is now closed (25 cards, one — Borborygmos
# Enraged — a name-only false positive with no Enrage ability at all).
# ---------------------------------------------------------------------------


def test_every_hand_authored_enrage_card_binds_without_error():
    names = [
        "Bellowing Aegisaur", "Frilled Deathspitter", "Sun-Crowned Hunters",
        "Indoraptor, the Perfect Hybrid", "Polyraptor", "Raphael, Ninja Destroyer",
        "Red Hulk", "Silverclad Ferocidons", "Stalwart Speartail", "Trapjaw Tyrant",
        "Vrondiss, Rage of Ancients",
    ]
    for name in names:
        assert ability_catalogue.is_registered(name), name
        specs_a = ability_catalogue.specs_for(Card(id=name, name=name, type_line="Creature — Test"))
        specs_b = ability_catalogue.specs_for(Card(id=name, name=name, type_line="Creature — Test"))
        assert specs_a is not specs_b
        assert specs_a[0] is not specs_b[0]
