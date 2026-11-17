"""PAR-311: normalization artifacts (RULE 201.4 self-reference, RULE 608.2c pronoun antecedent).

(1) A card name that ends in punctuation ("Kill! Maim! Burn!", "M.O.D.O.K.") or that is also a rules verb ("Regenerate",
"Destroy the Evidence") folds to ``~`` only where it denotes the card. (2) A character card's gendered self-pronoun
("he", "put a counter on him") reads as the neuter source reference, never where the pronoun can name a player.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize


def _engine():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _on_battlefield(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(name, oracle="", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Legendary Creature — Test", oracle_text=oracle, is_creature=True,
                power=power, toughness=toughness)


# -- name folding -------------------------------------------------------------------------------------------------------


def test_punctuation_final_names_fold_to_self():
    assert normalize("Kill! Maim! Burn! deals 3 damage to target player.", "Kill! Maim! Burn!") == "~ deals 3 damage to target player."
    assert normalize("Pay 3 life: M.O.D.O.K. connives.", "M.O.D.O.K.") == "pay 3 life: ~ connives."
    assert normalize("Fear, Fire, Foes! deals X damage.", "Fear, Fire, Foes!") == "~ deals x damage."


def test_a_verb_name_keeps_its_instruction_meaning():
    assert normalize("Regenerate target creature.", "Regenerate") == "regenerate target creature."
    assert normalize("Destroy target land.", "Destroy the Evidence") == "destroy target land."
    # a keyword alone on its line is not the card's own name, but a real self-reference later is
    assert normalize("Storm\nExile ~ from your graveyard.", "Storm of Memories").startswith("storm\n")
    assert normalize("Storm of Memories deals 1 damage to any target.", "Storm of Memories") == "~ deals 1 damage to any target."


def test_a_plural_name_enters_with_the_singular_verb():
    assert normalize("The Belligerent and Useless Island enter the battlefield tapped.",
                     "The Belligerent and Useless Island") == "~ enters the battlefield tapped."


def _real(name):
    import pytest
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _main_phase_engine(*cards):
    eng = GameEngine.new_game([("p1", "A", list(cards)), ("p2", "B", [])], starting_life=20,
                              starting_hand=len(cards))
    for player in eng.state.players:
        for obj in list(player.hand) + list(player.library):
            bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def test_regenerate_card_regenerates_its_target():
    eng = _main_phase_engine(_real("Regenerate"))
    state = eng.state
    p1 = state.players[0]
    bear = _on_battlefield(state, Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
                                       power=2, toughness=2), controller="p2")
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, p1.hand[0], targets=[bear])
    eng.resolve_until_stable()
    eng.rules.destroy(bear)
    assert bear in state.battlefield and bear.tapped


def test_kill_maim_burn_player_mode_resolves():
    card = _real("Kill! Maim! Burn!")
    assert parse_oracle(card).coverage == "MODELED"
    eng = _main_phase_engine(card)
    state = eng.state
    p1, p2 = state.players
    p1.mana_pool.add_many({"B": 1, "R": 1, "C": 3})
    eng.cast_spell(p1, p1.hand[0], mode=[2], targets=[p2])
    eng.resolve_until_stable()
    assert p2.life == 17


# -- gendered self-pronouns ---------------------------------------------------------------------------------------------


def test_gendered_self_pronoun_folds_only_on_a_line_naming_the_card():
    assert normalize("Whenever Zed attacks, put a +1/+1 counter on him. He gains indestructible until end of turn.",
                     "Zed") == "whenever ~ attacks, put a +1/+1 counter on it. it gains indestructible until end of turn."
    assert normalize("When Zed dies, return her to the battlefield under her owner's control.",
                     "Zed") == "when ~ dies, return it to the battlefield under its owner's control."
    # the pre-2011 player spelling and a line that never names the card stay untouched
    assert normalize("Target player draws a card unless he or she pays {2}.", "Zed") == (
        "target player draws a card unless he or she pays {2}.")
    assert normalize("Zed deals 2 damage to target player. That player discards a card of his or her choice.",
                     "Zed") == "~ deals 2 damage to target player. that player discards a card of his or her choice."
    assert normalize("Target creature's controller sacrifices it unless he pays {1}.", "Zed").count("he ") == 1


def test_pronoun_cards_are_modeled():
    hercules = Card(id="H", name="Hercules, Olympian Hero", type_line="Legendary Creature — God Hero", is_creature=True,
                    power=3, toughness=3, oracle_text=(
                        "Whenever Hercules attacks, put a +1/+1 counter on him. He gains indestructible until end of turn."))
    assert parse_oracle(hercules).coverage == "MODELED"
    zuko = Card(id="Z", name="Zuko, Seeking Honor", type_line="Legendary Creature — Human Noble", is_creature=True,
                power=2, toughness=2, oracle_text=(
                    "Whenever Zuko deals combat damage to a player, put a +1/+1 counter on him."))
    assert parse_oracle(zuko).coverage == "MODELED"


def test_pronoun_ability_affects_the_source_itself():
    eng, state = _engine()
    hercules = _on_battlefield(state, Card(
        id="H", name="Hercules, Olympian Hero", type_line="Legendary Creature — God Hero", is_creature=True,
        power=3, toughness=3, oracle_text=(
            "Whenever Hercules attacks, put a +1/+1 counter on him. He gains indestructible until end of turn.")))
    other = _on_battlefield(state, _creature("Bystander"))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": hercules, "defender": {"kind": "player", "id": "p2"}}])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert hercules.counters.get("+1/+1", 0) == 1
    assert other.counters.get("+1/+1", 0) == 0
    assert "indestructible" in hercules.granted_keywords
