"""Hidden-answer guessing games: a player records an answer, another player guesses it (RULE 608.2d / 400.2).

Blufferfish ("an opponent ... secretly notes whether it's true or false. You guess which it is"), Gollum, Scheming
Guide ("choose land or nonland. An opponent guesses ...") and Smart Ass ("they may reveal their hand") are the same
shape underneath: *ask a player a closed question mid-resolution, remember the answer, branch on it later*. Each
answer is a note on the resolving ability's source (`GameObject.guess_notes`), exactly where "choose a card name"
already stamps its pick (`chosen_card_name`). The notes never reach a view, so the secret stays hidden from the guesser
(RULE 400.2); the branch is an ordinary `if_else` over the ``guess_note_is`` condition (`effect_conditions`).
"""
from __future__ import annotations

from .core import GameEffect, _controller_of
from .damage_draw import _reveal_whose_player
from ..continuations import choice

#: Who an ``ask_player`` question goes to. ``opponent`` is "an opponent" -- the controller names one when several
#: are still in the game (RULE 800.4 multiplayer), otherwise the only one is asked outright.
ASK_CONTROLLER = "controller"
ASK_OPPONENT = "opponent"

#: The two stages of one ``ask_player`` choice (the same `kind`): naming the opponent, then the question itself.
STAGE_PICK_PLAYER = "pick_player"
STAGE_ANSWER = "answer"


def _answer_choice(player_id, source_id, key, prompt, options):
    return {
        "kind": "ask_player", "stage": STAGE_ANSWER, "player_id": player_id, "source_id": source_id,
        "note": key, "prompt": prompt, "options": [dict(o) for o in options],
    }


class AskPlayerEffect(GameEffect):
    """RULE 608.2d: ask ``player`` one closed question and keep the answer as ``note`` on this effect's source.

    ``options`` are ``{"id", "label"}`` rows (the id is what a later ``guess_note_is`` compares against). The rest of
    the resolution waits behind the choice (`_apply_effects_partitioned` parks it), as for "choose a card name".
    """

    def __init__(self, note, player=ASK_CONTROLLER, prompt="", options=None, source=None):
        super().__init__(source)
        self.note = str(note)
        self.player = player if player in (ASK_CONTROLLER, ASK_OPPONENT) else ASK_CONTROLLER
        self.prompt = str(prompt)
        self.options = [{"id": str(o["id"]), "label": str(o.get("label", o["id"]))} for o in (options or [])]

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None or self.source is None or not self.options:
            return
        # A note left by an earlier use of this object must never stand in for this resolution's answer.
        self.source.guess_notes.pop(self.note, None)
        source_id = self.source.instance_id
        if self.player == ASK_CONTROLLER:
            asked = [controller]
        else:
            asked = [p for p in context.state.living_players() if p.id != controller.id]
        if not asked:
            return
        if len(asked) == 1:
            context.engine.open_choice(_answer_choice(asked[0].id, source_id, self.note, self.prompt, self.options))
            return
        context.engine.open_choice({
            "kind": "ask_player", "stage": STAGE_PICK_PLAYER, "player_id": controller.id, "source_id": source_id,
            "note": self.note, "prompt": "Wähle einen Gegner", "question": self.prompt, "question_options": self.options,
            "options": [{"id": p.id, "label": p.name} for p in asked],
        })


@choice("ask_player", rule="608.2d")
def _resume_ask_player(rules, payload, answer):
    """Either the controller names the opponent to ask, or the asked player answers. A mandatory question: an unknown
    answer falls back to the first option, the treatment every other mandatory pick gets."""
    ids = [str(o["id"]) for o in payload["options"]]
    picked = str(answer) if answer is not None and str(answer) in ids else ids[0]
    if payload["stage"] == STAGE_PICK_PLAYER:
        rules.open_choice(_answer_choice(
            picked, payload["source_id"], payload["note"], payload["question"], payload["question_options"],
        ))
        return
    source = rules._object_by_instance_id(payload["source_id"])
    if source is not None:
        source.guess_notes[payload["note"]] = picked


class RevealHandEffect(GameEffect):
    """RULE 701.20: ``whose`` hand is revealed -- every card in it becomes public knowledge (Smart Ass)."""

    def __init__(self, whose="you", source=None):
        super().__init__(source)
        self.whose = str(whose or "you")

    def apply(self, context, targets=None):
        player = _reveal_whose_player(self.whose, self.source, context, targets)
        if player is None:
            return
        for obj in list(player.hand):
            context.state.reveal_card(obj, player_id=player.id)


EFFECT_FACTORIES = {
    "ask_player": lambda p: AskPlayerEffect(
        note=p.get("note", "answer"), player=p.get("player", ASK_CONTROLLER),
        prompt=p.get("prompt", ""), options=p.get("options"),
    ),
    "reveal_hand": lambda p: RevealHandEffect(whose=p.get("whose", "you")),
}
