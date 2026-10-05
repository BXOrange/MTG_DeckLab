"""Tests for MEC-24 — "target instant or sorcery card in your graveyard
gains flashback [`<cost>`] until end of turn[. The flashback cost is equal
to its mana cost.]" (Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of
Forgotten Lore/Katilda and Lier-shaped).

The untargeted "each instant and sorcery card in your graveyard gains
flashback…" sibling (Backdraft Hellkite/Will of the Jeskai) already had a
primitive (`grant_graveyard_cast_permission_this_turn`, appended onto the
*granting permanent's own* `GameObject.static_effects`). This one needs a
genuinely different shape: a marker on the *targeted graveyard card itself*
(`GameState.temp_flashback_grants`, ``instance_id -> cost``) rather than the
granting permanent, since the grant must survive independently of whatever
granted it and apply to exactly one chosen card, not every instant/sorcery
in the graveyard.

Two pieces:

  * `effects.GrantFlashbackToTargetEffect` (``"grant_flashback_to_target"``)
    stamps `GameState.temp_flashback_grants`; `game/engine/lands_mixin.py`'s
    `_graveyard_cast_keyword` and `game/engine/casting_mixin.py`'s
    `_flashback_cost` consult it alongside a printed Flashback keyword, so
    cost computation, the "cast_from_graveyard" UI tag, and the RULE 702.34a
    exile-after-cast (`GameObject.cast_via_flashback`) all fall out of the
    existing Flashback machinery unchanged.
  * `catalogue.handlers._grant_flashback_target` / `_GRANT_FLASHBACK_TARGET_RE`
    recognizes the oracle-text template, reusing the graveyard-recursion
    family's own `_GRAVEYARD_TYPE_WORD`/`_GRAVEYARD_SCOPE_WORD`/
    `_graveyard_target_kind` vocabulary (extended with a bare "sorcery" type
    word for Recoup, plus a matching `targeting._GRAVEYARD_TYPE_FILTERS`
    entry).

Reference: mtg_analyzer/game/effects/core.py (`GrantFlashbackToTargetEffect`),
mtg_analyzer/game/engine/{lands_mixin,casting_mixin}.py, mtg_analyzer/models/
game_state.py (`temp_flashback_grants`), mtg_analyzer/parser/oracle/
catalogue/handlers.py, mtg_analyzer/game/targeting.py, RULE 702.34.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, GrantFlashbackToTargetEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def gy_card(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def bolt():
    return Card(id="Lightning Bolt", name="Lightning Bolt", type_line="Instant",
                is_instant=True, mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="Lightning Bolt deals 3 damage to any target.")


def a_sorcery():
    return Card(id="Some Sorcery", name="Some Sorcery", type_line="Sorcery",
                is_sorcery=True, mana_cost_string="{2}{G}", converted_mana_cost=3,
                oracle_text="Draw a card.")


# ---------------------------------------------------------------------------
# PARSER: the new oracle-text handler
# ---------------------------------------------------------------------------


def test_the_common_equal_to_mana_cost_phrasing_is_recognized():
    (spec,) = match_clause(
        "target instant or sorcery card in your graveyard gains flashback until end of turn. "
        "the flashback cost is equal to its mana cost."
    )
    assert spec.type == "grant_flashback_to_target"
    assert spec.params == {"target_kind": "graveyard_instant_or_sorcery"}


def test_that_cards_mana_cost_phrasing_is_also_recognized():
    (spec,) = match_clause(
        "target instant or sorcery card in your graveyard gains flashback until end of turn. "
        "the flashback cost is equal to that card's mana cost."
    )
    assert spec.type == "grant_flashback_to_target"
    assert spec.params == {"target_kind": "graveyard_instant_or_sorcery"}


def test_a_bare_sorcery_only_target_is_recognized():
    (spec,) = match_clause(
        "target sorcery card in your graveyard gains flashback until end of turn. "
        "the flashback cost is equal to its mana cost."
    )
    assert spec.type == "grant_flashback_to_target"
    assert spec.params == {"target_kind": "graveyard_sorcery"}


def test_a_fixed_inline_cost_is_captured_with_no_trailing_sentence():
    (spec,) = match_clause(
        "target instant or sorcery card in your graveyard gains flashback {2}{r}{g} until end of turn."
    )
    assert spec.type == "grant_flashback_to_target"
    assert spec.params == {"target_kind": "graveyard_instant_or_sorcery", "cost": "{2}{r}{g}"}


def test_the_untargeted_each_sibling_still_claims_its_own_shape():
    (spec,) = match_clause(
        "each instant and sorcery card in your graveyard gains flashback until end of turn. "
        "the flashback cost is equal to its mana cost"
    )
    assert spec.type == "grant_graveyard_cast_permission_this_turn"


# ---------------------------------------------------------------------------
# ENGINE: GrantFlashbackToTargetEffect + the graveyard-cast machinery
# ---------------------------------------------------------------------------


def test_a_targeted_graveyard_card_becomes_castable_with_the_computed_cost():
    eng = make_engine()
    target = gy_card(eng, bolt())
    assert not eng._castable_from_graveyard(target)

    ctx = GameContext(eng.state, eng.rules)
    GrantFlashbackToTargetEffect().apply(ctx, targets=[target])

    assert eng._castable_from_graveyard(target)
    assert eng._graveyard_cast_keyword(target) == "flashback"
    assert eng._flashback_cost(target).raw == "{R}"


def test_a_fixed_cost_overrides_the_targets_own_mana_cost():
    eng = make_engine()
    target = gy_card(eng, bolt())  # {R}
    ctx = GameContext(eng.state, eng.rules)
    GrantFlashbackToTargetEffect(cost="{2}{R}{G}").apply(ctx, targets=[target])

    assert eng._flashback_cost(target).raw == "{2}{R}{G}"


def test_an_ungranted_graveyard_card_is_unaffected():
    eng = make_engine()
    granted = gy_card(eng, bolt())
    other = gy_card(eng, a_sorcery())
    ctx = GameContext(eng.state, eng.rules)
    GrantFlashbackToTargetEffect().apply(ctx, targets=[granted])

    assert eng._castable_from_graveyard(granted)
    assert not eng._castable_from_graveyard(other)


def test_casting_via_the_grant_exiles_the_card_on_resolution():
    eng = make_engine()
    target = gy_card(eng, bolt())
    ctx = GameContext(eng.state, eng.rules)
    GrantFlashbackToTargetEffect().apply(ctx, targets=[target])

    victim = GameObject(Card(id="Dummy", name="Dummy", type_line="Creature — Bear",
                              is_creature=True, power=3, toughness=3), owner_id="p2",
                         zone=Zone.BATTLEFIELD)
    bind_from_catalogue(victim)
    eng.state.add_to_battlefield(victim)

    player = eng.state.player_by_id("p1")
    player.mana_pool.add("R", 1)
    assert eng.can_cast(player, target, targets=[victim])
    eng.cast_spell(player, target, targets=[victim], target_groups=None)
    eng.resolve_until_stable()

    assert target.zone == Zone.EXILE  # RULE 702.34a, same as a printed Flashback cast


def test_the_grant_is_cleared_at_cleanup():
    eng = make_engine()
    target = gy_card(eng, bolt())
    ctx = GameContext(eng.state, eng.rules)
    GrantFlashbackToTargetEffect().apply(ctx, targets=[target])
    assert eng.state.temp_flashback_grants

    eng._step_cleanup()
    assert eng.state.temp_flashback_grants == {}
    assert not eng._castable_from_graveyard(target)


# ---------------------------------------------------------------------------
# Real cards end-to-end
# ---------------------------------------------------------------------------


def snapcaster_mage():
    return Card(
        id="Snapcaster Mage", name="Snapcaster Mage", type_line="Creature — Human Wizard",
        is_creature=True, power=2, toughness=1, mana_cost_string="{1}{U}",
        oracle_text=(
            "Flash\nWhen this creature enters, target instant or sorcery card in your "
            "graveyard gains flashback until end of turn. The flashback cost is equal to "
            "its mana cost. (You may cast that card from your graveyard for its flashback "
            "cost. Then exile it.)"
        ),
        keywords=["Flash"],
    )


def recoup():
    return Card(
        id="Recoup", name="Recoup", type_line="Sorcery", is_sorcery=True,
        mana_cost_string="{1}{R}",
        oracle_text=(
            "Target sorcery card in your graveyard gains flashback until end of turn. "
            "The flashback cost is equal to its mana cost. (Mana cost includes color.)\n"
            "Flashback {3}{R} (You may cast this card from your graveyard for its "
            "flashback cost. Then exile it.)"
        ),
        keywords=["Flashback"],
    )


def test_snapcaster_mage_is_fully_modeled():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    result = parse_oracle(snapcaster_mage())
    assert result.modeled, result.unclaimed


def test_recoup_is_fully_modeled():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    result = parse_oracle(recoup())
    assert result.modeled, result.unclaimed


def test_snapcaster_mage_end_to_end():
    eng = make_engine()
    target = gy_card(eng, bolt())
    snapper = GameObject(snapcaster_mage(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(snapper)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(snapper)
    p1.mana_pool.add("U", 2)

    eng.cast_spell(p1, snapper, targets=None, target_groups=None)
    eng.resolve_until_stable()
    # The ETB trigger's own target is chosen interactively (RULE 603.3c),
    # not announced with the spell — Snapcaster Mage's spell itself has no
    # target of its own.
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(str(target.instance_id))
    eng.resolve_until_stable()

    assert eng._castable_from_graveyard(target)
    assert eng._flashback_cost(target).raw == "{R}"
