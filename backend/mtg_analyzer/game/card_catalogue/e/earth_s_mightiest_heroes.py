from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _earths_mightiest_heroes() -> list[AbilitySpec]:
    """Teamwork 5 (As an additional cost to cast this spell, you may tap
    any number of creatures you control with total power 5 or more.)
    Reveal the top eight cards of your library. You may put a creature
    card from among them onto the battlefield. If this spell was cast
    using teamwork, put any number of creature cards from among them onto
    the battlefield instead. Put the rest into your graveyard.

    — MEC-85. The third RULE 702.194b "instead" shape: a *selection-count*
    override ("up to one" vs "any number"), neither a magnitude
    (`amount_if_teamwork`) nor a RULE 115 target-legality filter
    (`unless_flag` above) — "a creature card from among them" is a
    library-zone pick, not a target. `InspectTopChooseEffect.max_picks_
    if_teamwork` (new) generalizes MEC-72's own single-pick `inspect_top_
    n_choose` (Eclipsed Flamekin/Cream of the Crop/Cavalier of Thorns) to
    a cast-time-conditional cap, read off the real `GameObject.
    teamwork_paid` at resolve time (like `amount_if_teamwork` — there's no
    early-offer question here the way a real target has). 8 here already
    equals the reveal count, so it *is* "any number": a reveal-8 batch can
    never yield more than 8 creature hits, no separate "unlimited"
    sentinel needed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("inspect_top_choose", {
                    "count": 8, "action": "library_to_battlefield",
                    "filter": {"is_creature": True},
                    "rest_destination": "graveyard",
                    "optional": True,
                    "max_picks": 1, "max_picks_if_teamwork": 8,
                    "prompt": "Kreaturenkarte auf das Schlachtfeld legen",
                }),
            ],
        ),
    ]


register("Earth's Mightiest Heroes", _earths_mightiest_heroes)
