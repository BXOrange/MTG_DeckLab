# Account system: requirement-to-test map

Maps every verification gate of [the plan, section 8](../concepts/15_ACCOUNT_SYSTEM_PLAN.md) to the
tests that cover it, and lists the gates (or parts of one) that have **no automated test**. This is a
test inventory, not an OWASP/ASVS compliance claim: no verification scope or external evidence backs
such a claim. Paths are under `backend/tests/` unless stated. All tests use temporary directories and
in-memory stores; none touches `MTG_DATA_DIR` (the autouse fixtures in `tests/conftest.py` replace the
account store, the deck store and the account key).

Run: `python backend/scripts/run_tests.py -q`. The full-cache tier is not involved (no parser/engine code).

| Gate (plan section 8) | Tests |
| --- | --- |
| **Invitations**: generic failure for missing/expired/used/revoked/foreign token | `services/test_account_store.py` `test_invitation_failures_are_indistinguishable`, `test_invitation_is_single_use_and_atomic`; `api/test_api_auth.py` `test_signup_needs_a_valid_invitation_and_never_a_role`, `test_invitation_is_single_use` |
| concurrent redemption makes one account | `services/test_account_store.py` `test_invitation_is_single_use_and_atomic` (4 threads); `test_account_gates.py` `test_concurrent_signups_of_one_normalized_name_create_one_account` |
| token digest only in DB/logs; creator limits; disabled creator; admin cannot re-read a token | `services/test_account_store.py` `test_invitation_listing_never_exposes_the_token`, `test_player_invitation_limits`, `test_disabled_creator_invalidates_open_tokens`; `api/test_api_auth.py` `test_player_invitations_create_list_revoke_and_limits`, `test_cannot_revoke_someone_elses_invitation`; `api/test_api_admin.py` `TestInvitations` (`test_admin_mints_both_roles_and_the_token_is_never_listed`, `test_a_disabled_creator_invalidates_its_tokens`); `api/test_security_logging.py` `test_login_outcomes_are_logged_without_secrets` (no invitation token in the log) |
| **Auth/unit/API**: password verification, rehash, Unicode | `services/test_account_store.py` `test_hasher_roundtrip_unicode_and_rehash`; `api/test_api_admin.py` `test_unicode_passwords_work` |
| normalized-name collisions, concurrent signup | `services/test_account_store.py` `test_name_unique_after_normalisation`, `test_invalid_names_refused`; `test_account_gates.py` (concurrent signup) |
| rename | **No rename feature exists** (the plan's rename was a proposal; accounts are never renamed). Ownership by UUID is covered by `api/test_api_player_assets_authz.py` `test_rename_does_not_change_ownership` |
| expired/revoked sessions, rotation, logout | `services/test_account_store.py` `test_session_lifecycle`, `test_absolute_session_limit_beats_sliding_idle`, `test_logout_disable_and_password_change_revoke_sessions`; `api/test_api_auth.py` `test_signup_login_me_logout`, `test_logout_all`, `test_sessions_list_and_revoke_only_own`, `test_password_change_revokes_other_sessions` |
| throttling | `api/test_api_auth.py` `test_login_failures_are_generic_and_throttled`; `api/test_api_admin.py` `test_throttled_by_admin_identity_not_source` |
| CSRF incl. multipart, missing/`null`/spoofed Origin | `api/test_api_auth.py` `test_csrf_token_required_for_cookie_bearing_mutations`; `api/test_request_guard.py` `test_unsafe_methods_with_foreign_origin_rejected`, `..._with_null_origin_rejected`, `..._cross_site_fetch_metadata_rejected`, `test_session_cookie_without_csrf_token_is_refused_on_any_route` (includes the multipart upload route) |
| CORS | `test_account_gates.py` `test_a_foreign_origin_gets_no_cors_grant_even_with_credentials` |
| forbidden owner/scope changes | `api/test_api_deck_ownership.py` `test_global_decks_cannot_be_written_through_player_endpoints`, `test_update_and_delete_need_the_private_owner` |
| password limits/blocklist | `services/test_account_store.py` `test_policy_boundaries`, `test_trivial_and_name_passwords_are_refused`; `api/test_api_auth.py` `test_signup_password_policy` |
| generic error paths | `api/test_api_auth.py` `test_login_failures_are_generic_and_throttled`; `api/test_api_admin.py` `test_failures_are_generic`. **Timing equality** (`dummy_verify` on the unknown-account path) has no timing-measurement test: gap, see below |
| sessions survive a backend restart | `test_account_gates.py` `test_sessions_survive_a_backend_restart` |
| **Run modes**: LAN allowlist (own subnet, VPN interface, foreign HTTP/WS, spoofed headers) | `services/test_network_gate.py` `test_configured_networks_are_the_complete_list_plus_loopback`, `test_unset_uses_interface_subnets`, `test_enumeration_failure_is_loopback_only`, `test_ipv4_mapped_ipv6_and_zone_ids`, `test_http_gate_rejects_foreign_peer_and_ignores_forwarded_headers`, `test_ws_gate_closes_foreign_peer` |
| `--online` refuses without TLS, `--localdev` refuses non-loopback | `test_start_run_modes.py` (`["--online"]`, `["--localdev", "--host", "0.0.0.0"]` exit; `test_no_flag_means_lan_mode`); `services/test_network_gate.py` `test_localdev_rejects_lan_peer_and_online_accepts_any` |
| default-localuser unreachable elsewhere, logout | `api/test_api_auth.py` `test_localuser_*` (5 tests), `test_default_localuser_cannot_log_in_here` |
| **Authorization**: two players plus admin across every deck consumer and private sessions | `api/test_api_deck_ownership.py` (all), `api/test_api_anonymous_global_decks.py` (all), `api/test_api_player_assets_authz.py` |
| direct database-update calls | `api/test_api_admin.py` `TestUpdateRoutesEnforcement` (route inventory test) |
| **Admin**: player/anonymous fail on every admin route; no admin via signup; no cookie; disablement; deletion preview/confirm/cascade/tombstone | `api/test_api_admin.py` `TestAuthentication`, `TestSurfaceGate`, `TestPlayers`; `api/test_api_admin_mfa.py` `test_every_admin_route_refuses_anonymous_callers` |
| no admin reset path; admins cannot read private decks, impersonate, play, control seats | `api/test_api_admin.py` `test_there_is_no_admin_initiated_password_reset`, `test_admin_cannot_read_private_decks_or_assets`, `test_admin_credentials_reach_no_player_route` |
| MFA / recovery before remote admin; `/admin` loopback only incl. through the proxy | `api/test_api_admin_mfa.py` (all classes); `api/test_admin_page.py` `test_a_lan_client_gets_403_through_the_proxy_without_reaching_the_frontend` |
| XSS payloads in names do not execute on `/admin`; job poll token | `api/test_admin_page.py` `test_page_source_has_no_inline_script_handler_or_html_sink`; `api/test_api_admin_mfa.py` `test_pending_names_are_returned_as_data_not_markup`; `api/test_api_admin.py` `TestJobs` |
| **Names/IDs**: account name only visible name, UUID internal, client token gone | `api/test_api_player_name.py`; `api/test_api_multiplayer_identity.py` `test_no_legacy_credential_in_the_url_or_frame_reclaims_a_seat`; `api/test_api_player_assets_authz.py` `test_name_in_url_routes_no_longer_exist` |
| **Allowlist** | `services/test_network_gate.py` (see Run modes) |
| **Passwords**: 10-character minimum, blocklist, meter classes at the boundaries | server: `services/test_account_store.py` `test_policy_boundaries`, `test_strength_classes`, `test_trivial_and_name_passwords_are_refused`. **The JavaScript meter mirror (`frontend/src/js/passwordStrength.js`) has no automated parity test** (no JS test runner): gap |
| **Initial setup** | `api/test_api_admin.py` `TestInitialSetup`, `TestSeeding` |
| **Admin invitations** | `api/test_api_admin.py` `TestInvitations` |
| **Multiplayer**: same-name impossible, forged legacy credentials, owner-only resume, parallel tab, duplicated tab, guessed tab id, expiry/logout/deletion close sockets, WS first-frame failures, limits, idle revocation | `api/test_api_multiplayer_identity.py` (`TestHandshake`, `TestMessageLimits`, `TestSingleSessionLock`, `TestSessionLifecycle`); `services/test_account_store.py` `test_name_unique_after_normalisation` |
| **Storage**: credential leakage in DB/log/export fixtures | DB: `services/test_account_crypto.py` `test_encrypted_file_has_no_plaintext_even_with_wal`, `test_totp_secret_helper_still_works_encrypted`; log: `api/test_security_logging.py` `test_login_outcomes_are_logged_without_secrets`, `test_secret_looking_fields_are_refused`, `test_values_are_single_line_and_bounded`; export: `test_data_protection_files.py` `test_bug_report_dir_is_outside_the_data_dir` |
| file permissions | `services/test_account_crypto.py` `test_database_and_sidecars_are_owner_only`, `test_harden_data_dir_locks_directory_and_stores`, `test_key_file_readable_by_others_is_refused`; `api/test_security_logging.py` `test_security_log_file_is_private_and_rotates`; `test_data_protection_files.py` (git-ignore, no static mount). POSIX only; Windows relies on profile ACLs and is untested |
| encrypted backup and restore | `services/test_account_crypto.py` `test_backup_is_encrypted_consistent_and_never_overwritten`, `test_restore_replaces_and_keeps_previous_file`, `test_restore_refuses_a_backup_under_another_key`; `test_manage_accounts_crypto.py` `test_backup_and_restore_round_trip_with_pruning` |
| missing-key failure behaviour | `services/test_account_crypto.py` `test_missing_key_refuses_when_database_exists`, `test_wrong_key_is_refused_and_file_untouched`, `test_plaintext_file_under_a_key_is_refused_not_overwritten`; `test_manage_accounts_crypto.py` `test_commands_refuse_without_a_key_for_an_existing_database`. The lifespan refusal itself (`_require_account_store`) is exercised through the same exceptions; there is no end-to-end test that boots uvicorn without a key |
| conversion / rekey | `services/test_account_crypto.py` `test_convert_*`, `test_failed_verification_leaves_the_original`, `test_rekey_changes_the_key`; `test_manage_accounts_crypto.py` `test_encrypt_db_*`, `test_rekey_swaps_key_file_and_keeps_the_old_one` |
| retention | `services/test_account_crypto.py` `test_purge_expired_removes_only_dead_rows` |
| **Migration** (temporary copies): empty install, decks become global with ids/caches intact, legacy assets, unclassifiable rows listed, unverifiable backup aborts, partial failure/restart, repeat, restore | `test_migrate_legacy_decks_script.py` (all), `test_migrate_legacy_assets_script.py` (all) |
| **Browser**: stored-XSS payloads in both UIs | `api/test_admin_page.py`; frontend text escaping is by convention (`escapeHtml`/`escapeAttr`) and was reviewed for PLR-9e, not machine-checked |
| security headers | `api/test_security_headers.py`; `api/test_security_logging.py` `test_private_responses_are_no_store_even_on_errors`, `test_public_card_routes_stay_cacheable` |
| cache isolation | server side: `no-store` tests above; there is no service worker or Cache Storage in the frontend (searched in `frontend/src`) |
| signup, save deck, refresh, join game, reconnect, logout, second-account login in independent contexts; no credentials in URLs or snapshots | **No automated test.** Performed by hand with Playwright during the individual tickets; the repo has no browser test suite (see gaps) |

## Gates without an automated test (residue)

1. Timing-equality of the unknown-account login path (only the generic response is tested).
2. Client/server password-meter parity at the boundaries (no JS test runner).
3. End-to-end browser flow (signup to second-account login) and stored-XSS in both UIs as an automated
   run; only manual Playwright checks exist.
4. `--online` itself refusing plain-HTTP requests on non-admin routes: by design the app trusts a
   TLS-terminating proxy and only enforces HTTPS for remote `/admin`; the start script refuses
   `--online` without TLS or a declared proxy.
5. Windows file permissions (POSIX modes are tested; Windows depends on profile ACLs).
6. Booting the real server without a key (the refusal is covered at the function level).
