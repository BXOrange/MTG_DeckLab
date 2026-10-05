from __future__ import annotations

from ...card_registry.families import register_family

# ---------------------------------------------------------------------------
# Circle of Protection cycle: "{N}: The next time a <qualifier> source of
# your choice would deal damage to you this turn, prevent that damage." —
# same `RequestPreventDamageSourceEffect` template (`RulesEngine.request_
# choose_objects`'s interactive "choose a source" pick over every
# battlefield permanent matching `source_filter`, then a `RulesEngine.
# prevent_damage_to_player`-shaped shield scoped to whichever one gets
# picked; repeatable — nothing marks the ability itself once-per-turn,
# matching the real printed text) across all seven members, differing only
# in `source_filter`, one member's own cost (Artifacts is {2} where the
# rest of the cycle is {1}). The Rune of Protection cycle (same
# `register_family` helper, see `card_registry/families.py`) and Story
# Circle/Prismatic Circle/Circle of Solace, which reuse this exact shield
# shape but pick their colour interactively at ETB (RULE 601.2b) rather
# than printing it, aren't a fit for this templating and stay hand-written.
# ---------------------------------------------------------------------------

register_family(
    ability_kind="activated",
    effect_type="request_prevent_damage_source",
    base_params={"amount": "all"},
    base_cost={"mana": "{1}"},
    entries=[
        ("Circle of Protection: Blue", {"source_filter": {"color": "U"}}),
    ],
)
