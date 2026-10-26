"""Per-creature "its controller may pay <A> or <B>" decisions over an announced group of X targets (MEC-131).

"Choose X target attacking creatures. For each of those creatures, its controller may pay {1} or {2}. If that player
doesn't, destroy that creature at end of combat. If that player pays only {1}, prevent all combat damage that would be
dealt to and dealt by that creature this combat." (Winter's Chill)

RULE 601.2c: the X targets are announced when the spell is cast. RULE 608.2c / 101.4: on resolution each of them is
visited in turn and *its controller* (not the spell's) decides, so the whole body is one composition: a bare
`choose_targets` announcement, then a `for_each` over those targets whose body is two nested optional payments. The
payer is asked for the larger cost first; declining it, they are asked for the smaller; declining both destroys the
creature at the next end of combat step (RULE 603.7c: the delayed ability names that very creature, not a new target).
Paying only the smaller cost also shields the creature from combat damage both ways for the rest of this combat.

Pure grammar: the costs are read from the clause as generic mana costs, nothing here is keyed on a card name.
"""

from __future__ import annotations

import re
from typing import Optional

from ..spec import EffectSpec
from .effect_rows.shared import ANY_NUMBER_TARGET_CAP

#: The `create_delayed_trigger` step name of the end of combat step (`game/phases.py`).
_END_COMBAT_STEP = "end_combat"


_PER_CREATURE_PAYMENT_RE = re.compile(
    r"choose x target attacking creatures\. "
    r"for each of those creatures, its controller may pay \{(?P<low>\d+)\} or \{(?P<high>\d+)\}\. "
    r"if that player doesn't, destroy that creature at end of combat\. "
    r"if that player pays only \{(?P<only>\d+)\}, prevent all combat damage that would be dealt to and dealt by "
    r"that creature this combat\.?",
    re.IGNORECASE,
)


def _pay(cost: str, paid: list[dict], declined: list[dict]) -> dict:
    """One optional payment by the creature's controller (the iteration item is the payment's subject)."""
    return {"type": "pay_cost_then", "params": {
        "cost": f"{{{cost}}}", "payer": "target_controller", "effects": paid, "else_effects": declined,
    }}


def per_creature_payment_specs(body: str) -> Optional[list[EffectSpec]]:
    m = _PER_CREATURE_PAYMENT_RE.fullmatch(body.strip())
    if m is None:
        return None
    low, high = m.group("low"), m.group("high")
    if int(low) >= int(high) or m.group("only") != low:
        return None  # "pays only <A>" must be the cheaper of the two; anything else is a different rule
    destroy = {"type": "create_delayed_trigger", "params": {
        "step": _END_COMBAT_STEP, "scope": "any", "capture": "targets",
        "effects": [{"type": "destroy_specific", "params": {}}],
    }}
    shield = {"type": "prevent_combat_damage_to_and_by", "params": {}}
    decision = _pay(high, [], [_pay(low, [shield], [destroy])])
    return [
        EffectSpec("choose_targets", {
            "kinds": ["creature"], "count": ANY_NUMBER_TARGET_CAP, "count_selector": "source_x_paid",
            "optional": True, "creature_filter": {"attacking": True},
        }),
        EffectSpec("for_each", {"over": {"targets": True}, "effects": [decision]}),
    ]
