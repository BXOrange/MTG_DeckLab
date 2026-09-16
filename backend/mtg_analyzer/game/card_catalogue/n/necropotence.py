from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _necropotence() -> list[AbilitySpec]:
    """Skip your draw step.
    Whenever you discard a card, exile that card from your graveyard.
    Pay 1 life: Exile the top card of your library face down. Put that
    card into your hand at the beginning of your next end step.

    — MEC-38. Three real pieces, none previously reachable: (1) "Skip
    your draw step" is a new `StaticAbility` layer, `"skip_step"` —
    `RulesEngine.should_skip_step` already existed but had never had a
    real card wired to it (its own `Player.player_effects`/`StaticEffect`
    path is a designed-but-never-instantiated primitive; this uses a live
    battlefield read instead, `continuous.skipped_steps_for`, the same
    "no separate enter/leave lifecycle to build" shape `mana_type_
    override`/MEC-36 already established). (2) The discard trigger needed
    a new per-card `EventType.DISCARD_CARD` (the existing `DISCARD` only
    ever carried an aggregate `count`, the same granularity gap MEC-32
    found on the draw side — `RulesEngine.discard`/`discard_specific`/RULE
    614.12's "discard a land instead" now all fire it) plus `ExileEffect`'s
    new `target_kind="trigger_subject"` (mirroring `TapEffect`'s own),
    reading the discarded card's `instance_id` straight off the firing
    event rather than a chosen target — by the time this resolves the
    card is already sitting in the graveyard (discard moves it there
    before firing), so this is a real zone change into exile. (3) The
    activation cost is the already-shipped `ActivationCost.pay_life`; the
    effect needed a new `ExileTopOfLibraryEffect` (deterministic top-card
    exile, unlike `SearchLibraryEffect`'s real choice among the whole
    zone even at `count=1`) feeding `CreateDelayedTriggerEffect`'s
    existing `capture="created_objects"`, widened with a third captured
    attribute name (`exiled_object`, alongside the pre-existing `objects`/
    `target`) so the delayed half can reuse `ReturnUncastExiledEffect`
    unchanged — previously only ever constructed directly in Python
    (Beseech the Mirror/Rebound's own "if it wasn't cast this way" tail),
    never reachable through the `EffectSpec` whitelist until this card
    needed it as an ordinary delayed effect rather than a bespoke one.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("skip_step", {"step": "draw"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "trigger_subject"})],
            trigger={"event": "DISCARD_CARD", "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile_top_of_library", {"face_down": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [
                        {"type": "return_uncast_exiled", "params": {"destination": "hand"}}
                    ],
                }),
            ],
            cost={"text": "Pay 1 life"},
        ),
    ]


register("Necropotence", _necropotence)
