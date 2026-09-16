from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lore_drakkis() -> list[AbilitySpec]:
    """Mutate {U/R}{U/R}
    Whenever this creature mutates, return target instant or sorcery card
    from your graveyard to your hand.

    — Lore Drakkis. **Mutate (RULE 702.140)** is now a real cast mode rather
    than a recognized-but-inert keyword:

    * the Mutate cost is an *alternative* cast cost (`GameEngine.
      _mutate_cost`), substituted the same way Flashback/Escape already
      substitute theirs;
    * a mutate cast targets a creature you own and, on resolution, merges
      onto it instead of entering the battlefield
      (`RulesEngine.mutate_onto`). The **host** stays the surviving
      `GameObject`, which is what RULE 702.140c requires — the merged
      permanent is the *same* permanent, so counters, damage, Auras and
      summoning sickness all carry over, and no enters-the-battlefield
      trigger fires;
    * "the creature on top plus all abilities from under it" is modeled by
      banking whichever card ends up *underneath* on `GameObject.
      merged_oracle_text` and re-deriving abilities through the ordinary
      bind path — so the pile keeps accumulating abilities as further
      creatures mutate onto it, and mutate needs no ability-construction
      code of its own. Both directions of "over **or** under" work: which
      one applies is chosen as the spell is cast (RULE 702.140a,
      `GameObject.mutate_under`), and only which card supplies the printed
      face changes.
    * `EventType.MUTATES` then gives "whenever this creature mutates"
      something to trigger on — deliberately distinct from
      ENTERS_BATTLEFIELD, which mutate specifically does not fire.

    * the host is validated against a real ``non_human_creature_you_own``
      target kind (RULE 702.140a) — ownership rather than control (RULE
      108.3), and Humans genuinely excluded. Checked by `GameEngine.
      can_cast`/`_cast_current_face` directly, since a mutate creature
      spell carries no targeting *effect* for the ordinary RULE 115
      machinery to read.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_instant_or_sorcery",
                "destination": "hand",
            })],
            trigger={
                "event": EventType.MUTATES,
                "condition": {"subject": "self"},
            },
        ),
    ]


register("Lore Drakkis", _lore_drakkis)
