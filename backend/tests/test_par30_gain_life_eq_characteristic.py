"""PAR-30 — "you gain life equal to <its / that creature's> <power / toughness>".

~36 SOLU. The creature isn't a RULE 115 target of the gain-life effect
itself; `GainLifeEffect.amount_from_subject` (a "<who>_<char>" string) names
which object and characteristic. Three gated parser rows: "its" on a bare-~
trigger -> self_*, "its" on a group trigger -> trigger_subject_*, "that
creature's" after another clause -> previous_subject_* (RULE 608.2h
last-known info, since the creature is usually gone by then).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause(
        "you gain life equal to its power", self_subject=True
    ) == [EffectSpec("gain_life", {"amount_from_subject": "self_power"})]
    assert match_clause(
        "you gain life equal to its toughness", group_subject=True
    ) == [EffectSpec("gain_life", {"amount_from_subject": "trigger_subject_toughness"})]
    assert match_clause(
        "you gain life equal to that creature's toughness", previous_subject=True
    ) == [EffectSpec("gain_life", {"amount_from_subject": "previous_subject_toughness"})]
    # ungated ("its" with no antecedent) — not claimed
    assert match_clause("you gain life equal to its power") is None


def test_real_cards_modeled():
    for name, tl, text in [
        ("Bottle Golems", "Artifact Creature — Golem",
         "When Bottle Golems dies, you gain life equal to its power."),
        ("Angelic Chorus", "Enchantment",
         "Whenever a creature you control enters, you gain life equal to its toughness."),
        ("Weed Strangle", "Sorcery",
         "Destroy target creature. Clash with an opponent. If you win, you "
         "gain life equal to that creature's toughness."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_sorcery=tl == "Sorcery",
                 is_creature="Creature" in tl,
                 power=3 if "Creature" in tl else None,
                 toughness=4 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_self_and_previous_subject_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    p1 = st.player_by_id("p1")
    golem = GameObject(
        Card(id="G", name="Golem", type_line="Artifact Creature — Golem",
             is_creature=True, power=3, toughness=4),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    golem.controller_id = "p1"
    st.add_to_battlefield(golem)

    build_effects([EffectSpec("gain_life", {"amount_from_subject": "self_power"})],
                  golem)[0].apply(eng.rules.context, [])
    assert p1.life == 23  # +3

    ox = GameObject(
        Card(id="OX", name="Ox", type_line="Creature — Ox", is_creature=True,
             power=2, toughness=5),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    ox.controller_id = "p2"
    st.add_to_battlefield(ox)
    effs = build_effects([
        EffectSpec("destroy", {"target_kind": "creature"}),
        EffectSpec("gain_life", {"amount_from_subject": "previous_subject_toughness"}),
    ], golem)
    _apply_effects_partitioned(effs, eng.rules.context, [ox], None, source=golem)
    assert p1.life == 28  # +5 = the destroyed Ox's last-known toughness
