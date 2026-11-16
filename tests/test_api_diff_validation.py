"""/api/diff must answer 400 for missing parameters, not 500 (STATE: known issue since 2026-11-11)."""
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode

from auto_dev_crew import gui


class TestApiDiffValidation(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _get(self, params: dict):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            path = "/api/diff" + ("?" + urlencode(params) if params else "")
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def test_no_parameters_is_400(self):
        status, _ = self._get({})
        self.assertEqual(status, 400)

    def test_pr_without_repo_is_400(self):
        status, _ = self._get({"pr": "5"})
        self.assertEqual(status, 400)

    def test_workdir_outside_work_area_is_403(self):
        status, _ = self._get({"workdir": "C:/Windows"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
