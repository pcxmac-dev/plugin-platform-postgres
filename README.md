# plugin-platform-postgres

PostgreSQL for [Liminal](https://github.com/pcxmac-dev/liminal-charts): databases on PostgreSQL servers that already
run, connected, or made there with a role of their own. It never starts a server.

## What a database plugin is

A Liminal plugin of the platform's (plugin API 2.3, `liminal_libs.storage.databases`), drawn in its Databases
section: one engine's. It holds **instances**. An instance is a database the plugin made, or a connection to one that
exists, and each has its own configuration: what it holds, where it is, the method it is reached by, its port, and on a
server the role used there. The platform's Databases section lists them, tests them and changes them; the integrator
and the charts include the platform and open them in their own process.

- **What you add is kept through the plugin's login**, as one value under `POSTGRES_INSTANCES`: never in a file of this
  software's. A sign-in is two more pairs through the login (`POSTGRES_<INSTANCE>_USER`, `POSTGRES_<INSTANCE>_PASSWORD`),
  never in that value and never shown.
- **A change is made by the system that holds the data alone.** The suite on another system (the one inside WSL) reads
  what is kept there and changes nothing of it.
- **Forgetting an instance removes nothing**: what it holds stays where it is. Only you remove data.

## Installing

The app finds it through the entry point group `liminal.providers` and lists it as `package:
plugin-platform-postgres`, with this package's version; a checkout in the workspace's `plugins/` or `incoming/` folder
is loaded from there. It needs `liminal-libs` 1.90.0 or newer and its driver, `pg8000` (pure Python, nothing
compiled). The driver is loaded only when a server is asked: without it the plugin says "driver not installed", and
everything else works.

```
python -m pip install -e ".[dev]"
python -m pytest -q
```

The tests start, ask and need no server: the driver is a stand-in (a fake `pg8000` whose `connect` answers for
stand-in servers), and one test checks that what the plugin gives it binds to the real driver's `connect`, read from
the installed package. One more reads the makers' documentation pages, and only with `LIMINAL_VENDOR_PAGES=1`.

## Its instances

It has **no instance of its own**: every instance is one you add.

- **Connect**: a database on a server that runs, kept only when it answers. A server that signs in is given the role's
  name and password with the connection; with none, it signs in as this machine's user, as PostgreSQL's own clients
  do (a socket's peer authentication, or a server that trusts it).
- **New database**: on a server you name, made by its administrator, whose name and password are asked once and not
  kept. The database gets a role of its own, `liminal_<instance>` (LOGIN; no superuser, no CREATEDB, no CREATEROLE),
  which **owns** it; everyone else's CONNECT on it is taken away (`REVOKE CONNECT ... FROM PUBLIC`). The role's
  password is made here, kept through the login and never shown. The database says what it is in a small table
  (`liminal_instance`), written by its role.
  - Never over a database that is there: Connect keeps one that exists.
  - A make that fails is taken back whole: a role whose password could not be kept is dropped; a database whose marker
    could not be written is dropped with its role, and its sign-in forgotten. When even that undoing did not reach the
    server, the next make of the same name finds the role, and the database it owns saying nothing of itself, and
    finishes them.
- **Opened** (`open`): a DB-API connection of pg8000's to the database, signed in as its role, read only on the
  server's side unless it is asked to write; closed by whoever asked.
- **What it holds**: documents first. The stores that write there (a store's pick naming an instance) come with item 10.

## Its methods

- **`tcp`**: an address and a port, 5432 unless given another. **Off this machine only when you say so twice**, and
  then over TLS alone, the server's certificate checked against its name, and signed in. On this machine without TLS
  it is as pg8000 does by itself: encrypted, unchecked, when the server offers it. A status asks this machine alone
  whether a server listens; another machine is asked only by a test you start.
- **`socket`**: a Unix socket, on Linux (WSL too): its folder (`/run/postgresql`, the file then `.s.PGSQL.5432`) or
  the whole file (`/run/postgresql/.s.PGSQL.5433`). **Not on Windows**: Python has no Unix socket there and PostgreSQL
  takes no named pipe, so on Windows a server is reached by tcp, and the plugin says so.

## Sharing

The plugin keeps no shares, and says so: who reaches a server is the server's to decide (its `pg_hba.conf` and its
roles' grants).

## Its API

Its page in every app shows what it attaches to (`DATABASE.apis`): PostgreSQL's own pages and pg8000's, every part of
the engine with what the plugin does with it, and the statements it sends among the rest; and what it knows here
without asking anything (`DATABASE.api_facts()`): the driver this Python carries and the methods this system offers.
The addresses were written from what was known of the sites, not fetched: `LIMINAL_VENDOR_PAGES=1` checks them.
