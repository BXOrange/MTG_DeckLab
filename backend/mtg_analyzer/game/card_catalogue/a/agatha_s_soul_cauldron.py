from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _agathas_soul_cauldron() -> list[AbilitySpec]:
    """You may spend mana as though it were mana of any color to activate
    abilities of creatures you control.
    Creatures you control with +1/+1 counters on them have all activated
    abilities of all creature cards exiled with this artifact.
    {T}: Exile target card from a graveyard. When a creature card is
    exiled this way, put a +1/+1 counter on target creature you control.

    — Agatha's Soul Cauldron. MEC-21 closed both of this card's previously
    unmodeled clauses:

    - The mana-spend permission is `effects.grant_any_color_for_activation`
      (a standing RULE 605.1a wildcard over activation-cost mana, distinct
      from the shipped RULE 605.3a `restriction_predicate_for_cast`/
      `_for_activation` machinery, which restricts *what* a lot of mana can
      pay for rather than *what color* it counts as) — `continuous.
      any_color_for_activation`, consulted by every activation-cost payment
      site in `game/engine/activation_mixin.py`.
    - The dynamic ability grant is `effects.grant_borrowed_activated_
      ability`, reading live off `GameObject.exiled_with_ids` — the
      generalized, *accumulating* "cards exiled with ~" list this card's
      own activated ability below now stamps via `ExileEffect`'s new
      ``track_exiled_with`` param (MEC-21's other named primitive,
      reusable by any future "exile with ~" card; ~185 cached cards print
      that shape). `continuous._apply_borrowed_activated_abilities` builds
      one fresh `ActivatedAbility` per (grantee, exiled creature, ability
      index), reusing the exiled card's own cost/effects (bound once at
      bind-on-load, same as any other permanent's) with each nested
      effect's `.source` redirected to the grantee (RULE 113.7c).

    Documented simplification on the activated ability: the counter
    placement is unconditional rather than gated on "if a **creature** card
    was exiled this way" — this engine's ``exile`` effect has no
    "conditional on the exiled card's own type" follow-up yet (RULE 608.2's
    "when you do" sub-trigger machinery this would need is the same one
    Maestros Theater's cycle uses for its own mandatory "sacrifice it, then
    search" shape, not directly reusable for an optional target's *type*
    instead of a fixed antecedent) — so a noncreature exile still grows a
    counter, strictly more generous than print.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "track_exiled_with": True}),
                EffectSpec("add_counters", {"amount": 1, "target_kind": "creature"}),
            ],
            cost={"taps_self": True},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {"creature_abilities_only": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "creatures_you_control",
                "has_counter_kind": "+1/+1",
                "creature_only": True,
            })],
        ),
    ]


register("Agatha's Soul Cauldron", _agathas_soul_cauldron)
