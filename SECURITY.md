# Security Policy

## Public Repository Hygiene

This repository must not contain active credentials, passwords, private keys, service-account files, production database exports, user-uploaded documents, or private runtime diagnostics.

Secrets used by CI or deployment belong in GitHub Secrets or an external secret manager. Runtime and user data belong in the configured artifact/data plane, not in Git.

## Accidental Secret Exposure

If a secret is committed, treat it as compromised immediately:

1. Revoke or rotate the credential.
2. Remove the secret from the public source history before publication when feasible.
3. Review logs and dependent systems for unauthorized use.
4. Add or strengthen repository guards so the same class of secret is not committed again.

Deleting a secret only from the latest commit is not sufficient because Git history may still expose it.

## Test and Diagnostic Data

Public fixtures must be synthetic, generated, or explicitly approved for redistribution. Do not commit real customer/user documents, production database snapshots, or private processing artifacts.

## Reporting a Vulnerability

Do not post active credentials or exploitable private details in a public issue. Use GitHub's private security reporting channel when enabled, or contact the repository maintainer privately.
