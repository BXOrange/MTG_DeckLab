from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _drain_life() -> list[AbilitySpec]:
    """Spend only black mana on X.
    Drain Life deals X damage to any target. You gain life equal to the
    damage dealt, but not more life than the player's life total before
    the damage was dealt, the planeswalker's loyalty before the damage
    was dealt, or the creature's toughness.

    — MEC-43 round 4A. Two new primitives, plus a real pre-existing engine
    bug the card's own "or the planeswalker's loyalty" clause exposed.
    "Spend only `<color>` mana on X" is a genuinely different RULE 605.3a
    shape from every existing spend restriction (`costs.ActivationCost.
    spend_only_chosen_color` locks an *activated ability's whole* cost;
    `mana_source_kind_restriction` locks a *spell's whole* cost by mana
    *source*): the new `AbilitySpec.cast_x_color_restriction` (bound onto
    `GameObject.x_spend_color_restriction`, read by `GameEngine.
    effective_cast_cost`'s ``{X}``-resolution branch) locks only the
    ``{X}`` portion by *color*, via `ManaCost.with_x_colored` — resolving
    ``{X}`` into ``x`` real `COLOR`-kind pips instead of one generic
    `VARIABLE` pip reuses `ManaPool`'s existing colored-pip backtracking
    solver for free, no pool changes needed. The damage+drain clause is an
    ENG-37 `bind` (B4): its ``amount`` measures the target's ``target_defense``
    (life / loyalty / toughness), clamped to ``[0, X]``, *before* the body
    runs — RULE 608.2 "measured between the two halves" — then the body deals
    X and gains that much (``$cap``). Retires the fused
    ``damage_and_drain_capped``. Along the way: `targeting.legal_targets`'s
    own "any target" (RULE 115.4) turned out to only ever offer creatures and
    players — planeswalkers and battles were never added, a stale gap from
    before either card type was modeled (its own comment said so
    explicitly) — now widened to the real four-way definition, which is
    what makes this card's own planeswalker case reachable at all, and
    should also unlock a stray planeswalker/battle target on every other
    "any target" card already in the cache.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("bind", {
                "name": "cap",
                "amount": {
                    "kind": "target_defense", "of": "target",
                    "minimum": 0, "maximum": "x",
                },
                "effects": [
                    {"type": "damage", "params": {"amount": "x", "target_kind": "any"}},
                    {"type": "gain_life", "params": {"amount": "$cap"}},
                ],
            })],
            cast_x_color_restriction="B",
        ),
    ]


register("Drain Life", _drain_life)
