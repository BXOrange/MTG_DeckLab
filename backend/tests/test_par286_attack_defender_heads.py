"""PAR-286 milestone 2: attack heads that name *what* is attacked.

``whenever ~ attacks a battle``, ``... attacks the player with the most life or tied for most life`` and
``... attacks the monarch`` (RULE 506.2 / 508.1b), plus the "that player" pool the Spear of Bashenga's body needs.
Every behaviour test declares a real attack on a real card and shows a near miss that must not fire.
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

_DB = CardDatabase(DB_PATH)
#: Frontliner's "+1/+1" and the doubled power of the Slasher, named so the assertions read as rules text.
FRONTLINER_BONUS = 1
SLASHER_BASE_POWER = 4


def _card(name: str) -> Card:
    card = _DB.get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the card cache")
    return card


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    return eng


def _board(eng: GameEngine, card: Card, pid: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _battle(eng: GameEngine) -> GameObject:
    card = Card(id="b", name="Invasion of Testland", type_line="Battle — Siege", defense=3, layout="transform",
                back_name="Reverse", back_type_line="Creature — Phyrexian", back_power=3, back_toughness=3)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.rules._offer_protector_choice(obj, lambda: None)
    if eng.state.pending_choice:
        eng.rules.resolve_choice("p2")
    eng.state.add_to_battlefield(obj)
    return obj


def _attack(eng: GameEngine, attacker: GameObject, kind: str) -> None:
    p1 = eng.state.player_by_id("p1")
    spec = next(d for d in eng.legal_defenders_for(p1) if d["kind"] == kind)
    eng.declare_attackers(p1, [{"attacker": attacker, "defender": spec}])
    eng.resolve_until_stable()  # puts the trigger on the stack, which opens its target prompt
    choice = eng.state.pending_choice
    if choice is not None and choice["kind"] == "trigger_target":
        eng.resolve_pending_choice(str(choice["options"][0]["id"]))
        eng.resolve_until_stable()
    eng.recompute_continuous_effects()


# --- head grammar ------------------------------------------------------------------------------------------------


def test_head_shapes():
    battle = parse_object_trigger_head("~ attacks a battle")
    assert (battle.event, battle.condition, battle.trigger) == (
        "ATTACKS", {"subject": "self"}, {"filter": {"defender_kind": "battle"}})
    monarch = parse_object_trigger_head("equipped creature attacks the monarch")
    assert monarch.condition == {"subject": "attached_permanent"}
    assert monarch.trigger == {"attacked_player_is_monarch": True, "filter": {"defender_kind": "player"}}
    life = parse_object_trigger_head("equipped creature attacks the player with the most life or tied for most life")
    assert life.trigger == {"attacked_player_has_most_life": True}
    # near misses: an unknown defender word and a repeated qualifier stay unclaimed
    assert parse_object_trigger_head("~ attacks the player with the least life") is None
    assert parse_object_trigger_head("~ attacks a battle a battle") is None


@pytest.mark.parametrize("name", [
    "Thrashing Frontliner", "War-Trained Slasher", "The Spear of Bashenga", "Seraphic Greatsword",
])
def test_cards_are_modeled(name):
    assert parse_oracle(_card(name)).coverage == MODELED


# --- behaviour ---------------------------------------------------------------------------------------------------


def test_thrashing_frontliner_pumps_only_when_it_attacks_a_battle():
    eng = _engine()
    battle = _battle(eng)
    frontliner = _board(eng, _card("Thrashing Frontliner"))
    eng.recompute_continuous_effects()
    base = frontliner.power
    _attack(eng, frontliner, "battle")
    assert frontliner.combat_defender["instance_id"] == battle.instance_id
    assert frontliner.power == base + FRONTLINER_BONUS

    # near miss: attacking the player instead
    eng2 = _engine()
    _battle(eng2)
    other = _board(eng2, _card("Thrashing Frontliner"))
    eng2.recompute_continuous_effects()
    _attack(eng2, other, "player")
    assert other.power == base


def test_war_trained_slasher_doubles_power_only_against_a_battle():
    eng = _engine()
    _battle(eng)
    slasher = _board(eng, _card("War-Trained Slasher"))
    _attack(eng, slasher, "battle")
    assert slasher.power == SLASHER_BASE_POWER * 2

    eng2 = _engine()
    _battle(eng2)
    other = _board(eng2, _card("War-Trained Slasher"))
    _attack(eng2, other, "player")
    assert other.power == SLASHER_BASE_POWER


def _equip(eng: GameEngine, name: str, host: GameObject) -> GameObject:
    equipment = _board(eng, _card(name))
    assert eng.rules.attach_to_target(equipment, host)
    eng.recompute_continuous_effects()
    return equipment


def test_spear_of_bashenga_destroys_a_tapped_permanent_only_when_the_monarch_is_attacked():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    bear = _board(eng, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                            toughness=2))
    _equip(eng, "The Spear of Bashenga", bear)
    tapped = _board(eng, Card(id="t", name="Tapped Bear", type_line="Creature — Bear", is_creature=True, power=2,
                              toughness=2), "p2")
    untapped = _board(eng, Card(id="u", name="Untapped Bear", type_line="Creature — Bear", is_creature=True,
                                power=2, toughness=2), "p2")
    tapped.tapped = True
    eng.rules.become_monarch(p2)
    _attack(eng, bear, "player")
    assert tapped.zone != Zone.BATTLEFIELD
    assert untapped.zone == Zone.BATTLEFIELD

    # near miss: the defender is not the monarch
    eng2 = _engine()
    bear2 = _board(eng2, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                              toughness=2))
    _equip(eng2, "The Spear of Bashenga", bear2)
    tapped2 = _board(eng2, Card(id="t", name="Tapped Bear", type_line="Creature — Bear", is_creature=True,
                                power=2, toughness=2), "p2")
    tapped2.tapped = True
    eng2.rules.become_monarch(eng2.state.player_by_id("p1"))
    _attack(eng2, bear2, "player")
    assert eng2.state.pending_choice is None
    assert tapped2.zone == Zone.BATTLEFIELD


def test_monarch_flag_survives_clone():
    # the predicate reads live state, so a cloned game must still gate on the clone's own monarch
    eng = _engine()
    bear = _board(eng, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                            toughness=2))
    _equip(eng, "The Spear of Bashenga", bear)
    victim = _board(eng, Card(id="t", name="Tapped Bear", type_line="Creature — Bear", is_creature=True, power=2,
                              toughness=2), "p2")
    victim.tapped = True
    eng.rules.become_monarch(eng.state.player_by_id("p2"))
    clone = copy.deepcopy(eng)
    clone_bear = clone.state.find_object(bear.instance_id)
    _attack(clone, clone_bear, "player")
    assert clone.state.find_object(victim.instance_id).zone != Zone.BATTLEFIELD
    assert victim.zone == Zone.BATTLEFIELD  # the original is untouched


def test_seraphic_greatsword_makes_an_angel_only_against_the_most_life():
    eng = _engine()
    bear = _board(eng, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                            toughness=2))
    _equip(eng, "Seraphic Greatsword", bear)
    _attack(eng, bear, "player")  # tied for most life at 20 each
    angels = [o for o in eng.state.battlefield if "Angel" in o.name]
    assert len(angels) == 1

    eng2 = _engine()
    bear2 = _board(eng2, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                              toughness=2))
    _equip(eng2, "Seraphic Greatsword", bear2)
    eng2.state.player_by_id("p2").life = 5  # no longer the player with the most life
    _attack(eng2, bear2, "player")
    assert not [o for o in eng2.state.battlefield if "Angel" in o.name]


@pytest.mark.parametrize("name", ["Yosei, the Morning Star", "Sylvan Primordial"])
def test_that_player_pool_is_not_fed_by_a_prior_target_or_a_for_each_round(name):
    # Near miss: "that player" here is a prior "target player" / "for each opponent", which the event-only pools
    # (`targeting.trigger_player_antecedent`) do not read, so the card must stay unclaimed rather than tap or destroy
    # the wrong player's permanents.
    assert parse_oracle(_card(name)).coverage != MODELED


def test_seraphic_greatsword_angel_attacks_the_attacked_player_in_a_three_player_game():
    # RULE 508.4 / 506.3: "attacking that player" is the player the equipped creature attacked, even when another
    # opponent is a legal (and equally eligible) defender: no defender prompt is opened for the token.
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cy", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.state.current_phase = "combat"  # RULE 508.4: a creature can only be put into an existing combat
    bear = _board(eng, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                            toughness=2))
    _equip(eng, "Seraphic Greatsword", bear)
    for pid in ("p2", "p3"):
        eng.state.player_by_id(pid).life = 25  # both tied for the most life
    p1 = eng.state.player_by_id("p1")
    spec = next(d for d in eng.legal_defenders_for(p1) if d["kind"] == "player" and d["id"] == "p3")
    eng.declare_attackers(p1, [{"attacker": bear, "defender": spec}])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    angels = [o for o in eng.state.battlefield if "Angel" in o.name]
    assert len(angels) == 1 and angels[0].attacking
    assert angels[0].combat_defender["kind"] == "player" and angels[0].combat_defender["id"] == "p3"


#: Every distinct non-empty ``creature_filter`` a cached card's bound spec puts on the "that player" permanent pools
#: (audited over the full pool at v988: only The Spear of Bashenga). Each row: the filter, a candidate that matches it
#: and one that must be refused. The frame change (`apply_creature_filter=True`) is only sound if every key is read.
_THAT_PLAYER_FILTERS = [
    pytest.param({"tapped": True, "without_card_type": "land"},
                 dict(type_line="Artifact", tapped=True), dict(type_line="Artifact", tapped=False),
                 id="tapped-nonland-untapped-refused"),
    pytest.param({"tapped": True, "without_card_type": "land"},
                 dict(type_line="Artifact", tapped=True), dict(type_line="Land", tapped=True),
                 id="tapped-nonland-land-refused"),
]


@pytest.mark.parametrize("kind", ["permanent_that_player_controls", "nonland_permanent_that_player_controls"])
@pytest.mark.parametrize(("creature_filter", "good", "bad"), _THAT_PLAYER_FILTERS)
def test_that_player_pools_read_the_quality_filter(kind, creature_filter, good, bad):
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    eng = _engine()
    made = {}
    for label, attrs in (("good", good), ("bad", bad)):
        card = Card(id=label, name=label, type_line=attrs["type_line"])
        obj = GameObject(card, owner_id="p2", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p2"
        obj.tapped = attrs["tapped"]
        eng.state.add_to_battlefield(obj)
        made[label] = obj
    # a matching permanent of the other player is out of scope ("that player controls")
    other = GameObject(Card(id="o", name="other", type_line="Artifact"), owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    other.tapped = True
    eng.state.add_to_battlefield(other)

    spec = TargetSpec(kind=kind, creature_filter=dict(creature_filter))
    event = {"type": "ATTACKS", "defending_player_id": "p2"}
    offered = {o["instance_id"] for o in legal_targets(eng.state, "p1", spec, trigger_event=event)}
    assert offered == {made["good"].instance_id}


def test_soaring_lightbringer_token_attacks_the_player_you_attacked_in_a_three_player_game():
    # Same `attacks_event_player` wiring, reached through the PLAYER_ATTACKED event ("whenever you attack a player").
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cy", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.state.current_phase = "combat"
    _board(eng, _card("Soaring Lightbringer"))
    bear = _board(eng, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                            toughness=2))
    p1 = eng.state.player_by_id("p1")
    spec = next(d for d in eng.legal_defenders_for(p1) if d["kind"] == "player" and d["id"] == "p3")
    eng.declare_attackers(p1, [{"attacker": bear, "defender": spec}])
    eng._fire_player_attacked_events()  # the aggregate the turn loop fires when the declaration closes
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    glimmers = [o for o in eng.state.battlefield if o.is_token]
    assert len(glimmers) == 1 and glimmers[0].attacking
    assert glimmers[0].combat_defender["id"] == "p3"
