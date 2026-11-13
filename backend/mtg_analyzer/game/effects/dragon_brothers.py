"""The Dragon Brothers playtest card's named path and closed Legends token pool."""
from .core import GameEffect, StaticAbility, _controller_of
from ..continuations import choice, ANSWER_STR
from ...models.game.game_object import Zone


# The five Elder Dragons printed in Legends, as specified by chapter II.
LEGENDS_ELDER_DRAGONS = ("Arcades Sabboth", "Chromium", "Nicol Bolas", "Palladia-Mors", "Vaevictis Asmadi")


class DragonBrothersMemoryEffect(StaticAbility):
    """The playtest card's back face refers to its front-face named choice."""
    preserve_siege_named_mode = True

    def __init__(self):
        super().__init__(layer="rules")


@choice("dragon_brothers_path", answer=ANSWER_STR, rule="608.2d")
def _resume_path(rules, frame, answer):
    if answer not in {"bolas", "ugin"}:
        rules.open_choice(frame)
        raise ValueError("Choose Bolas or Ugin")
    source = rules.state.find_object(frame["source_id"])
    if source is not None and source.zone == Zone.BATTLEFIELD and source.zone_incarnation == frame["source_incarnation"]:
        source.chosen_mode = answer
    # The choice belongs to this ability's controller even if its source
    # changed control or left the battlefield while the trigger was on the stack.
    previous = rules.context.resolving_controller_id
    rules.context.resolving_controller_id = frame["player_id"]
    try:
        specs = ([{"type": "destroy", "params": {"selector": "all_creatures"}}] if answer == "bolas" else
                 [{"type": "manifest", "params": {"count": 3}}])
        rules._apply_effect_specs(specs, source)
    finally:
        rules.context.resolving_controller_id = previous


class DragonBrothersChooseEffect(GameEffect):
    def apply(self, context, targets=None):
        incarnation = context.resolving_source_incarnation
        context.engine.open_choice({"kind": "dragon_brothers_path", "player_id": _controller_of(self.source, context).id,
            "source_id": self.source.instance_id,
            "source_incarnation": self.source.zone_incarnation if incarnation is None else incarnation,
            "prompt": "Bolas oder Ugin wählen", "options": [
                {"id": "bolas", "label": "Bolas — Alle Kreaturen zerstören"},
                {"id": "ugin", "label": "Ugin — Die obersten drei Karten manifestieren"},
            ]})


class DragonBrothersManifestHandEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        # RULE 701.40e: manifest multiple cards one at a time. The player
        # chooses the order; the following draw waits for this choice to finish.
        if player.hand:
            context.engine._request_choose_objects(player, list(player.hand), "manifest_from_hand",
                count=len(player.hand), force_choice=True, source=self.source,
                prompt="Nächste Karte deiner Hand zum Manifestieren wählen")


@choice("dragon_brothers_elder", answer=ANSWER_STR, rule="608.2d")
def _resume_elder(rules, frame, answer):
    if answer not in LEGENDS_ELDER_DRAGONS:
        rules.open_choice(frame)
        raise ValueError("Choose a Legends Elder Dragon")
    from ...services.card_lookup import card_by_name
    dragon = card_by_name(answer)
    if dragon is not None:
        rules.create_token(frame["player_id"], dragon, 1)


class DragonBrothersElderEffect(GameEffect):
    def apply(self, context, targets=None):
        context.engine.open_choice({"kind": "dragon_brothers_elder", "player_id": _controller_of(self.source, context).id,
            "prompt": "Einen Uralten Drachen aus Legends wählen",
            "options": [{"id": name, "label": name} for name in LEGENDS_ELDER_DRAGONS]})
