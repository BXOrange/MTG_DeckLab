"""Blitz payments and battlefield consequences (RULE 702.152)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.game.events import EventType
from ..models.game.game_state import DelayedTrigger
from ..models.mana.mana_cost import VARIABLE, ManaCost
from . import continuous, static_conditions
from .costs import ActivationCost, parse_activation_cost
from .effects.core import GameEffect, StaticAbility


class BlitzSacrificeEffect(GameEffect):
    """The caster sacrifices only the permanent that this spell became.

    RULE 603.7c / 400.7: leaving and returning makes a new object. RULE
    701.17a: the delayed ability's controller cannot sacrifice another
    player's permanent, even if that player now controls the blitz creature.
    """
    def __init__(self, obj: Any, controller_id: str) -> None:
        super().__init__(obj)
        self.incarnation = obj.timestamp
        self.controller_id = controller_id

    def apply(self, context, targets=None) -> None:
        obj = self.source
        if (obj in context.state.battlefield and not obj.phased_out
                and obj.timestamp == self.incarnation
                and obj.controller_id == self.controller_id):
            context.engine.put_into_graveyard(obj)


@dataclass(frozen=True)
class BlitzCost:
    payment: ActivationCost
    minimum_mana_value: int = 0

    def available(self, card, x=0):
        # RULE 202.3e: announced X counts in a spell's mana value on the stack.
        return ManaCost.from_card(card).with_x(x).resolved_value >= self.minimum_mana_value

    def minimum_x(self, card):
        cost = ManaCost.from_card(card)
        variables = sum(symbol.kind == VARIABLE for symbol in cost.symbols)
        missing = max(0, self.minimum_mana_value - cost.converted_mana_cost)
        return (missing + variables - 1) // variables if variables else 0


def _statics_for(state, player, kind):
    for ability in continuous._battlefield_static_abilities(state):
        source = ability.source
        if (ability.layer == kind and source is not None
                and source.controller_id == player.id
                and not getattr(source, "loses_all_abilities", False)
                and static_conditions.condition_holds(
                    ability.params.get("active_if"), state, source, player.id)):
            yield ability


def costs_for(state, player, obj) -> list[BlitzCost]:
    """Separate choices for printed and granted instances (RULE 702.152b)."""
    result = []
    printed = (obj.parametric_keywords or {}).get("blitz", {}).get("cost")
    if printed:
        result.append(BlitzCost(parse_activation_cost(printed)))
    if "blitz" in obj.perpetual_keywords:
        result.append(BlitzCost(parse_activation_cost(obj.card.mana_cost_string or "{0}")))
    for ability in _statics_for(state, player, "grant_blitz"):
        params = ability.params
        minimum = int(params.get("min_mana_value", 0))
        if not obj.card.is_creature or (
            obj.card.converted_mana_cost < minimum and not ManaCost.from_card(obj.card).has_variable
        ):
            continue
        if params.get("from_hand") and obj not in player.hand:
            continue
        raw = params.get("cost")
        result.append(BlitzCost(parse_activation_cost(raw or obj.card.mana_cost_string or "{0}"), minimum))
    return result


def reduction_for(state, player) -> int:
    """Henzie's reduction counts all of this player's command-zone casts."""
    return sum(
        sum(player.commander_casts.values()) * int(ability.params.get("amount", 1))
        for ability in _statics_for(state, player, "blitz_cost_reduction")
    )


def graveyard_permission(obj) -> bool:
    return any(getattr(ability, "layer", None) == "blitz_graveyard_permission" for ability in obj.static_effects)


def resolve_blitz(state, obj, controller_id) -> None:
    """Keep the payment fact through stack→battlefield (RULE 400.7c).

    The ability grant is conditional on that fact, rather than an EOT buff;
    losing all abilities suppresses it and a later zone change clears it.
    The delayed ability exists independently of the creature's abilities.
    """
    if not obj.blitz_cost_paid:
        return
    obj.static_effects = [ability for ability in obj.static_effects
                          if not getattr(ability, "params", {}).get("blitz_grant")]
    obj.static_effects.append(StaticAbility(
        "ability", affects="self", source=obj,
        params={"blitz_grant": True, "keywords": ["haste"], "trigger_event": EventType.DIES,
                "grant_effects": [{"type": "draw", "params": {"count": 1}}],
                "active_if": {"kind": "flag", "flag": "blitz_cost_paid"}},
        description="Blitz: Beim Sterben eine Karte ziehen",
    ))
    state.delayed_triggers.append(DelayedTrigger(
        controller_id=controller_id, step="end", scope="any",
        effects=[BlitzSacrificeEffect(obj, controller_id)],
        description=f"{obj.name}: Blitz — im nächsten Endsegment opfern",
    ))


class ChoosePerpetualBlitzEffect(GameEffect):
    """Riveteers Provocateur's permanent card modification (MEC-109).

    Reuses the serializable object chooser and MEC-98's perpetual keyword
    storage; the cost is derived from the selected card's mana cost.
    """
    def apply(self, context, targets=None) -> None:
        player = context.state.player_by_id(context.resolving_controller_id or self.source.controller_id)
        if player is None:
            return
        candidates = [obj for obj in player.hand if obj.card.is_creature
                      and "blitz" not in (obj.parametric_keywords or {})
                      and "blitz" not in obj.perpetual_keywords]
        context.choose_objects(
            player, candidates, "grant_perpetual_blitz", count=1,
            prompt="Kreaturenkarte ohne Blitz wählen", source=self.source,
        )
