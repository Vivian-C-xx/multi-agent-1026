import unittest

from backend.agents.prompt_builder import phase_instruction


class FlowchartPromptTest(unittest.TestCase):
    def test_flowchart_prompt_uses_visual_blank_flowchart_format(self):
        prompt = phase_instruction(
            {"learning_step": "flowchart", "learning_phase": "流程图完善"},
            "mentor",
        )
        self.assertIn("挖空流程图", prompt)
        self.assertIn("（圆角矩形）开始", prompt)
        self.assertIn("（平行四边形）输入 ___1___、___2___", prompt)
        self.assertIn("（矩形）计算：BMI = ___3___", prompt)
        self.assertIn("（平行四边形）输出 ___4___", prompt)
        self.assertIn("不要挖空形状名称", prompt)
        self.assertIn("多分支判断", prompt)
        self.assertIn("不要把多分支题简化成只有“是/否”两个最终输出", prompt)


if __name__ == "__main__":
    unittest.main()
