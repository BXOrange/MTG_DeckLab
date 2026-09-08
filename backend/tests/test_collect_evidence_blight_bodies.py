"""PAR-30 — Collect Evidence / Forage / Blight *activated-body* residue,
sub-cluster (b).

Three keyword-action cost fragments (`collect evidence N`, `blight N`,
`forage`) were missing from `segmenter._COST_LOOKS_REAL`, so
`{cost}, collect evidence N: <body>` / `{T}, Blight 1: <body>` never even
reached the activated-ability handler. Adding them unblocked the bodies:

- **exile enchanted creature** — `ExileEffect`'s new ``attached_permanent``
  self-acting mode (no RULE 115 target), the sibling of the same mode on
  `TapEffect`/`PumpEffect`. Handler `exile_attached`. Also unlocks a whole
  Aura family ("Enchanted creature can't attack or block. {cost}: Exile
  enchanted creature." — Dreadful Apathy, Cooped Up, Choking Restraints …).
- **discard a card. If you do, `<effect>`** — `segmenter.
  _DISCARD_THEN_IF_YOU_DO_RE`, collapsing a bare mandatory discard + its
  reflexive tail to a plain sequence (Gristle Glutton's loot).
- **each opponent loses N life unless they discard a card or sacrifice a
  creature** — `_EACH_PLAYER_LOSE_LIFE_UNLESS_RE` widened to "each
  opponent" (`scope="each_opponent"`) and the OR cost form
  (`EachPlayerPayOrEffect.sacrifice_or_discard`) for Polygraph Orb.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
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


# --- parse -----------------------------------------------------------------


def test_keyword_action_activated_bodies_now_modeled():
    db = _db()
    for name in ("Gristle Glutton", "Spiral into Solitude", "Polygraph Orb",
                 "Dreadful Apathy"):
        card = db.get_card(name)
        assert card is not None, name
        assert parse_oracle(card).coverage != UNMODELED, (name, parse_oracle(card).unclaimed)


def test_hedge_whisperer_is_hand_authored():
    from mtg_analyzer.game.ability_catalogue import is_registered, specs_for
    card = _db().get_card("Hedge Whisperer")
    assert card is not None and is_registered("Hedge Whisperer")
    kinds = sorted(s.ability_kind for s in specs_for(card))
    assert kinds == ["activated", "static"]


def test_feed_the_cycle_forage_additional_cost():
    # "As an additional cost to cast this spell, forage or pay {B}." — the
    # forage half is modeled (`additional_cost={"forage": True}`), the
    # "or pay {B}" alternative is the documented drop behold/blight share.
    r = parse_oracle(_db().get_card("Feed the Cycle"))
    assert r.coverage != UNMODELED, r.unclaimed
    carrier = next(s for s in r.specs if s.additional_cost is not None)
    assert carrier.additional_cost == {"forage": True}
    assert any(e.type == "destroy" for s in r.specs for e in s.effects)


def test_polygraph_orb_scope_and_or_cost():
    spec = next(
        s for s in parse_oracle(_db().get_card("Polygraph Orb")).specs
        if s.ability_kind == "activated"
    )
    p = spec.effects[0].params
    assert spec.effects[0].type == "each_player_pay_or"
    assert p["scope"] == "each_opponent"
    assert p["sacrifice_or_discard"] is True
    assert p["effects"][0]["params"]["amount"] == 3


# --- execute -------------------------------------------------------------------


def test_exile_attached_exiles_the_hosts_creature():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    host = GameObject(Card(id="ogre", name="Ogre", type_line="Creature — Ogre",
                           is_creature=True, power=3, toughness=3),
                      owner_id="p2", zone=Zone.BATTLEFIELD)
    host.controller_id = "p2"
    st.add_to_battlefield(host)

    aura = GameObject(_db().get_card("Dreadful Apathy"), owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    aura.attached_to = host.instance_id
    bind_from_catalogue(aura)
    st.add_to_battlefield(aura)

    act = next(s for s in parse_oracle(aura.card).specs if s.ability_kind == "activated")
    build_effects(act.effects, aura)[0].apply(GameContext(st, eng.rules), None)

    assert host not in st.battlefield
    assert host in p2.exile


def test_gristle_glutton_discard_then_draw_sequence():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    # two cards in hand so the discard has something to spend
    for i in range(2):
        p1.hand.append(GameObject(Card(id=f"h{i}", name=f"Card{i}", type_line="Instant",
                                       is_instant=True), owner_id="p1", zone=Zone.HAND))
    p1.library.append(GameObject(Card(id="top", name="Top", type_line="Instant",
                                      is_instant=True), owner_id="p1", zone=Zone.LIBRARY))

    src = GameObject(_db().get_card("Gristle Glutton"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    st.add_to_battlefield(src)

    act = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "activated")
    assert [e.type for e in act.effects] == ["discard", "draw"]
    for e in build_effects(act.effects, src):
        e.apply(GameContext(st, eng.rules), None)
        guard = 0
        while st.pending_choice and st.pending_choice["kind"] == "choose_objects" and guard < 5:
            guard += 1
            cid = st.pending_choice["options"][0]["instance_id"]
            eng.rules.resolve_choose_objects_choice(cid)
    # discarded one (→ graveyard), drew the known top card
    assert any(o.name == "Top" for o in p1.hand)
    assert len(p1.graveyard) == 1


def test_hedge_whisperer_animates_a_land_while_it_stays_tapped():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    src = GameObject(_db().get_card("Hedge Whisperer"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.tapped = True  # the {T} cost taps it
    bind_from_catalogue(src)
    st.add_to_battlefield(src)
    land = GameObject(Card(id="for", name="Forest", type_line="Basic Land — Forest", is_land=True),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    st.add_to_battlefield(land)

    from mtg_analyzer.game.ability_catalogue import specs_for
    act = next(s for s in specs_for(src.card) if s.ability_kind == "activated")
    build_effects(act.effects, src)[0].apply(GameContext(st, eng.rules), [land])
    eng.recompute_continuous_effects()

    assert land.is_creature and land.power == 5 and land.toughness == 5
    assert "haste" in (land.granted_keywords or [])
    assert land.is_land  # "It's still a land."

    # RULE 611.2b: the effect ends when Hedge Whisperer untaps
    src.tapped = False
    eng.recompute_continuous_effects()
    assert not land.is_creature


def test_each_opponent_pay_or_loses_life_when_declined():
    eng = _engine()
    st = eng.state
    p1, p2 = st.players
    # p2 has no cards and no creatures → can't pay → loses 3
    src = GameObject(_db().get_card("Polygraph Orb"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    st.add_to_battlefield(src)

    act = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "activated")
    build_effects(act.effects, src)[0].apply(GameContext(st, eng.rules), None)
    # drive any pending pay-or choices to decline
    guard = 0
    while st.pending_choice and guard < 10:
        guard += 1
        k = st.pending_choice["kind"]
        if k == "pay_cost_then":
            eng.rules.resolve_pay_cost_then_choice(None)
        else:
            break
    eng.resolve_until_stable()

    assert p2.life == 17  # lost 3
    assert p1.life == 20  # scope=each_opponent excluded the controller
