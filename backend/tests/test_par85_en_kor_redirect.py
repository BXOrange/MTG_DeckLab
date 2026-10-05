"""PAR-85 — en-Kor's recipient-scoped finite damage redirect."""

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _creature(name, owner, text=""):
    return GameObject(Card(id=name, name=name, type_line="Creature", is_creature=True,
                           power=2, toughness=2, oracle_text=text), owner_id=owner,
                      zone=Zone.BATTLEFIELD)


def test_nomads_en_kor_redirects_only_its_next_damage_to_chosen_creature():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    p1, p2 = eng.state.players
    nomads = _creature("Nomads en-Kor", p1.id, "{0}: The next 1 damage that would be dealt to this creature this turn is dealt to target creature you control instead.")
    ally, enemy = _creature("Ally", p1.id), _creature("Enemy", p2.id)
    for obj in (nomads, ally, enemy):
        eng.state.add_to_battlefield(obj)
    bind_from_catalogue(nomads)

    eng.activate_ability(p1, nomads, 0, targets=[ally])
    eng.resolve_until_stable()
    eng.rules.deal_damage(nomads, 3, source=enemy)

    assert nomads.damage_marked == 2
    assert ally.damage_marked == 1


def test_nomads_en_kor_is_modeled():
    card = Card(id="Nomads en-Kor", name="Nomads en-Kor", type_line="Creature", is_creature=True,
                oracle_text="{0}: The next 1 damage that would be dealt to this creature this turn is dealt to target creature you control instead.")
    assert parse_oracle(card).modeled
