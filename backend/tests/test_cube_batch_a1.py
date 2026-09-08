"""cEDH staples cube — batch A1: oracle-text parser/binder coverage.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/concepts/
09_ORACLE_EFFECT_PARSER.md. This batch extended the **generic, reusable**
handler layer (`parser/oracle/catalogue/handlers.py`/`subgrammars.py`,
`game/effects/core.py`, `game/binding/core.py`, `game/costs.py`,
`game/top_library.py`) to flip real cEDH-cube cards from `UNMODELED` to
`MODELED`. Some plumbing (`parser/oracle/segmenter.py`'s trigger-wrapper
vocabulary, `game/targeting.py`'s target-kind vocabulary,
`game/game_engine.py`'s cast/activation legality,
`game/rules_engine.py`'s win/loss primitive) had to grow alongside those
owned files since a handler alone can't reach a permanent's non-effect
clauses or wire new cast/cost/win behaviour — see each test's docstring for
which mechanism it exercises.

Every test uses the real cached card (not a hand-built fixture) so a
`parse_oracle` regression here means a real card silently stopped
resolving. Cards that stay `UNMODELED` even after this batch (a real,
separate engine gap unrelated to what was fixed) are asserted as such,
pinning the *specific* remaining blocker so a future fix's regression shows
up here too — see docs/implementation-state/BACKLOG.md's "cEDH
staples cube" section for the full reasoning on each.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import (
    ActivatedAbility,
    PumpEffect,
    TapEffect,
    TriggeredAbility,
    WinGameEffect,
)
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _bound(name: str, zone=Zone.BATTLEFIELD) -> GameObject:
    """A real cached card, parsed + bound onto a fresh `GameObject`."""
    card = _card(name)
    obj = GameObject(card, owner_id="p1", zone=zone)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


# ---------------------------------------------------------------------------
# Item 1: "choose <n> —" modal fixes
# ---------------------------------------------------------------------------


def test_you_come_to_a_river_modeled():
    """Named-mode label ("Fight the Current — <effect>") already peeled by
    `gate._parse_mode_body`; mode 2's "gets +1/+0 ... and can't be blocked
    this turn" needed a new combined pump+unblockable handler
    (`handlers._pump_unblockable`/`PumpEffect.unblockable`)."""
    card = _card("You Come to a River")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = _bound("You Come to a River", zone=Zone.STACK)
    assert obj.spell_modes and len(obj.spell_modes) == 2
    mode2 = obj.spell_modes[1]["effects"]
    assert any(isinstance(e, PumpEffect) and e.unblockable for e in mode2)


def test_red_elemental_blast_and_pyroblast_modeled():
    """Old-templating colour restriction, both forms: the adjective
    ("destroy target blue permanent", `handlers._destroy_color_adj`) and
    the trailing "if it's blue" clause (`subgrammars.IF_COLOR_SUFFIX`),
    both folding into a `color` param `targeting.py` filters on."""
    for name in ("Red Elemental Blast", "Pyroblast"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)
    obj = _bound("Red Elemental Blast", zone=Zone.STACK)
    assert obj.spell_modes and len(obj.spell_modes) == 2
    counter_mode, destroy_mode = obj.spell_modes[0]["effects"], obj.spell_modes[1]["effects"]
    assert counter_mode[0].target_spec.spell_filter == {"color": "U"}
    assert destroy_mode[0].target_spec.color == "U"


def test_archdruid_charm_stays_unmodeled_two_targeting_effects():
    """A real, current engine ceiling (docs/11 §5: "at most one targeting
    effect per AbilitySpec") plus a dynamic "damage equal to its power"
    amount and a conditional search destination — see BACKLOG.md."""
    result = parse_oracle(_card("Archdruid's Charm"))
    assert not result.modeled
    assert any("deals damage equal to its power" in u for u in result.unclaimed)


def test_tooth_and_nail_stays_unmodeled_no_battlefield_from_hand_effect():
    """Entwine aside, mode 2 ("Put up to two creature cards from your hand
    onto the battlefield.") has no matching engine effect at all — see
    BACKLOG.md."""
    result = parse_oracle(_card("Tooth and Nail"))
    assert not result.modeled


# ---------------------------------------------------------------------------
# Item 2: condition-gated free-cast alternative cost
# ---------------------------------------------------------------------------


def test_deadly_rollick_and_fierce_guardianship_modeled():
    """"If you control a commander, you may cast this spell without paying
    its mana cost." — `AbilitySpec.free_cast_condition` (mirrors
    `conditional_flash`'s shape), bound onto `obj.free_cast_condition` and
    checked live by `condition_query.free_cast_condition_holds` /
    `GameEngine.can_cast(..., free=True)`."""
    for name in ("Deadly Rollick", "Fierce Guardianship"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)
    obj = _bound("Deadly Rollick", zone=Zone.STACK)
    assert obj.free_cast_condition == {"control_commander": True}


def test_deflecting_swat_stays_unmodeled_no_redirect_primitive():
    """The shared free-cast clause is modeled; "You may choose new targets
    for target spell or ability." has no redirect mechanism — see
    BACKLOG.md (binding it as a no-op would silently do nothing the
    card claims to do)."""
    result = parse_oracle(_card("Deflecting Swat"))
    assert not result.modeled
    assert any("choose new targets" in u for u in result.unclaimed)


# ---------------------------------------------------------------------------
# Item 3: non-mana additional activation cost + "activate only once"
# ---------------------------------------------------------------------------


def test_quirion_ranger_and_scryb_ranger_modeled():
    """"Return a Forest you control to its owner's hand: Untap target
    creature. Activate only once each turn." — `costs.ActivationCost.
    return_to_hand` (a new non-mana cost component, charged by
    `GameEngine._pay_activation_cost`/`_return_to_hand_candidate`) plus
    `ActivatedAbility.once_per_turn` (the marker-EffectSpec smuggling trick,
    `handlers.ONCE_PER_TURN_MARKER`, stripped by `effect_binder.bind_
    ability` before building real effects)."""
    for name in ("Quirion Ranger", "Scryb Ranger"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)
    obj = _bound("Quirion Ranger")
    ability = obj.activated_abilities[0]
    assert isinstance(ability, ActivatedAbility)
    assert ability.once_per_turn is True
    assert ability.cost.return_to_hand == "forest"


# ---------------------------------------------------------------------------
# Item 7: standing "look at top card any time" — informational no-op
# ---------------------------------------------------------------------------


def test_look_at_top_any_time_claimed_but_permission_clause_still_blocks():
    """Elsha/Bolas's Citadel's "You may look at the top card of your
    library any time." line is now claimed as a documented no-op
    (`segmenter._LOOK_AT_TOP_ANY_TIME_RE`) — it no longer appears in
    ``unclaimed`` — but each card's *actual* play/cast-from-top permission
    clause has no parser-front-end recognition yet (only hand-authored per
    card today), so the cards stay `UNMODELED` overall. See
    docs/implementation-state/BACKLOG.md."""
    for name in ("Elsha of the Infinite", "Bolas's Citadel"):
        result = parse_oracle(_card(name))
        assert not result.modeled
        assert not any("look at the top card" in u for u in result.unclaimed), (name, result.unclaimed)


# ---------------------------------------------------------------------------
# Item 8: Magecraft trigger family
# ---------------------------------------------------------------------------


def test_witherbloom_apprentice_modeled():
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    <effect>." A dedicated whole-line recognizer (`segmenter._MAGECRAFT_RE`)
    peels the "Magecraft — " ability-word label and binds a `SPELL_CAST`
    trigger filtered to instant/sorcery via the existing `spell_subtype_any`
    predicate; "or copy" is unreachable today (no spell-copy event bus
    anywhere in the engine) — a cross-cutting gap, not a card-specific one."""
    result = parse_oracle(_card("Witherbloom Apprentice"))
    assert result.modeled, result.unclaimed
    obj = _bound("Witherbloom Apprentice")
    assert len(obj.triggered_abilities) == 1
    ability = obj.triggered_abilities[0]
    assert isinstance(ability, TriggeredAbility)
    assert ability.trigger_event == "SPELL_CAST"


def test_professor_onyx_stays_unmodeled_unrelated_loyalty_abilities():
    """Magecraft itself parses fine (proven by Witherbloom Apprentice
    above); Professor Onyx stays `UNMODELED` because its +1/-3/-8 loyalty
    abilities are each their own complex, unrelated, unmodeled mechanic —
    see BACKLOG.md. Also proves the loyalty-ability bracket fix
    (below) doesn't over-claim: these lines are now *recognized* as loyalty
    abilities but still correctly fail on their own unparseable bodies."""
    result = parse_oracle(_card("Professor Onyx"))
    assert not result.modeled
    assert not any("magecraft" in u for u in result.unclaimed)
    assert any(u.startswith("+1:") for u in result.unclaimed)


# ---------------------------------------------------------------------------
# Item 11: standing end-step self-sacrifice trigger
# ---------------------------------------------------------------------------


def test_dress_down_and_underworld_breach_end_step_sac_claimed():
    """"At the beginning of the end step, sacrifice this enchantment." is
    now claimed (`segmenter._PHASE_TRIGGER_RE` for the turn-structure
    trigger family + `SacrificeSelfEffect` for the plain self-sac) — both
    cards stay `UNMODELED` only because of their own separate static-ability
    line (`static_handlers.py`, out of this batch's scope — see
    BACKLOG.md)."""
    for name in ("Dress Down", "Underworld Breach"):
        result = parse_oracle(_card(name))
        assert not result.modeled
        assert not any("sacrifice" in u and "enchantment" in u for u in result.unclaimed), (
            name, result.unclaimed
        )


# ---------------------------------------------------------------------------
# Item 12: Aura activated ability targeting "enchanted creature"
# ---------------------------------------------------------------------------


def test_freed_from_the_real_modeled():
    """"{U}: Tap enchanted creature." / "{U}: Untap enchanted creature." —
    `TapEffect`'s new ``target_kind="attached_permanent"`` mode, resolved
    live off the Aura's own `attached_to` at resolution (mirrors
    `effect_binder._subject_condition`'s trigger-side `"attached_permanent"`
    concept, applied to an effect's *target* instead)."""
    result = parse_oracle(_card("Freed from the Real"))
    assert result.modeled, result.unclaimed
    obj = _bound("Freed from the Real")
    assert len(obj.activated_abilities) == 2
    for ability in obj.activated_abilities:
        effect = ability.effects[0]
        assert isinstance(effect, TapEffect)
        assert effect._attached_mode is True


def test_pemmins_aura_stays_unmodeled_inline_or_modal():
    """Three of its four activated abilities (tap/untap/flying/shroud) now
    model fine via the same `attached_permanent` mechanism; the fourth
    ("gets +1/-1 or -1/+1") is an inline two-way modal choice with no
    bulleted "Choose one —" header — the modal grammar doesn't recognize
    that shape. See BACKLOG.md."""
    result = parse_oracle(_card("Pemmin's Aura"))
    assert not result.modeled
    assert len(result.unclaimed) == 1
    assert "+1/-1 or -1/+1" in result.unclaimed[0]


# ---------------------------------------------------------------------------
# Item 13: type-filtered target ("target legendary permanent")
# ---------------------------------------------------------------------------


def test_minamo_modeled():
    """"{U}, {T}: Untap target legendary permanent." — a new
    ``legendary_permanent`` target kind (`targeting.py`, filtered on
    `Card.is_legendary`), reachable from `_tap`'s widened allow-list."""
    result = parse_oracle(_card("Minamo, School at Water's Edge"))
    assert result.modeled, result.unclaimed
    obj = _bound("Minamo, School at Water's Edge")
    ability = obj.activated_abilities[0]
    effect = ability.effects[0]
    assert isinstance(effect, TapEffect)
    assert effect.target_spec.kind == "legendary_permanent"


# ---------------------------------------------------------------------------
# Item 14: self-exile trailing clause
# ---------------------------------------------------------------------------


def test_mnemonic_betrayal_and_teferis_protection_self_exile_claimed():
    """"Exile ~." is now claimed (`ExileEffect`'s new ``target_kind=None``
    self mode, mirroring `TapEffect`/`RegenerateEffect`) — each card stays
    `UNMODELED` only for its own separate, unrelated reason: Mnemonic
    Betrayal's main effect is the same "impulsive draw" primitive gap
    Ragavan needs (BACKLOG.md); Teferi's Protection needs a phasing
    subsystem that doesn't exist at all (BACKLOG.md, pre-existing)."""
    betrayal = parse_oracle(_card("Mnemonic Betrayal"))
    assert not betrayal.modeled
    assert not any(u == "exile ~." for u in betrayal.unclaimed)

    teferi = parse_oracle(_card("Teferi's Protection"))
    assert not teferi.modeled
    assert not any(u == "exile ~." for u in teferi.unclaimed)
    assert any("phase out" in u for u in teferi.unclaimed)


# ---------------------------------------------------------------------------
# Item 15: alternative win condition (new replacement type) + a real
# loyalty-ability bracket-notation bug this investigation surfaced
# ---------------------------------------------------------------------------


def test_jace_wielder_of_mysteries_and_laboratory_maniac_modeled():
    """"If you would draw a card while your library has no cards in it, you
    win the game instead." — a new `ReplacementRegistry` type
    (`win_instead_of_empty_draw`) intercepting the DRAW event and calling
    the new `RulesEngine.player_wins` primitive. Jace's own loyalty
    abilities only became reachable once `segmenter._LOYALTY_LINE_RE` was
    fixed to accept real (bracket-less) Scryfall loyalty-cost text ("+1:",
    not "[+1]:") — the pre-existing test fixture for that regex used a
    fictional bracketed format no real card actually prints, silently
    masking that no planeswalker's loyalty abilities were ever reachable
    from real oracle text before this fix."""
    result = parse_oracle(_card("Laboratory Maniac"))
    assert result.modeled, result.unclaimed
    obj = _bound("Laboratory Maniac")
    assert len(obj.replacement_effects) == 1

    jace = parse_oracle(_card("Jace, Wielder of Mysteries"))
    assert jace.modeled, jace.unclaimed
    jace_obj = _bound("Jace, Wielder of Mysteries")
    assert len(jace_obj.replacement_effects) == 1
    assert len(jace_obj.activated_abilities) == 2  # +1 and -8, both loyalty
    assert all(a.cost.is_loyalty for a in jace_obj.activated_abilities)
    minus_eight = next(a for a in jace_obj.activated_abilities if a.cost.loyalty == -8)
    assert any(isinstance(e, WinGameEffect) for e in minus_eight.effects)
