"""PAR-84 — tap targets and keep each from its next untap step."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _creature(name: str, owner: str, text: str = "") -> GameObject:
    return GameObject(
        Card(
            id=name, name=name, type_line="Creature — Snake", is_creature=True,
            power=2, toughness=2, oracle_text=text,
        ),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )


def test_multi_target_tap_and_skip_parses():
    assert parse_effect_body(
        "tap up to 2 target creatures. those creatures don't untap during "
        "their controller's next untap step."
    ) == [
        EffectSpec("tap", {
            "target_kind": "creature", "count": 2, "optional": True, "untap": False,
        }),
        EffectSpec("skip_next_untap", {"previous_subject": True}),
    ]


def test_damage_recipient_tap_and_skip_parses_only_in_self_damage_trigger_context():
    clause = "tap that creature and it doesn't untap during its controller's next untap step"
    assert parse_effect_body(clause) is None
    assert parse_effect_body(clause, self_subject=True) == [
        EffectSpec("tap", {"target_operand": "damage_recipient"}),
        EffectSpec("skip_next_untap", {"target_operand": "damage_recipient"}),
    ]


def test_real_cards_are_modeled():
    for name, type_line, keywords, text in [
        ("Chilling Grasp", "Instant", ["Madness {3}{U}"], "Tap up to two target creatures. Those creatures don't untap during their controller's next untap step."),
        ("Kashi-Tribe Reaver", "Creature — Snake", [], "Whenever this creature deals combat damage to a creature, tap that creature and it doesn't untap during its controller's next untap step.\n{1}{G}: Regenerate this creature."),
    ]:
        card = Card(
            id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
            is_instant=type_line == "Instant",
            power=2 if "Creature" in type_line else None,
            toughness=2 if "Creature" in type_line else None,
            keywords=keywords, oracle_text=text,
        )
        result = parse_oracle(card)
        assert result.modeled, result.unclaimed


def test_chilling_grasp_taps_and_freezes_each_chosen_creature():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    first, second = _creature("First", p2.id), _creature("Second", p2.id)
    state.add_to_battlefield(first)
    state.add_to_battlefield(second)

    spell = GameObject(
        Card(
            id="Chilling Grasp", name="Chilling Grasp", type_line="Instant", is_instant=True,
            mana_cost_string="{2}{U}", converted_mana_cost=3,
            oracle_text="Tap up to two target creatures. Those creatures don't untap during their controller's next untap step.",
        ),
        owner_id=p1.id, zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"U": 3})
    eng.cast_spell(p1, spell, targets=[first, second])
    eng.resolve_until_stable()

    assert all(obj.tapped and obj.skip_next_untap for obj in (first, second))


def test_kashi_tribe_reaver_uses_the_damaged_creature_not_its_source():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    reaver = _creature(
        "Kashi-Tribe Reaver", p1.id,
        "Whenever this creature deals combat damage to a creature, tap that creature and it doesn't untap during its controller's next untap step.\n{1}{G}: Regenerate this creature.",
    )
    victim = _creature("Victim", p2.id)
    bind_from_catalogue(reaver)
    state.add_to_battlefield(reaver)
    state.add_to_battlefield(victim)

    eng.rules.deal_damage(victim, 1, source=reaver, combat=True)
    eng.resolve_until_stable()

    assert victim.tapped and victim.skip_next_untap
    assert not reaver.tapped and not reaver.skip_next_untap
