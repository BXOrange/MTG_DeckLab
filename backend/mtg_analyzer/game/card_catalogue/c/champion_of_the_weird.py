from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# "Champions of the Perfect" was hand-authored (Eliferate deck batch) only
# because "behold an Elf and exile it" as an additional cast cost had no
# `AbilitySpec.additional_cost` vocabulary and the "return the exiled card
# to its owner's hand" trigger had nothing to reference. PAR-30's
# ``behold_exile`` additional cost + `ReturnLinkedExileEffect(destination=
# "hand")` cover both now, and the cast-trigger draw always parsed — so the
# whole card is parser-MODELED and the hand-authored stopgap is retired
# (removing it lets `specs_for` fall through to the oracle front-end). See
# `Done_Backend.md` "Collect Evidence / Forage / Blight".


def _champion_of_the_weird() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, behold a Goblin and exile
    it. (Exile a Goblin you control or a Goblin card from your hand.)
    Pay 1 life, Blight 2: Target opponent blights 2. Activate only as a
    sorcery.
    When this creature leaves the battlefield, return the exiled card to
    its owner's hand.

    — PAR-30 (Collect Evidence / Forage / Blight residue). The
    ``behold_exile`` additional cost + `ReturnLinkedExileEffect(destination=
    "hand")` are the shared Champion-cycle primitive (see `Done_Backend.md`);
    the only genuinely singleton part is the activated body — "target
    opponent **blights** 2", the outward-facing sibling of the "you blight
    N" verb (`BlightEffect(target_kind="opponent")` — the RULE 115 target
    is the player, the -1/-1 counters go on a creature *they* choose to
    control). `Pay 1 life, Blight 2` is a real compound `ActivationCost`
    (`pay_life` + `blight`, the latter auto-picking non-interactively per
    PAR-29), and "Activate only as a sorcery" is ``sorcery_speed_only``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            additional_cost={"behold_exile": "Goblin"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("blight", {"amount": 2, "target_kind": "opponent"})],
            cost={
                "text": "Pay 1 life, Blight 2",
                "pay_life": 1, "blight": 2, "sorcery_speed_only": True,
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {"destination": "hand"})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Champion of the Weird", _champion_of_the_weird)
