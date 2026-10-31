# Tests and CI (Stage 10)

`.github/workflows/ci.yml` runs on pushes, pull requests, and manual dispatch.
It has two independent jobs, each with a 15-minute timeout:

- **Backend checks:** Python 3.12, hash-pinned development dependencies, Ruff on
  application/migrations/tests, mypy on the application, and pytest against real
  PostgreSQL 16 and Redis 7 services. Pytest measures statement and branch coverage
  and requires a combined score of at least 90% across `app`.
- **Extension checks:** Node.js 22, `npm ci`, TypeScript/build checks, and all
  Playwright Chromium tests using fixture pages and the local fake sync API,
  followed by a clean local release ZIP build.

The workflow uses a read-only repository token, disables stored checkout
credentials, pins GitHub-maintained actions to commit SHAs, and cancels superseded
runs for the same ref. No deployment, admin secret, or third-party account is
needed. Service passwords in the workflow belong only to disposable test services.
Pull requests use `pull_request`, not privileged `pull_request_target` execution.
The setup follows the official [Python action](https://github.com/actions/setup-python),
[Node action](https://github.com/actions/setup-node), and
[checkout action](https://github.com/actions/checkout) interfaces.

PostgreSQL tests apply migrations in a unique temporary schema, test upgrade /
downgrade and model drift, then drop that schema. Redis tests use unique key
prefixes and delete only those keys. CI refuses to start pytest without both
`TEST_DATABASE_URL` and `TEST_REDIS_URL`; missing settings cannot silently skip
integration tests. Unreachable services also fail the run. Normal local runs
without these settings still skip the relevant integration tests explicitly.

## Local equivalent

From the repository root, install the development requirements into a Python 3.12
virtual environment:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
```

Start disposable services (these names/ports are separate from the local app):

```bash
docker run -d --name antislop-ci-postgres \
  -p 127.0.0.1:15480:5432 \
  -e POSTGRES_USER=antislop -e POSTGRES_PASSWORD=antislop_test \
  -e POSTGRES_DB=antislop_test postgres:16-alpine
docker run -d --name antislop-ci-redis \
  -p 127.0.0.1:16380:6379 redis:7-alpine
docker exec antislop-ci-postgres pg_isready -U antislop -d antislop_test
docker exec antislop-ci-redis redis-cli ping
```

Wait until those readiness checks report `accepting connections` and `PONG`, then:

```bash
cd backend
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
CI=true \
TEST_DATABASE_URL=postgresql+psycopg://antislop:antislop_test@127.0.0.1:15480/antislop_test \
TEST_REDIS_URL=redis://127.0.0.1:16380/0 \
.venv/bin/python -m pytest --cov=app --cov-report=term-missing --cov-report=xml -q
cd ../extension
npm ci
npm run build
npx playwright install --with-deps chromium
npm test
cd ..
docker rm -f -v antislop-ci-postgres antislop-ci-redis
```

Expected as of Stage 11: Ruff passes; mypy reports no issues in 12 application files;
100 backend tests pass with 98.87% combined statement/branch coverage; the production
extension builds and 26 browser tests pass. Coverage reports show the remaining
unexecuted branches instead of excluding them to inflate the score. The current
Starlette TestClient/httpx dependency emits a deprecation warning; tests still pass.
Coverage XML and browser results are generated locally but ignored by Git.

Ruff catches syntax/import mistakes and unused names; it does not enforce every
style preference. Mypy requires application function annotations and checks their
bodies, but tests and migration scripts are not type-checked. Coverage measures
execution, not correctness: the integration assertions check persistence,
concurrency, rollback, authentication, blocklist updates, and privacy boundaries.
Browser fixtures do not guarantee compatibility with every live YouTube layout.

## Inspecting a GitHub run

After pushing this stage, open the repository's Actions tab and select **CI**.
Both **Backend checks** and **Extension checks** should be green. Failed commands
and the coverage summary appear in their step logs. The local verification does
not claim that a hosted GitHub run has already passed.

When updating a dependency, regenerate the corresponding hash-pinned requirements
file and run these checks again. Update action commit pins deliberately using the
upstream repository's verified release refs. The workflow does not publish builds,
change branch protection, or deploy the application.
