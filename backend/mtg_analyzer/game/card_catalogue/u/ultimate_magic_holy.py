from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ultimate_magic_holy() -> list[AbilitySpec]:
    """Permanents you control gain indestructible until end of turn. If this spell was cast from exile, prevent all damage that would be dealt to you this turn.
    Foretell {2}{W} (During your turn, you may pay {2} and exile this card from your hand face down. Cast it on a later turn for its foretell cost.)

    — PLAY-ALL (Limit Break). Foretell is the keyword. `pump` over the structured group of every permanent you control (keyword grant); then `prevent_damage_shield` (all, to you)
    behind the ``foretold`` flag condition — **simplification:** "cast from exile" is read as "was foretold", the only way these cards are cast from exile.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "foretell", "cost": "{2}{W}"}),
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("pump", {"keywords": ["indestructible"], "selector": {"zone": "battlefield", "of": "you", "filter": {}}}),
                EffectSpec("prevent_damage_shield", {"amount": "all"}, condition={"kind": "flag", "flag": "foretold", "of": "source"}),
            ],
        ),
    ]


register("Ultimate Magic: Holy", _ultimate_magic_holy)
