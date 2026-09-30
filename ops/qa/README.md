# QA deployment bootstrap

This directory establishes a **separate** QA deployment path.  It is not a
fallback path for production and must never reuse the production user, key,
policy directory, database, Docker project, release root, or workflow
environment.

## One-time host bootstrap

An administrator on the QA host installs the root-owned wrappers and poller.
The host also creates a root-owned
`/etc/baseer-qa/deploy.env` (mode `0600`) with the QA-only paths and names:

```text
QA_BASE=/srv/baseer-qa
QA_ENVIRONMENT=qa
QA_DATABASE=<QA database name>
QA_DB_CONTAINER=<QA PostgreSQL container>
QA_ODOO_VOLUME=<QA Odoo data volume>
QA_COMPOSE_PROJECT=<QA Docker project>
QA_COMPOSE_FILE=/etc/baseer-qa/compose.yaml
QA_ENV_FILE=/etc/baseer-qa/runtime.env
QA_LOGIN_URL=http://127.0.0.1:<QA port>/web/login
QA_SOURCE_REMOTE=ssh://git@ssh.github.com:443/hajrix01-star/abroj-baseer-production.git
QA_SOURCE_SSH_KEY=/etc/baseer-qa/source-readonly.key
QA_SOURCE_KNOWN_HOSTS=/etc/baseer-qa/github-known_hosts
QA_TAG_ALLOWED_SIGNERS=/etc/baseer-qa/request-signers
```

The root-owned `0600` compose and env files must be under `/etc/baseer-qa`, and
the compose file must contain the exact mount
`/srv/baseer-qa/current/custom_addons`. Bootstrap seeds `$QA_BASE/current`
with the exact current QA source and a `RELEASE_COMMIT` file; the wrapper
refuses to deploy without it. The restricted deploy account must have no
supplementary groups, especially no Docker or sudo membership.
The configured source key is read-only and used only by the QA host to fetch
the reviewed source and request tags. `request-signers` is root-owned `0644`
and contains only the public SSH signing key whose private half is stored as
the `QA_REQUEST_SIGNING_KEY` secret in the protected `qa` environment.

Install the root-owned `baseer-qa-release-poller` systemd timer with
`install-qa-release-poller.sh`. GitHub's
hosted workflow writes only a bounded, immutable `qa-release-<release>-<run>`
tag. The poller runs on QA, verifies that the tag points to reviewed `main`,
then invokes the same root-owned approval and deployment wrappers. It accepts
no arbitrary command, SSH secret, public QA address, or self-hosted runner.
Create a GitHub environment named `qa` for the dispatch approval boundary.

Do not store Odoo passwords, database URLs, host configuration, production
keys, or data backups in GitHub or this repository.

## Routine use

From `main`, run **Queue a reviewed Baseer Odoo QA release**, enter the policy
identifier and `DEPLOY_QA`. GitHub queues a bounded tag only; the QA timer
collects it, takes the recovery pair, and upgrades only the policy allowlist.
