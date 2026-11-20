"""PAR-285 class E: a qualified "sacrifice a <permanent>" additional cast cost (RULE 601.2b, 701.17, 700.9, 608.2h).

"As an additional cost to cast this spell, sacrifice a legendary creature / a nonland permanent / a creature with
power 4 or greater / a creature or sacrifice a modified creature" reads the shared `sacrifice_clause` grammar into
`AbilitySpec.additional_cost`; `ActivationCost` and the engine's candidate pool read the resulting word. Tests run
parser -> binder -> `can_cast` / `cast_spell` with matching and non-matching permanents. Lethal Throwdown is the real
card this finishes (its rider reads the sacrificed creature's RULE 700.9 "modified" state); the other five E cards keep
a second unmodeled clause."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter.cost_line_patterns import additional_cost_dict
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine


def test_additional_cost_vocabulary():
    assert additional_cost_dict("sacrifice a nonland permanent") == {"sacrifice": "nonland_permanent"}
    assert additional_cost_dict("sacrifice a legendary creature") == {"sacrifice": "legendary_creature"}
    assert additional_cost_dict("sacrifice a creature with power 4 or greater") == {"sacrifice": "creature_power>=4"}
    assert additional_cost_dict("sacrifice a creature or sacrifice a modified creature") == {
        "either": [{"sacrifice": "creature"}, {"sacrifice": "modified_creature"}]}
    assert additional_cost_dict("sacrifice a legendary creature or pay {2}") == {
        "or_mana": {"cost": {"sacrifice": "legendary_creature"}, "mana": "{2}"}}
    # adversarial: unknown words, a different bound direction, "another", a counted group and a trailing tail fail closed
    for text in ("sacrifice a frobnicate creature", "sacrifice a creature with power 4 or less", "sacrifice another creature",
                 "sacrifice two legendary creatures", "sacrifice a legendary creature with flying and a land",
                 "sacrifice an artifact or creature with mana value 3"):
        assert additional_cost_dict(text) is None, text
    # MEC-169: the announced-X form is now read (Nahiri's Sacrifice), as its own cost key.
    assert additional_cost_dict("sacrifice an artifact or creature with mana value x") == {
        "sacrifice_mana_value_x": "artifact_or_creature"}
    assert parse_activation_cost({"sacrifice": "creature_power>=4"}).sacrifice == "creature_power>=4"


def _spell(extra: str) -> Card:
    return Card(
        id="t", name="Test Spell", type_line="Sorcery", is_sorcery=True, mana_cost_string="{1}", converted_mana_cost=1,
        oracle_text=f"As an additional cost to cast this spell, {extra}.\nDraw a card.",
    )


def _setup(extra: str, *permanents: tuple[Card, bool]):
    """The engine with the cost spell in hand and each ``(card, is_legendary)`` on p1's battlefield."""
    eng = make_engine([_spell(extra)], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    spell = player.hand[0]
    bind_from_catalogue(spell)
    objs = []
    for card, _ in permanents:
        obj = GameObject(card, owner_id=player.id, zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(obj)
        objs.append(obj)
    player.mana_pool.add("C", 1)
    return eng, player, spell, objs


def _legend(name, power=2):
    card = creature(name, power=power, toughness=power)
    card.type_line = "Legendary Creature — Human"
    card.is_legendary = True
    return card


def test_spec_carries_the_qualified_word():
    assert parse_oracle(_spell("sacrifice a legendary creature")).specs[0].additional_cost == {"sacrifice": "legendary_creature"}
    assert parse_oracle(_spell("sacrifice a legendary creature")).modeled is True


def test_legendary_creature_cost_needs_a_legendary_creature():
    eng, player, spell, (plain,) = _setup("sacrifice a legendary creature", (creature("Plain"), False))
    assert not eng.can_cast(player, spell)  # a non-legendary creature cannot pay it
    legend = GameObject(_legend("Legend"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(legend)
    assert eng.can_cast(player, spell, sacrifice_choice=legend.instance_id)
    assert not eng.can_cast(player, spell, sacrifice_choice=plain.instance_id)
    eng.cast_spell(player, spell, sacrifice_choice=legend.instance_id)
    assert legend.zone == Zone.GRAVEYARD and plain.zone == Zone.BATTLEFIELD


def test_nonland_permanent_cost_refuses_a_land():
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    eng, player, spell, (forest,) = _setup("sacrifice a nonland permanent", (land, False))
    assert not eng.can_cast(player, spell)
    bear = GameObject(creature("Bear"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    assert eng.can_cast(player, spell, sacrifice_choice=bear.instance_id)
    assert not eng.can_cast(player, spell, sacrifice_choice=forest.instance_id)


def test_power_bound_cost_reads_the_derived_power():
    eng, player, spell, (small,) = _setup("sacrifice a creature with power 4 or greater", (creature("Small", power=3), False))
    assert not eng.can_cast(player, spell)  # 3 < 4
    big = GameObject(creature("Big", power=4, toughness=4), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(big)
    assert eng.can_cast(player, spell, sacrifice_choice=big.instance_id)
    assert not eng.can_cast(player, spell, sacrifice_choice=small.instance_id)


# -- Lethal Throwdown (the real card) ----------------------------------------------------------------------------


def _throwdown():
    card = CardDatabase(DB_PATH).get_card("Lethal Throwdown")
    if card is None:
        pytest.skip("card cache not available")
    return card


def _throw(sacrifice_modified: bool):
    eng = make_engine([_throwdown()] * 4, [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    spell = player.hand[0]
    bind_from_catalogue(spell)
    fodder = GameObject(creature("Fodder"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(fodder)
    if sacrifice_modified:
        fodder.add_counters("+1/+1", 1)  # RULE 700.9: a counter makes it modified
    victim = GameObject(creature("Victim"), owner_id="p2" if player.id == "p1" else "p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(victim)
    player.mana_pool.add("C", 3)
    player.mana_pool.add("B", 1)
    library_before = len(player.library)
    eng.cast_spell(player, spell, targets=[victim], sacrifice_choice=fodder.instance_id)
    eng.resolve_until_stable()
    return player, victim, fodder, library_before


def test_lethal_throwdown_is_modeled():
    assert parse_oracle(_throwdown()).modeled is True


def test_lethal_throwdown_draws_only_when_the_sacrificed_creature_was_modified():
    player, victim, fodder, before = _throw(sacrifice_modified=True)
    assert fodder.zone == Zone.GRAVEYARD and victim.zone == Zone.GRAVEYARD
    assert len(player.library) == before - 1  # drew a card
    player, victim, fodder, before = _throw(sacrifice_modified=False)
    assert fodder.zone == Zone.GRAVEYARD and victim.zone == Zone.GRAVEYARD
    assert len(player.library) == before  # no counter, Equipment or Aura: not modified, no draw


def test_spec_validator_accepts_only_the_shared_vocabulary():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError

    AbilitySpec("spell_effect", [], additional_cost={"sacrifice": "legendary_creature"}).validate()
    AbilitySpec("spell_effect", [], additional_cost={"sacrifice": "creature_power>=4"}).validate()
    for word in ("frobnicate_creature", "creature_power>=x", "legendary_;drop", ""):
        with pytest.raises(SpecValidationError):
            AbilitySpec("spell_effect", [], additional_cost={"sacrifice": word}).validate()


def test_abjure_blue_permanent_cost_and_other_newly_modeled_cards():
    """Abjure ("sacrifice a blue permanent") is finished by the same slot: only a blue permanent can pay it."""
    abjure = CardDatabase(DB_PATH).get_card("Abjure")
    if abjure is None:
        pytest.skip("card cache not available")
    result = parse_oracle(abjure)
    assert result.modeled is True and result.specs[0].additional_cost == {"sacrifice": "blue_permanent"}
    eng = make_engine([abjure] * 4, [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    spell = player.hand[0]
    bind_from_catalogue(spell)
    red = GameObject(creature("Red Bear", cost="{R}"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(red)
    word = spell.additional_cast_cost.sacrifice
    assert eng._sacrifice_candidate(player, spell, word) is None  # no blue permanent to sacrifice
    blue = GameObject(creature("Blue Bear", cost="{U}"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(blue)
    assert eng._sacrifice_candidate(player, spell, word) is blue
    assert eng._sacrifice_candidate(player, spell, word, chosen_id=red.instance_id) is None
