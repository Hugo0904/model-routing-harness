import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mrh.adapters.catalogs.catalog import Catalog, Model
from mrh.application.ctrl_logic import CtrlError
from mrh.infrastructure import settings_v2 as v2
from mrh.presentation import ctrl


class CatalogChoicesTests(unittest.TestCase):
    def test_advertised_source_and_offline_cache_are_distinct_and_retirement_is_retained(self):
        result = Catalog("binding", "codex", "public", "test", "native-cli", 1000,
                         (Model("fresh", "Fresh", ("high",)), Model("retired", "Retired", state="retired", retirement_ref="notice")))
        cache = {}
        with patch('mrh.adapters.catalogs.catalog.discover', return_value=[{"tool": "codex"}]), patch('mrh.adapters.catalogs.catalog.describe_tool', return_value={}), patch('mrh.adapters.catalogs.catalog.ToolCatalog.refresh', return_value=result):
            good = ctrl.list_models("codex", cache)
        self.assertEqual((good.status, list(good)), ("advertised", [("fresh", ("high",))]))
        self.assertIn("不代表帳號實際可用", good.description())
        with patch('mrh.adapters.catalogs.catalog.discover', side_effect=RuntimeError()):
            offline = ctrl.list_models("codex", cache)
            builtin = ctrl.list_models("claude", {})
        self.assertEqual(offline.status, "unverified")
        self.assertIn("retired", offline.blocked)
        self.assertIn("離線或更新失敗不等於下架", offline.description())
        self.assertIn("內建參考", builtin.description())
        self.assertEqual(builtin.status, "unverified")

    def test_known_retired_and_unsupported_effort_cannot_be_added_and_cancel_preserves_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "owned" / "settings.json"; v2.init(path); before = path.read_bytes()
            choices = ctrl.ModelChoices([("fresh", ("high",))], status="advertised", source="fixture", blocked=["retired"])
            class Menu:
                def note(self, text): pass
                def pick(self, *args, **kwargs): return False
            session = ctrl.Session(path, Menu(), io.StringIO(), models=lambda _: choices)
            for item in ({"model": "retired"}, {"model": "fresh", "effort": "ultra"}):
                with self.assertRaises(CtrlError): session.check_new_candidates([item], choices)
            self.assertFalse(session.save({"enabled": True}, "candidate"))
            self.assertEqual(path.read_bytes(), before)
