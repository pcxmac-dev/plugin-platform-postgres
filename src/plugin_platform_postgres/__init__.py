"""PostgreSQL for Liminal: databases on PostgreSQL servers that already run, connected, or made there with a role of
their own (a database plugin, plugin API 2.3: liminal_libs.storage.databases; the platform's, drawn in its Databases
section; Monday list item 13, item 30's step 6).

The user, 2026-11-15: "for the integrator i need plugins for each type of database and in each plugin can setup either
new databases or connections to existing databases using many different types of IP or IPC methods. each instance in
the plugin has it's own configuration how it's shared, ports, permissions etc"; "make sure to include integrator plugins
for postgres and mariadb" "alongside existing used databases".

It has no instance of its own and never starts a server: every instance is one you add. **Connect** keeps a database
on a server that runs, asked first and kept only when it answers. **New database** makes one on a server you name, with
a role of its own that owns that database (the others' CONNECT on it taken away): the administrator's name and password
are asked once and not kept; the role's password is made here, kept through the login and never shown. A sign-in is
two pairs through the login, never in a file. What an instance holds: documents first (the design of item 30: "documents
as their first store"); the stores that write there come with item 10.

Two methods. `tcp`: an address and a port (5432 unless given another); off this machine only when you say so twice,
and then over TLS (the server's certificate checked against its name) with a sign-in. `socket`: a Unix socket, on
Linux (WSL too): its folder (/run/postgresql) or the whole file (/run/postgresql/.s.PGSQL.5432). Windows has no Unix
socket in Python and PostgreSQL takes no named pipe, so on Windows it is tcp alone, and the plugin says so.

The driver is pg8000 (pure Python), loaded only when a server is asked; without it the plugin says "driver not
installed" and everything else works. The plugin keeps no shares: who reaches a server is the server's to decide
(pg_hba.conf, the roles' grants). A status asks this machine alone whether anything listens; another machine is asked
only by a test you start."""
from __future__ import annotations

import getpass
import json
import socket
import ssl
from importlib import metadata
from pathlib import Path

from liminal_libs.storage import databases
from liminal_libs.storage.databases import DatabasePlugin, Instance, Made, Refusal, new_password, now_iso, variable_of

from .apis import APIS, POSTGRES

__version__ = "0.1.0"
PORT = 5432  # the engine's usual port (databases.PORTS)
MARKER = "liminal_instance"  # the table a database made here says what it is in
MAINTENANCE = ("postgres", "template1")  # where the administrator signs in to make a database: the first that is there
GRANTS = ("owner",)  # what the role made with a new database may do: own it, and no other
TIMEOUT_S = 5  # a connection's wait, and each question's
REFUSED = ("28P01", "28000")  # the server's SQLSTATE for a sign-in it refuses (invalid_password, invalid_authorization)
NO_DATABASE = "3D000"  # invalid_catalog_name: no such database
SOCKETS = hasattr(socket, "AF_UNIX")  # a Unix socket in this Python (Linux, WSL; never Windows')
SOCKET_FILE = ".s.PGSQL."  # a server's socket file in its folder: .s.PGSQL.<port>
NO_SOCKET = ("a Unix socket is not offered on Windows: Python has none there and PostgreSQL takes no named pipe, so "
             "a server is reached by tcp")


class ServerError(Exception):
    """What a server or the driver said, in its words, with the server's code (its SQLSTATE) when it gave one."""

    def __init__(self, words: str, code: str = ""):
        super().__init__(words)
        self.code = code


def said(e: BaseException) -> BaseException:
    """A driver's failure in words: pg8000 gives the server's fields as a dict (M its message, C its SQLSTATE).
    The plugin's own refusals pass unchanged."""
    if isinstance(e, (Refusal, PermissionError, ServerError)):
        return e
    first = e.args[0] if e.args else None
    if isinstance(first, dict):
        code = str(first.get("C") or "")
        return ServerError(f"{first.get('M') or 'the server refused'}" + (f" ({code})" if code else ""), code)
    return ServerError(" ".join(str(e).split()) or type(e).__name__)


def pg_connect(**given):
    """A DB-API connection of pg8000's, for one question; closed by whoever asked. (A module name, so a test stands one
    in; the driver is loaded here, when a server is asked, and only then.)"""
    import pg8000.dbapi

    return pg8000.dbapi.connect(application_name="liminal", **given)


def driver() -> str:
    """The pg8000 this Python carries, by its package's word (nothing is loaded to say it); "" when it has none."""
    try:
        return metadata.version("pg8000")
    except metadata.PackageNotFoundError:
        return ""


def socket_file(where: str, port: int | None = None) -> str:
    """A server's socket file from what was given: the file itself, or its folder (the file then .s.PGSQL.<port>)."""
    where = where.rstrip("/") or "/"
    if SOCKET_FILE in where.rsplit("/", 1)[-1]:
        return where
    return f"{where}/{SOCKET_FILE}{port or PORT}"


def identifier(name: str) -> str:
    """A name in a statement, quoted (a database's or a role's; DATABASE has let only letters, digits, _ and - by)."""
    return '"' + name.replace('"', '""') + '"'


def literal(text: str) -> str:
    """A string in a statement that takes no parameters (CREATE ROLE's password), quoted as standard SQL quotes it."""
    return "'" + text.replace("'", "''") + "'"


def role_of(instance: str) -> str:
    return f"liminal_{instance.replace('-', '_')}"


def _refused(e: BaseException) -> bool:
    return getattr(e, "code", "") in REFUSED


class PostgresPlugin(DatabasePlugin):
    name = "postgres"
    title = "PostgreSQL"
    about = ("Databases on PostgreSQL servers that already run: connected, or made there with a role of their own; "
             "never a server started")
    api = "2.3"
    order = 703
    options = (variable_of("postgres"),)  # POSTGRES_INSTANCES: what you add
    apis = APIS
    ENGINE = "postgres"
    METHODS = ("tcp", "socket") if SOCKETS else ("tcp",)
    HOLDS = ("documents",)
    SERVER = True
    DRIVER = "pg8000"
    DRIVER_HINT = "driver not installed: pg8000 is not in the app's Python (this plugin's own dependency: pip install pg8000)"
    SHARES = False
    SHARED = ("a server's own to decide (its pg_hba.conf and its roles' grants): the plugin reaches it with the role you "
              "give it, and a database it makes is the role's own")

    # -- a connection ------------------------------------------------------------------------------------------------
    def _connect(self, instance: Instance, user: str | None = None, password: str | None = None, database: str = "",
                 autocommit: bool = False):
        """A connection to `instance`'s server, signed in as given or as the instance says (its pairs from the login;
        with none, this machine's user, as PostgreSQL's own clients do), to `database` or the instance's."""
        if user is None:
            got = self.credentials(instance) if instance.auth else None
            if instance.auth and got is None:
                raise PermissionError(f"{instance.name}'s sign-in is not in the login: set its name and password again")
            user, password = got or (None, None)
        given = {"user": user or _os_user(), "password": password or None, "database": database or instance.database,
                 "timeout": TIMEOUT_S}
        if instance.method == "socket":
            if not SOCKETS:
                raise Refusal(NO_SOCKET)
            given.update(unix_sock=socket_file(instance.where), ssl_context=False)
        else:
            # over TLS: the server's certificate checked against its name; else as pg8000 does by itself (encrypted,
            # unchecked, when the server offers it), which only this machine's servers are
            given.update(host=instance.where, port=instance.port or PORT,
                         ssl_context=ssl.create_default_context() if instance.tls else None)
        try:
            conn = pg_connect(**given)
        except Exception as e:  # noqa: BLE001 - the server's or the driver's refusal, in words
            raise said(e) from None
        if autocommit:
            conn.autocommit = True
        return conn

    def _listens(self, instance: Instance) -> None:
        """ConnectionError when nothing listens at a server of this machine (asked now, not as a status remembered
        it). A socket, and another machine, are not asked here: the driver says."""
        port = instance.port or PORT
        if instance.method == "tcp" and databases.is_local(instance.where) and not databases.listening(
                instance.where, port, fresh=True):
            raise ConnectionError(f"nothing listens at {instance.where}:{port}: the plugin starts no server")

    # -- the hooks ---------------------------------------------------------------------------------------------------
    def builtin(self, data_dir: Path) -> tuple[Instance, ...]:
        return ()  # no server of its own: every instance is one you add

    def open(self, instance: Instance, part: str = "", read_only: bool = True, data_dir: Path | None = None):
        """A DB-API connection (pg8000's) to the instance's database, signed in as its role; closed by whoever asked.
        `read_only` (the default) is kept by the server itself: the session's transactions read only. `part` is not
        used by a server's engine (a table is named in the statements)."""
        conn = self._connect(instance)
        if read_only:
            try:
                cur = conn.cursor()
                cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
                conn.commit()
            except Exception as e:  # noqa: BLE001 - not handed out unless it reads only
                conn.close()
                raise said(e) from None
        return conn

    def probe(self, instance: Instance, data_dir: Path) -> list[str]:
        self._listens(instance)
        conn = self._connect(instance)
        try:
            cur = conn.cursor()
            cur.execute("SHOW server_version")
            version = str(cur.fetchone()[0] or "?").split(" ")[0]
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
                        "ORDER BY table_name")
            names = [str(r[0]) for r in cur.fetchall()]
            made = None
            if MARKER in names:
                cur.execute(f"SELECT made, holds FROM {MARKER} WHERE id = %s", ("instance",))
                made = cur.fetchone()
            conn.rollback()
        except Exception as e:  # noqa: BLE001 - in its words
            raise said(e) from None
        finally:
            conn.close()
        lines = [f"PostgreSQL {version} at {_where(instance)}" + (f", signed in as {instance.role}" if instance.auth else "")
                 + (", over TLS" if instance.tls else ""),
                 f"{instance.database}: {len(names)} table{'' if len(names) == 1 else 's'}"
                 + (f" ({', '.join(names[:6])}{', ...' if len(names) > 6 else ''})" if names else "")]
        if made:
            holds = _holds(made[1])
            lines.append(f"made here on {str(made[0] or '?')[:10]} to hold {', '.join(holds) or 'nothing yet'}")
        return lines

    def _admin(self, instance: Instance, user: str, password: str):
        """The administrator's connection, to the server's maintenance database (postgres, else template1), each
        statement its own (CREATE DATABASE runs in no transaction)."""
        where = _where(instance)
        for i, database in enumerate(MAINTENANCE):
            try:
                return self._connect(instance, user, password, database, autocommit=True)
            except ServerError as e:
                if _refused(e):
                    raise Refusal(f"{where} refused the administrator's sign-in: nothing was made") from None
                if e.code != NO_DATABASE or i + 1 == len(MAINTENANCE):
                    raise
        raise AssertionError("unreachable")

    def make(self, instance: Instance, data_dir: Path, admin_user: str = "", admin_password: str = "", **given) -> Made:
        where, name = _where(instance), instance.database
        try:
            self._listens(instance)
        except ConnectionError as e:
            raise Refusal(f"{e}: a database is made on a server that runs") from None
        if not admin_user:
            raise Refusal("the server's administrator makes a database and its role: give the administrator's name (and "
                          "password), asked this once and not kept")
        admin = self._admin(instance, admin_user, admin_password)
        role, password, lines = role_of(instance.name), new_password(), []
        try:
            cur = admin.cursor()
            try:
                cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (name,))
                owner = cur.fetchone()
                # A database owned by this instance's role and saying nothing of itself is an earlier make's that
                # stopped half way and whose undoing did not reach the server either: this make finishes it rather
                # than failing for good (as plugin-platform-mongodb 0.1.1 learned). Any other is never made over.
                half = owner is not None and str(owner[0]) == role and not self._marked(instance, admin_user,
                                                                                        admin_password)
                if owner is not None and not half:
                    raise Refusal(f"there is a database {name} on {where} already: Connect keeps one that exists")
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                there = cur.fetchone() is not None
                # A role and no database of its own: the same, a make that stopped half way; it is taken over with a
                # password of its own.
                verb = "ALTER" if there else "CREATE"
                cur.execute(f"{verb} ROLE {identifier(role)} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                            f"PASSWORD {literal(password)}")
            except Exception as e:  # noqa: BLE001 - in its words
                raise said(e) from None
            if half:
                lines.append(f"the database {name} was there from a make that stopped half way: finished")
            if there:
                lines.append(f"the role {role} was there from a make that stopped half way: taken over, its password "
                             "renewed")
            try:
                self.keep_credentials(instance.name, role, password)
            except Exception:
                _quietly(cur, f"DROP ROLE {identifier(role)}")  # a role nobody holds the password of is taken back
                raise
            try:
                if not half:
                    cur.execute(f"CREATE DATABASE {identifier(name)} OWNER {identifier(role)}")
                cur.execute(f"REVOKE CONNECT ON DATABASE {identifier(name)} FROM PUBLIC")
                self._mark(instance, role, password)
            except Exception as e:
                # No database without its marker, so nothing half made is left: the database, the role and its kept
                # sign-in are taken back (a retry takes over a role whose dropping did not reach the server).
                _quietly(cur, f"DROP DATABASE IF EXISTS {identifier(name)}")
                _quietly(cur, f"DROP ROLE {identifier(role)}")
                self._forget_credentials(instance.name)
                raise said(e) from None
        finally:
            admin.close()
        return Made((f"the database {name} made on {where}, owned by its role (its {MARKER} table says what it is)",
                     f"the role {role} made for it (the owner of {name}, CONNECT taken from everyone else); its password "
                     "kept through the login, never shown", *lines), role=role, grants=GRANTS)

    def _marked(self, instance: Instance, user: str, password: str) -> bool:
        """Whether a database there already says what it is (its marker's row), asked as the administrator; True when
        it cannot be told, so nothing is ever made over it."""
        try:
            conn = self._connect(instance, user, password, instance.database)
        except Exception:  # noqa: BLE001 - not told: taken as said
            return True
        try:
            cur = conn.cursor()
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
                        "AND table_name = %s", (MARKER,))
            if cur.fetchone() is None:
                return False
            cur.execute(f"SELECT made, holds FROM {MARKER} WHERE id = %s", ("instance",))
            return cur.fetchone() is not None
        except Exception:  # noqa: BLE001
            return True
        finally:
            conn.close()

    def _mark(self, instance: Instance, role: str, password: str) -> None:
        """The new database says what it is, written by its own role (so the table is the role's)."""
        conn = self._connect(instance, role, password, instance.database)
        try:
            cur = conn.cursor()
            cur.execute(f"CREATE TABLE IF NOT EXISTS {MARKER} (id text PRIMARY KEY, name text NOT NULL, made text NOT NULL, "
                        "holds text NOT NULL, made_by text NOT NULL)")
            cur.execute(f"INSERT INTO {MARKER} (id, name, made, holds, made_by) VALUES (%s, %s, %s, %s, %s)",
                        ("instance", instance.name, instance.at or now_iso(), json.dumps(list(instance.holds)),
                         f"plugin-platform-postgres {__version__}"))
            conn.commit()
        finally:
            conn.close()

    def api_facts(self) -> dict:
        """What is known of PostgreSQL here without asking any server: the driver this Python carries, and the methods
        this system offers."""
        return {POSTGRES.name: {"pg8000 in this Python": driver() or "driver not installed",
                                "Methods here": "tcp and a Unix socket" if SOCKETS else f"tcp alone ({NO_SOCKET})",
                                "Its own server": "none: it starts no server, every instance is one you add"}}


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no name for this machine's user: the server's usual administrator
        return "postgres"


def _where(instance: Instance) -> str:
    return socket_file(instance.where) if instance.method == "socket" else f"{instance.where}:{instance.port or PORT}"


def _holds(text) -> list[str]:
    try:
        got = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return [str(h) for h in got] if isinstance(got, list) else []


def _quietly(cur, statement: str) -> None:
    """An undoing: tried, and a server gone by now let be (a retry takes over what is left)."""
    try:
        cur.execute(statement)
    except Exception:  # noqa: BLE001
        pass


DATABASE = PostgresPlugin()
