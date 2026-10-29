# Reset an ie-config password

`scripts/reset-admin-password.sh` replaces one user's password when nobody can sign in. Run it as root on the host:

```bash
sudo ./scripts/reset-admin-password.sh
sudo ./scripts/reset-admin-password.sh --email admin@example.com
```

On a terminal it asks with `read -s` and does not echo the password. From a pipe, when a user already exists, it reads one line from stdin. The password is not printed, not written into the audit detail, and not placed on the `docker exec` argument list.

The script finds the container labelled `com.docker.compose.service=ie-config` in this compose project. In `docker-compose.yml` that container's name is `ie-config` (it is not `ie-config-$CLIENT_SLUG`). It asks `python -m ie_config reset-admin --status` whether the users table is empty, then runs `reset-admin` in that container.

The new password uses the same rules as the API: 12 to 200 characters, at least one letter and one digit, and no control characters. A reset clears that account's failed-attempt counter and lock, deletes that user's sessions, and appends an `audit_log` row with action `password-reset`. With no `--email`, the first Administrator (lowest id) is reset.

If the users table is empty, the same command creates the Administrator instead of sending you to `/setup/`. On a terminal it asks for the email (that line is echoed) and then the password (not echoed). From a pipe with no `--email`, the first line is the email and the second line is the password. `--email` plus one stdin line is the password. The audit row's action is `admin-created` and does not contain the password. Rebuild the `ie-config` image so the container has `reset-admin --status` and `--create`.

`/setup/` can still be used after the setup service notices the empty table and reopens the first-administrator step. Until that happens, a `complete` setup state refuses `/setup/admin`, which is why this script does not depend on it.

This was not exercised against a live ie-config container. `scripts/reset-admin-password.sh --self-test` uses a mock `docker`, and the database behaviour is covered by `config-api/tests/test_reset_admin.py`.
