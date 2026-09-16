from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kozilek_butcher_of_truth() -> list[AbilitySpec]:
    """When you cast this spell, draw four cards.
    Annihilator 4 (Whenever this creature attacks, defending player
    sacrifices four permanents of their choice.)
    When Kozilek is put into a graveyard from anywhere, its owner shuffles
    their graveyard into their library.

    — MEC-43 round 4B. Annihilator folds in via the ordinary keyword
    catalogue (already real behaviour, RULE 702.86 — `SacrificeEffect`'s
    own ``selector="defending_player"``), unaffected by registering this
    card. The cast trigger needed a genuinely new primitive: "when you
    cast this spell, `<effect>`" (RULE 601.2i/603.2) is a triggered
    ability belonging to the *spell itself*, which only ever exists on the
    stack, not the battlefield, at the moment `SPELL_CAST` fires for it —
    `_collect_triggers`'s main loop is battlefield-only
    (`state.permanents()`), so it could never see this without a
    dedicated scan (`RulesEngine._collect_self_cast_triggers`, new,
    mirroring `_collect_cycled_triggers`/`_collect_suspend_triggers`'s own
    "wrong zone for the main loop" shape).

    **Documented simplification**: the trailing "put into a graveyard
    from anywhere, its owner shuffles their graveyard into their library"
    is left unmodeled — the same call Hostility's own catalogue entry
    already made for the identical primitive gap. RULE 400.7's "from
    anywhere" needs a graveyard-entry event fired uniformly regardless of
    the card's *previous* zone, and this engine's graveyard-bound moves
    reach the graveyard through more than a dozen independent call sites
    across `draw_discard_mixin.py`/`search_mixin.py`/`casting_mixin.py`/
    `damage_death_mixin.py`/`misc_mixin.py`/`copies_mixin.py`/
    `effects.py` (`_move_to_graveyard` is the funnel for only *some* of
    them — sacrifice, SBA death, and a spell resolving to the graveyard,
    not discard or mill, which set `zone = Zone.GRAVEYARD` directly) — a
    genuinely large, cross-cutting primitive disproportionate to build
    correctly for one clause in this batch, unlike the cast trigger above
    (a single well-scoped predicate addition). Left as an open gap rather
    than a half-built event that only fires from some of those sites.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 4})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "self"}},
        ),
    ]


register("Kozilek, Butcher of Truth", _kozilek_butcher_of_truth)
