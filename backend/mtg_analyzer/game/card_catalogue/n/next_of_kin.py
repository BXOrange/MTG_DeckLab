from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _next_of_kin() -> list[AbilitySpec]:
    """Enchant creature folds in; the dies trigger chooses without targeting."""
    return [AbilitySpec("triggered", [EffectSpec("choose_objects", {
        "action": "zone_to_battlefield", "what": "creature", "optional": True,
        "prompt": "Kreaturenkarte aus Hand oder Kommandozone ins Spiel bringen",
        "pool_zones": ["hand", "command"], "mana_value_less_than_trigger": True,
        "then": [{"type": "create_delayed_trigger", "params": {
            "step": "end", "scope": "any", "capture": "previous_targets",
            "description": "Next of Kin: Aura zurückbringen",
            "effects": [{"type": "return_self_from_graveyard", "params": {
                "attach_to_previous": True,
            }}],
        }}],
    })], trigger={"event": "DIES", "condition": {"subject": "attached_permanent"}},
        raw_text="When enchanted creature dies, you may put a creature card you own with lesser mana value from your hand or from the command zone onto the battlefield. If you do, return this card to the battlefield attached to that creature at the beginning of the next end step.")]


register("Next of Kin", _next_of_kin)
