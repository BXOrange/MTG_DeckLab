"""Both physical faces of Invasion of Tarkir."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_tarkir():
    """(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)
When this Siege enters, reveal any number of Dragon cards from your hand. When you do, this Siege deals X plus 2 damage to any other target, where X is the number of cards revealed this way. (X can be 0.)"""
    return [AbilitySpec("triggered", [EffectSpec("tarkir_reveal_dragons", {})],
                        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}})]


def _defiant_thundermaw():
    """Flying, trample
Whenever a Dragon you control attacks, it deals 2 damage to any target."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("triggered", [EffectSpec("damage", {
            "amount": 2, "target_kind": "any", "dealer_event_key": "__group_subject__",
        })], trigger={"event": EventType.ATTACKS, "condition": {
            "subject": "group", "controller": "you", "other": False, "subtypes": ["dragon"], "nontoken": False,
        }}),
    ]


register("Invasion of Tarkir", _invasion_of_tarkir)
register("Invasion of Tarkir // Defiant Thundermaw", _invasion_of_tarkir)
register("Defiant Thundermaw", _defiant_thundermaw)
