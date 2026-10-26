import unittest

import streamlit_app


class StreamlitSuccessFlowTest(unittest.TestCase):
    def test_debug_success_does_not_auto_advance_to_code_optimization(self):
        state = {
            "learning_step": "self_evaluation",
            "learning_phase": "学习成果评价",
            "time_plan": [
                {"name": "分析问题", "minutes": 3},
                {"name": "设计算法", "minutes": 5},
                {"name": "编写程序", "minutes": 5},
                {"name": "代码优化", "minutes": 7},
            ],
            "plan_synced": True,
        }
        metadata = {"reflection_available": True}
        result = streamlit_app.auto_advance_after_completion(
            state,
            "38度是输出发烧，36.5时输出不发烧，我的代码运行成功了",
            metadata,
        )
        self.assertIsNone(result)
        self.assertNotIn("auto_messages", metadata)


if __name__ == "__main__":
    unittest.main()
