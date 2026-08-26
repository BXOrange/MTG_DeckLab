"""PAR-15: RULE 115.1a's "any number of target `<X>`" — a freely-chosen,
practically unbounded count (0..however many are legal), distinct from the
literal-N/"up to N" shape `TargetSpec.count`/`optional` already modeled.

Two pieces:

* `catalogue.handlers._MULTI_TARGET_QUANTIFIER`/`_multi_target_params`
  widened with a third alternative ("any number of ", alongside plain "N "
  and "up to N ") — capped at `_ANY_NUMBER_TARGET_CAP` (10), the same
  generous-fixed-cap convention the one pre-existing hand-authored example
  (`ability_catalogue._fire_covenant`) already used, rather than a live
  `legal_targets` count: the existing "offer up to N, one at a time, stop
  early or when targets run out" round-gathering machinery
  (`RulesEngine._continue_trigger_multi_target`) already handles both
  early-stopping cases, so the cap only needs to never be the *true*
  bottleneck. This one shared constant is embedded in ~9 existing handler
  regexes (destroy/exile/tap/untap/return-to-hand/"can't block"/damage-to-
  each-of/"choose"-for-search/graveyard-return), so all of them gain "any
  number of" for free.
* `catalogue.handlers._DIVIDED_DAMAGE_RE`/`_divided_damage` — RULE 601.2d's
  "`~` deals N/X damage divided as you choose among any number of
  target(s)/target creatures.", the ticket's own named biggest cluster.
  `DealDamageEffect(divided=True)` (RULE 601.2d) already existed as an
  engine primitive (Shatterskull Smashing/Fire Covenant, both hand-
  authored, cEDH-cube batch 19) — this is the first oracle-text recognizer
  to reach it.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py,
mtg_analyzer/game/effects.py (`DealDamageEffect`/`CantBlockEffect`).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(4)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


def _creature(name, power=2, toughness=2, owner="p1"):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness)
    return GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)


# ---------------------------------------------------------------------------
# PARSER: the widened multi-target quantifier, across a few real families
# ---------------------------------------------------------------------------


def test_any_number_of_is_recognized_by_destroy():
    (spec,) = match_clause("destroy any number of target creatures")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 10, "optional": True}


def test_any_number_of_is_recognized_by_cant_block():
    (spec,) = match_clause("any number of target creatures can't block this turn")
    assert spec.type == "cant_block_this_turn"
    assert spec.params == {"target_kind": "creature", "count": 10, "optional": True}


def test_any_number_of_is_recognized_by_exile():
    (spec,) = match_clause("exile any number of target artifacts")
    assert spec.type == "exile"
    assert spec.params == {"target_kind": "permanent", "count": 10, "optional": True}


def test_plain_up_to_n_still_works_after_the_widening():
    # match_clause takes already-normalized text (digits, not number words —
    # normalize.py folds those before this ever runs).
    (spec,) = match_clause("destroy up to 3 target creatures")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 3, "optional": True}


def test_plain_mandatory_n_still_works_after_the_widening():
    (spec,) = match_clause("destroy 2 target creatures")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 2}


def test_any_number_of_singular_is_not_claimed_by_the_multi_target_row():
    # "any number of target creature" (singular) isn't real card text; the
    # multi-target alternation is plural-only, same as the N>=2 rows.
    assert match_clause("destroy any number of target creature") is None


# ---------------------------------------------------------------------------
# PARSER: divided damage
# ---------------------------------------------------------------------------


def test_divided_damage_fixed_amount_among_targets():
    (spec,) = match_clause("deals 5 damage divided as you choose among any number of targets")
    assert spec.type == "damage"
    assert spec.params == {
        "amount": 5, "target_kind": "any", "count": 10, "optional": True, "divided": True,
    }


def test_divided_damage_fixed_amount_among_target_creatures():
    (spec,) = match_clause(
        "deals 5 damage divided as you choose among any number of target creatures"
    )
    assert spec.type == "damage"
    assert spec.params["target_kind"] == "creature"
    assert spec.params["divided"] is True


def test_divided_damage_x_amount():
    (spec,) = match_clause("deals x damage divided as you choose among any number of targets")
    assert spec.params["amount"] == "x"


def test_divided_damage_requires_the_any_number_of_phrasing():
    # "deals 5 damage divided among two target creatures" (a literal count)
    # isn't a shape any real card prints for the divided family — stays
    # unclaimed rather than guessed at.
    assert match_clause("deals 5 damage divided as you choose among two target creatures") is None


# ---------------------------------------------------------------------------
# END TO END: real cache cards named in the ticket
# ---------------------------------------------------------------------------


def test_blinding_flare_shaped_card_is_fully_modeled():
    card = Card(
        id="Test Blinding Flare", name="Test Blinding Flare", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{R}", converted_mana_cost=2,
        oracle_text="Strive — This spell costs {R} more to cast for each target beyond the first.\n"
                    "Any number of target creatures can't block this turn.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_bogardan_hellkite_shaped_card_is_fully_modeled():
    card = Card(
        id="Test Bogardan Hellkite", name="Test Bogardan Hellkite", type_line="Creature — Dragon",
        is_creature=True, power=4, toughness=4,
        oracle_text="Flying\nWhen this creature enters, it deals 5 damage divided as you "
                    "choose among any number of targets.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_fire_covenant_shaped_card_is_fully_modeled():
    card = Card(
        id="Test Fire Covenant", name="Test Fire Covenant", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{R}", converted_mana_cost=2,
        oracle_text="As an additional cost to cast this spell, pay X life.\n"
                    "Test Fire Covenant deals X damage divided as you choose among any "
                    "number of target creatures.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: divided damage actually splits the total across the chosen targets
# ---------------------------------------------------------------------------


def test_divided_damage_end_to_end_splits_across_three_creatures():
    card = Card(
        id="Test Rolling Thunder", name="Test Rolling Thunder", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{X}{R}", converted_mana_cost=1,
        oracle_text="Test Rolling Thunder deals X damage divided as you choose among "
                    "any number of targets.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bears = [_creature(f"Target{i}", power=1, toughness=6, owner="p2") for i in range(3)]
    for b in bears:
        eng.state.add_to_battlefield(b)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 6})

    eng.cast_spell(p1, obj, x=6, targets=[bears[0], bears[1], bears[2]])
    eng.resolve_until_stable()

    assert bears[0].damage_marked == 2
    assert bears[1].damage_marked == 2
    assert bears[2].damage_marked == 2


def test_divided_damage_can_be_split_unevenly_by_choosing_fewer_targets():
    card = Card(
        id="Test Rolling Thunder 2", name="Test Rolling Thunder 2", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{X}{R}", converted_mana_cost=1,
        oracle_text="Test Rolling Thunder 2 deals X damage divided as you choose among "
                    "any number of targets.",
    )
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bear = _creature("Solo Target", power=1, toughness=10, owner="p2")
    eng.state.add_to_battlefield(bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 5})

    # X=5, only one target chosen — the whole pool lands on it (RULE 601.2d
    # never requires spreading it out, just that the caster chooses how).
    eng.cast_spell(p1, obj, x=5, targets=[bear])
    eng.resolve_until_stable()

    assert bear.damage_marked == 5


# ---------------------------------------------------------------------------
# ENGINE: "any number of" for a non-divided, loop-over-the-list effect
# ---------------------------------------------------------------------------


def test_cant_block_any_number_end_to_end_affects_only_the_chosen_creatures():
    card = Card(
        id="Test Blinding Flare 2", name="Test Blinding Flare 2", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{R}", converted_mana_cost=2,
        oracle_text="Any number of target creatures can't block this turn.",
    )
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    chosen = [_creature(f"Chosen{i}", owner="p2") for i in range(2)]
    unchosen = _creature("Unchosen", owner="p2")
    for c in chosen + [unchosen]:
        eng.state.add_to_battlefield(c)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 1})

    eng.cast_spell(p1, obj, targets=chosen)
    eng.resolve_until_stable()

    assert chosen[0].temp_cant_block is True
    assert chosen[1].temp_cant_block is True
    assert getattr(unchosen, "temp_cant_block", False) is False
