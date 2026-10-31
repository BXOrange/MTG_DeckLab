"""Day/night, planar dice, schemes and dungeons."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject
from ...models.game.player import Player
from .. import combat, continuous, dungeons, variants
from ..effects.core import CompleteDungeonEffect, TriggeredAbility
from .. import continuations
from .misc_helpers import (
    CHOOSE_PLANAR_FACE_KIND,
)


class VariantSystemsMixin:
    """Day/night, planar dice, schemes and dungeons."""
    def apply_day_night_turn_check(self) -> None:
        """RULE 731.2: as the second part of the untap step, maybe flip
        day/night based on how many spells the *previous* turn's active
        player cast during that turn.

        A no-op on turn 1 (no previous turn) or once a designation is set
        but the check doesn't apply (RULE 731.2c — neither day nor night:
        the check simply doesn't run at all). Any flip is applied
        immediately, including transforming now-mismatched daybound/
        nightbound permanents (RULE 702.145c/f aren't state-based actions)."""
        if self.state._last_turn_player_id is None:
            return
        count = self.state._last_turn_spell_count
        if self.state.day_night == "day" and count == 0:
            designation = "night"
        elif self.state.day_night == "night" and count >= 2:
            designation = "day"
        else:
            return
        self.set_day_night(designation)

    def set_day_night(self, designation: str) -> None:
        """RULE 731.1/731.1a: establish a designation or change the existing one."""
        if designation not in {"day", "night"}:
            return
        previous = self.state.day_night
        self.state.day_night = designation
        if previous in {"day", "night"} and previous != designation:
            self.state.fire_event(GameEvent(
                EventType.DAY_NIGHT_CHANGED, previous=previous, current=designation,
            ))
        # RULE 702.145: every mismatched permanent transforms immediately.
        self._transform_mismatched_daynight_permanents()

    def _transform_mismatched_daynight_permanents(self) -> bool:
        """Flip any permanent whose daybound/nightbound keyword (RULE
        702.145b/e) no longer matches the current day/night designation.
        Returns whether anything changed."""
        keyword = {"night": "daybound", "day": "nightbound"}.get(self.state.day_night)
        changed = False
        if keyword is not None:
            for obj in list(self.state.permanents()):
                if combat.has(obj, keyword):
                    changed = self.transform_permanent(obj) or changed
        return changed
    def _check_day_night(self) -> bool:
        """RULE 702.145c/d/f/g: establish/maintain the day/night designation
        "any time" a player controls a (mis)matched daybound/nightbound
        permanent. Not itself a state-based action, but checked at the
        `_sba_pass` cadence — the same "any time" simplification already used
        for the Saga-sacrifice check. Returns whether anything changed, so
        `_sba_pass`'s fixpoint loop re-runs."""
        if self.state.day_night is None:
            battlefield = self.state.permanents()
            if any(combat.has(o, "daybound") for o in battlefield):
                self.state.day_night = "day"
                return True
            if any(combat.has(o, "nightbound") for o in battlefield):
                self.state.day_night = "night"
                return True
            return False
        return self._transform_mismatched_daynight_permanents()
    def planeswalk(self, player: Player, _depth: int = 0) -> Optional[GameObject]:
        """Planeswalk (RULE 901.10): the face-up plane goes to the bottom of
        the planar deck face down, and the next one turns face up.

        Fires `PLANESWALKED_AWAY` for the plane being left and
        `PLANESWALKED_TO` for the new one, in that order — RULE 901.10's own
        order, and the one that lets a plane's leave-trigger see the board
        before its successor's enter-trigger changes it. Returns the plane
        walked to, or ``None`` outside a Planechase game.
        """
        deck = self.state.planar_deck
        if not deck:
            return None
        leaving = deck.pop()
        deck.insert(0, leaving)  # bottom of the deck (index 0 — see `planar_deck`)
        self.state.fire_event(
            GameEvent(
                EventType.PLANESWALKED_AWAY,
                player_id=player.id,
                controller_id=player.id,
                instance_id=leaving.instance_id,
                plane=leaving.name,
            )
        )
        arriving = deck[-1]
        arriving.controller_id = player.id
        self.state.fire_event(
            GameEvent(
                EventType.PLANESWALKED_TO,
                player_id=player.id,
                controller_id=player.id,
                instance_id=arriving.instance_id,
                plane=arriving.name,
            )
        )
        if variants.is_phenomenon(arriving) and _depth < len(deck):
            # RULE 901.18: "when a phenomenon's triggered ability leaves the
            # stack, its controller planeswalks" — a phenomenon is never
            # somewhere the game stays. Chained straight away rather than
            # after that ability resolves: the ability is already queued with
            # this object bound as its source and reads no zone of its own,
            # so the two orders are indistinguishable (the same call
            # `set_scheme_in_motion` makes for RULE 904.10). ``_depth`` is a
            # loop guard, not a rule: RULE 901.15 caps a legal planar deck at
            # two phenomena, but nothing stops a hand-built one.
            return self.planeswalk(player, _depth=_depth + 1)
        return arriving
    #: Sanity ceiling on stacked "roll one more planar die" replacements.
    _MAX_PLANAR_DICE = 16
    #: Which face a planar-die roller keeps when a replacement lets them
    #: ignore one (a bot-style default, not a rule).
    _PLANAR_FACE_PREFERENCE = ("chaos", "planeswalk")

    def roll_planar_die(self, player: Player) -> Optional[str]:
        """Roll the planar die (RULE 901.6) and apply its face.

        Returns the face rolled: ``"chaos"`` (901.13 — the face-up plane's
        chaos ability triggers), ``"planeswalk"`` (901.14 — planeswalk right
        away) or ``"blank"`` (nothing happens, which is four of the six
        faces) — or ``None`` while the roller still has to choose which of
        several planar dice counts (MEC-117, Ichor Elixir; the face is applied
        by the `choose_planar_face` continuation). Paying the {X} cost is the *special action*'s job
        (`GameEngine.roll_planar_die`); this is the roll itself, so a test — or a card
        that rolls the die for free — can use it directly. Every roll fires
        `PLANAR_DIE_ROLLED`, which is what the next roll's {X} counts (RULE 901.6b).
        """
        dice = 1
        replaced = self.apply_replacements(GameEvent(
            EventType.PLANAR_DIE_ROLL, player_id=player.id, controller_id=player.id, dice=dice,
        ))
        if replaced is not None:
            dice = max(1, min(int(replaced.get("dice", dice)), self._MAX_PLANAR_DICE))
        # Ichor Elixir: "roll that many planar dice plus one and ignore one" —
        # the ignored faces never happened (RULE 706.6-style), only one counts.
        rolled = [self.random_choice(list(variants.PLANAR_DIE_FACES)) for _ in range(dice)]
        distinct = sorted(set(rolled), key=self._planar_face_rank)
        if getattr(self.state, "interactive_roll_picks", False) and len(distinct) > 1:
            # MEC-117 (RULE 706.3 ruling): the roller sees every face, then
            # chooses which one counts. The first option is the automatic pick
            # (chaos, then planeswalk, then blank) a bot takes; the face is
            # applied by `_resume_choose_planar_face`, so nothing is returned yet.
            self.open_choice({
                "kind": CHOOSE_PLANAR_FACE_KIND, "player_id": player.id, "optional": False,
                "prompt": "Wähle das Ergebnis des Planarwürfels, das zählt (die übrigen werden ignoriert)",
                "rolled": list(rolled),
                "options": [{"id": face, "label": face} for face in distinct],
            })
            return None
        # Automatic pick (bare engine): the first face by `_PLANAR_FACE_PREFERENCE`.
        return self._apply_planar_face(player, distinct[0])

    def _planar_face_rank(self, face: str) -> int:
        return (self._PLANAR_FACE_PREFERENCE.index(face)
                if face in self._PLANAR_FACE_PREFERENCE else len(self._PLANAR_FACE_PREFERENCE))

    def _apply_planar_face(self, player: Player, face: str) -> str:
        """The kept planar-die result happens (RULE 901.13 chaos / 901.14 planeswalk)."""
        self.state.fire_event(GameEvent(EventType.PLANAR_DIE_ROLLED, player_id=player.id, face=face))
        if face == "chaos":
            self.trigger_chaos(player)
        elif face == "planeswalk":
            self.planeswalk(player)
        return face

    @continuations.choice(CHOOSE_PLANAR_FACE_KIND, answer=continuations.ANSWER_STR, rule="901.6")
    def _resume_choose_planar_face(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        faces = list(choice["rolled"])
        if answer not in faces:
            self.open_choice(choice)
            raise ValueError("Choose one of the rolled faces")
        self._apply_planar_face(self.state.player_by_id(choice["player_id"]), answer)

    def trigger_chaos(self, player: Player) -> None:
        """RULE 901.13: "chaos ensues" — fire `CHAOS_ENSUED` for the
        face-up plane so its chaos-triggered ability goes on the stack.
        Factored out of `roll_planar_die` so a card that says "chaos
        ensues" outright (Path of the Animist/Enigma's vote outcome) can
        reach it too. A no-op with no active plane (outside a Planechase
        game there is no chaos ability to put on the stack)."""
        plane = variants.active_plane(self.state)
        if plane is None:
            return
        self.state.fire_event(
            GameEvent(
                EventType.CHAOS_ENSUED,
                player_id=player.id,
                controller_id=player.id,
                instance_id=plane.instance_id,
                plane=plane.name,
            )
        )
    def set_scheme_in_motion(self, player: Player) -> Optional[GameObject]:
        """RULE 904.7: the archenemy turns the top card of their scheme deck
        face up and it "is set in motion" — its triggered ability fires.

        An **ongoing** scheme (RULE 904.9) stays face up in the command zone
        until abandoned; every other scheme goes back under its deck as soon
        as its ability has resolved (904.10) — done here rather than after
        the resolution, since the ability is already on the stack by then and
        its effects don't read the card's zone.
        """
        if not player.scheme_deck:
            return None
        scheme = player.scheme_deck.pop()
        scheme.controller_id = player.id
        is_ongoing = "ongoing" in (scheme.card.type_line or "").lower()
        # Face up first, *then* the event: a scheme's own ability is found by
        # the same command-zone scan that finds an ongoing one's
        # (`variants.command_zone_ability_sources`), so the card has to be
        # face up while `fire_event` collects triggers. A non-ongoing scheme
        # then goes straight back under its deck — RULE 904.10 times that
        # "after its ability leaves the stack", which is indistinguishable
        # here: the ability is already on the stack with this object bound as
        # its source, and nothing it does reads the card's zone.
        player.ongoing_schemes.append(scheme)
        self.state.fire_event(
            GameEvent(
                EventType.SCHEME_SET_IN_MOTION,
                player_id=player.id,
                controller_id=player.id,
                instance_id=scheme.instance_id,
                scheme=scheme.name,
                ongoing=is_ongoing,
            )
        )
        if not is_ongoing:
            player.ongoing_schemes.remove(scheme)
            player.scheme_deck.insert(0, scheme)  # bottom of the deck (904.10)
        return scheme
    def abandon_scheme(self, player: Player, scheme: GameObject) -> bool:
        """RULE 904.11: an ongoing scheme is abandoned — turned face down and
        put on the bottom of its owner's scheme deck."""
        if scheme not in player.ongoing_schemes:
            return False
        player.ongoing_schemes.remove(scheme)
        player.scheme_deck.insert(0, scheme)
        return True
    def venture_into_the_dungeon(self, player: Player, dungeon_name: Optional[str] = None) -> None:
        """The venture-into-the-dungeon keyword action (RULE 701.49).

        Three branches, exactly as the rule splits them:

        * **701.49a** — not in a dungeon: choose one from outside the game
          (an interactive `pending_choice` when more than one is available),
          put it into the command zone and put the venture marker on its
          topmost room (309.4a).
        * **701.49b** — in a room with arrows leaving it: move the marker
          along one of them, choosing when there are several.
        * **701.49c** — in the bottommost room: that dungeon is completed and
          leaves the game, then a fresh one is entered at its top room.

        ``dungeon_name`` is RULE 701.49d's "venture into [quality]" variant
        (RULE 726.2's "venture into Undercity"): it names which dungeon a
        *new* one must be, and is ignored once the player is already in one —
        which is the rule's own wording, not a simplification.

        Moving the marker into a room is what triggers that room's ability
        (309.4c); this fires `EventType.DUNGEON_ROOM_ENTERED` and
        `_collect_dungeon_room_triggers` builds the ability from it, the same
        source-less way the monarch's and the initiative's own inherent
        abilities are built.
        """
        dungeon = player.dungeon
        if dungeon is None:
            self._enter_new_dungeon(player, dungeon_name)
            return
        if dungeon.on_last_room:
            # RULE 701.49c: complete this one first, then start another.
            self.complete_dungeon(player)
            self._enter_new_dungeon(player, dungeon_name)
            return
        rooms = dungeon.next_rooms()
        if not rooms:
            return
        if len(rooms) == 1:
            self.move_venture_marker(player, rooms[0].name)
            return
        # RULE 701.49b: "if there are multiple arrows … they choose one".
        self.open_choice({
            "kind": "venture_room",
            "player_id": player.id,
            "prompt": f"{dungeon.name}: welchen Raum betrittst du?",
            "options": [
                {"id": room.name, "label": f"{room.name} — {room.effect_text}"}
                for room in rooms
            ],
        })
    @continuations.choice("venture_room", answer=continuations.ANSWER_STR, rule="701.49")
    def _resume_venture_room(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending RULE 701.49b room choice. Mandatory (the marker
        has to move somewhere), so an unrecognized/missing answer takes the
        first arrow rather than staying put."""
        player = self.state.player_by_id(choice["player_id"])
        names = [opt["id"] for opt in choice["options"]]
        self.move_venture_marker(player, answer if answer in names else names[0])
    def _enter_new_dungeon(self, player: Player, dungeon_name: Optional[str] = None) -> None:
        """RULE 309.2a/701.49a: bring a dungeon card into the game.

        A named dungeon (RULE 701.49d) is taken directly; otherwise the pool
        is every dungeon that isn't gated behind its own "venture into
        [quality]" wording, and the player picks when there's more than one.
        """
        if dungeon_name:
            dungeon = dungeons.dungeon_by_name(dungeon_name)
            if dungeon is None:
                return
            self._put_dungeon_into_command_zone(player, dungeon)
            return
        pool = dungeons.choosable_dungeons()
        if not pool:
            return
        if len(pool) == 1:
            self._put_dungeon_into_command_zone(player, pool[0])
            return
        self.open_choice({
            "kind": "choose_dungeon",
            "player_id": player.id,
            "prompt": "In welchen Dungeon begibst du dich?",
            "options": [{"id": d.name, "label": d.name} for d in pool],
        })
    @continuations.choice("choose_dungeon", answer=continuations.ANSWER_STR, rule="309.2")
    def _resume_choose_dungeon(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending RULE 309.2a dungeon choice — mandatory, so an
        unrecognized/missing answer takes the first offered dungeon."""
        player = self.state.player_by_id(choice["player_id"])
        names = [opt["id"] for opt in choice["options"]]
        chosen = answer if answer in names else names[0]
        dungeon = dungeons.dungeon_by_name(chosen)
        if dungeon is not None:
            self._put_dungeon_into_command_zone(player, dungeon)
    def _put_dungeon_into_command_zone(self, player: Player, dungeon: Any) -> None:
        """RULE 309.2b/309.4a: the card goes to the command zone and the
        marker onto its topmost room — which immediately triggers that
        room's ability (309.4c)."""
        self.state._timestamp_counter = getattr(self.state, "_timestamp_counter", 0) + 1
        dungeon.controller_id = player.id
        dungeon.owner_id = player.id
        dungeon.timestamp = self.state._timestamp_counter
        player.dungeon = dungeon
        top = dungeon.top_room
        if top is None:
            return
        self.move_venture_marker(player, top.name)
    def move_venture_marker(self, player: Player, room_name: str) -> None:
        """Move ``player``'s venture marker into ``room_name`` and fire the
        event its room ability triggers off (RULE 309.4c)."""
        dungeon = player.dungeon
        if dungeon is None or dungeon.room(room_name) is None:
            return
        dungeon.current_room = room_name
        self.state.fire_event(
            GameEvent(
                EventType.DUNGEON_ROOM_ENTERED,
                player_id=player.id,
                controller_id=player.id,
                dungeon=dungeon.name,
                room=room_name,
            )
        )
    def complete_dungeon(self, player: Player) -> None:
        """RULE 309.6/309.7: the dungeon card is removed from the game, and
        its owner thereby *completes* it."""
        dungeon = player.dungeon
        if dungeon is None:
            return
        player.dungeon = None
        player.completed_dungeons.append(dungeon.name)
        self.state.fire_event(
            GameEvent(
                EventType.DUNGEON_COMPLETED,
                player_id=player.id,
                controller_id=player.id,
                dungeon=dungeon.name,
            )
        )
    def _collect_dungeon_room_triggers(self, event: GameEvent) -> None:
        """RULE 309.4c: build a room's triggered ability as the venture marker
        moves into it — "When you move your venture marker into this room,
        [effect]".

        Source-less in the same sense the monarch's and the initiative's
        abilities are: there is no permanent for `_collect_triggers`' object
        scan to find, only a dungeon card in the command zone. The ability's
        controller is the dungeon's owner (309.4c), and its source is the
        `Dungeon` itself — which carries `controller_id`/`timestamp` for
        exactly this, the way `models/emblem.py` does.
        """
        if event.type != EventType.DUNGEON_ROOM_ENTERED:
            return
        player = self.state.player_by_id(event.get("player_id"))
        dungeon = getattr(player, "dungeon", None)
        if dungeon is None:
            return
        room = dungeon.room(event.get("room"))
        if room is None:
            return
        specs = dungeons.room_effect_specs(room)
        effects = self._effects_from_specs(specs, source=dungeon)
        if room.is_last:
            # RULE 309.6: "if a player's venture marker is on the bottommost
            # room … and that dungeon card isn't the source of a room ability
            # that has triggered but not yet left the stack, the owner removes
            # it from the game". Modeled as the last thing that room's own
            # ability does, which is precisely the moment that condition first
            # becomes true — rather than as a separate SBA scan that would
            # have to identify "is this stack item this dungeon's ability?".
            effects.append(CompleteDungeonEffect(source=dungeon))
        if not effects:
            return
        ability = TriggeredAbility(
            trigger_event=EventType.DUNGEON_ROOM_ENTERED,
            effects=effects,
            controller_id=player.id,
            description=f"{dungeon.name} — {room.name}: {room.effect_text}",
        )
        # MEC-61 (Dungeon Delver): "Room abilities of dungeons you own
        # trigger an additional time." — same "extra, independent copies"
        # idiom `triggers_mixin`'s own `trigger_doubler_bonus` call uses
        # (RULE 603.3b: each copy is separately orderable once 2+ end up
        # pending together), just via `dungeon_room_trigger_doubler_bonus`
        # since a dungeon room trigger has no `GameObject` source for the
        # general doubler to key off.
        copies = 1 + continuous.dungeon_room_trigger_doubler_bonus(self.state, player.id)
        for _ in range(copies):
            self.pending_triggers.append((ability, event))
    def _effects_from_specs(self, specs: list[dict[str, Any]], source: Any) -> list[Any]:
        """Serialized `EffectSpec` dicts → live one-shot `GameEffect`s bound
        against ``source`` — the same lazily-imported binder path
        `create_emblem` uses for an emblem's quoted ability, and for the same
        reason (a module-level import would cycle through `game/effects/core.py`).
        """
        from ...parser.oracle.spec import EffectSpec
        from ..binding.core import BindError, build_effects

        if not specs:
            return []
        try:
            return build_effects(
                [
                    EffectSpec(
                        type=spec["type"],
                        params=dict(spec.get("params") or {}),
                        condition=spec.get("condition"),
                    )
                    for spec in specs
                ],
                source=source,
            )
        except BindError:
            # Fail closed, exactly as an unmodeled room text does: a spec the
            # registry doesn't know produces no effect rather than a wrong one.
            return []
