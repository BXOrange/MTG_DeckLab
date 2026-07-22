"""cEDH cube batch 25, wave 4 — naming a card, and the three loop shapes.

Four engine shapes that each had their own entry on the blocker list:

* **naming a card** (`RulesEngine.request_name_card`) — the only choice
  whose answer space isn't enumerable from game state. Demonic Consultation.
* **dig-until-a-predicate** (`RulesEngine.dig_until`) — the cascade dig with
  the predicate and both destinations made parameters.
* **repeat-until-a-predicate** (`MillUntilCreatureEffect`) — every other
  repetition primitive had its count fixed before it started. Helm of
  Obedience.
* **an open-ended loop** (`request_look_top_pay_life_loop`) — bounded by its
  own life payment rather than any counter. Lim-Dûl's Vault.

Plus `ScrambleSpellEffect` (Possibility Storm / Tibalt's Trickery), which
answers a spell and then digs *its controller's* library.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state, p1, p2


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _card(name, type_line="Instant", cost="{R}", cmc=1, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _creature(name="Bear"):
    return _card(name, "Creature — Bear", "{1}{G}", 2, power=2, toughness=2)


def _stack_library(player, cards):
    """Put ``cards`` into ``player``'s library, last element on top."""
    for card in cards:
        obj = GameObject(card, owner_id=player.id, zone=Zone.LIBRARY)
        player.add_to_zone(obj, Zone.LIBRARY)


def _catalogue_obj(name, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(_named(name), owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# Demonic Consultation — naming a card + a parameterized dig
# ---------------------------------------------------------------------------


def _cast_consultation(engine, state, p1):
    spell = _catalogue_obj("Demonic Consultation", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("B", 1)
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    return spell


def test_demonic_consultation_asks_for_a_card_name_first():
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card(f"Card{i}") for i in range(10)])

    _cast_consultation(engine, state, p1)

    choice = state.pending_choice
    assert choice["kind"] == "name_card"
    assert choice["free_text"] is True
    # The offered names are *suggestions* off what this player can see.
    assert "Card0" in {o["id"] for o in choice["options"]}


def test_demonic_consultation_exiles_six_then_digs_to_the_named_card():
    engine, state, p1, _ = _engine()
    # Library, bottom → top: six filler, then the target, then more filler.
    _stack_library(
        p1,
        [_card(f"Deep{i}") for i in range(4)]
        + [_card("Target")]
        + [_card(f"Top{i}") for i in range(6)],
    )
    _cast_consultation(engine, state, p1)

    engine.resolve_pending_choice("Target")

    target = next(o for o in p1.hand if o.name == "Target")
    assert target.zone == Zone.HAND
    # Six exiled up front, then everything revealed on the way down.
    assert len(p1.exile) == 6
    assert "Target" not in {o.name for o in p1.exile}


def test_naming_a_card_that_is_not_there_exiles_the_whole_library():
    """Not a degenerate case but the actual cEDH line — Consultation into an
    empty library, then Thassa's Oracle wins on it."""
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card(f"Card{i}") for i in range(10)])

    _cast_consultation(engine, state, p1)
    engine.resolve_pending_choice("Nothing In My Deck")

    assert p1.library == []
    assert len(p1.exile) == 10


def test_an_arbitrary_named_string_is_only_ever_compared_never_interpreted():
    """The naming choice is the one place a free-form string enters the
    engine; it reaches nothing but `card_query`'s name comparison."""
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card("Real") for _ in range(8)])

    _cast_consultation(engine, state, p1)
    engine.resolve_pending_choice("{'type': 'Creature'}")

    assert p1.library == []  # matched nothing; no criteria were smuggled in


# ---------------------------------------------------------------------------
# Helm of Obedience — repeat until a predicate holds
# ---------------------------------------------------------------------------


def test_helm_of_obedience_stops_at_the_first_creature_and_steals_it():
    engine, state, p1, p2 = _engine()
    helm = _catalogue_obj("Helm of Obedience")
    state.add_to_battlefield(helm)
    # p2's library, top-down: filler, filler, creature.
    _stack_library(p2, [_card("Deep"), _creature("Prize"), _card("Filler1"), _card("Filler2")])

    p1.mana_pool.add("C", 10)  # {X}, X = 10
    engine.activate_ability(p1, helm, 0, targets=[p2], x=10)
    engine.resolve_until_stable()

    prize = next(o for o in state.battlefield if o.name == "Prize")
    assert prize.controller_id == "p1"     # RULE 110.2: under *your* control
    assert helm in p1.graveyard            # sacrificed itself
    assert len(p2.graveyard) == 2          # stopped the moment it hit


def test_helm_of_obedience_stops_at_x_with_no_creature_found():
    engine, state, p1, p2 = _engine()
    helm = _catalogue_obj("Helm of Obedience")
    state.add_to_battlefield(helm)
    _stack_library(p2, [_card(f"Filler{i}") for i in range(10)])

    p1.mana_pool.add("C", 3)
    engine.activate_ability(p1, helm, 0, targets=[p2], x=3)
    engine.resolve_until_stable()

    assert len(p2.graveyard) == 3
    assert helm in state.battlefield  # not sacrificed — nothing was found


def test_helm_of_obedience_with_x_zero_does_nothing():
    """"X can't be 0." — the same guard that makes the loop bounded."""
    engine, state, p1, p2 = _engine()
    helm = _catalogue_obj("Helm of Obedience")
    state.add_to_battlefield(helm)
    _stack_library(p2, [_creature("Prize")])

    engine.activate_ability(p1, helm, 0, targets=[p2], x=0)
    engine.resolve_until_stable()

    assert p2.graveyard == []
    assert helm in state.battlefield


def test_helm_of_obedience_stops_on_an_empty_library():
    """The loop's second bound — it can't spin on a library that runs out."""
    engine, state, p1, p2 = _engine()
    helm = _catalogue_obj("Helm of Obedience")
    state.add_to_battlefield(helm)
    _stack_library(p2, [_card("Only")])

    p1.mana_pool.add("C", 50)
    engine.activate_ability(p1, helm, 0, targets=[p2], x=50)
    engine.resolve_until_stable()

    assert len(p2.graveyard) == 1
    assert p2.library == []


# ---------------------------------------------------------------------------
# Lim-Dûl's Vault — an open-ended loop bounded by its own payment
# ---------------------------------------------------------------------------


def _cast_vault(engine, state, p1):
    spell = _catalogue_obj("Lim-Dûl's Vault", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("B", 1)
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    return spell


def test_lim_duls_vault_offers_the_loop_and_re_opens_it_after_each_iteration():
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card(f"Card{i}") for i in range(20)])

    _cast_vault(engine, state, p1)
    assert state.pending_choice["kind"] == "look_top_pay_life"
    assert len(state.pending_choice["looking_at"]) == 5

    engine.rules.resolve_look_top_pay_life_loop_choice("again")
    assert p1.life == 19
    assert state.pending_choice["kind"] == "look_top_pay_life"  # re-opened

    engine.rules.resolve_look_top_pay_life_loop_choice("again")
    assert p1.life == 18
    assert state.pending_choice["kind"] == "look_top_pay_life"


def test_stopping_the_vault_loop_shuffles_then_restores_the_last_batch_on_top():
    """RULE 701.19e's ordering — the other order would scatter the very
    cards the card promises to leave on top."""
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card(f"Card{i}") for i in range(20)])

    _cast_vault(engine, state, p1)
    top_five = [o.name for o in p1.library[-5:]]

    engine.rules.resolve_look_top_pay_life_loop_choice("decline")

    assert state.pending_choice is None
    assert [o.name for o in p1.library[-5:]] == top_five
    assert p1.life == 20  # stopping costs nothing


def test_the_vault_loop_is_bounded_by_the_life_payment():
    """The loop has no counter at all — RULE 118.4's "you can't pay more life
    than you have" is the entire bound, so it is simply never offered at 1
    life."""
    engine, state, p1, _ = _engine()
    _stack_library(p1, [_card(f"Card{i}") for i in range(20)])
    p1.life = 1

    _cast_vault(engine, state, p1)

    assert state.pending_choice is None


# ---------------------------------------------------------------------------
# Tibalt's Trickery / Possibility Storm — answer a spell, dig its controller
# ---------------------------------------------------------------------------


def test_tibalts_trickery_counters_and_digs_the_casters_library():
    engine, state, p1, p2 = _engine()
    # Every card is a legal hit, so the random 1–3 mill can't change the
    # outcome under test (that the dig ran against *p2* and cast for free).
    _stack_library(p2, [_card(f"Filler{i}") for i in range(12)])
    victim = GameObject(_card("Big Spell", "Sorcery", "{5}", 5), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 5)
    engine.rules.cast_spell(p2, victim)

    trickery = _catalogue_obj("Tibalt's Trickery", controller="p1", zone=Zone.HAND)
    p1.add_to_zone(trickery, Zone.HAND)
    p1.mana_pool.add("R", 2)  # {1}{R}
    engine.rules.cast_spell(p1, trickery, targets=[victim])
    engine.rules.resolve_top_of_stack()

    assert victim in p2.graveyard                    # countered
    assert victim not in [i.obj for i in state.stack]
    # The dig ran against *p2*'s library, not the caster's, and the hit is
    # *offered* to them from exile ("they **may** cast that card") rather
    # than force-cast.
    hit = next(o for o in p2.exile if o.instance_id in state.free_cast_instance_ids)
    assert hit.name.startswith("Filler")
    assert hit.owner_id == "p2"            # *they* may cast it, not you
    assert p1.library == []                # your own library was never touched
    # RULE 603.7: uncast, it goes to the bottom of their library at the
    # next end step — the printed "if they don't cast it" fallback.
    assert any(
        d.step == "end" and d.controller_id == "p2" for d in state.delayed_triggers
    )


def test_tibalts_trickery_never_finds_a_card_with_the_same_name():
    """The `not_name` criteria key — the negated form of an exact match."""
    engine, state, p1, p2 = _engine()
    # Bottom → top: one legal hit, then nothing but same-named decoys, so the
    # dig has to skip every one of them however far the random mill got.
    _stack_library(
        p2,
        [_card("Other")] + [_card("Big Spell", "Sorcery", "{5}", 5) for _ in range(8)],
    )
    victim = GameObject(_card("Big Spell", "Sorcery", "{5}", 5), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(victim, Zone.HAND)
    p2.mana_pool.add("R", 5)
    engine.rules.cast_spell(p2, victim)

    trickery = _catalogue_obj("Tibalt's Trickery", controller="p1", zone=Zone.HAND)
    p1.add_to_zone(trickery, Zone.HAND)
    p1.mana_pool.add("R", 2)  # {1}{R}
    engine.rules.cast_spell(p1, trickery, targets=[victim])
    engine.rules.resolve_top_of_stack()

    # Every same-named copy was skipped; "Other" at the bottom was the hit —
    # offered from exile ("they **may** cast it"), not force-cast.
    hit = next(o for o in p2.exile if o.name == "Other")
    assert hit.instance_id in state.free_cast_instance_ids
    assert not any(
        i.obj is not None and i.obj.name == "Big Spell" for i in state.stack
    )


def test_possibility_storm_exiles_the_spell_rather_than_countering_it():
    """"That player exiles it" is a zone change, not a counter — which is
    exactly why Possibility Storm gets around "can't be countered"."""
    engine, state, p1, p2 = _engine()
    storm = _catalogue_obj("Possibility Storm")
    state.add_to_battlefield(storm)
    _stack_library(p2, [_card("Deep"), _card("Match", "Instant")])

    spell = GameObject(_card("Bolt", "Instant"), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(spell, Zone.HAND)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, spell)

    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    assert spell.zone == Zone.EXILE
    assert spell not in p2.graveyard  # exiled, never countered
    hit = next(o for o in p2.exile if o.name == "Match")
    assert hit.instance_id in state.free_cast_instance_ids


def test_possibility_storm_only_fires_on_a_cast_from_hand():
    engine, state, p1, p2 = _engine()
    storm = _catalogue_obj("Possibility Storm")
    state.add_to_battlefield(storm)

    from_graveyard = GameObject(_card("Bolt", "Instant"), owner_id="p2", zone=Zone.GRAVEYARD)
    p2.add_to_zone(from_graveyard, Zone.GRAVEYARD)
    p2.mana_pool.add("R", 1)
    engine.rules.cast_spell(p2, from_graveyard)

    assert engine.rules.pending_triggers == []


def test_possibility_storm_digs_for_a_shared_card_type():
    """RULE 205.2 — read off the answered spell's own types, snapshotted
    before it leaves the stack."""
    engine, state, p1, p2 = _engine()
    storm = _catalogue_obj("Possibility Storm")
    state.add_to_battlefield(storm)
    # Top-down: a sorcery (no shared type), then a creature (shared).
    _stack_library(p2, [_creature("Match"), _card("Miss", "Sorcery", "{2}", 2)])

    spell = GameObject(_creature("Grizzly"), owner_id="p2", zone=Zone.HAND)
    p2.add_to_zone(spell, Zone.HAND)
    p2.mana_pool.add("G", 2)
    engine.rules.cast_spell(p2, spell)

    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()

    hit = next(o for o in p2.exile if o.name == "Match")
    assert hit.instance_id in state.free_cast_instance_ids
