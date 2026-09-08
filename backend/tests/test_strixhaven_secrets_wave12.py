"""Secrets of Strixhaven — playability batch, wave 12.

Wave 12: the three remaining modal Charm/Command deck spells, hand-authored
wholesale in `ability_catalogue/strixhaven_commander.py` (the fail-closed parser
claims most modes but each has one mode on a family the grammar can't reach,
so the whole "choose N —" block fail-closes):

* **Quandrix Command** — new `ShuffleTargetGraveyardCardsIntoLibraryEffect`
  ("shuffle_target_graveyard_cards_into_library") for mode 4.
* **Lorehold Charm** — `return_from_graveyard` over the existing
  ``graveyard_artifact_or_creature`` kind + ``max_mana_value`` for mode 2.
* **Witherbloom Command** — new ``noncreature_nonland_permanent`` target
  kind for mode 2; a `mill` + `return_from_graveyard` compound for mode 1.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _bind(name):
    card = _db().get_card(name)
    obj = GameObject(card=card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    return obj


def test_all_three_registered():
    for name in ("Quandrix Command", "Lorehold Charm", "Witherbloom Command"):
        assert is_registered(name), name


def test_quandrix_command_modes():
    obj = _bind("Quandrix Command")
    assert obj.spell_modes_choose == 2
    kinds = [[e.__class__.__name__ for e in m["effects"]] for m in obj.spell_modes]
    assert ["ReturnToHandEffect"] in kinds
    assert ["CounterSpellEffect"] in kinds
    assert ["AddCountersEffect"] in kinds
    assert ["ShuffleTargetGraveyardCardsIntoLibraryEffect"] in kinds


def test_lorehold_charm_modes():
    obj = _bind("Lorehold Charm")
    assert obj.spell_modes_choose == 1
    kinds = [[e.__class__.__name__ for e in m["effects"]] for m in obj.spell_modes]
    assert ["SacrificeEffect"] in kinds
    assert ["ReturnFromGraveyardEffect"] in kinds
    assert ["PumpEffect"] in kinds
    rfg = next(m["effects"][0] for m in obj.spell_modes
              if m["effects"][0].__class__.__name__ == "ReturnFromGraveyardEffect")
    assert rfg.target_spec.kind == "graveyard_artifact_or_creature"
    assert rfg.target_spec.max_mana_value == 2
    assert rfg.destination == "battlefield"


def test_witherbloom_command_modes():
    obj = _bind("Witherbloom Command")
    assert obj.spell_modes_choose == 2
    kinds = [[e.__class__.__name__ for e in m["effects"]] for m in obj.spell_modes]
    assert ["MillEffect", "ReturnFromGraveyardEffect"] in kinds
    assert ["DestroyEffect"] in kinds
    assert ["PumpEffect"] in kinds
    assert ["LoseLifeEffect", "GainLifeEffect"] in kinds


def test_quandrix_command_shuffle_mode_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    src = GameObject(card=Card(id="s", name="QC", type_line="Instant", is_instant=True),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    for i in range(4):
        c = GameObject(card=Card(id=f"g{i}", name=f"Dead{i}",
                                 type_line="Creature — Zombie", is_creature=True,
                                 power=1, toughness=1),
                       owner_id=p2.id, zone=Zone.GRAVEYARD)
        c.zone = Zone.GRAVEYARD
        p2.graveyard.append(c)
    lib0, gy0 = len(p2.library), len(p2.graveyard)
    eff = EffectRegistry.create("shuffle_target_graveyard_cards_into_library",
                                {"count_max": 3})
    eff.source = src
    eff.apply(eng.rules.context, targets=[p2])
    picked = 0
    while (eng.state.pending_choice
           and eng.state.pending_choice.get("kind") == "choose_objects"
           and picked < 3):
        opts = [o for o in eng.state.pending_choice["options"] if o["id"] != "decline"]
        if not opts:
            break
        eng.rules.resolve_choose_objects_choice(opts[0]["instance_id"])
        picked += 1
    if (eng.state.pending_choice
            and eng.state.pending_choice.get("kind") == "choose_objects"):
        eng.rules.resolve_choose_objects_choice(None)
    assert len(p2.graveyard) == gy0 - 3
    assert len(p2.library) == lib0 + 3


def test_noncreature_nonland_permanent_target_kind():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players

    def mk(oid, name, tl, cmc, **kw):
        o = GameObject(card=Card(id=oid, name=name, type_line=tl,
                                 mana_cost_string="{%d}" % cmc, **kw),
                       owner_id=p2.id, zone=Zone.BATTLEFIELD)
        o.controller_id = p2.id
        o.card.converted_mana_cost = cmc
        return o

    signet = mk("a", "Signet", "Artifact", 2)
    big = mk("b", "BigArt", "Artifact", 5)
    artcre = mk("c", "ArtCre", "Artifact Creature — Golem", 2,
                is_creature=True, power=2, toughness=2)
    aura = mk("e", "Aura", "Enchantment", 1)
    land = mk("l", "Weird Land", "Land", 0)
    for o in (signet, big, artcre, aura, land):
        eng.state.add_to_battlefield(o)
    src = GameObject(card=Card(id="s2", name="WC", type_line="Sorcery", is_sorcery=True),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    names = sorted(
        t["name"] for t in legal_targets(
            eng.state, p1.id,
            TargetSpec(kind="noncreature_nonland_permanent", max_mana_value=2), src)
    )
    assert names == ["Aura", "Signet"]
