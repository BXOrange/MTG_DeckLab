from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_beamtown_bullies() -> list[AbilitySpec]:
    return [AbilitySpec("activated", [
        EffectSpec("return_from_graveyard", {
            "target_kind": "graveyard_creature", "exclude_legendary": True,
            "controller_target_kind": "opponent", "controller_target_active": True,
            "haste": True,
        }),
        EffectSpec("goad", {"target_kind": None, "referent": "created"}),
        EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any", "capture": "created_objects",
            "effects": [{"type": "exile", "params": {"target_kind": None}}],
            "description": "The Beamtown Bullies: Kreatur ins Exil schicken",
        }),
    ], cost={"taps_self": True}, raw_text="{T}: Target opponent whose turn it is puts target nonlegendary creature card from your graveyard onto the battlefield under their control. It gains haste. Goad it. At the beginning of the next end step, exile it.")]


register("The Beamtown Bullies", _the_beamtown_bullies)
