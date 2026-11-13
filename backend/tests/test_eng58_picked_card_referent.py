"""ENG-58: a card picked during resolution is the "it" of the next sentence.

RULE 608.2c / 400.7: "Target player exiles a card from their graveyard. If it's a creature card, you gain 2 life."
-- "it" is the card the player chose, as it now is in exile. The pick is interactive (a continuation), so the engine
hands the picked card to the parked remainder of the resolution (`GameContext.created_objects`) and the parser binds
"it's a <type> card" to that referent (`of: created`).
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield

SHOVEL = "Graveyard Shovel"

#: Life Graveyard Shovel's rider gains.
SHOVEL_LIFE = 2
#: Generic mana that pays the activation's {2}.
ACTIVATION_MANA = 2


def _effects(name):
    return [e for spec in parse_oracle(get_cached_card(name)).specs for e in spec.effects]


def test_graveyard_shovel_gates_the_life_gain_on_the_exiled_card():
    effects = _effects(SHOVEL)
    assert [e.type for e in effects] == ["exile_hand_card", "gain_life"]
    assert effects[0].condition is None
    assert effects[1].condition == {"kind": "is_card_type", "card_type": "creature", "of": "created"}
    assert parse_oracle(get_cached_card(SHOVEL)).modeled


def _grave_card(player, card_type_line, is_creature):
    card = Card(id="Pick", name="Pick", type_line=card_type_line, is_creature=is_creature,
                power=1 if is_creature else None, toughness=1 if is_creature else None)
    obj = GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD)
    player.graveyard.append(obj)
    return obj


def _activate_shovel(victim_id, card_type_line, is_creature, extra_card=False):
    eng, p1, p2 = game()
    shovel = on_battlefield(eng, "p1", SHOVEL)
    victim = eng.state.player_by_id(victim_id)
    pick = _grave_card(victim, card_type_line, is_creature)
    other = _grave_card(victim, "Land", False) if extra_card else None
    p1.mana_pool.add_many({"C": ACTIVATION_MANA})
    life = p1.life
    eng.activate_ability(p1, shovel, targets=[victim])
    eng.resolve_until_stable()
    return eng, p1, pick, other, life


def test_a_creature_card_exiled_gains_life_without_a_prompt():
    eng, p1, pick, _, life = _activate_shovel("p2", "Creature — Bear", True)
    assert pick.zone == Zone.EXILE
    assert p1.life - life == SHOVEL_LIFE


def test_a_noncreature_card_exiled_gains_no_life():
    eng, p1, pick, _, life = _activate_shovel("p2", "Sorcery", False)
    assert pick.zone == Zone.EXILE
    assert p1.life == life


def test_the_interactive_pick_reaches_the_parked_remainder():
    # Two graveyard cards: the player really chooses, so the rest of the resolution is parked and resumes after
    # the answer (RULE 608.2c). The land is picked: no life. Then the creature is picked in a second game.
    for choose_creature, gained in ((False, 0), (True, SHOVEL_LIFE)):
        eng, p1, pick, other, life = _activate_shovel("p2", "Creature — Bear", True, extra_card=True)
        pending = eng.state.pending_choice
        assert pending is not None
        wanted = pick if choose_creature else other
        eng.rules.resolve_choice(wanted.instance_id)
        eng.resolve_until_stable()
        assert wanted.zone == Zone.EXILE
        assert p1.life - life == gained


def test_target_player_is_the_chooser_and_the_source_is_not_the_referent():
    # The Shovel itself is a creature-less artifact: reading "it" as the source would never gain life.
    eng, p1, pick, _, life = _activate_shovel("p1", "Creature — Bear", True)
    assert p1.life - life == SHOVEL_LIFE
