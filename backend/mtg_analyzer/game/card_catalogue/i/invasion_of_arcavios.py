"""Both faces of Invasion of Arcavios."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_arcavios():
    """(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)
When this Siege enters, search your library, graveyard, and/or outside the game for an instant or sorcery card you own, reveal it, and put it into your hand. If you search your library this way, shuffle."""
    return [AbilitySpec("triggered", [EffectSpec("arcavios_search", {})],
                        trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}})]


def _invocation_of_the_founders():
    """Whenever you cast an instant or sorcery spell from your hand, you may copy that spell. You may choose new targets for the copy."""
    return [AbilitySpec("triggered", [EffectSpec("copy_spell", {
        "spell_from_trigger_event": "instance_id", "choose_new_targets": True,
    })], trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                 "spell_cast_from": ["hand"], "spell_filter": {"card_type_any": ["instant", "sorcery"]}},
        optional=True)]


register("Invasion of Arcavios", _invasion_of_arcavios)
register("Invasion of Arcavios // Invocation of the Founders", _invasion_of_arcavios)
register("Invocation of the Founders", _invocation_of_the_founders)
