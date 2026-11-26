"""PAR-291 M3: "<player> exiles the top card of their library", "reveals their hand and discards all <class> cards",
and Cataclysm / Global Ruin's per-type keepers led by "from among the ...".

Real cards on a 3-player engine: the affected player (never the caster) is the one whose zone is used.
"""
import pytest

from test_par320_edict_counts_punishers import _three, _creature, _land, _put, _real, _card, _ids
from test_par320_residue import _spell
from mtg_analyzer.game.card_registry import is_card_covered, specs_for
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

CLAIMED = ("Amnesia", "Trapfinder's Trick", "Shatter Assumptions", "Cataclysm", "Global Ruin",
           "Fathom Feeder", "Thought Harvester", "Knacksaw Clique", "Ornate Kanzashi")


@pytest.mark.parametrize("name", CLAIMED)
def test_real_cards_are_covered(name):
    assert is_card_covered(_real(name))


@pytest.mark.parametrize("text", [
    "Target player discards all cards.",  # the whole-hand shapes have their own rows
    "Target player reveals their hand and discards all cards of that color.",  # a referent class
    "Target player reveals their hand and discards all cards with art by the chosen artist.",
    "Target player exiles the top card of your library.",  # whose library must agree with the subject
    "Each player exiles the top card of target opponent's library.",
])
def test_unsound_forms_stay_refused(text):
    assert not parse_oracle(_card("Neg", type_line="Sorcery", is_sorcery=True, oracle=text)).modeled


def _hand(eng, pid, *cards):
    out = []
    for card in cards:
        obj = GameObject(card, owner_id=pid, zone=Zone.HAND)
        obj.controller_id = pid
        eng.state.player_by_id(pid).hand.append(obj)
        out.append(obj)
    return out


def _top(eng, pid, name, **kw):
    obj = GameObject(_card(name, type_line="Land", is_land=True, **kw), owner_id=pid, zone=Zone.LIBRARY)
    obj.controller_id = pid
    eng.state.player_by_id(pid).library.append(obj)
    return obj


def test_amnesia_discards_every_nonland_card_of_the_target_only():
    eng = _three()
    nonland = _hand(eng, "p2", _card("Bear", is_creature=True), _card("Bolt", type_line="Instant"))
    land = _hand(eng, "p2", _card("Forest", type_line="Basic Land — Forest", is_land=True))
    mine = _hand(eng, "p1", _card("Mine", is_creature=True))
    _spell(eng, "Amnesia", targets=[eng.state.player_by_id("p2")])
    assert all(o.zone is Zone.GRAVEYARD for o in nonland)
    assert land[0].zone is Zone.HAND and mine[0].zone is Zone.HAND
    assert eng.state.pending_choice is None  # "all": nothing to choose


def test_amnesia_on_an_empty_hand_does_nothing():
    eng = _three()
    _spell(eng, "Amnesia", targets=[eng.state.player_by_id("p2")])
    assert eng.state.pending_choice is None and not eng.state.player_by_id("p2").hand


def test_trapfinders_trick_discards_only_traps():
    eng = _three()
    trap, other = _hand(eng, "p2", _card("A Trap", type_line="Instant — Trap"), _card("Not", type_line="Instant"))
    _spell(eng, "Trapfinder's Trick", targets=[eng.state.player_by_id("p2")])
    assert trap.zone is Zone.GRAVEYARD and other.zone is Zone.HAND


def _run_mode(eng, name, index, targets):
    spec = next(s for s in specs_for(_real(name)) if s.modes)
    src = _creature(eng, "Src", "p1")
    for e in spec.modes["options"][index]:
        effect = EffectRegistry.create(e.type, e.params)
        effect.source = src
        effect.apply(GameContext(eng.state, eng.rules), targets)
    eng.resolve_until_stable()


def test_shatter_assumptions_both_modes_use_the_color_classes():
    eng = _three()
    colorless_spell, colorless_land, multi, mono = _hand(
        eng, "p2", _card("Rock", type_line="Artifact", mana_cost_string="{2}"), _card("Waste", type_line="Land", is_land=True),
        _card("Gold", type_line="Creature — X", is_creature=True, mana_cost_string="{W}{U}"),
        _card("Mono", type_line="Creature — X", is_creature=True, mana_cost_string="{W}"))
    _run_mode(eng, "Shatter Assumptions", 0, [eng.state.player_by_id("p2")])
    zones = [o.zone for o in (colorless_spell, colorless_land, multi, mono)]
    # one mode discards colorless nonland cards, the other multicolored ones
    first = {i for i, z in enumerate(zones) if z is Zone.GRAVEYARD}
    assert first in ({0}, {2})
    _run_mode(eng, "Shatter Assumptions", 1, [eng.state.player_by_id("p2")])
    assert {i for i, o in enumerate((colorless_spell, colorless_land, multi, mono)) if o.zone is Zone.GRAVEYARD} == {0, 2}
    assert colorless_land.zone is Zone.HAND and mono.zone is Zone.HAND


def _run_ability(eng, name, src, targets=None):
    spec = next(s for s in specs_for(_real(name)) if any(e.type == "exile_top_of_library" for e in s.effects))
    for e in spec.effects:
        if e.type != "exile_top_of_library":
            continue
        effect = EffectRegistry.create(e.type, e.params)
        effect.source = src
        effect.apply(GameContext(eng.state, eng.rules), targets)
    eng.resolve_until_stable()


def test_fathom_feeder_exiles_from_each_opponents_library_not_the_casters():
    eng = _three()
    src = _put(eng, _real("Fathom Feeder"), "p1")
    tops = {pid: _top(eng, pid, f"T-{pid}") for pid in ("p1", "p2", "p3")}
    _run_ability(eng, "Fathom Feeder", src)
    assert tops["p2"].zone is Zone.EXILE and tops["p3"].zone is Zone.EXILE
    assert tops["p1"].zone is Zone.LIBRARY


def test_thought_harvester_targets_one_opponent_and_an_empty_library_is_a_no_op():
    eng = _three()
    src = _put(eng, _real("Thought Harvester"), "p1")
    p2top = _top(eng, "p2", "T2")
    p3top = _top(eng, "p3", "T3")
    _run_ability(eng, "Thought Harvester", src, [eng.state.player_by_id("p2")])
    assert p2top.zone is Zone.EXILE and p3top.zone is Zone.LIBRARY
    _run_ability(eng, "Thought Harvester", src, [eng.state.player_by_id("p1")])  # p1's library is empty
    assert eng.state.pending_choice is None


def test_cataclysm_each_player_keeps_one_of_each_type_and_sacrifices_the_rest():
    eng = _three()
    keep = {}
    for pid in ("p1", "p2"):
        a = _put(eng, _card(f"Art-{pid}", type_line="Artifact"), pid)
        c1, c2 = _creature(eng, f"C1-{pid}", pid), _creature(eng, f"C2-{pid}", pid)
        e = _put(eng, _card(f"Ench-{pid}", type_line="Enchantment"), pid)
        l1, l2 = _land(eng, f"L1-{pid}", pid), _land(eng, f"L2-{pid}", pid)
        keep[pid] = (a, c1, c2, e, l1, l2)
    bare = _creature(eng, "Lonely", "p3")
    _spell(eng, "Cataclysm")
    seen = []
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        pid = choice["player_id"]
        seen.append(pid)
        pool = _ids(choice)
        own = {o.instance_id for o in keep[pid]}
        assert pool <= own  # only that player's permanents
        eng.resolve_pending_choice(str(next(iter(sorted(pool)))))
        eng.resolve_until_stable()
    assert seen.count("p1") == 2 and seen.count("p2") == 2  # creature and land need a decision
    assert bare.zone is Zone.BATTLEFIELD  # p3 keeps its lone creature
    for pid in ("p1", "p2"):
        left = [o for o in keep[pid] if o.zone is Zone.BATTLEFIELD]
        assert len(left) == 4  # artifact, enchantment, one creature, one land


def test_global_ruin_keeps_one_land_of_each_basic_land_type():
    eng = _three()
    plains = _put(eng, _card("Plains", type_line="Basic Land — Plains", is_land=True), "p1")
    plains2 = _put(eng, _card("Plains2", type_line="Basic Land — Plains", is_land=True), "p1")
    island = _put(eng, _card("Island", type_line="Basic Land — Island", is_land=True), "p1")
    other = _put(eng, _card("Waste", type_line="Land", is_land=True), "p1")
    bear = _creature(eng, "Bear", "p1")
    _spell(eng, "Global Ruin")
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(str(plains.instance_id))
        eng.resolve_until_stable()
    assert plains.zone is Zone.BATTLEFIELD and island.zone is Zone.BATTLEFIELD
    assert plains2.zone is Zone.GRAVEYARD and other.zone is Zone.GRAVEYARD  # not chosen
    assert bear.zone is Zone.BATTLEFIELD  # only lands are in the pool


def _view(eng, perspective):
    from mtg_analyzer.services.game_session import GameSession
    return GameSession(eng, mode="multiplayer").view(perspective=perspective)["state"]["known_cards"]


def test_revealed_hand_keeps_the_undiscarded_cards_public():
    # RULE 701.20a: every card of the revealed hand is shown, not only the discarded ones.
    eng = _three()
    bear, bolt = _hand(eng, "p2", _card("Bear", is_creature=True),
                       _card("Forest", type_line="Basic Land — Forest", is_land=True))
    _spell(eng, "Amnesia", targets=[eng.state.player_by_id("p2")])
    assert bear.zone is Zone.GRAVEYARD and bolt.zone is Zone.HAND
    known = {c["instance_id"] for c in _view(eng, "p1")}
    assert bolt.instance_id in known
    other = {c["instance_id"] for c in _view(eng, "p3")}
    assert bolt.instance_id in other  # public to every player


def test_without_the_reveal_words_nothing_becomes_public():
    eng = _three()
    from mtg_analyzer.game.effects.core import EffectRegistry as R, GameContext as C
    (keep,) = _hand(eng, "p2", _card("Forest", type_line="Basic Land — Forest", is_land=True))
    e = R.create("discard", {"hand_criteria": {"without_type": ["land"]}, "target_kind": "player"})
    e.source = _creature(eng, "Src", "p1")
    e.apply(C(eng.state, eng.rules), [eng.state.player_by_id("p2")])
    assert keep.instance_id not in {c["instance_id"] for c in _view(eng, "p1")}
