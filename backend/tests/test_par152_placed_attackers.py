"""PAR-152 — "put/return … tapped and attacking" placements and the surroundings each card gives them
(RULE 508.4: the creature is put into combat attacking, never declared, so no attack trigger fires; the
controller picks the defender; RULE 603.7 delayed triggers; RULE 603.12 reflexive triggers).

Each card is parsed from its real Oracle text and executed on a real engine.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle

from tests.test_par119_attack_batch_head import _attack

HANS = (
    "Whenever Hans Eriksson attacks, reveal the top card of your library. If it's a creature card, put it onto the "
    "battlefield tapped and attacking defending player or a planeswalker they control. Otherwise, put that card "
    "into your hand. When you put a creature card onto the battlefield this way, it fights Hans Eriksson."
)


def _table(opponents=1):
    players = [Player(id="p1", name="Alice", life=20)] + [
        Player(id=f"p{i + 2}", name=f"Opp{i + 1}", life=20) for i in range(opponents)
    ]
    state = GameState(players=players)
    engine = GameEngine(state)
    state.current_step = "main1"
    state.current_phase = "combat"
    return engine, state


def _perm(state, name, types, oracle="", controller="p1", power=2, toughness=2, **kw):
    card = Card(
        id=name, name=name, type_line=types, oracle_text=oracle, power=power, toughness=toughness,
        is_creature="Creature" in types, **kw,
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _card(state, zone, name, types="Creature — Bear", power=2, toughness=2, owner="p1", **kw):
    card = Card(
        id=name, name=name, type_line=types, power=power, toughness=toughness,
        is_creature="Creature" in types, **kw,
    )
    obj = GameObject(card, owner_id=owner, zone=zone)
    pl = state.player_by_id(owner)
    {Zone.LIBRARY: pl.library, Zone.HAND: pl.hand, Zone.GRAVEYARD: pl.graveyard}[zone].append(obj)
    return obj


def _modeled(name, types, oracle):
    result = parse_oracle(Card(id=name, name=name, type_line=types, oracle_text=oracle, is_creature=True))
    assert result.modeled, result.unclaimed


def _answer(engine, state, option_id=None):
    pc = state.pending_choice
    assert pc is not None
    ids = [o["id"] for o in pc["options"]]
    engine.rules.resolve_choice(option_id if option_id in ids else ids[0])
    engine.resolve_until_stable()


# -- Hans Eriksson -------------------------------------------------------------------------------------------


def test_hans_is_modeled():
    _modeled("Hans Eriksson", "Legendary Creature — Human Warrior", HANS)


def test_hans_puts_a_revealed_creature_attacking_the_same_player_and_it_fights_him():
    engine, state = _table(opponents=2)
    hans = _perm(state, "Hans Eriksson", "Legendary Creature — Human Warrior", HANS, power=3, toughness=3)
    _card(state, Zone.LIBRARY, "Bear", power=2, toughness=4)
    _attack(engine, state, [{"attacker": hans, "defender": {"kind": "player", "id": "p3", "label": "Opp2"}}])
    bear = next(o for o in state.battlefield if o.name == "Bear")
    assert bear.tapped and bear.attacking
    assert bear.combat_defender["id"] == "p3"  # RULE 508.4a: joins Hans's own defender, not ambiguity
    assert hans.damage_marked == 2 and bear.damage_marked == 3  # RULE 701.14: the reflexive fight
    assert state.player_by_id("p1").library == []


def test_hans_puts_a_revealed_noncreature_into_hand():
    engine, state = _table()
    hans = _perm(state, "Hans Eriksson", "Legendary Creature — Human Warrior", HANS, power=3, toughness=3)
    _card(state, Zone.LIBRARY, "Island", types="Basic Land — Island", power=None, toughness=None)
    _attack(engine, state, [hans])
    assert [o.name for o in state.player_by_id("p1").hand] == ["Island"]
    assert not any(o.name == "Island" for o in state.battlefield)


def _advance_to(engine, state, step):
    for _ in range(40):
        if state.current_step == step:
            break
        engine.advance_step()
        while state.pending_choice is not None:
            _answer(engine, state)
    engine.resolve_until_stable()


PROBE_HAND_TAIL = (
    "Whenever Probe attacks, you may put a creature card from your hand onto the battlefield tapped and attacking. "
    "Return that creature to its owner's hand at the beginning of the next end step."
)


def test_probe_put_from_hand_then_return_tail():
    engine, state = _table()
    probe = _perm(state, "Probe", "Creature — Human", PROBE_HAND_TAIL, power=3, toughness=3)
    big = _card(state, Zone.HAND, "Big", power=5, toughness=5)
    _attack(engine, state, [probe])
    while state.pending_choice is not None:
        _answer(engine, state)
    assert big in state.battlefield and big.attacking
    _advance_to(engine, state, "end")
    assert big in state.player_by_id("p1").hand and probe in state.battlefield


ZARA = (
    "Flying\nWhenever Zara attacks, look at defending player's hand. You may put a creature card from it onto the "
    "battlefield under your control tapped and attacking that player or a planeswalker they control. Return that "
    "creature to its owner's hand at the beginning of the next end step."
)


def test_zara_is_modeled():
    _modeled("Zara, Renegade Recruiter", "Legendary Creature — Vampire Rogue", ZARA)


def _zara_attack(opponents=2, walker=False):
    engine, state = _table(opponents)
    zara = _perm(state, "Zara", "Legendary Creature — Vampire Rogue", ZARA, power=3, toughness=3)
    hand = state.player_by_id("p3").hand
    thief = _card(state, Zone.HAND, "Hand Creature", power=4, toughness=4, owner="p3")
    _card(state, Zone.HAND, "Hand Land", types="Basic Land — Forest", power=None, toughness=None, owner="p3")
    pw = None
    if walker:
        pw = _perm(state, "Gideon", "Legendary Planeswalker — Gideon", controller="p3", power=None, toughness=None)
    _attack(engine, state, [{"attacker": zara, "defender": {"kind": "player", "id": "p3", "label": "Opp2"}}])
    return engine, state, zara, thief, hand, pw


def test_zara_takes_a_creature_from_the_defending_hand_attacking_that_player_and_returns_it_at_end_step():
    engine, state, zara, thief, hand, _ = _zara_attack()
    assert state.pending_choice["kind"] == "look_hand"
    _answer(engine, state)  # acknowledge the look
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Hand Creature"]  # only creatures
    engine.rules.resolve_choice(pc["options"][0]["id"])
    engine.resolve_until_stable()
    assert thief.zone == Zone.BATTLEFIELD and thief.controller_id == "p1" and thief.owner_id == "p3"
    assert thief.tapped and thief.attacking and thief.combat_defender["id"] == "p3"
    _advance_to(engine, state, "end")
    assert thief in hand and thief not in state.battlefield  # back to its OWNER's hand
    assert zara in state.battlefield  # not Zara herself


def test_zara_declined_pick_moves_nothing():
    engine, state, zara, thief, hand, _ = _zara_attack()
    _answer(engine, state)
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert thief in hand and zara in state.battlefield
    _advance_to(engine, state, "end")
    assert zara in state.battlefield


def test_zara_offers_the_defending_players_planeswalker():
    engine, state, zara, thief, hand, pw = _zara_attack(walker=True)
    _answer(engine, state)
    pc = state.pending_choice
    engine.rules.resolve_choice(pc["options"][0]["id"])
    engine.resolve_until_stable()
    pc = state.pending_choice
    assert pc["kind"] == "reselect_attack" and pc["player_id"] == "p1"
    engine.rules.resolve_choice(f"planeswalker:{pw.instance_id}")
    engine.resolve_until_stable()
    assert thief.combat_defender["instance_id"] == pw.instance_id


THUNDERKIN = (
    "Haste\nWhenever this creature attacks, choose target Elemental creature card in your graveyard with toughness "
    "less than this creature's toughness. Return that card to the battlefield tapped and attacking. Sacrifice it at "
    "the beginning of the next end step."
)
CHORALE = (
    "Enchant creature you control\nWhenever enchanted creature attacks, put target creature card from defending "
    "player's graveyard onto the battlefield under your control tapped and attacking.\nVoid — At the beginning of "
    "your end step, sacrifice this Aura unless a nonland permanent left the battlefield this turn or a spell was "
    "warped this turn."
)


def test_thunderkin_awakener_is_modeled():
    _modeled("Thunderkin Awakener", "Creature — Elemental Bird", THUNDERKIN)


def test_thunderkin_awakener_returns_a_smaller_elemental_attacking_and_sacrifices_it_at_end_step():
    engine, state = _table()
    awakener = _perm(state, "Thunderkin Awakener", "Creature — Elemental Bird", THUNDERKIN, power=3, toughness=3)
    small = _card(state, Zone.GRAVEYARD, "Small Elemental", types="Creature — Elemental", power=1, toughness=2)
    _card(state, Zone.GRAVEYARD, "Big Elemental", types="Creature — Elemental", power=1, toughness=3)  # not less
    _card(state, Zone.GRAVEYARD, "Small Bear", types="Creature — Bear", power=1, toughness=1)  # wrong type
    _attack(engine, state, [awakener])
    while state.pending_choice is not None:
        _answer(engine, state)
    assert small.zone == Zone.BATTLEFIELD and small.tapped and small.attacking
    assert [o.name for o in state.battlefield if o.name.endswith("Elemental") or o.name == "Small Bear"] == [
        "Small Elemental"
    ]
    _advance_to(engine, state, "end")
    assert small.zone == Zone.GRAVEYARD and awakener in state.battlefield


def test_chorale_of_the_void_steals_from_the_defending_players_graveyard_only():
    engine, state = _table(opponents=2)
    host = _perm(state, "Host", "Creature — Human", power=2, toughness=2)
    chorale = _perm(
        state, "Chorale of the Void", "Enchantment — Aura", CHORALE, power=None, toughness=None, keywords=["Void", "Enchant"],
    )
    chorale.attached_to = host.instance_id
    mine = _card(state, Zone.GRAVEYARD, "Theirs Two", power=3, toughness=3, owner="p3")
    _card(state, Zone.GRAVEYARD, "Theirs One", power=3, toughness=3, owner="p2")
    _attack(engine, state, [{"attacker": host, "defender": {"kind": "player", "id": "p3", "label": "Opp2"}}])
    while state.pending_choice is not None:
        _answer(engine, state, option_id="player:p3")
    assert mine.zone == Zone.BATTLEFIELD and mine.controller_id == "p1" and mine.owner_id == "p3"
    assert mine.tapped and mine.attacking and mine.combat_defender["id"] == "p3"
    assert all(o.name != "Theirs One" for o in state.battlefield)


ELIZABETH = (
    "Battalion — Whenever Paladin Elizabeth Taggerdy and at least two other creatures attack, draw a card, then you "
    "may put a creature card with mana value X or less from your hand onto the battlefield tapped and attacking, "
    "where X is Paladin Elizabeth Taggerdy's power."
)


def test_elizabeth_taggerdy_is_modeled():
    _modeled("Paladin Elizabeth Taggerdy", "Legendary Creature — Human Knight", ELIZABETH)


def test_elizabeth_draws_then_puts_a_creature_up_to_her_power_in_mana_value_attacking():
    engine, state = _table(opponents=2)
    liz = _perm(state, "Paladin Elizabeth Taggerdy", "Legendary Creature — Human Knight", ELIZABETH, power=3, toughness=4)
    a = _perm(state, "Soldier A", "Creature — Soldier")
    b = _perm(state, "Soldier B", "Creature — Soldier")
    _card(state, Zone.LIBRARY, "Drawn Card", types="Instant", power=None, toughness=None)
    fits = _card(state, Zone.HAND, "Fits", power=3, toughness=3, converted_mana_cost=3)
    _card(state, Zone.HAND, "Too Big", power=5, toughness=5, converted_mana_cost=4)
    defender = {"kind": "player", "id": "p3", "label": "Opp2"}
    _attack(engine, state, [{"attacker": o, "defender": defender} for o in (liz, a, b)])
    while state.pending_choice is not None:
        pc = state.pending_choice
        if pc["kind"] != "reselect_attack":
            assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Fits"]  # mana value 3 or less
        _answer(engine, state, option_id="player:p3")
    assert "Drawn Card" in [o.name for o in state.player_by_id("p1").hand]
    assert fits.zone == Zone.BATTLEFIELD and fits.tapped and fits.attacking and fits.combat_defender["id"] == "p3"


def test_elizabeth_needs_two_other_attackers():
    engine, state = _table()
    liz = _perm(state, "Paladin Elizabeth Taggerdy", "Legendary Creature — Human Knight", ELIZABETH, power=3, toughness=4)
    a = _perm(state, "Soldier A", "Creature — Soldier")
    _card(state, Zone.LIBRARY, "Drawn Card", types="Instant", power=None, toughness=None)
    _attack(engine, state, [liz, a])
    assert state.pending_choice is None and not state.player_by_id("p1").hand


ULTRA_MAGNUS = (
    "More than meets the eye {2}{R}{G}{W}\nWard {2}\nWhenever Ultra Magnus attacks, you may put an artifact creature "
    "card from your hand onto the battlefield tapped and attacking. If you do, convert Ultra Magnus at end of combat."
)


def test_ultra_magnus_is_modeled():
    _modeled("Ultra Magnus, Tactician", "Legendary Artifact Creature — Robot", ULTRA_MAGNUS)


def _magnus(state):
    card = Card(
        id="UM", name="Ultra Magnus, Tactician", type_line="Legendary Artifact Creature — Robot",
        oracle_text=ULTRA_MAGNUS, power=3, toughness=4, is_creature=True,
        back_name="Ultra Magnus, Armored Carrier", back_type_line="Legendary Artifact — Vehicle",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_ultra_magnus_puts_an_artifact_creature_attacking_then_converts_at_end_of_combat():
    engine, state = _table()
    magnus = _magnus(state)
    robot = _card(state, Zone.HAND, "Robot", types="Artifact Creature — Robot", power=2, toughness=2)
    _card(state, Zone.HAND, "Plain Bear", power=2, toughness=2)  # not an artifact
    _card(state, Zone.HAND, "Trinket", types="Artifact", power=None, toughness=None)  # not a creature
    _attack(engine, state, [magnus])
    pc = state.pending_choice
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Robot"]
    _answer(engine, state)
    assert robot.zone == Zone.BATTLEFIELD and robot.tapped and robot.attacking
    assert magnus.name == "Ultra Magnus, Tactician"
    _advance_to(engine, state, "end_combat")
    assert magnus.name == "Ultra Magnus, Armored Carrier"  # RULE 701.28a: convert = turn over


def test_ultra_magnus_declining_the_pick_does_not_convert():
    engine, state = _table()
    magnus = _magnus(state)
    _card(state, Zone.HAND, "Robot", types="Artifact Creature — Robot", power=2, toughness=2)
    _attack(engine, state, [magnus])
    _answer(engine, state, option_id="decline")
    _advance_to(engine, state, "end_combat")
    assert magnus.name == "Ultra Magnus, Tactician"


DOORS = (
    "Whenever you attack, scry 2, then you may reveal the top card of your library. If a creature card is revealed "
    "this way, put it onto the battlefield tapped and attacking. Until your next turn, it gains trample if you "
    "control a Dwarf and hexproof if you control an Elf."
)


def test_doors_of_durin_is_modeled():
    _modeled("Doors of Durin", "Legendary Enchantment", DOORS)


def _doors(extra_types=()):
    engine, state = _table()
    _perm(state, "Doors of Durin", "Legendary Enchantment", DOORS, power=None, toughness=None)
    attacker = _perm(state, "Attacker", "Creature — Human")
    for name, types in extra_types:
        _perm(state, name, types)
    revealed = _card(state, Zone.LIBRARY, "Revealed Bear", power=2, toughness=2)
    _attack(engine, state, [attacker])
    for _ in range(6):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    return engine, state, revealed


def test_doors_of_durin_puts_the_revealed_creature_attacking_with_only_the_granted_keywords_whose_tribe_you_control():
    engine, state, revealed = _doors([("Dwarf Friend", "Creature — Dwarf")])
    assert revealed.zone == Zone.BATTLEFIELD and revealed.tapped and revealed.attacking
    engine.recompute_continuous_effects()
    assert "trample" in revealed.granted_keywords and "hexproof" not in revealed.granted_keywords


def test_doors_of_durin_grants_neither_keyword_without_a_dwarf_or_elf():
    engine, state, revealed = _doors()
    assert revealed.attacking
    engine.recompute_continuous_effects()
    assert not {"trample", "hexproof"} & set(revealed.granted_keywords)


def test_doors_of_durin_leaves_a_revealed_noncreature_on_top():
    engine, state = _table()
    _perm(state, "Doors of Durin", "Legendary Enchantment", DOORS, power=None, toughness=None)
    attacker = _perm(state, "Attacker", "Creature — Human")
    land = _card(state, Zone.LIBRARY, "Forest", types="Basic Land — Forest", power=None, toughness=None)
    _attack(engine, state, [attacker])
    for _ in range(6):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert land.zone == Zone.LIBRARY and not any(o.attacking and o is not attacker for o in state.battlefield)


FIREFLUX = (
    "Haste\nWhenever this creature attacks, you may exile another target attacking creature you control. If you do, "
    "reveal cards from the top of your library until you reveal a creature card. Put that card onto the battlefield "
    "tapped and attacking and the rest on the bottom of your library in a random order."
)


def test_fireflux_squad_is_modeled():
    _modeled("Fireflux Squad", "Creature — Dwarf Artificer", FIREFLUX)


def _fireflux(opponents=1):
    engine, state = _table(opponents)
    squad = _perm(state, "Fireflux Squad", "Creature — Dwarf Artificer", FIREFLUX, power=3, toughness=3)
    friend = _perm(state, "Friend", "Creature — Human")
    _card(state, Zone.LIBRARY, "Deep Bear", power=4, toughness=4)  # revealed last (library top is the list end)
    _card(state, Zone.LIBRARY, "Island", types="Basic Land — Island", power=None, toughness=None)
    defender = {"kind": "player", "id": f"p{opponents + 1}", "label": "Opp"}
    _attack(engine, state, [{"attacker": o, "defender": defender} for o in (squad, friend)])
    for _ in range(6):
        if state.pending_choice is None:
            break
        _answer(engine, state, option_id="player:p3")
    return engine, state, squad, friend


def test_fireflux_squad_exiles_an_attacker_and_puts_the_first_revealed_creature_attacking():
    engine, state, squad, friend = _fireflux(opponents=2)
    assert friend.zone == Zone.EXILE and squad.zone == Zone.BATTLEFIELD
    bear = next(o for o in state.battlefield if o.name == "Deep Bear")
    assert bear.tapped and bear.attacking and bear.combat_defender["id"] == "p3"
    lib = state.player_by_id("p1").library
    assert [o.name for o in lib] == ["Island"]  # the revealed land went to the bottom


def test_fireflux_squad_cannot_target_itself_or_a_nonattacker():
    engine, state = _table()
    squad = _perm(state, "Fireflux Squad", "Creature — Dwarf Artificer", FIREFLUX, power=3, toughness=3)
    idle = _perm(state, "Idle", "Creature — Human")
    _card(state, Zone.LIBRARY, "Deep Bear", power=4, toughness=4)
    _attack(engine, state, [squad])
    # nothing else attacks, so there is no legal target: nothing is exiled and no creature is revealed
    assert idle.zone == Zone.BATTLEFIELD and squad.zone == Zone.BATTLEFIELD
    assert not any(o.name == "Deep Bear" for o in state.battlefield)


STREFAN = (
    "Flying\nAt the beginning of your end step, create a Blood token for each player who lost life this turn.\n"
    "Whenever Strefan attacks, you may sacrifice two Blood tokens. If you do, you may put a Vampire card from your "
    "hand onto the battlefield tapped and attacking. It gains indestructible until end of turn."
)


def test_strefan_is_modeled():
    _modeled("Strefan, Maurer Progenitor", "Legendary Creature — Vampire Noble", STREFAN)


def _strefan(blood=2):
    engine, state = _table()
    strefan = _perm(state, "Strefan", "Legendary Creature — Vampire Noble", STREFAN, power=3, toughness=3)
    tokens = [_perm(state, "Blood", "Token Artifact — Blood", power=None, toughness=None) for _ in range(blood)]
    vamp = _card(state, Zone.HAND, "Hand Vampire", types="Creature — Vampire", power=2, toughness=2)
    _card(state, Zone.HAND, "Hand Bear", power=2, toughness=2)
    _attack(engine, state, [strefan])
    return engine, state, strefan, tokens, vamp


def test_strefan_sacrifices_two_blood_to_put_a_vampire_attacking_that_is_indestructible():
    engine, state, strefan, tokens, vamp = _strefan()
    for _ in range(6):
        if state.pending_choice is None:
            break
        pc = state.pending_choice
        if pc["kind"] == "search":
            assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == ["Hand Vampire"]
        _answer(engine, state)
    assert all(t.zone != Zone.BATTLEFIELD for t in tokens)
    assert vamp.zone == Zone.BATTLEFIELD and vamp.tapped and vamp.attacking
    engine.recompute_continuous_effects()
    assert "indestructible" in vamp.granted_keywords and "indestructible" not in strefan.granted_keywords


def test_strefan_cannot_pay_with_a_single_blood_token():
    engine, state, strefan, tokens, vamp = _strefan(blood=1)
    for _ in range(4):
        if state.pending_choice is None:
            break
        _answer(engine, state, option_id="decline")
    assert vamp.zone == Zone.HAND and tokens[0].zone == Zone.BATTLEFIELD


def test_strefan_sacrifices_only_blood_tokens_and_the_payer_picks_which_two():
    engine, state, strefan, tokens, vamp = _strefan(blood=3)
    seen = []
    for _ in range(8):
        if state.pending_choice is None:
            break
        seen.append(state.pending_choice["kind"])
        _answer(engine, state)
    assert strefan.zone == Zone.BATTLEFIELD  # the unknown word "blood" no longer means "any permanent"
    assert sum(1 for t in tokens if t in state.battlefield) == 1
    assert vamp.attacking


NEUTRINOS = (
    "Flying\nAlliance — Whenever another creature you control enters, The Neutrinos get +1/+0 until end of turn.\n"
    "Whenever The Neutrinos attack, exile up to one target creature you own, then return it to the battlefield under "
    "your control tapped and attacking."
)
JOCASTA = (
    "Flying\nWhenever your commander deals combat damage to a player, put a +1/+1 counter on Jocasta.\n"
    "Whenever you attack with your commander, if this card is in your graveyard, you may return it to the "
    "battlefield tapped and attacking."
)
PHOENIX = (
    "Flying\n{2}{R}: Return this card from your graveyard to the battlefield tapped and attacking. Activate only "
    "during the declare attackers step and only if you're attacking two or more opponents."
)
ZARETH = (
    "Flash\n{2}{U}{B}, Return an unblocked attacking Rogue you control to its owner's hand: Put this card from your "
    "hand onto the battlefield tapped and attacking.\nWhenever Zareth San deals combat damage to a player, you may "
    "put target permanent card from that player's graveyard onto the battlefield under your control."
)


@pytest.mark.parametrize("name,types,oracle", [
    ("The Neutrinos", "Legendary Creature — Alien", NEUTRINOS),
    ("Jocasta, Automaton Avenger", "Legendary Artifact Creature — Robot", JOCASTA),
    ("Nemesis Phoenix", "Creature — Phoenix", PHOENIX),
    ("Zareth San, the Trickster", "Legendary Creature — Human Rogue", ZARETH),
])
def test_remaining_placements_are_modeled(name, types, oracle):
    _modeled(name, types, oracle)


def test_the_neutrinos_blinks_a_creature_back_tapped_and_attacking_the_same_player():
    engine, state = _table(opponents=2)
    neutrinos = _perm(state, "The Neutrinos", "Legendary Creature — Alien", NEUTRINOS, power=3, toughness=3)
    friend = _perm(state, "Friend", "Creature — Human", power=2, toughness=2)
    _attack(engine, state, [{"attacker": neutrinos, "defender": {"kind": "player", "id": "p3", "label": "Opp2"}}])
    for _ in range(4):
        if state.pending_choice is None:
            break
        pc = state.pending_choice
        _answer(engine, state, option_id=next(o["id"] for o in pc["options"] if o.get("label") == "Friend")
                if pc["kind"] == "trigger_target" else "player:p3" if pc["kind"] == "reselect_attack" else None)
    assert friend.zone == Zone.BATTLEFIELD and friend.tapped and friend.attacking
    assert friend.combat_defender["id"] == "p3"


def test_jocasta_returns_from_the_graveyard_attacking_when_the_commander_attacks():
    engine, state = _table()
    cmdr = _perm(state, "Commander", "Legendary Creature — Human", power=2, toughness=2)
    cmdr.is_commander = True
    jocasta = _card(state, Zone.GRAVEYARD, "Jocasta, Automaton Avenger", types="Legendary Artifact Creature — Robot",
                    power=3, toughness=3)
    jocasta.card.oracle_text = JOCASTA
    bind_from_catalogue(jocasta)
    _attack(engine, state, [cmdr])
    for _ in range(4):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert jocasta.zone == Zone.BATTLEFIELD and jocasta.tapped and jocasta.attacking


def _phoenix(opponents):
    engine, state = _table(opponents)
    a = _perm(state, "Attacker A", "Creature — Human")
    b = _perm(state, "Attacker B", "Creature — Human")
    phoenix = _card(state, Zone.GRAVEYARD, "Nemesis Phoenix", types="Creature — Phoenix", power=3, toughness=3)
    phoenix.card.oracle_text = PHOENIX
    bind_from_catalogue(phoenix)
    state.player_by_id("p1").mana_pool.add("R", 3)
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, [
        {"attacker": a, "defender": {"kind": "player", "id": "p2", "label": "Opp1"}},
        {"attacker": b, "defender": {"kind": "player", "id": f"p{opponents + 1}", "label": "Opp"}},
    ])
    return engine, state, phoenix


def _phoenix_action(engine, phoenix):
    actions = [a for a in engine.legal_actions(engine.state.player_by_id("p1")) if a.get("source_id") == phoenix.instance_id
               or a.get("instance_id") == phoenix.instance_id]
    return actions


def test_nemesis_phoenix_needs_two_defending_opponents_and_the_declare_attackers_step():
    engine, state, phoenix = _phoenix(opponents=2)
    ability = phoenix.activated_abilities[0]
    cond = ability.cost.activation_condition
    from mtg_analyzer.game import static_conditions
    assert static_conditions.condition_holds(cond, state, source=phoenix, controller_id="p1")
    state.current_step = "main2"
    assert not static_conditions.condition_holds(cond, state, source=phoenix, controller_id="p1")
    engine2, state2, phoenix2 = _phoenix(opponents=1)  # both attackers hit the same (only) opponent
    assert not static_conditions.condition_holds(
        phoenix2.activated_abilities[0].cost.activation_condition, state2, source=phoenix2, controller_id="p1",
    )


def test_nemesis_phoenix_returns_attacking_when_activated_while_two_opponents_are_attacked():
    engine, state, phoenix = _phoenix(opponents=2)
    engine.activate_ability(state.player_by_id("p1"), phoenix, 0)
    for _ in range(4):
        engine.resolve_until_stable()
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert phoenix.zone == Zone.BATTLEFIELD and phoenix.tapped and phoenix.attacking
    assert phoenix.combat_defender is not None


def test_nemesis_phoenix_cannot_be_activated_against_a_single_opponent():
    engine, state, phoenix = _phoenix(opponents=1)
    try:
        engine.activate_ability(state.player_by_id("p1"), phoenix, 0)
    except ValueError:
        pass
    engine.resolve_until_stable()
    assert phoenix.zone == Zone.GRAVEYARD


def _zareth_board(opponents=1):
    engine, state = _table(opponents)
    rogue = _perm(state, "Sneaky Rogue", "Creature — Human Rogue", power=2, toughness=2)
    other = _perm(state, "Bear", "Creature — Bear")
    zareth = _card(state, Zone.HAND, "Zareth San, the Trickster", types="Legendary Creature — Human Rogue",
                   power=3, toughness=3)
    zareth.card.oracle_text = ZARETH
    bind_from_catalogue(zareth)
    state.player_by_id("p1").mana_pool.add("U", 1)
    state.player_by_id("p1").mana_pool.add("B", 1)
    state.player_by_id("p1").mana_pool.add("R", 2)
    state.current_step = "declare_attackers"
    defender = {"kind": "player", "id": "p2", "label": "Opp1"}
    engine.declare_attackers(state.active_player, [
        {"attacker": rogue, "defender": defender}, {"attacker": other, "defender": defender},
    ])
    return engine, state, rogue, other, zareth


def test_zareth_san_comes_in_attacking_by_returning_an_unblocked_attacking_rogue():
    engine, state, rogue, other, zareth = _zareth_board()
    engine.activate_ability(state.player_by_id("p1"), zareth, 0, return_choices=[rogue.instance_id])
    for _ in range(4):
        engine.resolve_until_stable()
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert rogue in state.player_by_id("p1").hand  # the cost
    assert zareth.zone == Zone.BATTLEFIELD and zareth.tapped and zareth.attacking
    assert other.zone == Zone.BATTLEFIELD


def test_zareth_san_cannot_pay_with_a_blocked_or_nonrogue_attacker():
    engine, state, rogue, other, zareth = _zareth_board()
    rogue.blocked_by = [other.instance_id]
    try:
        engine.activate_ability(state.player_by_id("p1"), zareth, 0, return_choices=[other.instance_id])
    except ValueError:
        pass
    engine.resolve_until_stable()
    assert zareth.zone == Zone.HAND and rogue.zone == Zone.BATTLEFIELD


def test_zareth_san_reanimates_from_the_damaged_players_graveyard():
    engine, state = _table(opponents=2)
    zareth = _perm(state, "Zareth San, the Trickster", "Legendary Creature — Human Rogue", ZARETH, power=3, toughness=3)
    stolen = _card(state, Zone.GRAVEYARD, "Their Relic", types="Artifact", power=None, toughness=None, owner="p3")
    _card(state, Zone.GRAVEYARD, "Other Relic", types="Artifact", power=None, toughness=None, owner="p2")
    _attack(engine, state, [{"attacker": zareth, "defender": {"kind": "player", "id": "p3", "label": "Opp2"}}])
    engine._deal_combat_damage_step(first_strike_step=False)
    engine.resolve_until_stable()
    for _ in range(4):
        if state.pending_choice is None:
            break
        pc = state.pending_choice
        assert [o["label"] for o in pc["options"] if o["id"] != "decline"] in (["Their Relic"], [])
        _answer(engine, state)
    assert stolen.zone == Zone.BATTLEFIELD and stolen.controller_id == "p1"


OLIVIA = (
    "Flying, haste\nWhenever Olivia attacks, return target creature card from your graveyard to the battlefield "
    "tapped and attacking. It gains \"When you don't control a legendary Vampire, exile this creature.\""
)


def test_olivia_crimson_bride_is_modeled():
    _modeled("Olivia, Crimson Bride", "Legendary Creature — Vampire Noble", OLIVIA)


def test_olivia_reanimated_creature_is_exiled_once_no_legendary_vampire_is_left():
    engine, state = _table()
    olivia = _perm(state, "Olivia, Crimson Bride", "Legendary Creature — Vampire Noble", OLIVIA, power=4, toughness=4,
                   is_legendary=True)
    risen = _card(state, Zone.GRAVEYARD, "Risen Bear", power=2, toughness=2)
    _attack(engine, state, [olivia])
    for _ in range(4):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert risen.zone == Zone.BATTLEFIELD and risen.tapped and risen.attacking
    engine.rules.put_into_graveyard(olivia)  # the last legendary Vampire leaves
    engine.resolve_until_stable()
    for _ in range(4):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    assert risen.zone == Zone.EXILE


def test_olivia_reanimated_creature_stays_while_a_legendary_vampire_remains():
    engine, state = _table()
    olivia = _perm(state, "Olivia, Crimson Bride", "Legendary Creature — Vampire Noble", OLIVIA, power=4, toughness=4,
                   is_legendary=True)
    _perm(state, "Other Vampire Lord", "Legendary Creature — Vampire", power=2, toughness=2, is_legendary=True)
    risen = _card(state, Zone.GRAVEYARD, "Risen Bear", power=2, toughness=2)
    _attack(engine, state, [olivia])
    for _ in range(4):
        if state.pending_choice is None:
            break
        _answer(engine, state)
    engine.rules.put_into_graveyard(olivia)
    engine.resolve_until_stable()
    assert risen.zone == Zone.BATTLEFIELD


TOWERSHELL = (
    "Islandwalk\nWhenever this creature attacks, exile it. Return it to the battlefield under your control tapped "
    "and attacking at the beginning of the declare attackers step on your next turn."
)
NOCTIS = (
    "Whenever a creature you control enters during combat, you may attach target Equipment you control to target "
    "creature you control.\n{3}: Exile Noctis. Return it to the battlefield under its owner's control tapped and "
    "attacking at the beginning of that player's next declare attackers step. It can't be blocked that combat."
)


def _to_next_declare_attackers(engine, state, player_id="p1"):
    start = state.internal_turn.number
    for _ in range(400):
        engine.advance_step()
        while state.pending_choice is not None:
            _answer(engine, state)
        if state.current_step == "declare_attackers" and state.active_player.id == player_id \
                and state.internal_turn.number > start:
            break
    engine.resolve_until_stable()
    while state.pending_choice is not None:
        _answer(engine, state)


@pytest.mark.parametrize("name,types,oracle", [
    ("Meandering Towershell", "Creature — Turtle", TOWERSHELL),
    ("Noctis, Heir Apparent", "Legendary Creature — Human Knight", NOCTIS),
])
def test_declare_attackers_returns_are_modeled(name, types, oracle):
    _modeled(name, types, oracle)


def test_meandering_towershell_exiles_itself_and_returns_attacking_next_turn():
    engine, state = _table()
    shell = _perm(state, "Meandering Towershell", "Creature — Turtle", TOWERSHELL, power=5, toughness=9)
    _attack(engine, state, [shell])
    assert shell.zone == Zone.EXILE
    _to_next_declare_attackers(engine, state)
    assert shell.zone == Zone.BATTLEFIELD and shell.tapped and shell.attacking
    assert shell.controller_id == "p1"


def test_noctis_blinks_into_the_next_combat_unblockable():
    engine, state = _table()
    state.current_phase = "main1"
    state.current_step = "main1"
    noctis = _perm(state, "Noctis, Heir Apparent", "Legendary Creature — Human Knight", NOCTIS, power=3, toughness=3)
    state.player_by_id("p1").mana_pool.add("C", 3)
    engine.activate_ability(state.player_by_id("p1"), noctis, 0)
    engine.resolve_until_stable()
    assert noctis.zone == Zone.EXILE
    _to_next_declare_attackers(engine, state)
    assert noctis.zone == Zone.BATTLEFIELD and noctis.tapped and noctis.attacking


def _noctis_attach_board(phase):
    engine, state = _table()
    state.current_phase = phase
    state.current_step = "declare_attackers" if phase == "combat" else "main1"
    _perm(state, "Noctis, Heir Apparent", "Legendary Creature — Human Knight", NOCTIS, power=3, toughness=3)
    sword = _perm(state, "Sword", "Artifact — Equipment", "Equip {1}",
                  power=None, toughness=None, keywords=["Equip"])
    arriving = _card(state, Zone.HAND, "Arriving", power=2, toughness=2)
    state.player_by_id("p1").remove_from_zone(arriving, Zone.HAND)
    engine.rules._put_searched_card(state.player_by_id("p1"), arriving, "battlefield")
    engine.resolve_until_stable()
    for _ in range(6):
        if state.pending_choice is None:
            break
        pc = state.pending_choice
        want = next((o["id"] for o in pc["options"] if o.get("label") == "Arriving"), None)
        _answer(engine, state, option_id=want)
    return sword, arriving


def test_noctis_attaches_an_equipment_when_a_creature_enters_during_combat():
    sword, arriving = _noctis_attach_board("combat")
    assert sword.attached_to == arriving.instance_id


def test_noctis_does_not_attach_when_the_creature_enters_outside_combat():
    sword, arriving = _noctis_attach_board("main1")
    assert sword.attached_to is None


SPRINKLER = (
    'Whenever The Sprinkler of Stardust attacks, look at the top six cards of your library. You may put an instant '
    'or sorcery card from among them onto the battlefield tapped and attacking. It becomes a 2/2 creature with '
    '"Whenever this deals combat damage to an opponent, cast a copy of this card." '
    '(The 2/2 creature stays on the battlefield.) Put the rest of the cards on the bottom of your library in a random order.'
)


def _sprinkler_board(decline=False):
    engine, state = _table()
    sprinkler = _perm(state, 'The Sprinkler of Stardust', 'Legendary Creature — Human Warrior', SPRINKLER)
    spell = _card(state, Zone.LIBRARY, 'Divination', types='Sorcery', power=None, toughness=None,
                  oracle_text='Draw two cards.', mana_cost_string='{2}{U}', is_sorcery=True)
    bind_from_catalogue(spell)
    _card(state, Zone.LIBRARY, 'Bear')
    _attack(engine, state, [sprinkler])
    pc = state.pending_choice
    assert [o['label'] for o in pc['options'] if o['id'] != 'decline'] == ['Divination']
    _answer(engine, state, option_id='decline' if decline else str(spell.instance_id))
    return engine, state, sprinkler, spell


def test_sprinkler_puts_only_a_spell_into_combat_as_a_persistent_two_two():
    engine, state, sprinkler, spell = _sprinkler_board()
    assert spell.zone == Zone.BATTLEFIELD and spell.is_creature
    assert spell.tapped and spell.attacking
    assert (spell.power, spell.toughness) == (2, 2)
    assert 'sorcery' not in spell.type_words
    assert len(spell._granted_triggered_abilities) == 1
    _advance_to(engine, state, 'end')
    assert spell.zone == Zone.BATTLEFIELD and spell.is_creature
    assert (spell.power, spell.toughness) == (2, 2)
    engine.rules.exile(spell)
    engine.recompute_continuous_effects()
    assert spell.zone == Zone.EXILE
    engine.rules.return_from_graveyard(spell, "battlefield")
    engine.recompute_continuous_effects()
    assert not spell.is_creature and not spell._granted_triggered_abilities


def test_sprinkler_declining_places_nothing_and_bottoms_all_inspected_cards():
    engine, state, sprinkler, spell = _sprinkler_board(decline=True)
    assert spell.zone == Zone.LIBRARY and len(state.player_by_id('p1').library) == 2
    assert state.battlefield == [sprinkler]


def test_sprinkler_combat_damage_copies_the_printed_spell_with_normal_mana_cost():
    engine, state, sprinkler, spell = _sprinkler_board()
    engine._deal_combat_damage_step(first_strike_step=False)
    engine.resolve_until_stable()
    choice = state.resolution_play_choice
    assert choice is not None and not choice['free']
    copy = state.find_object(choice['instance_ids'][0])
    assert copy.is_copy and not copy.is_creature and copy.card.is_sorcery
    assert copy.card.mana_cost_string == '{2}{U}'
    assert spell.zone == Zone.BATTLEFIELD and spell.is_creature
    player = state.player_by_id('p1')
    player.mana_pool.add('U', 1)
    player.mana_pool.add('C', 2)
    engine.cast_spell(player, copy)
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD


def test_sprinkler_catalogue_returns_fresh_specs():
    from mtg_analyzer.game.card_registry import specs_for
    card = Card(id='sprinkler', name='The Sprinkler of Stardust', type_line='Creature', oracle_text=SPRINKLER)
    first, second = specs_for(card), specs_for(card)
    assert first is not second and first[0] is not second[0]


@pytest.mark.parametrize('departure, survives', [(None, False), ('Land', False), ('Creature', True)])
def test_chorale_void_checks_game_wide_nonland_departures(departure, survives):
    engine, state = _table()
    engine.start()
    _advance_to(engine, state, 'main1')
    host = _perm(state, 'Host', 'Creature')
    chorale = _perm(state, 'Chorale of the Void', 'Enchantment — Aura', CHORALE,
                    power=None, toughness=None, keywords=['Void', 'Enchant'])
    chorale.attached_to = host.instance_id
    if departure:
        other = _perm(state, 'Departing', departure, controller='p2',
                      power=2 if departure == 'Creature' else None,
                      toughness=2 if departure == 'Creature' else None)
        engine.rules.exile(other)
    _advance_to(engine, state, 'end')
    assert (chorale.zone == Zone.BATTLEFIELD) == survives


def test_void_condition_accepts_only_warped_cast_events_and_resets_each_turn():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from mtg_analyzer.game.static_conditions import condition_holds
    engine, state = _table()
    cond = {'kind': 'void_this_turn'}
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id='p2'))
    assert not condition_holds(cond, state, controller_id='p1')
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id='p2', warped=True))
    assert condition_holds(cond, state, controller_id='p1')
    _to_next_declare_attackers(engine, state)
    assert not condition_holds(cond, state, controller_id='p1')


def test_unrestricted_placed_attacker_can_choose_another_opponent():
    engine, state = _table(opponents=2)
    neutrinos = _perm(state, 'The Neutrinos', 'Legendary Creature — Elf Rebel', NEUTRINOS)
    friend = _perm(state, 'Friend', 'Creature')
    _attack(engine, state, [{'attacker': neutrinos, 'defender': {'kind': 'player', 'id': 'p3'}}])
    _answer(engine, state, option_id=str(friend.instance_id))
    pc = state.pending_choice
    assert pc['kind'] == 'reselect_attack'
    assert {o['id'] for o in pc['options']} >= {'player:p2', 'player:p3'}
    _answer(engine, state, option_id='player:p2')
    assert friend.combat_defender['id'] == 'p2'


def test_noctis_returns_in_its_owners_upcoming_combat_even_when_borrowed():
    from mtg_analyzer.game.combat import has
    engine, state = _table()
    state.current_phase = state.current_step = 'main1'
    noctis = _perm(state, 'Noctis, Heir Apparent', 'Legendary Creature — Human Noble', NOCTIS)
    noctis.owner_id = 'p2'
    for owner in ('p1', 'p2'):
        for n in range(3):
            _card(state, Zone.LIBRARY, f'Draw {owner} {n}', owner=owner)
    state.player_by_id('p1').mana_pool.add('C', 3)
    engine.activate_ability(state.player_by_id('p1'), noctis, 0)
    engine.resolve_until_stable()
    assert noctis.zone == Zone.EXILE
    _to_next_declare_attackers(engine, state, 'p2')
    assert noctis.zone == Zone.BATTLEFIELD and noctis.controller_id == 'p2' and noctis.attacking
    blocker = _perm(state, 'Blocker', 'Creature')
    assert not engine.can_block(state.player_by_id("p1"), blocker, noctis)
    assert has(noctis, "cant_be_blocked")
    _advance_to(engine, state, "main2")
    engine.recompute_continuous_effects()
    assert not has(noctis, "cant_be_blocked")


def test_noctis_activated_in_main_phase_returns_in_the_same_turns_combat():
    engine, state = _table()
    engine.start()
    _advance_to(engine, state, 'main1')
    noctis = _perm(state, 'Noctis, Heir Apparent', 'Legendary Creature — Human Noble', NOCTIS)
    turn = state.internal_turn.number
    state.player_by_id('p1').mana_pool.add('C', 3)
    engine.activate_ability(state.player_by_id('p1'), noctis, 0)
    engine.resolve_until_stable()
    assert noctis.zone == Zone.EXILE
    _advance_to(engine, state, 'declare_attackers')
    assert state.internal_turn.number == turn
    assert noctis.zone == Zone.BATTLEFIELD and noctis.attacking


def test_sprinkler_copy_cast_is_mandatory_with_payable_costs():
    engine, state, _, spell = _sprinkler_board()
    engine._deal_combat_damage_step(first_strike_step=False)
    engine.resolve_until_stable()
    player = state.player_by_id('p1')
    assert any(a['type'] == 'decline' for a in engine.resolution_play_actions(player))
    player.mana_pool.add('C', 2)
    player.mana_pool.add('U', 1)
    assert not any(a['type'] == 'decline' for a in engine.resolution_play_actions(player))
    with pytest.raises(ValueError, match='mandatory'):
        engine.rules.resolve_choice('decline')
    assert state.pending_choice['kind'] == 'play_during_resolution'
    copy = state.find_object(state.resolution_play_choice['instance_ids'][0])
    engine.cast_spell(player, copy)
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD


def test_olivia_state_trigger_exiles_the_returned_creature_if_olivia_already_left():
    engine, state = _table()
    olivia = _perm(state, 'Olivia, Crimson Bride', 'Legendary Creature — Vampire Noble', OLIVIA,
                   is_legendary=True)
    risen = _card(state, Zone.GRAVEYARD, 'Risen Bear')
    _attack(engine, state, [olivia])
    assert state.pending_choice['kind'] == 'trigger_target'
    engine.rules.exile(olivia)
    while state.pending_choice is not None:
        _answer(engine, state)
    engine.resolve_until_stable()
    assert risen.zone == Zone.EXILE


def test_olivia_state_trigger_waits_for_its_existing_firing_to_leave_the_stack():
    engine, state = _table()
    olivia = _perm(state, 'Olivia, Crimson Bride', 'Legendary Creature — Vampire Noble', OLIVIA,
                   is_legendary=True)
    risen = _card(state, Zone.GRAVEYARD, 'Risen Bear')
    _attack(engine, state, [olivia])
    while state.pending_choice is not None:
        _answer(engine, state)
    engine.rules.exile(olivia)
    engine.rules.check_state_based_actions()
    assert len(engine.rules.pending_triggers) == 1
    engine.rules.check_state_based_actions()
    assert len(engine.rules.pending_triggers) == 1
    engine.rules.put_triggers_on_stack()
    assert len(state.stack) == 1
    engine.rules.check_state_based_actions()
    assert not engine.rules.pending_triggers
    engine.resolve_until_stable()
    assert risen.zone == Zone.EXILE


MEANDERED = (
    'Enchant creature\nEnchanted creature has islandwalk and "Whenever this creature attacks, exile it and '
    'Meandered Towershell. Return it to the battlefield under your control tapped and attacking at the beginning '
    'of the declare attackers step on your next turn, then return Meandered Towershell to the battlefield '
    'under its owner\'s control attached to that creature."'
)


def _meandered_board():
    engine, state = _table()
    for owner in ("p1", "p2"):
        for n in range(6):
            _card(state, Zone.LIBRARY, f"Meandered draw {owner} {n}", owner=owner)
    host = _perm(state, 'Enchanted Bear', 'Creature')
    aura = _perm(state, 'Meandered Towershell', 'Enchantment — Aura', MEANDERED,
                 controller='p2', power=None, toughness=None, keywords=['Enchant'])
    aura.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    return engine, state, host, aura


def test_meandered_towershell_returns_the_creature_attacking_and_the_aura_attached_under_its_owner():
    engine, state, host, aura = _meandered_board()
    from mtg_analyzer.game.combat import has
    assert has(host, "islandwalk")
    _attack(engine, state, [host])
    assert host.zone == aura.zone == Zone.EXILE
    assert state.delayed_triggers[0].controller_id == 'p1'  # the creature's granted ability
    _to_next_declare_attackers(engine, state)
    assert host.zone == Zone.BATTLEFIELD and host.attacking and host.tapped
    assert aura.zone == Zone.BATTLEFIELD and aura.controller_id == 'p2'
    assert aura.attached_to == host.instance_id


def test_meandered_towershell_leaves_the_aura_exiled_if_the_creature_is_gone():
    engine, state, host, aura = _meandered_board()
    _attack(engine, state, [host])
    state.player_by_id(host.owner_id).remove_from_zone(host, Zone.EXILE)
    host.reset_as_new_object()
    host.zone = Zone.GRAVEYARD
    state.player_by_id(host.owner_id).add_to_zone(host, Zone.GRAVEYARD)
    _to_next_declare_attackers(engine, state)
    assert host.zone == Zone.GRAVEYARD and aura.zone == Zone.EXILE


def test_meandered_towershell_grant_is_fresh_after_the_aura_returns():
    engine, state, host, aura = _meandered_board()
    _attack(engine, state, [host])
    _to_next_declare_attackers(engine, state)
    _to_next_declare_attackers(engine, state)
    _attack(engine, state, [host])
    assert host.zone == aura.zone == Zone.EXILE


def test_meandered_towershell_catalogue_returns_fresh_specs():
    from mtg_analyzer.game.card_registry import specs_for
    card = Card(id='meandered', name='Meandered Towershell', type_line='Enchantment — Aura',
                oracle_text=MEANDERED, keywords=['Enchant'])
    first, second = specs_for(card), specs_for(card)
    assert first is not second and first[0] is not second[0]
