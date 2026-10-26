import unittest

from streamlit_app import parse_flowchart_message, render_flowchart_html


class StreamlitFlowchartRenderTest(unittest.TestCase):
    def test_parse_visual_blank_flowchart_message(self):
        message = (
            "我给你一个挖空版流程图，请补全缺失的符号和文字。\n\n"
            "挖空流程图：\n"
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___、___2___\n"
            "↓\n"
            "（菱形）判断 ___3___\n"
            "↓\n"
            "（平行四边形）输出 ___4___\n"
            "↓\n"
            "（圆角矩形）结束\n\n"
            "请回答：___1___、___2___、___3___、___4___分别应该填什么？"
        )
        parsed = parse_flowchart_message(message)
        self.assertEqual(5, len(parsed["nodes"]))
        self.assertEqual("圆角矩形", parsed["nodes"][0]["shape"])
        self.assertEqual("菱形", parsed["nodes"][2]["shape"])

    def test_render_visual_blank_flowchart_html(self):
        message = (
            "挖空流程图：\n"
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（矩形）处理：___2___\n"
            "↓\n"
            "（圆角矩形）结束\n\n"
            "请回答：___1___、___2___分别应该填什么？"
        )
        rendered = render_flowchart_html(message)
        self.assertIn("flowchart-diagram", rendered)
        self.assertIn("flow-node-terminal", rendered)
        self.assertIn("flow-node-io", rendered)
        self.assertIn("flow-node-process", rendered)
        self.assertIn("flow-arrow", rendered)
        self.assertIn("flow-blank", rendered)

    def test_parse_and_render_branch_flowchart_outputs(self):
        message = (
            "挖空流程图：\n"
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（菱形）判断 ___2___\n"
            "├─ 是 → （平行四边形）输出 ___3___\n"
            "└─ 否 → （平行四边形）输出 ___4___\n"
            "↓\n"
            "（圆角矩形）___5___\n\n"
            "请回答：___1___、___2___、___3___、___4___、___5___分别应该填什么？"
        )
        parsed = parse_flowchart_message(message)
        self.assertEqual(6, len(parsed["nodes"]))
        self.assertEqual("branch", parsed["nodes"][3]["type"])
        self.assertEqual("是", parsed["nodes"][3]["label"])
        self.assertEqual("否", parsed["nodes"][4]["label"])

        rendered = render_flowchart_html(message)
        self.assertIn("flow-branches", rendered)
        self.assertIn("flow-branch-label", rendered)
        self.assertIn("___3___", rendered)
        self.assertIn("___4___", rendered)
        self.assertIn("___5___", rendered)

    def test_render_multi_branch_condition_blanks_in_labels(self):
        message = (
            "挖空流程图：\n"
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（菱形）判断条件 ___2___\n"
            "├─ 是 → （平行四边形）输出 ___3___（进入汇合）\n"
            "└─ 否 → （矩形）继续判断下一条件\n"
            "↓\n"
            "（菱形）判断条件 ___4___\n"
            "├─ 是 → （平行四边形）输出 ___5___（进入汇合）\n"
            "└─ 否（其他情况） → （平行四边形）输出 ___6___（进入汇合）\n"
            "↓\n"
            "（矩形）各分支汇合\n"
            "↓\n"
            "（圆角矩形）___7___\n\n"
            "请回答：___1___、___2___、___3___、___4___、___5___、___6___、___7___分别应该填什么？"
        )
        rendered = render_flowchart_html(message)
        self.assertEqual(7, rendered.count("flow-blank"))
        self.assertIn("其他情况", rendered)
        self.assertEqual(2, rendered.count("flow-node-decision"))
        self.assertIn("flow-node-merge", rendered)
        self.assertIn("各分支汇合", rendered)


if __name__ == "__main__":
    unittest.main()
