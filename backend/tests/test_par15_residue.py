"""PAR-15 residue (2026-08-03): the four clusters left after the initial
"any number of target `<X>`" + divided-damage batch, per
`docs/implementation-state/BACKLOG.md`'s narrowed PAR-15 entry — closed in
full, no new *targeting* primitive needed for any of them (the ticket's own
call, confirmed): only new/widened effect-body recognizers.

* RULE 615's divided-prevention sibling of divided damage — "prevent the
  next N damage that would be dealt this turn to any number of targets,
  divided as you choose" (Embolden/Remedy/Angel of Salvation) —
  `PreventDamageEffect` gained a targeted/divided mode and a new
  `RulesEngine.prevent_damage_to_target` engine primitive (the any-target
  sibling of the existing player-only `prevent_damage_to_player`). Pollen
  Remedy's own trailing "if this spell was kicked, prevent the next N
  damage this way instead" is a narrow `amount_if_kicked` override param on
  this one effect class, not a generic kicked-override mechanism (RULE
  702.33b's *additive* "if kicked, `<effect>`" shape already exists via
  `ConditionalEffect` — this is the different, override shape a couple of
  cards use instead).
* Two new `ReturnFromGraveyardEffect` destinations for the "any number of
  target `<X>` cards from your graveyard" family: "on top of your library"
  (`destination="library_top"`, already a supported destination — no new
  engine primitive) and "into your library" (modeled as "put on the bottom,
  then shuffle" via the new `shuffle_after` param, since the position
  `library_bottom` gives it is immediately randomized away).
* `AddCountersEffect.divided` — "distribute N +1/+1 counters among any
  number of target creatures[ you control]" (Blessings of
  Nature/Jugan/Verdurous Gearhulk), the same evenly-split-pool shape
  `DealDamageEffect.divided` already established for damage.
* `PumpEffect.target_count` (a genuinely new N>=2 mode for a class that was
  single-target-only until now) — "any number of target creatures each get
  +N/+N [and gain `<keyword>`] until end of turn" (Aerial Formation/Ajani's
  Presence/Cruel Feeding/Desperate Stand/Rouse the Mob) — every chosen
  creature gets the *full* boost, not a divided pool. `TapEffect.
  previous_subject` (new, mirroring `ReturnToHandEffect`'s existing
  pronoun shape) closes Colossal Heroics' trailing "Untap those creatures."

Setessan Tactics (same cluster) stays UNMODELED on purpose: its trailing
"and gain '{T}: ~ fights another target creature.'" is a *granted activated
ability* on a multi-target group, a materially different and harder shape
than a flag keyword — a real, separate gap, not swept under this ticket.

Reference: mtg_analyzer/game/effects/core.py (`PreventDamageEffect`,
`ReturnFromGraveyardEffect`, `AddCountersEffect`, `PumpEffect`, `TapEffect`),
mtg_analyzer/game/rules/damage_death_mixin.py (`prevent_damage_to_target`),
mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
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
# PARSER: divided damage prevention
# ---------------------------------------------------------------------------


def test_prevent_divided_damage_is_recognized():
    (spec,) = match_clause(
        "prevent the next 5 damage that would be dealt this turn to any number of "
        "targets, divided as you choose"
    )
    assert spec.type == "prevent_damage_shield"
    assert spec.params == {
        "amount": 5, "target_kind": "any", "count": 10, "optional": True, "divided": True,
    }


def test_prevent_divided_damage_with_kicked_override():
    (spec,) = match_clause(
        "prevent the next 3 damage that would be dealt this turn to any number of "
        "targets, divided as you choose. if this spell was kicked, prevent the next "
        "6 damage this way instead"
    )
    assert spec.type == "prevent_damage_shield"
    assert spec.params["amount"] == 3
    assert spec.params["amount_if_kicked"] == 6


def test_plain_untargeted_prevent_shield_is_unaffected():
    # Riot Control/Thought Lash's own untargeted shape stays a distinct,
    # unclaimed-by-this-handler clause (hand-authored, not parser-driven).
    assert match_clause(
        "prevent the next 5 damage that would be dealt this turn to any number of "
        "targets, divided as you choose and gains flying"
    ) is None


# ---------------------------------------------------------------------------
# END TO END: real cards named in the ticket
# ---------------------------------------------------------------------------


def test_embolden_is_fully_modeled():
    card = Card(
        id="Embolden", name="Embolden", type_line="Instant", is_instant=True,
        oracle_text="Prevent the next 4 damage that would be dealt this turn to any "
                    "number of targets, divided as you choose.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_pollen_remedy_is_fully_modeled():
    card = Card(
        id="Pollen Remedy", name="Pollen Remedy", type_line="Instant", is_instant=True,
        oracle_text="Kicker—Sacrifice a land.\n"
                    "Prevent the next 3 damage that would be dealt this turn to any "
                    "number of targets, divided as you choose. If this spell was "
                    "kicked, prevent the next 6 damage this way instead.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: divided prevention actually shields whichever targets got a share
# ---------------------------------------------------------------------------


def test_prevent_divided_damage_end_to_end_shields_a_creature_and_a_player():
    card = Card(
        id="Test Embolden", name="Test Embolden", type_line="Instant",
        is_instant=True, mana_cost_string="{W}", converted_mana_cost=1,
        oracle_text="Prevent the next 4 damage that would be dealt this turn to any "
                    "number of targets, divided as you choose.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    p2 = eng.state.players[1]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bear = _creature("Shielded Bear", power=1, toughness=10, owner="p2")
    eng.state.add_to_battlefield(bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"W": 1})

    # 4 divided over two targets: 2 each (the even-split simplification).
    eng.cast_spell(p1, obj, targets=[bear, p2])
    eng.resolve_until_stable()

    eng.rules.deal_damage(bear, 3, source=None)
    eng.rules.deal_damage(p2, 3, source=None)

    # 2 of each hit were prevented — 1 damage got through to each.
    assert bear.damage_marked == 1
    assert p2.life == 19


def test_prevent_divided_damage_kicked_override_uses_the_larger_pool():
    card = Card(
        id="Test Pollen Remedy", name="Test Pollen Remedy", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text="Kicker {1}\n"
                    "Prevent the next 3 damage that would be dealt this turn to any "
                    "number of targets, divided as you choose. If this spell was "
                    "kicked, prevent the next 6 damage this way instead.",
        keywords=["Kicker"],
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bear = _creature("Kicked Bear", power=1, toughness=10, owner="p2")
    eng.state.add_to_battlefield(bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 2})

    eng.cast_spell(p1, obj, kicked=1, targets=[bear])
    eng.resolve_until_stable()

    eng.rules.deal_damage(bear, 6, source=None)
    assert bear.damage_marked == 0  # all 6 prevented — the kicked amount, not 3


# ---------------------------------------------------------------------------
# PARSER: graveyard-recursion "any number of" destinations
# ---------------------------------------------------------------------------


def test_put_any_number_on_top_of_library_is_recognized():
    (spec,) = match_clause(
        "put any number of target creature cards from your graveyard on top of your library"
    )
    assert spec.type == "return_from_graveyard"
    assert spec.params == {
        "target_kind": "graveyard_creature", "destination": "library_top",
        "count": 10, "optional": True,
    }


def test_shuffle_any_number_into_library_is_recognized():
    (spec,) = match_clause(
        "shuffle any number of target creature cards from your graveyard into your library"
    )
    assert spec.type == "return_from_graveyard"
    assert spec.params == {
        "target_kind": "graveyard_creature", "destination": "library_bottom",
        "shuffle_after": True, "count": 10, "optional": True,
    }


def test_shuffle_any_number_bare_card_type():
    (spec,) = match_clause(
        "shuffle any number of target cards from your graveyard into your library"
    )
    assert spec.params["target_kind"] == "graveyard_card"


# ---------------------------------------------------------------------------
# END TO END
# ---------------------------------------------------------------------------


def test_bone_harvest_is_fully_modeled():
    card = Card(
        id="Bone Harvest", name="Bone Harvest", type_line="Sorcery", is_sorcery=True,
        oracle_text="Put any number of target creature cards from your graveyard "
                    "on top of your library.\nDraw a card at the beginning of the "
                    "next turn's upkeep.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_pipers_melody_is_fully_modeled():
    card = Card(
        id="Piper's Melody", name="Piper's Melody", type_line="Instant", is_instant=True,
        oracle_text="Shuffle any number of target creature cards from your "
                    "graveyard into your library.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


# ---------------------------------------------------------------------------
# ENGINE: the two graveyard destinations actually move the cards
# ---------------------------------------------------------------------------


def test_return_from_graveyard_top_of_library_end_to_end():
    card = Card(
        id="Test Bone Harvest", name="Test Bone Harvest", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{2}{B}", converted_mana_cost=3,
        oracle_text="Put any number of target creature cards from your graveyard "
                    "on top of your library.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    dead_bear = _creature("Dead Bear", owner="p1")
    dead_bear.zone = Zone.GRAVEYARD
    p1.graveyard.append(dead_bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "C": 2})
    library_before = len(p1.library)

    eng.cast_spell(p1, obj, targets=[dead_bear])
    eng.resolve_until_stable()

    assert dead_bear not in p1.graveyard
    assert len(p1.library) == library_before + 1
    assert p1.library[-1] is dead_bear  # index 0 is the bottom; top is the list end


def test_return_from_graveyard_shuffle_into_library_end_to_end():
    card = Card(
        id="Test Piper's Melody", name="Test Piper's Melody", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text="Shuffle any number of target creature cards from your "
                    "graveyard into your library.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    dead_bear = _creature("Shuffled Bear", owner="p1")
    dead_bear.zone = Zone.GRAVEYARD
    p1.graveyard.append(dead_bear)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    library_before = len(p1.library)

    eng.cast_spell(p1, obj, targets=[dead_bear])
    eng.resolve_until_stable()

    assert dead_bear not in p1.graveyard
    assert dead_bear in p1.library
    assert len(p1.library) == library_before + 1


# ---------------------------------------------------------------------------
# PARSER: distribute counters
# ---------------------------------------------------------------------------


def test_distribute_counters_is_recognized():
    (spec,) = match_clause(
        "distribute 4 +1/+1 counters among any number of target creatures"
    )
    assert spec.type == "add_counters"
    assert spec.params == {
        "count": 4, "kind": "+1/+1", "target_kind": "creature",
        "target_count": 10, "optional": True, "divided": True,
    }


def test_distribute_counters_you_control_variant():
    (spec,) = match_clause(
        "distribute 4 +1/+1 counters among any number of target creatures you control"
    )
    assert spec.params["target_kind"] == "creature_you_control"


def test_blessings_of_nature_is_fully_modeled():
    card = Card(
        id="Blessings of Nature", name="Blessings of Nature", type_line="Sorcery",
        is_sorcery=True,
        oracle_text="Distribute four +1/+1 counters among any number of target creatures.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_verdurous_gearhulk_is_fully_modeled():
    card = Card(
        id="Verdurous Gearhulk", name="Verdurous Gearhulk", type_line="Creature — Golem",
        is_creature=True, power=4, toughness=4,
        oracle_text="Trample\nWhen this creature enters, distribute four +1/+1 "
                    "counters among any number of target creatures you control.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_distribute_counters_end_to_end_splits_the_pool():
    card = Card(
        id="Test Blessings of Nature", name="Test Blessings of Nature", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{2}{G}", converted_mana_cost=3,
        oracle_text="Distribute four +1/+1 counters among any number of target creatures.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    bears = [_creature(f"Counter Bear{i}", owner="p1") for i in range(3)]
    for b in bears:
        eng.state.add_to_battlefield(b)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 2})

    eng.cast_spell(p1, obj, targets=bears)
    eng.resolve_until_stable()

    # 4 counters over 3 targets: 2/1/1 (as-evenly-as-possible split).
    total = sum(b.counters.get("+1/+1", 0) for b in bears)
    assert total == 4
    assert bears[0].counters.get("+1/+1", 0) == 2
    assert bears[1].counters.get("+1/+1", 0) == 1
    assert bears[2].counters.get("+1/+1", 0) == 1


# ---------------------------------------------------------------------------
# PARSER: pump "any number of target creatures each get ..."
# ---------------------------------------------------------------------------


def test_pump_multi_target_with_keyword_is_recognized():
    (spec,) = match_clause(
        "any number of target creatures each get +1/+1 and gain flying until end of turn"
    )
    assert spec.type == "pump"
    assert spec.params == {
        "power": 1, "toughness": 1, "target_kind": "creature",
        "target_count": 10, "optional": True, "keywords": ["flying"],
    }


def test_pump_multi_target_without_keyword_is_recognized():
    (spec,) = match_clause(
        "any number of target creatures each get +2/+2 until end of turn"
    )
    assert spec.type == "pump"
    assert "keywords" not in spec.params


def test_untap_previous_group_requires_a_preceding_multi_target_clause():
    # Not offered in isolation — only reachable after a real multi-target
    # announcement (`EffectHandler.previous_subject_only`), same gate
    # `_return_previous_group` uses.
    from mtg_analyzer.parser.oracle.catalogue.handlers import HANDLERS

    handler = next(h for h in HANDLERS if h.name == "untap_previous_group")
    assert handler.previous_subject_only is True


def test_aerial_formation_is_fully_modeled():
    card = Card(
        id="Aerial Formation", name="Aerial Formation", type_line="Instant", is_instant=True,
        oracle_text="Strive — This spell costs {2}{U} more to cast for each target "
                    "beyond the first.\nAny number of target creatures each get "
                    "+1/+1 and gain flying until end of turn.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_colossal_heroics_is_fully_modeled():
    card = Card(
        id="Colossal Heroics", name="Colossal Heroics", type_line="Instant", is_instant=True,
        oracle_text="Strive — This spell costs {1}{G} more to cast for each target "
                    "beyond the first.\nAny number of target creatures each get "
                    "+2/+2 until end of turn. Untap those creatures.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_setessan_tactics_remains_unmodeled_granted_ability_gap():
    # A confirmed, separate residue: "gain '<activated ability>'" on a
    # multi-target group is a different shape than a flag keyword.
    card = Card(
        id="Setessan Tactics", name="Setessan Tactics", type_line="Instant", is_instant=True,
        oracle_text='Strive — This spell costs {G} more to cast for each target '
                    'beyond the first.\nUntil end of turn, any number of target '
                    'creatures each get +1/+1 and gain "{T}: This creature fights '
                    'another target creature."',
    )
    result = parse_oracle(card)
    assert not result.modeled


# ---------------------------------------------------------------------------
# ENGINE: pump-any-number gives the full boost to every chosen creature,
# and the trailing "untap those creatures" reads the same group back.
# ---------------------------------------------------------------------------


def test_pump_multi_target_end_to_end_full_boost_and_untap():
    card = Card(
        id="Test Colossal Heroics", name="Test Colossal Heroics", type_line="Instant",
        is_instant=True, mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text="Any number of target creatures each get +2/+2 until end of "
                    "turn. Untap those creatures.",
    )
    result = parse_oracle(card)
    assert result.modeled

    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    chosen = [_creature(f"Pumped{i}", power=2, toughness=2, owner="p1") for i in range(2)]
    unchosen = _creature("Not Pumped", power=2, toughness=2, owner="p1")
    for c in chosen + [unchosen]:
        eng.state.add_to_battlefield(c)
        c.tapped = True

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})

    eng.cast_spell(p1, obj, targets=chosen)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert chosen[0].power == 4 and chosen[0].toughness == 4
    assert chosen[1].power == 4 and chosen[1].toughness == 4
    assert unchosen.power == 2  # untouched
    assert chosen[0].tapped is False
    assert chosen[1].tapped is False
    assert unchosen.tapped is True  # untap only reaches the chosen group
