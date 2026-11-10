"""PAR-245: the per-card "whenever a <type> card leaves your / an opponent's graveyard" head, with the second clauses
of Murktide Regent, Along the Crooked Way and Erebos's Titan, through the real engine and real cached cards."""
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import activate, answer, card, cast, filler, game

#: Murktide Regent's cost, {5}{U}{U}: paying the two blue pips by mana leaves exactly five generic for Delve.
MURKTIDE_BLUE_PIPS = {"U": 2}
MURKTIDE_GENERIC = 5
#: Murktide Regent's printed size, before any counter.
MURKTIDE_BASE_SIZE = 3
#: The mana an Along the Crooked Way menace activation costs, {1}{B}.
MENACE_ACTIVATION_POOL = {"B": 1, "C": 1}


def _gy(eng, name, player="p1"):
    return card(eng, name, player, zone=Zone.GRAVEYARD)


def _leave(eng, obj):
    """The card goes from its graveyard to its owner's hand (RULE 603.6c: it left the graveyard)."""
    eng.rules.return_from_graveyard(obj, "hand")
    eng.resolve_until_stable()


def _counters(obj):
    return obj.plus_one_counters


def _fill_graveyard_for_delve(eng):
    """Two instants, one sorcery, one creature and one land: five cards, three of them instants or sorceries."""
    cards = [
        _gy(eng, "Lightning Bolt"), _gy(eng, "Opt"), _gy(eng, "Divination"),
        _gy(eng, "Grizzly Bears"), _gy(eng, "Forest"),
    ]
    assert len(cards) == MURKTIDE_GENERIC
    return cards


def _murktide_on_battlefield(eng):
    gy = _fill_graveyard_for_delve(eng)
    murktide = card(eng, "Murktide Regent", zone=Zone.HAND)
    cast(eng, murktide, pool=MURKTIDE_BLUE_PIPS, help_pay=True)
    return murktide, gy


# --- the three cards are modeled ------------------------------------------------------------------------------

def test_the_three_cards_are_modeled():
    db = CardDatabase(DB_PATH)
    for name in ("Murktide Regent", "Along the Crooked Way", "Erebos's Titan"):
        result = parse_oracle(db.get_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_the_head_emits_a_per_card_trigger_for_each_owner():
    db = CardDatabase(DB_PATH)
    murktide = parse_oracle(db.get_card("Murktide Regent"))
    trig = next(s.trigger for s in murktide.specs if s.ability_kind == "triggered")
    assert trig == {"event": "CARD_LEFT_GRAVEYARD", "graveyard_owner": "you",
                    "left_graveyard_types": ["instant", "sorcery"]}
    titan = parse_oracle(db.get_card("Erebos's Titan"))
    trig = next(s.trigger for s in titan.specs if s.ability_kind == "triggered")
    assert trig["graveyard_owner"] == "opponent" and trig["left_graveyard_types"] == ["creature"]


# --- Murktide Regent ------------------------------------------------------------------------------------------

def test_murktide_enters_with_a_counter_per_instant_or_sorcery_it_delved():
    eng = game()
    murktide, gy = _murktide_on_battlefield(eng)
    assert murktide.zone == Zone.BATTLEFIELD
    assert all(c.zone == Zone.EXILE for c in gy)  # RULE 702.66: all five were exiled to pay
    assert _counters(murktide) == 3  # Lightning Bolt, Opt and Divination; the creature and the land do not count
    eng.recompute_continuous_effects()
    assert murktide.power == MURKTIDE_BASE_SIZE + 3


def test_murktide_counts_only_what_delve_exiled_not_other_exiled_cards():
    eng = game()
    card(eng, "Lightning Bolt", zone=Zone.EXILE)  # exiled by something else: never "exiled with it"
    murktide = card(eng, "Murktide Regent", zone=Zone.HAND)
    for _ in range(MURKTIDE_GENERIC):
        filler(eng, "Junk", type_line="Land", zone=Zone.GRAVEYARD)
    cast(eng, murktide, pool=MURKTIDE_BLUE_PIPS, help_pay=True)
    assert _counters(murktide) == 0


def test_murktide_gains_a_counter_when_an_instant_leaves_your_graveyard():
    eng = game()
    murktide, _ = _murktide_on_battlefield(eng)
    before = _counters(murktide)
    _leave(eng, _gy(eng, "Shock"))
    assert _counters(murktide) == before + 1


def test_murktide_ignores_other_types_and_an_opponents_graveyard():
    eng = game()
    murktide, _ = _murktide_on_battlefield(eng)
    before = _counters(murktide)
    _leave(eng, _gy(eng, "Grizzly Bears"))  # a creature card: type mismatch
    _leave(eng, _gy(eng, "Shock", "p2"))  # an instant, but in an opponent's graveyard
    assert _counters(murktide) == before


def test_each_card_leaving_at_once_triggers_separately():
    eng = game()
    murktide, _ = _murktide_on_battlefield(eng)
    before = _counters(murktide)
    first, second, creature = _gy(eng, "Shock"), _gy(eng, "Opt"), _gy(eng, "Grizzly Bears")
    # RULE 603.2c: a mass exit is simultaneous, yet "whenever a ... card leaves" triggers once per matching card.
    with eng.state.simultaneous():
        for obj in (first, second, creature):
            eng.rules.return_from_graveyard(obj, "hand")
    eng.resolve_until_stable()
    assert _counters(murktide) == before + 2


def test_any_destination_counts_including_exile_and_the_battlefield():
    eng = game()
    murktide, _ = _murktide_on_battlefield(eng)
    before = _counters(murktide)
    to_exile = _gy(eng, "Shock")
    eng.rules.exile(to_exile)
    eng.resolve_until_stable()
    assert _counters(murktide) == before + 1


def test_murktide_through_a_session_cast_then_undo():
    eng = game()
    gy = _fill_graveyard_for_delve(eng)
    murktide = card(eng, "Murktide Regent", zone=Zone.HAND)
    eng.state.current_phase, eng.state.current_step = "main", "main1"
    eng.state.player_by_id("p1").mana_pool.add_many(MURKTIDE_BLUE_PIPS)
    session = GameSession(eng, require_setup=False)
    session.apply_action({"type": "cast_spell", "instance_id": murktide.instance_id, "help_pay": True}, actor_id="p1")
    session.engine.resolve_until_stable()
    live = next(o for o in session.engine.state.battlefield if o.name == "Murktide Regent")
    assert _counters(live) == 3
    session.rewind(1)
    rewound = session.engine.state
    assert not [o for o in rewound.battlefield if o.name == "Murktide Regent"]
    assert [o.name for o in rewound.player_by_id("p1").graveyard].count("Lightning Bolt") == 1
    assert len(gy) == MURKTIDE_GENERIC


# --- Along the Crooked Way ------------------------------------------------------------------------------------

def test_along_the_crooked_way_amasses_when_a_creature_card_leaves():
    eng = game()
    card(eng, "Along the Crooked Way")
    _leave(eng, _gy(eng, "Grizzly Bears"))
    armies = [o for o in eng.state.battlefield if "Army" in o.card.type_line]
    assert len(armies) == 1 and _counters(armies[0]) == 1
    _leave(eng, _gy(eng, "Shock"))  # not a creature card
    assert _counters(armies[0]) == 1
    _leave(eng, _gy(eng, "Grizzly Bears"))
    assert _counters(armies[0]) == 2  # RULE 701.47: the existing Army grows


def test_along_the_crooked_way_menace_reaches_goblins_and_orcs_only():
    eng = game()
    card(eng, "Along the Crooked Way")
    _leave(eng, _gy(eng, "Grizzly Bears"))
    army = next(o for o in eng.state.battlefield if "Army" in o.card.type_line)
    goblin = filler(eng, "Goblin Body", type_line="Creature — Goblin", power=1, toughness=1)
    orc = filler(eng, "Orc Body", type_line="Creature — Orc", power=1, toughness=1)
    elf = filler(eng, "Elf Body", type_line="Creature — Elf", power=1, toughness=1)
    eng.state.player_by_id("p1").mana_pool.add_many(MENACE_ACTIVATION_POOL)
    activate(eng, next(o for o in eng.state.battlefield if o.name == "Along the Crooked Way"))
    eng.recompute_continuous_effects()
    assert "menace" in army.granted_keywords  # the amassed Army is a Goblin
    assert "menace" in goblin.granted_keywords and "menace" in orc.granted_keywords
    assert "menace" not in elf.granted_keywords


def test_along_the_crooked_way_ignores_an_opponents_graveyard():
    eng = game()
    card(eng, "Along the Crooked Way")
    _leave(eng, _gy(eng, "Grizzly Bears", "p2"))
    assert not [o for o in eng.state.battlefield if "Army" in o.card.type_line]


# --- Erebos's Titan -------------------------------------------------------------------------------------------

def _titan_in_graveyard(eng):
    titan = card(eng, "Erebos's Titan", zone=Zone.GRAVEYARD)
    discard = filler(eng, "Discard Fodder", type_line="Sorcery", zone=Zone.HAND)
    return titan, discard


def test_titan_returns_from_the_graveyard_when_an_opponents_creature_card_leaves():
    eng = game()
    titan, discard = _titan_in_graveyard(eng)
    _leave(eng, _gy(eng, "Grizzly Bears", "p2"))
    assert eng.state.pending_choice is not None  # RULE 603.6c: it triggers from the graveyard
    answer(eng, lambda choice: "pay" if any(str(o["id"]) == "pay" for o in choice.get("options") or []) else None)
    eng.resolve_until_stable()
    if eng.state.pending_choice is not None:
        answer(eng)
    assert discard.zone == Zone.GRAVEYARD
    assert titan.zone == Zone.HAND


def test_titan_discard_is_optional_and_declining_leaves_it_in_the_graveyard():
    eng = game()
    titan, discard = _titan_in_graveyard(eng)
    _leave(eng, _gy(eng, "Grizzly Bears", "p2"))
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert titan.zone == Zone.GRAVEYARD and discard.zone == Zone.HAND


def test_titan_ignores_its_own_players_graveyard_and_other_card_types():
    eng = game()
    titan, discard = _titan_in_graveyard(eng)
    _leave(eng, _gy(eng, "Grizzly Bears"))  # your own graveyard
    _leave(eng, _gy(eng, "Shock", "p2"))  # an opponent's, but not a creature card
    assert eng.state.pending_choice is None
    assert titan.zone == Zone.GRAVEYARD and discard.zone == Zone.HAND


def test_titan_does_not_trigger_from_the_battlefield():
    eng = game()
    card(eng, "Erebos's Titan")
    discard = filler(eng, "Discard Fodder", type_line="Sorcery", zone=Zone.HAND)
    _leave(eng, _gy(eng, "Grizzly Bears", "p2"))
    assert eng.state.pending_choice is None and discard.zone == Zone.HAND


def test_titan_is_indestructible_only_while_opponents_control_no_creatures():
    eng = game()
    titan = card(eng, "Erebos's Titan")
    eng.recompute_continuous_effects()
    assert "indestructible" in titan.granted_keywords
    bear = filler(eng, "Opposing Bear", player="p2", power=2, toughness=2)
    eng.recompute_continuous_effects()
    assert "indestructible" not in titan.granted_keywords
    eng.rules.destroy(bear)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert "indestructible" in titan.granted_keywords


def test_titan_trigger_survives_a_state_clone():
    eng = game()
    titan, discard = _titan_in_graveyard(eng)
    _leave(eng, _gy(eng, "Grizzly Bears", "p2"))
    clone = GameEngine(eng.state.clone())
    assert clone.state.pending_choice is not None  # the optional discard question was kept
    eng.resolve_pending_choice("decline")
    assert titan.zone == Zone.GRAVEYARD


# --- the other cards the two shared grammar pieces unlocked, each executed ----------------------------------------
# A joined subtype list as a group subject (`goblins and orcs you control`) and `your opponents control no creatures`.

def _creature(eng, name, subtype, player="p1"):
    return filler(eng, name, type_line=f"Creature — {subtype}", player=player, power=1, toughness=1)


def test_captain_america_gives_soldiers_and_heroes_indestructible():
    eng = game()
    soldier, hero, other = _creature(eng, "S", "Soldier"), _creature(eng, "H", "Hero"), _creature(eng, "O", "Elf")
    theirs = _creature(eng, "T", "Soldier", player="p2")
    captain = card(eng, "Captain America, Unbowed", zone=Zone.HAND)
    cast(eng, captain)
    eng.recompute_continuous_effects()
    assert "indestructible" in soldier.granted_keywords and "indestructible" in hero.granted_keywords
    assert "indestructible" not in other.granted_keywords and "indestructible" not in theirs.granted_keywords


def test_kaitos_pursuit_discards_and_gives_ninjas_and_rogues_menace():
    eng = game()
    ninja, rogue, other = _creature(eng, "N", "Ninja"), _creature(eng, "R", "Rogue"), _creature(eng, "O", "Elf")
    for i in range(2):
        filler(eng, f"Hand {i}", type_line="Sorcery", player="p2", zone=Zone.HAND)
    cast(eng, card(eng, "Kaito's Pursuit", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    answer(eng)
    eng.recompute_continuous_effects()
    assert not eng.state.player_by_id("p2").hand
    assert "menace" in ninja.granted_keywords and "menace" in rogue.granted_keywords
    assert "menace" not in other.granted_keywords


def test_deb_thomas_minus_x_pumps_employees_and_dogs():
    eng = game()
    deb = card(eng, "Deb Thomas")
    employee, dog, other = _creature(eng, "E", "Employee"), _creature(eng, "D", "Dog"), _creature(eng, "O", "Elf")
    deb.counters["loyalty"] = 5
    activate(eng, deb, index=1, x=2)
    eng.recompute_continuous_effects()
    assert employee.power == 3 and dog.power == 3 and other.power == 1


def test_kickoff_celebrations_sacrifice_grants_haste_at_max_speed():
    eng = game()
    celebrations = card(eng, "Kickoff Celebrations")
    rider = _creature(eng, "Rider", "Elf")
    eng.state.player_by_id("p1").speed = 4
    activate(eng, celebrations)
    eng.recompute_continuous_effects()
    assert celebrations.zone == Zone.GRAVEYARD
    assert "haste" in rider.granted_keywords


def test_kezzerdrix_hurts_you_only_while_your_opponents_control_no_creatures():
    eng = game()
    card(eng, "Kezzerdrix")
    life = eng.state.player_by_id("p1").life
    from tests.support.deck_batch import step

    step(eng, "upkeep")
    assert eng.state.player_by_id("p1").life == life - 4
    _creature(eng, "Theirs", "Bear", player="p2")
    step(eng, "upkeep")
    assert eng.state.player_by_id("p1").life == life - 4  # an opposing creature switches the trigger off


def test_chevill_marks_a_creature_when_no_opponent_permanent_carries_a_bounty():
    eng = game()
    card(eng, "Chevill, Bane of Monsters")
    victim = _creature(eng, "Victim", "Bear", player="p2")
    from tests.support.deck_batch import step

    step(eng, "upkeep")
    answer(eng)
    assert victim.counters.get("bounty") == 1


# --- a sentence that merely opens with a keyword word is not a keyword line ------------------------------------------

def test_a_keyword_cost_reduction_sentence_is_not_claimed_as_a_bare_keyword():
    # PAR-256 models the sentence for real: it is a cost_reduction static, not an inert keyword claim.
    db = CardDatabase(DB_PATH)
    for name in ("Boom Scholar", "Fluctuator", "Warbringer", "Silver-Fur Master", "Catalyst Stone"):
        result = parse_oracle(db.get_card(name))
        assert any(e.type == "cost_reduction" for s in result.specs for e in s.effects), name


def test_real_keyword_lines_are_still_keyword_lines():
    from mtg_analyzer.parser.oracle.segmenter import is_keyword_line

    for line in ("flying", "flashback {2}{r}", "boast {1}{r}", "cycling {2}", "ninjutsu {1}{u}"):
        assert is_keyword_line(line), line
    for line in ("exhaust abilities of other permanents you control cost {2} less to activate.",
                 "flashback costs you pay cost {2} less."):
        assert not is_keyword_line(line), line
