# Reset an ie-config password

`scripts/reset-admin-password.sh` replaces one user's password when nobody can sign in. Run it as root on the host:

```bash
sudo ./scripts/reset-admin-password.sh
sudo ./scripts/reset-admin-password.sh --email admin@example.com
```

On a terminal it asks with `read -s` and does not echo the password. From a pipe it reads one line from stdin. The password is not printed, not written into the audit detail, and not placed on the `docker exec` argument list.

The script finds the container labelled `com.docker.compose.service=ie-config` in this compose project. In `docker-compose.yml` that container's name is `ie-config` (it is not `ie-config-$CLIENT_SLUG`). It then runs `python -m ie_config reset-admin` inside the container.

The new password uses the same rules as the API: 12 to 200 characters, at least one letter and one digit, and no control characters. The account's failed-attempt counter and lock are cleared, that user's sessions are deleted, and an `audit_log` row with action `password-reset` is appended.

With no `--email`, the first Administrator (lowest id) is reset. If the database has no users, the script stops and tells you to open `/setup/` to create the first administrator.

This was not exercised against a live ie-config container in the environment that added the script. `scripts/reset-admin-password.sh --self-test` uses a mock `docker`, and the database behaviour is covered by `config-api/tests/test_reset_admin.py`.
