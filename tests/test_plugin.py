"""The PostgreSQL plugin against a stand-in driver (a fake pg8000 whose connect answers for stand-in servers: no server
is started, asked or needed; no process, no port, no network): it has no instance of its own and starts no server; a
database on a server is connected only when it answers, signing in as the role given; one off this machine only when
asked twice, over TLS with the certificate checked, and signed in; a socket on Linux alone; a new database gets a role
of its own that owns it, the administrator not kept, and a make that fails is taken back whole; every connection it
makes is closed; a sign-in never reaches what is kept or shown; without its driver it says so."""
from __future__ import annotations

import importlib.machinery
import json
import re
import ssl
import sys
import types
from types import SimpleNamespace

import pytest

import plugin_platform_postgres as module
from liminal_libs.apps import EnvironmentLogin
from liminal_libs.apps.authorization import Unauthorized
from liminal_libs.storage import databases
from liminal_libs.storage.databases import Refusal
from plugin_platform_postgres import DATABASE, MARKER, PostgresPlugin, __version__


class DatabaseError(Exception):
    """pg8000's: the server's fields as a dict."""


class InterfaceError(Exception):
    """pg8000's: no connection made."""


def fail(code: str, message: str) -> DatabaseError:
    return DatabaseError({"S": "FATAL", "C": code, "M": message})


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def _super(self):
        if not self.conn.role().get("super"):
            raise fail("42501", "permission denied")

    def execute(self, sql, args=()):
        conn, server = self.conn, self.conn.server
        server["log"].append((conn.user, conn.database, sql))
        db = server["dbs"][conn.database]
        self.rows = []
        if sql == "SHOW server_version":
            self.rows = [(server["version"],)]
        elif sql.startswith("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"):
            self.rows = [(t,) for t in sorted(db["tables"])]
        elif sql == f"SELECT made, holds FROM {MARKER} WHERE id = %s":
            self.rows = [(r["made"], r["holds"]) for r in db["tables"].get(MARKER, []) if r["id"] == args[0]]
        elif sql == "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s":
            self.rows = [(server["dbs"][args[0]]["owner"],)] if args[0] in server["dbs"] else []
        elif sql == ("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
                     "AND table_name = %s"):
            self.rows = [(args[0],)] if args[0] in db["tables"] else []
        elif sql == "SELECT 1 FROM pg_roles WHERE rolname = %s":
            self.rows = [(1,)] if args[0] in server["roles"] else []
        elif m := re.fullmatch(r'(CREATE|ALTER) ROLE "([^"]+)" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                               r"PASSWORD '([^']*)'", sql):
            self._super()
            verb, role, password = m.groups()
            if verb == "CREATE" and role in server["roles"]:
                raise fail("42710", f'role "{role}" already exists')
            if verb == "ALTER" and role not in server["roles"]:
                raise fail("42704", f'role "{role}" does not exist')
            server["roles"][role] = {"password": password}
            server["made"].append((verb, role))
        elif m := re.fullmatch(r'CREATE DATABASE "([^"]+)" OWNER "([^"]+)"', sql):
            self._super()
            if not conn.autocommit:
                raise fail("25001", "CREATE DATABASE cannot run inside a transaction block")
            server["dbs"][m.group(1)] = {"owner": m.group(2), "tables": {}, "public": True}
        elif m := re.fullmatch(r'REVOKE CONNECT ON DATABASE "([^"]+)" FROM PUBLIC', sql):
            self._super()
            server["dbs"][m.group(1)]["public"] = False
        elif m := re.fullmatch(r'DROP DATABASE IF EXISTS "([^"]+)"', sql):
            if server.get("drop_fails"):
                raise InterfaceError("network error")
            self._super()
            server["dbs"].pop(m.group(1), None)
            server["dropped"].append(("database", m.group(1)))
        elif m := re.fullmatch(r'DROP ROLE "([^"]+)"', sql):
            if server.get("drop_fails"):
                raise InterfaceError("network error")
            self._super()
            server["roles"].pop(m.group(1), None)
            server["dropped"].append(("role", m.group(1)))
        elif sql.startswith(f"CREATE TABLE IF NOT EXISTS {MARKER} ("):
            if db["owner"] != conn.user and not conn.role().get("super"):
                raise fail("42501", "permission denied for schema public")
            db["tables"].setdefault(MARKER, [])
            db["table_owner"] = conn.user
        elif sql.startswith(f"INSERT INTO {MARKER} (id, name, made, holds, made_by) VALUES"):
            if conn.read_only:
                raise fail("25006", "cannot execute INSERT in a read-only transaction")
            if server.get("insert_fails"):
                server["insert_fails"] -= 1
                raise InterfaceError("network error")
            db["tables"][MARKER].append(dict(zip(("id", "name", "made", "holds", "made_by"), args)))
        elif sql == "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY":
            conn.read_only = True
        else:
            raise fail("42601", f"syntax error at or near {sql[:20]!r}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, servers, server, user, database, given):
        self.servers, self.server, self.user, self.database, self.given = servers, server, user, database, given
        self.autocommit = self.closed = self.read_only = False
        servers.connections.append(self)

    def role(self) -> dict:
        return self.server["roles"][self.user]

    def cursor(self):
        assert not self.closed, "a closed connection was used"
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def fake_driver(servers) -> types.ModuleType:
    """A stand-in pg8000 package with its dbapi module: connect answers for `servers.at`, by ("tcp", host, port) or
    ("socket", file)."""

    def connect(user, password=None, database=None, host=None, port=5432, unix_sock=None, ssl_context=None,
                timeout=None, application_name=None):
        given = dict(user=user, password=password, database=database, host=host, port=port, unix_sock=unix_sock,
                     ssl_context=ssl_context, timeout=timeout, application_name=application_name)
        servers.given.append(given)
        key = ("socket", unix_sock) if unix_sock is not None else ("tcp", host, port)
        server = servers.at.get(key)
        if server is None:
            raise InterfaceError(f"Can't create a connection to host {host} and port {port} (timeout is {timeout} and "
                                 "source_address is None).")
        if server.get("tls") and not isinstance(ssl_context, ssl.SSLContext):
            raise fail("28000", f'no pg_hba.conf entry for host "{host}", user "{user}", no encryption')
        role = server["roles"].get(user)
        if role is None or (role["password"] is not None and role["password"] != password):
            raise fail("28P01", f'password authentication failed for user "{user}"')
        if database not in server["dbs"]:
            raise fail("3D000", f'database "{database}" does not exist')
        db = server["dbs"][database]
        if not db.get("public", True) and db["owner"] != user and not role.get("super"):
            raise fail("42501", f'permission denied for database "{database}"')
        return FakeConnection(servers, server, user, database, given)

    dbapi = types.ModuleType("pg8000.dbapi")
    dbapi.connect, dbapi.paramstyle = connect, "format"
    dbapi.DatabaseError, dbapi.InterfaceError = DatabaseError, InterfaceError
    pkg = types.ModuleType("pg8000")
    pkg.__spec__ = importlib.machinery.ModuleSpec("pg8000", None, is_package=True)
    pkg.__path__ = []
    pkg.dbapi = dbapi
    return pkg


def server(**more) -> dict:
    return {"version": "17.2 (Ubuntu 17.2-1.pgdg24.04+1)",
            "roles": {"postgres": {"password": "admin-secret", "super": True}},
            "dbs": {"postgres": {"owner": "postgres", "tables": {}}, "template1": {"owner": "postgres", "tables": {}}},
            "made": [], "dropped": [], "log": [], **more}


@pytest.fixture
def pgs(tmp_path, monkeypatch):
    """The plugin attached to an app whose data folder is the test's, its driver a stand-in; `servers.at` is what
    answers and what listens on this machine; another machine is never asked whether it listens."""
    servers = SimpleNamespace(at={}, connections=[], given=[], fresh=[])
    pkg = fake_driver(servers)
    monkeypatch.setitem(sys.modules, "pg8000", pkg)
    monkeypatch.setitem(sys.modules, "pg8000.dbapi", pkg.dbapi)
    monkeypatch.setattr(module, "_os_user", lambda: "ciara")

    def listening(host, port, timeout=0.3, fresh=False):
        assert databases.is_local(host), f"{host} asked whether it listens without the user's test"
        if fresh:
            servers.fresh.append((host, port))
        return ("tcp", host, port) in servers.at

    monkeypatch.setattr(databases, "listening", listening)
    data = tmp_path / "data"
    data.mkdir()
    env: dict = {}
    plugin = PostgresPlugin()
    plugin.attach(SimpleNamespace(db_path=data / "liminal.db"), EnvironmentLogin(env=env))
    yield plugin, servers, env
    assert all(c.closed for c in servers.connections), "a connection was left open"


def test_it_has_no_instance_of_its_own_and_starts_no_server(pgs):
    plugin, servers, env = pgs
    assert DATABASE.name == "postgres" and isinstance(DATABASE, PostgresPlugin) and plugin.default_port() == 5432
    assert plugin.instances() == ()
    status = plugin.status()
    assert (status["engine"], status["engineTitle"], status["server"], status["shares"], status["defaultPort"]) == (
        "postgres", "PostgreSQL", True, False, 5432)
    assert status["driver"] == {"name": "pg8000", "ok": True, "why": ""} and status["holds"] == [
        {"name": "documents", "title": status["holds"][0]["title"]}]
    assert [m["name"] for m in status["methods"]] == list(plugin.METHODS) and status["instances"] == []
    assert status["can"]["new"] and status["can"]["connect"] and status["can"]["share"] is False
    with pytest.raises(LookupError):
        plugin.instance("local")
    facts = plugin.api_facts()["PostgreSQL"]
    assert facts["Its own server"].startswith("none") and facts["pg8000 in this Python"]
    with pytest.raises(Refusal, match="nothing listens at 127.0.0.1:5432: the plugin starts no server"):
        plugin.connect_to("docs", "127.0.0.1", database="docs")
    assert servers.given == [] and env == {}  # nothing listens: no connection is tried to find that out


def test_without_its_driver_it_says_so_and_everything_else_works(pgs, monkeypatch):
    plugin, servers, env = pgs
    monkeypatch.setitem(sys.modules, "pg8000", None)  # (find_spec then says there is none, and an import fails)
    monkeypatch.delitem(sys.modules, "pg8000.dbapi")
    status = plugin.status()
    assert status["driver"]["ok"] is False and status["driver"]["why"].startswith("driver not installed: pg8000")
    assert status["can"]["new"] is False and status["can"]["why"].startswith("driver not installed")
    with pytest.raises(Refusal, match="driver not installed"):
        plugin.connect_to("docs", "127.0.0.1:5433", database="docs")
    with pytest.raises(Refusal, match="driver not installed"):
        plugin.new_database("docs", "127.0.0.1:5433", admin_user="postgres", admin_password="admin-secret")
    assert plugin.api_facts()["PostgreSQL"]["Methods here"] and env == {}


def test_a_database_on_a_server_is_connected_only_when_it_answers_signed_in_as_the_role_given(pgs):
    plugin, servers, env = pgs
    here = servers.at[("tcp", "127.0.0.1", 5433)] = server()
    here["roles"]["reader"] = {"password": "r-secret"}
    here["dbs"]["docs"] = {"owner": "reader", "tables": {"filings": [], "news": []}}
    with pytest.raises(Refusal, match='did not answer, so it is not kept: password authentication failed for user "ciara" '
                                      r"\(28P01\)"):
        plugin.connect_to("docs", "127.0.0.1:5433", database="docs")
    with pytest.raises(Refusal, match="did not answer, so it is not kept: password authentication failed"):
        plugin.connect_to("docs", "127.0.0.1:5433", database="docs", user="reader", password="wrong")
    assert env == {}  # a sign-in that did not work is forgotten again
    with pytest.raises(Refusal, match='did not answer, so it is not kept: database "nope" does not exist'):
        plugin.connect_to("docs", "127.0.0.1:5433", database="nope", user="reader", password="r-secret")
    got = plugin.connect_to("docs", "127.0.0.1:5433", database="docs", holds="documents", user="reader", password="r-secret")
    assert got["ok"] and got["said"] == "docs connected: 127.0.0.1:5433/docs"
    assert got["lines"][:2] == ["PostgreSQL 17.2 at 127.0.0.1:5433, signed in as reader", "docs: 2 tables (filings, news)"]
    assert servers.given[-1] == {"user": "reader", "password": "r-secret", "database": "docs", "host": "127.0.0.1",
                                 "port": 5433, "unix_sock": None, "ssl_context": None, "timeout": 5,
                                 "application_name": "liminal"}
    inst = plugin.instance("docs")
    assert (inst.port, inst.database, inst.auth, inst.role, inst.remote, inst.tls, inst.method) == (
        5433, "docs", True, "reader", False, False, "tcp")
    assert plugin.state(inst)["state"] == "listening" and plugin.test("docs")["ok"]
    assert servers.fresh[-1] == ("127.0.0.1", 5433)  # a test asks now whether it listens
    kept = env["POSTGRES_INSTANCES"]
    assert "secret" not in kept and "secret" not in json.dumps(plugin.status()) and "secret" not in json.dumps(got)
    assert env["POSTGRES_DOCS_USER"] == "reader" and env["POSTGRES_DOCS_PASSWORD"] == "r-secret"
    assert plugin.status()["instances"][0]["signsIn"] is True
    # the port left out: PostgreSQL's usual one
    servers.at[("tcp", "127.0.0.1", 5432)] = server(dbs={"other": {"owner": "postgres", "tables": {}}})
    assert plugin.connect_to("other", "127.0.0.1", database="other", user="postgres", password="admin-secret")["said"] == (
        "other connected: 127.0.0.1:5432/other")
    # moved to another port: kept only when it answers there
    servers.at[("tcp", "127.0.0.1", 5440)] = here
    assert plugin.set_port("docs", 5440)["said"] == "docs's port is 5440 now"
    with pytest.raises(Refusal, match="so docs's port stays 5440"):
        plugin.set_port("docs", 5441)
    # its sign-in gone from the login: said, nothing asked
    del env["POSTGRES_DOCS_PASSWORD"]
    before = len(servers.given)
    assert "docs's sign-in is not in the login" in plugin.test("docs")["said"] and len(servers.given) == before
    # forgotten: what it holds stays, its sign-in goes with it
    gone = plugin.forget("docs")
    assert gone["lines"][0] == "127.0.0.1:5440/docs stays as it is: nothing of it was removed"
    assert "POSTGRES_DOCS_USER" not in env and "filings" in here["dbs"]["docs"]["tables"]


def test_opened_it_reads_only_unless_asked_to_write_and_is_the_callers_to_close(pgs):
    plugin, servers, env = pgs
    here = servers.at[("tcp", "127.0.0.1", 5433)] = server()
    here["dbs"]["docs"] = {"owner": "postgres", "tables": {MARKER: []}}
    plugin.connect_to("docs", "127.0.0.1:5433", database="docs", user="postgres", password="admin-secret")
    reading = plugin.open(plugin.instance("docs"))
    assert reading.read_only and reading.database == "docs" and reading.user == "postgres" and not reading.closed
    with pytest.raises(DatabaseError, match="read-only transaction"):
        reading.cursor().execute(f"INSERT INTO {MARKER} (id, name, made, holds, made_by) VALUES (%s, %s, %s, %s, %s)",
                                 ("x", "x", "x", "[]", "x"))
    writing = plugin.open(plugin.instance("docs"), read_only=False)
    assert not writing.read_only
    for c in (reading, writing):
        c.close()
    del env["POSTGRES_DOCS_PASSWORD"]
    with pytest.raises(PermissionError, match="sign-in is not in the login"):
        plugin.open(plugin.instance("docs"))


def test_a_server_off_this_machine_is_kept_only_when_asked_twice_over_tls_checked_and_signed_in(pgs):
    plugin, servers, env = pgs
    far = servers.at[("tcp", "db.example.net", 5432)] = server(tls=True)
    far["roles"]["reader"] = {"password": "far-secret"}
    far["dbs"]["docs"] = {"owner": "reader", "tables": {}}
    with pytest.raises(Refusal, match="db.example.net is not this machine") as first:
        plugin.connect_to("far", "db.example.net", database="docs", tls=True, user="reader", password="far-secret")
    assert first.value.accept == "accept_remote" and env == {} and servers.given == []
    with pytest.raises(Refusal, match="only with TLS and a sign-in"):
        plugin.connect_to("far", "db.example.net", database="docs", accept_remote=True, user="reader", password="far-secret")
    got = plugin.connect_to("far", "db.example.net", database="docs", tls=True, accept_remote=True, user="reader",
                            password="far-secret")
    assert got["lines"][0] == "PostgreSQL 17.2 at db.example.net:5432, signed in as reader, over TLS"
    context = servers.given[-1]["ssl_context"]
    assert isinstance(context, ssl.SSLContext) and context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    inst = plugin.instance("far")
    assert inst.remote and inst.tls and inst.auth and plugin.state(inst)["state"] == "not asked"  # a status never asks it
    assert plugin.test("far")["ok"]  # a test the user starts does
    with pytest.raises(Refusal, match="it is reached with a sign-in alone"):
        plugin.set_credentials("far", "", "")


def test_a_socket_is_linuxs_alone_its_folder_or_its_file(pgs, monkeypatch):
    plugin, servers, env = pgs
    if not module.SOCKETS:  # Windows: tcp alone, and said
        assert plugin.METHODS == ("tcp",) and "not offered on Windows" in plugin.api_facts()["PostgreSQL"]["Methods here"]
        with pytest.raises(Refusal, match="is reached by tcp: not 'socket'"):
            plugin.connect_to("local", "/run/postgresql", database="docs")
    # as on Linux (WSL too): the folder given, its file found by the usual port; or the file itself
    monkeypatch.setattr(module, "SOCKETS", True)
    monkeypatch.setattr(plugin, "METHODS", ("tcp", "socket"))
    here = servers.at[("socket", "/run/postgresql/.s.PGSQL.5432")] = server()
    here["roles"]["ciara"] = {"password": None}  # peer authentication: this machine's user, no password
    here["dbs"]["docs"] = {"owner": "ciara", "tables": {}}
    got = plugin.connect_to("local", "/run/postgresql", database="docs")
    assert got["lines"][0] == "PostgreSQL 17.2 at /run/postgresql/.s.PGSQL.5432" and got["said"] == (
        "local connected: /run/postgresql (docs)")
    given = servers.given[-1]
    assert (given["unix_sock"], given["ssl_context"], given["host"], given["user"], given["password"]) == (
        "/run/postgresql/.s.PGSQL.5432", False, None, "ciara", None)
    inst = plugin.instance("local")
    assert (inst.method, inst.port, inst.auth) == ("socket", None, False) and plugin.state(inst)["state"] == "not asked"
    servers.at[("socket", "/tmp/.s.PGSQL.5544")] = here
    assert plugin.connect_to("other", "/tmp/.s.PGSQL.5544", database="docs")["ok"]
    assert servers.given[-1]["unix_sock"] == "/tmp/.s.PGSQL.5544"
    with pytest.raises(Refusal, match="has no port"):
        plugin.set_port("local", 5433)
    monkeypatch.setattr(module, "SOCKETS", False)  # a socket instance read where there is none: said, nothing tried
    assert "not offered on Windows" in plugin.test("local")["said"]


def test_a_new_database_gets_a_role_of_its_own_that_owns_it_the_administrator_not_kept(pgs):
    plugin, servers, env = pgs
    with pytest.raises(Refusal, match="nothing listens at 127.0.0.1:5432.*a database is made on a server that runs"):
        plugin.new_database("notes", admin_user="postgres", admin_password="admin-secret")
    here = servers.at[("tcp", "127.0.0.1", 5432)] = server()
    with pytest.raises(Refusal, match="give the administrator's name"):
        plugin.new_database("notes")
    with pytest.raises(Refusal, match="127.0.0.1:5432 refused the administrator's sign-in: nothing was made"):
        plugin.new_database("notes", admin_user="postgres", admin_password="nope")
    with pytest.raises(Refusal, match="there is a database postgres on 127.0.0.1:5432 already: Connect keeps one"):
        plugin.new_database("again", database="postgres", admin_user="postgres", admin_password="admin-secret")
    assert env == {} and plugin.instances() == () and here["made"] == []
    made = plugin.new_database("filings-2026", database="filings", holds="documents", admin_user="postgres",
                               admin_password="admin-secret")
    assert made["ok"] and made["said"] == "filings-2026 made: 127.0.0.1:5432/filings"
    assert made["lines"][0] == f"the database filings made on 127.0.0.1:5432, owned by its role (its {MARKER} table says what it is)"
    assert made["lines"][1].startswith("the role liminal_filings_2026 made for it (the owner of filings, CONNECT taken")
    assert here["made"] == [("CREATE", "liminal_filings_2026")]
    db = here["dbs"]["filings"]
    assert db["owner"] == "liminal_filings_2026" and db["public"] is False and db["table_owner"] == "liminal_filings_2026"
    (row,) = db["tables"][MARKER]
    inst = plugin.instance("filings-2026")
    assert row == {"id": "instance", "name": "filings-2026", "made": inst.at, "holds": '["documents"]',
                   "made_by": f"plugin-platform-postgres {__version__}"}
    assert inst.made and inst.auth and (inst.role, inst.grants, inst.database, inst.holds) == (
        "liminal_filings_2026", ("owner",), "filings", ("documents",))
    password = env["POSTGRES_FILINGS_2026_PASSWORD"]
    assert here["roles"]["liminal_filings_2026"] == {"password": password} and len(password) >= 24
    everything = json.dumps(env) + json.dumps(made) + json.dumps(plugin.status())
    assert "admin-secret" not in everything
    assert password not in json.dumps(made) + json.dumps(plugin.status()) + env["POSTGRES_INSTANCES"]
    tested = plugin.test("filings-2026")
    assert tested["lines"] == ["PostgreSQL 17.2 at 127.0.0.1:5432, signed in as liminal_filings_2026",
                               f"filings: 1 table ({MARKER})", f"made here on {inst.at[:10]} to hold documents"]
    # the administrator signed in to the maintenance database, every statement its own; the role wrote the marker
    admin = [c for c in servers.connections if c.user == "postgres" and c.database == "postgres"]
    assert admin and all(c.autocommit for c in admin)
    # a server with no `postgres` database: the administrator signs in to template1
    bare = servers.at[("tcp", "127.0.0.1", 5434)] = server()
    del bare["dbs"]["postgres"]
    assert plugin.new_database("notes", "127.0.0.1:5434", admin_user="postgres", admin_password="admin-secret")["ok"]
    assert "notes" in bare["dbs"] and [g["database"] for g in servers.given if g["port"] == 5434][:2] == ["postgres", "template1"]


def test_a_make_whose_marker_was_not_written_is_taken_back_whole_and_its_retry_finishes(pgs):
    plugin, servers, env = pgs
    here = servers.at[("tcp", "127.0.0.1", 5432)] = server(insert_fails=1)
    given = {"admin_user": "postgres", "admin_password": "admin-secret"}
    with pytest.raises(Exception, match="network error"):
        plugin.new_database("filings", **given)
    assert here["dropped"] == [("database", "filings"), ("role", "liminal_filings")]
    assert "filings" not in here["dbs"] and "liminal_filings" not in here["roles"]
    assert env == {} and plugin.instances() == ()  # neither half a sign-in nor an instance
    made = plugin.new_database("filings", **given)
    assert made["ok"] and here["dbs"]["filings"]["tables"][MARKER][0]["name"] == "filings"
    # the undoing did not reach the server either: the retry finds the role and no database, and takes it over
    here["insert_fails"], here["drop_fails"] = 1, True
    with pytest.raises(Exception, match="network error"):
        plugin.new_database("notes", **given)
    assert "liminal_notes" in here["roles"] and "notes" in here["dbs"] and "POSTGRES_NOTES_PASSWORD" not in env
    here["drop_fails"] = False
    made = plugin.new_database("notes", **given)
    assert made["ok"] and made["lines"][2:4] == [
        "the database notes was there from a make that stopped half way: finished",
        "the role liminal_notes was there from a make that stopped half way: taken over, its password renewed"]
    assert here["made"][-1] == ("ALTER", "liminal_notes") and here["dbs"]["notes"]["public"] is False
    assert here["roles"]["liminal_notes"] == {"password": env["POSTGRES_NOTES_PASSWORD"]}
    assert plugin.test("notes")["lines"][0] == "PostgreSQL 17.2 at 127.0.0.1:5432, signed in as liminal_notes"
    # one made whole, then forgotten: its database stays, and a new one of that name is never made over it
    plugin.forget("notes")
    with pytest.raises(Refusal, match="there is a database notes on 127.0.0.1:5432 already"):
        plugin.new_database("notes", **given)
    # and one of somebody else's, saying nothing of itself, neither
    here["dbs"]["theirs"] = {"owner": "postgres", "tables": {}}
    with pytest.raises(Refusal, match="there is a database theirs on 127.0.0.1:5432 already"):
        plugin.new_database("theirs", **given)


def test_a_role_whose_password_could_not_be_kept_is_taken_back_and_no_database_made(pgs):
    plugin, servers, env = pgs
    here = servers.at[("tcp", "127.0.0.1", 5432)] = server()

    class Full(EnvironmentLogin):
        def save(self, variable, value):
            if variable.endswith("_PASSWORD") and value:
                raise Unauthorized("no room for it", 500)
            return super().save(variable, value)

    plugin.attach(plugin.app, Full(env=env))
    with pytest.raises(Unauthorized, match="no room for it"):
        plugin.new_database("filings", admin_user="postgres", admin_password="admin-secret")
    assert here["dropped"] == [("role", "liminal_filings")] and "liminal_filings" not in here["roles"]
    assert "filings" not in here["dbs"] and env == {} and plugin.instances() == ()


def test_what_it_gives_the_driver_is_what_the_real_pg8000_takes(pgs, monkeypatch):
    """The stand-in must not drift from the driver: every connection given in a make binds to pg8000's own connect
    (read from the installed package, nothing connected)."""
    plugin, servers, env = pgs
    import importlib
    import importlib.util
    import inspect

    del sys.modules["pg8000"], sys.modules["pg8000.dbapi"]
    try:
        if importlib.util.find_spec("pg8000") is None:
            pytest.skip("pg8000 is not installed here")
        signature = inspect.signature(importlib.import_module("pg8000.dbapi").connect)
        servers.at[("tcp", "127.0.0.1", 5432)] = server()
        given, stand_in = [], fake_driver(servers)
        monkeypatch.setattr(module, "pg_connect", lambda **k: (given.append(k), stand_in.dbapi.connect(**k))[1])
        plugin.new_database("notes", admin_user="postgres", admin_password="admin-secret")
        assert plugin.test("notes")["ok"] and len(given) == 3  # the administrator's, the marker's, the role's own
        for k in given:
            signature.bind(application_name="liminal", **k)
    finally:
        for name in [n for n in sys.modules if n == "pg8000" or n.startswith("pg8000.")]:
            del sys.modules[name]
