import unittest

from backend.services.learning_flow import decorate_message


def overtime_state():
    return {
        "learning_step": "flowchart",
        "learning_phase": "流程图完善",
        "overtime_replan_pending": True,
        "overtime_current_index": 1,
        "overtime_completed_tasks": 1,
        "overtime_remaining_minutes": 14,
        "overtime_remaining_task_names": ["设计算法", "编写程序", "代码优化"],
        "time_plan": [
            {"name": "分析问题", "minutes": 3},
            {"name": "设计算法", "minutes": 3},
            {"name": "编写程序", "minutes": 7},
            {"name": "代码优化", "minutes": 7},
        ],
    }


class OvertimeReplanTest(unittest.TestCase):
    def test_overtime_replan_rejects_total_larger_than_remaining_budget(self):
        state = overtime_state()
        response, _, metadata = decorate_message(
            state,
            "peer",
            "好的，我来帮你重新分配。",
            "设计算法3分钟，编写程序7分钟，代码优化7分钟",
        )
        self.assertTrue(metadata["replan_invalid"])
        self.assertTrue(state["overtime_replan_pending"])
        self.assertNotIn("reset_timer", metadata)
        self.assertIn("剩余总时间应为14分钟", response)
        self.assertIn("当前填写总计17分钟", response)

    def test_overtime_replan_accepts_exact_remaining_budget(self):
        state = overtime_state()
        _, _, metadata = decorate_message(
            state,
            "peer",
            "好的，新的剩余计划已同步。",
            "设计算法2分钟，编写程序6分钟，代码优化6分钟",
        )
        self.assertFalse(state["overtime_replan_pending"])
        self.assertTrue(metadata["reset_timer"])
        self.assertTrue(metadata["remaining_replan"])
        self.assertEqual(14, metadata["total_minutes"])
        self.assertEqual(1, metadata["replan_current_index"])
        self.assertEqual(
            [
                {"name": "分析问题", "minutes": 3},
                {"name": "设计算法", "minutes": 2},
                {"name": "编写程序", "minutes": 6},
                {"name": "代码优化", "minutes": 6},
            ],
            metadata["time_plan"],
        )


if __name__ == "__main__":
    unittest.main()
