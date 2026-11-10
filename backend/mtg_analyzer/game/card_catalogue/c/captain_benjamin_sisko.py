from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "Exile the top five cards of your library."
_EXILED_CARDS = 5


def _captain_benjamin_sisko() -> list[AbilitySpec]:
    """At the beginning of your end step, create a 1/1 red Officer creature token for each dilemma you've faced this turn.
    {2}{W}{U}{B}{R}{G}, {T}: Exile the top five cards of your library. You may cast any number of spells with mana value less than or equal to the number of Officers you control from among those cards without paying their mana costs.

    — MEC-141. The end-step trigger is the parser's `create_token` over the `dilemmas_faced_this_turn` count selector
    (RULE 700.17). The activated ability is `exile_top_of_library` followed by PAR-167's resolution-local casting window
    over that pool (RULE 608.2g, any number of spells, RULE 118.9 free); its mana-value bound is an amount (the Officers
    Sisko's controller has) read as the casts are offered.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Officer"], "keywords": [],
                "token_name": "Officer", "count_selector": "dilemmas_faced_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_top_of_library", "params": {"count": _EXILED_CARDS}},
                {"type": "cast_window_exiled_pool", "params": {
                    "resolution_local": True, "any_number": True, "free": True, "only_spells": True,
                    "card_filter": {"max_mana_value": {
                        "kind": "count_selector",
                        "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "officer"}},
                    }},
                }},
            ]})],
            cost={"text": "{2}{W}{U}{B}{R}{G}, {T}"},
        ),
    ]


register("Captain Benjamin Sisko", _captain_benjamin_sisko)
