"""PAR-30 — "doesn't untap during its controller's next untap step".

`SkipNextUntapEffect` (registered `skip_next_untap`) sets
`GameObject.skip_next_untap` — RULE 702.19b's own one-time flag, consumed
and cleared in `GameEngine._step_untap` (built for exert). A pure rider, so
the ~95-card "Tap X. It doesn't untap …" tempo family (Frost Lynx,
Chillbringer, Berg Strider, Dungeon Geists, Frost Titan, …) is the ordinary
two-clause `[tap, skip_next_untap{previous_subject}]` sequence.

Also widened `_tap`'s allowed target kinds to the controller-scoped creature
kinds so "tap target creature **an opponent controls**" parses at all.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause(
        "target creature doesn't untap during its controller's next untap step"
    ) == [EffectSpec("skip_next_untap", {"target_kind": "creature"})]
    assert match_clause(
        "it doesn't untap during its controller's next untap step", previous_subject=True
    ) == [EffectSpec("skip_next_untap", {"previous_subject": True})]
    assert match_clause(
        "~ doesn't untap during your next untap step", self_subject=True
    ) == [EffectSpec("skip_next_untap", {"target_kind": None})]


def test_tap_and_freeze_two_clause_sequence():
    specs = parse_effect_body(
        "tap target creature an opponent controls. it doesn't untap during "
        "its controller's next untap step."
    )
    assert specs is not None
    assert [s.type for s in specs] == ["tap", "skip_next_untap"]
    assert specs[0].params["target_kind"] == "creature_you_dont_control"
    assert specs[1].params["previous_subject"] is True


def test_real_cards_modeled():
    for name, tl, text in [
        ("Barl's Cage", "Artifact",
         "{3}: Target creature doesn't untap during its controller's next untap step."),
        ("Frost Lynx", "Creature — Cat",
         "When Frost Lynx enters, tap target creature an opponent controls. That "
         "creature doesn't untap during its controller's next untap step."),
        ("Frost Titan", "Creature — Giant",
         "Whenever Frost Titan becomes the target of a spell or ability an "
         "opponent controls, counter that spell or ability unless its controller "
         "pays {2}.\nWhenever Frost Titan enters or attacks, tap target "
         "permanent. It doesn't untap during its controller's next untap step."),
    ]:
        c = Card(id=name[:5], name=name, type_line=tl, is_creature="Creature" in tl,
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_skip_next_untap_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    bear = GameObject(
        Card(id="BR", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = "p1"
    bear.tapped = True
    st.add_to_battlefield(bear)

    src = GameObject(Card(id="FR", name="Frost", type_line="Instant", is_instant=True),
                     owner_id="p2", zone=Zone.STACK)
    src.controller_id = "p2"
    from mtg_analyzer.game.effect_binder import build_effects
    eff = build_effects([EffectSpec("skip_next_untap", {"target_kind": "creature"})], src)[0]
    eff.apply(eng.rules.context, [bear])
    assert bear.skip_next_untap is True

    st.turn_number = 1  # p1's turn
    eng._step_untap()
    assert bear.tapped is True          # the untap step skipped it
    assert bear.skip_next_untap is False  # one-time flag consumed
