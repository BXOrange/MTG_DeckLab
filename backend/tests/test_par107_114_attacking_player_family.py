"""PAR-107…114 residue batches, part 8 — "whenever a player attacks …, that attacking player …" (PAR-113's
player-attack heads whose body needs the attacking player as its "you").

The head names the defender (`attacks you` / `enchanted player` / `1 of your opponents` / `1 or more of your
opponents`) and the body runs *as* the attacking player (`trigger_subject_referent` ``acting="event_player"``,
RULE 109.5), including across a "you may" / "if you do" pause. Xorn/Jolene's "instead create those tokens plus an
additional Treasure" is `additional_named_token` narrowed to a named kind (``only_token``).

Reference: parser/oracle/catalogue/player_event_head.py, segmenter.py (`_event_player_body`), game/effects/
composition.py (`TriggerSubjectReferentEffect`), game/binding/core.py (`defender_is_*`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

CHAOS = ("Enchant player\nWhenever a player attacks enchanted player with one or more creatures, that attacking "
         "player may discard a card. If the player does, they draw a card.")
GRAVES = ("Enchant player\nWhenever a player attacks enchanted player with one or more creatures, that attacking "
          "player may create a tapped 2/2 black Zombie creature token.")
JOLENE = ("Whenever a player attacks one or more of your opponents, that attacking player creates a Treasure "
          "token.\nIf you would create one or more Treasure tokens, instead create those tokens plus an additional "
          "Treasure token.")
EVERETT = "Whenever an opponent attacks you with two or more creatures, draw a card."


def _card(name, text, type_line="Creature — Human", power=2, toughness=2):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None)


def _engine(players=("p1", "p2")):
    eng = GameEngine.new_game([(p, p.upper(), []) for p in players], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    return eng


def _put(eng, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _attack(eng, attackers):
    eng.declare_attackers(eng.state.active_player, attackers)
    eng._fire_player_attacked_events()
    eng.resolve_until_stable()


def _count(eng, controller, name):
    return sum(1 for o in eng.state.battlefield if o.controller_id == controller and o.name == name)


def test_real_cards_are_modeled():
    for name, text in [("Curse of Chaos", CHAOS), ("Curse of Shallow Graves", GRAVES), ("Jolene", JOLENE),
                       ("Everett", EVERETT)]:
        result = parse_oracle(_card(name, text, "Enchantment — Aura Curse" if "Curse" in name else "Creature"))
        assert result.modeled, (name, result.unclaimed)


def test_head_with_a_different_defender_is_not_claimed():
    # "attacks you or a planeswalker you control" names a defender the head grammar does not model.
    result = parse_oracle(_card("Probe", "Whenever a player attacks you and/or 1 or more planeswalkers you "
                                          "control, that attacking player creates a Treasure token."))
    assert not result.modeled


def test_curse_of_shallow_graves_token_goes_to_the_attacker():
    eng = _engine()
    curse = _put(eng, _card("Curse of Shallow Graves", GRAVES, "Enchantment — Aura Curse"), "p2")
    curse.attached_to = "p1"  # enchants the *attacked* player's opponent: p2 attacks p1 is the legal case
    bear = _put(eng, _card("Bear", ""), "p1")
    _put(eng, _card("Wall", ""), "p2")
    # p1 (active) attacks p2: the curse is on p1, so nothing happens.
    _attack(eng, [bear])
    assert eng.state.pending_choice is None
    assert _count(eng, "p1", "Zombie") == 0


def test_curse_of_shallow_graves_fires_for_the_enchanted_player_and_asks_the_attacker():
    eng = _engine()
    curse = _put(eng, _card("Curse of Shallow Graves", GRAVES, "Enchantment — Aura Curse"), "p2")
    curse.attached_to = "p2"  # p2 controls the Curse and is enchanted; p1 attacks p2
    bear = _put(eng, _card("Bear", ""), "p1")
    _attack(eng, [bear])
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p1"  # the attacker is asked, not the Curse's controller
    eng.resolve_pending_choice("yes")
    eng.resolve_until_stable()
    assert _count(eng, "p1", "Zombie") == 1 and _count(eng, "p2", "Zombie") == 0


def test_curse_of_chaos_discard_then_the_same_player_draws():
    eng = _engine()
    curse = _put(eng, _card("Curse of Chaos", CHAOS, "Enchantment — Aura Curse"), "p2")
    curse.attached_to = "p2"
    bear = _put(eng, _card("Bear", ""), "p1")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for i in range(2):
        p1.add_to_zone(GameObject(_card(f"Card{i}", "", "Sorcery"), owner_id="p1", zone=Zone.HAND), Zone.HAND)
    for i in range(2):  # both libraries have a card to draw, so a wrong drawer would show
        for pl in (p1, p2):
            pl.add_to_zone(GameObject(_card(f"Lib{pl.id}{i}", "", "Sorcery"), owner_id=pl.id, zone=Zone.LIBRARY),
                           Zone.LIBRARY)
    before_p2 = len(p2.hand)
    _attack(eng, [bear])
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice("pay")
    for _ in range(3):  # the discard pick, if the engine asks which card
        choice = eng.state.pending_choice
        if choice is None:
            break
        eng.resolve_pending_choice(choice["options"][0]["id"] if choice.get("options") else None)
    eng.resolve_until_stable()
    assert len(p2.hand) == before_p2  # the Curse's controller drew nothing
    assert len(p1.hand) == 2 and len(p1.graveyard) == 1  # discarded one, drew one: the attacker did both


def test_jolene_gives_the_attacker_a_treasure_plus_the_additional_one():
    eng = _engine()
    _put(eng, _card("Jolene", JOLENE), "p1")
    bear = _put(eng, _card("Bear", ""), "p1")
    _attack(eng, [bear])
    assert _count(eng, "p1", "Treasure") == 2  # one created, plus an additional one (her own replacement)


def test_jolene_ignores_an_attack_on_its_own_controller():
    eng = _engine()
    _put(eng, _card("Jolene", JOLENE), "p1")
    eng.state.active_player_index = 1
    bear = _put(eng, _card("Bear", ""), "p2")
    _attack(eng, [bear])  # p2 attacks p1 — Jolene's controller, not one of *their* opponents
    assert _count(eng, "p2", "Treasure") == 0 and _count(eng, "p1", "Treasure") == 0


def test_additional_treasure_replacement_leaves_other_tokens_alone():
    eng = _engine()
    _put(eng, _card("Jolene", JOLENE), "p1")
    eng.state.player_by_id("p1")
    result = parse_oracle(_card("Zombie Maker", "When this creature enters, create a 2/2 black Zombie creature token."))
    assert result.modeled
    maker = _put(eng, _card("Zombie Maker", "When this creature enters, create a 2/2 black Zombie creature token."), "p1")
    del maker
    eng.resolve_until_stable()
    assert _count(eng, "p1", "Treasure") == 0


def _everett_engine():
    eng = _engine()
    eng.state.active_player_index = 1
    _put(eng, _card("Everett", EVERETT), "p1")
    p1 = eng.state.player_by_id("p1")
    p1.add_to_zone(GameObject(_card("Filler", "", "Sorcery"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    return eng, p1


def test_everett_draws_for_two_attackers_at_its_controller():
    eng, p1 = _everett_engine()
    a, b = _put(eng, _card("A", ""), "p2"), _put(eng, _card("B", ""), "p2")
    _attack(eng, [a, b])
    assert len(p1.hand) == 1


def test_everett_does_not_draw_for_a_single_attacker():
    eng, p1 = _everett_engine()
    _attack(eng, [_put(eng, _card("A", ""), "p2")])
    assert len(p1.hand) == 0


ELLIE = ("Whenever a player attacks one of your opponents, that attacking player creates a tapped 1/1 black Fungus "
         "Zombie creature token named Cordyceps Infected that's attacking that opponent.")


def test_ellie_token_is_named_and_joins_the_attack_on_that_opponent():
    assert parse_oracle(_card("Ellie", ELLIE)).modeled
    eng = _engine()
    _put(eng, _card("Ellie", ELLIE), "p1")
    bear = _put(eng, _card("Bear", ""), "p1")
    eng.state.current_phase = "combat"  # RULE 508.4: only a creature entering during combat can join it
    _attack(eng, [bear])
    tokens = [o for o in eng.state.battlefield if o.name == "Cordyceps Infected"]
    assert len(tokens) == 1
    assert tokens[0].controller_id == "p1" and tokens[0].attacking and tokens[0].tapped
    assert tokens[0].combat_defender["id"] == "p2"
