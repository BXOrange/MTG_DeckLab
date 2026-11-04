"""Administrative operations that span several stores (PLR-9d, plan section 6).

Account deletion is a cascade over the account store, the private decks, the player assets
and the in-memory game sessions; it lives here so the API route and tests share one path.
Nothing here ever returns deck or asset *content*: previews are counts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import Account, AccountStore
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.player_assets import PlayerAssetStore


class ProtectedAccountError(Exception):
    """The default-localuser and admin accounts cannot be deleted through the admin path."""


def managed_player(accounts: AccountStore, player_uuid: str) -> Optional[Account]:
    """The player account ``player_uuid``, or None for unknown ids *and* admin ids.

    Player-account operations never address an admin (plan section 6: role changes and admin
    recovery stay with the OS operator), and an admin id looks like any unknown one."""
    account = accounts.get(player_uuid)
    return account if account is not None and account.role == acc.ROLE_PLAYER else None


@dataclass(frozen=True)
class DeletePreview:
    name: str
    decks: int
    assets: int
    sessions: int

    def counts(self) -> dict:
        return {"name": self.name, "decks": self.decks, "assets": self.assets, "sessions": self.sessions}


def delete_preview(
    accounts: AccountStore, decks: DeckDatabase, assets: PlayerAssetStore, account: Account
) -> DeletePreview:
    """What deleting ``account`` removes, as counts only (never content)."""
    return DeletePreview(
        name=account.name,
        decks=decks.count_private(account.player_uuid),
        assets=sum(assets.count_for_owner(account.player_uuid).values()),
        sessions=accounts.count_live_sessions(account.player_uuid),
    )


def delete_player(
    accounts: AccountStore, decks: DeckDatabase, assets: PlayerAssetStore,
    game_sessions: GameSessionManager, account: Account,
) -> DeletePreview:
    """Cascade-delete a player account and return what was removed.

    Order: data first, the account row last, so a failure midway leaves a still-listed account
    the admin can delete again rather than orphaned data. Sockets close and the seat is freed
    by the multiplayer sweeper, which is told through `AccountStore.drain_deleted`."""
    if account.role != acc.ROLE_PLAYER or account.is_default_local:
        raise ProtectedAccountError(account.name)
    preview = delete_preview(accounts, decks, assets, account)
    accounts.set_disabled(account.player_uuid, True)  # no new data or sessions while the cascade runs
    decks.delete_all_private(account.player_uuid)
    assets.delete_all_for_owner(account.player_uuid)  # also bound as a delete listener in production
    game_sessions.remove_owned_by(account.player_uuid)
    accounts.delete_account(account.player_uuid)  # sessions cascade; starts the name tombstone
    return preview
