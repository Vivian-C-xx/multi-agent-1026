import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from backend.config import SESSIONS
from backend.server import Handler
from backend.storage import init_storage


class ReflectionApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["APP_DB_PATH"] = os.path.join(self.tmpdir.name, "api.db")
        init_storage()
        SESSIONS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = None

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        SESSIONS.clear()
        self.tmpdir.cleanup()
        os.environ.pop("APP_DB_PATH", None)

    def request(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        cookie = response.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";", 1)[0]
        conn.close()
        return response.status, json.loads(raw)

    def test_reflection_init_save_and_report_api(self):
        status, data = self.request("POST", "/api/reflection/init", {})
        self.assertEqual(200, status)
        self.assertEqual("OUTCOME_SELF_EVALUATION", data["currentStep"])

        status, data = self.request(
            "POST",
            "/api/reflection/save",
            {
                "step": "OUTCOME_SELF_EVALUATION",
                "payload": {
                    "taskCompletion": "已完成",
                    "testedDifferentData": "有",
                    "runtimeCorrectness": "符合",
                    "programLogic": "检查过",
                    "codeQuality": "基本规范",
                },
            },
        )
        self.assertEqual(200, status)
        self.assertEqual("OUTCOME_AGENT_EVALUATION", data["currentStep"])

        steps = [
            ("OUTCOME_AGENT_EVALUATION", {}),
            ("OUTCOME_CONFIRMATION", {"studentFinalEvaluation": "我确认作品基本完成。", "nextAction": "continue_reflection"}),
            ("REFLECTION_PROCESS_REVIEW", {"selectedProblem": "调试次数较多"}),
            (
                "REFLECTION_CAUSE_ANALYSIS",
                {
                    "studentSelectedCause": "调试方法",
                    "studentEvidence": "调试时没有先看报错行号",
                    "studentConfirmed": True,
                    "confirmedCauses": [{"problem": "调试次数较多", "selectedCause": "调试方法", "studentEvidence": "调试时没有先看报错行号", "studentConfirmed": True}],
                },
            ),
            ("REFLECTION_EXPERIENCE_SUMMARY", {"effectiveStrategies": ["先看报错"]}),
            (
                "REFLECTION_IMPROVEMENT_PLAN",
                {
                    "actions": [
                        {
                            "relatedProblem": "调试次数较多",
                            "relatedCause": "调试方法",
                            "action": "下次先记录报错行号，再检查变量名和缩进。",
                            "verification": "能在两次以内定位错误位置。",
                            "nextUseContext": "代码调试环节",
                        }
                    ]
                },
            ),
        ]
        for step, payload in steps:
            status, data = self.request("POST", "/api/reflection/save", {"step": step, "payload": payload})
            self.assertEqual(200, status)

        self.assertEqual("REFLECTION_COMPLETE", data["currentStep"])
        status, report = self.request("POST", "/api/reflection/report", {"studentConfirmed": True})
        self.assertEqual(200, status)
        self.assertGreater(report["reportId"], 0)

        status, previous = self.request("GET", "/api/reflection/previous")
        self.assertEqual(200, status)
        self.assertEqual(report["reportId"], previous["reportId"])
        self.assertEqual("我确认作品基本完成。", previous["previousReflection"]["outcomeSummary"]["studentFinalEvaluation"])
        self.assertEqual(
            "下次先记录报错行号，再检查变量名和缩进。",
            previous["previousReflection"]["improvementActions"][0]["action"],
        )


if __name__ == "__main__":
    unittest.main()
