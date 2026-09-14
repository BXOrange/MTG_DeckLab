"""MEC-85 — RULE 702.194b Teamwork's *other* "instead" shape: a cast-time-
conditional change to target legality or selection count, not a flat
magnitude (PAR-68's `DealDamageEffect.amount_if_teamwork` already closed
that half — see `test_par68_teamwork_residue.py`). Three cards, all
confirmed singleton via `parser_probe.py blocked`, hand-authored:

- Cruel Alliance / Too Evil to Stay Dead — the mana-value cap sits on the
  RULE 115 target itself ("exile target creature **with mana value 3 or
  less**. If ... teamwork, instead exile target creature[.]"), so it needs
  new `targeting.TargetSpec.unless_flag`: a cast-time flag name that, when
  true for the requirement's own spell at *offer* time, drops
  `max_mana_value`/`creature_filter`/`color`/`colors` back to unfiltered
  for that one requirement (RULE 601.2b's additional cost is chosen/paid
  before RULE 601.2c's targets are chosen, so this is answerable before
  a target is ever offered — unlike a flat-magnitude override, which has
  no target-legality question and stays a resolve-time trick). Resolved
  through the same two-phase reading `GameEngine._modal_override_active`
  already uses (`GameObject._modal_announced_teamwork` while a cast's
  targets are still being offered/checked, `teamwork_paid` once cast).
- Earth's Mightiest Heroes — "you may put **a** creature card from among
  them onto the battlefield. If ... teamwork, put **any number** of
  creature cards ... instead." is a selection-*count* override with no
  RULE 115 target at all (a library-zone pick, not a target). New
  `InspectTopChooseEffect.max_picks_if_teamwork` generalizes MEC-72's own
  single-pick `RulesEngine.inspect_top_n_choose` (Eclipsed Flamekin/Cream
  of the Crop/Cavalier of Thorns) to a cast-time-conditional cap, read off
  the real, final `GameObject.teamwork_paid` at resolve time — like
  `amount_if_teamwork`, since there's no early-offer question here.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


CRUEL_ALLIANCE = Card(
    id="CA", name="Cruel Alliance", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{2}{B}", converted_mana_cost=3, keywords=["Teamwork"],
    oracle_text=(
        "Teamwork 2 (As an additional cost to cast this spell, you may tap "
        "any number of creatures you control with total power 2 or more.)\n"
        "Exile target creature with mana value 3 or less. If this spell was "
        "cast using teamwork, instead exile target creature and you gain 3 "
        "life."
    ),
)

TOO_EVIL_TO_STAY_DEAD = Card(
    id="TESD", name="Too Evil to Stay Dead", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{2}{B}", converted_mana_cost=3, keywords=["Teamwork"],
    oracle_text=(
        "Teamwork 4 (As an additional cost to cast this spell, you may tap "
        "any number of creatures you control with total power 4 or more.)\n"
        "Choose target creature card in your graveyard with mana value 4 or "
        "less. If this spell was cast using teamwork, instead choose target "
        "creature card in your graveyard. Return the chosen card to the "
        "battlefield."
    ),
)

EARTHS_MIGHTIEST_HEROES = Card(
    id="EMH", name="Earth's Mightiest Heroes", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{4}{G}{G}", converted_mana_cost=6, keywords=["Teamwork"],
    oracle_text=(
        "Teamwork 5 (As an additional cost to cast this spell, you may tap "
        "any number of creatures you control with total power 5 or more.)\n"
        "Reveal the top eight cards of your library. You may put a creature "
        "card from among them onto the battlefield. If this spell was cast "
        "using teamwork, put any number of creature cards from among them "
        "onto the battlefield instead. Put the rest into your graveyard."
    ),
)


def _helper(eng, ctrl="p1", power=5, name="Helper"):
    o = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=power),
        owner_id=ctrl, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = ctrl
    o.summoning_sick = False
    eng.state.add_to_battlefield(o)
    return o


def _hand_spell(eng, card, ctrl="p1"):
    o = GameObject(card, owner_id=ctrl, zone=Zone.HAND)
    o.controller_id = ctrl
    bind_from_catalogue(o)
    eng.state.player_by_id(ctrl).hand.append(o)
    return o


def _creature(name, ctrl, mana_cost, cmc, zone=Zone.BATTLEFIELD):
    o = GameObject(
        Card(id=name, name=name, type_line="Creature — Giant", is_creature=True,
             power=1, toughness=1, mana_cost_string=mana_cost, converted_mana_cost=cmc),
        owner_id=ctrl, zone=zone,
    )
    o.controller_id = ctrl
    return o


# --- Cruel Alliance ---------------------------------------------------------


def test_cruel_alliance_specs():
    specs = specs_for(CRUEL_ALLIANCE)
    spell_effects = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    exile_params = spell_effects[0].effects[0].params
    assert exile_params["max_mana_value"] == 3
    assert exile_params["unless_flag"] == "teamwork_paid"
    gain_life = spell_effects[0].effects[1]
    assert gain_life.type == "gain_life"
    assert gain_life.condition == {"teamwork_paid": True}


def test_cruel_alliance_target_pool_caps_by_mana_value_without_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    cheap = _creature("Cheap", "p2", "{1}", 1)
    expensive = _creature("Expensive", "p2", "{5}", 5)
    eng.state.add_to_battlefield(cheap)
    eng.state.add_to_battlefield(expensive)
    _helper(eng)
    spell = _hand_spell(eng, CRUEL_ALLIANCE)

    plain = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "cast_spell" and a.get("instance_id") == spell.instance_id
        and not a.get("teamwork")
    ]
    assert len(plain) == 1
    names = {o["name"] for o in plain[0]["targets"][0]["options"]}
    # Expensive (mv 5) is over the printed cap; Helper (p1's own, mv 0) is
    # still a legal "target creature" either way.
    assert names == {"Cheap", "Helper"}


def test_cruel_alliance_target_pool_uncapped_with_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    cheap = _creature("Cheap", "p2", "{1}", 1)
    expensive = _creature("Expensive", "p2", "{5}", 5)
    eng.state.add_to_battlefield(cheap)
    eng.state.add_to_battlefield(expensive)
    _helper(eng)
    spell = _hand_spell(eng, CRUEL_ALLIANCE)

    teamwork = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "cast_spell" and a.get("instance_id") == spell.instance_id
        and a.get("teamwork")
    ]
    assert len(teamwork) == 1
    names = {o["name"] for o in teamwork[0]["targets"][0]["options"]}
    assert names == {"Cheap", "Expensive", "Helper"}


def test_cruel_alliance_no_life_gain_without_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    cheap = _creature("Cheap", "p2", "{1}", 1)
    eng.state.add_to_battlefield(cheap)
    spell = _hand_spell(eng, CRUEL_ALLIANCE)
    life_before = p1.life

    eng.cast_spell(p1, spell, targets=[cheap])
    eng.resolve_until_stable()

    assert cheap.zone == Zone.EXILE
    assert p1.life == life_before


def test_cruel_alliance_exiles_over_cap_and_gains_life_with_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    expensive = _creature("Expensive", "p2", "{5}", 5)
    eng.state.add_to_battlefield(expensive)
    helper = _helper(eng)
    spell = _hand_spell(eng, CRUEL_ALLIANCE)
    life_before = p1.life

    eng.cast_spell(p1, spell, targets=[expensive], teamwork=True, teamwork_choices=[helper.instance_id])
    eng.resolve_until_stable()

    assert expensive.zone == Zone.EXILE
    assert p1.life == life_before + 3
    assert helper.tapped is True


# --- Too Evil to Stay Dead ---------------------------------------------------


def test_too_evil_to_stay_dead_specs():
    specs = specs_for(TOO_EVIL_TO_STAY_DEAD)
    spell_effects = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    params = spell_effects[0].effects[0].params
    assert params["target_kind"] == "graveyard_creature"
    assert params["max_mana_value"] == 4
    assert params["unless_flag"] == "teamwork_paid"
    assert params["destination"] == "battlefield"


def test_too_evil_to_stay_dead_graveyard_pool_caps_without_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    cheap = _creature("CheapDead", "p1", "{1}", 1, zone=Zone.GRAVEYARD)
    expensive = _creature("ExpensiveDead", "p1", "{6}", 6, zone=Zone.GRAVEYARD)
    p1.graveyard.extend([cheap, expensive])
    _helper(eng, power=4)
    spell = _hand_spell(eng, TOO_EVIL_TO_STAY_DEAD)

    plain = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "cast_spell" and a.get("instance_id") == spell.instance_id
        and not a.get("teamwork")
    ]
    assert len(plain) == 1
    names = {o["name"] for o in plain[0]["targets"][0]["options"]}
    assert names == {"CheapDead"}


def test_too_evil_to_stay_dead_reanimates_over_cap_with_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    expensive = _creature("ExpensiveDead", "p1", "{6}", 6, zone=Zone.GRAVEYARD)
    p1.graveyard.append(expensive)
    helper = _helper(eng, power=4)
    spell = _hand_spell(eng, TOO_EVIL_TO_STAY_DEAD)

    eng.cast_spell(
        p1, spell, targets=[expensive], teamwork=True, teamwork_choices=[helper.instance_id],
    )
    eng.resolve_until_stable()

    assert expensive.zone == Zone.BATTLEFIELD
    assert expensive in eng.state.battlefield


# --- Earth's Mightiest Heroes -------------------------------------------------


def test_earths_mightiest_heroes_specs():
    specs = specs_for(EARTHS_MIGHTIEST_HEROES)
    spell_effects = [s for s in specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    params = spell_effects[0].effects[0].params
    assert params["count"] == 8
    assert params["action"] == "library_to_battlefield"
    assert params["filter"] == {"is_creature": True}
    assert params["rest_destination"] == "graveyard"
    assert params["max_picks"] == 1
    assert params["max_picks_if_teamwork"] == 8


def _stock_library(p1, n_creatures=4, n_lands=4, n_filler=10):
    for i in range(n_filler):
        p1.library.append(GameObject(
            Card(id=f"F{i}", name=f"Filler{i}", type_line="Island", is_land=True),
            owner_id="p1", zone=Zone.LIBRARY,
        ))
    for i in range(n_lands):
        p1.library.append(GameObject(
            Card(id=f"L{i}", name=f"Land{i}", type_line="Island", is_land=True),
            owner_id="p1", zone=Zone.LIBRARY,
        ))
    creatures = []
    for i in range(n_creatures):
        c = GameObject(
            Card(id=f"CR{i}", name=f"Creature{i}", type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        c.controller_id = "p1"
        p1.library.append(c)  # library[-1] is "on top" — see RevealTopEffect
        creatures.append(c)
    return creatures


def _answer_choose_objects(eng, take_all: bool):
    picked = 0
    while eng.state.pending_choice is not None:
        pc = eng.state.pending_choice
        creature_opts = [o for o in pc["options"] if "instance_id" in o]
        if not creature_opts or (not take_all and picked >= 1):
            eng.rules.resolve_choice(None)
            break
        eng.rules.resolve_choice(creature_opts[0]["instance_id"])
        picked += 1
        eng.resolve_until_stable()
    return picked


def test_earths_mightiest_heroes_caps_at_one_without_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 6})
    _stock_library(p1)
    spell = _hand_spell(eng, EARTHS_MIGHTIEST_HEROES)

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["count"] == 1
    picked = _answer_choose_objects(eng, take_all=True)

    assert picked == 1
    battlefield_creatures = [o for o in eng.state.battlefield if o.name.startswith("Creature")]
    assert len(battlefield_creatures) == 1
    # Every other revealed card (3 creatures + 4 lands) went to the graveyard.
    assert len(p1.graveyard) == 7 + 1  # +1 for the sorcery itself


def test_earths_mightiest_heroes_any_number_with_teamwork():
    eng = _engine()
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 6})
    _stock_library(p1)
    helper = _helper(eng)
    spell = _hand_spell(eng, EARTHS_MIGHTIEST_HEROES)

    eng.cast_spell(p1, spell, teamwork=True, teamwork_choices=[helper.instance_id])
    eng.resolve_until_stable()
    assert eng.state.pending_choice["count"] == 8
    picked = _answer_choose_objects(eng, take_all=True)

    assert picked == 4  # all four revealed creatures, "any number"
    battlefield_creatures = sorted(
        o.name for o in eng.state.battlefield if o.name.startswith("Creature")
    )
    assert battlefield_creatures == ["Creature0", "Creature1", "Creature2", "Creature3"]
    # Only the 4 revealed lands + the spell itself hit the graveyard.
    assert sorted(o.name for o in p1.graveyard) == [
        "Earth's Mightiest Heroes", "Land0", "Land1", "Land2", "Land3",
    ]
    assert helper.tapped is True
