from __future__ import annotations

from ...card_registry.families import register_family

# ---------------------------------------------------------------------------
# Rune of Protection cycle: same `RequestPreventDamageSourceEffect` shield
# shape as the Circle of Protection cycle, cheaper and repeatable per
# activation but at a flat {W} instead of the Circles' generic mana, and
# every member also prints Cycling {2} — the ordinary keyword fold-in
# (PAR-9 — recognized-but-inert became real behaviour independently of this
# registration), so it's not part of this `register_family` call at all.
# Seven members this cycle (White/Blue/Black/Red/Green/Artifacts/Lands —
# note "Lands", not a "Shadow" sibling the way Circle of Protection has
# one), all sharing the one {W} cost, so no member needs a `"cost"`
# override.
# ---------------------------------------------------------------------------

register_family(
    ability_kind="activated",
    effect_type="request_prevent_damage_source",
    base_params={"amount": "all"},
    base_cost={"mana": "{W}"},
    entries=[
        ("Rune of Protection: Green", {"source_filter": {"color": "G"}}),
    ],
)
