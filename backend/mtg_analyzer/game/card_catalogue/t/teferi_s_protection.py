from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferis_protection() -> list[AbilitySpec]:
    """Until your next turn, your life total can't change and you gain
    protection from everything. All permanents you control phase out.
    Exile Teferi's Protection.

    — Teferi's Protection. Three simultaneous effects sharing one duration,
    so they're one primitive:

    * **mass phasing** (RULE 702.26b) — the shipped `PhaseOutEffect` only
      ever phased a single permanent, and deliberately unattached any Aura/
      Equipment on it. Here host and attachment phase out *together*, so the
      attachment stays valid throughout (RULE 702.26e) — which is the whole
      point of the card as a board-preserving answer. The duration needs no
      bookkeeping of its own: `GameEngine._step_untap`'s existing RULE
      702.26a sweep phases everything back in at your next untap step.
    * **"your life total can't change"** (RULE 119.6) — a *prohibition*, not
      a replacement that rewrites an amount, so `RulesEngine.gain_life`/
      `lose_life` check it at their choke points rather than routing it
      through `apply_replacements`.
    * **protection from everything** for a *player* (RULE 702.16e), which
      reduces to "is dealt no damage" — the only half a player can be
      subject to. Checked in `deal_damage` alongside the permanent-side
      `is_protected_from`, which can't answer it (players carry no printed
      protection).

    The latter two live on `Player.player_effects` (`PlayerShieldEffect`)
    for the same reason Hope of Ghirapur's lock does: the spell is already
    in the graveyard, so there is no permanent to derive a static from. Both
    lapse together in `GameEngine.begin_turn` (RULE 611.2b).

    "Exile Teferi's Protection." is the shipped `ExileEffect` self mode.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("phase_out_all_you_control", {}),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Teferi's Protection", _teferis_protection)
