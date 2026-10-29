"""Named choices, conditional payments and opening-hand entry."""
from __future__ import annotations

import re
from itertools import combinations
from typing import Any, Optional
from ...models.cards import card_query
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.game_state import DelayedTrigger
from ...models.game.player import Player
from .. import card_registry
from ..effects.core import TriggeredAbility
from .. import continuations
from .misc_helpers import (
    _creature_type_options,
)


class SourceChoicesMixin:
    """Named choices, conditional payments and opening-hand entry."""

    def _request_choose_creature_type_grant(
        self, player: Player, source: GameObject, then_specs: list[dict],
    ) -> None:
        """Open a **resolve-time** "choose a creature type" choice — RULE
        601.2b's "as ~ enters, choose a creature type" happens *during*
        battlefield entry via `_offer_enter_choices`'s own continuation-
        passing pipeline; this is for a triggered ability's own "When ~
        enters, choose a creature type. <effect naming the chosen type>."
        (Selfless Safewright-shaped), where the choice is part of an
        ordinary resolution instead. Stashes the pick onto ``source.
        chosen_type`` (the same field the enter-time choice sets, so a
        later static/effect reading it doesn't care which path set it) and
        runs ``then_specs`` once answered.

        No bespoke continuation needed: `_apply_effects_partitioned`
        already parks the rest of *this* effect list the instant this one
        opens `pending_choice` (RULE 608.2), and `GameEngine.
        resolve_until_stable`'s `resume_deferred_effects` resumes it —
        this method only needs to open the choice and, via
        `_resume_choose_type_for_source`, apply the tail.
        """
        options = _creature_type_options(self.state, player.id)
        if not options:
            # Nothing to choose from (e.g. a puzzle board with no creature
            # cards anywhere) — chosen_type stays None, the same safe
            # fallback RULE 601.2b's own enter-time choice gets.
            source.chosen_type = None
            self._apply_effect_specs(list(then_specs or []), source)
            return
        self.open_choice({
            "kind": "choose_type_for_source",
            "player_id": player.id,
            "prompt": "Kreaturentyp wählen",
            "options": [{"id": t, "label": t} for t in options],
            "source_id": source.instance_id,
            "then_specs": [dict(spec) for spec in (then_specs or [])],
        })
    def _request_choose_player(
        self, player: Player, source: GameObject, opponents_only: bool = False,
        then_specs: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """"As this creature enters, choose a player." (Stuffy Doll) — a
        resolve-time choice, the player-choice sibling of `request_choose_
        creature_type_grant` (see its docstring for why this needs its
        own primitive rather than RULE 601.2b's own enter-time machinery:
        that pipeline only knows creature-type/colour/mode picks). Stashes
        the pick onto `GameObject.chosen_player_id`.

        ``opponents_only`` is "choose an opponent" (Intellectual Offering): only the other players are offered,
        and a lone opponent is taken without asking. ``then_specs`` are the effects that follow the pick and
        read it back (the ``chosen_player`` referent), run once it is answered.
        """
        living = self.state.living_players()
        if opponents_only:
            living = [p for p in living if p.id != player.id]
        if not living:
            return
        if opponents_only and len(living) == 1:
            source.chosen_player_id = living[0].id
            self._apply_effect_specs(list(then_specs or []), source)
            return
        self.open_choice({
            "kind": "choose_player_for_source",
            "player_id": player.id,
            "prompt": "Gegner wählen" if opponents_only else "Spieler wählen",
            "options": [{"id": p.id, "label": p.name} for p in living],
            "source_id": source.instance_id,
            "then_specs": [dict(spec) for spec in (then_specs or [])],
        })
    @continuations.choice(
        "choose_player_for_source",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_choose_player_for_source(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `_request_choose_player` choice."""
        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        source = self._object_by_instance_id(choice.get("source_id"))
        if source is not None:
            source.chosen_player_id = chosen
        self._apply_effect_specs(list(choice.get("then_specs") or []), source)

    def _request_slithermuse_opponent(self, player: Player, source: GameObject) -> None:
        """Slithermuse's non-targeting ``choose an opponent`` resolution."""
        opponents = [p for p in self.state.living_players() if p.id != player.id]
        if not opponents:
            return
        self.open_choice({
            "kind": "slithermuse_opponent", "player_id": player.id,
            "prompt": "Gegner für Slithermuse wählen",
            "options": [{"id": p.id, "label": p.name} for p in opponents],
            "source_id": source.instance_id,
        })

    @continuations.choice(
        "slithermuse_opponent",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_slithermuse_opponent(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        self.state.pending_choice = None
        options = choice.get("options") or []
        ids = {str(option["id"]) for option in options}
        selected = str(answer) if answer is not None and str(answer) in ids else (
            str(options[0]["id"]) if options else None
        )
        if selected is None:
            return
        chooser = self.state.player_by_id(choice["player_id"])
        opponent = self.state.player_by_id(selected)
        if chooser is not None and opponent is not None:
            self.draw(chooser, max(0, len(opponent.hand) - len(chooser.hand)))
    @continuations.choice(
        "choose_type_for_source",
        answer=continuations.ANSWER_STR,
        rule="601.2b",
    )
    def _resume_choose_type_for_source(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `_request_choose_creature_type_grant` choice."""
        options = choice["options"]
        valid_ids = {str(o["id"]) for o in options}
        chosen = str(answer) if answer is not None and str(answer) in valid_ids else (
            str(options[0]["id"]) if options else None
        )
        source = self._object_by_instance_id(choice.get("source_id"))
        if source is not None:
            source.chosen_type = chosen
        self._apply_effect_specs(list(choice.get("then_specs") or []), source)
    #: PAR-203: which stamp on the source each "choose a ..." kind writes, and the filter sentinel that reads it.
    _NAMED_CHOICE_ATTRS: dict[str, str] = {
        "creature_type": "chosen_type", "color": "chosen_color", "card_name": "chosen_card_name",
        "basic_land_type": "chosen_land_type", "colors": "chosen_colors",
    }
    #: RULE 305.6: the five basic land types a "basic land type of your choice" can name.
    _BASIC_LAND_TYPE_OPTIONS: tuple[str, ...] = ("Plains", "Island", "Swamp", "Mountain", "Forest")

    def _named_choice_options(
        self, player: Player, kind: str, other_than: list[str], card_filter: Optional[dict[str, Any]],
        prefer_opponents: bool = False,
    ) -> list[dict[str, str]]:
        """The answers offered for a resolution-time "choose a creature type / color / card name".

        RULE 205.3m / 105.1 / 201.3: a creature type is any entry of the RULE 205.3m list and a name is any real
        card name, so the offered options are suggestions drawn from what is in the game (public zones plus the
        chooser's own hidden ones), exactly like the as-it-enters `choose_creature_type` pick; colours are the
        five of RULE 105.1."""
        if kind == "colors":
            # RULE 105.1: any nonempty subset of the five colors is legal.
            colors = list(self._ANY_COLOR_LABELS)
            return [{"id": "".join(cs), "label": ", ".join(self._ANY_COLOR_LABELS[c] for c in cs)}
                    for size in range(1, len(colors) + 1) for cs in combinations(colors, size)]
        if kind == "color":
            return [{"id": color, "label": label} for color, label in self._ANY_COLOR_LABELS.items()]
        if kind == "basic_land_type":
            return [{"id": t, "label": t} for t in self._BASIC_LAND_TYPE_OPTIONS]
        if kind == "creature_type":
            seen: set[str] = set()
            for obj in self._named_choice_cards(player):
                type_line = (getattr(obj.card, "type_line", "") or "").lower()
                if "creature" in type_line:
                    seen.update(w.capitalize() for w in re.findall(r"[a-z]+", type_line.partition("—")[2]))
            excluded = {t.lower() for t in other_than}
            return [{"id": t, "label": t} for t in sorted(seen) if t.lower() not in excluded]
        names = {
            obj.name for obj in self._named_choice_cards(player)
            if card_filter is None or card_query.matches(obj.card, card_filter)
        }
        ordered = sorted(names)
        if prefer_opponents:
            # A bot (or a player in a hurry) takes the first suggestion: let that be a card an opponent is known to have.
            theirs = {obj.name for obj in self._named_choice_cards(player) if obj.owner_id != player.id}
            ordered.sort(key=lambda name: name not in theirs)
        return [{"id": name, "label": name} for name in ordered]

    def _validated_card_name(self, player_id: str, answer: Optional[str], card_filter: Optional[dict[str, Any]]) -> str:
        """The card name a player's typed answer stands for, or ``""`` when it names nothing legal.

        A name only has to be a card name, so it is never validated against the offered suggestions; one that contradicts
        the stated card filter ("nonland card name", RULE 201.3) is refused when the game knows the card, since naming it
        would be illegal. A card the game has never seen cannot be checked and is accepted as typed."""
        raw = "" if answer is None or answer == "decline" else str(answer)
        if card_filter and raw:
            known = [o for o in self._named_choice_cards(self.state.player_by_id(player_id))
                     if card_query.name_matches(o.name, raw)]
            if known and not card_query.matches(known[0].card, card_filter):
                return ""
        return raw

    def _named_choice_cards(self, player: Player) -> list[GameObject]:
        """Every card the chooser can see or knows of: the battlefield and every graveyard/exile, plus their own
        hand, library and command zone."""
        cards = list(self.state.battlefield)
        for other in self.state.players:
            cards += list(other.graveyard) + list(other.exile)
        return cards + list(player.hand) + list(player.library) + list(player.command)

    def _request_choose_for_source(
        self, player: Player, source: Optional[GameObject], kind: str,
        other_than: Optional[list[str]] = None, card_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        """RULE 608.2d: "choose a creature type / color / card name" as part of a resolving spell or ability.

        The pick is stamped on ``source`` (`chosen_type` / `chosen_color` / `chosen_card_name`), where the clauses
        that follow read it back through the ``$chosen_*`` placeholders `composition._build` resolves. The rest of
        the effect list waits behind the choice (RULE 608.2: `_apply_effects_partitioned` parks it), so the choice
        opens, is answered by `_resume_choose_for_source`, and the tail then runs with the answer in place."""
        if source is None:
            return
        # A pick left over from an earlier use of this object (a flashed-back spell, a repeatable ability) must never
        # stand in for this resolution's answer.
        setattr(source, self._NAMED_CHOICE_ATTRS[kind], [] if kind == "colors" else None)
        other = [str(t) for t in (other_than or [])]
        options = self._named_choice_options(player, kind, other, card_filter)
        if kind == "creature_type" and not options:
            # Nothing on the board names a type: any RULE 205.3m type is still a legal pick.
            from ...models.cards.creature_types import CREATURE_SUBTYPES

            options = [{"id": t.capitalize(), "label": t.capitalize()} for t in sorted(CREATURE_SUBTYPES)
                       if t not in {x.lower() for x in other}]
        self.open_choice({
            "kind": "choose_for_source",
            "player_id": player.id,
            "prompt": {"creature_type": "Kreaturentyp wählen", "color": "Farbe wählen",
                       "card_name": "Kartennamen wählen", "basic_land_type": "Standardland-Typ wählen", "colors": "Eine oder mehrere Farben wählen"}[kind],
            "options": options,
            # A type or a name can be any legal answer, not just a suggestion (RULE 205.3m, RULE 201.3).
            **({"free_text": True} if kind in ("creature_type", "card_name") else {}),
            "what": kind,
            "source_id": source.instance_id,
            "other_than": other,
            "card_filter": dict(card_filter) if card_filter else None,
        })

    @continuations.choice("choose_for_source", answer=continuations.ANSWER_STR, rule="608.2d")
    def _resume_choose_for_source(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a `_request_choose_for_source` choice and stamp the (validated) pick on its source.

        A mandatory pick: an answer that is not a legal one falls back to the first option, the same treatment
        `_resume_choose_creature_type` gives. A name only has to be a card name, so it is never validated against
        the suggestions; one that contradicts the stated card filter ("nonland card name") is refused when the game
        knows the card, since naming it would be illegal (RULE 201.3), and then names nothing."""
        kind = choice["what"]
        options = [str(o["id"]) for o in choice.get("options", [])]
        raw = "" if answer is None or answer == "decline" else str(answer)
        chosen: Optional[str]
        if kind == "card_name":
            chosen = self._validated_card_name(choice["player_id"], answer, choice.get("card_filter"))
        elif kind == "creature_type":
            from ...models.cards.creature_types import CREATURE_SUBTYPES

            excluded = {str(t).lower() for t in choice.get("other_than", [])}
            by_lower = {o.lower(): o for o in options}
            if raw.lower() in by_lower:
                chosen = by_lower[raw.lower()]
            elif raw.lower() in CREATURE_SUBTYPES and raw.lower() not in excluded:
                chosen = raw.capitalize()
            else:
                chosen = options[0] if options else None
        else:
            chosen = raw if raw in options else (options[0] if options else None)
        source = self._object_by_instance_id(choice.get("source_id"))
        if source is not None and chosen is not None:
            setattr(source, self._NAMED_CHOICE_ATTRS[kind], list(chosen) if kind == "colors" else chosen)

    def _request_sacrifice_unless_pay(
        self, player: Player, cost: "ActivationCost", source: Optional[GameObject]
    ) -> None:
        """Open the interactive "sacrifice ``source`` unless you pay ``cost``"
        choice (RULE 701.17 + RULE 118.3-style "unless" payment).

        The single biggest remaining upkeep-trigger template — Arcades
        Sabboth/Breeding Pit/Child of Gaea's "At the beginning of your
        upkeep, sacrifice ~ unless you pay `<cost>`.", and (granted onto
        another permanent) Aura Flux/Coral Net's quoted form.

        Deliberately built on the *same* pay-or-lose-it machinery ward
        already uses (`_can_pay_player_cost`/`_pay_player_cost`, generalized
        out of `resolve_ward_effect` for exactly this) rather than a second
        parallel one: both are "a rule asks a player for an arbitrary cost
        mid-resolution, and something bad happens if they don't", and
        `ActivationCost` already covers the whole real cost vocabulary these
        cards print (mana, life, discard, sacrifice-another-permanent).

        A player who *can't* pay is not asked — the permanent is sacrificed
        outright, the same "don't stall a passive goldfish opponent on a
        choice nobody can act on" shortcut ward and `counter_unless_pays`
        take. As with ward, a mana component has to be paid out of the pool
        as it stands at resolution (RULE 605.3a mana abilities during
        resolution aren't modeled for either).
        """
        if source is None:
            return
        if not self._can_pay_player_cost(player, cost):
            self.put_into_graveyard(source)  # RULE 701.16c: sacrifice, not destruction
            return
        self._pending_sacrifice_unless_pay = {
            "player_id": player.id,
            "cost": cost,
            "source": source,
        }
        cost_label = cost.label()
        self.open_choice({
            "kind": "sacrifice_unless_pay",
            "player_id": player.id,
            "prompt": f"{cost_label} bezahlen, um {source.name} zu behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": f"{source.name} opfern"},
            ],
        })
    @continuations.choice(
        "sacrifice_unless_pay",
        answer=continuations.ANSWER_STR,
        rule="701.21",
    )
    def _resume_sacrifice_unless_pay(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `sacrifice_unless_pay` choice. ``answer == "pay"``
        charges the cost and keeps the permanent; anything else sacrifices
        it (RULE 701.17)."""
        pending = self._pending_sacrifice_unless_pay
        self._pending_sacrifice_unless_pay = None
        if pending is None:
            return
        source = pending["source"]
        try:
            player = self.state.player_by_id(pending["player_id"])
        except KeyError:
            player = None
        if answer == "pay" and player is not None:
            # Re-check: the board can have changed between the offer and the
            # answer (an interactive session hands control back to the UI in
            # between), and a promise to pay we can't honour must not
            # silently keep the permanent for free.
            if self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                return
        if source is not None and source in self.state.battlefield:
            self.put_into_graveyard(source)
    def _request_destroy_unless_pay(
        self, player: Player, cost: "ActivationCost", source: Optional[GameObject]
    ) -> None:
        """Open the interactive "destroy ``source`` unless you pay ``cost``"
        choice — RULE 701.16 destruction gated by an "unless" payment, the
        real-destruction sibling of `_request_sacrifice_unless_pay` above
        (The Tabernacle at Pendrell Vale's granted upkeep trigger, "At the
        beginning of your upkeep, destroy this creature unless you pay
        {1}."). Deliberately a separate method rather than a shared "unless
        pay" verb parameter on the sacrifice one: RULE 701.16c matters here
        — destruction (unlike sacrifice) goes through `destroy`, so a
        regeneration shield can still save the permanent, which sacrifice
        can never be.

        Same pay-or-lose-it machinery as sacrifice/ward
        (`_can_pay_player_cost`/`_pay_player_cost`); a player who can't pay
        isn't asked, the permanent is destroyed outright.
        """
        if source is None:
            return
        if not self._can_pay_player_cost(player, cost):
            self.destroy(source)
            return
        self._pending_destroy_unless_pay = {
            "player_id": player.id,
            "cost": cost,
            "source": source,
        }
        cost_label = cost.label()
        self.open_choice({
            "kind": "destroy_unless_pay",
            "player_id": player.id,
            "prompt": f"{cost_label} bezahlen, um {source.name} zu behalten?",
            "options": [
                {"id": "pay", "label": f"{cost_label} bezahlen"},
                {"id": "decline", "label": f"{source.name} zerstören lassen"},
            ],
        })
    @continuations.choice("destroy_unless_pay", answer=continuations.ANSWER_STR, rule="701.8")
    def _resume_destroy_unless_pay(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `destroy_unless_pay` choice. ``answer == "pay"``
        charges the cost and keeps the permanent; anything else destroys it
        (RULE 701.16, regenerable — see `_request_destroy_unless_pay`)."""
        pending = self._pending_destroy_unless_pay
        self._pending_destroy_unless_pay = None
        if pending is None:
            return
        source = pending["source"]
        try:
            player = self.state.player_by_id(pending["player_id"])
        except KeyError:
            player = None
        if answer == "pay" and player is not None:
            # Re-check: the board can have changed between the offer and the
            # answer, same guard as `_resume_sacrifice_unless_pay`.
            if self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                return
        if source is not None and source in self.state.battlefield:
            self.destroy(source)
    def _request_tap_or_untap_choice(self, target: GameObject, source: Optional[GameObject] = None) -> None:
        """"You may tap or untap target permanent." (Derevi, Empyrial
        Tactician — MEC-42) — a genuine two-way choice layered on top of
        RULE 115's own target (unlike `TapEffect`'s plain ``untap`` bool,
        fixed at bind time), so it needs its own small `pending_choice`
        rather than reusing that effect's target-only optionality.
        """
        self._pending_tap_or_untap_target_id = target.instance_id
        self.open_choice({
            "kind": "tap_or_untap",
            "player_id": getattr(source, "controller_id", None) or self.state.active_player.id,
            "prompt": f"{target.name} tappen oder enttappen?",
            "options": [
                {"id": "tap", "label": "Tappen"},
                {"id": "untap", "label": "Enttappen"},
                {"id": "decline", "label": "Nichts tun"},
            ],
        })
    @continuations.choice("tap_or_untap", answer=continuations.ANSWER_STR, rule="701.26")
    def _resume_tap_or_untap(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `tap_or_untap` choice — ``"tap"``/``"untap"``
        do the obvious thing; anything else (a decline) does nothing."""
        target_id = self._pending_tap_or_untap_target_id
        self._pending_tap_or_untap_target_id = None
        if answer not in ("tap", "untap") or target_id is None:
            return
        target = self.state.find_object(target_id)
        if target is not None and target in self.state.battlefield:
            self.set_tapped(target, tapped=(answer == "tap"))
    def offer_opening_hand_battlefield_choice(
        self, player: Player, obj: GameObject, alternatives: Optional[list[GameObject]] = None,
    ) -> None:
        """RULE 103.6: offer this player's remaining pregame actions in any order.

        Card identities and visits live in pending_choice, so a fresh engine
        restored from clone/undo can answer without a transient engine pointer.
        The generic prompt does not disclose an unchosen hand card to opponents.
        """
        cards = alternatives if alternatives is not None else [obj]
        offered = []
        options = []
        labels = {"battlefield": "Auf das Schlachtfeld legen", "graveyard": "In den Friedhof legen",
                  "reveal": "Vorzeigen"}
        for card in cards:
            permission = card_registry.pregame_setup_permission(card.card)
            if permission is None:
                continue
            visit = (player.id, card.instance_id, card.zone_incarnation)
            if visit in self.state.opening_hand_revealed:
                continue  # RULE 103.6b: each card may be revealed only once.
            option = permission.destination if not offered else f"{permission.destination}:{card.instance_id}"
            offered.append({"option_id": option, "instance_id": card.instance_id,
                            "incarnation": card.zone_incarnation})
            options.append({"id": option, "label": f"{card.name}: {labels[permission.destination]}"})
        if not options:
            return
        self.open_choice({
            "kind": "opening_hand_battlefield", "player_id": player.id,
            "prompt": "Aktion aus der Starthand wählen",
            "cards": offered,
            "options": options + [{"id": "decline", "label": "Keine weitere Aktion"}],
        })
    @continuations.choice(
        "opening_hand_battlefield",
        answer=continuations.ANSWER_STR,
        rule="103.6",
    )
    def _resume_opening_hand_battlefield(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """RULE 103.6: perform the selected action for its exact opening-hand visit.

        Battlefield/graveyard actions retain their entry counters and mandatory
        tails. Revealing leaves the card in hand and creates its independent
        delayed payoff. Declining finishes this player's remaining actions.
        """
        player = self.state.player_by_id(choice["player_id"])
        candidates = choice.get("cards") or []
        chosen = next((entry for entry in candidates if entry["option_id"] == answer), None)
        if chosen is None:
            if answer in (None, "decline"):
                self.state.opening_hand_queue[:] = [entry for entry in self.state.opening_hand_queue
                                                    if entry[0] != player.id]
            return
        self.state.opening_hand_queue[:] = [entry for entry in self.state.opening_hand_queue
                                           if not (entry[0] == player.id and entry[1] == chosen["instance_id"])]
        obj = next((card for card in player.hand if card.instance_id == chosen["instance_id"]
                    and card.zone_incarnation == chosen["incarnation"]), None)
        if obj is None:
            return  # RULE 400.7: an old permission does not act on a returned card.
        permission = card_registry.pregame_setup_permission(obj.card)
        if permission is None:
            return
        if permission.destination == "reveal":
            visit = (player.id, obj.instance_id, obj.zone_incarnation)
            if visit in self.state.opening_hand_revealed:
                return
            self.state.reveal_card(obj, player.id)
            self.state.opening_hand_revealed.append(visit)
            self._arm_opening_hand_reveal(player, obj, permission)
            return
        player.remove_from_zone(obj, Zone.HAND)
        if permission.destination == "battlefield":
            obj.zone = Zone.BATTLEFIELD
            obj.summoning_sick = True
            self.state.add_to_battlefield(obj)
            if permission.counter_type and permission.counter_count:
                obj.add_counters(permission.counter_type, permission.counter_count)
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    from_zone=Zone.HAND.value,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
        else:
            player.add_to_zone(obj, Zone.GRAVEYARD)
        if permission.cost_kind == "lose_life":
            self.lose_life(player, permission.cost_amount, cause="cost")
        elif permission.cost_kind == "exile_hand_card":
            self._request_choose_objects(
                player, list(player.hand), "exile", count=1,
                prompt="Wähle eine Karte aus deiner Hand zum Exilieren",
            )
    def _arm_opening_hand_reveal(self, player: Player, obj: GameObject, permission: Any) -> None:
        """RULE 103.6b/603.7: arm the delayed body independently of the revealed card's zone."""
        from ..binding.core import build_effects
        from ..effects.core import TriggeredAbility
        from ...models.game.game_state import TurnScopedTrigger

        if permission.reveal_event is not None:
            # Each opponent's first cast is an independent one-shot event.
            # None install_turn reuses the existing across-turn subscription.
            for opponent in self.state.players:
                if opponent.id == player.id or opponent.has_lost:
                    continue
                ability = TriggeredAbility(
                    trigger_event=permission.reveal_event,
                    effects=build_effects(list(permission.reveal_effects), obj),
                    condition=lambda event, context, pid=opponent.id: event.get("player_id") == pid,
                    controller_id=player.id, source=obj, description=obj.name,
                )
                self.state.turn_scoped_triggers.append(TurnScopedTrigger(ability, None, once=True))
        else:
            self.state.delayed_triggers.append(DelayedTrigger(
                controller_id=player.id, step=permission.reveal_step,
                effects=build_effects(list(permission.reveal_effects), obj),
                scope=permission.reveal_scope, description=obj.name,
            ))
