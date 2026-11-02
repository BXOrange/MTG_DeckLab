from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Life lost when the damaging source's controller does not pay Elesh Norn's {1} (printed "loses 2 life").
_ELESH_NORN_LIFE_LOSS = 2
#: Incubator tokens chapter I makes ("Incubate 2 five times") and the +1/+1 counters each starts with.
_ARGENT_ETCHINGS_INCUBATOR_COUNT = 5
_ARGENT_ETCHINGS_INCUBATE_AMOUNT = 2


def _elesh_norn() -> list[AbilitySpec]:
    """Vigilance
    Whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller
    loses 2 life unless they pay {1}.
    {2}{W}, Sacrifice three other creatures: Exile Elesh Norn, then return it to the battlefield transformed under its
    owner's control. Activate only as a sorcery.

    — Vigilance is the printed keyword. The damage clause is two DAMAGE triggers sharing one effect (a damage event
    names either a player or a permanent, never both): ``recipient_is_you`` (Mikaeus) for damage to you, and the
    ``recipient`` group form (Rite of Passage) for damage to a permanent you control, both scoped to opponents'
    sources with the ``by_opponent`` filter (Archfiend of Spite). The new `damage_source_pays_or_loses_life` owes
    the RULE 118.12 "unless" payment to the dealing source's controller. The flip is `blink` of the source with
    ``transformed`` (RULE 712.8; Ral, Monsoon Mage's primitive), gated to sorcery speed, paid by sacrificing three
    *other* creatures (RULE 602.2b, 109.5).
    """
    def penalty() -> list[EffectSpec]:
        return [EffectSpec("damage_source_pays_or_loses_life", {"cost": "{1}", "life": _ELESH_NORN_LIFE_LOSS})]

    return [
        AbilitySpec(
            "triggered", penalty(),
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "group", "recipient_is_you": True},
                     "filter": {"by_opponent": True}},
            raw_text="whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller loses 2 life unless they pay {1}.",
        ),
        AbilitySpec(
            "triggered", penalty(),
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "group", "controller": "you", "recipient": True},
                     "filter": {"by_opponent": True}},
            raw_text="whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller loses 2 life unless they pay {1}.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("blink", {"subject": "source", "transformed": True})],
            cost={"text": "{2}{W}, Sacrifice three other creatures", "sorcery_speed_only": True},
            raw_text="{2}{w}, sacrifice three other creatures: exile ~, then return it to the battlefield transformed under its owner's control. activate only as a sorcery.",
        ),
    ]


def _the_argent_etchings() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Incubate 2 five times, then transform all Incubator tokens you control.
    II — Creatures you control get +1/+1 and gain double strike until end of turn.
    III — Destroy all other permanents except for artifacts, lands, and Phyrexians. Exile this Saga, then return it
    to the battlefield (front face up).

    — The back face of Elesh Norn (a Saga, reached by her transform ability). I is Glissa's Incubate pair: five
    Incubator tokens with two +1/+1 counters (`create_token` with ``extra_counters``), then `transform_named_tokens`
    animates every Incubator (RULE 701.51 / 712.8). II is a `pump` of the controller's creatures (RULE 702.4 double
    strike). III is a `destroy` over a structured group of every other permanent that is not an artifact, a land or
    a Phyrexian (``not_reference`` keeps the Saga out of its own sweep, RULE 109.5), then `blink` of the Saga itself:
    a card returning from exile is a new object with its front face up (RULE 400.7, 712.14a).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": _ARGENT_ETCHINGS_INCUBATOR_COUNT, "token_name": "Incubator",
                    "extra_counters": {"kind": "+1/+1", "count": _ARGENT_ETCHINGS_INCUBATE_AMOUNT},
                }),
                EffectSpec("transform_named_tokens", {
                    "token_name": "Incubator", "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                    "power": 0, "toughness": 0,
                }),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "selector": "creatures_you_control", "power": 1, "toughness": 1, "keywords": ["double_strike"],
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("destroy", {"group": {
                    "zone": "battlefield", "of": "any",
                    "filter": {"without_card_type": ["artifact", "land"], "without_subtype": "Phyrexian",
                               "not_reference": True},
                }}),
                EffectSpec("blink", {"subject": "source"}),
            ],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("Elesh Norn // The Argent Etchings", _elesh_norn)
register("Elesh Norn", _elesh_norn)
register("The Argent Etchings", _the_argent_etchings)
