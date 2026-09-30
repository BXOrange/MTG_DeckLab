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
    # PAR-128: "another" is the shared target grammar's slot, so the phrase
    # resolves through `resolve_target_creature_state_filter` like every
    # other "target attacking creature" (no redundant `card_type` key).
    specs = match_clause("another target attacking creature can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature",
        "creature_filter": {"attacking": True},
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
    # See `test_another_target_attacking_creature_unblockable_parses`'s own
    # comment: the redundant `card_type` key is `object_filter`'s general
    # recursion, not a regression.
    specs = match_clause("another target legendary creature can't be blocked this turn")
    # PAR-141's adjective slot reads "legendary" straight off the target phrase; the kind already is "creature".
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature",
        "creature_filter": {"legendary": True},
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
        EffectSpec("unblockable", {
            "target_kind": "creature",
            "creature_filter": {"legendary": True},
        }),
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


# ---------------------------------------------------------------------------
# Sixth increment (PAR-79) — "except by <A> and/or <B>" union filter, and
# "except by N or more creatures" as a blocker-count restriction rather than
# a characteristic filter. See BACKLOG.md/Done_Backend.md's PAR-79 entry.
# ---------------------------------------------------------------------------


def test_and_or_filter_parses_as_any_of():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import object_filter
    assert object_filter("artifact creatures and/or red creatures") == {
        "any_of": [{"card_type": "artifact"}, {"color": "R"}],
    }


def test_and_or_filter_recurses_through_every_existing_single_phrase_shape():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import object_filter
    assert object_filter("Walls and/or creatures with flying") == {
        "any_of": [{"subtype": "Wall"}, {"keyword": "flying"}],
    }


def test_and_or_filter_fails_closed_on_an_unrecognized_side():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import object_filter
    # "plunder" isn't in the closed keyword vocabulary either side reuses.
    assert object_filter("artifact creatures and/or creatures with plunder") is None


def test_except_by_union_filter_on_the_resolve_time_form_parses():
    assert parse_effect_body(
        "target creature can't be blocked this turn except by artifact "
        "creatures and/or red creatures."
    ) == [EffectSpec("combat_restriction_this_turn", {
        "restriction": {
            "kind": "only_blocked_by",
            "filter": {"any_of": [{"card_type": "artifact"}, {"color": "R"}]},
        },
        "target_kind": "creature",
    })]


def test_except_by_count_parses_as_min_blockers_not_a_filter():
    assert parse_effect_body(
        "target creature can't be blocked this turn except by 2 or more creatures."
    ) == [EffectSpec("combat_restriction_this_turn", {
        "restriction": {"kind": "min_blockers", "count": 2},
        "target_kind": "creature",
    })]


def test_real_cards_now_modeled_sixth_increment():
    for name, tl, txt in [
        ("Firefright Mage", "Creature — Human Wizard",
         "{1}{R}, {T}, Discard a card: Target creature can't be blocked "
         "this turn except by artifact creatures and/or red creatures."),
        ("Amrou Seekers", "Creature — Kithkin Soldier",
         "This creature can't be blocked except by artifact creatures "
         "and/or white creatures."),
        ("Elven Riders", "Creature — Elf",
         "This creature can't be blocked except by Walls and/or "
         "creatures with flying."),
    ]:
        c = _card(name, tl, txt, power=2, toughness=2, mana_cost_string="{1}{R}")
        r = parse_oracle(c)
        assert r.modeled, (name, r.unclaimed)


def test_any_of_filter_executes():
    from mtg_analyzer.game import combat
    artifact_blocker = GameObject(
        _card("Art", "Artifact Creature — Golem", "", power=1, toughness=1),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    red_blocker = GameObject(
        _card("Red", "Creature — Goblin", "", power=1, toughness=1, color_identity={"R"}),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    green_blocker = GameObject(
        _card("Green", "Creature — Bear", "", power=1, toughness=1, color_identity={"G"}),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    filt = {"any_of": [{"card_type": "artifact"}, {"color": "R"}]}
    assert combat.matches_object_filter(artifact_blocker, filt) is True
    assert combat.matches_object_filter(red_blocker, filt) is True
    assert combat.matches_object_filter(green_blocker, filt) is False


def test_min_blockers_restriction_executes():
    eng = _engine()
    attacker = GameObject(_card("Attacker", "Creature — Bear", "", power=2, toughness=2),
                           owner_id="p1", zone=Zone.BATTLEFIELD)
    attacker.controller_id = "p1"
    eng.state.add_to_battlefield(attacker)
    build_effects(
        [EffectSpec("combat_restriction_this_turn", {
            "restriction": {"kind": "min_blockers", "count": 2},
        })],
        attacker,
    )[0].apply(eng.rules.context, [attacker])

    from mtg_analyzer.game import combat

    assert combat.min_blockers(attacker) == 2


# ---------------------------------------------------------------------------
# animate_self/animate_target gain colour words + an unblockable tail
# (PAR-79 sixth increment). Dead-simple 7-word subtype whitelist widened to
# the shared real-creature-type vocabulary segmenter.py's cast-trigger rows
# already use — see BACKLOG.md/Done_Backend.md's PAR-79 entry.
# ---------------------------------------------------------------------------


def test_animate_self_gains_color_words():
    assert parse_effect_body(
        "~ becomes a 2/2 blue and black horror artifact creature until end of turn."
    ) == [EffectSpec("grant_until", {
        "duration": "end_of_turn", "target_kind": None,
        "static": {
            "type": "type_change",
            "params": {
                "add_types": ["creature", "artifact"], "power": 2, "toughness": 2,
                "add_subtypes": ["Horror"],
            },
        },
        "extra_statics": [{"type": "color", "params": {"colors": ["U", "B"], "set": True}}],
    })]


def test_animate_self_color_and_unblockable_tail_combine():
    assert parse_effect_body(
        "~ becomes a 2/2 blue and black horror artifact creature until end "
        "of turn and can't be blocked this turn."
    ) == [
        EffectSpec("grant_until", {
            "duration": "end_of_turn", "target_kind": None,
            "static": {
                "type": "type_change",
                "params": {
                    "add_types": ["creature", "artifact"], "power": 2, "toughness": 2,
                    "add_subtypes": ["Horror"],
                },
            },
            "extra_statics": [{"type": "color", "params": {"colors": ["U", "B"], "set": True}}],
        }),
        EffectSpec("unblockable", {"target_kind": None}),
    ]


def test_animate_self_widened_subtype_whitelist_accepts_bird():
    # The Ravnica guild Keyrune cycle alone prints ten distinct creature
    # types — the original 7-word whitelist only covered the one card it
    # was written against.
    assert parse_effect_body(
        "~ becomes a 2/2 white and blue bird artifact creature with flying "
        "until end of turn."
    ) is not None


def test_animate_self_still_fails_closed_on_an_unrecognized_word():
    assert parse_effect_body(
        "~ becomes a 2/2 purple and orange gremlin artifact creature "
        "until end of turn."
    ) is None


def test_animate_target_gains_color_words_and_snow_kind():
    specs = parse_effect_body(
        "target snow land becomes a 2/2 blue elemental creature with "
        "flying until end of turn. it's still a snow land."
    )
    assert specs is not None
    assert specs[0].type == "grant_until"
    assert specs[0].params["static"]["params"]["add_subtypes"] == ["Elemental"]
    assert specs[0].params["extra_statics"][0] == {
        "type": "color", "params": {"colors": ["U"], "set": True},
    }


def test_real_cards_now_modeled_sixth_increment_animation():
    for name, tl, txt in [
        ("Dimir Keyrune", "Artifact",
         "{T}: Add {U} or {B}.\n{U}{B}: This artifact becomes a 2/2 blue "
         "and black Horror artifact creature until end of turn and can't "
         "be blocked this turn."),
        ("Boros Keyrune", "Artifact",
         "{T}: Add {R} or {W}.\n{R}{W}: This artifact becomes a 1/1 red "
         "and white Soldier artifact creature with double strike until "
         "end of turn."),
        ("Atarka Monument", "Artifact",
         "{T}: Add {R} or {G}.\n{4}{R}{G}: This artifact becomes a 4/4 "
         "red and green Dragon artifact creature with flying until end "
         "of turn."),
    ]:
        c = _card(name, tl, txt, mana_cost_string="{2}")
        r = parse_oracle(c)
        assert r.modeled, (name, r.unclaimed)


def test_animate_self_color_static_executes():
    eng = _engine()
    source = GameObject(_card("Source", "Artifact", ""), owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    eng.state.add_to_battlefield(source)
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    build_effects(
        [EffectSpec("grant_until", {
            "duration": "end_of_turn", "target_kind": None,
            "static": {
                "type": "type_change",
                "params": {"add_types": ["creature", "artifact"], "power": 2, "toughness": 2},
            },
            "extra_statics": [{"type": "color", "params": {"colors": ["U", "B"], "set": True}}],
        })],
        source,
    )[0].apply(eng.rules.context, [])
    eng.recompute_continuous_effects()
    assert source.colors == {"U", "B"}
    assert source.power == 2 and source.toughness == 2


# ---------------------------------------------------------------------------
# UnblockableEffect.previous_subject — "that creature can't be blocked this
# turn" (Stealth Mission-shaped, PAR-79 sixth increment).
# ---------------------------------------------------------------------------


def test_previous_subject_unblockable_parses():
    assert parse_effect_body(
        "put 2 +1/+1 counters on target creature you control. that "
        "creature can't be blocked this turn."
    ) == [
        EffectSpec("add_counters", {
            "count": 2, "kind": "+1/+1", "target_kind": "creature_you_control",
        }),
        EffectSpec("unblockable", {"previous_subject": True}),
    ]


def test_real_card_stealth_mission_now_modeled():
    c = _card(
        "Stealth Mission", "Instant",
        "Put two +1/+1 counters on target creature you control. That "
        "creature can't be blocked this turn.",
        mana_cost_string="{1}{G}",
    )
    r = parse_oracle(c)
    assert r.modeled, r.unclaimed


def test_previous_subject_unblockable_executes():
    eng = _engine()
    target = GameObject(_card("Target", "Creature — Bear", "", power=2, toughness=2),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    target.controller_id = "p1"
    eng.state.add_to_battlefield(target)
    eng.rules.context.previous_targets = [target]
    build_effects(
        [EffectSpec("unblockable", {"previous_subject": True})],
        target,
    )[0].apply(eng.rules.context, [])
    assert target.temp_unblockable is True


# ---------------------------------------------------------------------------
# "You may <effect>. If you do, <effect2>." with a resolving-effect (not
# cost) antecedent — PAR-79 sixth increment. `OptionalEffect`'s own
# docstring already spelled this composition out: sequencing both effects
# inside one `optional` node, since RULE 603.5's "if you do" is automatic
# once the whole body only runs when the player accepts.
# ---------------------------------------------------------------------------


def test_may_effect_then_parses_as_optional_wrapping_a_sequence():
    assert parse_effect_body(
        "you may draw a card. if you do, discard a card."
    ) == [EffectSpec("optional", {
        "effects": [
            {"type": "draw", "params": {"count": 1}},
            {"type": "discard", "params": {"count": 1}},
        ],
    })]


def test_may_effect_then_does_not_preempt_the_cost_shaped_row():
    # "you may pay {1}." is `_MAY_COST_THEN_CLAUSE`'s job (real cost
    # affordability, PayCostThenEffect) — must not fall through to the
    # cruder untargeted-optional wrap.
    specs = parse_effect_body("you may pay {1}. if you do, draw a card.")
    assert specs == [EffectSpec("pay_cost_then", {
        "cost": "{1}", "effects": [{"type": "draw", "params": {"count": 1}}],
    })]


def test_real_card_shipwreck_looter_now_modeled():
    c = _card(
        "Shipwreck Looter", "Creature — Human Pirate",
        "Raid — When this creature enters, if you attacked this turn, "
        "you may draw a card. If you do, discard a card.",
        power=2, toughness=1, mana_cost_string="{1}{U}", keywords=["Raid"],
    )
    r = parse_oracle(c)
    assert r.modeled, r.unclaimed


def test_may_effect_then_executes():
    eng = _engine()
    p1 = eng.state.players[0]
    p1.library.append(GameObject(_card("Lib", "Creature — Bear", "", power=1, toughness=1),
                                  owner_id="p1", zone=Zone.LIBRARY))
    kept_card = GameObject(_card("Kept", "Creature — Bear", "", power=1, toughness=1),
                            owner_id="p1", zone=Zone.HAND)
    p1.hand.append(kept_card)
    source = GameObject(_card("Source", "Creature — Bear", "", power=1, toughness=1),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    eng.state.add_to_battlefield(source)
    hand_before = len(p1.hand)
    build_effects(
        [EffectSpec("optional", {
            "effects": [
                {"type": "draw", "params": {"count": 1}},
                {"type": "discard", "params": {"count": 1}},
            ],
        })],
        source,
    )[0].apply(eng.rules.context, [])
    assert eng.state.pending_choice is not None
    eng.rules.resolve_choice("yes")
    # Drew 1, then had to discard 1 (an interactive choice of which card).
    assert eng.state.pending_choice is not None
    eng.rules.resolve_choice(kept_card.instance_id)
    assert len(p1.hand) == hand_before


# ---------------------------------------------------------------------------
# "return another/<N> other <type>[s] you control to its owner's hand" /
# "tap another/<N> other untapped <type>[s] you control" — PAR-79 seventh
# increment. These are ordinary RULE 608.2c resolve-time effect bodies (no
# "target" word), reusing the pre-existing `ChooseObjectsEffect`/
# `"choose_objects"` chooser rather than a new primitive; combined with
# `_may_effect_then` (sixth increment) they close Biblioplex Kraken/
# Gravelgill Scoundrel/Tidal Terror — that handler's own three motivating
# cards, which still didn't parse even once it shipped, because
# `_peel_optional` stripped their leading "you may " (and the reflexive
# "if you do" gate along with it) before `_may_effect_then`'s own regex
# ever got a chance to match. See `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE`.
# ---------------------------------------------------------------------------


def test_return_another_you_control_parses():
    assert match_clause(
        "return another creature you control to its owner's hand"
    ) == [EffectSpec("choose_objects", {
        "action": "return_to_hand", "what": "creature", "count": 1, "exclude_self": True,
    })]


def test_tap_another_untapped_you_control_parses():
    assert match_clause(
        "tap another untapped creature you control"
    ) == [EffectSpec("choose_objects", {
        "action": "tap", "what": "creature", "count": 1,
        "exclude_self": True, "require_untapped": True,
    })]


def test_tap_n_other_untapped_you_control_parses():
    # Tidal Terror's own count-2 form.
    assert match_clause(
        "tap 2 other untapped creatures you control"
    ) == [EffectSpec("choose_objects", {
        "action": "tap", "what": "creature", "count": 2,
        "exclude_self": True, "require_untapped": True,
    })]


def test_may_effect_then_peel_guard_protects_resolving_effect_antecedent():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    # A segmenter-level test, not just `parse_effect_body` directly: this is
    # the shape that actually regressed — `_peel_optional` ran *before*
    # `parse_effect_body` ever saw the clause, stripping "you may " (and
    # marking the whole ability optional) so `_may_effect_then`'s own
    # "you may <effect>. if you do, <effect2>." regex never matched.
    seg = segment_line(
        "whenever ~ attacks, you may return another creature you control "
        "to its owner's hand. if you do, ~ can't be blocked this turn.",
        allow_spell_effect=True, provenance=ParserProvenance(),
    )
    assert seg.claimed, seg
    assert seg.spec.effects == [EffectSpec("optional", {
        "effects": [
            {"type": "choose_objects", "params": {
                "action": "return_to_hand", "what": "creature",
                "count": 1, "exclude_self": True,
            }},
            {"type": "unblockable", "params": {"target_kind": None}},
        ],
    })]


def test_may_effect_then_peel_guard_does_not_break_certain_antecedent_reduction():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    # The regression this guard must NOT reintroduce: a *certain*,
    # self-referential antecedent ("sacrifice ~") that RULE 603.3's "when
    # you do" reduces to a plain unconditional sequence
    # (`_SACRIFICE_THEN_WHEN_YOU_DO_RE`) needs `_peel_optional` to still
    # strip the leading "you may " — widening the guard to match *every*
    # "you may X. if/when you do" shape (tried and reverted while building
    # this increment) broke this family (Sunfire Torch/Throwing Knife &c.).
    seg = segment_line(
        "whenever ~ attacks, you may sacrifice ~. when you do, "
        "~ deals 2 damage to any target.",
        allow_spell_effect=True, provenance=ParserProvenance(),
    )
    assert seg.claimed, seg
    # The ability itself is still optional (RULE 601.2b — "you may
    # sacrifice"); it's the *reduction* of "when you do" to a plain
    # unconditional sequence (rather than a separate `optional`/
    # `pay_cost_then` wrapper) this test is actually guarding.
    assert seg.spec.optional is True
    assert [e.type for e in seg.spec.effects] == ["sacrifice_self", "damage"]


def test_real_cards_now_modeled_seventh_increment():
    cards = [
        _card(
            "Biblioplex Kraken", "Creature — Kraken",
            "Whenever this creature attacks, you may return another creature "
            "you control to its owner's hand. If you do, this creature can't "
            "be blocked this turn.",
            power=5, toughness=5, mana_cost_string="{5}{U}{U}",
        ),
        _card(
            "Gravelgill Scoundrel", "Creature — Merfolk Rogue",
            "Vigilance\nWhenever this creature attacks, you may tap another "
            "untapped creature you control. If you do, this creature can't "
            "be blocked this turn.",
            power=2, toughness=2, mana_cost_string="{1}{U}", keywords=["Vigilance"],
        ),
        _card(
            "Tidal Terror", "Creature — Serpent",
            "Whenever this creature attacks, you may tap two other untapped "
            "creatures you control. If you do, this creature can't be "
            "blocked this turn.",
            power=5, toughness=5, mana_cost_string="{4}{U}{U}",
        ),
    ]
    for c in cards:
        r = parse_oracle(c)
        assert r.modeled, (c.name, r.unclaimed)


def test_require_untapped_excludes_tapped_candidates():
    eng = _engine()
    source = GameObject(_card("Source", "Creature — Bear", "", power=1, toughness=1),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    eng.state.add_to_battlefield(source)
    tapped_other = GameObject(_card("TappedOther", "Creature — Bear", "", power=1, toughness=1),
                               owner_id="p1", zone=Zone.BATTLEFIELD)
    tapped_other.controller_id = "p1"
    tapped_other.tapped = True
    eng.state.add_to_battlefield(tapped_other)
    untapped_other = GameObject(_card("UntappedOther", "Creature — Bear", "", power=1, toughness=1),
                                 owner_id="p1", zone=Zone.BATTLEFIELD)
    untapped_other.controller_id = "p1"
    eng.state.add_to_battlefield(untapped_other)
    build_effects(
        [EffectSpec("choose_objects", {
            "action": "tap", "what": "creature", "count": 1,
            "exclude_self": True, "require_untapped": True,
        })],
        source,
    )[0].apply(eng.rules.context, [])
    # Only the untapped candidate was eligible, so with exactly one legal
    # pick this resolves without a prompt (the pre-existing "asking would be
    # theatre" forced-pick idiom `_request_choose_objects` already applies).
    assert untapped_other.tapped is True
    assert tapped_other.tapped is True  # was already tapped, untouched
    assert source.tapped is False  # excluded by `exclude_self`


def test_return_to_hand_excludes_self():
    eng = _engine()
    p1 = eng.state.players[0]
    source = GameObject(_card("Source", "Creature — Bear", "", power=1, toughness=1),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    source.controller_id = "p1"
    eng.state.add_to_battlefield(source)
    other = GameObject(_card("Other", "Creature — Bear", "", power=1, toughness=1),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    eng.state.add_to_battlefield(other)
    hand_before = len(p1.hand)
    build_effects(
        [EffectSpec("choose_objects", {
            "action": "return_to_hand", "what": "creature", "count": 1,
            "exclude_self": True,
        })],
        source,
    )[0].apply(eng.rules.context, [])
    # Only `other` was eligible (the source is excluded), so this resolves
    # as a forced pick — the source itself never leaves the battlefield.
    assert len(p1.hand) == hand_before + 1
    assert source in eng.state.battlefield
    assert other not in eng.state.battlefield


# ---------------------------------------------------------------------------
# "at the beginning of the next end step, return `<it>` to its owner's
# hand[. if you do, `<effect>`]." — PAR-79 eighth increment. The Alora,
# Cheerful `<X>` cycle's own shape: `_DELAYED_SAC_EXILE_WHEN_FIRST_RE`
# (already shipped for the sacrifice/exile "when-first" siblings, MEC-52)
# widened with a "return" verb branch and an optional "if you do" tail
# collapsed into the *same* delayed trigger's own effects list — plus a new
# `_PREFIXED_DELAYED_SAC_EXILE_RE` dispatch in `parse_effect_body` for when
# an unrelated earlier sentence (Alora's own unblockable-target pick)
# precedes the delayed clause, which every existing "certain antecedent"
# collapse in this family assumes never happens.
# ---------------------------------------------------------------------------


def test_delayed_return_when_first_parses():
    specs = match_clause(
        "at the beginning of the next end step, return that creature to its owner's hand"
    )
    assert specs is not None
    assert specs[0].type == "create_delayed_trigger"
    assert specs[0].params["capture"] == "previous_or_self"
    assert specs[0].params["effects"] == [{"type": "return_specific_to_hand", "params": {}}]


def test_delayed_return_when_first_with_if_you_do_parses():
    specs = match_clause(
        "at the beginning of the next end step, return that creature to its owner's "
        "hand. if you do, each opponent loses 2 life."
    )
    assert specs is not None
    assert specs[0].params["effects"] == [
        {"type": "return_specific_to_hand", "params": {}},
        {"type": "lose_life", "params": {"amount": 2, "selector": "each_opponent"}},
    ]


def test_delayed_return_when_first_if_you_do_unparseable_fails_closed():
    # No handler for this made-up follow-up — the whole clause must stay
    # unclaimed rather than silently dropping the "if you do" half.
    assert match_clause(
        "at the beginning of the next end step, return that creature to its owner's "
        "hand. if you do, frobnicate the sprocket."
    ) is None


def test_delayed_return_when_first_if_you_do_targeted_effect_fails_closed():
    # A genuine RULE 115 target in the follow-up needs its own announced-
    # target step this off-stack delayed-effects list has no way to give
    # it — same reasoning `_may_effect_then` rejects one for.
    assert match_clause(
        "at the beginning of the next end step, return that creature to its owner's "
        "hand. if you do, destroy target artifact."
    ) is None


def test_prefixed_delayed_return_with_if_you_do_parses():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    seg = segment_line(
        "whenever you attack, up to 1 target attacking creature can't be blocked "
        "this turn. at the beginning of the next end step, return that creature to "
        "its owner's hand. if you do, each opponent loses 2 life.",
        allow_spell_effect=True, provenance=ParserProvenance(),
    )
    assert seg.claimed, seg
    assert [e.type for e in seg.spec.effects] == ["unblockable", "create_delayed_trigger"]
    assert seg.spec.effects[1].params["effects"] == [
        {"type": "return_specific_to_hand", "params": {}},
        {"type": "lose_life", "params": {"amount": 2, "selector": "each_opponent"}},
    ]


def test_real_cards_now_modeled_eighth_increment():
    cheerful = (
        "Whenever you attack, up to one target attacking creature can't be "
        "blocked this turn. At the beginning of the next end step, return that "
        "creature to its owner's hand. If you do, {tail}"
    )
    cards = [
        _card("Alora, Cheerful Assassin", "Creature — Halfling Rogue",
              cheerful.format(tail="each opponent loses 2 life."),
              power=1, toughness=1, mana_cost_string="{1}{B}"),
        _card("Alora, Cheerful Mastermind", "Creature — Halfling Rogue",
              cheerful.format(tail="create a 1/1 white Soldier creature token."),
              power=1, toughness=1, mana_cost_string="{1}{W}"),
        _card("Alora, Cheerful Swashbuckler", "Creature — Halfling Rogue",
              cheerful.format(tail="create a Treasure token."),
              power=1, toughness=1, mana_cost_string="{1}{R}"),
        _card(
            "Alora, Rogue Companion", "Creature — Halfling Rogue",
            "Whenever you attack, up to one target attacking creature can't be "
            "blocked this turn. At the beginning of the next end step, return "
            "that creature to its owner's hand.",
            power=1, toughness=1, mana_cost_string="{1}{U}",
        ),
    ]
    for c in cards:
        r = parse_oracle(c)
        assert r.modeled, (c.name, r.unclaimed)


def test_alora_cheerful_scout_stays_unmodeled():
    # The tail's own "it perpetually gets +1/+1" names the just-returned
    # creature again — `create_delayed_trigger`'s `previous_or_self`
    # capture bakes its referent once, at arm time, onto every inner
    # effect built from *this* clause's own recursive parse; a second,
    # independent pronoun reference in the "if you do" follow-up isn't
    # reachable through that (see `_delayed_sac_exile_when_first`'s own
    # docstring) and must stay unclaimed rather than building a
    # `PumpEffect` with no target baked in at all.
    c = _card(
        "Alora, Cheerful Scout", "Creature — Halfling Rogue",
        "Whenever you attack, up to one target attacking creature can't be "
        "blocked this turn. At the beginning of the next end step, return that "
        "creature to its owner's hand. If you do, it perpetually gets +1/+1.",
        power=1, toughness=1, mana_cost_string="{1}{G}",
    )
    r = parse_oracle(c)
    assert not r.modeled


def test_delayed_return_with_if_you_do_fires_both_effects():
    eng = _engine()
    p1 = eng.state.players[0]
    p2 = eng.state.players[1]
    src = GameObject(_card("Src", "Creature — Bear", "", power=1, toughness=1),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    loaned = GameObject(_card("Loaned", "Creature — Bear", "", power=3, toughness=3),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    loaned.controller_id = "p1"
    eng.state.add_to_battlefield(loaned)
    life_before = p2.life

    eng.rules.context.previous_targets = [loaned]
    build_effects(
        match_clause(
            "at the beginning of the next end step, return that creature to its "
            "owner's hand. if you do, each opponent loses 2 life."
        ),
        source=src,
    )[0].apply(eng.rules.context, [loaned])

    assert len(eng.state.delayed_triggers) == 1
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert loaned not in eng.state.battlefield
    assert loaned in p1.hand
    assert p2.life == life_before - 2


# ---------------------------------------------------------------------------
# "return another target `<X>` you control to its owner's hand" — PAR-79
# ninth increment. `other_creature_you_control` (RULE 109.5, built for Giver
# of Runes) was already whitelisted in `targeting.ALLOWED_TARGET_KINDS` and
# already resolved by `resolve_target_kind` — `_return_to_hand`'s own closed
# `_RETURN_TO_HAND_KINDS` set had just never been widened to accept it.
# ---------------------------------------------------------------------------


def test_return_another_target_creature_you_control_parses():
    specs = match_clause(
        "return another target creature you control to its owner's hand"
    )
    assert specs == [EffectSpec("return_to_hand", {
        "target_kind": "other_creature_you_control",
    })]


def test_return_up_to_one_other_target_creature_you_control_parses():
    specs = match_clause(
        "return up to 1 other target creature you control to its owner's hand"
    )
    assert specs is not None
    assert specs[0].params["target_kind"] == "other_creature_you_control"
    assert specs[0].params["optional"] is True


def test_real_cards_now_modeled_ninth_increment():
    cards = [
        _card("Deputy of Acquittals", "Creature — Bird Soldier",
              "Flash\nWhen this creature enters, you may return another "
              "target creature you control to its owner's hand.",
              power=2, toughness=2, mana_cost_string="{2}{W}", keywords=["Flash"]),
        _card("Jeskai Barricade", "Creature — Bird Monk",
              "Flash\nDefender\nWhen this creature enters, you may return "
              "another target creature you control to its owner's hand.",
              power=1, toughness=4, mana_cost_string="{3}{W}", keywords=["Flash", "Defender"]),
    ]
    for c in cards:
        r = parse_oracle(c)
        assert r.modeled, (c.name, r.unclaimed)
