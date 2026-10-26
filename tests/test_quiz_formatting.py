import unittest
from unittest.mock import patch

from backend.services.learning_flow import (
    decorate_message,
    ensure_complete_quiz_message,
    format_quiz_layout,
    normalize_quiz_grading,
    parse_student_quiz_answers,
    prepare_step_for_prompt,
    quiz_regeneration_prompt,
    quiz_content_issues,
    quiz_layout_issues,
)


class QuizFormattingTest(unittest.TestCase):
    def test_inline_options_are_split_to_separate_lines(self):
        raw = "题目1（单选） 在计算BMI时，哪个输入正确？ A. height B. weight C. print D. input"
        formatted = format_quiz_layout(raw)
        lines = [line.strip() for line in formatted.splitlines() if line.strip()]
        self.assertEqual("1. 在计算BMI时，哪个输入正确？", lines[0])
        self.assertIn("A. height", lines)
        self.assertIn("B. weight", lines)
        self.assertIn("C. print", lines)
        self.assertIn("D. input", lines)
        self.assertIn("1. 在计算BMI时，哪个输入正确？\n\nA. height\n\nB. weight", formatted)

    def test_judgement_hint_is_split_to_own_line(self):
        raw = "题目2（判断） 计算BMI前需要先得到身高。（回答“对”或“错”）"
        formatted = format_quiz_layout(raw)
        self.assertIn("2. 计算BMI前需要先得到身高。\n\n（回答“对”或“错”）", formatted)

    def test_mixed_true_false_and_right_wrong_question_is_rejected(self):
        raw = (
            "2. 如果体温是38.0，判断条件 tem > 37.5 的结果是“真”(True)还是“假”(False)？\n\n"
            "（回答“对”或“错”）"
        )
        issues = quiz_layout_issues(raw)
        self.assertTrue(issues[0]["mixedJudgementFormats"])

    def test_mixed_judgement_question_is_regenerated_as_a_statement(self):
        invalid = (
            "2. 如果体温是38.0，判断条件 tem > 37.5 的结果是True还是False？\n\n"
            "（回答“对”或“错”）"
        )
        regenerated = (
            "1. 当体温为38.0时，表达式 tem > 37.5 的结果为真。\n\n"
            "（回答“对”或“错”）"
        )
        with patch("backend.services.learning_flow.call_llm", return_value=regenerated):
            message, metadata = ensure_complete_quiz_message({}, "assistant", "exercise_intake", invalid)
        self.assertTrue(metadata["quiz_layout_complete"])
        self.assertTrue(metadata["quiz_regenerated"])
        self.assertIn("结果为真", message)
        self.assertFalse(quiz_layout_issues(message))

    def test_missing_single_choice_options_are_detected(self):
        raw = "题目1（单选） 顺序结构是什么？\nA. 从上到下\nB. 随机执行\nC. 只执行最后一行"
        issues = quiz_layout_issues(raw)
        self.assertEqual(["D"], issues[0]["missingOptions"])

    def test_independent_programming_question_is_rejected_from_pretest(self):
        quiz = (
            "1. 请根据成绩等级要求编写一段 Python 程序（）\n\n"
            "A. 使用 if 判断\n\nB. 使用 print 输出\n\nC. 使用 input 输入\n\nD. 使用变量保存数据"
        )
        issues = quiz_content_issues(quiz)
        self.assertTrue(issues[0]["requiresIndependentProgramming"])

    def test_natural_language_is_not_accepted_as_a_code_option(self):
        quiz = (
            "1. 下面哪段代码最像成绩判断器的判断部分（）\n\n"
            "A. print('请输入分数')\n\n"
            "B. score = input('请输入分数：')\n\n"
            "C. if score >= 90: 输出A，否则输出B\n\n"
            "D. score = 90"
        )
        issues = quiz_content_issues(quiz)
        self.assertEqual(["if score >= 90: 输出A，否则输出B"], issues[0]["nonCodeOption"])

    def test_invalid_pretest_content_falls_back_to_knowledge_question(self):
        invalid = (
            "1. 请自己设计代码实现成绩等级判断（）\n\n"
            "A. 使用 if\n\nB. 使用 print\n\nC. 使用 input\n\nD. 使用变量"
        )
        with patch("backend.services.learning_flow.call_llm", return_value=invalid):
            message, metadata = ensure_complete_quiz_message(
                {"exercise_prompt": "输入成绩，判断等级"},
                "assistant",
                "exercise_intake",
                invalid,
            )
        self.assertTrue(metadata["quiz_fallback_generated"])
        self.assertFalse(quiz_content_issues(message))
        self.assertNotIn("请自己设计代码", message)

    def test_incomplete_quiz_is_regenerated_once(self):
        incomplete = "题目1（单选） 顺序结构是什么？ A. 从上到下 B. 随机执行"
        regenerated = "1. 顺序结构最主要的特点是（）\n\nA. 从上到下执行\n\nB. 从下到上执行\n\nC. 随机执行\n\nD. 只执行最后一行"
        with patch("backend.services.learning_flow.call_llm", return_value=regenerated):
            message, metadata = ensure_complete_quiz_message({}, "assistant", "exercise_intake", incomplete)
        self.assertTrue(metadata["quiz_layout_complete"])
        self.assertTrue(metadata["quiz_regenerated"])
        self.assertIn("1. 顺序结构最主要的特点是（）", message)
        self.assertIn("D. 只执行最后一行", message)

    def test_code_block_quiz_is_regenerated(self):
        incomplete = "1. 执行下面代码输出什么？\n```python\nprint(1)\n```\nA. 1\nB. 2\nC. 报错\nD. 空白"
        regenerated = "1. print(1) 的输出是（）\n\nA. 1\n\nB. 2\n\nC. 报错\n\nD. 空白"
        with patch("backend.services.learning_flow.call_llm", return_value=regenerated):
            message, metadata = ensure_complete_quiz_message({}, "assistant", "exercise_intake", incomplete)
        self.assertTrue(metadata["quiz_layout_complete"])
        self.assertTrue(metadata["quiz_regenerated"])
        self.assertNotIn("```", message)

    def test_incomplete_quiz_uses_local_fallback_after_failed_retry(self):
        incomplete = "题目1（单选） 顺序结构是什么？ A. 从上到下 B. 随机执行"
        with patch("backend.services.learning_flow.call_llm", return_value=incomplete):
            message, metadata = ensure_complete_quiz_message(
                {"exercise_prompt": "我要设计一个计算BMI值的程序"},
                "assistant",
                "exercise_intake",
                incomplete,
            )
        self.assertTrue(metadata["quiz_layout_complete"])
        self.assertTrue(metadata["quiz_fallback_generated"])
        self.assertTrue(any(word in message for word in ["BMI", "身高", "体重", "float(input())"]))
        self.assertFalse(quiz_layout_issues(message))

    def test_llm_error_is_not_masked_as_incomplete_options(self):
        error = "还没有配置 DeepSeek API 密钥。请在 .env 中设置 DEEPSEEK_API_KEY 后重新启动。"
        message, metadata = ensure_complete_quiz_message({}, "assistant", "exercise_intake", error)
        self.assertFalse(metadata["quiz_layout_complete"])
        self.assertTrue(metadata["quiz_llm_error"])
        self.assertIn("DeepSeek API 密钥", message)


    def test_input_output_topic_uses_io_fallback_after_failed_retry(self):
        incomplete = "题目1：顺序结构是什么 A. 从上到下 B. 随机执行"
        state = {"current_topic": "输入输出", "exercise_prompt": "输出圆周率取3.1415926"}
        with patch("backend.services.learning_flow.call_llm", return_value=incomplete):
            message, metadata = ensure_complete_quiz_message(state, "assistant", "exercise_intake", incomplete)
        self.assertTrue(metadata["quiz_fallback_generated"])
        self.assertGreaterEqual(
            sum(1 for marker in ["print", "input", "输出", "逗号", "字符串"] if marker in message),
            3,
        )
        self.assertNotIn("程序顺序结构最主要的特点", message)

    def test_quiz_regeneration_prompt_keeps_current_topic(self):
        prompt = quiz_regeneration_prompt(
            {"current_topic": "输入输出", "exercise_prompt": "输出圆周率取3.1415926"},
            "格式不完整",
        )
        self.assertIn("当前学习主题是：输入输出", prompt)
        self.assertIn("不要退回到通用的顺序结构题", prompt)
        self.assertIn("至少三道题必须直接考查输入输出", prompt)

    def test_exercise_intake_saves_prompt_before_llm_call(self):
        state = {"learning_step": "exercise_intake", "learning_phase": "练习题干输入"}
        prepare_step_for_prompt(state, "制作一个月饼计算器：用户输入半径后，输出面积和周长")
        self.assertEqual("制作一个月饼计算器：用户输入半径后，输出面积和周长", state["exercise_prompt"])

    def test_complete_but_irrelevant_quiz_uses_input_output_fallback(self):
        sequence_quiz = (
            "我先给你一组基础知识前测。请按顺序作答。\n\n"
            "1. 程序顺序结构最主要的特点是（）\n\n"
            "A. 根据条件选择性运行代码\n\n"
            "B. 按照代码书写顺序，从上到下依次执行\n\n"
            "C. 重复执行一段代码\n\n"
            "D. 代码执行顺序可以自动跳跃\n\n"
            "2. 在 Python 中，变量的主要作用是（）\n\n"
            "A. 保存数据\n\n"
            "B. 改变电脑屏幕颜色\n\n"
            "C. 自动生成图片\n\n"
            "D. 删除程序\n\n"
            "3. 算法流程图中的开始和结束通常表示程序边界。\n\n"
            "（回答“对”或“错”）"
        )
        state = {
            "current_topic": "输入输出",
            "exercise_prompt": "制作一个月饼计算器：用户输入半径后，输出面积和周长",
        }
        with patch("backend.services.learning_flow.call_llm", return_value=sequence_quiz):
            message, metadata = ensure_complete_quiz_message(state, "assistant", "exercise_intake", sequence_quiz)
        self.assertTrue(metadata["quiz_fallback_generated"])
        self.assertTrue(metadata["quiz_topic_mismatch"])
        self.assertGreaterEqual(
            sum(1 for marker in ["print", "input", "输出", "逗号", "字符串"] if marker in message),
            3,
        )
        self.assertNotIn("程序顺序结构最主要的特点", message)

    def test_local_fallback_quiz_varies_by_seed(self):
        from backend.services.learning_flow import fallback_quiz_message

        state = {"current_topic": "输入输出", "exercise_prompt": "输出圆周率取3.1415926"}
        first = fallback_quiz_message({**state, "quiz_variant_seed": "a"})
        second = fallback_quiz_message({**state, "quiz_variant_seed": "b"})
        self.assertNotEqual(first, second)
        self.assertFalse(quiz_layout_issues(first))
        self.assertFalse(quiz_layout_issues(second))

    def test_quiz_grading_corrects_answer_key_consistency(self):
        message = (
            "前测批改结果：\n\n"
            "第1题：正确 第2题：正确 第3题：正确答案是 错。print(2+3) 输出的结果是数字5，不是字符串“2+3”。"
            "第4题：正确答案是 B。print('你的年龄是',15) 用英文逗号分隔字符串和算式。\n\n"
            "正确率：75% 前测通过：否"
        )
        corrected, metadata = normalize_quiz_grading("B B 错 B", message)
        self.assertTrue(metadata["quiz_grading_corrected"])
        self.assertIn("正确率：100%", corrected)
        self.assertIn("前测通过：是", corrected)

    def test_true_false_answers_are_normalized_to_chinese_judgement_tokens(self):
        self.assertEqual(
            {1: "对", 2: "错", 3: "对", 4: "错"},
            parse_student_quiz_answers("1True 2False 3对 4错"),
        )
        self.assertEqual({1: "错"}, parse_student_quiz_answers("False"))

    def test_true_false_answer_key_can_be_graded(self):
        message = (
            "第1题：你的答案是 True，正确答案是 True，正确。\n"
            "第2题：你的答案是 False，正确答案是 False，正确。\n"
            "正确率：50% 前测通过：否"
        )
        corrected, metadata = normalize_quiz_grading("True False", message)
        self.assertTrue(metadata["quiz_grading_complete"])
        self.assertEqual(100, metadata["quiz_grading_percent"])
        self.assertIn("正确率：100%", corrected)
        self.assertIn("前测通过：是", corrected)

    def test_quiz_grading_correction_allows_next_stage(self):
        state = {"learning_step": "quiz", "learning_phase": "前测"}
        response, phase, metadata = decorate_message(
            state,
            "assistant",
            "第1题：正确 第2题：正确 第3题：正确答案是 错。第4题：正确答案是 B。正确率：75% 前测通过：否",
            "B B 错 B",
        )
        self.assertEqual("plan_allocation", state["learning_step"])
        self.assertEqual("任务拆解与时间分配", phase)
        self.assertTrue(metadata["quiz_passed"])
        self.assertIn("正确率：100%", response)

    def test_perfect_quiz_does_not_handoff_to_mentor(self):
        state = {"learning_step": "quiz", "learning_phase": "前测"}
        response, phase, metadata = decorate_message(
            state,
            "assistant",
            (
                "第1题 你的答案：B 正确答案：B 正确\n"
                "第2题 你的答案：B 正确答案：B 正确\n"
                "第3题 你的答案：对 正确答案：对 正确\n"
                "第4题 你的答案：B 正确答案：B 正确\n\n"
                "正确率：100% 前测通过：是\n\n"
                "接下来，我会请编程导师智能体为你讲解错题知识点。如果后续在计划制定或作品引导方面有需要，我随时在。"
            ),
            "B B 对 B",
        )
        self.assertEqual("plan_allocation", state["learning_step"])
        self.assertEqual("任务拆解与时间分配", phase)
        self.assertTrue(metadata["quiz_passed"])
        self.assertNotIn("讲解错题", response)
        self.assertNotIn("编程导师智能体", response)
        self.assertNotIn("mentor_explained_quiz_errors", metadata)
        self.assertNotIn("after_messages", metadata)
        self.assertIn("任务拆解与时间分配", response)


if __name__ == "__main__":
    unittest.main()
