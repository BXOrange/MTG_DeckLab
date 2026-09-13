"""PAR-59 — printed Haunt payoff triggers bind to the MEC-70 link."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def test_combined_haunt_trigger_emits_etb_and_linked_death_abilities():
    card = Card(id="Absolver Thrull", name="Absolver Thrull", type_line="Creature — Thrull",
                oracle_text="When Absolver Thrull enters or the creature it haunts dies, destroy target enchantment.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert [spec.ability_kind for spec in result.effect_specs] == ["triggered", "triggered"]
    assert result.effect_specs[1].effects[0].type == "haunt_linked_death"


def test_standalone_haunt_death_trigger_binds_the_linked_death_wrapper():
    card = Card(id="Cry of Contrition", name="Cry of Contrition", type_line="Sorcery",
                oracle_text="When the creature this card haunts dies, target player discards a card.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.effect_specs[0].effects[0].type == "haunt_linked_death"
