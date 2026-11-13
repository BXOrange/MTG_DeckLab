"""PAR-238: tokens that carry a quoted ability next to keywords."""
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature

MITE = ('create 2 1/1 colorless phyrexian mite artifact creature tokens '
        'with toxic 1 and "~ can\'t block."')


def _make(clause):
    eng = _engine()
    source = _bf(eng, Card(id='source', name='Source', type_line='Artifact'))
    specs = parse_effect_body(clause)
    assert specs
    build_effects(specs, source)[0].apply(eng.rules.context)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    return eng, [o for o in eng.state.battlefield if o.is_token]


def test_mite_has_toxic_and_cannot_block():
    eng, tokens = _make(MITE)
    assert len(tokens) == 2
    attacker = _bf(eng, _creature('Bear'), 'p2')
    attacker.attacking = True
    attacker.combat_defender = {'kind': 'player', 'id': 'p1'}
    for tok in tokens:
        assert tok.parametric_keywords['toxic'] == {'n': 1}
        # RULE 509.1b: "can't block" removes it from the legal blockers.
        assert not eng.can_block(eng.state.player_by_id('p1'), tok, attacker)
    # RULE 702.164: its combat damage also gives a poison counter.
    p2 = eng.state.player_by_id('p2')
    eng.rules.deal_damage(p2, 1, source=tokens[0], combat=True)
    assert (p2.life, p2.poison) == (19, 1)


def test_ordinary_creature_can_still_block():
    eng, _ = _make(MITE)
    bear = _bf(eng, _creature('Bear'), 'p1')
    attacker = _bf(eng, _creature('Wolf'), 'p2')
    attacker.attacking = True
    attacker.combat_defender = {'kind': 'player', 'id': 'p1'}
    assert eng.can_block(eng.state.player_by_id('p1'), bear, attacker)


# -- Pilot: "saddles Mounts and crews Vehicles as though its power were 2 greater" --------------------------------
ROADS_PILOT = ('create a 1/1 colorless pilot creature token with '
               '"~ saddles mounts and crews vehicles as though its power were 2 greater."')
LEGACY_PILOT = 'create a 1/1 colorless pilot creature token with "~ crews vehicles as though its power were 2 greater."'


def _vehicle(eng, n):
    return _bf(eng, Card(id='veh', name='Rig', type_line='Artifact — Vehicle', vehicle_power=4,
                         vehicle_toughness=4, oracle_text=f'Crew {n}'))


def _mount(eng, n):
    return _bf(eng, Card(id='mnt', name='Horse', type_line='Creature — Mount', is_creature=True, power=2,
                         toughness=2, oracle_text=f'Saddle {n}'))


def test_roads_pilot_crews_and_saddles_with_bonus_but_keeps_real_power():
    eng, tokens = _make(ROADS_PILOT)
    pilot = tokens[0]
    assert pilot.power == 1  # RULE 208.1: the bonus is a cost contribution only
    p1 = eng.state.player_by_id('p1')
    # RULE 702.122a: 1 power + 2 = 3 crews Crew 3.
    assert eng._resolve_crew_cost(p1, _vehicle(eng, 3), 3, [pilot.instance_id]) == [pilot]
    # RULE 702.171a: the same creature saddles Saddle 3.
    assert eng._resolve_crew_cost(p1, _mount(eng, 3), 3, [pilot.instance_id], crewing=False) == [pilot]
    # ... but 3 is the ceiling: Crew 4 is out of reach.
    assert eng._resolve_crew_cost(p1, _vehicle(eng, 4), 4, [pilot.instance_id]) is None


def test_pilot_bonus_does_not_leak_into_combat_damage():
    eng, tokens = _make(ROADS_PILOT)
    p2 = eng.state.player_by_id('p2')
    eng.rules.deal_damage(p2, tokens[0].power, source=tokens[0], combat=True)
    assert p2.life == 19


def test_legacy_crew_only_pilot_does_not_saddle():
    eng, tokens = _make(LEGACY_PILOT)
    pilot = tokens[0]
    p1 = eng.state.player_by_id('p1')
    assert eng._resolve_crew_cost(p1, _vehicle(eng, 3), 3, [pilot.instance_id]) == [pilot]
    assert eng._resolve_crew_cost(p1, _mount(eng, 3), 3, [pilot.instance_id], crewing=False) is None


def test_plain_creature_has_no_bonus():
    eng = _engine()
    bear = _bf(eng, _creature('Bear'))
    eng.recompute_continuous_effects()
    assert eng._crew_power_of(bear) == bear.power
    assert eng._crew_power_of(bear, crewing=False) == bear.power


def test_unmodelled_bonus_wording_fails_closed():
    assert not parse_effect_body('create a 1/1 colorless pilot creature token with '
                                 '"~ crews vehicles as though its power were twice as great."')


def test_hand_authored_pilot_token_still_crews_with_bonus():
    from mtg_analyzer.game.card_catalogue._shared.pilot import pilot_token
    eng = _engine()
    source = _bf(eng, Card(id='source', name='Source', type_line='Artifact'))
    build_effects([pilot_token()], source)[0].apply(eng.rules.context)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    pilot = next(o for o in eng.state.battlefield if o.is_token)
    assert eng._crew_power_of(pilot) == pilot.power + 2


# -- "<token sentence>. It has \"<quoted ability>\"" ----------------------------------------------------------------
def test_it_has_sentence_gives_the_token_an_activated_pump():
    eng, tokens = _make('create a 2/2 red dragon creature token with flying. '
                        'it has "{r}: ~ gets +1/+0 until end of turn."')
    dragon = tokens[0]
    assert dragon.power == 2
    assert len(dragon.activated_abilities) == 1
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('R', 1)
    eng.activate_ability(p1, dragon, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert dragon.power == 3


def test_it_has_sentence_gives_the_token_a_death_trigger():
    eng, tokens = _make('create a 1/1 red devil creature token. '
                        'it has "when ~ dies, it deals 1 damage to any target."')
    assert tokens[0].triggered_abilities


def test_it_has_cda_sentence_defines_the_tokens_power_and_toughness():
    eng, tokens = _make('create a white avatar creature token. '
                        'it has "~\'s power and toughness are each equal to your life total."')
    life = eng.state.player_by_id('p1').life
    assert tokens[0].power == tokens[0].toughness == life


def test_it_has_sentence_naming_the_creating_card_fails_closed():
    # RULE 201.5: "a card named ~" would name the creating card, not the token.
    assert not parse_effect_body('create a 1/1 black bat creature token with flying. '
                                 'it has "{1}{b}, sacrifice ~: return an exiled card named ~ to the battlefield."')


def test_keyword_and_quoted_ability_token_blocks_only_fliers():
    eng, tokens = _make('create a 1/1 blue faerie creature token with flying and '
                        '"~ can block only creatures with flying."')
    ground = _bf(eng, _creature('Wolf'), 'p2')
    flier = _bf(eng, Card(id='bird', name='Bird', type_line='Creature — Bird', is_creature=True, power=1,
                          toughness=1, keywords=['Flying']), 'p2')
    eng.recompute_continuous_effects()
    p1 = eng.state.player_by_id('p1')
    for att in (ground, flier):
        att.attacking = True
        att.combat_defender = {'kind': 'player', 'id': 'p1'}
    assert not eng.can_block(p1, tokens[0], ground)
    assert eng.can_block(p1, tokens[0], flier)
