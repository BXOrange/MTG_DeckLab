"""PAR-215 axis F: "If damage is prevented this way, ~ deals that much damage to <target>." (RULE 615, RULE 603.12).

The shield remembers its source so the reflexive trigger is sized by what was actually prevented.
"""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import answer, card, cast, filler, game


@pytest.mark.parametrize("name", ["Divine Deflection", "Vengeful Archon", "Channel Harm"])
def test_prevention_with_reflexive_damage_is_modeled(name):
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    assert parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def test_divine_deflection_reflects_exactly_the_prevented_amount():
    eng = game(library=0)
    attacker = filler(eng, "Ogre", player="p2", power=5, toughness=5)
    victim = filler(eng, "Wall", player="p2", power=0, toughness=9)
    spell = card(eng, "Divine Deflection", zone=Zone.HAND)
    cast(eng, spell, x=3)
    me = eng.state.player_by_id("p1")
    life = me.life
    eng.rules.deal_damage(me, 5, source=attacker)
    eng.resolve_until_stable()
    assert me.life == life - 2  # 3 of the 5 were prevented
    # the reflexive trigger asks for its target; aim it at the opposing wall
    for _ in range(4):
        choice = eng.state.pending_choice
        if choice is None:
            break
        options = choice.get("options") or []
        pick = next((o for o in options if str(victim.instance_id) == str(o["id"])), options[0])
        eng.resolve_pending_choice(str(pick["id"]))
        eng.resolve_until_stable()
    assert victim.damage_marked == 3


def test_channel_harm_prevents_damage_to_my_permanents_from_opposing_sources():
    eng = game(library=0)
    attacker = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    mine = filler(eng, "Bear", power=2, toughness=2)
    spell = card(eng, "Channel Harm", zone=Zone.HAND)
    cast(eng, spell)
    eng.rules.deal_damage(mine, 4, source=attacker)
    eng.resolve_until_stable()
    assert mine.damage_marked == 0
    # damage from my own source is not covered ("sources you don't control")
    own = filler(eng, "Own", power=1, toughness=1)
    eng.rules.deal_damage(mine, 1, source=own)
    assert mine.damage_marked == 1


def test_chant_of_vitu_ghazi_prevents_creature_damage_and_gains_that_much_life():
    eng = game(library=0)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    bolt_source = filler(eng, "Rock", type_line="Artifact", player="p2", mv=0)
    wall = filler(eng, "Wall", power=0, toughness=9)
    spell = card(eng, "Chant of Vitu-Ghazi", zone=Zone.HAND)
    me = eng.state.player_by_id("p1")
    cast(eng, spell)
    life = me.life
    eng.rules.deal_damage(wall, 4, source=ogre)
    eng.resolve_until_stable()
    assert wall.damage_marked == 0 and me.life == life + 4
    eng.rules.deal_damage(wall, 2, source=bolt_source)  # a non-creature source is not prevented
    assert wall.damage_marked == 2
