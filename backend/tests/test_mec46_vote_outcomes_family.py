"""MEC-46 — RULE 701.38 Vote outcome bodies that needed new primitives.

Four shapes split out of PAR-30 once its parser-reachable vote grammar was
exhausted:

* **per-winning-option** (`request_vote(winner_specs=...)`) — apply *every*
  tied-for-most option's spec list, plus an indefinite (RULE 611, no
  duration) self-scoped "protection from <colour>" grant. Council Guardian.
* **targeted-tally** (`request_object_vote`) — each voter picks a board /
  graveyard *object*, then exile / return each most-voted one. Council's
  Judgment, Custodi Squire.
* **forced vote** (`set_forced_voter` / `GameState.forced_vote_controller_id`)
  — one player answers every seat's ballot for the turn. Illusion of Choice.
* **Expropriate** — a count-aware `take_extra_turn` per time vote + a
  per-*ballot* gain-control per money vote.

Plus Galadriel, Elven-Queen's parser residue (ring-tempts bare body, "your
Ring-bearer" counter selector, "if another Elf entered … this turn"
intervening-if).

Reference: game/rules/misc_mixin.py (`request_vote`/`request_object_vote`/
`_advance_expropriate_gain_control`), game/effects/core.py (`VoteEffect`/
`ObjectVoteEffect`/`SetForcedVoterEffect`/`AddCountersEffect.ring_bearer`),
game/static_conditions.py (`another_subtype_entered_this_turn`),
parser/oracle/catalogue/handlers.py, parser/oracle/segmenter.py.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


# --- parse -------------------------------------------------------------------


REAL_CARDS = [
    ("Council Guardian", "Creature — Giant Soldier",
     "Will of the council — When this creature enters, starting with you, each "
     "player votes for blue, black, red, or green. This creature gains "
     "protection from each color with the most votes or tied for most votes."),
    ("Council's Judgment", "Sorcery",
     "Will of the council — Starting with you, each player votes for a nonland "
     "permanent you don't control. Exile each permanent with the most votes or "
     "tied for most votes."),
    ("Custodi Squire", "Creature — Spirit Cleric",
     "Flying\nWill of the council — When this creature enters, starting with "
     "you, each player votes for an artifact, creature, or enchantment card in "
     "your graveyard. Return each card with the most votes or tied for most "
     "votes to your hand."),
    ("Illusion of Choice", "Instant",
     "You choose how each player votes this turn.\nDraw a card."),
    ("Expropriate", "Sorcery",
     "Council's dilemma — Starting with you, each player votes for time or "
     "money. For each time vote, take an extra turn after this one. For each "
     "money vote, choose a permanent owned by the voter and gain control of "
     "it. Exile Expropriate."),
    ("Galadriel, Elven-Queen", "Legendary Creature — Elf Noble",
     "Will of the council — At the beginning of combat on your turn, if another "
     "Elf entered the battlefield under your control this turn, starting with "
     "you, each player votes for dominion or guidance. If dominion gets more "
     "votes, the Ring tempts you, then you put a +1/+1 counter on your "
     "Ring-bearer. If guidance gets more votes or the vote is tied, draw a card."),
]


def _real_card(name, type_line, text):
    tl = type_line.lower()
    # RULE 207.2c ability words ride in Scryfall's `keywords` array just like
    # real keywords; `normalize._strip_unregistered_keyword_labels` needs
    # them there to drop the "Will of the council — " / "Council's dilemma —"
    # label before the ordinary trigger/spell grammar sees the body.
    kw = []
    if "will of the council" in text.lower():
        kw.append("Will of the council")
    if "council's dilemma" in text.lower():
        kw.append("Council's dilemma")
    return Card(
        id=name[:6], name=name, type_line=type_line, oracle_text=text,
        keywords=kw,
        is_creature="creature" in tl,
        is_instant="instant" in tl,
        is_sorcery="sorcery" in tl,
        power="1" if "creature" in tl else None,
        toughness="1" if "creature" in tl else None,
    )


def test_all_mec46_cards_modeled():
    for name, type_line, text in REAL_CARDS:
        r = parse_oracle(_real_card(name, type_line, text))
        assert r.modeled, (name, r.unclaimed)


def test_council_guardian_emits_winner_specs():
    r = match_clause(
        "starting with you, each player votes for blue, black, red, or green. "
        "this creature gains protection from each color with the most votes or "
        "tied for most votes."
    )
    assert r and r[0].type == "vote"
    ws = r[0].params["winner_specs"]
    assert len(ws) == 4
    grant = ws[1][0]
    assert grant["type"] == "grant_until"
    assert grant["params"]["self_subject"] is True
    assert grant["params"]["duration"] == "rest_of_game"
    assert grant["params"]["static"]["params"]["protections"] == ["black"]


def test_council_judgment_and_custodi_squire_emit_vote_object():
    j = match_clause(
        "starting with you, each player votes for a nonland permanent you don't "
        "control. exile each permanent with the most votes or tied for most votes."
    )
    assert j and j[0].type == "vote_object"
    assert j[0].params == {"pool": "nonland_permanents_opponents", "outcome": "exile"}

    s = match_clause(
        "starting with you, each player votes for an artifact, creature, or "
        "enchantment card in your graveyard. return each card with the most "
        "votes or tied for most votes to your hand."
    )
    assert s and s[0].type == "vote_object"
    assert s[0].params["pool"] == "graveyard_cards"
    assert s[0].params["outcome"] == "return_to_hand"
    assert sorted(s[0].params["card_types"]) == ["artifact", "creature", "enchantment"]


def test_expropriate_emits_per_vote_and_self_exile():
    r = match_clause(
        "starting with you, each player votes for time or money. for each time "
        "vote, take an extra turn after this one. for each money vote, choose a "
        "permanent owned by the voter and gain control of it. exile ~."
    )
    assert r and [s.type for s in r] == ["vote", "exile"]
    pv = r[0].params["per_vote_specs"]
    assert pv[0]["effects"][0] == {"type": "take_extra_turn", "params": {"count": 1}}
    assert pv[1] == {"option": 1, "per_voter_gain_control": True}


def test_illusion_of_choice_emits_set_forced_voter():
    r = parse_oracle(_real_card("Illusion of Choice", "Instant",
                                "You choose how each player votes this turn.\nDraw a card."))
    assert r.modeled
    types = [s.type for a in r.specs for s in a.effects]
    assert "set_forced_voter" in types and "draw" in types


def test_galadriel_intervening_if_becomes_trigger_active_if():
    r = parse_oracle(_real_card(*REAL_CARDS[5]))
    assert r.modeled, r.unclaimed
    trig = r.specs[0].trigger
    assert trig["active_if"] == {
        "kind": "another_subtype_entered_this_turn", "subtype": "elf",
    }
    # dominion branch: ring-tempts bare body + "your Ring-bearer" counter
    vote = r.specs[0].effects[0]
    dominion = vote.params["majority_specs"][0]
    assert dominion[0]["type"] == "the_ring_tempts_you"
    assert dominion[1] == {"type": "add_counters",
                           "params": {"count": 1, "kind": "+1/+1", "ring_bearer": True}}


# --- execute ---------------------------------------------------------------------


def _engine(players=2):
    seats = [("p1", "Alice", []), ("p2", "Bob", [])][:players]
    return GameEngine.new_game(seats, starting_life=20, starting_hand=0)


def _put(eng, name, type_line, owner="p1", controller=None, zone=Zone.BATTLEFIELD, **card_kw):
    obj = GameObject(Card(id=name[:8], name=name, type_line=type_line, **card_kw),
                     owner_id=owner, zone=zone)
    obj.controller_id = controller or owner
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.STACK:
        obj.zone = Zone.STACK   # a source reference only; no real stack item
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def test_winner_specs_grants_indefinite_protection_from_every_leader():
    eng = _engine()
    src = _put(eng, "Council Guardian", "Creature — Giant Soldier",
               is_creature=True, power=5, toughness=5)
    eng.rules.request_vote(
        source=src, controller_id="p1", options=["blue", "black", "red", "green"],
        winner_specs=[
            [{"type": "grant_until", "params": {
                "static": {"type": "grant_protection_static",
                           "params": {"protections": [c]}},
                "duration": "rest_of_game", "self_subject": True}}]
            for c in ("blue", "black", "red", "green")
        ],
    )
    eng.resolve_pending_choice("0")   # p1 -> blue
    eng.resolve_pending_choice("2")   # p2 -> red   => blue & red tie for most
    eng.recompute_continuous_effects()
    prot = set(src._granted_protections)   # normalized to WUBRG letters
    assert "U" in prot and "R" in prot
    assert "B" not in prot and "G" not in prot
    # indefinite — survives a cleanup step (RULE 611, no duration)
    assert len(eng.state.floating_statics) == 2
    eng.state.internal_turn.number = 1
    from mtg_analyzer.game import durations
    durations.sweep(eng.state, "cleanup")
    assert len(eng.state.floating_statics) == 2   # not swept


def test_object_vote_exiles_most_voted_nonland_permanent_not_yours():
    eng = _engine()
    src = _put(eng, "Council's Judgment", "Sorcery", zone=Zone.STACK, is_sorcery=True)
    a = _put(eng, "Their Bear", "Creature — Bear", owner="p2", is_creature=True,
             power=2, toughness=2)
    b = _put(eng, "Their Ox", "Creature — Ox", owner="p2", is_creature=True,
             power=2, toughness=2)
    mine = _put(eng, "My Bear", "Creature — Bear", owner="p1", is_creature=True,
                power=2, toughness=2)
    eng.rules.request_object_vote(
        source=src, controller_id="p1",
        candidates=[a, b, mine], outcome="exile", prompt="x",
    )
    eng.resolve_pending_choice(str(a.instance_id))   # p1
    eng.resolve_pending_choice(str(a.instance_id))   # p2  => a wins 2-0
    assert a.zone == Zone.EXILE
    assert b in eng.state.battlefield and mine in eng.state.battlefield


def test_object_vote_returns_most_voted_graveyard_card_to_hand():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, "Custodi Squire", "Creature — Spirit Cleric", is_creature=True,
               power=3, toughness=3)
    relic = _put(eng, "Relic", "Artifact", owner="p1", zone=Zone.GRAVEYARD)
    bear = _put(eng, "Dead Bear", "Creature — Bear", owner="p1", zone=Zone.GRAVEYARD,
                is_creature=True, power=2, toughness=2)
    eng.rules.request_object_vote(
        source=src, controller_id="p1",
        candidates=[relic, bear], outcome="return_to_hand", prompt="x",
    )
    eng.resolve_pending_choice(str(bear.instance_id))
    eng.resolve_pending_choice(str(bear.instance_id))
    assert bear in p1.hand
    assert relic in p1.graveyard


def test_forced_voter_answers_every_ballot_and_clears_at_cleanup():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, "Illusion of Choice", "Instant", zone=Zone.STACK, is_instant=True)
    eng.rules._apply_effect_specs([{"type": "set_forced_voter", "params": {}}], src)
    assert eng.state.forced_vote_controller_id == "p1"

    voter = _put(eng, "Src", "Enchantment")
    eng.rules.request_vote(
        source=voter, controller_id="p1", options=["a", "b"],
        majority_specs=[
            [{"type": "gain_life", "params": {"amount": 7}}],
            [{"type": "gain_life", "params": {"amount": 1}}],
        ],
        tie_index=1,
    )
    # both ballots are addressed to p1 (the forcer), not p1 then p2
    assert eng.state.pending_choice["player_id"] == "p1"
    assert "Bob" in eng.state.pending_choice["prompt"] or "Alice" in eng.state.pending_choice["prompt"]
    eng.resolve_pending_choice("0")
    assert eng.state.pending_choice["player_id"] == "p1"   # p2's ballot, still p1 answers
    eng.resolve_pending_choice("0")
    assert p1.life == 27   # option a won 2-0

    eng._step_cleanup()
    assert eng.state.forced_vote_controller_id is None


def test_expropriate_time_votes_queue_extra_turns():
    eng = _engine()
    src = _put(eng, "Expropriate", "Sorcery", zone=Zone.STACK, is_sorcery=True)
    eng.rules.request_vote(
        source=src, controller_id="p1", options=["time", "money"],
        per_vote_specs=[
            {"option": 0,
             "effects": [{"type": "take_extra_turn", "params": {"count": 1}}],
             "scale": 1},
            {"option": 1, "per_voter_gain_control": True},
        ],
    )
    eng.resolve_pending_choice("0")   # p1 -> time
    eng.resolve_pending_choice("0")   # p2 -> time  => 2 time votes
    assert eng.state.extra_turns.count("p1") == 2


def test_expropriate_money_vote_gains_control_of_a_permanent_the_voter_owns():
    eng = _engine()
    src = _put(eng, "Expropriate", "Sorcery", zone=Zone.STACK, is_sorcery=True)
    rock = _put(eng, "Bob Rock", "Artifact", owner="p2")
    gem = _put(eng, "Bob Gem", "Artifact", owner="p2")
    eng.rules.request_vote(
        source=src, controller_id="p1", options=["time", "money"],
        per_vote_specs=[
            {"option": 0,
             "effects": [{"type": "take_extra_turn", "params": {"count": 1}}],
             "scale": 1},
            {"option": 1, "per_voter_gain_control": True},
        ],
    )
    eng.resolve_pending_choice("1")   # p1 -> money (p1 owns nothing → skipped)
    eng.resolve_pending_choice("1")   # p2 -> money
    # one gain-control pick opens for p1 among the two permanents p2 owns
    assert eng.state.pending_choice["kind"] == "choose_objects"
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(rock.instance_id))
    assert rock.controller_id == "p1" and rock.owner_id == "p2"
    assert gem.controller_id == "p2"   # only one ballot for p2


def test_another_subtype_entered_this_turn_condition():
    from mtg_analyzer.game.static_conditions import condition_holds
    eng = _engine()
    gal = _put(eng, "Galadriel", "Legendary Creature — Elf Noble", is_creature=True,
               power=4, toughness=5)
    cond = {"kind": "another_subtype_entered_this_turn", "subtype": "elf"}
    assert not condition_holds(cond, eng.state, gal, "p1")   # only Galadriel herself

    elf = _put(eng, "Llanowar Elves", "Creature — Elf Druid", is_creature=True,
               power=1, toughness=1)
    elf.turn_entered = eng.state.internal_turn.number
    assert condition_holds(cond, eng.state, gal, "p1")

    elf.turn_entered = eng.state.internal_turn.number - 1   # entered a previous turn
    assert not condition_holds(cond, eng.state, gal, "p1")


def test_ring_bearer_counter_targets_your_ring_bearer():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    src = _put(eng, "Galadriel", "Legendary Creature — Elf Noble", is_creature=True,
               power=4, toughness=5)
    bearer = _put(eng, "Bearer", "Creature — Hobbit", is_creature=True,
                  power=1, toughness=1)
    p1.ring_bearer_id = bearer.instance_id
    eng.rules._apply_effect_specs(
        [{"type": "add_counters", "params": {"count": 1, "kind": "+1/+1",
                                             "ring_bearer": True}}],
        src,
    )
    assert bearer.counters.get("+1/+1") == 1
    assert src.counters.get("+1/+1") in (None, 0)


def test_bot_answers_a_vote_choice_at_random_not_always_option_zero():
    from mtg_analyzer.services.bots import Bot

    answers = [{"type": "choose", "option_id": str(i)} for i in range(4)]
    # A vote view: no decline offered, every option a real choice.
    picks = set()
    for pid in ("bot:a", "bot:b", "bot:c", "bot:d", "bot:e"):
        b = Bot(pid)
        for _ in range(8):
            picks.add(b.answer_choice({"pending_choice": {"kind": "vote"}}, answers)["option_id"])
    assert len(picks) > 1   # spreads across options rather than always "0"

    # Seeded off the id → the same bot replays identically.
    b1, b2 = Bot("bot:x"), Bot("bot:x")
    seq1 = [b1.answer_choice({"pending_choice": {"kind": "vote_object"}}, answers)["option_id"]
            for _ in range(6)]
    seq2 = [b2.answer_choice({"pending_choice": {"kind": "vote_object"}}, answers)["option_id"]
            for _ in range(6)]
    assert seq1 == seq2

    # A non-vote choice still takes the least-change option (decline).
    with_decline = answers + [{"type": "decline"}]
    assert Bot("bot:y").answer_choice(
        {"pending_choice": {"kind": "choose_objects"}}, with_decline
    )["type"] == "decline"


def test_winner_specs_noop_when_no_votes_cast():
    eng = _engine(players=1)
    src = _put(eng, "Council Guardian", "Creature — Giant Soldier",
               is_creature=True, power=5, toughness=5)
    eng.rules.request_vote(
        source=src, controller_id="p1", options=["blue", "red"],
        winner_specs=[None, None],
    )
    eng.resolve_pending_choice("0")   # sole player votes blue
    eng.recompute_continuous_effects()
    # winner_specs entries are None -> nothing granted, no crash
    assert not src._granted_protections
