"""PAR-30 — "Create a token …. It gains haste until end of turn." tail.

Three small pieces close this cluster:

- `segmenter._announces_creature_target` now returns True for a
  `create_token`/`copy_permanent`/`become_copy` spec, so the connector-split
  loop offers "it" to the next clause; `PumpEffect.previous_subject` falls
  back to `GameContext.created_objects` when `previous_targets` is empty.
- The connector-split loop seeds its pronoun chain from the caller's
  `previous_subject`/`previous_selector` (a two-sentence wrapper like
  `_EXILE_THEN_COPY_SENTENCE_RE` passes `previous_subject=True` for a span
  that opens with a referent) — the first sub-part must inherit it.
- `_DELAYED_SAC_EXILE_TAIL_RE` gained a `destroy` verb → `destroy_specific`
  (Old Hob-shaped "destroy it at the beginning of the next end step").
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


# --- parse ------------------------------------------------------------


def test_create_token_then_it_gains_haste_parses():
    specs = parse_effect_body(
        "create a 1/1 colorless thopter artifact creature token with flying. "
        "it gains haste until end of turn."
    )
    assert specs is not None
    assert [s.type for s in specs] == ["create_token", "pump"]
    assert specs[1].params.get("previous_subject") is True
    assert specs[1].params.get("keywords") == ["haste"]


def test_create_token_then_haste_then_destroy_at_end_step():
    specs = parse_effect_body(
        "create a 2/2 red mutant creature token. it gains haste until end of "
        "turn. destroy it at the beginning of the next end step."
    )
    assert specs is not None
    assert [s.type for s in specs] == ["create_token", "pump", "create_delayed_trigger"]
    dt = specs[2].params
    assert dt["capture"] == "previous_or_self"
    assert dt["effects"] == [{"type": "destroy_specific", "params": {}}]


def test_connector_seed_carries_previous_subject_into_first_subpart():
    # the shape `_EXILE_THEN_COPY_SENTENCE_RE` feeds its "after" span:
    # two sentences, the first of which opens with "that card" (a referent
    # the caller already established).
    specs = parse_effect_body(
        "create a token that's a copy of that card, except it's a 4/4 black "
        "zombie. it gains haste until end of turn.",
        previous_subject=True,
    )
    assert specs is not None
    assert [s.type for s in specs] == ["copy_permanent", "pump"]
    assert specs[1].params.get("previous_subject") is True


def test_real_cards_modeled():
    for name, tl, text in [
        ("Harried Dronesmith", "Artifact Creature — Construct",
         "At the beginning of combat on your turn, create a 1/1 colorless "
         "Thopter artifact creature token with flying. It gains haste until "
         "end of turn. Sacrifice it at the beginning of your next end step."),
        ("Mordor on the March", "Sorcery",
         "Exile a creature card from your graveyard. Create a token that's a "
         "copy of it. It gains haste until end of turn. Exile it at the "
         "beginning of the next end step."),
        ("God-Pharaoh's Gift", "Artifact",
         "At the beginning of combat on your turn, you may exile a creature "
         "card from your graveyard. If you do, create a token that's a copy "
         "of that card, except it's a 4/4 black Zombie. It gains haste until "
         "end of turn."),
    ]:
        c = Card(id=name[:4], name=name, type_line=tl,
                 is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                 power=1 if "Creature" in tl else None,
                 toughness=1 if "Creature" in tl else None,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ---------------------------------------------------------


def test_it_gains_haste_targets_the_created_token_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state

    src = GameObject(
        Card(id="HD", name="Harried Dronesmith",
             type_line="Artifact Creature — Construct", is_creature=True,
             power=1, toughness=1,
             oracle_text=("At the beginning of combat on your turn, create a "
                          "1/1 colorless Thopter artifact creature token with "
                          "flying. It gains haste until end of turn. Sacrifice "
                          "it at the beginning of your next end step.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    bind_from_catalogue(src)

    trig = next(t for t in src.triggered_abilities)
    _apply_effects_partitioned(
        list(trig.effects), eng.rules.context, [], None, source=src
    )
    eng.recompute_continuous_effects()

    thopters = [o for o in st.battlefield if o.card.name == "Thopter" and o.is_token]
    assert len(thopters) == 1
    # the "It gains haste until end of turn." clause resolved against the
    # just-created token (via GameContext.created_objects), not a target
    assert "haste" in thopters[0].granted_keywords
