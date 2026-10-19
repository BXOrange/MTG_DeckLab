"""PAR-132 -- "if a [type] card is discarded this way" / "for each [type] card discarded this way" (RULE 608.2c).

The window is a `mark_event_log` position on the source, so it survives the discarding player's pending choice.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle

LOOT_IF = "Discard a card, then draw a card. If a land card is discarded this way, you gain 5 life."
EACH = "Discard 2 cards. You gain 3 life for each land card discarded this way."
NONLAND = "Discard 2 cards, then draw 2 cards. For each nonland card discarded this way, you gain 3 life."


def _card(name: str, text: str, type_line: str = "Sorcery") -> Card:
    return Card(id=name[:6], name=name, type_line=type_line, is_sorcery=True, oracle_text=text,
                mana_cost_string="{0}", converted_mana_cost=0)


def _hand_card(i: int, land: bool) -> GameObject:
    card = Card(id=f"h{i}", name=f"{'Forest' if land else 'Bear'} {i}",
                type_line="Basic Land — Forest" if land else "Creature — Bear",
                is_land=land, is_creature=not land, power=None if land else 2, toughness=None if land else 2)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    return obj


def _cast(text: str, hand: list[bool], picks: list[int], earlier_land_discard: bool = False):
    """Cast a sorcery with ``text`` holding ``hand`` (True = land); ``picks`` are the hand indexes to discard."""
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    player = eng.state.player_by_id("p1")
    cards = [_hand_card(i, land) for i, land in enumerate(hand)]
    player.hand.extend(cards)
    if earlier_land_discard:  # a land discarded before the spell is cast is not "this way"
        earlier = _hand_card(99, True)
        player.hand.append(earlier)
        eng.rules.discard_specific(earlier)
    card = _card("Tester", text)
    assert parse_oracle(card).coverage != UNMODELED
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    player.hand.append(spell)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    for index in picks:
        choice = eng.state.pending_choice
        assert choice, "the discard must ask the player"
        eng.rules.resolve_choice(str(next(o["id"] for o in choice["options"] if o["id"] == str(cards[index].instance_id))))
        eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    return eng, player


def test_if_land_discarded_gains_life():
    _, p = _cast(LOOT_IF, [True, False], picks=[0])
    assert p.life == 25


def test_if_nonland_discarded_does_not_trigger():
    _, p = _cast(LOOT_IF, [True, False], picks=[1])
    assert p.life == 20


def test_for_each_land_discarded_counts_only_lands():
    _, p = _cast(EACH, [True, False, True], picks=[0, 1])
    assert p.life == 23


def test_for_each_nonland_discarded_after_draw():
    _, p = _cast(NONLAND, [False, False, True], picks=[0, 1])
    assert p.life == 26


def test_earlier_discards_are_not_this_way():
    """The window opens at this spell's own discard: a land discarded before it never counts."""
    _, p = _cast(LOOT_IF, [False], picks=[], earlier_land_discard=True)
    assert p.life == 20


def test_discard_without_this_way_clause_still_unmodeled_when_mismatched():
    card = _card("Odd", "Discard a card. You gain 1 life for each land card sacrificed this way.")
    assert parse_oracle(card).coverage == UNMODELED


def _opponent_discard(text: str, hand: list[bool], pick: int):
    """Cast ``text`` (a targeted "target player discards") at p2, who holds ``hand``; p2 discards hand[pick]."""
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cards = []
    for i, land in enumerate(hand):
        obj = _hand_card(i, land)
        obj.owner_id = obj.controller_id = "p2"
        cards.append(obj)
    p2.hand.extend(cards)
    card = _card("Tester", text)
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.cast_spell(p1, spell, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice and choice["player_id"] == "p2"
    eng.rules.resolve_choice(str(cards[pick].instance_id))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    return eng, p1, spell


MIASMA = "Target player discards a card. If a land card is discarded this way, return Tester to its owner's hand."


def test_psychic_miasma_returns_itself_only_when_a_land_was_discarded():
    _, p1, spell = _opponent_discard(MIASMA, [True, False], pick=0)
    assert spell in p1.hand
    _, p1, spell = _opponent_discard(MIASMA, [True, False], pick=1)
    assert spell not in p1.hand


def _permanent_game(text: str, hand: list[bool], etb: bool):
    """A creature with ``text`` either cast from hand (``etb``) or already on the battlefield with ``hand`` held."""
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    p1 = eng.state.player_by_id("p1")
    cards = [_hand_card(i, land) for i, land in enumerate(hand)]
    p1.hand.extend(cards)
    card = Card(id="Tester", name="Tester", type_line="Creature — Human", is_creature=True, power=2, toughness=2,
                oracle_text=text, mana_cost_string="{0}", converted_mana_cost=0)
    assert parse_oracle(card).coverage != UNMODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    if etb:
        p1.hand.append(obj)
        eng.cast_spell(p1, obj)
    else:
        obj.zone = Zone.BATTLEFIELD
        eng.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        eng.activate_ability(p1, obj)
    eng.resolve_until_stable()
    return eng, p1, obj, cards


def test_seasoned_pyromancer_shape_makes_one_token_per_nonland_discard():
    eng, p1, obj, cards = _permanent_game(
        "When this creature enters, discard 2 cards, then draw 2 cards. For each nonland card discarded this way, "
        "create a 1/1 red Elemental creature token.", [True, False, False], etb=True)
    for card in (cards[0], cards[1]):  # discard a land and a nonland: exactly one token
        choice = eng.state.pending_choice
        assert choice
        eng.rules.resolve_choice(str(card.instance_id))
        eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert sum(1 for o in eng.state.battlefield if o.name == "Elemental") == 1


def test_scholar_shape_untaps_and_transforms_only_on_a_creature_discard():
    text = ("{T}: Draw a card, then discard a card. If a creature card is discarded this way, untap this creature, "
            "then transform it.")
    for pick, expect_untapped in ((1, True), (0, False)):
        eng, p1, obj, cards = _permanent_game(text, [True, False], etb=False)
        choice = eng.state.pending_choice
        assert choice, "a drawn card makes the hand non-trivial"
        eng.rules.resolve_choice(str(cards[pick].instance_id))
        eng.resolve_until_stable()
        assert eng.state.pending_choice is None
        assert (not obj.tapped) is expect_untapped


def _sacrifice_game(text: str, opp_permanents: list[str]):
    """Cast ``text``; p2 controls the given permanents ("artifact" or "creature"); answer p2's sacrifice pick if asked."""
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    p1 = eng.state.player_by_id("p1")
    victims = []
    for i, kind in enumerate(opp_permanents):
        card = Card(id=f"v{i}", name=f"Victim {i}", type_line="Artifact" if kind == "artifact" else "Creature — Bear",
                    is_creature=kind == "creature",
                    power=2 if kind == "creature" else None, toughness=2 if kind == "creature" else None)
        obj = GameObject(card, owner_id="p2", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p2"
        eng.state.add_to_battlefield(obj)
        victims.append(obj)
    card = _card("Tester", text)
    assert parse_oracle(card).coverage != UNMODELED
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.rules.resolve_choice(str(victims[0].instance_id))
        eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    return eng, p1


VISIONS = ("Each opponent sacrifices an artifact. For each artifact sacrificed this way, you create a Treasure token.")


def test_visions_shape_pays_a_treasure_per_sacrificed_artifact():
    eng, _ = _sacrifice_game(VISIONS, ["artifact", "artifact"])
    assert sum(1 for o in eng.state.battlefield if o.name == "Treasure") == 1
    assert sum(1 for o in eng.state.battlefield if o.name.startswith("Victim")) == 1


def test_visions_shape_pays_nothing_when_nothing_was_sacrificed():
    eng, _ = _sacrifice_game(VISIONS, ["creature"])
    assert sum(1 for o in eng.state.battlefield if o.name == "Treasure") == 0


def test_this_way_verb_must_match_the_first_clause():
    card = _card("Odd", "Each opponent sacrifices an artifact. Draw a card for each artifact discarded this way.")
    assert parse_oracle(card).coverage == UNMODELED
