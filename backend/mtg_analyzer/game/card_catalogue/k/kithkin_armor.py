from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kithkin_armor() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature can't be blocked by creatures with power 3 or
    greater.
    Sacrifice this Aura: The next time a source of your choice would deal
    damage to enchanted creature this turn, prevent that damage.

    — The Enchant keyword and the block restriction are *both* real parser
    output (confirmed via `parse_oracle` on the clause in isolation — only
    the shield clause is `UNCLAIMED`), so registering this card means
    replicating them by hand too, not just the shield — the same Haazda
    Shield Mate lesson: `specs_for` trusts a registered card wholesale. The
    shield needed a new small param on `RequestPreventDamageSourceEffect`:
    ``recipient="attached_permanent"`` (MEC-30) — Family B's own sibling of
    Family A's already-shipped ``to="attached_permanent"``, reading
    ``self.source.attached_to`` instead of the caster/an RULE 115 target.
    Read at *resolution* time, after the sacrifice cost has already moved
    this Aura to the graveyard — safe because this engine doesn't clear
    `GameObject.attached_to` on a zone change (the same "the object's last
    known state survives its own move" convention `LoseLifeEffect.amount_
    from_trigger_event`'s own docstring documents for RULE 400.7).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"}),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
                "affects": "attached_permanent",
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "attached_permanent", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Kithkin Armor", _kithkin_armor)
