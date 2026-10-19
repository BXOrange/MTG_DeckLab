"""PAR-132 -- "<tap/sacrifice/return/discard> any number of X. <body> for each X <verb>ed this way" (RULE 608.2c).

One `choose_objects` pick whose ``then_that_many`` body is the ordinary for-each bind over how many were picked.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _card(name: str, text: str, type_line: str = "Sorcery") -> Card:
    return Card(id=name[:6], name=name, type_line=type_line, is_sorcery="Sorcery" in type_line, oracle_text=text,
                mana_cost_string="{0}", converted_mana_cost=0)


def _board(creatures: int = 3, lands: tuple[str, ...] = ()):  # noqa: D401
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Creature", is_creature=True, power=1, toughness=1)
              for i in range(30)]
    eng = GameEngine.new_game([("p1", "p1", list(filler)), ("p2", "p2", list(filler))], starting_life=20,
                              starting_hand=0)
    st = eng.state
    eng.start()
    while st.current_phase != "precombat_main":  # RULE 601.3a: a sorcery needs its controller's main phase
        eng.advance_step()
    for i in range(creatures):
        c = GameObject(
            Card(id=f"b{i}", name=f"Bear{i}", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        c.controller_id = "p1"
        st.add_to_battlefield(c)
    for i, sub in enumerate(lands):
        c = GameObject(
            Card(id=f"l{i}", name=sub, type_line=f"Basic Land — {sub}", is_land=True),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        c.controller_id = "p1"
        st.add_to_battlefield(c)
    src = GameObject(Card(id="SP", name="Spell", type_line="Sorcery", is_sorcery=True), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    return eng, st, src


def _run(eng, src, card: Card, picks: int):
    """Cast ``card`` for real (so its source is a spell mid-resolution) and answer its choices."""
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    player = eng.state.player_by_id("p1")
    player.mana_pool.add_many({"C": 4})
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    player.hand.append(spell)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    for _ in range(picks):
        choice = eng.state.pending_choice
        assert choice and choice["kind"] == "choose_objects"
        eng.rules.resolve_choice(str(choice["options"][0]["id"]))
        eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None


def test_tap_any_number_gains_life_per_tapped_creature():
    eng, st, src = _board(3)
    _run(eng, src, _card("Harmony", "Tap any number of untapped creatures you control. "
                                    "You gain 4 life for each creature tapped this way."), picks=2)
    assert st.player_by_id("p1").life == 28
    assert sum(1 for o in st.battlefield if o.tapped) == 2


def test_tap_pool_excludes_tapped_creatures_and_other_types():
    eng, st, src = _board(2)
    st.battlefield[0].tapped = True
    _run(eng, src, _card("Harmony", "Tap any number of untapped creatures you control. "
                                    "You gain 4 life for each creature tapped this way."), picks=1)
    assert st.player_by_id("p1").life == 24


def test_declining_every_pick_does_nothing():
    eng, st, src = _board(2)
    _run(eng, src, _card("Harmony", "Tap any number of untapped creatures you control. "
                                    "You gain 4 life for each creature tapped this way."), picks=0)
    assert st.player_by_id("p1").life == 20


def test_return_subtype_lands_pumps_creatures_per_returned():
    eng, st, src = _board(1, lands=("Plains", "Plains", "Mountain"))
    _run(eng, src, _card("Charge", "Return any number of Plains you control to their owner's hand. Creatures you "
                                   "control get +1/+1 until end of turn for each Plains returned this way."), picks=2)
    bear = next(o for o in st.battlefield if o.is_creature)
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)
    assert sum(1 for c in st.player_by_id("p1").hand if c.is_land) == 2
    assert any(o.is_land and "Mountain" in o.card.type_line for o in st.battlefield)


def test_trailing_noun_must_match_the_pool():
    card = _card("Mismatch", "Tap any number of untapped creatures you control. "
                             "You gain 4 life for each land tapped this way.")
    assert parse_oracle(card).coverage == UNMODELED


def test_body_with_target_is_refused():
    card = _card("Targeted", "Tap any number of untapped creatures you control. Target creature gets +1/+1 until "
                             "end of turn for each creature tapped this way.")
    assert parse_oracle(card).coverage == UNMODELED


# --- the rest of the family, executed as the real card text -----------------------------------------------------


def _answer(eng, picks: int):
    for _ in range(picks):
        choice = eng.state.pending_choice
        assert choice and choice["kind"] == "choose_objects"
        eng.rules.resolve_choice(str(choice["options"][0]["id"]))
        eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.rules.resolve_choice("decline")
        eng.resolve_until_stable()
    assert eng.state.pending_choice is None


def test_renounce_sacrifices_chosen_permanents_for_life():
    eng, st, src = _board(3)
    _run(eng, src, _card("Renounce", "Sacrifice any number of permanents. You gain 2 life for each permanent "
                                     "sacrificed this way."), picks=2)
    assert st.player_by_id("p1").life == 24
    assert sum(1 for o in st.battlefield if o.controller_id == "p1") == 1


def test_sacred_rites_discards_from_hand_and_pumps_toughness():
    eng, st, src = _board(1)
    hand = st.player_by_id("p1").hand
    for i in range(2):
        card = GameObject(Card(id=f"h{i}", name=f"Card{i}", type_line="Sorcery", is_sorcery=True),
                          owner_id="p1", zone=Zone.HAND)
        hand.append(card)
    _run(eng, src, _card("Rites", "Discard any number of cards. Creatures you control get +0/+1 until end of turn "
                                  "for each card discarded this way."), picks=2)
    eng.recompute_continuous_effects()
    bear = next(o for o in st.battlefield if o.is_creature)
    assert (bear.power, bear.toughness) == (2, 4)
    assert not [c for c in hand if c.name.startswith("Card")]


def test_devout_invocation_creates_one_angel_per_tapped_creature():
    eng, st, src = _board(3)
    _run(eng, src, _card("Devout", "Tap any number of untapped creatures you control. Create a 4/4 white Angel "
                                   "creature token with flying for each creature tapped this way."), picks=2)
    angels = [o for o in st.battlefield if o.is_token and o.controller_id == "p1"]
    assert len(angels) == 2 and all((a.power, a.toughness) == (4, 4) for a in angels)


def _creature(text: str, name: str) -> Card:
    return Card(id=name[:6], name=name, type_line="Creature — Human", is_creature=True, power=2, toughness=2,
                oracle_text=text, mana_cost_string="{0}", converted_mana_cost=0)


def test_mind_maggots_puts_counters_on_itself_per_discarded_creature_card():
    eng, st, src = _board(0)
    hand = st.player_by_id("p1").hand
    for i in range(2):
        hand.append(GameObject(Card(id=f"c{i}", name=f"Creature{i}", type_line="Creature — Bear",
                                    is_creature=True, power=1, toughness=1), owner_id="p1", zone=Zone.HAND))
    hand.append(GameObject(Card(id="s", name="Spell", type_line="Sorcery", is_sorcery=True),
                           owner_id="p1", zone=Zone.HAND))
    card = _creature("When ~ enters, discard any number of creature cards. For each card discarded this way, put "
                     "2 +1/+1 counters on ~.", "Maggots")
    _run(eng, src, card, picks=2)
    maggots = next(o for o in st.battlefield if o.name == "Maggots")
    assert maggots.counters.get("+1/+1") == 4
    assert [c.name for c in hand] == ["Spell"]  # the pool offered only creature cards


def test_attack_trigger_pumps_the_attacker_per_tapped_creature():
    eng, st, src = _board(0)
    from mtg_analyzer.game.binding.core import bind_from_catalogue as bind

    card = _creature("Whenever ~ attacks, tap any number of untapped creatures you control. ~ gets +1/+1 until "
                     "end of turn for each creature tapped this way.", "Orphans")
    attacker = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    attacker.controller_id = "p1"
    attacker.summoning_sick = False
    bind(attacker)
    st.add_to_battlefield(attacker)
    for i in range(2):
        mate = GameObject(Card(id=f"m{i}", name=f"Mate{i}", type_line="Creature — Bear", is_creature=True,
                               power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
        mate.controller_id = "p1"
        st.add_to_battlefield(mate)
    eng.recompute_continuous_effects()
    while st.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(st.player_by_id("p1"), [attacker])
    eng.resolve_until_stable()
    # The attacker is tapped by attacking, so only the two other creatures are offered.
    assert {o["label"] for o in st.pending_choice["options"] if o["id"] != "decline"} == {"Mate0", "Mate1"}
    _answer(eng, 2)
    eng.recompute_continuous_effects()
    assert (attacker.power, attacker.toughness) == (4, 4)


# --- "If a [non]creature card was exiled this way" (the exile pool condition) -------------------------------------


def _scavenger_game(card: Card, graveyard_cards: list[Card]):
    eng, st, src = _board(0)
    for i, printed in enumerate(graveyard_cards):
        grave = GameObject(printed, owner_id="p2", zone=Zone.GRAVEYARD)
        st.player_by_id("p2").graveyard.append(grave)
    player = st.player_by_id("p1")
    player.mana_pool.add_many({"C": 4})
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    player.hand.append(obj)
    st.player_by_id("p1").life = 20
    return eng, st, obj


def _cast_and_target(eng, st, obj, grave_index: int):
    eng.cast_spell(st.player_by_id("p1"), obj)
    eng.resolve_until_stable()
    choice = st.pending_choice
    assert choice is not None, "the ETB trigger should ask for its graveyard target"
    options = [o for o in choice["options"] if o["id"] != "decline"]
    eng.rules.resolve_choice(str(options[grave_index]["id"]))
    eng.resolve_until_stable()


_CREATURE_CARD = Card(id="gc", name="Dead Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)
_SORCERY_CARD = Card(id="gs", name="Dead Sorcery", type_line="Sorcery", is_sorcery=True)
_DIREGRAF = ("When ~ enters, exile up to one target card from a graveyard. If a creature card was exiled this way, "
             "each opponent loses 2 life and you gain 2 life.")


def test_creature_card_exiled_triggers_the_rider():
    eng, st, obj = _scavenger_game(_creature(_DIREGRAF, "Diregraf"), [_CREATURE_CARD])
    _cast_and_target(eng, st, obj, 0)
    assert st.player_by_id("p2").life == 18 and st.player_by_id("p1").life == 22
    assert [c.name for c in st.player_by_id("p2").graveyard] == []


def test_noncreature_card_exiled_does_not_trigger_the_creature_rider():
    eng, st, obj = _scavenger_game(_creature(_DIREGRAF, "Diregraf"), [_SORCERY_CARD])
    _cast_and_target(eng, st, obj, 0)
    assert st.player_by_id("p2").life == 20 and st.player_by_id("p1").life == 20
    assert [c.name for c in st.player_by_id("p2").graveyard] == []  # it was still exiled


def test_deathgorge_scavenger_branches_on_the_exiled_type():
    text = ("Whenever ~ enters or attacks, you may exile target card from a graveyard. If a creature card is exiled "
            "this way, you gain 2 life. If a noncreature card is exiled this way, ~ gets +1/+1 until end of turn.")
    eng, st, obj = _scavenger_game(_creature(text, "Deathgorge"), [_SORCERY_CARD])
    eng.cast_spell(st.player_by_id("p1"), obj)
    eng.resolve_until_stable()
    choice = st.pending_choice
    while choice is not None:
        pick = next((o for o in choice["options"] if o["id"] != "decline"), choice["options"][0])
        eng.rules.resolve_choice(str(pick["id"]))
        eng.resolve_until_stable()
        choice = st.pending_choice
    eng.recompute_continuous_effects()
    assert st.player_by_id("p1").life == 20
    assert (obj.power, obj.toughness) == (3, 3)


def test_discard_hand_then_draw_pumps_per_discarded_card_without_prompting():
    eng, st, src = _board(1)
    hand = st.player_by_id("p1").hand
    for i in range(3):
        hand.append(GameObject(Card(id=f"h{i}", name=f"Card{i}", type_line="Sorcery", is_sorcery=True),
                               owner_id="p1", zone=Zone.HAND))
    _run(eng, src, _card("Pyretic", "Discard your hand, then draw four cards. For each card discarded this way, "
                                    "creatures you control get +1/+0 until end of turn."), picks=0)
    eng.recompute_continuous_effects()
    bear = next(o for o in st.battlefield if o.is_creature)
    assert bear.power == 5  # three cards discarded (the cast spell itself had left the hand)
    assert len(hand) == 4 and not any(c.name.startswith("Card") for c in hand)


def test_malfegor_makes_each_opponent_sacrifice_per_discarded_card():
    eng, st, src = _board(0)
    st.player_by_id("p1").hand.extend(
        GameObject(Card(id=f"h{i}", name=f"Card{i}", type_line="Sorcery", is_sorcery=True),
                   owner_id="p1", zone=Zone.HAND) for i in range(2))
    for i in range(3):
        bear = GameObject(Card(id=f"o{i}", name=f"Opp{i}", type_line="Creature — Bear", is_creature=True,
                               power=1, toughness=1), owner_id="p2", zone=Zone.BATTLEFIELD)
        bear.controller_id = "p2"
        st.add_to_battlefield(bear)
    card = _creature("When ~ enters, discard your hand. Each opponent sacrifices a creature of their choice for "
                     "each card discarded this way.", "Malfegor")
    player = st.player_by_id("p1")
    player.mana_pool.add_many({"C": 4})
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    player.hand.append(spell)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    # The opponent's mandatory sacrifices are their own choices (RULE 701.17a): answer each in turn.
    while st.pending_choice is not None:
        eng.rules.resolve_choice(str(st.pending_choice["options"][0]["id"]))
        eng.resolve_until_stable()
    assert not [c for c in player.hand if c.name.startswith("Card")]
    assert sum(1 for o in st.battlefield if o.controller_id == "p2") == 1
