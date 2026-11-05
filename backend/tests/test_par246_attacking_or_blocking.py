"""PAR-246: "target attacking or blocking <noun> with[out] <keyword>" -- one noun, two combat-status adjectives.

RULE 506.4 (attacking) / RULE 509.1 (blocking): either status satisfies the pair, and the rest of the noun phrase
(power bound, keyword, subtype, controller) narrows the same pool. The parsed spec must drive the real target pool.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.subgrammars import attacking_or_blocking_reading, resolve_target_kind

SPELLS = {"Puncturing Light", "Searing Light", "Rock Slide", "Sonar Strike", "Spirit Flare"}
CARDS = {
    "Puncturing Light": "Destroy target attacking or blocking creature with power 3 or less.",
    "Searing Light": "Destroy target attacking or blocking creature with power 2 or less.",
    "Skyshooter": "Reach\n{T}, Sacrifice this creature: Destroy target attacking or blocking creature with flying.",
    "Takeno's Cavalry": "Bushido 1\n{T}: This creature deals 1 damage to target attacking or blocking Spirit.",
    "Venomspout Brackus": "{1}{G}, {T}: This creature deals 5 damage to target attacking or blocking creature with flying.\n"
                          "Morph {3}{G}{G}",
    "Rock Slide": "Rock Slide deals X damage divided as you choose among any number of target attacking or blocking "
                  "creatures without flying.",
}
RESIDUE = {
    "Sonar Strike": "Sonar Strike deals 4 damage to target attacking, blocking, or tapped creature. "
                    "You gain 3 life if you control a Bat.",
    "Spirit Flare": "Tap target untapped creature you control. If you do, it deals damage equal to its power to "
                    "target attacking or blocking creature an opponent controls.\nFlashback—{1}{W}, Pay 3 life.",
    "Unerring Sling": "{3}, {T}, Tap an untapped creature you control: This artifact deals damage equal to the "
                      "tapped creature's power to target attacking or blocking creature with flying.",
}


def _card(name, text, type_line="Creature — Human", power=2, keywords=None):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature, is_instant="Instant" in type_line,
                power=power if creature else None, toughness=2 if creature else None, keywords=keywords or [])


def _printed(name, text):
    """The card as printed: the named spells are Instants, the rest Creatures."""
    return _card(name, text, "Instant" if name in SPELLS else "Creature — Human")


def _params(name):
    result = parse_oracle(_printed(name, CARDS[name]))
    assert result.coverage == MODELED
    for spec in result.specs:
        for eff in getattr(spec, "effects", []):
            if eff.type in ("destroy", "damage"):
                return eff.params
    raise AssertionError("no destroy/damage effect")


@pytest.mark.parametrize("name", sorted(CARDS))
def test_card_is_modeled_with_pair_flag(name):
    params = _params(name)
    assert params["creature_filter"]["attacking_or_blocking"] is True


@pytest.mark.parametrize("name", sorted(RESIDUE))
def test_other_shapes_stay_unmodeled(name):
    assert parse_oracle(_printed(name, RESIDUE[name])).coverage != MODELED


def test_noun_must_be_creature_or_subtype():
    assert attacking_or_blocking_reading("target attacking or blocking permanent with flying") is None
    assert resolve_target_kind("target attacking or blocking permanent with flying") is None
    # Bare phrase keeps its dedicated pool; narrower ones use the creature pool plus the flag.
    assert resolve_target_kind("target attacking or blocking creature") == "attacking_or_blocking_creature"
    assert resolve_target_kind("target attacking or blocking creature an opponent controls") == "creature_you_dont_control"


def _board():
    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])

    def put(name, text="", power=2, kind="Creature — Human", keywords=None, controller="p2",
            attacking=False, blocking=False):
        obj = GameObject(_card(name, text, kind, power, keywords), owner_id=controller, zone=Zone.BATTLEFIELD)
        obj.attacking = attacking
        if blocking:
            obj.blocking = "attacker-id"
        state.add_to_battlefield(obj)
        return obj

    return state, put


def _legal(state, name):
    params = _params(name)
    spec = targeting.TargetSpec(kind=params["target_kind"], creature_filter=params["creature_filter"])
    source = GameObject(_card("Source", "", "Artifact", None), owner_id="p1", zone=Zone.BATTLEFIELD)
    return {t["name"] for t in targeting.legal_targets(state, "p1", spec, source=source)}


def test_power_bound_pair_covers_attackers_and_blockers_only():
    state, put = _board()
    put("Small Attacker", power=3, attacking=True)
    put("Small Blocker", power=1, blocking=True)
    put("Big Attacker", power=4, attacking=True)
    put("Idle Small", power=1)
    assert _legal(state, "Puncturing Light") == {"Small Attacker", "Small Blocker"}
    assert _legal(state, "Searing Light") == {"Small Blocker"}


def test_keyword_with_requires_flying_in_either_status():
    state, put = _board()
    put("Flying Attacker", attacking=True, keywords=["Flying"])
    put("Flying Blocker", blocking=True, keywords=["Flying"])
    put("Ground Attacker", attacking=True)
    put("Idle Flier", keywords=["Flying"])
    assert _legal(state, "Skyshooter") == {"Flying Attacker", "Flying Blocker"}
    assert _legal(state, "Venomspout Brackus") == {"Flying Attacker", "Flying Blocker"}


def test_subtype_noun_and_keyword_without():
    state, put = _board()
    put("Spirit Attacker", attacking=True, kind="Creature — Spirit")
    put("Spirit Blocker", blocking=True, kind="Creature — Spirit")
    put("Human Attacker", attacking=True)
    put("Idle Spirit", kind="Creature — Spirit")
    assert _legal(state, "Takeno's Cavalry") == {"Spirit Attacker", "Spirit Blocker"}
    put("Flying Attacker", attacking=True, keywords=["Flying"])
    assert _legal(state, "Rock Slide") == {"Spirit Attacker", "Spirit Blocker", "Human Attacker"}
