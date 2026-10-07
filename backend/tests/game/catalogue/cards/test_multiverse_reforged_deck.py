"""Gameplay regressions for Multiverse Reforged."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


#: Printed data for cards newer than the committed-in-CI test cache seed (resolved from the cache when present).
_SYNTH_CARDS = {
    "Jace, Multiverse Architect": dict(
        type_line="Legendary Planeswalker — Jace", mana_cost_string="{1}{W}{U}{B}{R}", cmc=5, loyalty=4,
        oracle_text="At the beginning of combat on each opponent's turn, they may pay {2}. If they don't, creatures they "
                    "control can't attack Jaces you control this turn.\n+1: Draw two cards, then put a card from your hand "
                    "on the bottom of your library.\n−3: Exile another target planeswalker or creature you control. Reveal "
                    "cards from the top of your library until you reveal a creature or planeswalker card. Put that card onto "
                    "the battlefield and the rest on the bottom of your library in a random order.\nJace, Multiverse "
                    "Architect can be your commander."),
    "The Ur-Sphinx": dict(
        type_line="Legendary Creature — Sphinx Avatar", mana_cost_string="{6}{W}{U}{B}", cmc=9, power=6, toughness=6,
        keywords=["Flying"],
        oracle_text="Eminence — As long as The Ur-Sphinx is in the command zone or on the battlefield, other Sphinx spells "
                    "you cast cost {1} less to cast.\nFlying\nWhenever one or more Sphinxes you control attack, each player "
                    "mills that many cards. For each player, you may cast a card that player milled this way without paying "
                    "its mana cost."),
    "Venser, Fervent Forger": dict(
        type_line="Legendary Creature — Human Sorcerer", mana_cost_string="{4}{R}{R}", cmc=6, power=4, toughness=4,
        keywords=["Flash"],
        oracle_text="Flash\nWhen Venser enters, choose one —\n• Copy target instant or sorcery spell an opponent controls "
                    "twice. You may choose new targets for the copies.\n• Create two tokens that are copies of target "
                    "permanent an opponent controls. They gain haste. At the beginning of the next end step, sacrifice them."),
    "Plan for All Outcomes": dict(
        type_line="Enchantment", mana_cost_string="{3}{U}", cmc=4,
        oracle_text="When this enchantment enters, the owner of up to one other target nonland permanent puts it on their "
                    "choice of the top or bottom of their library.\nWhenever you cast your first noncreature spell each "
                    "turn, empower Jace 1. (Put a loyalty counter on a Jace token you control. If you don't control one, "
                    "first create a blue Jace planeswalker token with \"[−1]: Surveil 1\" and \"[−3]: Draw a card.\")"),
    "Jhoira, Weatherlight Corsair": dict(
        type_line="Legendary Creature — Human Pirate", mana_cost_string="{4}{B}{B}", cmc=6, power=4, toughness=4,
        oracle_text="Whenever Jhoira enters or attacks, target opponent reveals cards from the top of their library until "
                    "they reveal a historic permanent card. You put that card onto the battlefield under your control and "
                    "lose life equal to that permanent's mana value. That player puts the rest of the revealed cards on the "
                    "bottom of their library in a random order. (Artifacts, legendaries, and Sagas are historic.)"),
    "Teferi's Reproach": dict(
        type_line="Instant", mana_cost_string="{2}{W}", cmc=3,
        oracle_text="Choose target opponent. Until that player's next turn, they gain protection from everything and their "
                    "life total can't change. All nonland permanents they control phase out. (While they're phased out, "
                    "they're treated as though they don't exist. They phase in before that player untaps during their next "
                    "untap step.)\nExile Teferi's Reproach."),
    "Omnath, Locus of the Void": dict(
        type_line="Legendary Creature — Elemental", mana_cost_string="{7}", cmc=7, power=7, toughness=7,
        oracle_text="Omnath gets +1/+1 for each unspent mana you have.\nIf you would lose unspent mana, that mana becomes "
                    "colorless instead.\nLandfall — Whenever a land you control enters, add {C}{C}."),
    "Tamiyo, Upriser Crowned": dict(
        type_line="Legendary Creature — Moonfolk Warrior", mana_cost_string="{4}{R}{W}", cmc=6, power=3, toughness=5,
        keywords=["Flying", "Haste", "Double strike"],
        oracle_text="Flying, double strike, haste\nWhen Tamiyo enters, you become the monarch.\nWhenever one or more "
                    "creatures deal combat damage to you while you're the monarch, tap those creatures and put a stun "
                    "counter on each of them."),
}


def _synth_card(name):
    kw = dict(_SYNTH_CARDS[name])
    type_line = kw.pop("type_line")
    return Card(id=name, name=name, type_line=type_line, converted_mana_cost=kw.pop("cmc"),
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                is_legendary="Legendary" in type_line, **kw)


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    card = CardDatabase(DB_PATH).get_card(name) or (_synth_card(name) if name in _SYNTH_CARDS else None)
    if name == 'Ginger, Queen of Sweets':
        card = Card(id='ginger', name=name, type_line='Legendary Artifact Creature — Food Noble',
                    is_creature=True, power=6, toughness=4, mana_cost_string='{6}',
                    oracle_text="When Ginger enters, you become the monarch.\n{2}, {T}, Sacrifice Ginger: You gain 6 life.\n"
                                "At the beginning of each upkeep, if you're the monarch, create a Gingerbrute token.")
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string=kw.pop("mana_cost_string", "{%d}" % mv if mv else ""),
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine._fire_delayed_triggers(step)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 5, "U": 5, "B": 5, "R": 5, "G": 5, "C": 15}







def test_brainsurge_controller_chooses_two_cards_and_their_order_off_turn():
    e = _game()
    e.state.active_player_index = 1
    spell = _card(e, 'Brainsurge', zone=Zone.HAND)
    kept = _filler(e, 'Keep', 'Instant', zone=Zone.HAND)
    first = _filler(e, 'First', 'Instant', zone=Zone.HAND)
    last = _filler(e, 'Last', 'Instant', zone=Zone.HAND)
    _cast(e, spell, RICH)
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice(str(first.instance_id))
    e.resolve_pending_choice(str(last.instance_id))
    p = e.state.player_by_id('p1')
    assert [o.name for o in p.library[-2:]] == ['First', 'Last']
    assert kept in p.hand and len(p.hand) == 5
    assert not e.state.player_by_id('p2').hand


def test_kher_keep_creates_the_printed_kobold():
    e = _game()
    land = _card(e, 'Kher Keep')
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    index = 0
    _activate(e, land, index)
    token = _named(e, 'Kobolds of Kher Keep')[0]
    assert (token.power, token.toughness) == (0, 1)
    assert continuous._has_subtype(token, 'Kobold') and token.colors == {'R'}
    assert land.tapped


def test_ginger_monarch_upkeep_and_sacrifice():
    e = _game()
    ginger = _put_on_battlefield(e, 'Ginger, Queen of Sweets')
    assert e.state.monarch_id == 'p1'
    e.state.active_player_index = 1
    _step(e, 'upkeep', 'p2')
    brute = _named(e, 'Gingerbrute')[0]
    assert brute.is_token and (brute.power, brute.toughness) == (1, 1)
    assert 'haste' in combat._obj_keywords(brute)
    assert len(brute.activated_abilities) >= 2
    e.state.monarch_id = 'p2'
    _step(e, 'upkeep', 'p2')
    assert len(_named(e, 'Gingerbrute')) == 1
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    before = e.state.player_by_id('p1').life
    _activate(e, ginger)
    assert ginger.zone == Zone.GRAVEYARD
    assert e.state.player_by_id('p1').life == before + 6


def test_restless_anchorage_animates_attacks_and_cleans_up():
    e = _game()
    land = _card(e, 'Restless Anchorage')
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    index = 0
    _activate(e, land, index)
    e.recompute_continuous_effects()
    assert land.is_creature and land.is_land and (land.power, land.toughness) == (2, 3)
    assert set(land.colors) == {'W', 'U'}
    assert 'flying' in combat._obj_keywords(land)
    land.tapped = False
    e.state.current_phase, e.state.current_step = 'combat', 'declare_attackers'
    e.declare_attackers(e.state.player_by_id('p1'), [
        {'attacker': land, 'defender': e.state.player_by_id('p2')}])
    e.resolve_until_stable()
    assert _named(e, 'Map')
    e.state.current_step = 'cleanup'
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert not land.is_creature and 'flying' not in combat._obj_keywords(land)
    assert not land._derived_colors


@pytest.mark.parametrize('x', [0, 4, 5])
def test_white_suns_twilight_x_and_created_token_exemption(x):
    e = _game()
    spell = _card(e, "White Sun's Twilight", zone=Zone.HAND)
    ours = _filler(e, 'Ours', power=2, toughness=2)
    theirs = _filler(e, 'Theirs', player='p2', power=2, toughness=2)
    _cast(e, spell, RICH, x=x)
    p = e.state.player_by_id('p1')
    assert p.life == 20 + x
    mites = _named(e, 'Phyrexian Mite')
    assert len(mites) == x
    for token in mites:
        assert "artifact" in token.type_words and (token.power, token.toughness) == (1, 1)
        assert token.parametric_keywords.get('toxic') == {'n': 1}
        assert 'cant_block' in combat._obj_keywords(token)
    assert (ours.zone == Zone.GRAVEYARD) == (x >= 5)
    assert (theirs.zone == Zone.GRAVEYARD) == (x >= 5)


def test_archfiend_doubles_each_opponents_own_loss_and_prohibits_their_gains():
    e = _game(players=3)
    _card(e, 'Archfiend of Despair')
    p1, p2, p3 = e.state.players
    e.rules.lose_life(p2, 3)
    e.rules.lose_life(p3, 5)
    e.rules.gain_life(p1, 2)
    e.rules.gain_life(p2, 7)
    e.rules.gain_life(p3, 7)
    assert (p1.life, p2.life, p3.life) == (22, 17, 15)
    _step(e, 'end', 'p2')
    assert (p1.life, p2.life, p3.life) == (22, 14, 10)


def test_archon_opponent_chooses_sacrifice_then_discard_before_controller_draw():
    e = _game(players=3)
    p1, p2, p3 = e.state.players
    victim = _filler(e, 'Victim', player='p2', power=2, toughness=2)
    spared = _filler(e, 'Spared', player='p2', power=2, toughness=2)
    discarded = _filler(e, 'Discard', 'Instant', player='p2', zone=Zone.HAND)
    _filler(e, 'Keep in hand', 'Instant', player='p2', zone=Zone.HAND)
    archon = _put_on_battlefield(e, 'Archon of Cruelty')
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert e.state.pending_choice['player_id'] == 'p2'
    assert p1.life == 20 and not p1.hand
    e.resolve_pending_choice(str(victim.instance_id))
    assert e.state.pending_choice['player_id'] == 'p2'
    e.resolve_pending_choice(str(discarded.instance_id))
    e.resolve_until_stable()
    assert victim.zone == discarded.zone == Zone.GRAVEYARD
    assert spared.zone == Zone.BATTLEFIELD
    assert (p1.life, p2.life, p3.life) == (23, 17, 20)
    assert len(p1.hand) == 1
    assert archon.zone == Zone.BATTLEFIELD


def test_archon_without_creatures_still_discards_and_loses_life():
    e = _game()
    _put_on_battlefield(e, 'Archon of Cruelty')
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert not e.state.pending_choice
    assert e.state.player_by_id('p1').life == 23
    assert e.state.player_by_id('p2').life == 17


def test_niv_optional_life_payment_uses_the_amount_of_that_life_gain():
    e = _game()
    niv = _filler(e, 'Niv-Mizzet, Ghost Counsel', 'Legendary Creature — Spirit Dragon',
                  power=6, toughness=6, oracle_text='Flying', keywords=['Flying'])
    p = e.state.player_by_id('p1')
    e.rules.gain_life(p, 3)
    e.resolve_until_stable()
    assert e.state.pending_choice['player_id'] == 'p1'
    _answer(e)
    assert p.life == 20 and len(p.hand) == 3
    e.rules.gain_life(p, 2)
    e.resolve_until_stable()
    e.resolve_pending_choice('decline')
    assert p.life == 22 and len(p.hand) == 3
    _activate(e, niv)
    _answer(e)
    assert p.life == 22 and len(p.hand) == 4
    assert e.state.player_by_id('p2').life == 19


def _fatehold(e):
    return _filler(e, 'Fatehold Charm', 'Instant', zone=Zone.HAND, mana_cost_string='{W}{U}')


def test_fatehold_draw_and_empower_creates_then_increments_jace():
    e = _game()
    _cast(e, _fatehold(e), RICH, mode=[0])
    _answer(e)
    p = e.state.player_by_id('p1')
    assert len(p.hand) == 1
    jace = _named(e, 'Jace')[0]
    assert jace.is_planeswalker and jace.counters['loyalty'] == 2
    assert len(jace.activated_abilities) == 2
    _cast(e, _fatehold(e), RICH, mode=[0])
    _answer(e)
    assert jace.counters['loyalty'] == 4 and len(_named(e, 'Jace')) == 1


def test_fatehold_bounces_a_creature():
    e = _game()
    victim = _filler(e, 'Victim', player='p2', power=2, toughness=2)
    _cast(e, _fatehold(e), RICH, targets=[victim], mode=[1])
    assert victim.zone == Zone.HAND
    assert not e.state.player_by_id('p1').hand


def test_fatehold_pumps_only_our_creatures_until_cleanup():
    e = _game()
    ours = _filler(e, 'Ours', power=2, toughness=2)
    theirs = _filler(e, 'Theirs', player='p2', power=2, toughness=2)
    _cast(e, _fatehold(e), RICH, mode=[2])
    e.recompute_continuous_effects()
    assert (ours.power, ours.toughness) == (3, 4)
    assert (theirs.power, theirs.toughness) == (2, 2)
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert (ours.power, ours.toughness) == (2, 2)


def test_fatehold_returns_a_spell_without_countering_it():
    e = _game()
    p2 = e.state.player_by_id('p2')
    spell = _filler(e, 'Response', 'Instant', player='p2', zone=Zone.HAND,
                    oracle_text='Draw a card.')
    e.state.current_phase, e.state.current_step = 'main', 'main1'
    e.cast_spell(p2, spell)
    item = e.state.stack[-1]
    _cast(e, _fatehold(e), RICH, targets=[item], mode=[1])
    assert spell.zone == Zone.HAND and spell in p2.hand
    assert len(p2.hand) == 1 and not e.state.stack


def _avacyn(e):
    return _filler(e, 'Avacyn, Angel of Horror', 'Legendary Creature — Angel', power=6, toughness=6,
                   oracle_text='Flying, deathtouch', keywords=['Flying', 'Deathtouch'])


def test_avacyn_returns_an_owned_opponents_creature_under_trigger_controllers_control():
    e = _game()
    avacyn = _avacyn(e)
    creature = _filler(e, 'Borrowed', player='p2', power=2, toughness=2)
    creature.controller_id = 'p1'
    e.rules.destroy(creature)
    e.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD
    assert len(e.state.delayed_triggers) == 1
    avacyn.controller_id = 'p2'
    _step(e, 'end', 'p2')
    assert creature.zone == Zone.BATTLEFIELD and creature.controller_id == 'p1'


def test_avacyn_returns_itself_after_death():
    e = _game()
    avacyn = _avacyn(e)
    e.rules.destroy(avacyn)
    e.resolve_until_stable()
    assert avacyn.zone == Zone.GRAVEYARD
    _step(e, 'end')
    assert avacyn.zone == Zone.BATTLEFIELD


def test_avacyn_ignores_tokens_and_cards_that_changed_graveyard_incarnation():
    e = _game()
    _avacyn(e)
    token = _filler(e, 'Token', power=2, toughness=2)
    token.is_token = True
    creature = _filler(e, 'Other', power=2, toughness=2)
    e.rules.destroy(token)
    e.resolve_until_stable()
    assert not e.state.delayed_triggers
    e.rules.destroy(creature)
    e.resolve_until_stable()
    assert len(e.state.delayed_triggers) == 1
    e.rules.return_from_graveyard(creature)
    e.rules.destroy(creature)
    e.resolve_until_stable()
    # Two delayed triggers exist, but only the second still names this card.
    assert len(e.state.delayed_triggers) == 2
    e.state.delayed_triggers.pop()
    _step(e, 'end')
    assert creature.zone == Zone.GRAVEYARD


def test_fact_or_fiction_opponent_divides_and_controller_chooses():
    e = _game()
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Revealed {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    p1, p2 = e.state.players
    initial_library = list(p1.library)
    _cast(e, spell, RICH)
    assert e.state.pending_choice['player_id'] == 'p2'
    assert p1.library == initial_library
    e.resolve_pending_choice(str(cards[0].instance_id))
    e.resolve_pending_choice(str(cards[3].instance_id))
    e.resolve_pending_choice('decline')
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice('first')
    assert set(p1.hand) == {cards[0], cards[3]}
    assert all(o in p1.graveyard for o in (cards[1], cards[2], cards[4], spell))
    assert len(p1.library) == 10 and not p2.hand
    assert not any(ev.type == EventType.DRAW for ev in e.state.events_this_turn())


@pytest.mark.parametrize('take', ['first', 'second'])
def test_fact_or_fiction_empty_pile_is_a_real_choice(take):
    e = _game(library=2)
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    p1 = e.state.player_by_id('p1')
    cards = list(p1.library)
    _cast(e, spell, RICH)
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice(take)
    assert len(p1.hand) == (0 if take == 'first' else 2)
    assert all(o.zone == (Zone.GRAVEYARD if take == 'first' else Zone.HAND) for o in cards)


def test_fact_or_fiction_choose_divider_and_reject_nonrevealed_card():
    e = _game(players=3)
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    bottom = e.state.player_by_id('p1').library[0]
    _cast(e, spell, RICH)
    assert e.state.pending_choice['kind'] == 'choose_pile_divider'
    e.resolve_pending_choice('p3')
    assert e.state.pending_choice['player_id'] == 'p3'
    with pytest.raises(ValueError, match='revealed card'):
        e.resolve_pending_choice(str(bottom.instance_id))
    assert e.state.pending_choice['player_id'] == 'p3'
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice('second')
    assert len(e.state.player_by_id('p1').hand) == 5


def _darksteel(e, zone=Zone.BATTLEFIELD):
    return _filler(e, 'Darksteel Angel', 'Artifact Creature — Angel', power=4, toughness=4, mv=9,
                   zone=zone, keywords=['Flying', 'Indestructible'], oracle_text=(
                       "Flying, indestructible\nYou can't lose the game and your opponents can't win the game.\n"
                       "Creatures you control can't have -1/-1 counters put on them."))


def test_darksteel_angel_prohibits_only_negative_counters_on_our_creatures():
    e = _game()
    angel = _darksteel(e)
    ours = _filler(e, 'Ours', power=4, toughness=4)
    theirs = _filler(e, 'Theirs', player='p2', power=4, toughness=4)
    artifact = _filler(e, 'Artifact', 'Artifact')
    for obj in (angel, ours, theirs, artifact):
        e.rules.add_counters(obj, 1, '-1/-1')
    assert angel.counters.get('-1/-1', 0) == ours.counters.get('-1/-1', 0) == 0
    assert theirs.counters['-1/-1'] == artifact.counters['-1/-1'] == 1
    e.rules.add_counters(ours, 1, '+1/+1')
    assert ours.counters['+1/+1'] == 1
    # Prohibiting placement doesn't prevent removal of existing counters.
    ours.add_counters('-1/-1', 2)
    e.rules.add_counters(ours, -1, '-1/-1')
    assert ours.counters['-1/-1'] == 1
    e.rules.exile(angel)
    e.rules.add_counters(ours, 1, '-1/-1')
    assert ours.counters['-1/-1'] == 2


def test_darksteel_prohibition_applies_to_entry_counters_including_itself():
    e = _game()
    angel = _darksteel(e, Zone.HAND)
    angel.entry_bonus_counters = {'-1/-1': 2}
    _cast(e, angel, RICH)
    assert angel.counters.get('-1/-1', 0) == 0
    creature = _filler(e, 'Entrant', power=4, toughness=4, zone=Zone.HAND,
                       oracle_text='This creature enters with two -1/-1 counters on it.')
    _cast(e, creature, RICH)
    assert creature.counters.get('-1/-1', 0) == 0
    enemy = _filler(e, 'Enemy entrant', player='p2', power=4, toughness=4, zone=Zone.HAND,
                    oracle_text='This creature enters with two -1/-1 counters on it.')
    e.state.active_player_index = 1
    _cast(e, enemy, RICH)
    assert enemy.counters['-1/-1'] == 2


def test_darksteel_angel_prevents_loss_and_opponents_alternate_wins():
    e = _game()
    angel = _darksteel(e)
    p1, p2 = e.state.players
    p1.life = 0
    e.resolve_until_stable()
    assert not p1.has_lost
    e.rules.player_wins(p2)
    assert not p1.has_lost and not e.state.game_over
    assert combat.has(angel, 'flying') and combat.has(angel, 'indestructible')
    e.rules.exile(angel)
    e.resolve_until_stable()
    assert p1.has_lost


def test_skrelvs_hive_upkeep_and_live_corrupted_toxic_filter():
    e = _game(players=3)
    _card(e, "Skrelv's Hive")
    other = _filler(e, 'Ordinary', power=2, toughness=2)
    enemy = _filler(e, 'Enemy', player='p2', power=2, toughness=2, oracle_text='Toxic 1')
    e.state.active_player_index = 1
    _step(e, 'upkeep', 'p2')
    assert not _named(e, 'Phyrexian Mite')
    e.state.active_player_index = 0
    _step(e, 'upkeep')
    mite = _named(e, 'Phyrexian Mite')[0]
    assert e.state.player_by_id('p1').life == 19 and combat.has(mite, 'toxic')
    assert 'cant_block' in combat._obj_keywords(mite)
    assert not combat.has(mite, 'lifelink')
    e.state.player_by_id('p3').poison = 3
    e.recompute_continuous_effects()
    assert combat.has(mite, 'lifelink')
    assert not combat.has(other, 'lifelink') and not combat.has(enemy, 'lifelink')
    e.state.player_by_id('p3').poison = 2
    e.recompute_continuous_effects()
    assert not combat.has(mite, 'lifelink')


def test_fact_or_fiction_graveyard_pile_honors_exile_replacement():
    e = _game()
    _card(e, 'Rest in Peace')
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Pile card {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    _cast(e, spell, RICH)
    e.resolve_pending_choice(str(cards[1].instance_id))
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice('first')
    assert cards[1].zone == Zone.HAND
    assert all(o.zone == Zone.EXILE for o in cards if o is not cards[1])
    assert all(o not in e.state.player_by_id('p1').library for o in cards)


def test_fact_or_fiction_choice_survives_session_rewind():
    from mtg_analyzer.services.game_session import GameSession
    e = _game()
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Undo card {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    _cast(e, spell, RICH)
    session = GameSession(e)
    action = {'type': 'choose', 'option_id': str(cards[2].instance_id)}
    session.apply_action(action, actor_id='p2')
    assert e.state.pending_choice['first_ids'] == [cards[2].instance_id]
    session.rewind()
    e = session.engine
    assert e.state.pending_choice['first_ids'] == []
    session.apply_action(action, actor_id='p2')
    session.apply_action({'type': 'decline'}, actor_id='p2')
    session.apply_action({'type': 'choose', 'option_id': 'first'}, actor_id='p1')
    assert [o.name for o in e.state.player_by_id('p1').hand] == ['Undo card 2']
    assert len(e.state.player_by_id('p1').library) == 10


def test_tamiyo_stuns_creatures_that_hit_the_monarch():
    engine = _game()
    _card(engine, "Tamiyo, Upriser Crowned")
    me = engine.state.player_by_id("p1")
    engine.state.monarch_id = "p1"
    attacker = _filler(engine, "Bear", power=2, toughness=2, player="p2")
    engine.rules.deal_damage(me, 2, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert attacker.tapped and attacker.counters.get("stun") == 1


def test_tamiyo_ignores_damage_when_not_the_monarch():
    engine = _game()
    _card(engine, "Tamiyo, Upriser Crowned")
    me = engine.state.player_by_id("p1")
    engine.state.monarch_id = "p2"
    attacker = _filler(engine, "Bear", power=2, toughness=2, player="p2")
    engine.rules.deal_damage(me, 2, source=attacker, combat=True)
    engine.resolve_until_stable()
    assert not attacker.tapped and not attacker.counters.get("stun")


def test_omnath_grows_with_unspent_mana_and_keeps_it_as_colorless():
    engine = _game()
    omnath = _card(engine, "Omnath, Locus of the Void")
    me = engine.state.player_by_id("p1")
    base, base_toughness = omnath.power, omnath.toughness
    me.mana_pool.add_many({"R": 2, "U": 1})
    engine.recompute_continuous_effects()
    assert omnath.power == base + 3 and omnath.toughness == base_toughness + 3
    continuous.empty_mana_pool(engine.state, me)
    assert me.mana_pool.total() == 3 and me.mana_pool.pool["C"] == 3 and me.mana_pool.pool["R"] == 0


def test_omnath_landfall_adds_two_colorless():
    engine = _game()
    _card(engine, "Omnath, Locus of the Void")
    land = _filler(engine, "Forest", type_line="Basic Land — Forest", zone=Zone.HAND)
    land.zone = Zone.BATTLEFIELD
    engine.state.player_by_id("p1").hand[:] = []
    engine.state.add_to_battlefield(land)
    _enter(engine, land)
    assert engine.state.player_by_id("p1").mana_pool.pool["C"] == 2


def test_without_omnath_unspent_mana_still_empties():
    engine = _game()
    me = engine.state.player_by_id("p1")
    me.mana_pool.add("R", 2)
    continuous.empty_mana_pool(engine.state, me)
    assert me.mana_pool.total() == 0


def test_teferis_reproach_shields_and_phases_out_the_opponents_nonland_permanents():
    engine = _game()
    reproach = _card(engine, "Teferi's Reproach", zone=Zone.HAND)
    bear = _filler(engine, "Bear", power=2, toughness=2, player="p2")
    land = _filler(engine, "Island", type_line="Basic Land — Island", player="p2")
    mine = _filler(engine, "Mine", power=1, toughness=1)
    opp = engine.state.player_by_id("p2")
    _cast(engine, reproach, RICH, targets=[opp])
    assert bear.phased_out and not land.phased_out and not mine.phased_out
    life = opp.life
    engine.rules.deal_damage(opp, 3, source=mine)
    engine.rules.gain_life(opp, 5)
    assert opp.life == life
    assert reproach.zone == Zone.EXILE


def test_serras_emissary_protects_you_and_your_creatures_from_the_chosen_type():
    engine = _game()
    emissary = _card(engine, "Serra's Emissary", zone=Zone.HAND)
    mine = _filler(engine, "Mine", power=1, toughness=1)
    theirs = _filler(engine, "Theirs", power=3, toughness=3, player="p2")
    _cast(engine, emissary, RICH)
    assert engine.state.pending_choice["kind"] == "choose_card_type"
    engine.resolve_pending_choice("creatures")
    engine.resolve_until_stable()
    assert emissary.chosen_type == "creatures"
    me = engine.state.player_by_id("p1")
    life = me.life
    engine.rules.deal_damage(me, 3, source=theirs, combat=True)
    assert me.life == life
    engine.rules.deal_damage(mine, 3, source=theirs, combat=True)
    assert mine.damage_marked == 0
    other = engine.state.player_by_id("p2")
    engine.rules.deal_damage(other, 3, source=mine)
    assert other.life == 17


def test_serras_emissary_noncreature_choice_leaves_creature_damage_alone():
    engine = _game()
    emissary = _card(engine, "Serra's Emissary", zone=Zone.HAND)
    theirs = _filler(engine, "Theirs", power=3, toughness=3, player="p2")
    _cast(engine, emissary, RICH)
    engine.resolve_pending_choice("artifacts")
    engine.resolve_until_stable()
    me = engine.state.player_by_id("p1")
    engine.rules.deal_damage(me, 3, source=theirs, combat=True)
    assert me.life == 17


def _stack_library(engine, player, *cards):
    """Put ``cards`` on top of ``player``'s library; the first listed ends up deepest, the last on top."""
    p = engine.state.player_by_id(player)
    for obj in cards:
        p.library[:] = [o for o in p.library if o is not obj]
        obj.zone = Zone.LIBRARY
        p.library.append(obj)


def test_mass_polymorph_exiles_your_creatures_and_reveals_that_many():
    engine = _game()
    poly = _card(engine, "Mass Polymorph", zone=Zone.HAND)
    _filler(engine, "Old A", power=1, toughness=1)
    _filler(engine, "Old B", power=1, toughness=1)
    top_a = _filler(engine, "New A", power=2, toughness=2, zone=Zone.LIBRARY)
    top_b = _filler(engine, "New B", power=2, toughness=2, zone=Zone.LIBRARY)
    top_c = _filler(engine, "New C", power=2, toughness=2, zone=Zone.LIBRARY)
    land = _filler(engine, "Skipped", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    _stack_library(engine, "p1", top_c, land, top_b, top_a)
    _cast(engine, poly, RICH)
    names = sorted(o.name for o in engine.state.battlefield if o.controller_id == "p1")
    assert names == ["New A", "New B"]
    me = engine.state.player_by_id("p1")
    assert top_c in me.library and land in me.library
    assert {o.name for o in engine.state.player_by_id("p1").exile} >= {"Old A", "Old B"}


def test_synthetic_destiny_reveals_at_the_next_end_step():
    engine = _game()
    destiny = _card(engine, "Synthetic Destiny", zone=Zone.HAND)
    _filler(engine, "Old A", power=1, toughness=1)
    new_a = _filler(engine, "New A", power=2, toughness=2, zone=Zone.LIBRARY)
    _stack_library(engine, "p1", new_a)
    _cast(engine, destiny, RICH)
    assert not [o for o in engine.state.battlefield if o.controller_id == "p1"]
    _step(engine, "end")
    assert [o.name for o in engine.state.battlefield if o.controller_id == "p1"] == ["New A"]


def test_proteus_staff_swaps_a_creature_for_the_top_creature_of_its_controller():
    engine = _game()
    staff = _card(engine, "Proteus Staff")
    victim = _filler(engine, "Victim", power=5, toughness=5, player="p2")
    replacement = _filler(engine, "Replacement", power=1, toughness=1, player="p2", zone=Zone.LIBRARY)
    junk = _filler(engine, "Junk", type_line="Basic Land — Forest", player="p2", zone=Zone.LIBRARY)
    _stack_library(engine, "p2", replacement, junk)
    engine.state.player_by_id("p1").mana_pool.add_many({"U": 1, "C": 2})
    _activate(engine, staff, 0, targets=[victim])
    opp = engine.state.player_by_id("p2")
    assert [o.name for o in engine.state.battlefield if o.controller_id == "p2"] == ["Replacement"]
    assert victim in opp.library and opp.library[0] in (victim, junk) and staff.tapped


def test_jhoira_steals_the_first_historic_permanent_and_pays_its_mana_value():
    engine = _game()
    rock = _filler(engine, "Rock", type_line="Artifact", mv=3, player="p2", zone=Zone.LIBRARY)
    land = _filler(engine, "Plain Land", type_line="Basic Land — Forest", player="p2", zone=Zone.LIBRARY)
    bear = _filler(engine, "Under", power=1, toughness=1, player="p2", zone=Zone.LIBRARY)
    _stack_library(engine, "p2", rock, bear, land)
    _put_on_battlefield(engine, "Jhoira, Weatherlight Corsair")
    _answer(engine)
    me = engine.state.player_by_id("p1")
    assert me.life == 17
    stolen = [o for o in engine.state.battlefield if o.name == "Rock"]
    assert stolen and stolen[0].controller_id == "p1"
    opp = engine.state.player_by_id("p2")
    assert land in opp.library and bear in opp.library


def test_plan_for_all_outcomes_lets_the_owner_pick_top_or_bottom():
    engine = _game()
    plan = _card(engine, "Plan for All Outcomes", zone=Zone.HAND)
    victim = _filler(engine, "Victim", power=4, toughness=4, player="p2")
    _cast(engine, plan, RICH)
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(next(str(o["id"]) for o in choice["options"] if "Victim" in str(o.get("label"))))
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p2"
    engine.resolve_pending_choice("bottom")
    opp = engine.state.player_by_id("p2")
    assert victim not in engine.state.battlefield and opp.library[0] is victim


def test_plan_for_all_outcomes_empowers_jace_on_the_first_noncreature_spell_only():
    engine = _game()
    _card(engine, "Plan for All Outcomes")
    first = _filler(engine, "Spell One", type_line="Instant", zone=Zone.HAND)
    second = _filler(engine, "Spell Two", type_line="Instant", zone=Zone.HAND)
    for spell in (first, second):
        engine.state.current_phase, engine.state.current_step = "main", "main1"
        engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", controller_id="p1",
                                          instance_id=spell.instance_id, object=spell.name, card_types=["instant"]))
        engine.resolve_until_stable()
        _answer(engine)
    jaces = [o for o in engine.state.battlefield if "jace" in o.card.name.lower()]
    assert len(jaces) == 1


def test_occult_epiphany_draws_discards_and_makes_a_spirit_per_card_type():
    engine = _game()
    epiphany = _card(engine, "Occult Epiphany", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    hand_land = _filler(engine, "Hand Land", type_line="Basic Land — Forest", zone=Zone.HAND)
    hand_art = _filler(engine, "Hand Rock", type_line="Artifact Creature — Golem", power=1, toughness=1, zone=Zone.HAND)
    _stack_library(engine, "p1")
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    me.mana_pool.add_many({"U": 3})
    engine.cast_spell(me, epiphany, x=2)
    engine.resolve_until_stable()
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if o.get("label") in ("Hand Land", "Hand Rock")), None))
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if o.get("label") in ("Hand Land", "Hand Rock")), None))
    spirits = [o for o in engine.state.battlefield if o.name == "Spirit" and o.controller_id == "p1"]
    discarded = [o for o in me.graveyard if o.name in ("Hand Land", "Hand Rock")]
    assert len(discarded) == 2
    assert len(spirits) == 3  # land + artifact + creature


def test_venser_copies_an_opponents_permanent_twice_and_sacrifices_the_copies():
    engine = _game()
    target = _filler(engine, "Their Bear", power=2, toughness=2, player="p2")
    _put_on_battlefield(engine, "Venser, Fervent Forger")
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if "ermanent" in str(o.get("label"))), None))
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if "Their Bear" in str(o.get("label"))), None))
    copies = [o for o in engine.state.battlefield if o.name == "Their Bear" and o.controller_id == "p1"]
    assert len(copies) == 2 and all(o.is_token for o in copies)
    _step(engine, "end")
    assert not [o for o in engine.state.battlefield if o.name == "Their Bear" and o.controller_id == "p1"]
    assert target in engine.state.battlefield


def test_venser_copies_an_opponents_spell_twice():
    engine = _game()
    bolt = _card(engine, "Lightning Bolt", player="p2", zone=Zone.HAND)
    victim = _filler(engine, "Victim", power=1, toughness=20, player="p1")
    p2 = engine.state.player_by_id("p2")
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    p2.mana_pool.add("R", 1)
    engine.cast_spell(p2, bolt, targets=[victim])
    assert bolt in [i.obj for i in engine.state.stack if getattr(i, "obj", None) is not None]
    _put_on_battlefield(engine, "Venser, Fervent Forger")
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if "opy target" in str(o.get("label"))), None))
    _answer(engine, lambda c: next((str(o["id"]) for o in c["options"] if "Lightning Bolt" in str(o.get("label"))), None))
    engine.resolve_until_stable()
    assert victim.damage_marked == 9  # the Bolt and its two copies


def test_ur_sphinx_eminence_discounts_other_sphinx_spells_from_the_command_zone():
    engine = _game()
    sphinx = _card(engine, "The Ur-Sphinx", zone=Zone.COMMAND)
    other = _filler(engine, "Other Sphinx", type_line="Creature — Sphinx", mv=4, zone=Zone.HAND)
    human = _filler(engine, "Human", type_line="Creature — Human", mv=4, zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    assert continuous.cost_reduction_for(engine.state, me, other)[0] == 1
    assert continuous.cost_reduction_for(engine.state, me, human)[0] == 0
    assert continuous.cost_reduction_for(engine.state, me, sphinx)[0] == 0  # "other" Sphinx spells only


def test_ur_sphinx_attack_mills_each_player_and_offers_a_free_cast_per_player():
    engine = _game()
    sphinx = _card(engine, "The Ur-Sphinx")
    sphinx.card.keywords = list(sphinx.card.keywords)
    _filler(engine, "Mine A", type_line="Creature — Bear", mv=3, power=1, toughness=1, zone=Zone.LIBRARY)
    their = _filler(engine, "Theirs A", type_line="Sorcery", mv=5, player="p2", zone=Zone.LIBRARY)
    mine = next(o for o in engine.state.player_by_id("p1").library if o.name == "Mine A")
    _stack_library(engine, "p1", mine)
    _stack_library(engine, "p2", their)
    engine.state.fire_event(GameEvent(EventType.ATTACKERS_DECLARED, player_id="p1", controller_id="p1",
                                      attacker_ids=[sphinx.instance_id], count=1))
    engine.resolve_until_stable()
    _answer(engine)
    assert mine.zone == Zone.GRAVEYARD and their.zone == Zone.GRAVEYARD
    assert engine.state.free_cast_instance_ids >= {mine.instance_id, their.instance_id}
    assert engine.state.temp_graveyard_cast_permissions[their.instance_id] == "p1"
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    engine.cast_spell(engine.state.player_by_id("p1"), their)  # no mana in the pool: cast for free from the graveyard
    engine.resolve_until_stable()
    assert their.instance_id not in engine.state.free_cast_instance_ids
    assert their.zone != Zone.GRAVEYARD or their in engine.state.player_by_id("p2").graveyard


def test_jace_plus_one_draws_two_and_bottoms_a_chosen_card():
    engine = _game()
    jace = _card(engine, "Jace, Multiverse Architect")
    me = engine.state.player_by_id("p1")
    keep = _filler(engine, "Keep", zone=Zone.HAND)
    put_away = _filler(engine, "Put Away", zone=Zone.HAND)
    _activate(engine, jace, 0)
    options = engine.state.pending_choice["options"]
    pick = next(str(o["id"]) for o in options if o.get("label") == "Put Away")
    engine.resolve_pending_choice(pick)
    assert put_away in me.library and me.library[0] is put_away
    assert keep in me.hand and len(me.hand) == 3  # Keep + two drawn - the bottomed card
    assert jace.counters.get("loyalty") == 5


def test_jace_minus_three_swaps_a_creature_for_the_next_creature_or_planeswalker():
    engine = _game()
    jace = _card(engine, "Jace, Multiverse Architect")
    old = _filler(engine, "Old", power=1, toughness=1)
    new = _filler(engine, "New", power=3, toughness=3, zone=Zone.LIBRARY)
    land = _filler(engine, "Skip", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    _stack_library(engine, "p1", new, land)
    _activate(engine, jace, 1, targets=[old])
    assert old.zone == Zone.EXILE
    assert [o.name for o in engine.state.battlefield if o.name in ("New", "Old")] == ["New"]
    assert land in engine.state.player_by_id("p1").library
    assert jace.counters.get("loyalty") == 1


def _begin_combat_on_p2s_turn(engine):
    engine.state.active_player_index = 1
    engine.state.current_step = "begin_combat"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p2", controller_id="p2"))
    engine.resolve_until_stable()


def test_jace_bars_attacks_on_jaces_when_the_active_opponent_cannot_pay():
    engine = _game()
    jace = _card(engine, "Jace, Multiverse Architect")
    _begin_combat_on_p2s_turn(engine)
    defenders = engine.legal_defenders_for(engine.state.player_by_id("p2"))
    assert all(d.get("instance_id") != jace.instance_id for d in defenders)
    assert any(d["kind"] == "player" and d["id"] == "p1" for d in defenders)


def test_jace_lets_the_active_opponent_pay_two_to_keep_attacking_jaces():
    engine = _game()
    jace = _card(engine, "Jace, Multiverse Architect")
    engine.state.player_by_id("p2").mana_pool.add("C", 2)
    _begin_combat_on_p2s_turn(engine)
    choice = engine.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    defenders = engine.legal_defenders_for(engine.state.player_by_id("p2"))
    assert any(d.get("instance_id") == jace.instance_id for d in defenders)


def test_tamiyo_uses_one_trigger_for_a_combat_damage_batch_and_each_dealer_once():
    engine = _game()
    _card(engine, "Tamiyo, Upriser Crowned")
    engine.state.monarch_id = "p1"
    me = engine.state.player_by_id("p1")
    first = _filler(engine, "First", power=2, toughness=2, player="p2")
    second = _filler(engine, "Second", power=2, toughness=2, player="p2")
    ignored = _filler(engine, "Noncombat", power=2, toughness=2, player="p2")
    with engine.state.simultaneous():
        engine.rules.deal_damage(me, 1, source=first, combat=True)
        engine.rules.deal_damage(me, 1, source=first, combat=True)
        engine.rules.deal_damage(me, 1, source=second, combat=True)
        engine.rules.deal_damage(me, 1, source=ignored, combat=False)
    firings = [a for a, _ in engine.rules.pending_triggers if getattr(a.source, "name", None) == "Tamiyo, Upriser Crowned"]
    assert len(firings) == 1
    engine.state.monarch_id = "p2"  # losing monarch after triggering does not undo the trigger
    engine.resolve_until_stable()
    assert first.tapped and second.tapped
    assert first.counters.get("stun") == second.counters.get("stun") == 1
    assert not ignored.tapped and not ignored.counters.get("stun")
