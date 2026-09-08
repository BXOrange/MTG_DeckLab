"""cEDH staples cube — batch B4: the "destroy/counter target X; its
controller creates a token" cluster.

This wave's one reusable primitive is `counter_create_token`
(`CounterCreateTokenEffect`) — the stack-side sibling of B3's
`destroy_create_token`: it counters a target spell and hands a token to the
*countered spell's own controller*, the same "read something off the target,
then act" shape. Proven here on the three real cards that motivated it
(Swan Song, Strix Serenade, An Offer You Can't Refuse). Pongify and Rapid
Hybridization reuse the existing `destroy_create_token` with
``can_be_regenerated=False``.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/Reference/
11_CARD_CATALOGUE_AUTHORING_GUIDE.md; tests/test_counter_family.py's
`push_spell` fixture for putting an opponent's spell on the stack.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)

ALL_B4_REGISTERED = [
    "Pongify",
    "Rapid Hybridization",
    "Swan Song",
    "Strix Serenade",
    "An Offer You Can't Refuse",
    "Path to Exile",
    "Cyclonic Rift",
    "Alchemist's Retrieval",
    "Copy Enchantment",
    "Gitaxian Probe",
    "Reanimate",
    "Noxious Revival",
    "Dramatic Reversal",
]


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine(p1_cards=(), p2_cards=()) -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_cards)), ("p2", "Bob", list(p2_cards))],
        starting_life=40,
        starting_hand=max(len(p1_cards), len(p2_cards)) or 0,
    )
    for player in eng.state.players:
        for obj in list(player.hand) + list(player.library):
            bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _push_spell(eng, player, card) -> GameObject:
    """Put ``card`` directly onto the stack as ``player``'s spell (mirrors
    tests/test_counter_family.py's `push_spell`)."""
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = []
    item = StackItem(
        kind="spell", controller_id=player.id, obj=obj,
        description=card.name, effects=[],
    )
    eng.state.stack.append(item)
    return obj


def _has_token(state, controller: str, subtype: str) -> bool:
    for o in state.permanents_controlled_by(controller):
        if not getattr(o, "is_token", False):
            continue
        if subtype in (o.card.type_line or "") or subtype in getattr(o, "subtypes", []):
            return True
    return False


# ---------------------------------------------------------------------------
# 0. All five register + are playable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_B4_REGISTERED)
def test_registered_and_playable(name):
    assert name.strip().lower() in ac._REGISTRY
    card = _card(name)
    # Registered cards are "playable" by definition; the specs must also build.
    specs = ac.specs_for(card)
    assert specs, f"{name} produced no specs"


# ---------------------------------------------------------------------------
# 1. Pongify / Rapid Hybridization — destroy (no regen) + controller token
# ---------------------------------------------------------------------------


def test_pongify_destroys_creature_and_gives_controller_an_ape():
    victim = Card(id="PgVictim", name="PgVictim", type_line="Creature — Elf",
                  is_creature=True, power=1, toughness=1)
    eng = _engine(p1_cards=[_card("Pongify")])
    state = eng.state
    p1 = state.active_player
    victim_obj = _battlefield(state, victim, controller="p2")

    spell = p1.hand[0]
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, spell, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj not in state.battlefield
    assert _has_token(state, "p2", "Ape"), "controller should get a 3/3 Ape token"


def test_rapid_hybridization_gives_controller_a_frog_lizard():
    victim = Card(id="RhVictim", name="RhVictim", type_line="Creature — Elf",
                  is_creature=True, power=1, toughness=1)
    eng = _engine(p1_cards=[_card("Rapid Hybridization")])
    state = eng.state
    p1 = state.active_player
    victim_obj = _battlefield(state, victim, controller="p2")

    spell = p1.hand[0]
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, spell, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj not in state.battlefield
    assert _has_token(state, "p2", "Frog") or _has_token(state, "p2", "Lizard")


# ---------------------------------------------------------------------------
# 2. Swan Song / Strix Serenade — counter + controller Bird token
# ---------------------------------------------------------------------------


def test_swan_song_counters_sorcery_and_gives_controller_a_bird():
    sorc = Card(id="SwSorc", name="SwSorc", type_line="Sorcery", is_sorcery=True)
    eng = _engine(p1_cards=[_card("Swan Song")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_spell = _push_spell(eng, p2, sorc)

    swan = p1.hand[0]
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, swan, targets=[victim_spell])
    eng.resolve_until_stable()

    assert victim_spell not in [it.obj for it in state.stack]
    assert victim_spell in p2.graveyard
    assert _has_token(state, "p2", "Bird"), "countered spell's controller gets a Bird"


def test_swan_song_cannot_target_a_creature_spell():
    from mtg_analyzer.game import targeting
    creat = Card(id="SwCreat", name="SwCreat", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2)
    eng = _engine(p1_cards=[_card("Swan Song")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    creature_spell = _push_spell(eng, p2, creat)

    swan = p1.hand[0]
    # The bound spell effect's target_spec must exclude the creature spell.
    effs = swan.spell_effects or []
    eff = next(e for e in effs if hasattr(e, "target_spec") and e.target_spec is not None)
    legal = targeting.legal_targets(state, "p1", eff.target_spec, source=swan)
    assert creature_spell.instance_id not in {t["instance_id"] for t in legal}


def test_strix_serenade_counters_creature_spell():
    creat = Card(id="SxCreat", name="SxCreat", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2)
    eng = _engine(p1_cards=[_card("Strix Serenade")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_spell = _push_spell(eng, p2, creat)

    strix = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.cast_spell(p1, strix, targets=[victim_spell])
    eng.resolve_until_stable()

    assert victim_spell in p2.graveyard
    assert _has_token(state, "p2", "Bird")


# ---------------------------------------------------------------------------
# 3. An Offer You Can't Refuse — counter noncreature + two Treasures
# ---------------------------------------------------------------------------


def test_an_offer_counters_noncreature_and_gives_two_treasures():
    sorc = Card(id="AoSorc", name="AoSorc", type_line="Sorcery", is_sorcery=True)
    eng = _engine(p1_cards=[_card("An Offer You Can't Refuse")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    victim_spell = _push_spell(eng, p2, sorc)

    offer = p1.hand[0]
    p1.mana_pool.add("U", 1)
    eng.cast_spell(p1, offer, targets=[victim_spell])
    eng.resolve_until_stable()

    assert victim_spell in p2.graveyard
    treasures = [o for o in state.permanents_controlled_by("p2")
                 if "Treasure" in (o.card.type_line or "")
                 or "Treasure" in getattr(o, "subtypes", [])]
    assert len(treasures) == 2, "controller should get exactly two Treasure tokens"


# ---------------------------------------------------------------------------
# 4. Path to Exile — exile a creature, its controller may ramp a basic
# ---------------------------------------------------------------------------


def test_path_to_exile_exiles_target_creature():
    victim = Card(id="PteVictim", name="PteVictim", type_line="Creature — Elf",
                  is_creature=True, power=1, toughness=1)
    eng = _engine(p1_cards=[_card("Path to Exile")])
    state = eng.state
    p1 = state.active_player
    victim_obj = _battlefield(state, victim, controller="p2")

    spell = p1.hand[0]
    p1.mana_pool.add("W", 1)
    eng.cast_spell(p1, spell, targets=[victim_obj])
    eng.resolve_until_stable()

    assert victim_obj not in state.battlefield
    assert victim_obj in state.players[1].exile


# ---------------------------------------------------------------------------
# 5. Cyclonic Rift / Alchemist's Retrieval — controller-scoped bounce
# ---------------------------------------------------------------------------


def test_cyclonic_rift_bounces_only_a_permanent_you_dont_control():
    from mtg_analyzer.game import targeting
    mine = Card(id="CrMine", name="CrMine", type_line="Artifact")
    theirs = Card(id="CrTheirs", name="CrTheirs", type_line="Artifact")
    eng = _engine(p1_cards=[_card("Cyclonic Rift")])
    state = eng.state
    p1 = state.active_player
    mine_obj = _battlefield(state, mine, controller="p1")
    theirs_obj = _battlefield(state, theirs, controller="p2")

    spell = p1.hand[0]
    eff = next(e for e in (spell.spell_effects or [])
               if getattr(e, "target_spec", None) is not None)
    legal = {t["instance_id"]
             for t in targeting.legal_targets(state, "p1", eff.target_spec, source=spell)}
    assert theirs_obj.instance_id in legal
    assert mine_obj.instance_id not in legal

    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.cast_spell(p1, spell, targets=[theirs_obj])
    eng.resolve_until_stable()
    assert theirs_obj not in state.battlefield
    assert any(o.card.name == "CrTheirs" for o in state.players[1].hand)


def test_alchemists_retrieval_bounces_only_your_own_permanent():
    from mtg_analyzer.game import targeting
    mine = Card(id="ArMine", name="ArMine", type_line="Artifact")
    theirs = Card(id="ArTheirs", name="ArTheirs", type_line="Artifact")
    eng = _engine(p1_cards=[_card("Alchemist's Retrieval")])
    state = eng.state
    p1 = state.active_player
    mine_obj = _battlefield(state, mine, controller="p1")
    theirs_obj = _battlefield(state, theirs, controller="p2")

    spell = p1.hand[0]
    eff = next(e for e in (spell.spell_effects or [])
               if getattr(e, "target_spec", None) is not None)
    legal = {t["instance_id"]
             for t in targeting.legal_targets(state, "p1", eff.target_spec, source=spell)}
    assert mine_obj.instance_id in legal
    assert theirs_obj.instance_id not in legal


# ---------------------------------------------------------------------------
# 6. Copy Enchantment — enter as a copy of an enchantment on the battlefield
# ---------------------------------------------------------------------------


def test_copy_enchantment_offers_only_enchantments_as_copy_targets():
    from mtg_analyzer.game import targeting
    ench = Card(id="CeEnch", name="CeEnch", type_line="Enchantment")
    crea = Card(id="CeCrea", name="CeCrea", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    eng = _engine()
    state = eng.state
    ench_obj = _battlefield(state, ench, controller="p2")
    crea_obj = _battlefield(state, crea, controller="p2")

    copy_card = _card("Copy Enchantment")
    obj = GameObject(copy_card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    assert obj.enter_as_copy_effects, "Copy Enchantment should carry an enter-as-copy effect"
    spec = obj.enter_as_copy_effects[0].target_spec if hasattr(
        obj.enter_as_copy_effects[0], "target_spec") else None
    from mtg_analyzer.game.targeting import TargetSpec
    spec = TargetSpec(kind=obj.enter_as_copy_effects[0].target_kind)
    legal = {t["instance_id"]
             for t in targeting.legal_targets(state, "p1", spec, source=obj)}
    assert ench_obj.instance_id in legal
    assert crea_obj.instance_id not in legal


# ---------------------------------------------------------------------------
# 7. Gitaxian Probe — cantrip (draw a card)
# ---------------------------------------------------------------------------


def test_gitaxian_probe_draws_a_card():
    extra = Card(id="GpFiller", name="GpFiller", type_line="Island — Basic Land")
    eng = _engine(p1_cards=[_card("Gitaxian Probe")], p2_cards=[extra])
    state = eng.state
    p1 = state.active_player
    # ensure the library has a card to draw
    p1.library.append(GameObject(extra, owner_id="p1", zone=Zone.LIBRARY))
    hand_before = len(p1.hand)

    spell = p1.hand[0]
    eng.cast_spell(p1, spell, targets=[])
    eng.resolve_until_stable()
    # cast one (probe leaves hand), drew one → net unchanged, but a new card is in hand
    assert any(o.card.name == "GpFiller" for o in p1.hand)


# ---------------------------------------------------------------------------
# 8. Reanimate — return a creature from a graveyard, lose life = its MV
# ---------------------------------------------------------------------------


def test_reanimate_returns_creature_and_costs_life_equal_to_mv():
    creat = Card(id="RnBig", name="RnBig", type_line="Creature — Dragon",
                 is_creature=True, power=5, toughness=5,
                 mana_cost_string="{4}{R}{R}", converted_mana_cost=6)
    eng = _engine(p1_cards=[_card("Reanimate")])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    dead = GameObject(creat, owner_id="p2", zone=Zone.GRAVEYARD)
    p2.graveyard.append(dead)
    life_before = p1.life

    spell = p1.hand[0]
    p1.mana_pool.add("B", 1)
    eng.cast_spell(p1, spell, targets=[dead])
    eng.resolve_until_stable()

    assert dead in state.battlefield
    assert dead.controller_id == "p1", "Reanimate takes control"
    assert p1.life == life_before - 6, "lose life equal to the creature's mana value"


# ---------------------------------------------------------------------------
# 9. Noxious Revival — put a graveyard card on top of its owner's library
# ---------------------------------------------------------------------------


def test_noxious_revival_puts_graveyard_card_on_top_of_owners_library():
    card = Card(id="NrCard", name="NrCard", type_line="Sorcery", is_sorcery=True)
    eng = _engine(p1_cards=[_card("Noxious Revival")])
    state = eng.state
    p1 = state.active_player
    dead = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead)

    spell = p1.hand[0]
    eng.cast_spell(p1, spell, targets=[dead])
    eng.resolve_until_stable()

    assert dead not in p1.graveyard
    # top of library is the end of the list (see Player.library ordering)
    assert p1.library[-1] is dead


# ---------------------------------------------------------------------------
# 10. Dramatic Reversal — untap all your nonland permanents (not lands)
# ---------------------------------------------------------------------------


def test_dramatic_reversal_untaps_nonland_permanents_only():
    rock = Card(id="DrRock", name="DrRock", type_line="Artifact")
    land = Card(id="DrLand", name="DrLand", type_line="Land", is_land=True)
    eng = _engine(p1_cards=[_card("Dramatic Reversal")])
    state = eng.state
    p1 = state.active_player
    rock_obj = _battlefield(state, rock, controller="p1")
    land_obj = _battlefield(state, land, controller="p1")
    rock_obj.tapped = True
    land_obj.tapped = True

    spell = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.cast_spell(p1, spell, targets=[])
    eng.resolve_until_stable()

    assert not rock_obj.tapped, "nonland permanent should untap"
    assert land_obj.tapped, "lands are untouched by Dramatic Reversal"


# ---------------------------------------------------------------------------
# 11. Sphere of Resistance — parser-modeled "spells cost {1} more"
# ---------------------------------------------------------------------------


def test_sphere_of_resistance_is_parser_modeled():
    card = _card("Sphere of Resistance")
    assert parse_oracle(card).modeled, "bare 'spells cost {1} more' should now parse"
