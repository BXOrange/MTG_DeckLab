from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _opal_eye_kondas_yojimbo() -> list[AbilitySpec]:
    """Defender
    Bushido 1
    {T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead.
    {1}{W}: Prevent the next 1 damage that would be dealt to Opal-Eye this
    turn.

    — Defender/Bushido are the ordinary keyword fold-in. The first
    activated ability is RULE 616.1c *redirection*, not prevention —
    `RequestPreventDamageSourceEffect` doesn't fit at all, hence the new
    `RequestRedirectDamageSourceEffect`/`RulesEngine.redirect_damage_from_
    source` (MEC-30), reusing the exact chooser plumbing (`request_choose_
    objects`'s new `"remember_source_redirect"` action) with a rewritten
    recipient instead of a reduced amount — deliberately not marked
    `prevents_damage`, since RULE 615's "damage can't be prevented this
    turn" has no bearing on a redirect. The second ability is the ordinary
    already-shipped `prevent_damage_shield`, just needing one new small
    flag — `self_only=True` — since "damage to `<this permanent>`" has no
    existing recipient shape (the untargeted default always protects the
    *controller*, not the object itself).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_redirect_damage_source", {"amount": "all"})],
            cost={"text": "{T}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1, "self_only": True})],
            cost={"mana": "{1}{W}"},
        ),
    ]


register("Opal-Eye, Konda's Yojimbo", _opal_eye_kondas_yojimbo)
