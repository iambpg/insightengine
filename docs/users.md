# Users

InsightEngine signs people in with the ie-config `users` table. Passwords are argon2id hashes. The hash is never returned by the API, written to the audit log, or printed by the reset script.

The existing administrator is kept. `scripts/upgrade.sh` runs `python -m ie_config.users_migrate` after the stack is up, and ie-config runs the same migration on startup. The migration adds columns and the database guard. It does not rewrite `password_hash`. The earliest Administrator becomes the built-in user `admin` when that username is free, and their email and password stay the same, so the account that already signs in still signs in.

## Roles

The stored roles are the ones the API already used. The Users screen shows the product name beside them.

| Stored role | On the Users screen | What they can do |
|---|---|---|
| Administrator | Administrator (Admin) | Everything, including Users, Settings, and Vault |
| Engineer | Engineer | Settings except Vault and user management. Device edits, NetBridge writes, and alert acknowledgement |
| Operator | Operator | Approve NetBridge syncs, acknowledge alerts (which open a silence), and edit devices. No Users, Settings, or Vault |
| Read-only | Read-only (Viewer) | Read-only. `Admin` and `Viewer` are accepted as names for Administrator and Read-only |

A request with the wrong role is **403** `forbidden`. Hiding a button in the UI is not the check. Every `/api/v1` route asks for a session, and the write routes check the role again.

Sign-in is `POST /api/v1/auth/login` with `email` and `password`. `email` may be the email address or the username (`admin`). The cookie is still `ie_session`. `GET /api/v1/auth/me` still returns `email`, `role`, and `csrfToken`, and also `id`, `username`, `displayName`, and `mustChangePassword`.

## Roles and users

Settings → **Roles and users** is the existing settings tab. Administrators can:

- list users: username, name, email, role, status, last login, created
- add a user with a password that is 12–200 characters and contains a letter and a digit, or generate a one-time password
- require a password change at the next sign-in (always on for a generated password)
- edit name, email, and role
- enable or disable an account
- reset a password (sessions for that user are dropped; the new password is shown once when it was generated)
- delete a user after confirmation

The one-time password is in the create or reset response and nowhere else. Until it is changed, other API calls return **403** `password_change_required`. `POST /api/v1/auth/change-password` with `currentPassword` and `newPassword` clears that flag.

A disabled account can no longer sign in (**403** `disabled`).

## The built-in admin

The user whose username is `admin` cannot be deleted, disabled, or demoted.

- The API returns **409** `protected_admin`.
- The Users screen disables those actions.
- A database trigger on `users` rejects the `UPDATE` or `DELETE` as well, including SQL that does not go through the API.

That account also cannot be deleted by itself. Nobody can delete their own user (**403** `self_delete`).

If a change would leave no active Administrator, the API returns **409** `last_admin`. That includes disable, delete, and a role change to Engineer, Operator, or Read-only.

## Audit

User changes are appended to `audit_log` (`user-create`, `user-update`, `user-disable`, `user-enable`, `user-delete`, `user-password-reset`, `user-password-change`, plus the older `bootstrap-admin`, `admin-created`, and `password-reset` rows). The Roles and users page lists who, when, and what. The password is not in the row.

`GET /api/v1/auth/users` and `GET /api/v1/auth/users/audit` are Administrator only. Creating, editing, disabling, resetting, and deleting use the same rule and the CSRF header.
