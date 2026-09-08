"""MEC-50 — Clash (RULE 701.30) win/otherwise-branch residue: the six
primitive-blocked singletons the parser grammar (v147–v154) left behind.

Each needed a genuinely new engine primitive, not parser grammar:

- **Hoarder's Greed** — `RepeatProcessEffect`: "`<process>`, then clash. If
  you win, repeat this process." loops the whole process (capped at
  `_MAX_CLASH_REPEAT_ITERATIONS`).
- **Broken Ambitions** — `MillEffect.selector="previous_subject_controller"`:
  "that spell's controller mills four" reads the countered spell's
  `owner_id` off `GameContext.previous_targets[0]` (RULE 608.2h).
- **Whirlpool Whelm** — `ReturnToHandEffect.to_library_top_if_clash_won`:
  the bounce's destination is overridden to library-top on a win (the
  clash resolves first, so `context.clash_won` is already set).
- **Captivating Glance** — `GainControlAttachedEffect(recipient)`: an
  indefinite control change of the Aura's host to the controller (win) or
  `GameContext.clashed_opponent` (otherwise).
- **Pulling Teeth** — `DiscardEffect.previous_subject`: "that player" in
  the otherwise branch is the same player the win branch RULE 115-targeted.
- **Pollen Lullaby** — `SkipNextUntapEffect.subject="clashed_opponent"`:
  flags every creature the clashed opponent controls.

The shared load-bearing piece is `GameContext.clashed_opponent`, recorded
by `RulesEngine.clash` (`_last_clash_opponent_id`) and stashed by
`ClashEffect`, with the same save/reset/restore in
`_apply_effects_partitioned` as `clash_won`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _lib(state, pid, mv):
    """Put one MV-`mv` card on top of `pid`'s library and return it."""
    obj = GameObject(Card(id=f"{pid}top{mv}", name=f"Top{mv}", type_line="Sorcery",
                          is_sorcery=True, converted_mana_cost=mv),
                     owner_id=pid, zone=Zone.LIBRARY)
    state.player_by_id(pid).add_to_zone(obj, Zone.LIBRARY)
    return obj


def _rig_clash(state, *, p1_wins: bool):
    _lib(state, "p1", 6 if p1_wins else 1)
    _lib(state, "p2", 1 if p1_wins else 6)


def _spec_source(eng, name, zone=Zone.STACK):
    src = GameObject(_db().get_card(name), owner_id="p1", zone=zone)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    return src


def _run(eng, src, specs, targets=None):
    effs = build_effects(specs, src)
    _apply_effects_partitioned(effs, eng.rules.context, targets, None, source=src)


# --- all six are MODELED -----------------------------------------------------


def test_all_six_modeled():
    db = _db()
    for name in ("Hoarder's Greed", "Broken Ambitions", "Whirlpool Whelm",
                 "Captivating Glance", "Pulling Teeth", "Pollen Lullaby"):
        card = db.get_card(name)
        assert card is not None, name
        assert parse_oracle(card).coverage != UNMODELED, (name, parse_oracle(card).unclaimed)


# --- Hoarder's Greed -------------------------------------------------------------


def test_hoarders_greed_loops_the_process_while_clashes_win():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    # p2's library empty → p1 wins every clash while it still has a card of
    # its own (RULE 701.30b). 8 cards, 2 drawn per pass: passes 1–3 win,
    # pass 4 draws the last 2 then clashes with an empty library → loss → stop.
    for _ in range(8):
        _lib(st, "p1", 1)
    life0 = p1.life
    src = _spec_source(eng, "Hoarder's Greed")
    spec = parse_oracle(src.card).specs[0].effects[0]
    _run(eng, src, [spec])
    assert p1.life == life0 - 8   # 4 passes, 2 life each
    assert len(p1.hand) == 8      # 4 passes, 2 cards each


def test_hoarders_greed_is_capped():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    p1.life = 500  # survive the whole cap
    for _ in range(80):
        _lib(st, "p1", 6)   # every clash wins
        _lib(st, "p2", 1)
    src = _spec_source(eng, "Hoarder's Greed")
    _run(eng, src, [parse_oracle(src.card).specs[0].effects[0]])
    from mtg_analyzer.game.effects.core import _MAX_CLASH_REPEAT_ITERATIONS
    assert p1.life == 500 - 2 * _MAX_CLASH_REPEAT_ITERATIONS


# --- Broken Ambitions -----------------------------------------------------------


def test_broken_ambitions_mills_the_countered_spells_owner_on_win():
    eng = _engine()
    st = eng.state
    p2 = st.player_by_id("p2")
    for _ in range(6):
        p2.library.append(GameObject(Card(id=f"pl{_}", name=f"L{_}", type_line="Plains",
                                          is_land=True), owner_id="p2", zone=Zone.LIBRARY))
    # p2's spell on the stack (bare object — the counter is what's under test)
    from mtg_analyzer.models.game.game_state import StackItem
    spell = GameObject(Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
                       owner_id="p2", zone=Zone.STACK)
    spell.controller_id = "p2"
    st.stack.append(StackItem(kind="spell", controller_id="p2", obj=spell,
                              description="Bolt", effects=[]))
    _rig_clash(st, p1_wins=True)

    src = _spec_source(eng, "Broken Ambitions")
    src.x_paid = 5  # p2 holds no mana → can't pay {5} → spell is countered
    specs = parse_oracle(src.card).specs[0].effects
    _run(eng, src, specs, targets=[spell])

    assert spell not in [i.obj for i in st.stack]     # countered
    assert len(p2.graveyard) == 4 + 1                 # milled 4 (+ the countered Bolt)


# --- Whirlpool Whelm ----------------------------------------------------------


def test_whirlpool_whelm_bounces_to_hand_on_loss_library_on_win():
    for win, in_hand in ((False, True), (True, False)):
        eng = _engine()
        st = eng.state
        p2 = st.player_by_id("p2")
        creature = GameObject(Card(id="ogre", name="Ogre", type_line="Creature — Ogre",
                                   is_creature=True, power=3, toughness=3),
                              owner_id="p2", zone=Zone.BATTLEFIELD)
        creature.controller_id = "p2"
        st.add_to_battlefield(creature)
        _rig_clash(st, p1_wins=win)

        src = _spec_source(eng, "Whirlpool Whelm")
        _run(eng, src, parse_oracle(src.card).specs[0].effects, targets=[creature])

        assert creature not in st.battlefield
        assert (creature in p2.hand) is in_hand
        assert (creature in p2.library) is (not in_hand)


# --- Captivating Glance -----------------------------------------------------------


def test_captivating_glance_control_goes_to_winner():
    for win, new_ctrl in ((True, "p1"), (False, "p2")):
        eng = _engine()
        st = eng.state
        host = GameObject(Card(id="bear", name="Bear", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
        host.controller_id = "p2"
        st.add_to_battlefield(host)
        aura = _spec_source(eng, "Captivating Glance", zone=Zone.BATTLEFIELD)
        aura.attached_to = host.instance_id
        st.add_to_battlefield(aura)
        _rig_clash(st, p1_wins=win)

        trig = next(s for s in parse_oracle(aura.card).specs if s.ability_kind == "triggered")
        _run(eng, aura, trig.effects)
        assert host.controller_id == new_ctrl


# --- Pulling Teeth ------------------------------------------------------------


def test_pulling_teeth_win_discards_two_otherwise_that_player_discards_one():
    for win, expected in ((True, 2), (False, 1)):
        eng = _engine()
        st = eng.state
        p2 = st.player_by_id("p2")
        for i in range(3):
            p2.hand.append(GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Instant",
                                           is_instant=True), owner_id="p2", zone=Zone.HAND))
        _rig_clash(st, p1_wins=win)
        src = _spec_source(eng, "Pulling Teeth")
        specs = parse_oracle(src.card).specs[0].effects
        _run(eng, src, specs, targets=[p2])

        guard = 0
        while st.pending_choice and guard < 6:
            guard += 1
            opt = st.pending_choice["options"][0]
            eng.rules.resolve_choose_objects_choice(opt["instance_id"])
        assert len(p2.graveyard) == expected


# --- bonus family: "that player discards a card" off a trigger event -----------


def test_that_player_discards_reads_the_damage_events_player():
    # Abyssal Specter — "whenever ~ deals damage to a player, that player
    # discards a card." No RULE 115 target, so `previous_subject` falls back
    # to the DAMAGE event's recipient.
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    for i in range(2):
        p2.hand.append(GameObject(Card(id=f"h{i}", name=f"H{i}", type_line="Instant",
                                       is_instant=True), owner_id="p2", zone=Zone.HAND))
    spec = GameObject(_db().get_card("Abyssal Specter"), owner_id="p1", zone=Zone.BATTLEFIELD)
    spec.controller_id = "p1"
    bind_from_catalogue(spec)
    st.add_to_battlefield(spec)

    from mtg_analyzer.models.game.events import EventType, GameEvent
    ev = GameEvent(EventType.DAMAGE, target_id="p2", is_player=True,
                   instance_id=spec.instance_id, controller_id="p1")
    eng.rules.context.trigger_event = ev
    trig = next(s for s in parse_oracle(spec.card).specs if s.ability_kind == "triggered")
    build_effects(trig.effects, spec)[0].apply(eng.rules.context, None)
    eng.rules.context.trigger_event = None

    guard = 0
    while st.pending_choice and guard < 5:
        guard += 1
        eng.rules.resolve_choose_objects_choice(st.pending_choice["options"][0]["instance_id"])
    assert len(p2.graveyard) == 1  # p2 (the damaged player) discarded, not p1


# --- Pollen Lullaby ---------------------------------------------------------------


def test_pollen_lullaby_clashed_opponent_creatures_dont_untap_on_win():
    eng = _engine()
    st = eng.state
    p2 = st.player_by_id("p2")
    mine = GameObject(Card(id="myc", name="Mine", type_line="Creature — Bear",
                           is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    theirs = GameObject(Card(id="thc", name="Theirs", type_line="Creature — Bear",
                             is_creature=True, power=1, toughness=1),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    theirs.controller_id = "p2"
    st.add_to_battlefield(mine)
    st.add_to_battlefield(theirs)
    _rig_clash(st, p1_wins=True)

    src = _spec_source(eng, "Pollen Lullaby")
    _run(eng, src, parse_oracle(src.card).specs[0].effects)

    assert getattr(theirs, "skip_next_untap", False) is True
    assert getattr(mine, "skip_next_untap", False) is False
