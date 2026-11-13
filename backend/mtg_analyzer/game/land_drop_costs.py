"""Mystery Booster 2 {D}: give up a potential land play, not mana."""


def remaining_land_plays(state, player):
    from .continuous import extra_land_plays_for
    return max(0, player.max_lands_per_turn + extra_land_plays_for(state, player)
        + player.extra_land_plays_this_turn - player.lands_played_this_turn
        - player.land_drops_given_up_this_turn)


def can_pay_land_drops(state, player, count):
    return player is state.active_player and remaining_land_plays(state, player) >= count
