"""What the PostgreSQL plugin attaches to (plugin API 2.2): its card is sound, every address one of PostgreSQL's own
pages or pg8000's; it names the statements the plugin itself sends; what it knows of PostgreSQL here asks no server and
loads no driver; and the card's pages answer (LIMINAL_VENDOR_PAGES=1 only, the one test that reaches the network: the
addresses were written from what was known of the sites, not fetched)."""
from __future__ import annotations

import inspect
import os
import sys

import pytest

import plugin_platform_postgres as module
from liminal_libs.sources.apis import dead_links, problems, urls
from plugin_platform_postgres import DATABASE
from plugin_platform_postgres import apis as cards


def test_the_card_is_sound_and_links_the_makers_own_pages():
    assert problems(DATABASE.apis) == [] and DATABASE.apis == cards.APIS == (cards.POSTGRES,)
    api = cards.POSTGRES
    assert (api.name, api.kind, api.verified, api.costs) == ("PostgreSQL", "sdk", "2026-11-25", "") and api.docs == cards.MANUAL
    assert all(u.startswith(("https://www.postgresql.org/", "https://github.com/tlocke/pg8000", "https://pypi.org/project/pg8000/"))
               for u in urls(DATABASE.apis))
    assert {x.kind for x in api.links} == {"docs", "reference", "sdk", "guide", "changelog", "terms"}
    assert len(api.areas) > len(api.covered) >= 6 and len(api.calls) > len(api.used) >= 10
    assert {c.area for c in api.calls} <= {a.name for a in api.areas}
    assert "over TLS alone" in next(a.covered for a in api.areas if a.name == "TLS")
    assert {c.name for c in api.calls if c.writes} >= {"CREATE ROLE", "DROP ROLE", "CREATE DATABASE ... OWNER",
                                                        "DROP DATABASE IF EXISTS"}


def test_the_card_names_what_the_plugin_itself_sends():
    src = inspect.getsource(module)
    used = " ".join(c.name for c in cards.POSTGRES.used)
    for sent, named in (("SHOW server_version", "SHOW server_version"), ("information_schema.tables", "information_schema.tables"),
                        ("FROM pg_database", "pg_database"), ("FROM pg_roles", "pg_roles"),
                        ("ROLE {identifier(role)} WITH LOGIN", "CREATE ROLE"), ('"ALTER" if there', "ALTER ROLE"),
                        ('f"DROP ROLE', "DROP ROLE"), ("CREATE DATABASE {identifier(name)} OWNER", "CREATE DATABASE ... OWNER"),
                        ("DROP DATABASE IF EXISTS", "DROP DATABASE IF EXISTS"),
                        ("REVOKE CONNECT ON DATABASE", "REVOKE CONNECT ON DATABASE ... FROM PUBLIC"),
                        ("CREATE TABLE IF NOT EXISTS {MARKER}", "CREATE TABLE liminal_instance, INSERT"),
                        ("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY", "SET SESSION CHARACTERISTICS")):
        assert sent in src and named in used
    for never in ("pg_ctl", "postgres -D", "subprocess", "DROP DATABASE {", "pg_terminate_backend"):
        assert never not in src  # it starts and ends no server, and drops only what it just made (IF EXISTS)
    assert module.PORT == 5432 and module.GRANTS == ("owner",)


def test_what_it_knows_of_postgresql_here_asks_no_server_and_loads_no_driver(monkeypatch):
    was = {name: sys.modules.pop(name) for name in list(sys.modules) if name == "pg8000" or name.startswith("pg8000.")}
    monkeypatch.setattr(module, "pg_connect", lambda **k: pytest.fail("a server was asked"))
    try:
        facts = module.PostgresPlugin().api_facts()
        assert list(facts) == ["PostgreSQL"] and facts["PostgreSQL"]["Its own server"].startswith("none")
        assert facts["PostgreSQL"]["Methods here"].startswith("tcp and a Unix socket" if module.SOCKETS else "tcp alone")
        assert "pg8000" not in sys.modules
    finally:
        sys.modules.update(was)


@pytest.mark.skipif(os.environ.get("LIMINAL_VENDOR_PAGES") != "1", reason="reaches the makers' pages: LIMINAL_VENDOR_PAGES=1")
def test_the_cards_pages_answer():
    assert dead_links(DATABASE.apis) == []
