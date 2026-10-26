"""Player designations, the Ring and emblems."""
from __future__ import annotations

from typing import Any
from ...models.game.emblem import Emblem
from ...models.game.events import EventType, GameEvent
from ...models.game.player import Player
from .. import continuous
from ..effects.core import ReplacementEffect, ActivatedAbility, StaticAbility, TriggeredAbility
from .. import continuations


class DesignationsMixin:
    """Player designations, the Ring and emblems."""

    def become_monarch(self, player: Player) -> None:
        """RULE 725.3: ``player`` becomes the monarch; whoever held it
        (possibly ``player`` themself) ceases to."""
        self.state.monarch_id = player.id
        # "…until an opponent becomes the monarch" (Palace Jailer): the exiler's creature comes back under its owner's
        # control once a *different* player takes the crown.
        for holder in self.state.players:
            for obj in list(holder.exile):
                exiler = getattr(obj, "exiled_until_opponent_monarch_of", None)
                if exiler is not None and exiler != player.id:
                    obj.exiled_until_opponent_monarch_of = None
                    self.return_from_graveyard(obj, "battlefield")

    def start_engines(self, player: Player) -> None:
        """RULE 702.179a/c: ``player``'s speed becomes 1 if they currently
        have no speed. Idempotent — a no-op once they have any speed at all
        (the SBA that calls this re-checks every pass)."""
        if int(getattr(player, "speed", 0) or 0) == 0:
            player.speed = 1

    def increase_speed(self, player: Player, amount: int = 1) -> None:
        """RULE 702.179c/d: raise ``player``'s speed by ``amount``, capped at
        the maximum of 4 (RULE 702.179e). A player with no speed who is told
        to increase it has their speed *become* that amount (702.179c)."""
        current = int(getattr(player, "speed", 0) or 0)
        player.speed = min(4, (amount if current == 0 else current + amount))
    def get_city_blessing(self, player: Player) -> None:
        """RULE 702.131a-c: ``player`` gets the city's blessing.

        Unlike Monarch/Initiative this is a plain idempotent per-player flag
        rather than a single shared holder — "any number of players may have
        the city's blessing at the same time", and once granted it lasts
        "for the rest of the game" (702.131c/d), so a second Ascend firing
        while the player already has it is simply a no-op, same as
        `monstrosity`'s "isn't monstrous" gate rather than `take_initiative`'s
        unconditional re-fire.
        """
        if player.has_city_blessing:
            return
        player.has_city_blessing = True
    def get_enduring_story(self, player: Player) -> None:
        """RULE 702.195a-b: ``player`` gets the enduring story designation —
        Storied's own onetime per-player flag (PAR-51), the exact same
        idempotent shape as `get_city_blessing` above (any number of
        players may have it at once, and it lasts for the rest of the
        game once granted)."""
        if player.has_enduring_story:
            return
        player.has_enduring_story = True
    def take_initiative(self, player: Player) -> None:
        """RULE 726.3: ``player`` takes the initiative; whoever held it
        (possibly ``player`` themself) ceases to.

        RULE 726.5: a player who *already* has the initiative and is told to
        take it doesn't gain a second designation, but the "whenever a player
        takes the initiative" ability still triggers — which is why the event
        is announced unconditionally rather than only on a change of holder.
        """
        self.state.initiative_id = player.id
        self.state.fire_event(
            GameEvent(
                EventType.TOOK_INITIATIVE, player_id=player.id, controller_id=player.id
            )
        )
    def the_ring_tempts_you(self, player: Player) -> None:
        """RULE 701.51a: the Ring tempts ``player``.

        Two things happen, in this order. First the Ring emblem gains its
        next ability (`Player.ring_level`, capped at 4 — RULE 701.51b: a
        fifth temptation adds nothing, it still just re-chooses the bearer).
        The level *is* the emblem: unlike a RULE 114 emblem there's no
        quoted card text to parse, the four abilities are fixed by the rules
        and all read live state, so nothing is created in the command zone.

        Then RULE 701.52a's Ring-bearer choice: "you choose a creature you
        control as your Ring-bearer". Mandatory when the player controls a
        creature (the previous bearer may be re-chosen, and with exactly one
        candidate the choice is forced, so it's made outright); with 2+
        candidates it's a genuine `ring_bearer` `pending_choice`. Controlling
        no creature means no bearer at all — the emblem's abilities simply
        have nothing to apply to until the next temptation picks one.

        Finally fires `EventType.RING_TEMPTED` (for "whenever the Ring
        tempts you, `<effect>`" triggers) once ``ring_bearer_id`` is
        settled — immediately for the 0/1-candidate paths here, or from
        `_resume_ring_bearer` once the interactive pick resolves, so
        a trigger reading "if you chose a creature other than ~" always
        sees the final bearer.
        """
        player.ring_level = min(4, int(getattr(player, "ring_level", 0) or 0) + 1)
        candidates = [
            obj for obj in self.state.permanents_controlled_by(player.id) if obj.is_creature
        ]
        if not candidates:
            player.ring_bearer_id = None
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
            return
        if len(candidates) == 1:
            player.ring_bearer_id = candidates[0].instance_id
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
            return
        self.open_choice({
            "kind": "ring_bearer",
            "player_id": player.id,
            "prompt": "Wähle eine Kreatur als deinen Ringträger (RULE 701.52a).",
            "options": [
                {
                    "id": str(obj.instance_id),
                    "label": obj.name,
                    "instance_id": obj.instance_id,
                }
                for obj in candidates
            ],
        })
    @continuations.choice(
        "ring_bearer",
        answer=continuations.ANSWER_INT_REQUIRED,
        rule="701.52",
    )
    def _resume_ring_bearer(self, choice: dict[str, Any], instance_id: int) -> None:
        """Answer a pending `ring_bearer` choice (RULE 701.52a).

        Not optional — the choice only ever opens when the player controls
        2+ creatures, and RULE 701.52a makes choosing mandatory then.
        """
        allowed = {o["instance_id"] for o in choice["options"]}
        if instance_id not in allowed:
            raise ValueError(f"{instance_id} is not a legal Ring-bearer")
        player = self.state.player_by_id(choice["player_id"])
        if player is not None:
            player.ring_bearer_id = instance_id
            # `the_ring_tempts_you`'s own RING_TEMPTED firing is deferred to
            # here for this 2+-candidate path — a "whenever the Ring tempts
            # you, if you chose a creature other than ~ as your Ring-bearer,
            # …" trigger (Aragorn, Company Leader/Faramir, Field Commander)
            # needs `ring_bearer_id` already settled when it fires, and this
            # is the only point that's true for an interactive choice.
            self.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id=player.id))
    def _sweep_ring_bearer(self) -> None:
        """RULE 701.52d: a Ring-bearer that stops being a creature its
        designator controls stops being the Ring-bearer. Run as part of the
        SBA pass, next to the Soulbond sweep, since both are "the state that
        made this designation true is gone" cleanups rather than anything a
        player did."""
        for player in self.state.players:
            if player.ring_bearer_id is None:
                continue
            if continuous.ring_bearer_of(self.state, player) is None:
                player.ring_bearer_id = None
    def create_emblem(self, player: Player, ability: dict) -> None:
        """RULE 114.2/114.4: bind the emblem's already-parsed quoted
        ability (or, for ``ability`` being a *list* of ability dicts —
        "You get an emblem with 'A' and 'B'.", You Compleat Me — every one
        of them) into live `TriggeredAbility`/`StaticAbility`/`ActivatedAbility`
        objects on a single `Emblem` and file it in ``player``'s command
        zone.

        Binding happens here — once, at resolve time — rather than at
        bind-on-load like every other ability, because an emblem has no
        permanent to bind *onto*: `effect_binder.bind_ability` is imported
        lazily (it imports `game/effects/core.py`, which this module also feeds
        into, so a module-level import would cycle) and given a synthetic
        `Emblem` as its ``source`` instead of a `GameObject` (`models/
        emblem.py` — carries just enough, ``controller_id``/``timestamp``,
        for the existing "you control"/layer-ordering machinery to work
        unchanged).
        """
        from ...parser.oracle.spec import AbilitySpec
        from ..binding.core import bind_ability
        from ..effects.core import GraveyardCastPermissionEffect

        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        emblem = Emblem(controller_id=player.id, timestamp=self.state._timestamp_counter)
        ability_dicts = ability if isinstance(ability, list) else [ability]
        descriptions: list[str] = []
        for one in ability_dicts:
            spec = AbilitySpec.from_dict(one)
            if spec.raw_text:
                descriptions.append(spec.raw_text)
            bound = bind_ability(spec, source=emblem)
            if isinstance(bound, TriggeredAbility):
                emblem.triggered_abilities.append(bound)
            elif isinstance(bound, ActivatedAbility):
                # RULE 114.4 — "functions in the command zone" covers an
                # activated ability too (MEC-8); previously dropped silently
                # since only the triggered/static branches were handled here.
                emblem.activated_abilities.append(bound)
            elif isinstance(bound, list):
                for effect in bound:
                    if isinstance(effect, (StaticAbility, GraveyardCastPermissionEffect)):
                        # RULE 114.4: standing play permissions also function
                        # from the command zone; their own scanners read these.
                        emblem.static_effects.append(effect)
                    elif isinstance(effect, TriggeredAbility):
                        # The compound "~ enters or attacks"-shaped multi-event
                        # trigger returns a *list* of `TriggeredAbility` (see
                        # `bind_ability`'s docstring) — the same silent-drop gap
                        # the bare-`TriggeredAbility` branch above already covers
                        # for a single-event trigger.
                        emblem.triggered_abilities.append(effect)
                    elif isinstance(effect, ReplacementEffect):
                        # MEC-30 (Ajani Steadfast's own "-7": "You get an emblem
                        # with 'If a source would deal damage to you or a
                        # planeswalker you control, prevent all but 1 of that
                        # damage.'") — the first emblem to grant a replacement
                        # rather than a triggered/static ability; previously
                        # silently dropped here the same way the activated-
                        # ability branch above used to be, before MEC-8.
                        emblem.replacement_effects.append(effect)
        emblem.description = " / ".join(d for d in descriptions if d)
        player.emblems.append(emblem)
