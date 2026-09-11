"""Incubate (RULE 701.53) residue — the three cache singletons the PAR-30
parser trail left, now hand-authored in `ability_catalogue/special_mechanics.py`
(docs/Reference/11 escape valve). Each was blocked on its own bespoke
shape, not on incubate grammar (v160/v162 shipped that):

- **Traumatic Revelation** — "you may choose … If you don't, incubate 3.":
  an *else*-branch on an optional `reveal_hand_choose_discard`. New
  ``optional`` + ``else_specs`` on the effect, threaded through
  `_request_choose_objects`' new ``else_specs`` (mirror of ``then_specs``,
  fires only when nothing is picked / the pool is empty). "battle" joins
  the effect's ``card_types`` filter.
- **Phyrexian Incubator** — "incubate 2 **that many times**", the count
  being how many cards the search exiled, across the RULE 608.2
  pending-choice suspension. `SearchLibraryEffect(track_exiled_with=True)`
  parks the exiled ids on the source's own `GameObject.exiled_with_ids`
  (survives suspend/resume — it's on the permanent, not the
  `GameContext`); the following `create_token` reads it back with
  ``count_selector="exiled_with_count"``.
- **Progenitor Exarch** — "incubate 3 **X times**", X = the source's own
  announced {X} (`GameObject.x_paid`). New `continuous.count_selector`
  key ``"source_x_paid"``. Plus "{T}: Transform target Incubator token
  you control" — the `Incubator` token's own `grant_until`/``type_change``
  transform shape with a RULE 115 target (new
  ``incubator_token_you_control`` target kind).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered, specs_for


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _phyrexian_creature(name):
    return Card(id=name[:8], name=name, type_line="Creature — Phyrexian Horror",
                is_creature=True, power=1, toughness=1)


def _tokens(state):
    return [o for o in state.battlefield if getattr(o, "is_token", False)]


# --- all three are registered, and the parser still (correctly) can't claim them


def test_all_three_are_hand_authored_not_parsed():
    db = _db()
    for name in ("Traumatic Revelation", "Phyrexian Incubator", "Progenitor Exarch"):
        assert is_registered(name), name
        card = db.get_card(name)
        assert card is not None, name
        # hand-authoring does not move the parser verdict — it stays UNMODELED
        assert parse_oracle(card).coverage == UNMODELED, name
        assert specs_for(card), name


# --- Traumatic Revelation -------------------------------------------------------


def test_traumatic_revelation_else_branch_incubates_when_no_card_chosen():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    # p2's hand has only a land — no creature/battle card to choose, so
    # "if you don't" fires.
    land = GameObject(Card(id="waste", name="Wastes", type_line="Basic Land", is_land=True),
                      owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(land, Zone.HAND)

    src = GameObject(_db().get_card("Traumatic Revelation"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    effects = build_effects(specs_for(src.card)[0].effects, src)
    effects[0].apply(GameContext(st, eng.rules), [p2])

    toks = _tokens(st)
    assert len(toks) == 1 and toks[0].name == "Incubator"
    assert toks[0].counters.get("+1/+1") == 3
    assert land in p2.hand  # nothing discarded


def test_traumatic_revelation_discards_the_chosen_creature_card():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    bearcard = Card(id="bear", name="Bear", type_line="Creature — Bear",
                    is_creature=True, power=2, toughness=2)
    bear = GameObject(bearcard, owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(bear, Zone.HAND)

    src = GameObject(_db().get_card("Traumatic Revelation"), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    effects = build_effects(specs_for(src.card)[0].effects, src)
    effects[0].apply(GameContext(st, eng.rules), [p2])

    # an object choice is now pending on p1; pick the bear
    choice = st.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    eng.rules.resolve_choice(bear.instance_id)

    assert bear in p2.graveyard
    assert not _tokens(st)  # the else-branch did NOT fire


# --- Phyrexian Incubator ------------------------------------------------------


def test_phyrexian_incubator_incubates_once_per_exiled_card():
    incard = _db().get_card("Phyrexian Incubator")
    phyr = [_phyrexian_creature(f"Phyrexian {i}") for i in range(3)]
    junk = [Card(id=f"j{i}", name=f"Bear {i}", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2) for i in range(2)]
    eng = GameEngine.new_game([("p1", "Alice", phyr + junk)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    inc = GameObject(incard, owner_id="p1", zone=Zone.BATTLEFIELD)
    inc.summoning_sick = False
    bind_from_catalogue(inc)
    eng.state.add_to_battlefield(inc)
    p1.mana_pool.add("C", 3)

    eng.activate_ability(p1, inc, 0)
    eng.resolve_until_stable()

    # pick every Phyrexian card, then decline
    guard = 0
    while eng.state.pending_choice is not None and guard < 20:
        guard += 1
        choice = eng.state.pending_choice
        assert choice["kind"] == "search"
        elig = [e for e in choice["eligible"] if e["name"].startswith("Phyrexian")]
        if elig:
            eng.rules.resolve_choice(elig[0]["instance_id"])
        else:
            eng.rules.resolve_choice(None)  # decline
    eng.resolve_until_stable()

    toks = _tokens(eng.state)
    assert len(toks) == 3, [t.name for t in toks]
    assert all(t.name == "Incubator" and t.counters.get("+1/+1") == 2 for t in toks)
    assert sum(1 for c in p1.exile if c.name.startswith("Phyrexian")) == 3
    assert inc not in eng.state.battlefield  # sacrificed as a cost
    assert any(e.type == EventType.SHUFFLE for e in eng.state.event_log)


def test_phyrexian_incubator_makes_no_token_when_nothing_found():
    incard = _db().get_card("Phyrexian Incubator")
    junk = [Card(id=f"j{i}", name=f"Bear {i}", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2) for i in range(3)]
    eng = GameEngine.new_game([("p1", "Alice", junk)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    inc = GameObject(incard, owner_id="p1", zone=Zone.BATTLEFIELD)
    inc.summoning_sick = False
    bind_from_catalogue(inc)
    eng.state.add_to_battlefield(inc)
    p1.mana_pool.add("C", 3)

    eng.activate_ability(p1, inc, 0)
    eng.resolve_until_stable()
    guard = 0
    while eng.state.pending_choice is not None and guard < 10:
        guard += 1
        eng.rules.resolve_choice(None)
    eng.resolve_until_stable()

    # RULE 701.53a: incubate 0 times = no Incubator token at all
    assert not _tokens(eng.state)


# --- Progenitor Exarch -------------------------------------------------------


def test_progenitor_exarch_incubates_x_times_off_source_x_paid():
    eng = _engine()
    st = eng.state
    src = GameObject(_db().get_card("Progenitor Exarch"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.x_paid = 2
    bind_from_catalogue(src)
    st.add_to_battlefield(src)

    etb = next(s for s in specs_for(src.card) if s.ability_kind == "triggered")
    build_effects(etb.effects, src)[0].apply(GameContext(st, eng.rules), None)

    toks = _tokens(st)
    assert len(toks) == 2, [t.name for t in toks]
    assert all(t.name == "Incubator" and t.counters.get("+1/+1") == 3 for t in toks)


def test_progenitor_exarch_x_zero_makes_no_token():
    eng = _engine()
    st = eng.state
    src = GameObject(_db().get_card("Progenitor Exarch"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.x_paid = 0
    bind_from_catalogue(src)
    st.add_to_battlefield(src)

    etb = next(s for s in specs_for(src.card) if s.ability_kind == "triggered")
    build_effects(etb.effects, src)[0].apply(GameContext(st, eng.rules), None)
    assert not _tokens(st)


def _make_incubator(eng, controller):
    maker = GameObject(_phyrexian_creature("maker"), owner_id=controller, zone=Zone.BATTLEFIELD)
    maker.controller_id = controller
    eng.state.add_to_battlefield(maker)
    build_effects([EffectSpec("create_token", {
        "token_name": "Incubator", "extra_counters": {"kind": "+1/+1", "count": 3},
    })], maker)[0].apply(GameContext(eng.state, eng.rules), None)
    return [o for o in eng.state.battlefield
            if getattr(o, "is_token", False) and o.controller_id == controller][-1]


def test_progenitor_exarch_transform_targets_only_your_incubator_tokens():
    eng = _engine()
    st = eng.state
    src = GameObject(_db().get_card("Progenitor Exarch"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    st.add_to_battlefield(src)

    mine = _make_incubator(eng, "p1")
    theirs = _make_incubator(eng, "p2")

    ids = {
        t["instance_id"]
        for t in legal_targets(st, "p1", TargetSpec(kind="incubator_token_you_control"))
    }
    assert ids == {mine.instance_id}

    act = next(s for s in specs_for(src.card) if s.ability_kind == "activated")
    build_effects(act.effects, src)[0].apply(GameContext(st, eng.rules), [mine])
    eng.recompute_continuous_effects()

    assert mine.is_creature
    assert not theirs.is_creature
