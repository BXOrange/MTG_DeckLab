from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hoarding_broodlord() -> list[AbilitySpec]:
    """Hoarding Broodlord (Creature — Dragon, {5}{B}{B}{B}, 7/6)

    "Convoke
    Flying
    When this creature enters, search your library for a card, exile it
    face down, then shuffle. For as long as that card remains exiled, you
    may play it.
    Spells you cast from exile have convoke."

    The ETB is `SearchLibraryEffect`'s already-shipped
    ``destination="exile_face_down_standing_cast"`` (Praetor's Grasp,
    MEC-42) verbatim — face down, standing (never turn-swept) play
    permission granted to the searcher, ordinary mana cost still applies:
    an exact match for "for as long as that card remains exiled, you may
    play it."

    **Documented simplification**: Convoke (RULE 702.51) isn't bound to
    real creature-tapping cost-payment behaviour yet — the same posture
    `Selfless Safewright`'s/`City on Fire`'s own catalogue entries already
    take, which note it "come[s] from the RULE 702 keyword catalogue
    automatically." The trailing "spells you cast from exile have
    convoke" static grant is left unmodeled for the same reason (nothing
    real to grant until Convoke itself is bound) — both are out of scope
    for this single card's own coverage gate; a real RULE 702.51 build is
    general enough to be worth its own ticket (119 cached cards print
    Convoke).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "convoke"}),
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {}, "destination": "exile_face_down_standing_cast",
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
    ]


register("Hoarding Broodlord", _hoarding_broodlord)
