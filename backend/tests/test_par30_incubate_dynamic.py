"""PAR-30 — "Incubate X, where X is `<count>`" dynamic amount.

`_incubate` (RULE 701.53, PAR-29) only handled a literal "incubate N". The
"…where X is …" forms real cards print resolve X fresh at incubate time:

- a board count (`continuous.count_selector`) — "the number of lands you
  control" (Glistening Dawn), "the number of creature cards in your
  graveyard" (Blight Titan). New `count_from_count_selector` key on
  `CreateTokenEffect.extra_counters`; `creature_cards_in_your_graveyard`
  added to `continuous.count_selector`.
- the firing spell's mana value — "…where X is that spell's mana value"
  (Chrome Host Seedshark). New `count_from_trigger_event` key.
- "incubate X **twice**" — two Incubator tokens, each with X counters,
  which is just `create_token`'s own `count=2`.
- "…where X is **its power**" (Bloated Processor, Furnace Gremlin) — a
  "when ~ dies" trigger; the DIES event carries the dying creature's own
  last-known `power` snapshot (RULE 400.7 / 603.6e), read via
  `CreateTokenEffect.extra_counters`' existing `count_from_trigger_event`
  key — the same firing-event idiom `EarthbendEffect` uses for
  "earthbend X, where X is that creature's power".
- "**Its controller** incubates X, where X is **its mana value**" (Excise
  the Imperfect) — `create_token`'s new `creators="previous_target_
  controller"` (the token's creator is whoever controlled the just-exiled
  previous target) + `extra_counters`' new `count_from_subject=
  "previous_subject_mana_value"` (RULE 608.2h last-known info — the
  permanent is already gone). Also needed the plain exile handler to
  accept `nonland_permanent` (a real `targeting` kind it never reached).
- "…where X is the number of creatures **exiled this way**" (Sunfall) —
  `extra_counters`' new `count_from_context="objects_exiled_this_way"`, a
  new `GameContext` same-resolution accumulator (sibling of
  `permanents_destroyed_this_way`) bumped by `context.exile`.

The parser still (by design) can't claim two shapes — "incubate N **that
many times**" (Phyrexian Incubator) and "incubate N **X times**"
(Progenitor Exarch) — but both cards, plus Traumatic Revelation's
"if you don't, incubate 3" else-branch, are now **hand-authored** in
`ability_catalogue/entries_016.py`; see
`tests/test_incubate_residue_authored.py` for their end-to-end coverage.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )


def _bear(name="Bear"):
    return Card(id=name[:6], name=name, type_line="Creature — Bear",
               is_creature=True, power=2, toughness=2)


# --- parse ------------------------------------------------------------------


def test_incubate_x_board_count_selector_parses():
    card = Card(id="gld", name="Glistening Dawn", type_line="Sorcery",
                is_sorcery=True, mana_cost_string="{5}{G}{G}",
                oracle_text="Incubate X twice, where X is the number of lands you control.")
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    spec = r.specs[0].effects[0]
    assert spec.type == "create_token"
    assert spec.params["count"] == 2
    assert spec.params["extra_counters"] == {
        "kind": "+1/+1", "count_from_count_selector": "lands_you_control",
    }


def test_incubate_x_creature_cards_in_graveyard_parses():
    card = Card(id="bt", name="Blight Titan",
                type_line="Creature — Phyrexian Horror", is_creature=True,
                power=5, toughness=5, mana_cost_string="{4}{B}{B}",
                oracle_text=("Whenever Blight Titan enters or attacks, mill two "
                             "cards, then incubate X, where X is the number of "
                             "creature cards in your graveyard."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    types = [e.type for e in r.specs[0].effects]
    assert types == ["mill", "create_token"]
    assert r.specs[0].effects[1].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_count_selector": "creature_cards_in_your_graveyard",
    }


def test_incubate_x_that_spells_mana_value_parses():
    card = Card(id="chs", name="Chrome Host Seedshark",
                type_line="Creature — Phyrexian", is_creature=True,
                power=1, toughness=4, mana_cost_string="{2}{U}",
                oracle_text=("Whenever you cast a noncreature spell, incubate X, "
                             "where X is that spell's mana value."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    assert r.specs[0].effects[0].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_trigger_event": "mana_value",
    }


def test_incubate_x_its_power_parses():
    card = Card(id="bp", name="Bloated Processor",
                type_line="Creature — Phyrexian Insect", is_creature=True,
                power=3, toughness=3, mana_cost_string="{3}{B}",
                oracle_text=("Sacrifice another Phyrexian: Put a +1/+1 counter on "
                             "this creature.\nWhen Bloated Processor dies, incubate "
                             "X, where X is its power."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    dies = next(s for s in r.specs
                if s.trigger and s.trigger.get("event") == "DIES")
    assert dies.effects[0].type == "create_token"
    assert dies.effects[0].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_trigger_event": "power",
    }


def test_incubate_x_its_controllers_mana_value_parses():
    card = Card(id="exc", name="Excise the Imperfect", type_line="Instant",
                is_instant=True, mana_cost_string="{1}{W}{B}",
                oracle_text=("Exile target nonland permanent. Its controller "
                             "incubates X, where X is its mana value."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    types = [e.type for e in r.specs[0].effects]
    assert types == ["exile", "create_token"]
    tok = r.specs[0].effects[1].params
    assert tok["creators"] == "previous_target_controller"
    assert tok["extra_counters"] == {
        "kind": "+1/+1", "count_from_subject": "previous_subject_mana_value",
    }


def test_incubate_x_creatures_exiled_this_way_parses():
    card = Card(id="sf", name="Sunfall", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{3}{W}{W}",
                oracle_text=("Exile all creatures. Incubate X, where X is the "
                             "number of creatures exiled this way."))
    r = parse_oracle(card)
    assert r.coverage != UNMODELED, r.unclaimed
    types = [e.type for e in r.specs[0].effects]
    assert types == ["exile", "create_token"]
    assert r.specs[0].effects[1].params["extra_counters"] == {
        "kind": "+1/+1", "count_from_context": "objects_exiled_this_way",
    }


def test_incubate_x_that_many_times_not_claimed_by_the_parser():
    # "that many times" (a search-result repeat count) is deliberately not
    # parser grammar — Phyrexian Incubator is hand-authored instead
    # (tests/test_incubate_residue_authored.py). The parser still fails
    # closed on the synthetic clause.
    card = Card(id="pi", name="Phyrexian Incubator synthetic", type_line="Artifact",
                mana_cost_string="{4}",
                oracle_text=("{3}, {T}, Sacrifice ~: Search your "
                             "library for any number of Phyrexian cards, exile them, "
                             "then incubate 2 that many times. Then shuffle."))
    assert parse_oracle(card).coverage == UNMODELED


# --- execute --------------------------------------------------------------


def test_incubate_x_places_a_live_graveyard_count_of_counters():
    eng = _engine()
    st = eng.state
    for i in range(3):
        st.players[0].graveyard.append(
            GameObject(_bear(f"GY{i}"), owner_id="p1", zone=Zone.GRAVEYARD)
        )
    # a noncreature card in the graveyard must not be counted
    st.players[0].graveyard.append(
        GameObject(Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True),
                   owner_id="p1", zone=Zone.GRAVEYARD)
    )

    src = GameObject(Card(id="bt", name="Blight Titan", type_line="Creature — Phyrexian",
                          is_creature=True, power=5, toughness=5),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    build_effects([EffectSpec("create_token", {
        "count": 1, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1",
                           "count_from_count_selector": "creature_cards_in_your_graveyard"},
    })], src)[0].apply(GameContext(st, eng.rules), None)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].counters.get("+1/+1") == 3


def test_incubate_x_twice_makes_two_tokens_each_sized_to_the_count():
    eng = _engine()
    st = eng.state
    # give p1 four lands
    for i in range(4):
        land = GameObject(Card(id=f"F{i}", name="Forest", type_line="Basic Land — Forest",
                               is_land=True),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
        land.controller_id = "p1"
        st.add_to_battlefield(land)

    src = GameObject(Card(id="gld", name="Glistening Dawn", type_line="Sorcery",
                          is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("create_token", {
        "count": 2, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count_from_count_selector": "lands_you_control"},
    })], src)[0].apply(GameContext(st, eng.rules), None)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 2
    assert all(t.counters.get("+1/+1") == 4 for t in tokens)


def test_incubate_x_its_power_reads_the_dies_events_last_known_power():
    eng = _engine()
    st = eng.state

    proc = GameObject(
        Card(id="BP", name="Bloated Processor",
             type_line="Creature — Phyrexian Insect", is_creature=True,
             power=3, toughness=3,
             oracle_text=("Sacrifice another Phyrexian: Put a +1/+1 counter on this "
                          "creature.\nWhen Bloated Processor dies, incubate X, where "
                          "X is its power.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    proc.controller_id = "p1"
    st.add_to_battlefield(proc)
    bind_from_catalogue(proc)

    # grew a counter while on the battlefield → last-known power is 4
    proc.counters["+1/+1"] = 1
    eng.recompute_continuous_effects()
    assert proc.power == 4

    eng.rules.destroy(proc)
    eng.resolve_until_stable()

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].counters.get("+1/+1") == 4


def test_incubate_x_its_power_zero_still_makes_the_incubator_token():
    # RULE 701.53a: Incubate X creates an Incubator token even when X is 0.
    eng = _engine()
    st = eng.state
    src = GameObject(Card(id="Z", name="Zero", type_line="Creature — Wall",
                          is_creature=True, power=0, toughness=4),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    ctx = GameContext(st, eng.rules)
    ctx.trigger_event = GameEvent(EventType.DIES, power=0)

    build_effects([EffectSpec("create_token", {
        "count": 1, "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count_from_trigger_event": "power"},
    })], src)[0].apply(ctx, None)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].counters.get("+1/+1", 0) == 0


def test_excise_the_imperfect_incubates_for_the_victims_controller_and_mv():
    eng = _engine()
    st = eng.state

    victim = GameObject(
        Card(id="OGRE", name="Ogre", type_line="Creature — Ogre", is_creature=True,
             power=3, toughness=3, converted_mana_cost=4),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p2"
    st.add_to_battlefield(victim)

    src = GameObject(Card(id="EXC", name="Excise the Imperfect", type_line="Instant",
                          is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    from mtg_analyzer.game.effects import _apply_effects_partitioned
    effects = build_effects([
        EffectSpec("exile", {"target_kind": "nonland_permanent"}),
        EffectSpec("create_token", {
            "count": 1, "token_name": "Incubator",
            "creators": "previous_target_controller",
            "extra_counters": {"kind": "+1/+1",
                               "count_from_subject": "previous_subject_mana_value"},
        }),
    ], src)
    _apply_effects_partitioned(effects, eng.rules.context, [victim], None, source=src)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].controller_id == "p2"          # the victim's controller
    assert tokens[0].counters.get("+1/+1") == 4     # the victim's mana value
    assert victim not in st.battlefield


def test_sunfall_incubates_for_the_number_of_creatures_it_exiled():
    eng = _engine()
    st = eng.state
    for i, pid in enumerate(("p1", "p2", "p2")):
        c = GameObject(Card(id=f"C{i}", name=f"Bear{i}", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2),
                       owner_id=pid, zone=Zone.BATTLEFIELD)
        c.controller_id = pid
        st.add_to_battlefield(c)

    src = GameObject(Card(id="SF", name="Sunfall", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    from mtg_analyzer.game.effects import _apply_effects_partitioned
    effects = build_effects([
        EffectSpec("exile", {"selector": "all_creatures"}),
        EffectSpec("create_token", {
            "count": 1, "token_name": "Incubator",
            "extra_counters": {"kind": "+1/+1",
                               "count_from_context": "objects_exiled_this_way"},
        }),
    ], src)
    _apply_effects_partitioned(effects, eng.rules.context, None, None, source=src)

    assert not [o for o in st.battlefield if o.is_creature and not o.is_token]
    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert tokens[0].counters.get("+1/+1") == 3


def test_objects_exiled_this_way_resets_between_resolutions():
    # the accumulator must not leak from one _apply_effects_partitioned run
    # into the next (Sunfall cast twice in a game shouldn't compound)
    eng = _engine()
    st = eng.state
    src = GameObject(Card(id="SF2", name="Sunfall", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    from mtg_analyzer.game.effects import _apply_effects_partitioned
    for _ in range(2):
        c = GameObject(Card(id="ZZ", name="Z", type_line="Creature — Bear",
                            is_creature=True, power=1, toughness=1),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
        c.controller_id = "p1"
        st.add_to_battlefield(c)
        effects = build_effects([
            EffectSpec("exile", {"selector": "all_creatures"}),
            EffectSpec("create_token", {
                "count": 1, "token_name": "Incubator",
                "extra_counters": {"kind": "+1/+1",
                                   "count_from_context": "objects_exiled_this_way"},
            }),
        ], src)
        _apply_effects_partitioned(effects, eng.rules.context, None, None, source=src)

    tokens = [o for o in st.battlefield if getattr(o, "is_token", False)]
    assert [t.counters.get("+1/+1") for t in tokens] == [1, 1]
