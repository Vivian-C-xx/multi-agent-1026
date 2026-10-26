import unittest

from backend.services.learning_flow import clean_reply


class ReplyCleanupTest(unittest.TestCase):
    def test_unavailable_personal_center_reference_is_replaced(self):
        raw = "学习报告已归档，你可至个人中心查看历史记录。"
        cleaned = clean_reply(raw)
        self.assertNotIn("个人中心", cleaned)
        self.assertIn("学习报告", cleaned)

    def test_unavailable_learning_center_reference_is_replaced(self):
        raw = "你可以到学习中心查看历史记录。"
        cleaned = clean_reply(raw)
        self.assertNotIn("学习中心", cleaned)
        self.assertIn("学习报告已保存", cleaned)

    def test_teacher_data_reference_is_replaced_for_student_report(self):
        raw = "学习报告已保存，后续可在教师端学习数据中查看或导出。"
        cleaned = clean_reply(raw)
        self.assertNotIn("教师端学习数据", cleaned)
        self.assertEqual("学习报告已保存。", cleaned)

    def test_student_report_entry_reference_is_removed(self):
        raw = "好的，我已记录你的确认。学习报告已保存，可在学生端右侧的“我的反思报告”中查看。"
        cleaned = clean_reply(raw)
        self.assertNotIn("我的反思报告", cleaned)
        self.assertNotIn("学生端右侧", cleaned)
        self.assertIn("学习报告已保存", cleaned)

    def test_learning_task_step_labels_use_student_task_order(self):
        raw = "IPO分析通过。请告诉我“已完成”，你将自动进入第四步：设计算法。"
        cleaned = clean_reply(raw)
        self.assertNotIn("第四步", cleaned)
        self.assertIn("第二步任务“设计算法”", cleaned)

    def test_programming_step_label_uses_student_task_order(self):
        raw = "流程图框架补全完成。请进入第五步：编写程序。"
        cleaned = clean_reply(raw)
        self.assertNotIn("第五步", cleaned)
        self.assertIn("第三步任务“编写程序”", cleaned)

    def test_flowchart_design_is_second_algorithm_task(self):
        raw = "现在请你确认一下，第三步流程图设计是否完成？确认后我们就进入第二步任务“设计算法”。"
        cleaned = clean_reply(raw)
        self.assertNotIn("第三步流程图设计", cleaned)
        self.assertIn("第二步任务“设计算法”流程图设计", cleaned)

    def test_algorithm_is_not_described_as_coding(self):
        raw = "现在进入第二步任务“设计算法”，也就是编写代码。"
        cleaned = clean_reply(raw)
        self.assertNotIn("设计算法”，也就是编写代码", cleaned)
        self.assertIn("第三步任务“编写程序”，也就是在海龟编辑器编写代码", cleaned)


if __name__ == "__main__":
    unittest.main()
