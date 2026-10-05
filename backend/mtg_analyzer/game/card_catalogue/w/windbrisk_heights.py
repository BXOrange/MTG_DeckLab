from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "…if you attacked with three or more creatures this turn" — the Hideaway payoff's threshold.
WINDBRISK_ATTACKER_THRESHOLD = 3


def _windbrisk_heights():
    """Hideaway 4 (When this land enters, look at the top four cards of your library, exile one face down, then put the rest on the bottom in a random order.)
    This land enters tapped.
    {T}: Add {W}.
    {W}, {T}: You may play the exiled card without paying its mana cost if you attacked with three or more creatures this turn.

    Hideaway, enters-tapped and the mana ability come from the keyword catalogue and the oracle
    text (as for Mosswort Bridge / Spinerock Knoll); only the payoff is authored here, gated on the
    existing `creatures_attacked_this_turn` count (distinct declared attackers, RULE 508.1a).
    """
    return [AbilitySpec("activated", [EffectSpec("play_hideaway_card", {
        "condition": {
            "kind": "control_count", "selector": "creatures_attacked_this_turn", "min": WINDBRISK_ATTACKER_THRESHOLD,
        },
    })], cost={"mana": "{W}", "taps_self": True})]


register("Windbrisk Heights", _windbrisk_heights)
