"""PAR-79 — "<Name>/target creature can't be blocked this turn" broad
recognition.

`UnblockableEffect`/the `"unblockable"` effect key already existed end to
end (ENG-32, built for Rogue's Passage/Giant Koi) — this batch is purely
parser recognition of three shapes `handlers.py` didn't cover yet, all
routing through the pre-existing primitive:

- a keyword grant plus unblockable in one sentence ("~ gains lifelink until
  end of turn and can't be blocked this turn") — `_PUMP_KEYWORD_UNBLOCKABLE_RE`
  / `_pump_keyword_unblockable`, the keyword-grant sibling of the already-
  shipped `_PUMP_UNBLOCKABLE_RE` (P/T delta plus unblockable).
- "another target attacking creature can't be blocked this turn" —
  `_CANT_BE_BLOCKED_TURN_OTHER_ATTACKER_RE`, the unblockable sibling of
  `_PUMP_OTHER_ATTACKING_CREATURE_RE` (the shared `TARGET` macro has no
  "another ... attacking creature" phrasing).
- an optional "with power N or less/greater" target-power qualifier, added
  to *both* the new keyword-grant handler and the pre-existing bare
  `_CANT_BE_BLOCKED_TURN_RE` — the same suffix `_GAIN_CONTROL_EOT_RE`
  already uses, not a new filter shape (`creature_filter`'s `min_power`/
  `max_power` keys).

Reference: parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import match_clause, parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, tl, txt, **kw):
    if "Creature" not in tl:
        kw.pop("power", None)
        kw.pop("toughness", None)
    return Card(id=name[:6], name=name, type_line=tl, oracle_text=txt,
                is_creature="Creature" in tl, is_instant="Instant" in tl,
                is_sorcery="Sorcery" in tl, **kw)


def _engine():
    libs = [("p1", "A", []), ("p2", "B", [])]
    return GameEngine.new_game(libs, starting_life=20, starting_hand=0)


# --- parse -------------------------------------------------------------


def test_keyword_grant_plus_unblockable_parses():
    specs = match_clause("~ gains lifelink until end of turn and can't be blocked this turn")
    assert specs == [EffectSpec("pump", {"unblockable": True, "keywords": ["lifelink"]})]


def test_keyword_grant_plus_unblockable_with_power_filter_parses():
    specs = match_clause(
        "target creature you control with power 2 or less gains lifelink until end "
        "of turn and can't be blocked this turn"
    )
    assert specs == [EffectSpec("pump", {
        "unblockable": True, "keywords": ["lifelink"],
        "target_kind": "creature_you_control",
        "creature_filter": {"max_power": 2},
    })]


def test_bare_unblockable_with_power_filter_parses():
    specs = match_clause("target creature with power 2 or less can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"max_power": 2},
    })]


def test_another_target_attacking_creature_unblockable_parses():
    specs = match_clause("another target attacking creature can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"attacking": True},
    })]


def test_does_not_overmatch_unrelated_trailing_effect():
    # "and draws a card" is a genuinely separate second effect, not an
    # unblockable/keyword grant — must split into two specs, not one.
    specs = match_clause("~ gains lifelink until end of turn and draws a card")
    assert specs is None  # match_clause is single-clause only; the split happens one level up
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    body_specs = parse_effect_body("~ gains lifelink until end of turn and draws a card.")
    assert body_specs == [
        EffectSpec("pump", {"keywords": ["lifelink"]}),
        EffectSpec("draw", {"count": 1}),
    ]


def test_plain_keyword_grant_still_works():
    # adversarial: the widened `pump_keyword_unblockable` regex must not
    # steal the plain (no unblockable tail) keyword-grant clause.
    specs = match_clause("~ gains lifelink until end of turn")
    assert specs == [EffectSpec("pump", {"keywords": ["lifelink"]})]


def test_bare_self_unblockable_rejects_power_filter():
    # "with power N or less" needs a real RULE 115 target, not the bare
    # self-referential ("~ can't be blocked this turn") form — fail closed.
    from mtg_analyzer.parser.oracle.catalogue.handlers import _cant_be_blocked_turn, _CANT_BE_BLOCKED_TURN_RE
    m = _CANT_BE_BLOCKED_TURN_RE.fullmatch("~ can't be blocked this turn")
    assert m is not None and m.groupdict().get("selfref")
    assert _cant_be_blocked_turn(m) == [EffectSpec("unblockable", {"target_kind": None})]


def test_real_cards_now_modeled():
    for name, tl, txt in [
        ("Apocalypse Runner", "Artifact — Vehicle",
         "{T}: Target creature you control with power 2 or less gains lifelink "
         "until end of turn and can't be blocked this turn."),
        ("Break Through the Line", "Instant",
         "{R}: Target creature with power 2 or less gains haste until end of "
         "turn and can't be blocked this turn."),
        ("Cephalid Inkshrouder", "Creature — Cephalid",
         "Discard a card: This creature gains shroud until end of turn and "
         "can't be blocked this turn."),
        ("Clammy Prowler", "Creature — Horror",
         "Whenever this creature attacks, another target attacking creature "
         "can't be blocked this turn."),
        ("Crafty Pathmage", "Creature — Human Wizard",
         "{T}: Target creature with power 2 or less can't be blocked this turn."),
    ]:
        c = _card(name, tl, txt, power=2, toughness=2, mana_cost_string="{1}{U}")
        r = parse_oracle(c)
        assert r.modeled, (name, r.unclaimed)


# --- execute -------------------------------------------------------------


def test_pump_keyword_unblockable_executes():
    eng = _engine()
    target = GameObject(_card("Bear", "Creature — Bear", "", power=2, toughness=2),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    target.controller_id = "p1"
    eng.state.add_to_battlefield(target)
    build_effects(
        [EffectSpec("pump", {"unblockable": True, "keywords": ["lifelink"], "target_kind": "creature"})],
        target,
    )[0].apply(eng.rules.context, [target])
    eng.recompute_continuous_effects()
    assert target.temp_unblockable is True
    assert "lifelink" in target.granted_keywords


def test_other_attacking_creature_unblockable_executes():
    eng = _engine()
    other = GameObject(_card("Bear", "Creature — Bear", "", power=2, toughness=2),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    eng.state.add_to_battlefield(other)
    build_effects(
        [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"attacking": True}})],
        other,
    )[0].apply(eng.rules.context, [other])
    assert other.temp_unblockable is True


# ---------------------------------------------------------------------------
# Second increment: "another target legendary creature"/bare-subtype-noun
# targets (Bessie, the Doctor's Roadster; Aquatic Incursion/Daughter of the
# Deep/Corsairs of Umbar). See `Done_Backend.md`'s PAR-79 entry — these two
# shapes are what the second increment actually closed; the ~77-card
# residue (Alora cycle, activation-cost riders, qualified "except by..."
# forms) is unaffected and stays open.
# ---------------------------------------------------------------------------


def test_another_target_legendary_creature_unblockable_parses():
    specs = match_clause("another target legendary creature can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"legendary": True},
    })]


def test_bare_subtype_unblockable_parses():
    specs = match_clause("target merfolk can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"subtype": "Merfolk"},
    })]


def test_bare_subtype_or_list_unblockable_parses():
    # The Oxford-comma "A, B, or C" shape (Corsairs of Umbar) — the
    # regression this increment's own split-regex bug fix targets: a naive
    # `,\s*|\s+or\s+` split leaves "or pirate" as one unmatched word.
    specs = match_clause("target goblin, orc, or pirate can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature",
        "creature_filter": {"subtype_any": ["Goblin", "Orc", "Pirate"]},
    })]


def test_bare_subtype_unblockable_rejects_unknown_words():
    # An unrecognized word must fail closed rather than guessing a subtype
    # filter for what's really a qualifier — e.g. "attacking creature" is
    # already claimed by `cant_be_blocked_this_turn` before this handler is
    # even tried, so this proves the *fallback* also stays closed.
    assert match_clause("target sliver overlord can't be blocked this turn") is None


def test_subtype_word_rejects_a_power_toughness_pattern():
    # Regression: `object_filter`'s own singular-"creature" widening
    # (third increment) made `_scope` reach real "a 1/1 creature" text for
    # the first time (Lovestruck Beast's "unless you control a 1/1
    # creature") — "1/1" must never be guessed as a subtype *named*
    # "1/1" (a `combat.matches_object_filter` substring check on that
    # would just never match any real card, silently making the
    # restriction impossible to satisfy rather than failing closed).
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import object_filter

    assert object_filter("1/1 creature") is None
    assert object_filter("merfolk creature") == {"subtype": "Merfolk"}


def test_bare_subtype_unblockable_executes():
    eng = _engine()
    merfolk = GameObject(
        _card("Silvergill Adept", "Creature — Merfolk Wizard", "", power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    merfolk.controller_id = "p2"
    eng.state.add_to_battlefield(merfolk)
    build_effects(
        [EffectSpec("unblockable", {
            "target_kind": "creature", "creature_filter": {"subtype": "Merfolk"},
        })],
        merfolk,
    )[0].apply(eng.rules.context, [merfolk])
    assert merfolk.temp_unblockable is True


def test_real_cards_now_modeled_second_increment():
    for name, tl, txt in [
        ("Bessie, the Doctor's Roadster", "Legendary Creature — Car",
         "Whenever ~ attacks, another target legendary creature can't be "
         "blocked this turn."),
        ("Aquatic Incursion", "Instant",
         "{3}{U}: Target merfolk can't be blocked this turn."),
        ("Corsairs of Umbar", "Creature — Human Pirate",
         "{2}{U}: Target goblin, orc, or pirate can't be blocked this turn."),
    ]:
        c = _card(name, tl, txt, power=2, toughness=2, mana_cost_string="{1}{U}")
        r = parse_oracle(c)
        assert r.modeled, (name, r.unclaimed)


# ---------------------------------------------------------------------------
# Third increment (2026-09-15 return pass): "except by <filter>", the
# untargeted mass form, the multi-target form, "target <subtype>[ creature]"
# widenings, and a bare-target-kind widening on the P/T-delta row. See
# Done_Backend.md's PAR-79 entry for the full closed/residue breakdown.
# ---------------------------------------------------------------------------


def test_except_by_filter_parses():
    assert parse_effect_body(
        "~ can't be blocked this turn except by creatures with haste."
    ) == [EffectSpec("combat_restriction_this_turn", {
        "restriction": {"kind": "only_blocked_by", "filter": {"keyword": "haste"}},
    })]


def test_except_by_filter_on_a_real_target_parses():
    assert parse_effect_body(
        "another target creature you control can't be blocked this turn "
        "except by spirits."
    ) == [EffectSpec("combat_restriction_this_turn", {
        "restriction": {"kind": "only_blocked_by", "filter": {"subtype": "Spirit"}},
        "target_kind": "other_creature_you_control",
    })]


def test_pt_delta_unblockable_now_accepts_controller_scoped_targets():
    # Teleportal-shaped — this row's own allowed set had fallen behind its
    # keyword-grant sibling.
    assert parse_effect_body(
        "target creature you control gets +1/+0 until end of turn and "
        "can't be blocked this turn."
    ) == [EffectSpec("pump", {
        "power": 1, "toughness": 0, "unblockable": True, "target_kind": "creature_you_control",
    })]


def test_mass_form_parses():
    assert parse_effect_body("creatures can't be blocked this turn.") == [
        EffectSpec("unblockable", {"selector": "all_creatures"}),
    ]
    assert parse_effect_body("creatures you control can't be blocked this turn.") == [
        EffectSpec("unblockable", {"selector": "creatures_you_control"}),
    ]


def test_multi_target_parses():
    assert parse_effect_body("up to 2 target creatures can't be blocked this turn.") == [
        EffectSpec("unblockable", {"target_kind": "creature", "count": 2, "optional": True}),
    ]


def test_legendary_target_without_another_parses():
    assert parse_effect_body("target legendary creature can't be blocked this turn.") == [
        EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"legendary": True}}),
    ]


def test_subtype_creature_parses():
    assert parse_effect_body("target merfolk creature can't be blocked this turn.") == [
        EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"subtype": "Merfolk"}}),
    ]


def test_real_cards_now_modeled_third_increment():
    for name, tl, txt in [
        ("Gingerbrute", "Artifact Creature — Gremlin",
         "{1}: ~ can't be blocked this turn except by creatures with haste."),
        ("Jace, Arcane Strategist", "Legendary Planeswalker — Jace",
         "−7: Creatures you control can't be blocked this turn."),
        ("Ghostform", "Instant", "Up to 2 target creatures can't be blocked this turn."),
        ("K-9, Mark I", "Legendary Artifact Creature — Dog",
         "{1}{U}, {T}: Target legendary creature can't be blocked this turn."),
        ("Merfolk Sovereign", "Creature — Merfolk",
         "{T}: Target Merfolk creature can't be blocked this turn."),
        ("Teleportal", "Instant",
         "Target creature you control gets +1/+0 until end of turn and "
         "can't be blocked this turn."),
    ]:
        c = _card(name, tl, txt, power=2, toughness=2, mana_cost_string="{1}{U}")
        r = parse_oracle(c)
        assert r.modeled, (name, r.unclaimed)


def test_except_by_filter_executes():
    eng = _engine()
    attacker = GameObject(_card("Attacker", "Creature — Bear", "", power=2, toughness=2),
                           owner_id="p1", zone=Zone.BATTLEFIELD)
    attacker.controller_id = "p1"
    eng.state.add_to_battlefield(attacker)
    fast_blocker = GameObject(_card("Fast", "Creature — Bear", "", power=1, toughness=1),
                               owner_id="p2", zone=Zone.BATTLEFIELD)
    fast_blocker.controller_id = "p2"
    slow_blocker = GameObject(_card("Slow", "Creature — Bear", "", power=1, toughness=1),
                               owner_id="p2", zone=Zone.BATTLEFIELD)
    slow_blocker.controller_id = "p2"
    eng.state.add_to_battlefield(fast_blocker)
    eng.state.add_to_battlefield(slow_blocker)
    build_effects(
        [EffectSpec("combat_restriction_this_turn", {
            "restriction": {"kind": "only_blocked_by", "filter": {"keyword": "haste"}},
        })],
        attacker,
    )[0].apply(eng.rules.context, [attacker])

    from mtg_analyzer.game import combat

    assert combat.blocker_allowed(attacker, slow_blocker) is False
    fast_blocker.temp_keywords.add("haste")
    eng.recompute_continuous_effects()
    assert combat.blocker_allowed(attacker, fast_blocker) is True


def test_mass_form_executes():
    eng = _engine()
    p1 = eng.state.players[0]
    a = GameObject(_card("A", "Creature — Bear", "", power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    a.controller_id = "p1"
    b = GameObject(_card("B", "Creature — Bear", "", power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    b.controller_id = "p2"
    eng.state.add_to_battlefield(a)
    eng.state.add_to_battlefield(b)
    source = GameObject(_card("Source", "Enchantment", ""), owner_id="p1", zone=Zone.BATTLEFIELD)
    build_effects(
        [EffectSpec("unblockable", {"selector": "creatures_you_control"})],
        source,
    )[0].apply(eng.rules.context, [])
    assert a.temp_unblockable is True
    assert b.temp_unblockable is False
