"""PAR-87 — mandatory sacrifice-or-mana additional cast costs."""

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _additional_cost_dict
from tests.support.game import creature, make_engine


def test_parser_preserves_both_payment_branches():
    assert _additional_cost_dict("sacrifice a creature or pay {3}{B}") == {
        "sacrifice_or_mana": {"sacrifice": "creature", "mana": "{3}{b}"},
    }
    card = Card(id="ba", name="Bayou Groff", type_line="Creature — Frog",
                is_creature=True, oracle_text=(
                    "As an additional cost to cast this spell, sacrifice a creature or pay {3}."))
    result = parse_oracle(card)
    assert result.modeled
    assert result.specs[0].additional_cost_optional


def _setup(with_creature: bool):
    spell_card = Card(id="spell", name="Spell", type_line="Instant",
                      is_instant=True, mana_cost_string="{1}")
    eng = make_engine([spell_card], [creature("Bear")] if with_creature else [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    spell = player.hand[0]
    spell.additional_cast_cost = parse_activation_cost({
        "sacrifice_or_mana": {"sacrifice": "creature", "mana": "{3}"},
    })
    spell.additional_cast_cost_optional = True
    return eng, player, spell


def test_mana_branch_needs_no_creature_and_charges_the_extra_mana():
    eng, player, spell = _setup(False)
    player.mana_pool.add("C", 4)
    assert eng.can_cast(player, spell)
    eng.cast_spell(player, spell)
    assert player.mana_pool.total() == 0


def test_sacrifice_branch_avoids_the_extra_mana():
    eng, player, spell = _setup(True)
    victim = GameObject(creature("Bear"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(victim)
    player.mana_pool.add("C", 1)
    assert eng.can_cast(player, spell, pay_additional=True, sacrifice_choice=victim.instance_id)
    eng.cast_spell(player, spell, pay_additional=True, sacrifice_choice=victim.instance_id)
    assert victim in player.graveyard
    assert player.mana_pool.total() == 0
