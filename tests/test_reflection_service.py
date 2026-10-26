import os
import tempfile
import unittest

from backend.storage import init_storage, save_interaction
from backend.services.reflection_service import (
    REFLECTION_STEPS,
    assemble_reflection_context,
    build_agent_outcome_evaluation,
    get_reflection_session_payload,
    reply_conflicts_with_current_task,
    save_final_report,
    save_reflection_step,
    task_reviews_from_plan,
    validate_improvement_action,
)


class ReflectionServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["APP_DB_PATH"] = os.path.join(self.tmpdir.name, "app.db")
        init_storage()
        self.state = {
            "student_session_id": "student-a",
            "student_name": "小林",
            "learning_phase": "学习成果评价",
            "learning_step": "self_evaluation",
            "current_topic": "条件判断",
            "exercise_prompt": "输入体温，判断是否发烧",
            "time_plan": [
                {"name": "分析问题", "minutes": 3},
                {"name": "设计算法", "minutes": 4},
                {"name": "编写程序", "minutes": 8},
                {"name": "代码优化", "minutes": 5},
            ],
            "debug_count": 2,
        }

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("APP_DB_PATH", None)

    def test_task_completion_summary_marks_all_done_in_self_evaluation(self):
        reviews = task_reviews_from_plan(self.state["time_plan"], "self_evaluation")
        self.assertEqual(4, len(reviews))
        self.assertTrue(all(item["completed"] for item in reviews))
        self.assertIsNone(reviews[0]["actualMinutes"])

    def test_assemble_context_uses_real_state_and_marks_missing_data(self):
        context = assemble_reflection_context(self.state)
        self.assertTrue(context["learningGoal"]["available"])
        self.assertTrue(context["plannedTasks"]["available"])
        self.assertEqual(2, context["debugCount"]["value"])
        self.assertFalse(context["testResults"]["available"])
        self.assertFalse(context["actualDurations"]["available"])

    def test_create_and_restore_unfinished_reflection_session(self):
        first = get_reflection_session_payload(self.state)
        second = get_reflection_session_payload(self.state)
        self.assertEqual(first["session"]["id"], second["session"]["id"])
        self.assertEqual("OUTCOME_SELF_EVALUATION", first["currentStep"])

    def test_save_steps_advances_reflection_state(self):
        result = save_reflection_step(
            self.state,
            "OUTCOME_SELF_EVALUATION",
            {
                "taskCompletion": "已完成",
                "testedDifferentData": "没有",
                "runtimeCorrectness": "不确定",
                "programLogic": "检查过",
                "codeQuality": "基本规范",
            },
        )
        self.assertEqual("OUTCOME_AGENT_EVALUATION", result["currentStep"])
        self.assertIn("OUTCOME_SELF_EVALUATION", result["draft"])

    def test_outcome_evaluation_flags_success_without_tests_as_not_fully_correct(self):
        save_interaction(self.state, "peer", "代码运行成功了", "继续进入评价", "代码编写与调试", {})
        context = assemble_reflection_context(self.state)
        outcome = build_agent_outcome_evaluation(context, {"taskCompletion": "已完成"})
        self.assertIn("测试数据较少", "；".join(outcome["problems"]))
        self.assertEqual("需要更多测试", outcome["agentEvaluation"]["runtimeCorrectness"]["status"])

    def test_improvement_action_validation_rejects_vague_action(self):
        result = validate_improvement_action(
            {
                "relatedProblem": "调试慢",
                "action": "认真一点",
                "verification": "下次少出错",
                "nextUseContext": "编写程序",
            }
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["needsDetail"])

    def test_full_report_save_requires_confirmed_improvement_actions(self):
        save_reflection_step(self.state, "OUTCOME_SELF_EVALUATION", {"taskCompletion": "已完成", "testedDifferentData": "有", "runtimeCorrectness": "符合", "programLogic": "检查过", "codeQuality": "基本规范"})
        save_reflection_step(self.state, "OUTCOME_AGENT_EVALUATION", {})
        save_reflection_step(self.state, "OUTCOME_CONFIRMATION", {"studentFinalEvaluation": "我确认功能基本完成", "nextAction": "continue_reflection"})
        save_reflection_step(self.state, "REFLECTION_PROCESS_REVIEW", {"selectedProblem": "测试数据较少"})
        save_reflection_step(
            self.state,
            "REFLECTION_CAUSE_ANALYSIS",
            {
                "studentSelectedCause": "调试方法",
                "studentEvidence": "我没有先看行号",
                "studentConfirmed": True,
                "confirmedCauses": [{"problem": "调试次数较多", "selectedCause": "调试方法", "studentEvidence": "我没有先看行号", "studentConfirmed": True}],
            },
        )
        save_reflection_step(self.state, "REFLECTION_EXPERIENCE_SUMMARY", {"effectiveStrategies": ["先看报错行号"]})
        save_reflection_step(
            self.state,
            "REFLECTION_IMPROVEMENT_PLAN",
            {
                "actions": [
                    {
                        "relatedProblem": "调试次数较多",
                        "relatedCause": "调试方法",
                        "action": "下次报错后先记录行号，再检查这一行的变量名和缩进。",
                        "verification": "能在两次以内说出错误位置和修改方向。",
                        "nextUseContext": "代码调试环节",
                    }
                ]
            },
        )
        result = save_final_report(self.state, {"studentConfirmed": True})
        self.assertGreater(result["reportId"], 0)
        self.assertEqual("REFLECTION_COMPLETE", self.state["reflection_current_step"])

    def test_outcome_confirmation_can_return_to_debug(self):
        save_reflection_step(self.state, "OUTCOME_SELF_EVALUATION", {"taskCompletion": "部分完成"})
        save_reflection_step(self.state, "OUTCOME_AGENT_EVALUATION", {})
        result = save_reflection_step(self.state, "OUTCOME_CONFIRMATION", {"nextAction": "return_to_debug"})
        self.assertTrue(result["returnedToDebug"])
        self.assertEqual("debugging", self.state["learning_step"])

    def test_next_run_can_read_previous_improvement_actions(self):
        self.test_full_report_save_requires_confirmed_improvement_actions()
        self.state["learning_phase"] = "主题作品体验"
        self.state["learning_step"] = "topic_intro"
        self.state["current_topic"] = "循环"
        self.state["exercise_prompt"] = ""
        context = assemble_reflection_context(self.state)
        previous = context["previousReflection"]
        self.assertIn("improvementActions", previous)
        self.assertEqual(1, len(previous["improvementActions"]))

    def test_cannot_read_other_learning_session(self):
        with self.assertRaises(PermissionError):
            assemble_reflection_context(self.state, learning_session_id="student-b")

    def test_reflection_reply_conflict_detects_old_bmi_task(self):
        state = {"exercise_prompt": "我要制作校园跑步计算器"}
        self.assertTrue(reply_conflicts_with_current_task(state, "你完成了BMI计算器，height 和 weight 命名清楚。"))
        self.assertFalse(reply_conflicts_with_current_task(state, "你完成了校园跑步计算器的核心功能。"))

    def test_step_order_contains_required_flow(self):
        self.assertEqual("OUTCOME_SELF_EVALUATION", REFLECTION_STEPS[0])
        self.assertEqual("REFLECTION_COMPLETE", REFLECTION_STEPS[-1])
        self.assertIn("OUTCOME_AGENT_EVALUATION", REFLECTION_STEPS)
        self.assertIn("REFLECTION_CAUSE_ANALYSIS", REFLECTION_STEPS)


if __name__ == "__main__":
    unittest.main()
