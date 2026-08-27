"""Cycle/family templating for the hand-authored catalogue.

Most of `ability_catalogue`'s ~660 entries are genuinely unique cards and
stay hand-written `def _card_name() -> list[AbilitySpec]: ...` factories.
A real card *cycle* — several cards sharing one mechanical template and
differing only in a couple of parameters (a colour, a card-type filter, a
cost) — doesn't need that repetition. This is the `entries_NNN.py` files'
counterpart to `parser/oracle/catalogue/lands.py`'s one-regex-per-cycle
style (Circle of Protection: Red/White/Black/Blue/Green/Artifacts/Shadow,
Rune of Protection's own sibling cycle), but for the hand-authored registry
instead of the oracle-text front-end: one small data table + one call
instead of N near-identical factory functions.

Deliberately narrow: `register_family` only fits a family whose members
share exactly one `AbilitySpec` with exactly one `EffectSpec` end to end —
same `ability_kind`, same effect `type`, same trigger (none, here — these
are activated abilities). A family with 2+ abilities per card, or members
that vary in shape (not just in a few param values), doesn't fit this and
should stay hand-written rather than be forced through it.
"""

from __future__ import annotations

from typing import Any, Optional

from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

#: The one param key handled specially: when present in a member's
#: ``overrides``, it replaces the family's ``base_cost`` for that card's
#: `AbilitySpec` instead of being folded into the `EffectSpec` params
#: (Circle of Protection: Artifacts costs {2} where the rest of its cycle
#: costs {1}).
_COST_OVERRIDE_KEY = "cost"


def register_family(
    *,
    ability_kind: str,
    effect_type: str,
    base_params: dict[str, Any],
    entries: list[tuple[str, dict[str, Any], str]],
    base_cost: Optional[dict[str, Any]] = None,
) -> None:
    """Register a family of cards that share one `AbilitySpec`/`EffectSpec`
    shape, differing only in a few per-card values.

    ``entries`` is a list of ``(card_name, overrides, raw_text)`` triples:

    - ``overrides`` is merged over ``base_params`` to build that card's own
      `EffectSpec` params, except for the reserved ``"cost"`` key (see
      `_COST_OVERRIDE_KEY` above), which overrides ``base_cost`` instead of
      being folded into the effect params.
    - ``raw_text`` is that card's own (German) reminder/rules text, exactly
      as `register`'s callers have always supplied it.

    Registers each card via the ordinary `register(name, factory)` — every
    factory still returns fresh `AbilitySpec`/`EffectSpec` objects on each
    call, matching `core.register`'s "fresh copies each call" contract
    (specs are mutated when bound onto a `GameObject`).
    """
    for name, overrides, raw_text in entries:
        params = dict(base_params)
        cost = overrides.get(_COST_OVERRIDE_KEY)
        if cost is None:
            cost = base_cost
        params.update(
            (key, value) for key, value in overrides.items() if key != _COST_OVERRIDE_KEY
        )

        def _factory(
            _ability_kind: str = ability_kind,
            _effect_type: str = effect_type,
            _params: dict[str, Any] = params,
            _cost: Optional[dict[str, Any]] = cost,
            _raw_text: str = raw_text,
        ) -> list[AbilitySpec]:
            return [
                AbilitySpec(
                    _ability_kind,
                    [EffectSpec(_effect_type, dict(_params))],
                    cost=dict(_cost) if _cost else None,
                    raw_text=_raw_text,
                )
            ]

        register(name, _factory)
