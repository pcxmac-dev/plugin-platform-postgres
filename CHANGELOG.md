# Changelog

## 0.1.0 (2026-11-25)

The first release: PostgreSQL as a database plugin of the platform's Databases section (plugin API 2.3, liminal-libs
1.90.0; Monday list item 13, item 30's step 6; the user, 2026-11-15: "make sure to include integrator plugins for
postgres and mariadb" "alongside existing used databases").

- No instance of its own, and no server ever started: Connect (a database on a server that runs, kept only when it
  answers) and New database (made by the server's administrator, asked once and not kept, with a role of its own that
  owns it, everyone else's CONNECT taken away).
- A make that fails is taken back whole, and a make whose undoing did not reach the server is finished by the next.
- Two methods: `tcp` (5432 unless given another; off this machine only when asked twice, over TLS with the
  certificate checked, and signed in) and `socket` (a Unix socket, on Linux alone: on Windows it is tcp, and said).
- A sign-in is two pairs through the login: never in the value the instances are kept in, never in what a page is
  given. Every connection it makes is closed after the question; one it opens for reading is read only on the
  server's side.
- Holds documents first.
- Its driver, pg8000 (pure Python), loaded only when a server is asked; without it, "driver not installed".
- Its API card: PostgreSQL through pg8000, every address one of postgresql.org's pages or pg8000's, written from what
  was known of them on 2026-11-25 and not fetched.
- Tests on a stand-in driver: no server started, asked or needed.
