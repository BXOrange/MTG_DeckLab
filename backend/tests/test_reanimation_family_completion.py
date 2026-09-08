"""Execute-level completion tests for the Regrowth/Reanimate/Deathrite-
adjacent targeted graveyard-recursion family (`game/effects/core.py`'s
`ReturnFromGraveyardEffect`, RULE 701.3) — real cache cards spanning the
family's main axes, to confirm each one actually *completes* (moves the
right card to the right zone, with the right side effects), not just that
it parses or binds.

Sampled from the cache (`docs/implementation-state/Done_Backend.md`'s
"graveyard-card recursion/exile" entry) to cover, in combination:

- **Destination**: hand (Regrowth/Raise Dead) vs. battlefield (Zombify/
  Trash for Treasure/Reanimate).
- **Graveyard scope**: your own (Regrowth/Raise Dead/Zombify/Trash for
  Treasure, all parser-MODELED) vs. *any* graveyard, including an
  opponent's (Reanimate, hand-authored — `target_kind="any_graveyard_
  creature"`).
- **Card-type filter**: any card (Regrowth) vs. creature-only (Raise Dead/
  Zombify/Reanimate) vs. artifact-only (Trash for Treasure).
- **Control**: returns to the card's *owner* (the family's default — the
  only behavior visible when the card is already yours) vs. Reanimate's
  own `under_your_control=True` rider, which only shows a real difference
  when reanimating an *opponent's* card — tested explicitly below,
  along with its `lose_life_equal_mv` life-loss side effect.

Two cards this same investigation turned up as genuinely unplayable today
(neither parser-MODELED nor hand-authored, so `bind_from_catalogue` binds
nothing at all) are deliberately *not* claimed as completing here — see
the module-level TODO note below rather than silently omitting them.

**Persist** ("Return target nonlegendary creature card from your graveyard
to the battlefield **with a -1/-1 counter on it**.") — the "nonlegendary"
supertype exclusion (`TargetSpec.exclude_legendary`) and the "with a -1/-1
counter on it" enters-with rider (`ReturnFromGraveyardEffect.extra_
counters`, placed via `context.add_counters` so a "whenever a -1/-1 counter
is put on a creature" trigger still sees it) are both wired now; covered
below.

Real gap still left for a future session (not fixed here — this suite is
verification, not new modeling):
- **Exhume** ("**Each player** puts a creature card from their graveyard
  onto the battlefield.") — an untargeted, per-player mass effect, a
  different shape from this whole family (no RULE 115 target at all).
  UNMODELED and unauthored today; `bind_from_catalogue` binds nothing for
  it, so nothing here exercises it.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(4)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


def _spell(name, cost, mv, oracle_text, extra_kwargs=None):
    return Card(
        id=name, name=name, type_line="Sorcery", is_sorcery=True,
        mana_cost_string=cost, converted_mana_cost=mv, oracle_text=oracle_text,
        **(extra_kwargs or {}),
    )


def _bind_and_cast(eng, player, spell_card, mana, targets):
    obj = GameObject(spell_card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player.mana_pool.add_many(mana)
    eng.cast_spell(player, obj, targets=targets)
    eng.resolve_until_stable()
    return obj


# ---------------------------------------------------------------------------
# Regrowth — own graveyard, any card type, to hand
# ---------------------------------------------------------------------------


def test_regrowth_is_fully_modeled():
    card = _spell("Test Regrowth", "{1}{G}", 2, "Return target card from your graveyard to your hand.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_regrowth_completes_own_graveyard_to_hand():
    eng = _engine()
    p1 = eng.state.players[0]
    lost_land = GameObject(Card(id="Lost Forest", name="Lost Forest", type_line="Land", is_land=True),
                            owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(lost_land)

    spell = _spell("Test Regrowth 2", "{1}{G}", 2, "Return target card from your graveyard to your hand.")
    _bind_and_cast(eng, p1, spell, {"G": 1, "C": 1}, targets=[lost_land])

    assert lost_land not in p1.graveyard
    assert lost_land in p1.hand


# ---------------------------------------------------------------------------
# Raise Dead — own graveyard, creature only, to hand
# ---------------------------------------------------------------------------


def test_raise_dead_is_fully_modeled():
    card = _spell("Test Raise Dead", "{1}{B}", 2, "Return target creature card from your graveyard to your hand.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_raise_dead_completes_own_graveyard_to_hand():
    eng = _engine()
    p1 = eng.state.players[0]
    dead_bear = GameObject(Card(id="Dead Bear", name="Dead Bear", type_line="Creature — Bear",
                                 is_creature=True, power=2, toughness=2),
                            owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead_bear)

    spell = _spell("Test Raise Dead 2", "{1}{B}", 2,
                    "Return target creature card from your graveyard to your hand.")
    _bind_and_cast(eng, p1, spell, {"B": 1, "C": 1}, targets=[dead_bear])

    assert dead_bear not in p1.graveyard
    assert dead_bear in p1.hand


# ---------------------------------------------------------------------------
# Zombify — own graveyard, creature only, to the battlefield
# ---------------------------------------------------------------------------


def test_zombify_is_fully_modeled():
    card = _spell("Test Zombify", "{2}{B}", 3, "Return target creature card from your graveyard to the battlefield.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_zombify_completes_own_graveyard_to_battlefield():
    eng = _engine()
    p1 = eng.state.players[0]
    dead_bear = GameObject(Card(id="Dead Bear 2", name="Dead Bear 2", type_line="Creature — Bear",
                                 is_creature=True, power=2, toughness=2),
                            owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(dead_bear)

    spell = _spell("Test Zombify 2", "{2}{B}", 3,
                    "Return target creature card from your graveyard to the battlefield.")
    _bind_and_cast(eng, p1, spell, {"B": 1, "C": 2}, targets=[dead_bear])

    assert dead_bear not in p1.graveyard
    assert dead_bear in eng.state.battlefield
    assert dead_bear.controller_id == "p1"


# ---------------------------------------------------------------------------
# Persist — own graveyard, NONLEGENDARY creature only, to the battlefield,
# entering WITH A -1/-1 COUNTER on it
# ---------------------------------------------------------------------------


def test_persist_is_fully_modeled():
    card = _spell("Test Persist", "{1}{B}{G}", 3,
                  "Return target nonlegendary creature card from your graveyard "
                  "to the battlefield with a -1/-1 counter on it.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    effs = [e for s in result.specs for e in (s.effects or [])]
    rfg = next(e for e in effs if e.type == "return_from_graveyard")
    assert rfg.params.get("exclude_legendary") is True
    assert rfg.params.get("extra_counters") == {"kind": "-1/-1", "count": 1}


def test_persist_completes_with_counter_and_excludes_legendary():
    eng = _engine()
    p1 = eng.state.players[0]
    dead_bear = GameObject(Card(id="Persist Bear", name="Persist Bear", type_line="Creature — Bear",
                                is_creature=True, power=3, toughness=3),
                           owner_id="p1", zone=Zone.GRAVEYARD)
    legend = GameObject(Card(id="Persist Legend", name="Persist Legend",
                             type_line="Legendary Creature — Avatar", is_creature=True,
                             is_legendary=True, power=5, toughness=5),
                        owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.extend([dead_bear, legend])

    spell = _spell("Test Persist 2", "{1}{B}{G}", 3,
                   "Return target nonlegendary creature card from your graveyard "
                   "to the battlefield with a -1/-1 counter on it.")
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "G": 1, "C": 1})

    # RULE 205.4a: the legendary creature card in the graveyard is NOT a
    # legal target; the nonlegendary one is.
    from mtg_analyzer.game.targeting import legal_targets
    effect = next(e for e in obj.spell_effects if getattr(e, "target_spec", None) is not None)
    offered = {d["instance_id"] for d in legal_targets(eng.state, "p1", effect.target_spec, source=obj)}
    assert dead_bear.instance_id in offered
    assert legend.instance_id not in offered

    eng.cast_spell(p1, obj, targets=[dead_bear])
    eng.resolve_until_stable()

    assert dead_bear not in p1.graveyard
    assert dead_bear in eng.state.battlefield
    assert dead_bear.controller_id == "p1"
    assert dead_bear.counters.get("-1/-1", 0) == 1
    # 3/3 printed, one -1/-1 counter → 2/2 after the layer pass.
    eng.recompute_continuous_effects()
    assert (dead_bear.power, dead_bear.toughness) == (2, 2)


# ---------------------------------------------------------------------------
# Aberrant Return — ANY graveyard, creature only, enumerated 1/2/3 target
# range, under YOUR control, each entering with a -1/-1 counter
# ---------------------------------------------------------------------------


def test_aberrant_return_is_fully_modeled():
    card = _spell("Test Aberrant Return", "{3}{B}{G}", 5,
                  "Put one, two, or three target creature cards from graveyards onto "
                  "the battlefield under your control. Each of them enters with an "
                  "additional -1/-1 counter on it.")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    rfg = next(e for s in result.specs for e in (s.effects or []) if e.type == "return_from_graveyard")
    assert rfg.params["count"] == 1 and rfg.params["count_max"] == 3
    assert rfg.params["under_your_control"] is True
    assert rfg.params["extra_counters"] == {"kind": "-1/-1", "count": 1}


def test_aberrant_return_completes_from_opponent_graveyard_with_counters():
    eng = _engine()
    p1, p2 = eng.state.players[0], eng.state.players[1]
    corpses = []
    for i, owner in enumerate((p1, p2, p2)):
        obj = GameObject(Card(id=f"Corpse{i}", name=f"Corpse{i}",
                              type_line="Creature — Zombie", is_creature=True,
                              power=3, toughness=3),
                         owner_id=owner.id, zone=Zone.GRAVEYARD)
        owner.graveyard.append(obj)
        corpses.append(obj)

    spell = _spell("Test Aberrant Return 2", "{3}{B}{G}", 5,
                   "Put one, two, or three target creature cards from graveyards onto "
                   "the battlefield under your control. Each of them enters with an "
                   "additional -1/-1 counter on it.")
    _bind_and_cast(eng, p1, spell, {"B": 1, "G": 1, "C": 3}, targets=corpses)

    for obj in corpses:
        assert obj in eng.state.battlefield
        assert obj.controller_id == "p1"  # under YOUR control, even p2's cards
        assert obj.counters.get("-1/-1", 0) == 1
    eng.recompute_continuous_effects()
    assert (corpses[0].power, corpses[0].toughness) == (2, 2)


# ---------------------------------------------------------------------------
# Trash for Treasure — own graveyard, artifact only, to the battlefield,
# with its own additional cost (sacrifice an artifact)
# ---------------------------------------------------------------------------


def test_trash_for_treasure_completes_with_its_additional_cost():
    eng = _engine()
    p1 = eng.state.players[0]
    dead_artifact = GameObject(
        Card(id="Dead Artifact", name="Dead Artifact", type_line="Artifact"),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    p1.graveyard.append(dead_artifact)
    sac_fodder = GameObject(
        Card(id="Sac Fodder", name="Sac Fodder", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(sac_fodder)

    spell = _spell(
        "Test Trash for Treasure", "{2}{R}", 3,
        "As an additional cost to cast this spell, sacrifice an artifact.\n"
        "Return target artifact card from your graveyard to the battlefield.",
    )
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 1, "C": 2})
    eng.cast_spell(p1, obj, targets=[dead_artifact], sacrifice_choice=sac_fodder.instance_id)
    eng.resolve_until_stable()

    assert sac_fodder not in eng.state.battlefield  # paid as the additional cost
    assert dead_artifact not in p1.graveyard
    assert dead_artifact in eng.state.battlefield


# ---------------------------------------------------------------------------
# Reanimate — ANY graveyard (including an opponent's), creature only,
# always under YOUR control, plus its life-loss rider
# ---------------------------------------------------------------------------


def test_reanimate_is_hand_authored():
    from mtg_analyzer.game.ability_catalogue import specs_for

    card = Card(id="Reanimate", name="Reanimate", type_line="Instant", is_instant=True,
                mana_cost_string="{B}", converted_mana_cost=1,
                oracle_text="Put target creature card from a graveyard onto the battlefield "
                            "under your control. You lose life equal to that card's mana value.")
    specs = specs_for(card)
    assert specs, "Reanimate should resolve via the hand-authored catalogue"


def test_reanimate_from_your_own_graveyard():
    eng = _engine()
    p1 = eng.state.players[0]
    big_creature = GameObject(
        Card(id="Big Creature", name="Big Creature", type_line="Creature — Giant",
             is_creature=True, power=6, toughness=6, mana_cost_string="{4}{R}{R}",
             converted_mana_cost=6),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    p1.graveyard.append(big_creature)

    spell = Card(id="Test Reanimate", name="Reanimate", type_line="Instant", is_instant=True,
                 mana_cost_string="{B}", converted_mana_cost=1,
                 oracle_text="Put target creature card from a graveyard onto the battlefield "
                             "under your control. You lose life equal to that card's mana value.")
    _bind_and_cast(eng, p1, spell, {"B": 1}, targets=[big_creature])

    assert big_creature not in p1.graveyard
    assert big_creature in eng.state.battlefield
    assert big_creature.controller_id == "p1"
    assert p1.life == 14  # 20 - 6 (the reanimated creature's mana value)


def test_reanimate_from_an_opponents_graveyard_takes_control():
    eng = _engine()
    p1, p2 = eng.state.players
    opponents_creature = GameObject(
        Card(id="Opponent's Giant", name="Opponent's Giant", type_line="Creature — Giant",
             is_creature=True, power=5, toughness=5, mana_cost_string="{3}{R}{R}",
             converted_mana_cost=5),
        owner_id="p2", zone=Zone.GRAVEYARD,
    )
    p2.graveyard.append(opponents_creature)

    spell = Card(id="Test Reanimate 2", name="Reanimate", type_line="Instant", is_instant=True,
                 mana_cost_string="{B}", converted_mana_cost=1,
                 oracle_text="Put target creature card from a graveyard onto the battlefield "
                             "under your control. You lose life equal to that card's mana value.")
    _bind_and_cast(eng, p1, spell, {"B": 1}, targets=[opponents_creature])

    assert opponents_creature not in p2.graveyard
    assert opponents_creature in eng.state.battlefield
    # RULE 701.3: control is p1's (the "under your control" rider), even
    # though p2 still *owns* the card.
    assert opponents_creature.controller_id == "p1"
    assert opponents_creature.owner_id == "p2"
    assert p1.life == 15  # 20 - 5


# ---------------------------------------------------------------------------
# Known gaps in this family — verified UNMODELED/unauthored, not fixed here
# ---------------------------------------------------------------------------


def test_exhume_is_not_yet_modeled_or_authored():
    from mtg_analyzer.game.ability_catalogue import specs_for

    card = Card(id="Exhume", name="Exhume", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{B}", converted_mana_cost=1,
                oracle_text="Each player puts a creature card from their graveyard onto the battlefield.")
    result = parse_oracle(card)
    assert not result.modeled
    assert not specs_for(card)
