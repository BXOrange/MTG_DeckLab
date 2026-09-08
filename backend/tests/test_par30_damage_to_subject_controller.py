"""PAR-30 — "~ [also] deals N damage to that creature's controller".

~22 SOLU. The controller of a creature an earlier clause targeted ("Destroy
target creature. ~ deals 2 damage to that creature's controller." — Consign
to the Pit) or one a group/trigger subject names ("Whenever a creature
blocks/dies, ~ deals N damage to that creature's controller." — Battle
Strain). New `DealDamageEffect.recipient_subject` string derives the
recipient player; no RULE 115 target of its own.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause(
        "~ deals 2 damage to that creature's controller", previous_subject=True
    ) == [EffectSpec("damage", {"amount": 2, "recipient_subject": "previous_subject_controller"})]
    assert match_clause(
        "~ deals 1 damage to that creature's controller", group_subject=True
    ) == [EffectSpec("damage", {"amount": 1, "recipient_subject": "trigger_subject_controller"})]
    assert match_clause(
        "~ also deals 3 damage to that creature's controller", previous_subject=True
    )[0].params["amount"] == 3
    # ungated — not claimed
    assert match_clause("~ deals 2 damage to that creature's controller") is None


def test_real_cards_modeled():
    for name, tl, text in [
        ("Consign to the Pit", "Sorcery",
         "Destroy target creature. Consign to the Pit deals 2 damage to that "
         "creature's controller."),
        ("Battle Strain", "Enchantment",
         "Whenever a creature blocks, Battle Strain deals 1 damage to that "
         "creature's controller."),
        ("Lash Out", "Instant",
         "Lash Out deals 3 damage to target creature. Clash with an opponent. "
         "If you win, Lash Out deals 3 damage to that creature's controller."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_sorcery=tl == "Sorcery",
                 is_instant=tl == "Instant", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_end_to_end_both_subjects():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p2 = st.player_by_id("p2")
    src = GameObject(Card(id="S", name="Consign", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    ox = GameObject(
        Card(id="OX", name="Ox", type_line="Creature — Ox", is_creature=True,
             power=2, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    ox.controller_id = "p2"
    st.add_to_battlefield(ox)
    effs = build_effects([
        EffectSpec("destroy", {"target_kind": "creature"}),
        EffectSpec("damage", {"amount": 2, "recipient_subject": "previous_subject_controller"}),
    ], src)
    _apply_effects_partitioned(effs, eng.rules.context, [ox], None, source=src)
    assert p2.life == 18

    eng.rules.context.trigger_event = {"instance_id": None, "controller_id": "p2"}
    build_effects([EffectSpec("damage", {
        "amount": 1, "recipient_subject": "trigger_subject_controller",
    })], src)[0].apply(eng.rules.context, [])
    eng.rules.context.trigger_event = None
    assert p2.life == 17
