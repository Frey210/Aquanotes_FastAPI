import sys
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI


class MonitoringRouteTest(unittest.TestCase):
    def test_both_paths_are_direct_routes_but_schema_stays_unchanged(self):
        fake_auth = types.ModuleType("app.auth")
        fake_auth.get_current_user = lambda: None

        with patch.dict(sys.modules, {"app.auth": fake_auth}):
            sys.modules.pop("app.routers.monitoring", None)
            from app.routers import monitoring

        app = FastAPI()
        app.include_router(monitoring.router)

        route_paths = [route.path for route in monitoring.router.routes]
        self.assertIn("/monitoring", route_paths)
        self.assertIn("/monitoring/", route_paths)
        self.assertNotIn("/monitoring", app.openapi()["paths"])
        self.assertIn("/monitoring/", app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
