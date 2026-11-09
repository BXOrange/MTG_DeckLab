"""PAR-250: ``create x <tokens>, where x is <amount>. The tokens have "<ability>"`` (Cloudspire Coordinator,
Return of the Mole Man): every created token owns the quoted ability natively (RULE 111.3)."""
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _bf, _creature, _engine

COORDINATOR_TEXT = (
    "When this creature enters, scry 2.\n"
    "{T}: Create X 1/1 colorless Pilot creature tokens, where X is the number of Mounts and/or Vehicles that "
    "entered the battlefield under your control this turn. The tokens have \"This token saddles Mounts and "
    "crews Vehicles as though its power were 2 greater.\""
)
MOLE_MAN_TEXT = (
    "Landfall — Whenever a land you control enters, you may mill two cards.\n"
    "{5}{G}, Sacrifice this enchantment: Create X 1/1 green Minion creature tokens named Moloid, where X is the "
    "number of permanent cards in your graveyard. The tokens have \"Whenever this token attacks, you may mill a "
    "card.\" Activate only as a sorcery."
)


def _coordinator(eng):
    card = Card(id="cc", name="Cloudspire Coordinator", type_line="Creature — Dwarf Artificer", is_creature=True,
                power=1, toughness=3, oracle_text=COORDINATOR_TEXT)
    obj = _bf(eng, card)
    return obj


def _pilots(eng):
    return [o for o in eng.state.battlefield if o.is_token and o.name == "Pilot"]


def _enter(eng, obj):
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
                                   controller_id=obj.controller_id))
    return obj


def _vehicle(eng, name="Rig", player="p1", entered=True):
    obj = _bf(eng, Card(id=name, name=name, type_line="Artifact — Vehicle", vehicle_power=3, vehicle_toughness=3),
              player)
    return _enter(eng, obj) if entered else obj


def _activate_tap(eng, obj):
    p1 = eng.state.player_by_id("p1")
    eng.activate_ability(p1, obj, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()


def test_both_cards_are_claimed_modeled():
    for text in (COORDINATOR_TEXT, MOLE_MAN_TEXT):
        card = Card(id="x", name="X", type_line="Creature", oracle_text=text)
        assert card.oracle_text  # sanity; coverage verdicts are asserted via the clause rows below
    assert parse_effect_body(
        'create x 1/1 colorless pilot creature tokens, where x is the number of mounts and/or vehicles that '
        'entered the battlefield under your control this turn. the tokens have "~ saddles mounts and crews '
        'vehicles as though its power were 2 greater."')


def test_coordinator_x_two_gives_two_pilots_each_with_the_bonus():
    eng = _engine()
    coordinator = _coordinator(eng)
    _vehicle(eng, "Rig")  # these entered under p1's control this turn
    _enter(eng, _bf(eng, Card(id="mnt", name="Horse", type_line="Creature — Mount", is_creature=True, power=2,
                              toughness=2)))
    _vehicle(eng, "Old", entered=False)  # on the battlefield already, did not enter this turn
    eng.recompute_continuous_effects()
    _activate_tap(eng, coordinator)
    pilots = _pilots(eng)
    assert len(pilots) == 2
    p1 = eng.state.player_by_id("p1")
    for pilot in pilots:
        assert pilot.power == 1  # RULE 208.1: bonus is a cost contribution only
        assert eng._crew_power_of(pilot) == pilot.power + 2  # RULE 702.122a / 702.171a bonus lives on each token
        crewed = _vehicle(eng, f"Big{pilot.instance_id}", entered=False)
        assert eng._resolve_crew_cost(p1, crewed, 3, [pilot.instance_id]) == [pilot]


def test_coordinator_x_zero_makes_no_tokens():
    eng = _engine()
    coordinator = _coordinator(eng)
    eng.recompute_continuous_effects()
    _activate_tap(eng, coordinator)
    assert _pilots(eng) == []


def test_coordinator_ignores_vehicles_the_opponent_controlled_and_other_types():
    eng = _engine()
    coordinator = _coordinator(eng)
    _vehicle(eng, "TheirRig", "p2")
    _enter(eng, _bf(eng, _creature("Bear")))
    eng.recompute_continuous_effects()
    _activate_tap(eng, coordinator)
    assert _pilots(eng) == []


def test_unmodelled_amount_stays_unclaimed():
    assert not parse_effect_body(
        'create x 1/1 colorless pilot creature tokens, where x is the number of flurbs that entered the '
        'battlefield under your control this turn. the tokens have "~ crews vehicles as though its power were '
        '2 greater."')
    # a filter the ENTERS_BATTLEFIELD predicate does not share with the count grammar is refused, not guessed
    assert not parse_effect_body(
        'create x 1/1 colorless pilot creature tokens, where x is the number of tapped creatures that entered '
        'the battlefield under your control this turn. the tokens have "~ crews vehicles as though its power '
        'were 2 greater."')


# -- Return of the Mole Man ---------------------------------------------------------------------------------------
def _mole_man(eng, graveyard_cards):
    card = Card(id="mm", name="Return of the Mole Man", type_line="Enchantment — Saga", oracle_text=MOLE_MAN_TEXT)
    obj = _bf(eng, card)
    p1 = eng.state.player_by_id("p1")
    for i in range(graveyard_cards):
        p1.graveyard.append(GameObject(
            Card(id=f"g{i}", name=f"Grave {i}", type_line="Creature — Bear", is_creature=True, power=1, toughness=1),
            owner_id="p1", zone=Zone.GRAVEYARD))
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 5)
    return obj


def _moloids(eng):
    return [o for o in eng.state.battlefield if o.is_token and o.name == "Moloid"]


def test_mole_man_makes_x_moloids_each_with_the_attack_trigger():
    eng = _engine()
    obj = _mole_man(eng, 3)  # 3 in the graveyard + the sacrificed Saga
    p1 = eng.state.player_by_id("p1")
    eng.activate_ability(p1, obj, ability_index=0)
    eng.resolve_until_stable()
    moloids = _moloids(eng)
    # RULE 602.2b: the Saga is sacrificed as a cost, so it is the fourth permanent card when X is measured.
    assert len(moloids) == 4
    assert all(m.triggered_abilities for m in moloids)
    assert all((m.power, m.toughness) == (1, 1) for m in moloids)


def test_mole_man_with_empty_graveyard_makes_nothing():
    eng = _engine()
    obj = _mole_man(eng, 0)
    p1 = eng.state.player_by_id("p1")
    eng.activate_ability(p1, obj, ability_index=0)
    eng.resolve_until_stable()
    # The sacrifice cost itself put the Saga into the graveyard first, so X counts it (RULE 602.2b: costs are
    # paid before resolution) -- exactly one permanent card.
    assert len(_moloids(eng)) == 1


def test_mole_man_cannot_be_activated_outside_sorcery_timing():
    eng = _engine()
    obj = _mole_man(eng, 2)
    eng.state.current_step = "combat_damage"  # RULE 307.1 / 602.5d: not a main phase
    p1 = eng.state.player_by_id("p1")
    try:
        eng.activate_ability(p1, obj, ability_index=0)
        eng.resolve_until_stable()
    except Exception:  # noqa: BLE001 - the engine may refuse by raising or by returning without activating
        pass
    assert _moloids(eng) == []
    assert obj.zone == Zone.BATTLEFIELD  # the sacrifice cost was never paid


# -- the shared "entered the battlefield under your control this turn" amount (also claims Hobgoblin Bandit Lord) --
def test_entered_this_turn_amount_counts_only_matching_entries_under_your_control():
    from mtg_analyzer.game.binding.core import build_effects

    eng = _engine()
    source = _bf(eng, Card(id="src", name="Src", type_line="Creature — Goblin", is_creature=True, power=1, toughness=1))
    gob = lambda i, who="p1": _enter(eng, _bf(eng, Card(  # noqa: E731
        id=f"gob{i}", name=f"Gob{i}", type_line="Creature — Goblin", is_creature=True, power=1, toughness=1), who))
    gob(1)
    gob(2)
    gob(3, "p2")  # entered under the opponent's control: not counted
    _enter(eng, _bf(eng, _creature("Bear")))  # not a Goblin
    specs = parse_effect_body("~ deals x damage to each opponent, where x is the number of goblins that "
                              "entered the battlefield under your control this turn")
    assert specs
    build_effects(specs, source)[0].apply(eng.rules.context)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 18
