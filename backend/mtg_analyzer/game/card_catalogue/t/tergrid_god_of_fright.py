from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-43 round 4E — Tergrid God of Fright, Swift Reconfiguration, Angel's
# Grace, Mesmeric Orb, Smokestack, Oko Thief of Crowns
# ---------------------------------------------------------------------------


def _tergrid_god_of_fright() -> list[AbilitySpec]:
    """Menace
    Whenever an opponent sacrifices a nontoken permanent or discards a
    permanent card, you may put that card from a graveyard onto the
    battlefield under your control.

    — Tergrid, God of Fright's front face (MEC-43 round 4E). Menace comes
    from the RULE 702 keyword catalogue. The trigger is a compound RULE
    603.1 subject ("an opponent sacrifices... or discards...") over *two*
    different event types with the same effect body, so — like Orcish
    Bowmasters' ETB-and-draw pair — it's two `AbilitySpec`s sharing one
    effect list rather than one spec naming two events: `EventType.
    SACRIFICE`'s own ``"nontoken"`` group-subject condition (widened this
    round to apply on its own, not only alongside a ``subtypes`` filter —
    see `effect_binder._build_group_ok`) for the first half, `EventType.
    DISCARD_CARD`'s ``"type"`` condition (an OR-list of every permanent
    type word) for the second — the latter needed `DISCARD_CARD` widened
    to actually carry ``object_types`` at all (`draw_discard_mixin.
    _main_type_words`), since nothing had ever needed to tell a discarded
    permanent card apart from a discarded instant/sorcery before.

    "You may put that card from a graveyard onto the battlefield under
    your control" is `ReturnFromGraveyardEffect`'s own ``trigger_subject_
    key`` mode (RULE 400.7/701.3 reanimation of the *exact* object the
    firing event named, not a fresh RULE 115 target), wrapped in a
    ``cost=""`` `PayCostThenEffect` purely for its "you may... if you do"
    framing (Tenacious Dead's same "remember the trigger subject before
    the interactive choice, since `context.trigger_event` isn't live once
    it's answered" idiom) — genuinely free, no cost is actually paid here.
    """
    _reanimate_sacrificed_or_discarded = EffectSpec("pay_cost_then", {
        "cost": "", "remember_trigger_subject": True,
        "prompt": "Karte unter deine Kontrolle ins Spiel bringen?",
        "effects": [{
            "type": "return_from_graveyard",
            "params": {
                "trigger_subject_key": "remembered", "destination": "battlefield",
                "under_your_control": True,
            },
        }],
    })
    return [
        AbilitySpec(
            "triggered",
            [_reanimate_sacrificed_or_discarded],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "group", "controller": "not_you", "nontoken": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [_reanimate_sacrificed_or_discarded],
            trigger={
                "event": EventType.DISCARD_CARD,
                "condition": {
                    "subject": "group", "controller": "not_you",
                    "type": ["artifact", "creature", "enchantment", "land", "planeswalker", "battle"],
                },
            },
        ),
    ]


register("Tergrid, God of Fright", _tergrid_god_of_fright)
