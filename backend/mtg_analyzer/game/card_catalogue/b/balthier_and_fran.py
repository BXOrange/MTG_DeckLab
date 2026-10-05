from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _balthier_and_fran() -> list[AbilitySpec]:
    """Reach
    Vehicles you control get +1/+1 and have vigilance and reach.
    Whenever a Vehicle crewed by Balthier and Fran this turn attacks, if
    it's the first combat phase of the turn, you may pay {1}{R}{G}. If you
    do, after this phase, there is an additional combat phase.

    MEC-29: the last of MEC-28's own five-card list, closed by building the
    two primitives its own diagnosis named. RULE 702.122 **Crew** as real
    engine state (`ActivationCost.crew_power`, `GameEngine._resolve_crew_
    cost`/`_crew_pool`, `GameObject.crewed_by_ids`, `effect_binder._crew_
    activated_ability`) — "Crew N" had been parser-*recognized* the whole
    time (the coverage gate's own keyword catalogue), just never bound to
    behaviour anywhere in `game/`/`models/` (`grep -rn "crewed_by"` found
    nothing before this), the same "recognized but inert" gap Cycling had
    before PAR-9 — and a new `"crewed_by_self"` RULE 603.1 group-subject
    trigger-condition key (`effect_binder._build_group_ok`) reading it live
    off the board. Hand-authored here rather than left to the oracle-text
    parser: "a Vehicle crewed by ~ this turn attacks" is a genuinely
    singleton phrasing (`parser_probe.py cards 'crewed by'` finds exactly
    one other cached card, Mighty Servant of Leuk-o, printing a completely
    different "crewed by exactly N creatures" template) not worth a
    dedicated grammar row for.

    The anthem clause is duplicated here rather than left to the parser for
    a narrower reason: it already parses correctly on its own (a real fix
    below), but registering this card for its trigger clause means
    `card_registry.specs_for` takes *all* of this card's non-keyword
    abilities from the registry instead — "Reach" alone still auto-attaches
    from `parse_keywords`, which runs regardless of registration.

    Building Crew surfaced two real, previously-invisible bugs, both fixed
    at the root rather than worked around for this one card:

    1. `_ANTHEM_RE`'s `_scope` (`parser/oracle/catalogue/static_handlers.
       py`) had no non-creature-**subtype** guard the way `_NONCREATURE_
       TYPES` already gives it for non-creature main *types* ("Artifacts
       you control…"), so a bare "Vehicles" scope silently fell through to
       the ordinary creature-subtype reading and produced ``affects:
       creatures_you_control`` — wrong, since a Vehicle isn't a creature
       until crewed, so the anthem would have excluded every uncrewed
       Vehicle it's printed to buff. No real card had ever reached this
       shape's *whole* card fully-MODELED before, so it silently shipped
       wrong without ever showing up as a coverage regression. Fixed with
       `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params`, reused by
       `_GRANT_RE`/`_QUOTED_GRANT_RE`'s existing PAR-3 fallback chain too —
       any other "Vehicles [you control] get/have …" card benefits for
       free, not just this one.
    2. A freshly crewed Vehicle had no power/toughness at all —
       `Card.__init__`'s own invariant refuses P/T on a noncreature, so a
       Vehicle's *printed* P/T (RULE 208.1: some noncreature permanents,
       Vehicles chief among them, print P/T that matters once something
       else makes them a creature) had never been captured anywhere in
       this engine's `Card` model. Without it, `type_change`'s "becomes an
       artifact creature" grant left the crewed Vehicle at 0/0, dying to
       RULE 704.5f the instant the next state-based action check ran —
       Crew would have bound correctly while being unusable in any real
       game. Fixed with `Card.vehicle_power`/`vehicle_toughness`
       (deliberately separate fields, not a relaxation of the existing
       invariant, so every reader that treats "power is not None" as a
       creature check stays correct), populated by `scryfall_client.
       card_from_scryfall_data` for any noncreature Vehicle and read by
       `effect_binder._crew_activated_ability` when building the grant.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "power": 1, "toughness": 1,
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
                EffectSpec("grant_keyword", {
                    "keywords": ["vigilance", "reach"],
                    "affects": "artifacts_you_control", "subtype": "Vehicle",
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "pay_cost_then",
                    {
                        "cost": "{1}{R}{G}",
                        "effects": [{"type": "extra_combat_phase", "params": {}}],
                    },
                    condition={"is_first_combat_phase": True},
                ),
            ],
            trigger={
                "event": "ATTACKS",
                "condition": {"subject": "group", "subtypes": ["vehicle"], "crewed_by_self": True},
            },
        ),
    ]


register("Balthier and Fran", _balthier_and_fran)
