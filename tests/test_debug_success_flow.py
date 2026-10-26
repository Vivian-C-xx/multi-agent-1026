import unittest

from backend.agents.router_agent import route_agent
from backend.services.learning_flow import (
    decorate_message,
    guard_reflection_agent_echo,
    guard_algorithm_design_flowchart_format,
    guard_premature_flowchart_completion,
    guard_programming_stage_overguidance,
    looks_like_debug_attempt,
    looks_like_debug_failure,
    looks_like_debug_success,
)


class DebugSuccessFlowTest(unittest.TestCase):
    def test_success_run_words_are_detected(self):
        self.assertTrue(looks_like_debug_success("代码已经成功运行了"))
        self.assertTrue(looks_like_debug_success("程序跑通了，没有报错"))
        self.assertFalse(looks_like_debug_success("我的代码还是不能运行"))
        self.assertTrue(looks_like_debug_failure("我的代码还是不能运行"))

    def test_debug_attempt_detects_code_and_run_result_without_error_words(self):
        self.assertTrue(looks_like_debug_attempt('weight = input("请输入体重")\nprint(weight)'))
        self.assertTrue(looks_like_debug_attempt("修改后重新运行，输出结果是 18.5"))

    def test_success_run_routes_to_peer_before_mentor(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        message = 'print("ok") 成功运行了'
        self.assertEqual("peer", route_agent(message, state))

    def test_success_run_with_negative_output_text_routes_to_peer(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        message = "38度是输出发烧，36.5时输出不发烧，我的代码运行成功了"
        self.assertTrue(looks_like_debug_success(message))
        self.assertFalse(looks_like_debug_failure(message))
        self.assertEqual("peer", route_agent(message, state))

    def test_success_run_only_routes_to_peer_once(self):
        state = {
            "learning_step": "debugging",
            "learning_phase": "代码编写与调试",
            "debug_success_peer_acknowledged": True,
        }
        self.assertEqual("assistant", route_agent("代码成功运行了", state))

    def test_reflection_routes_to_assistant_even_when_reviewing_debugging(self):
        state = {"learning_step": "self_evaluation", "learning_phase": "学习成果评价"}
        message = "在调试代码时，我忽略了错误提示里的行号"
        self.assertEqual("assistant", route_agent(message, state))

    def test_learning_evaluation_routes_to_assistant_before_mentor_step(self):
        state = {"learning_step": "ipo_analysis", "learning_phase": "IPO问题分析"}
        self.assertEqual("assistant", route_agent("我完成了全部学习，请帮我评价", state))

    def test_mentor_ipo_completion_directly_starts_algorithm_design(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "判断输入年份是否为闰年",
        }
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "你的IPO分析非常清晰，完全正确。接下来进入第二步“设计算法”。\n<IPO_STATUS input=done process=done output=done>",
            "输入：年份；处理：能被4整除且不能被100整除，或能被400整除；输出：是否闰年",
        )
        self.assertEqual("流程图完善", phase)
        self.assertEqual("flowchart", state["learning_step"])
        self.assertTrue(metadata["mentor_started_algorithm_design"])
        self.assertIn("编程导师智能体继续带你进入第二步任务“设计算法”", response)
        self.assertIn("挖空流程图", response)
        self.assertNotIn("编程同伴智能体会", response)

    def test_semantically_reasonable_ipo_does_not_need_fixed_completion_words(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "输入成绩，按分数段判断等级",
        }
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "你的分析和题意基本一致，可以继续下一步。\n<IPO_STATUS input=done process=done output=done>",
            "输入分数，按不同的分数范围判断，最后显示对应等级。",
        )
        self.assertEqual("流程图完善", phase)
        self.assertEqual("flowchart", state["learning_step"])
        self.assertTrue(metadata["mentor_started_algorithm_design"])
        self.assertIn("挖空流程图", response)
        self.assertNotIn("是否准备好", response)
        self.assertNotIn("IPO_STATUS", response)

    def test_ipo_ready_acknowledgement_advances_after_all_three_parts_were_recorded(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "判断输入年份是否为闰年",
            "ipo_coverage": {"input": True, "process": True, "output": True},
        }
        _, phase, _ = decorate_message(
            state,
            "mentor",
            "我们继续完成算法设计。",
            "没有大问题",
        )
        self.assertEqual("流程图完善", phase)
        self.assertEqual("flowchart", state["learning_step"])

    def test_input_only_ipo_answer_does_not_enter_flowchart(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "输入成绩，按分数段判断等级",
        }
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "对，成绩是需要先获得的数据。接下来想一想如何根据分数判断等级。\n"
            "<IPO_STATUS input=done process=missing output=missing>",
            "输入用户的成绩",
        )
        self.assertEqual("IPO问题分析", phase)
        self.assertEqual("ipo_analysis", state["learning_step"])
        self.assertEqual({"input": True, "process": False, "output": False}, state["ipo_coverage"])
        self.assertNotIn("挖空流程图", response)
        self.assertNotIn("mentor_started_algorithm_design", metadata)

    def test_ipo_coverage_accumulates_across_natural_language_answers(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "输入成绩，按分数段判断等级",
        }
        decorate_message(
            state,
            "mentor",
            "成绩是需要先获得的数据。\n<IPO_STATUS input=done process=missing output=missing>",
            "程序先拿到学生的成绩",
        )
        decorate_message(
            state,
            "mentor",
            "对，再按照分数范围进行判断。\n<IPO_STATUS input=done process=done output=missing>",
            "然后根据不同分数范围进行判断",
        )
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "最后显示对应等级即可。\n<IPO_STATUS input=done process=done output=done>",
            "把判断出的等级显示给用户",
        )
        self.assertEqual("流程图完善", phase)
        self.assertEqual("flowchart", state["learning_step"])
        self.assertTrue(metadata["mentor_started_algorithm_design"])
        self.assertIn("挖空流程图", response)

    def test_only_material_ipo_problem_keeps_student_in_analysis(self):
        state = {
            "learning_step": "ipo_analysis",
            "learning_phase": "IPO问题分析",
            "exercise_prompt": "判断输入年份是否为闰年",
        }
        _, phase, metadata = decorate_message(
            state,
            "mentor",
            "存在明显问题：没有说明判断闰年的条件，请补充处理逻辑。\n"
            "<IPO_STATUS input=done process=missing output=done>",
            "输入年份，输出结果。",
        )
        self.assertEqual("IPO问题分析", phase)
        self.assertEqual("ipo_analysis", state["learning_step"])
        self.assertNotIn("mentor_started_algorithm_design", metadata)

    def test_assistant_evaluation_request_enters_reflection(self):
        state = {"learning_step": "ipo_analysis", "learning_phase": "IPO问题分析"}
        _, phase, metadata = decorate_message(
            state,
            "assistant",
            "好的，我们进入学习评价。",
            "我完成了全部学习，请帮我评价",
        )
        self.assertEqual("self_evaluation", state["learning_step"])
        self.assertEqual("学习成果评价", phase)
        self.assertTrue(metadata["reflection_available"])

    def test_code_that_cannot_run_routes_to_mentor(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        message = 'a=input("请输入身高") b=input("请输入体重") bmi=b/(a*a) 我的代码还是不能运行'
        self.assertEqual("mentor", route_agent(message, state))

    def test_code_failure_does_not_enter_reflection(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        _, phase, metadata = decorate_message(
            state,
            "mentor",
            "先看报错位置，再检查输入值的数据类型。",
            'a=input("请输入身高") b=input("请输入体重") bmi=b/(a*a) 我的代码还是不能运行',
        )
        self.assertEqual("代码编写与调试", phase)
        self.assertEqual("debugging", state["learning_step"])
        self.assertNotIn("complete_timer", metadata)
        self.assertNotIn("reflection_available", metadata)

    def test_peer_encourages_when_debug_count_reaches_two(self):
        state = {
            "learning_step": "debugging",
            "learning_phase": "代码编写与调试",
            "debug_count": 1,
        }
        _, phase, metadata = decorate_message(
            state,
            "mentor",
            "先检查 input() 得到的数据类型，再决定怎么转换。",
            'weight=input("请输入体重") bmi=weight/2 我的代码还是不能正常运行',
        )
        self.assertEqual("代码编写与调试", phase)
        self.assertEqual(2, state["debug_count"])
        self.assertTrue(state["debug_peer_encouraged"])
        self.assertTrue(metadata["peer_encouraged_before_debug"])
        self.assertEqual("peer", metadata["before_messages"][0]["agent"])
        self.assertIn("连续调试", metadata["before_messages"][0]["message"])

    def test_peer_debug_encouragement_does_not_repeat(self):
        state = {
            "learning_step": "debugging",
            "learning_phase": "代码编写与调试",
            "debug_count": 2,
            "debug_peer_encouraged": True,
        }
        _, _, metadata = decorate_message(
            state,
            "mentor",
            "继续观察报错行号。",
            "代码还是报错",
        )
        self.assertEqual(3, state["debug_count"])
        self.assertNotIn("before_messages", metadata)

    def test_code_submission_counts_as_debug_attempt_in_debugging_stage(self):
        state = {
            "learning_step": "debugging",
            "learning_phase": "代码编写与调试",
            "debug_count": 0,
        }
        _, _, metadata = decorate_message(
            state,
            "mentor",
            "先检查变量类型。",
            'weight = input("请输入体重")\nbmi = weight / 2\nprint(bmi)',
        )
        self.assertEqual(1, state["debug_count"])
        self.assertEqual(1, metadata["debug_count"])

    def test_peer_success_auto_starts_assistant_reflection(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        response, phase, metadata = decorate_message(
            state,
            "peer",
            "太好了，你的程序运行成功了。",
            "代码成功运行了",
        )
        self.assertEqual("学习成果评价", phase)
        self.assertEqual("self_evaluation", state["learning_step"])
        self.assertTrue(metadata["complete_timer"])
        self.assertTrue(metadata["reflection_available"])
        self.assertEqual("assistant", metadata["after_messages"][0]["agent"])
        self.assertIn("学习成果评价", metadata["after_messages"][0]["message"])
        self.assertIn("助教", response)
        self.assertTrue(state["debug_success_peer_acknowledged"])
        self.assertEqual(1, state["debug_count"])
        self.assertEqual(1, metadata["debug_count"])

    def test_mentor_success_reply_is_forced_to_peer_reflection_handoff(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "请继续补充两组运行结果，我再帮你确认。",
            "38度是输出发烧，36.5时输出不发烧，我的代码运行成功了",
        )
        self.assertEqual("学习成果评价", phase)
        self.assertEqual("self_evaluation", state["learning_step"])
        self.assertTrue(metadata["complete_timer"])
        self.assertTrue(metadata["reflection_available"])
        self.assertTrue(metadata["assistant_started_reflection"])
        self.assertIn("代码已经成功运行", response)
        self.assertIn("编程助教智能体", response)
        self.assertEqual("assistant", metadata["after_messages"][0]["agent"])
        self.assertNotIn("继续补充", response)
        self.assertNotIn("代码优化", response)

    def test_reflection_reply_removes_repeated_peer_handoff(self):
        state = {"learning_step": "self_evaluation", "learning_phase": "学习成果评价"}
        raw = (
            "我看到你已经完成“代码优化”。四项任务都已完成，我已帮你暂停倒计时，"
            "接下来由编程助教智能体辅助你进行学习评价和反思。\n\n"
            "我已经收到同伴的反馈：你的程序可以运行了。接下来我们直接进入反思阶段，"
            "一起完成学习评价和改进优化。\n\n"
            "现在进入作品自评环节。请你先给自己的作品打个分。"
        )
        cleaned = guard_reflection_agent_echo(state, "assistant", raw)
        self.assertNotIn("同伴的反馈", cleaned)
        self.assertNotIn("代码优化", cleaned)
        self.assertIn("作品自评", cleaned)

    def test_reflection_reply_replaces_wrong_bmi_task_context(self):
        state = {
            "student_session_id": "student-task-mismatch",
            "learning_step": "self_evaluation",
            "learning_phase": "学习成果评价",
            "exercise_prompt": "我要制作校园跑步计算器",
            "time_plan": [],
        }
        response, _, _ = decorate_message(
            state,
            "assistant",
            "任务完成情况：你完成了BMI计算器的核心功能，能输入身高体重并输出结果。",
            "我已完成自评",
        )
        self.assertIn("当前任务：我要制作校园跑步计算器", response)
        self.assertNotIn("BMI计算器", response)

    def test_flowchart_completion_requires_numbered_blank_answers(self):
        state = {"learning_step": "flowchart", "learning_phase": "流程图完善"}
        guarded = guard_premature_flowchart_completion(
            state,
            "mentor",
            "开始 输入身高 输入体重 计算BMI 输出BMI值",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。请进入第五步。",
        )
        self.assertIn("还没有按空白编号逐项填写", guarded)
        self.assertNotIn("进入第五步", guarded)

    def test_flowchart_numbered_blank_answers_can_pass_guard(self):
        state = {"learning_step": "flowchart", "learning_phase": "流程图完善"}
        original = "回答正确！所有空白都填对了。第四步流程图框架补全完成。"
        guarded = guard_premature_flowchart_completion(
            state,
            "mentor",
            "___1___：平行四边形\n___2___：weight / (height * height)\n___3___：BMI值\n___4___：结束",
            original,
        )
        self.assertEqual(original, guarded)

    def test_flowchart_requires_all_expected_blanks_for_running_lap_task(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "我要制作校园跑步计算器",
        }
        guarded = guard_premature_flowchart_completion(
            state,
            "mentor",
            "1：操场一圈的长度 2：总共跑的长度 3：总共跑的长度=操场一圈的长度*跑的圈数",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。",
        )
        self.assertIn("___4___：", guarded)

    def test_running_lap_flowchart_uses_two_input_nodes(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "我要制作校园跑步计算器",
        }
        guarded = guard_algorithm_design_flowchart_format(
            state,
            "mentor",
            "挖空流程图：\n（圆角矩形）开始\n↓\n（平行四边形）输入 ___1___\n↓\n（矩形）处理：___2___\n↓\n（平行四边形）输出 ___3___\n↓\n（圆角矩形）结束",
        )
        self.assertIn("（平行四边形）输入 ___1___\n↓\n（平行四边形）输入 ___2___", guarded)
        self.assertIn("___4___", guarded)

    def test_branch_flowchart_uses_decision_node_and_five_blanks(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入体温，判断是否发烧",
        }
        guarded = guard_algorithm_design_flowchart_format(
            state,
            "mentor",
            "挖空流程图：\n（圆角矩形）开始\n↓\n（平行四边形）输入 ___1___\n↓\n（矩形）处理：___2___\n↓\n（平行四边形）输出 ___3___\n↓\n（圆角矩形）结束",
        )
        self.assertIn("（菱形）判断 ___2___", guarded)
        self.assertIn("输出 ___3___", guarded)
        self.assertIn("输出 ___4___", guarded)
        self.assertIn("___5___", guarded)

    def test_branch_flowchart_requires_five_numbered_answers(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入体温，判断是否发烧",
        }
        guarded = guard_premature_flowchart_completion(
            state,
            "mentor",
            "1：体温 2：体温>=37.3 3：发烧 4：正常",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。",
        )
        self.assertIn("___5___：", guarded)

    def test_multi_branch_flowchart_uses_elif_style_decisions_and_seven_blanks(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入成绩分数，判断优秀、良好或及格等级",
        }
        guarded = guard_algorithm_design_flowchart_format(
            state,
            "mentor",
            "挖空流程图：\n（圆角矩形）开始\n↓\n（平行四边形）输入 ___1___\n↓\n（菱形）判断 ___2___\n├─ 是 → （平行四边形）输出 ___3___\n└─ 否 → （平行四边形）输出 ___4___\n↓\n（圆角矩形）___5___",
        )
        self.assertEqual(2, guarded.count("（菱形）"))
        self.assertIn("（菱形）判断条件 ___2___", guarded)
        self.assertIn("└─ 否 → （矩形）继续判断下一条件", guarded)
        self.assertIn("（菱形）判断条件 ___4___", guarded)
        self.assertIn("└─ 否（其他情况） → （平行四边形）输出 ___6___（进入汇合）", guarded)
        self.assertIn("（矩形）各分支汇合", guarded)
        self.assertIn("输出 ___5___", guarded)
        self.assertIn("输出 ___6___", guarded)
        self.assertIn("___7___", guarded)

    def test_old_parallel_multi_branch_diagram_is_replaced_with_sequential_decisions(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入成绩分数，判断优秀、良好或及格等级",
        }
        old_diagram = (
            "挖空流程图：\n（圆角矩形）开始\n↓\n（平行四边形）输入 ___1___\n↓\n"
            "（菱形）按条件分支判断\n├─ ___2___ → （平行四边形）输出 ___3___\n"
            "├─ ___4___ → （平行四边形）输出 ___5___\n└─ 其他情况 → （平行四边形）输出 ___6___\n↓\n"
            "（圆角矩形）___7___"
        )
        guarded = guard_algorithm_design_flowchart_format(state, "mentor", old_diagram)
        self.assertEqual(2, guarded.count("（菱形）"))
        self.assertIn("继续判断下一条件", guarded)
        self.assertIn("各分支汇合", guarded)

    def test_four_level_multi_branch_flowchart_uses_three_sequential_decisions(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入成绩，判断优秀、良好、及格或不及格等级",
        }
        guarded = guard_algorithm_design_flowchart_format(
            state,
            "mentor",
            "请生成流程图。",
        )
        self.assertEqual(3, guarded.count("（菱形）"))
        self.assertEqual(2, guarded.count("继续判断下一条件"))
        self.assertIn("___9___", guarded)
        self.assertEqual(9, state["flowchart_expected_blank_count"])

    def test_multi_branch_flowchart_requires_seven_numbered_answers(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "输入成绩分数，判断优秀、良好或及格等级",
        }
        guarded = guard_premature_flowchart_completion(
            state,
            "mentor",
            "1：分数 2：分数>=90 3：优秀 4：分数>=80 5：良好 6：及格",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。",
        )
        self.assertIn("___7___：", guarded)

    def test_flowchart_stage_does_not_advance_without_numbered_answers(self):
        state = {"learning_step": "flowchart", "learning_phase": "流程图完善"}
        response, phase, metadata = decorate_message(
            state,
            "mentor",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。请进入第五步。",
            "开始 输入身高 输入体重 计算BMI 输出BMI值",
        )
        self.assertEqual("flowchart", state["learning_step"])
        self.assertEqual("流程图完善", phase)
        self.assertIn("还没有按空白编号逐项填写", response)

    def test_algorithm_design_replaces_code_blank_with_flowchart(self):
        state = {
            "learning_step": "flowchart",
            "learning_phase": "流程图完善",
            "exercise_prompt": "设计一个计算BMI值的程序",
        }
        guarded = guard_algorithm_design_flowchart_format(
            state,
            "mentor",
            "现在进入第二步任务“设计算法”。请补全Python代码。\nheight = ______\nweight = ______\nbmi = ______\n提示：使用input()和float()",
        )
        self.assertIn("挖空流程图", guarded)
        self.assertIn("（平行四边形）输入 ___1___、___2___", guarded)
        self.assertIn("（矩形）计算：BMI = ___3___", guarded)
        self.assertNotIn("height = ______", guarded)
        self.assertNotIn("Python代码", guarded)

    def test_flowchart_stage_advances_after_numbered_answers_and_confirmation(self):
        state = {"learning_step": "flowchart", "learning_phase": "流程图完善"}
        _, phase, _ = decorate_message(
            state,
            "mentor",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。请进入第五步。",
            "___1___：平行四边形\n___2___：weight / (height * height)\n___3___：BMI值\n___4___：结束",
        )
        self.assertEqual("debugging", state["learning_step"])
        self.assertEqual("代码编写与调试", phase)

    def test_programming_stage_ready_message_gets_self_coding_prompt(self):
        state = {
            "learning_step": "debugging",
            "learning_phase": "代码编写与调试",
            "exercise_prompt": "设计一个计算BMI值的程序",
        }
        guarded = guard_programming_stage_overguidance(
            state,
            "mentor",
            "我准备好了",
            "好的，我们先从第一步开始：输入身高。请写出这一句代码。",
        )
        self.assertIn("自己写出完整 Python 程序", guarded)
        self.assertIn("把代码和运行结果发给我", guarded)
        self.assertNotIn("请写出这一句代码", guarded)

    def test_programming_stage_keeps_debug_feedback_for_errors(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        original = "请先观察报错行号，再检查变量名。"
        guarded = guard_programming_stage_overguidance(
            state,
            "mentor",
            "运行报错 SyntaxError",
            original,
        )
        self.assertEqual(original, guarded)

    def test_flowchart_completion_marks_step_change_without_extra_timer_advance(self):
        state = {"learning_step": "flowchart", "learning_phase": "流程图完善"}
        response, _, metadata = decorate_message(
            state,
            "mentor",
            "回答正确！所有空白都填对了。第四步流程图框架补全完成。请进入第五步：编写程序。",
            "___1___：身高\n___2___：体重\n___3___：weight / (height * height)\n___4___：BMI值",
        )
        self.assertEqual("debugging", state["learning_step"])
        self.assertTrue(metadata["learning_step_changed"])
        self.assertEqual("flowchart", metadata["previous_learning_step"])
        self.assertIn("第三步任务“编写程序”", response)

    def test_programming_prompt_mentions_turtle_editor(self):
        state = {"learning_step": "debugging", "learning_phase": "代码编写与调试"}
        guarded = guard_programming_stage_overguidance(
            state,
            "mentor",
            "我准备好了",
            "请写出第一行代码。",
        )
        self.assertIn("海龟编辑器", guarded)


if __name__ == "__main__":
    unittest.main()
