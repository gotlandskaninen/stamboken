# Stamboken

Digital stambok för genbankskaniner — gotlandskanin och mellerudskanin.
Används av [Föreningen Gotlandskaninen](https://gotlandskaninen.se) för
registrering av individer, parningar och kullar, genetisk analys
(inavel, släktskap) och digitalt signerade stamtavlor.

Stamboken är fri programvara under [AGPL-3.0](LICENSE). Den bygger vidare på
NBIS-projektet [theherdbook](https://github.com/NBISweden/theherdbook)
(bakgrund nedan).

Fel och önskemål: [Issues](https://github.com/gotlandskaninen/stamboken/issues).
Säkerhetsbrister rapporteras enligt [SECURITY.md](SECURITY.md), inte som issue.

## Bakgrund: The Herdbook (NBIS)

The Herd Book Is a NBIS project Supporting the Swedish Board of Agriculture (Jordbruksverket) Action Plan for the Long-term
Sustainable Management of Swedish Animal Genetic Resources 2010–2020.

Mainly measure 5 “Keeping herd books and planning genetic conservation breeding”. Found in [this report](https://www2.jordbruksverket.se/webdav/files/SJV/trycksaker/Pdf_rapporter/ra09_15kort.pdf)

The aim here is to set up a online web-service for keeping a herd
book and spreading admin task to all local genebank holders.

## Terminology

### Herd = Besättning/Genbanksbesättning

A site participating in the preservation program. These will typically
have signed an agreement and have efforts in place to make sure there
is no accidental breeding with other races. Have a local pool of animals that is the actual
_in situ_ genebank.

### Genebank = Genbank (Herdbook)

Several different Herds of the same race will form a Genebank

### Herd owner = Besättningägare /Genbanksbesättningägare

A user tied to one or more herds. The owner or owners of a herd of animals

### Genebank Manager = Genbanksansvarig

A user tasked with overall maintenance of the herd book and managing the
breeding/preservation effort for a genebank. Usually responsible for a specific animal breed.

## Development setup

From a fresh clone: copy the env templates, create the directories the
compose file bind-mounts, create the schema (the migration chain does not
start from an empty database, so `init()` builds it at the current version,
as CI does), start the stack, then load the demo data and the test users:

```console
for f in .docker/*.env.default; do cp "$f" "${f%.default}"; done
mkdir -p config logs uppladdningar skyddat
docker compose run --rm api python3 -c "from utils.database import init, DATABASE; DATABASE.connect(reuse_if_open=True); init()"
docker compose up -d
docker compose exec api flask seed create
docker compose exec api python3 -m cli.create_test_users
```

The first `run` builds the api image and starts the database, so it can take a
few minutes; give the stack about a minute after `up -d` before the pages
answer. The API answers on <http://localhost:9090/api/health> and the Next.js app on
<http://localhost:3000>. Local test accounts sign in with a password, no
Google setup needed: for example `test-admin` / `test-admin-pass` (more
accounts in [docs/legacy-regression-testing.md](docs/legacy-regression-testing.md)).
The env templates need no real secrets for development; PDF signing uses the
dev certificate in [app/certs/](app/certs/README.md).
The containers create root-owned data directories (`postgres-data/`,
`s3data/` and friends) inside the clone; removing the clone later needs
`docker compose down -v` and `sudo rm -rf`.

More in [CLAUDE.md](CLAUDE.md) (quick start, conventions) and
[docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

## Testing

See [TESTING.md](TESTING.md). Never run pytest against the dev stack; it
truncates the database.

## Access rules

One API answers both frontends, so it decides per request which logged-in
account may use which function (`enforce_access_rules` in `app/herdbook.py`,
the rules in `app/utils/legacy_compat.py`):

| Host | Function | Needs | Otherwise |
|---|---|---|---|
| a legacy host (`LEGACY_HOSTS`) | on the legacy list | `validated` (the web course) | 403 |
| a legacy host | not on the list | `v2_prod_access`, or admin | 403 |
| any other host | any | `v2_prod_access`, or admin | 403 |

Open to every logged-in account on every host: `/api/user`, `/api/logout`,
the login routes, linking Google to one's own account, the public certificate
verification, posting a membership application, uploading certificates to the
intake queue, reading one's own uploads and unread-notice count there and
marking those notices seen (the queue's work and the original photos stay
gated), and the health check
(`EXEMPT_ENDPOINTS`).
Anonymous requests are not affected. Each refusal is logged at warning level
with the endpoint and method only.

`ACCESS_RULES` is `enforce` or `off`. Unset, it is `enforce` when
`FLASK_ENV=production` and `off` otherwise; the demo API (`DEMO_INSTANCE=true`)
is always off. Any other value stops the API at start, and the start log shows
the effective value and the legacy hosts. `LEGACY_HOSTS` (comma-separated)
defaults to `DEFAULT_LEGACY_HOSTS`. A legacy hostname missing from it counts as
a new host, where every account without `v2_prod_access` is refused.

**Adding a legacy function.** The list (`LEGACY_ENDPOINTS`) holds pairs of
Flask endpoint and HTTP method, not URLs: legacy's `GET /api/individual/<nr>`
is on it, the new frontend's `PATCH` on the same URL is not. It was taken from
the legacy frontend's source at the commit `build-and-publish.yml` pins, one
row per call site in `app/tests/data/legacy_calls.tsv`. When that pin moves,
read the call sites again, update the rows, and add the pairs
`test_access_rules.py` reports. The `playwright-legacy` job runs the legacy
suite with the rules enforced.

**Deploy checks**, against the deployed API:

1. A refusal on purpose: an account without `v2_prod_access` gets 403 on an
   address under `/api/v2/`, for example `GET /api/v2/my-membership`.
2. An allowed call on purpose, once per legacy hostname: a validated account
   without `v2_prod_access` gets 200 on a listed function, for example
   `GET /api/genebanks`, with that hostname as `Host`. The server's own
   `LEGACY_HOSTS` can differ from the repo's.
3. Before a release, count the active accounts that are not validated and have
   a password; the first row is new for them (numbers only):

   ```sql
   SELECT count(*) FROM hbuser u WHERE u.is_active AND NOT u.validated
     AND EXISTS (SELECT 1 FROM authenticators a WHERE a.user_id = u.user_id AND a.auth = 'password');
   ```

   An admin or promoted account is in that group too: on a legacy host the
   legacy frontend's functions need `validated`, whatever the role. The legacy
   frontend shows an empty page, not the 403's text.
4. Count the active accounts without a Google identity (numbers only). The
   legacy Google login no longer links an account that already holds the
   address, so their holders sign in with the password and link Google
   themselves, or an admin helps:

   ```sql
   SELECT count(*) FROM hbuser u WHERE u.is_active
     AND NOT EXISTS (SELECT 1 FROM authenticators a WHERE a.user_id = u.user_id AND a.auth = 'google');
   ```

### Sessions

Every login goes through `establish_session` (`app/herdbook.py`). It stamps
the session with how it signed in, `auth_method` (`google` or `losenord`,
also in `/api/user`), and with the account's mark: a random value per account
in the sessions' Redis, `generation:<uuid>` beside `logout-epoch`. A session
is valid only while its mark is the account's, and an account without a mark
has no valid session. The one-request session of Basic auth is not checked,
and it has no mark: a password change, a reset or the removal of a Google
login through Basic auth is refused.

The mark is replaced, which ends every session of the account on both APIs,
when the account is deactivated (activating it again brings none back), when
its Google identity is replaced or removed, when its password is changed or
reset by an admin, and with **Logga ut överallt** on the admin user page
(`POST /api/v2/admin/users/<id>/logga-ut`). Changing one's own password or
Google identity ends one's own session too. Only the production API replaces
a mark; the demo API reads the marks and may create a missing one, and refuses
Logga ut överallt.

**Releasing this:**

- Everybody is signed out: no session from before has `auth_method`. Say so
  in advance.
- Release the API and the demo API together. They share the session store, and
  the new one refuses every session the old one makes.
- Before rolling back to a version without the mark check: close both APIs to
  user traffic and let running requests finish, then run the mass logout on
  the production API (`POST /api/v2/admin/sessions/mass-logout`), and open
  traffic again only when both APIs run the older version. Otherwise revoked
  sessions come back: one nobody has used since is still in the store with its
  old epoch, and a login in flight can save a session after the mass logout.
- Migration 44 makes a Google identity unique to one account. If two accounts
  hold one, the migration fails, the schema stays at 43 and **the API does not
  start**; the demo API does not either, on its copy of the database. Before
  deploying, count read-only (numbers only); it must be 0:

  ```sql
  SELECT count(*) FROM (SELECT auth_data FROM authenticators WHERE auth = 'google'
    GROUP BY auth_data HAVING count(*) > 1) AS shared;
  ```

  If it is not 0, do not deploy. While the old release still runs, decide for
  each shared identity which account keeps it: the holder of the other account
  unlinks Google from it, or a data fix (ADR-0013) removes that account's
  `google` row in `authenticators`. Count again, and on the demo database too
  until its next copy.

### Roles and Google

The roles `admin`, `matrikel_admin`, `manager` and `helper` (not `viewer` or
`owner`) need a Google login whose verified address is on the association's
domain (`google_email`); the domain is fixed in code:

- A role is given only to such an account; otherwise 409 `google-required`.
- An account with a role cannot unlink its Google login, and links or switches
  only to an identity with a verified address on the domain.
- Replacing or removing a Google identity needs a session that signed in with
  Google. Adding a first identity works from a password session.
- An admin can remove the Google login of an account without a role
  (`DELETE /api/v2/admin/users/<id>/google`, no button yet). An account whose
  only way in is Google gets a password first (Återställ lösenord); it then
  signs in with it and links its new identity.
- `google_email` values written before this version are no proof of the
  domain: an identity switched on the older code kept its old address until
  the next Google sign-in, which now rewrites it under the account's lock.
  Give a role only after the account has signed in with Google on this
  version.
- To change the Google identity of an account with a role: it cannot unlink
  Google, and the legacy link flow reuses the Google token it already holds,
  so it cannot pick another Google account. An admin removes the role, sets a
  password (Återställ lösenord) and removes the Google login; the holder signs
  in with the password and links the new identity; the admin gives the role
  back.

The role rule: Google is the only way into an account with a role.

- A password login to it is refused after the password is checked, with a
  wrong password's answer (`null` on a legacy host).
- Basic auth for it is refused where the header is read: the request is
  anonymous, so 401 wherever a login is needed, also under `/api/v2/`.
- A session of it that did not sign in with Google is emptied at its next
  request (`_session_revoked`), so giving a role ends the account's password
  sessions. `is_admin` and the other role properties are unchanged: they also
  answer for an account that is not the caller.
- A Google login to it, on either Google route, needs a verified address on
  the domain from a token of the domain, whatever `auth.ini` says.
- The CMS admits only a session that signed in with Google (`auth_method` in
  `/api/user`). Set for next-app, `ALLOW_ROLE_PASSWORD_LOGIN=true` lifts this
  outside a production build (`NODE_ENV=production`), which ignores it.

`ALLOW_ROLE_PASSWORD_LOGIN=true` lifts these role rules for development and
tests, where the seed's accounts with roles have only passwords. The
development compose file (for api and next-app), the pytest compose file, the
CI pytest job, the API the Playwright jobs start and `scripts/ci-local.sh` set
it. The API refuses to start with it when `FLASK_ENV=production`, which the
demo API has too.

**Releasing the role rule.** Count read-only against production (numbers
only):

1. Active accounts with a role that would be locked out: no Google login whose
   `google_email` is on the domain, or not `validated` (the legacy frontend
   needs it). It must be 0:

   ```sql
   SELECT count(*) FROM hbuser u WHERE u.is_active
     AND EXISTS (SELECT 1 FROM jsonb_array_elements(u.privileges::jsonb) p
       WHERE p->>'level' IN ('admin', 'matrikel_admin', 'manager', 'helper'))
     AND (NOT u.validated OR coalesce(lower(u.google_email), '') NOT LIKE '%@gotlandskaninen.se'
       OR NOT EXISTS (SELECT 1 FROM authenticators a WHERE a.user_id = u.user_id AND a.auth = 'google'));
   ```

   The count trusts `google_email`. A value written before Google sign-ins
   rewrote it under the account's lock (see above) is no proof, so a role
   holder who has not signed in with Google since can still be locked out.
2. Active accounts with a role and a password: the password stops working for
   them, at the login and as Basic auth, so a client that uses Basic auth with
   such an account stops working. The API logs each Basic auth login as
   `Login ok: header, user id=<id>`.

   ```sql
   SELECT count(*) FROM hbuser u WHERE u.is_active
     AND EXISTS (SELECT 1 FROM jsonb_array_elements(u.privileges::jsonb) p
       WHERE p->>'level' IN ('admin', 'matrikel_admin', 'manager', 'helper'))
     AND EXISTS (SELECT 1 FROM authenticators a WHERE a.user_id = u.user_id AND a.auth = 'password');
   ```

A role account that is locked out gets back when an admin removes its role:
without one the account signs in with a password again (Återställ lösenord
sets one) and links a Google login on the domain, and the admin gives the role
back. When no admin can sign in to do that, `flask users add-role` below makes
an account that can sign in an admin.

`flask users add-role <konto> <roll>` is the way back when the only admin has
lost the Google account: it gives `admin` or `matrikel_admin` to the one active,
validated account whose verified Google address (`google_email`) is `<konto>`,
on the domain, and refuses any other. It never looks at the contact address or
the username, which the holder can edit.

## External authenticators

### Google

To set up Google authentication, visit the [developer console](https://console.cloud.google.com/) and select/create a project (dropdown next to the Google cloud platform in the upper left corner).

When you have a project, you can select "Credentials" and use the "Create credentials" to create an OAuth client ID.

Once selected, you will be told you need to configure the consent screen. You can choose "Internal" to only provide login for users within your organization or external, potentially allowing for access from any google account (but which may require verification).

Once selected, you'll need to supply an application name (e.g. Herdbook) and a support contact. You also need to supply a developer contact (for Google) at the bottom.

Once filled in, you can save and continue.

Next, you'll need to select the scopes provided. Select "Add and remove scopes" and pick `openid` and
".../auth/userinfo.email": the login always asks for the verified address. Automatic account creation also asks for
".../auth/userinfo.profile".

Once done, select save and continue to finish configuration of the consent screen.

As you now have the consent screen, you can again select Credentials and use Create new credential -> OAuth client ID.

When asked for the application type, select "Web application".

You will be asked for URLs. Under "Authorized redirect URI" you should provide

[https://YOURSITE/api/login/google/back/google/authorized](https://YOURSITE/api/login/google/back/google/authorized)

where YOURSITE is any address your service can be accessed at.

Once you've added all such URIs, you can select "Create".

You will be presented with a box with "Your client ID" and "Your client secret", copy these.

Create/edit `config/auth.ini` and add a `[google]` section where you provide your client ID as `key` and your secret as `secret`, e.g.

```lang-ini
[google]
key=YourIDHereLikelyEndsWith.apps.googleusercontent.com
secret=YourClientSecretGoesHere
```

and restart the server, once this is done - you should see the option to login with Google.

If you want to support automatic creation of accounts from Google, also include

```lang-ini
autocreate = yes
```

in the `[google]` section.

In short, you need to set up OAuth 2.0 with the `openid` and `.../userinfo.email` scopes (and `.../userinfo.profile` to allow automatic creation). Once you've done that, provide the `Client secret` as `secret` and `Client ID` as `key` in the `[google]` section in `auth.ini`.

#### Automatic herd ownerships

The google authenticator driver also supports automatically creating herd
ownership links at the time of account creation. This requires using a custom
domain / Google workspace.

To use that, you need to enable the `Admin SDK API` in the google developer
console. Next, create a service account under "Credentials" in your project and
create and download keys for the service account in JSON format.

Note the `Unique ID` for the service account. Head over to the
[workspace console](https://admin.google.com/) and add a domain wide delegation
(under Security -> API controls).

Create a domain wide delegation for the unique id from the service account with
the scope `https://www.googleapis.com/auth/admin.directory.user.readonly`.

Once this is done, you can add the key JSON file to the `config` directory.
Also modify the `auth.ini` in the `[google]` section, adding `herdattribute`
describing what attribute to be used for tying the user to herd(s). Other keys
needed are `credentialsfile` which should be the name of the key file for the
servicea count as well as `lookupuser` which should be set to the e-mail of an
administrative user for the domain.
