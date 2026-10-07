"""
External-service connectors for the hearth_agent subsystem.

One package per connector — each owns its whole surface and re-exports it from
its ``__init__``, so callers import the connector, not its internals::

    from services.hearth_agent.connectors.github import get_status

    github/    GitHub    (common.py + pat.py, plus the HEARTH job surface:
                          gh_api.py, repo.py, pulls.py, poller.py, bot.py)

One shared piece sits alongside, deliberately not a connector:

    token_store   the single owner of ``token.json``

Credential stores never live in the checkout: ``$HEARTH_STATE_DIR/secrets/token.json``
(token_store). For GitHub that file holds the credential's *metadata* only (login,
expiry, repositories); the token itself lives in the gh CLI's store, configured with
``gh auth login --with-token`` (HEARTH TDD §6 "Credentials").

These are all agent-agnostic; their HTTP surfaces live in the matching
``routers/hearth_agent/connectors/`` modules.
"""
