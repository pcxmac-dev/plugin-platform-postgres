"""What the PostgreSQL plugin attaches to (plugin API 2.2, liminal_libs.sources.apis; the user, 2026-11-11: "each plugin
should reflect the the API its attached to, and present links that provide documentation ... it should also expose more
of what the API is about"): a PostgreSQL server, through pg8000, a pure-Python driver.

Every address is one of PostgreSQL's own pages (postgresql.org, the current release's manual) or pg8000's (its
repository, where its documentation is, and its PyPI page). They were written on 2026-11-25 from what was known of
those sites, not fetched (`VERIFIED` is that day): the one test that reaches the network, with LIMINAL_VENDOR_PAGES=1,
says whether each answers.

What those pages say and the plugin stands on: a server listens on 5432 unless given another port, on the addresses of
listen_addresses (localhost unless told otherwise) and in the folders of unix_socket_directories, its socket file
.s.PGSQL.<port>; who may sign in from where is pg_hba.conf's; CREATE DATABASE runs in no transaction block; CREATE ROLE
takes no parameters, so its password is written in the statement; a database's owner may do everything in it, and
PUBLIC is given CONNECT on every database unless it is taken away (REVOKE)."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

VERIFIED = "2026-11-25"
MANUAL = "https://www.postgresql.org/docs/current/"
CONNECTIONS = MANUAL + "runtime-config-connection.html"
HBA = MANUAL + "auth-pg-hba-conf.html"
SSL = MANUAL + "ssl-tcp.html"
ROLES = MANUAL + "user-manag.html"
PRIVILEGES = MANUAL + "ddl-priv.html"
CREATE_DATABASE = MANUAL + "sql-createdatabase.html"
DROP_DATABASE = MANUAL + "sql-dropdatabase.html"
CREATE_ROLE = MANUAL + "sql-createrole.html"
ALTER_ROLE = MANUAL + "sql-alterrole.html"
DROP_ROLE = MANUAL + "sql-droprole.html"
REVOKE = MANUAL + "sql-revoke.html"
SET_TRANSACTION = MANUAL + "sql-set-transaction.html"
SHOW = MANUAL + "sql-show.html"
TABLES = MANUAL + "infoschema-tables.html"
PG_DATABASE = MANUAL + "catalog-pg-database.html"
PG_ROLES = MANUAL + "view-pg-roles.html"
SIZES = MANUAL + "functions-admin.html"
PROTOCOL = MANUAL + "protocol.html"
NOTES = "https://www.postgresql.org/docs/release/"
LICENCE = "https://www.postgresql.org/about/licence/"
PG8000 = "https://github.com/tlocke/pg8000"
PG8000_PYPI = "https://pypi.org/project/pg8000/"

POSTGRES = Api(
    name="PostgreSQL",
    maker="The PostgreSQL Global Development Group (postgresql.org); pg8000 by Tony Locke and its contributors",
    about=("A relational database server: databases of tables, reached over TCP or a Unix socket by a driver that speaks "
           "its protocol. The plugin reaches servers that already run through pg8000, a pure-Python driver (nothing "
           "compiled, the same in the WSL suite), and keeps documents there first."),
    kind="sdk",
    base="each instance's address: host:port (5432 unless given another), or a Unix socket on Linux",
    version="PostgreSQL 13 and newer, through pg8000 1.31 (its DB-API interface, pg8000.dbapi)",
    auth=("a role's name and password, kept through the login as two pairs; a server off this machine over TLS alone, "
          "its certificate checked against its name; who may sign in from where is the server's pg_hba.conf"),
    limits="",
    costs="",
    links=(
        Link("PostgreSQL documentation (the current release)", MANUAL, "docs"),
        Link("Connections and Authentication: listen_addresses, port, unix_socket_directories", CONNECTIONS, "reference"),
        Link("The pg_hba.conf file", HBA, "reference"),
        Link("Secure TCP/IP Connections with SSL", SSL, "guide"),
        Link("Database Roles", ROLES, "guide"),
        Link("Privileges", PRIVILEGES, "guide"),
        Link("CREATE DATABASE", CREATE_DATABASE, "reference"),
        Link("CREATE ROLE", CREATE_ROLE, "reference"),
        Link("Frontend/Backend Protocol", PROTOCOL, "reference"),
        Link("pg8000, the Python driver (its documentation is its README)", PG8000, "sdk"),
        Link("pg8000 on PyPI", PG8000_PYPI, "sdk"),
        Link("Release Notes", NOTES, "changelog"),
        Link("The PostgreSQL Licence", LICENCE, "terms"),
    ),
    areas=(
        Area("Connections", "where a server listens: the addresses of listen_addresses, its port, the folders of its "
             "Unix sockets", CONNECTIONS,
             covered="an instance is an address and a port (5432 unless given another), or a socket on Linux; one off this "
                     "machine is kept only when asked twice"),
        Area("Client authentication (pg_hba.conf)", "which roles may sign in to which databases, from where, and how",
             HBA, covered="the server's own: the plugin keeps no shares, and says so"),
        Area("TLS", "a connection encrypted, the server's certificate checked by the client", SSL,
             covered="an instance off this machine is reached over TLS alone, the certificate checked against its name"),
        Area("Roles and privileges", "who signs in, what each role may do, the owner of a database", ROLES,
             covered="a database made here is owned by a role of its own (LOGIN, no superuser, no CREATEDB, no "
                     "CREATEROLE), CONNECT taken from PUBLIC; a sign-in is two pairs through the login"),
        Area("Databases", "a database made, dropped, listed", CREATE_DATABASE,
             covered="New database: never over one that is there; a make that fails is taken back whole"),
        Area("The catalogs", "what a server says of itself: its databases, its roles, a database's tables", PG_DATABASE,
             covered="Test reads the version and the tables; New database asks pg_database and pg_roles first"),
        Area("Transactions", "a session's transactions read only, or reading and writing", SET_TRANSACTION,
             covered="a connection opened for reading is read only on the server's side"),
        Area("The Python driver (pg8000)", "pg8000.dbapi.connect and its cursors: host, port, unix_sock, ssl_context, "
             "timeout, application_name", PG8000,
             covered="every connection it opens: one server, a short wait, closed after the question; loaded only when "
                     "a server is asked"),
        Area("Sizes", "a database's and a table's bytes on disk (pg_database_size, pg_total_relation_size)", SIZES),
        Area("The protocol", "the messages between a client and a server, SSL's request among them", PROTOCOL),
        Area("Replication and high availability", "several servers as one: streaming replication, standbys", MANUAL),
    ),
    calls=(
        Call("pg8000.dbapi.connect(user=, password=, database=, host=, port=, unix_sock=, ssl_context=, timeout=, "
             "application_name=)", "a connection to one server, signed in", "The Python driver (pg8000)",
             used="every connection it opens, closed after the question", docs=PG8000),
        Call("SHOW server_version", "the server's version", "The catalogs", used="Test: which PostgreSQL answers", docs=SHOW),
        Call("information_schema.tables", "a schema's tables", "The catalogs", used="Test: what the database holds",
             docs=TABLES),
        Call("pg_database", "the databases a server has", "The catalogs",
             used="New database: never over one that is there", docs=PG_DATABASE),
        Call("pg_roles", "the roles a server has", "The catalogs",
             used="New database: a role left by a make that stopped half way is taken over", docs=PG_ROLES),
        Call("CREATE ROLE", "a role made, with LOGIN and its password", "Roles and privileges",
             used="New database: the role of its own", docs=CREATE_ROLE, writes=True),
        Call("ALTER ROLE", "a role's password and attributes changed", "Roles and privileges",
             used="New database: a role left half way taken over, its password renewed", docs=ALTER_ROLE, writes=True),
        Call("DROP ROLE", "a role removed", "Roles and privileges",
             used="the role taken back when its password could not be kept, or its database not made", docs=DROP_ROLE,
             writes=True),
        Call("CREATE DATABASE ... OWNER", "a database made, owned by a role", "Databases",
             used="New database", docs=CREATE_DATABASE, writes=True),
        Call("DROP DATABASE IF EXISTS", "a database removed", "Databases",
             used="a database whose marker could not be written taken back (never one it did not just make)",
             docs=DROP_DATABASE, writes=True),
        Call("REVOKE CONNECT ON DATABASE ... FROM PUBLIC", "a privilege taken away", "Roles and privileges",
             used="New database: no role but its own and the administrators connects to it", docs=REVOKE, writes=True),
        Call("CREATE TABLE liminal_instance, INSERT", "a table made, a row written", "Databases",
             used="a database made here says what it is in it: its name, the day, what it is to hold", writes=True),
        Call("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY", "a session that reads only", "Transactions",
             used="a connection opened for reading", docs=SET_TRANSACTION),
        Call("pg_database_size(), pg_total_relation_size()", "bytes on disk", "Sizes", docs=SIZES),
    ),
    verified=VERIFIED,
)

APIS = (POSTGRES,)
