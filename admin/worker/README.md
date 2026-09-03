# Private multi-student admin

This Worker is the private write boundary for managed student profiles. It
stores names and complete imports in D1, then dispatches the existing Pages
workflow. The Pages workflow receives only active profiles through the
authenticated `/internal/profiles` endpoint.

## One-time Cloudflare setup

1. Install Wrangler and log in with the Cloudflare account that owns the
   Worker: `npm install -g wrangler` then `wrangler login`.
2. Create a D1 database: `wrangler d1 create shahaf-profiles`.
3. Copy `wrangler.toml.example` to `wrangler.toml`, fill in the returned
   database ID, and set `ADMIN_ORIGIN` to the Worker URL.
4. Apply the schema:
   `wrangler d1 execute shahaf-profiles --remote --file schema.sql`.
5. Generate an admin hash from the repository root:
   `python scripts/hash_admin_password.py`.
6. Add Worker secrets:

   - `ADMIN_PASSWORD_HASH`: the generated `pbkdf2$...` value.
   - `GITHUB_DISPATCH_TOKEN`: fine-grained token limited to this repository’s
     Actions workflow dispatch permission.
   - `PROFILE_SYNC_TOKEN`: a long random token used only by GitHub Actions.

7. Set Worker variables for `ADMIN_ORIGIN`, `PUBLIC_SITE_ORIGIN`,
   `GITHUB_REPO`, and `GITHUB_REF`, then deploy:
   `wrangler deploy`.
8. In the GitHub repository, add Actions secrets:

   - `PROFILE_SYNC_URL`: `https://<worker-host>/internal/profiles`
   - `PROFILE_SYNC_TOKEN`: exactly the Worker secret value

The existing `GIST_TOKEN`, `NVIDIA_API_KEY`, and Alexa secrets are unchanged.

## Import flow

Open the Worker URL, log in, paste the strict GPT JSON or load a `.json`
file, enter the admin-only student name, and choose **Validate and publish**.
The Worker rejects unknown rows, duplicate periods, invalid times, missing
class identity, and incomplete represented weekdays. A valid import is
idempotent for the same admin name, reactivates a disabled profile, and
queues one workflow dispatch.

The console displays:

`https://<pages>/students/<random-id>/`

`https://<pages>/students/<random-id>/wake.json`

and the alarm label `Shahaf Wake - <first-six-id-characters>`. Configure the
reviewed Shortcut template with those values; the `.shortcut` file is not
generated server-side.

The GitHub workflow remains the only publisher. A failed Worker dispatch or
failed sync does not replace the last published student page. The workflow
also continues to use its existing concurrency guard, and one run processes
the whole active profile bundle rather than creating one job per student.

## Security boundary

The public profile ID has 128 bits of randomness and is private by obscurity,
not authentication. Public output contains no admin name, home address,
coordinates, or tokens. The Worker uses an HTTP-only Secure SameSite cookie,
PBKDF2 password verification, strict Origin checks, a hashed CSRF token, and
D1-backed login/publish rate limits.
