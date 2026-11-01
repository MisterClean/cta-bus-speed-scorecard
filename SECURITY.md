# Security and privacy

Please report vulnerabilities privately through GitHub's **Security → Report a vulnerability** if enabled. If unavailable, open a minimal issue asking for a private reporting channel without exploit details or sensitive data.

Never attach credentials, raw personal datasets, private database files or unredacted local paths. Public vehicle identifiers in upstream bus observations identify transit vehicles, not passengers; this repository distributes aggregate outputs, not raw vehicle histories.

The importer records a local source path inside your local database for provenance. Databases and download caches are ignored by Git. Build outputs deliberately select non-path manifest fields. Review generated artifacts before publishing them. No credentials are needed for public sources.
