from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pure_intentions() -> list[AbilitySpec]:
    """Whenever a spell or ability an opponent controls causes you to
    discard cards this turn, return those cards from your graveyard to
    your hand.
    When a spell or ability an opponent controls causes you to discard
    this card, return this card from your graveyard to your hand at the
    beginning of the next end step.

    MEC-101 — the first card to use the new "caused you to discard"
    provenance: `RulesEngine.discard`/`discard_random`/`discard_specific`/
    `discard_matching` now all take a ``cause`` (the responsible spell/
    ability's own `GameObject`) and stamp `EventType.DISCARD_CARD`'s own
    ``cause_controller_id`` with it, so `binding.core`'s new
    ``requires_opponent_caused_discard`` trigger-condition predicate can
    tell a hostile discard apart from RULE 514.2's own cleanup or a cost
    the discarding player paid themself (neither passes a ``cause``).

    The first paragraph is the instant's own resolution: a RULE 603.7a
    `create_turn_trigger` (the same primitive Thunderclap Drake/Bonus
    Round use for "…this turn" — `Done_Backend.md`'s v455 entry), whose
    inner body reads the firing `DISCARD_CARD` event's own object back via
    `ReturnToHandEffect`'s already-general ``target_kind="trigger_subject"``
    (PAR-123, Cunning Evasion) — `RulesEngine.return_to_hand` already moves
    an object out of whatever zone it's currently in, graveyard included,
    so no new effect was needed for "those cards" at all, only the new
    trigger condition to gate *which* discards this floating ability reacts
    to.

    The second paragraph functions from the graveyard the *discard itself*
    puts it in (RULE 112.6a) — unlike Cycling's own `_collect_cycled_
    triggers`, nothing here puts the card there *on purpose*; the ability
    just has to still be watched once it lands there, which needed a new
    `triggers_mixin._collect_discarded_triggers` scan (the `state.
    permanents()` main loop is battlefield-only, so a hand-zone self-
    subject `DISCARD_CARD` trigger would otherwise never be seen at all).
    Its own effect is an ordinary RULE 603.7 `create_delayed_trigger`
    wrapping the pre-existing `return_self_from_graveyard_to_hand` (PAR-16)
    — no ``capture`` needed, since `build_effects` already threads this
    ability's own source (the discarded card itself) into the delayed
    effect, and RULE 400.7 instance-id stability (`rule-400-7-new-object-
    identity`) means that reference is still valid once the delayed
    trigger actually fires.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("create_turn_trigger", {
            "trigger": {
                "event": "DISCARD_CARD",
                "condition": {"subject": "you"},
                "requires_opponent_caused_discard": True,
            },
            "effects": [{
                "type": "return_to_hand",
                "params": {"target_kind": "trigger_subject"},
            }],
            "description": "whenever a spell or ability an opponent controls causes you "
                            "to discard cards this turn, return those cards from your "
                            "graveyard to your hand",
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_delayed_trigger", {
                "step": "end",
                "scope": "any",
                "effects": [{"type": "return_self_from_graveyard_to_hand", "params": {}}],
                "description": "return this card from your graveyard to your hand at "
                                "the beginning of the next end step",
            })],
            trigger={
                "event": "DISCARD_CARD",
                "condition": {"subject": "self"},
                "requires_opponent_caused_discard": True,
            },
        ),
    ]


register("Pure Intentions", _pure_intentions)
