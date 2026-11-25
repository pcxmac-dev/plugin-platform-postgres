"""Every plugin here conforms to the class contract (plugin API 2.3): liminal_libs.sources.conformance, read from
the plugin alone (nothing opened, nothing sent)."""
from __future__ import annotations

import pathlib

import plugin_platform_postgres as module
from liminal_libs.sources.conformance import assert_module_conforms
from liminal_libs.sources.registry import _plugins_in
from liminal_libs.storage.databases import DatabasePlugin, variable_of
from liminal_libs.ui import STATIC


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert [p.name for p in found] == ["postgres"] and all(p.api == "2.3" and not p.is_record for p in found)
    (p,) = found
    assert isinstance(p, DatabasePlugin) and (p.SYSTEM, p.KIND, p.ENGINE) == (DatabasePlugin.SYSTEM, "database", "postgres")
    assert p.SYSTEM == "platform" and p.SECTION == "databases"  # the platform's Databases section (liminal-libs 1.90.0)
    assert module.__name__ == "plugin_platform_postgres" and pathlib.Path(module.__file__).resolve().is_relative_to(
        pathlib.Path(__file__).resolve().parents[1] / "src")  # this checkout's
    assert p.METHODS == (("tcp", "socket") if module.SOCKETS else ("tcp",)) and p.HOLDS == ("documents",)
    assert p.SERVER is True and p.SHARES is False and p.DRIVER == "pg8000" and p.default_port() == 5432
    assert p.options == (variable_of("postgres"),) == ("POSTGRES_INSTANCES",)
    assert p.apis and p.interface()["apis"] == [a.name for a in p.apis]  # what it attaches to (2.2)
    assert set(p.interface()["hooks"]) >= {"builtin", "open", "probe", "make"}
    assert f"    {p.ICON}: '" in (STATIC / "icons.js").read_text(encoding="utf-8")
    assert module.__version__ == "0.1.0" and [q.name for q in _plugins_in(module, "test")] == ["postgres"]
