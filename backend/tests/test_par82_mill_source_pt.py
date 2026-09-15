"""PAR-82: "target player mills X cards, where X is ~'s power/toughness."
(Phenax, God of Deception's own granted ability).

The ticket's own premise — that "creatures you control have '<ability>'"/
"enchanted creature has '<ability>'" is missing a subject-shape recognition
— turned out to be stale: both already correctly resolve to `affects=
"creatures_you_control"`/`"attached_permanent"` once the *inner* quoted
ability itself parses (confirmed directly against `static_effect_specs`
with a synthetic already-modeled inner clause). Every card still SOLO on
this search phrase is blocked by its own separate, unrelated inner-clause
gap instead — this file covers the one closed this pass (`MillEffect.
count_selector`'s already-shipped `"source_power"`/`"source_toughness"`
reading, previously reachable only by hand-authoring, now recognized from
oracle text). See `Done_Backend.md`'s PAR-82 entry for the rest of the
residue and why it stays open.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-82 entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_source_power_parses():
    assert parse_effect_body(
        "target player mills x cards, where x is ~'s power."
    ) == [EffectSpec("mill", {"target_kind": "player", "count_selector": "source_power"})]


def test_source_toughness_parses():
    assert parse_effect_body(
        "target player mills x cards, where x is ~'s toughness."
    ) == [EffectSpec("mill", {"target_kind": "player", "count_selector": "source_toughness"})]


def test_granted_ability_resolves_affects_creatures_you_control():
    specs = static_effect_specs(
        'creatures you control have "{t}: target player mills x cards, '
        'where x is ~\'s toughness."'
    )
    assert specs == [EffectSpec("grant_activated_ability", {
        "cost": {"text": "{t}"},
        "grant_effects": [{
            "type": "mill", "params": {"target_kind": "player", "count_selector": "source_toughness"},
        }],
        "once_per_turn": False,
        "sorcery_speed_only": False,
        "affects": "creatures_you_control",
    })]


def test_phenax_now_modeled():
    card = Card(
        id="Phenax, God of Deception", name="Phenax, God of Deception",
        type_line="Legendary Enchantment Creature — God", mana_cost_string="{2}{U}{B}",
        converted_mana_cost=4, is_creature=True, power=5, toughness=5,
        oracle_text=(
            "Indestructible\n"
            "As long as your devotion to blue and black is less than seven, "
            "Phenax, God of Deception isn't a creature.\n"
            "Creatures you control have \"{T}: Target player mills X cards, where "
            "X is this creature's toughness.\""
        ),
        keywords=["Indestructible"],
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_granted_mill_reads_the_granted_to_creatures_own_toughness():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1, p2 = state.players

    grantor = GameObject(
        Card(
            id="Phenax", name="Phenax", type_line="Enchantment", is_creature=False,
            oracle_text='Creatures you control have "{T}: Target player mills X '
                        'cards, where X is ~\'s toughness."',
        ),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(grantor)
    state.add_to_battlefield(grantor)

    miller = GameObject(
        Card(id="Miller", name="Miller", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=6),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    miller.summoning_sick = False
    bind_from_catalogue(miller)
    state.add_to_battlefield(miller)

    for _ in range(10):
        p2.library.append(GameObject(
            Card(id="Filler", name="Filler", type_line="Land", is_land=True),
            owner_id="p2", zone=Zone.LIBRARY,
        ))
    eng.recompute_continuous_effects()

    assert miller.granted_activated_abilities, "the mill ability wasn't granted to Miller"
    eng.activate_ability(p1, miller, ability_index=len(miller.activated_abilities), targets=[p2])
    eng.resolve_until_stable()

    assert len(p2.graveyard) == 6  # Miller's own toughness, not Phenax's
