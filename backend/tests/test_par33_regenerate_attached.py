"""PAR-33 — "regenerate enchanted creature" as an Aura's own activated
ability (RULE 701.16 / 303 — Regeneration / Gaea's Embrace / Blessing of
Leeches / Dark Privilege / Serpent Skin).

New `handlers._REGENERATE_ATTACHED_RE` → `EffectSpec("regenerate",
{"target_kind": "attached_permanent"})`, routing to `RegenerateEffect`'s
pre-existing `attached_permanent` mode (reads `source.attached_to` live).
No engine change.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import GameContext, RegenerateEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _rules():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    return RulesEngine(state), state, p1


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# --- parse -----------------------------------------------------------------


def test_regenerate_enchanted_creature_parses():
    assert parse_effect_body("regenerate enchanted creature") == [
        EffectSpec("regenerate", {"target_kind": "attached_permanent"})
    ]
    assert parse_effect_body("regenerate equipped creature") == [
        EffectSpec("regenerate", {"target_kind": "attached_permanent"})
    ]


def test_plain_regenerate_target_creature_unaffected():
    assert parse_effect_body("regenerate target creature") == [
        EffectSpec("regenerate", {"target_kind": "creature"})
    ]


def test_real_cards_modeled():
    for name, text in [
        ("Regeneration", "Enchant creature\n{G}: Regenerate enchanted creature."),
        ("Blessing of Leeches",
         "Enchant creature\nEnchanted creature has \"{0}: Regenerate this creature. "
         "Activate only once each turn.\"\n{0}: Regenerate enchanted creature."),
        ("Dark Privilege",
         "Enchant creature\nEnchanted creature gets +1/+1.\n"
         "Sacrifice a creature: Regenerate enchanted creature."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Enchantment — Aura", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_attached_regenerate_shields_the_host_from_destruction():
    eng, state, p1 = _rules()
    host = _bf(state, Card(id="h", name="Grizzly Bear", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2))
    aura = _bf(state, Card(id="a", name="Regeneration", type_line="Enchantment — Aura"))
    aura.attached_to = host.instance_id

    RegenerateEffect(target_kind="attached_permanent", source=aura).apply(
        GameContext(state, eng)
    )
    eng.destroy(host, can_be_regenerated=True)

    assert host in state.battlefield          # the shield absorbed the destroy
    assert host not in p1.graveyard


def test_attached_regenerate_is_a_noop_when_unattached():
    eng, state, p1 = _rules()
    aura = _bf(state, Card(id="a", name="Regeneration", type_line="Enchantment — Aura"))
    aura.attached_to = None
    # must not raise
    RegenerateEffect(target_kind="attached_permanent", source=aura).apply(
        GameContext(state, eng)
    )
