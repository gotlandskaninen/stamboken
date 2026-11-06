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
mkdir -p config logs uppladdningar
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

## External authenticators

### Google

To set up Google authentication, visit the [developer console](https://console.cloud.google.com/) and select/create a project (dropdown next to the Google cloud platform in the upper left corner).

When you have a project, you can select "Credentials" and use the "Create credentials" to create an OAuth client ID.

Once selected, you will be told you need to configure the consent screen. You can choose "Internal" to only provide login for users within your organization or external, potentially allowing for access from any google account (but which may require verification).

Once selected, you'll need to supply an application name (e.g. Herdbook) and a support contact. You also need to supply a developer contact (for Google) at the bottom.

Once filled in, you can save and continue.

Next, you'll need to select the scopes provided. Select "Add and remove scopes" and pick `openid`.
If you want to support automatic account creation, you also need to select ".../auth/userinfo.email"

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

In short, you need to set up OAuth 2.0 with the `openid` scope (and optionally the `.../userinfo.email` scope to allow automatic creation). Once you've done that, provide the `Client secret` as `secret` and `Client ID` as `key` in the `[google]` section in `auth.ini`.

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
