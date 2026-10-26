import random
import re
from datetime import datetime

from backend.services.llm_client import call_llm
from backend.services.reflection_service import (
    assemble_reflection_context,
    build_agent_outcome_evaluation,
    format_outcome_evaluation_feedback,
    reply_conflicts_with_current_task,
)
from backend.utils import contains_any

TASK_PATTERNS = [
    ("分析问题", ["分析问题", "问题分析", "需求分析", "分析"]),
    ("设计算法", ["设计算法", "算法设计", "设计程序", "程序设计", "设计步骤", "设计思路", "算法"]),
    ("编写程序", ["编写程序", "程序编写", "代码编写", "写代码", "写程序", "编程"]),
    ("代码优化", ["代码优化", "优化代码", "优化程序", "程序优化", "优化"]),
]
TASK_NAMES = [name for name, _ in TASK_PATTERNS]

REPLAN_WORDS = ["重新分配", "调整时间", "剩余时间", "再分配", "重置时间"]
DEBUG_SUCCESS_WORDS = [
    "调试成功",
    "运行成功",
    "成功运行",
    "成功运行了",
    "可以运行了",
    "能运行了",
    "可以正常运行",
    "能正常运行",
    "跑通",
    "跑通了",
    "没有报错",
    "无报错",
    "代码成功",
    "问题解决",
]
DEBUG_FAILURE_WORDS = [
    "不能运行",
    "不能正常运行",
    "不能成功运行",
    "无法运行",
    "不会运行",
    "没法运行",
    "运行不了",
    "跑不通",
    "不能执行",
    "无法执行",
    "还是不能运行",
    "还不能运行",
    "仍然不能运行",
    "没有成功运行",
    "没成功运行",
    "没有跑通",
    "还是报错",
    "仍然报错",
    "报错",
    "错误",
    "bug",
    "Bug",
    "BUG",
    "Traceback",
    "SyntaxError",
    "TypeError",
    "NameError",
]
CODE_HELP_WORDS = [
    "修改代码",
    "改代码",
    "优化代码",
    "调试代码",
    "代码怎么改",
    "哪里错",
    "哪错",
    "为什么错",
    "运行错误",
    "运行结果",
    "运行不了",
    "不能运行",
]
FLOWCHART_COMPLETION_WORDS = [
    "流程图框架补全完成",
    "流程图完成",
    "流程图正确",
    "所有空白都填对",
    "所有空白都对",
    "进入第五步",
    "开始第五步",
    "进入第三步任务",
    "开始第三步任务",
    "进入代码编写",
    "开始代码编写",
]
# IPO 阶段由导师按语义记录三项是否已完成；不要求学生使用固定措辞。
IPO_MATERIAL_PROBLEM_PATTERNS = [
    r"存在(?:明显|关键)?(?:的)?(?:逻辑)?问题",
    r"(?:输入|处理|输出).{0,12}(?:明显错误|有误|不对|矛盾)",
    r"(?:缺少|遗漏|没有说明).{0,16}(?:关键|必要|核心|输入|处理|输出|条件|结果)",
    r"(?:请|需要)(?:重新|继续).{0,20}(?:分析|补充|说明|修改).{0,20}(?:输入|处理|输出|条件|逻辑)",
]
IPO_STATUS_MARKER_RE = re.compile(
    r"\s*<IPO_STATUS\s+input=(done|missing)\s+process=(done|missing)\s+output=(done|missing)\s*>",
    re.I,
)
REFLECTION_WORDS = [
    "学习完",
    "学完",
    "本节课结束",
    "完成相关内容",
    "完成全部学习",
    "完成了全部学习",
    "全部学习完成",
    "请帮我评价",
    "帮我评价",
    "请生成报告",
    "自评",
    "反思",
    "学习评价",
]
LLM_ERROR_MARKERS = [
    "还没有配置 DeepSeek API 密钥",
    "大模型 API",
    "暂时无法连接大模型",
    "连接大模型 API",
    "调用大模型 API",
    "大模型返回了空内容",
]

AGENT_LABELS = "编程自主学习管家|编程助教智能体|编程导师智能体|编程同伴智能体"
AGENT_LABEL_RE = re.compile(
    rf"(?:^|\n)\s*(?:[【\[]\s*(?:{AGENT_LABELS})\s*[】\]]\s*[:：]?|(?:{AGENT_LABELS})\s*[:：])\s*"
)


def strip_agent_labels(message):
    cleaned = message or ""
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = AGENT_LABEL_RE.sub("\n", cleaned)
    return cleaned.strip()


def soften_reply_format(message):
    parts = re.split(r"(```.*?```)", message or "", flags=re.S)
    cleaned_parts = []
    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            cleaned_parts.append(part)
            continue
        part = re.sub(r"(?m)^\s*[-*_]{3,}\s*$\n?", "", part)
        part = re.sub(r"(?m)^\s*#{1,6}\s*", "", part)
        part = re.sub(r"(?m)^\s*[*+-]\s+", "", part)
        part = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", part)
        part = re.sub(r"(?m)^\s*>\s*", "", part)
        cleaned_parts.append(part)
    return "".join(cleaned_parts).strip()


def clean_reply(message):
    cleaned = soften_reply_format(strip_agent_labels(message))
    cleaned = replace_unavailable_ui_references(cleaned)
    return normalize_student_task_step_labels(cleaned)


def normalize_student_task_step_labels(message):
    if not message:
        return message
    text = message
    replacements = [
        (r"当前是第三步流程图设计", "当前是第二步任务“设计算法”流程图设计"),
        (r"第三步流程图设计", "第二步任务“设计算法”流程图设计"),
        (r"第三步[：:]?\s*流程图", "第二步任务“设计算法”流程图"),
        (r"当前是第三步[：:]?请用IPO模式", "当前是第一步任务“分析问题”：请用IPO模式"),
        (r"当前是第三步[：:]?", "当前是第一步任务“分析问题”："),
        (r"进入第二步任务[“\"]?设计算法[”\"]?[，,、]?\s*也就是(?:编写|写)代码", "进入第三步任务“编写程序”，也就是在海龟编辑器编写代码"),
        (r"第二步任务[“\"]?设计算法[”\"]?[，,、]?\s*也就是(?:编写|写)代码", "第三步任务“编写程序”，也就是在海龟编辑器编写代码"),
        (r"开始第四步[：:]?\s*(?:生成流程图框架|设计流程图|设计算法)", "开始第二步任务“设计算法”"),
        (r"进入第四步[：:]?\s*(?:生成流程图框架|设计流程图|设计算法)", "进入第二步任务“设计算法”"),
        (r"第四步[：:]?\s*(?:流程图框架补全|流程图|设计算法)", "第二步任务“设计算法”"),
        (r"第四步流程图框架", "第二步任务“设计算法”流程图框架"),
        (r"第四步", "第二步任务“设计算法”"),
        (r"开始第五步[：:]?\s*(?:编写代码|编写程序|代码编写|编程)", "开始第三步任务“编写程序”"),
        (r"进入第五步[：:]?\s*(?:编写代码|编写程序|代码编写|编程)", "进入第三步任务“编写程序”"),
        (r"第五步[：:]?\s*(?:编写代码|编写程序|代码编写|编程|编写程序与调试)", "第三步任务“编写程序”"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def numbered_flowchart_answer_count(message):
    text = message or ""
    numbered = set(
        re.findall(
            r"(?<![\d.])(?:___\s*)?([1-9])(?:\s*___)?\s*(?:[：:=、)）]|[.](?!\d))",
            text,
        )
    )
    compact = re.sub(r"\s+", "", text)
    compact_numbered = set(re.findall(r"___?([1-9])___?", compact))
    return len(numbered | compact_numbered)


def looks_like_numbered_flowchart_answer(message, expected_count=3):
    return numbered_flowchart_answer_count(message) >= expected_count


def mentor_claims_flowchart_complete(message):
    return contains_any(message or "", FLOWCHART_COMPLETION_WORDS)


def mentor_identifies_material_ipo_problem(message):
    """只识别会影响实现的明确问题，不把措辞或格式建议当作未完成。"""
    text = re.sub(r"\s+", "", message or "")
    return any(re.search(pattern, text) for pattern in IPO_MATERIAL_PROBLEM_PATTERNS)


def extract_ipo_status_marker(message):
    """读取导师的内部 IPO 状态标记，并确保标记不会展示给学生。"""
    match = IPO_STATUS_MARKER_RE.search(message or "")
    if not match:
        return None, message
    status = dict(zip(("input", "process", "output"), (value.lower() for value in match.groups())))
    return status, IPO_STATUS_MARKER_RE.sub("", message or "").strip()


def update_ipo_coverage(state, status):
    coverage = state.setdefault("ipo_coverage", {"input": False, "process": False, "output": False})
    for item in ("input", "process", "output"):
        coverage[item] = bool(coverage.get(item) or status.get(item) == "done")
    return coverage


def ipo_analysis_is_acceptable(state, mentor_message):
    """仅当 IPO 三项均已按语义确认、且无实质问题时，才进入流程图。"""
    coverage = state.get("ipo_coverage") or {}
    return (
        all(coverage.get(item) for item in ("input", "process", "output"))
        and not mentor_identifies_material_ipo_problem(mentor_message)
    )


def looks_like_programming_ready(message):
    return contains_any(message or "", ["准备好了", "开始写", "开始编程", "可以写", "进入编写", "写代码"])


def looks_like_flowchart_diagram(message):
    text = message or ""
    return "挖空流程图" in text and bool(re.search(r"（(?:圆角矩形|平行四边形|矩形|菱形)）", text))


def flowchart_blank_count(message):
    return len(set(re.findall(r"___\s*([1-9])\s*___", message or "")))


def needs_running_lap_flowchart(exercise):
    return contains_any(exercise or "", ["校园跑步", "跑步", "操场", "一圈", "圈数", "总共跑", "总长度", "跑的圈"])


def needs_branch_flowchart(exercise):
    return contains_any(exercise or "", ["分支结构", "判断", "如果", "条件", "是否", "发烧", "及格", "闰年", "等级"])


def needs_multi_branch_flowchart(exercise):
    return contains_any(
        exercise or "",
        [
            "多分支",
            "多重分支",
            "elif",
            "等级",
            "成绩",
            "分数",
            "优秀",
            "良好",
            "及格",
            "不及格",
            "A等",
            "B等",
            "C等",
            "D等",
            "A/B/C",
            "A、B、C",
        ],
    )


def multi_branch_output_count(exercise):
    """根据题干可识别的档位数决定通用多分支模板的结果分支数。"""
    text = exercise or ""
    has_four_levels = (
        all(level in text for level in ("优秀", "良好", "及格", "不及格"))
        or all(level in text for level in ("A等", "B等", "C等", "D等"))
        or bool(re.search(r"\bA\s*[/、，,]\s*B\s*[/、，,]\s*C\s*[/、，,]\s*D\b", text, re.I))
    )
    return 4 if has_four_levels else 3


def flowchart_expected_blank_count(state):
    exercise = state.get("exercise_prompt") or ""
    if needs_multi_branch_flowchart(exercise):
        return multi_branch_output_count(exercise) * 2 + 1
    if needs_branch_flowchart(exercise):
        return 5
    if contains_any(exercise, ["BMI", "bmi", "身高", "体重"]) or needs_running_lap_flowchart(exercise):
        return 4
    return 3


def is_sequential_multi_branch_flowchart(message, output_count=3):
    """多分支必须表现为 if / elif / else 的串联判断，而非单个菱形的并列出口。"""
    text = message or ""
    return (
        len(re.findall(r"（菱形）", text)) >= output_count - 1
        and "继续判断下一条件" in text
        and "各分支汇合" in text
    )


def looks_like_code_blank_algorithm(message):
    text = message or ""
    if contains_any(text, ["Python代码", "代码填空", "input()", "float(", "print("]):
        return True
    return bool(re.search(r"(?m)^\s*[A-Za-z_]\w*\s*=\s*[_＿—-]{3,}", text))


def algorithm_flowchart_prompt_message(state):
    exercise = state.get("exercise_prompt") or "当前练习任务"
    if needs_multi_branch_flowchart(exercise):
        output_count = multi_branch_output_count(exercise)
        lines = ["（圆角矩形）开始", "↓", "（平行四边形）输入 ___1___", "↓"]
        blank_number = 2
        for decision_index in range(output_count - 1):
            lines.append(f"（菱形）判断条件 ___{blank_number}___")
            blank_number += 1
            lines.append(f"├─ 是 → （平行四边形）输出 ___{blank_number}___（进入汇合）")
            blank_number += 1
            if decision_index < output_count - 2:
                lines.append("└─ 否 → （矩形）继续判断下一条件")
            else:
                lines.append(f"└─ 否（其他情况） → （平行四边形）输出 ___{blank_number}___（进入汇合）")
                blank_number += 1
            lines.append("↓")
        lines.extend(["（矩形）各分支汇合", "↓", f"（圆角矩形）___{blank_number}___"])
        nodes = "\n".join(lines)
        blanks = "、".join(f"___{index}___" for index in range(1, blank_number + 1))
    elif needs_branch_flowchart(exercise):
        nodes = (
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（菱形）判断 ___2___\n"
            "├─ 是 → （平行四边形）输出 ___3___\n"
            "└─ 否 → （平行四边形）输出 ___4___\n"
            "↓\n"
            "（圆角矩形）___5___"
        )
        blanks = "___1___、___2___、___3___、___4___、___5___"
    elif contains_any(exercise, ["BMI", "bmi", "身高", "体重"]):
        nodes = (
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___、___2___\n"
            "↓\n"
            "（矩形）计算：BMI = ___3___\n"
            "↓\n"
            "（平行四边形）输出 ___4___\n"
            "↓\n"
            "（圆角矩形）结束"
        )
        blanks = "___1___、___2___、___3___、___4___"
    elif needs_running_lap_flowchart(exercise):
        nodes = (
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（平行四边形）输入 ___2___\n"
            "↓\n"
            "（矩形）处理：___3___\n"
            "↓\n"
            "（平行四边形）输出 ___4___\n"
            "↓\n"
            "（圆角矩形）结束"
        )
        blanks = "___1___、___2___、___3___、___4___"
    else:
        nodes = (
            "（圆角矩形）开始\n"
            "↓\n"
            "（平行四边形）输入 ___1___\n"
            "↓\n"
            "（矩形）处理：___2___\n"
            "↓\n"
            "（平行四边形）输出 ___3___\n"
            "↓\n"
            "（圆角矩形）结束"
        )
        blanks = "___1___、___2___、___3___"
    state["flowchart_expected_blank_count"] = flowchart_blank_count(nodes)
    return (
        "现在进入第二步任务“设计算法”。这一步只设计流程图，不写代码。\n\n"
        "请根据刚才的IPO分析，补全下面流程图节点里的空白。\n\n"
        f"练习任务：{exercise}\n\n"
        f"挖空流程图：\n{nodes}\n\n"
        f"请回答：{blanks}分别应该填什么？"
    )


def mentor_algorithm_design_start_message(state):
    return (
        "你的IPO分析已经完成。接下来由编程导师智能体继续带你进入第二步任务“设计算法”。\n\n"
        + algorithm_flowchart_prompt_message(state)
    )


def peer_debug_encouragement_message():
    return (
        "你已经连续调试了几次，还在认真把问题一点点缩小，这说明你没有被报错吓住。"
        "先稳住节奏，很多程序问题都是这样靠一轮轮观察和验证找出来的。\n\n"
        "接下来继续跟着编程导师智能体看报错、看变量类型和运行结果，我们把问题定位出来。"
    )


def guard_algorithm_design_flowchart_format(state, agent, assistant_message):
    if state.get("learning_step") != "flowchart" or agent != "mentor":
        return assistant_message
    if looks_like_flowchart_diagram(assistant_message):
        expected_count = flowchart_expected_blank_count(state)
        if (
            flowchart_blank_count(assistant_message) < expected_count
            or (
                needs_multi_branch_flowchart(state.get("exercise_prompt") or "")
                and not is_sequential_multi_branch_flowchart(
                    assistant_message,
                    multi_branch_output_count(state.get("exercise_prompt") or ""),
                )
            )
        ):
            return algorithm_flowchart_prompt_message(state)
        return assistant_message
    if looks_like_code_blank_algorithm(assistant_message):
        return algorithm_flowchart_prompt_message(state)
    return assistant_message


def guard_premature_flowchart_completion(state, agent, user_message, assistant_message):
    if state.get("learning_step") != "flowchart" or agent != "mentor":
        return assistant_message
    if not mentor_claims_flowchart_complete(assistant_message):
        return assistant_message
    expected_count = flowchart_expected_blank_count(state)
    if looks_like_numbered_flowchart_answer(user_message, expected_count):
        return assistant_message
    blanks = "\n".join(f"___{index}___：" for index in range(1, expected_count + 1))
    return (
        "我先不判断流程图已经完成，因为你还没有按空白编号逐项填写。\n\n"
        "请你按这个格式回答：\n"
        f"{blanks}\n\n"
        "如果你想写完整流程，也可以写，但需要把每个空白编号对应的答案标出来。"
    )


def programming_prompt_message(state):
    exercise = state.get("exercise_prompt") or "当前练习任务"
    return (
        f"现在进入第三步任务“编写程序/编程”。你的练习任务是：{exercise}\n\n"
        "请你根据刚才完成的IPO分析和流程图，到海龟编辑器中自己写出完整 Python 程序。\n\n"
        "写代码前可以简单检查这几件事：\n"
        "1. 输入：需要从用户那里得到哪些数据？\n"
        "2. 处理：核心公式或判断条件是什么？\n"
        "3. 输出：最后要显示什么结果？\n\n"
        "请直接在海龟编辑器中编写完整代码并运行。运行后把代码和运行结果发给我；如果报错，我再帮你一起调试。"
    )


def guard_programming_stage_overguidance(state, agent, user_message, assistant_message):
    if state.get("learning_step") != "debugging" or agent != "mentor":
        return assistant_message
    if contains_any(user_message or "", ["报错", "错误", "bug", "Traceback", "SyntaxError", "TypeError", "NameError"]):
        return assistant_message
    if looks_like_programming_ready(user_message):
        return programming_prompt_message(state)
    return assistant_message


def guard_reflection_agent_echo(state, agent, assistant_message):
    if agent != "assistant" or (
        state.get("learning_step") != "self_evaluation"
        and not state.get("reflection_current_step")
    ):
        return assistant_message
    text = assistant_message or ""
    lines = []
    skip_until_blank = False
    repeated_markers = [
        "我看到你已经完成“代码优化”",
        "我看到你已经完成\"代码优化\"",
        "我已经收到同伴的反馈",
        "你的程序可以运行了。接下来我们直接进入反思阶段",
        "由编程助教智能体辅助你进行学习评价和反思",
    ]
    for line in text.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in repeated_markers):
            skip_until_blank = True
            continue
        if skip_until_blank:
            if not stripped:
                skip_until_blank = False
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or text


def guard_reflection_task_consistency(state, agent, assistant_message):
    if agent != "assistant" or state.get("learning_step") != "self_evaluation":
        return assistant_message
    if not reply_conflicts_with_current_task(state, assistant_message):
        return assistant_message
    context = assemble_reflection_context(state)
    outcome = build_agent_outcome_evaluation(context, {})
    return format_outcome_evaluation_feedback(context, outcome)


def replace_unavailable_ui_references(message):
    if not message:
        return message
    text = message
    replacements = [
        (r"学习报告已保存[，,。；;]?\s*后续可在教师端学习数据中查看或导出[。！!]*", "学习报告已保存。"),
        (r"学习报告已保存[，,。；;]?\s*后续可在教师端导出的学习数据中查看记录[。！!]*", "学习报告已保存。"),
        (r"学习报告已保存[，,。；;]?\s*(?:可|可以|后续可)?.*?(?:我的反思报告|个人中心|学习中心|教师端学习数据|教师端导出的学习数据).*?(?:查看|导出|记录)?[。！!]*", "学习报告已保存。"),
        (r"你可以?至?个人中心查看历史记录", "学习报告已保存。"),
        (r"你可以?到学习中心查看历史记录", "学习报告已保存。"),
        (r"可至个人中心查看历史记录", "学习报告已保存。"),
        (r"可到学习中心查看历史记录", "学习报告已保存。"),
        (r"后续可在教师端学习数据中查看或导出", "学习报告已保存。"),
        (r"后续可在教师端导出的学习数据中查看记录", "学习报告已保存。"),
        (r"可在学生端右侧的“我的反思报告”中查看", ""),
        (r"学生端右侧的“我的反思报告”", "学习报告"),
        (r"我的反思报告", "学习报告"),
        (r"教师端学习数据", "学习报告"),
        (r"教师端导出的学习数据", "学习报告"),
        (r"个人中心", "学习报告"),
        (r"学习中心", "学习报告"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text

def format_quiz_layout(message):
    if not message:
        return message
    parts = re.split(r"(```.*?```)", message, flags=re.S)
    formatted_parts = []
    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            formatted_parts.append(part)
            continue
        text = part
        text = re.sub(r"(?<!^)(?<!\n)\s*(题目\s*\d+(?:\s*[（(]|[.．、])?)", r"\n\n\1", text)
        text = re.sub(r"(?<!^)(?<!\n)\s*(\d+\s*[.．、]\s*)", r"\n\n\1", text)
        text = re.sub(r"(题目\s*\d+\s*[（(][^）)]{1,10}[）)])\s*(?=\S)", r"\1\n", text)
        text = re.sub(r"(?<!\n)\s*([A-D][.．、)）])\s*", r"\n\1 ", text)
        text = re.sub(r"(?<!\n)(（回答[“\"']?对[”\"']?或[“\"']?错[”\"']?）)", r"\n\1", text)
        text = re.sub(r"\n(题目\s*\d+\s*[（(][^）)]{1,10}[）)])\n+", r"\n\n\1\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        formatted_parts.append(text)
    formatted = "".join(formatted_parts).strip()
    formatted = re.sub(r"(?m)^\s*题目\s*(\d+)\s*[（(]\s*(?:单选|判断)\s*[）)]\s*", r"\1. ", formatted)
    formatted = re.sub(r"(?m)^(\d+\.\s*[^\n]+)\n(?=[A-D][.．、)）])", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^(\d+\.\s*[^\n]+)\n(?=（回答)", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^([A-D][.．、)）]\s*[^\n]+)\n(?=[A-D][.．、)）])", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^([A-D][.．、)）]\s*[^\n]+)\n(?=\d+\.\s*)", r"\1\n\n", formatted)
    formatted = re.sub(r"\n{4,}", "\n\n", formatted)
    return formatted.strip()

def should_format_quiz(agent, step):
    return agent == "assistant" and step in {"exercise_intake", "quiz_review"}


def split_quiz_blocks(message):
    formatted = format_quiz_layout(message)
    blocks = []
    current = []
    for line in formatted.splitlines():
        if re.match(r"^\s*(?:题目\s*)?\d+\s*[.．、]\s+", line):
            if current and re.match(r"^\s*(?:题目\s*)?\d+\s*[.．、]\s+", current[0]):
                blocks.append("\n".join(current).strip())
            current = [line]
        else:
            if current:
                current.append(line)
    if current:
        block = "\n".join(current).strip()
        if re.search(r"(?m)^\s*(?:题目\s*)?\d+\s*[.．、]\s+", block):
            blocks.append(block)
    return blocks


def quiz_layout_issues(message):
    issues = []
    for block in split_quiz_blocks(message):
        title = block.splitlines()[0].strip()
        if "```" in block:
            issues.append({"question": title, "codeBlock": True})
            continue
        has_alternative_word = bool(re.search(r"还是|或者|或|/|\bOR\b", block, re.I))
        has_english_true_false = bool(
            re.search(r"(?<![A-Za-z])TRUE(?![A-Za-z])", block, re.I)
            and re.search(r"(?<![A-Za-z])FALSE(?![A-Za-z])", block, re.I)
        )
        has_chinese_true_false = "真" in block and "假" in block
        asks_for_true_false = has_alternative_word and (has_english_true_false or has_chinese_true_false)
        requires_right_wrong = bool(re.search(r"回答[^\n]{0,12}对[^\n]{0,8}(?:或|/)[^\n]{0,8}错", block))
        if asks_for_true_false and requires_right_wrong:
            issues.append({"question": title, "mixedJudgementFormats": True})
            continue
        if "判断" in title or "回答" in block:
            continue
        options = set(re.findall(r"(?m)^\s*([A-D])[\.\．、\)）]", block))
        missing = [option for option in "ABCD" if option not in options]
        if missing:
            issues.append({"question": title, "missingOptions": missing})
    return issues


def quiz_layout_is_complete(message):
    blocks = split_quiz_blocks(message)
    return bool(blocks) and not quiz_layout_issues(message) and not quiz_content_issues(message)


INDEPENDENT_PROGRAMMING_QUESTION_PATTERNS = [
    r"(?:请|自己|独立).{0,16}(?:编写|完成|设计|实现).{0,16}(?:代码|程序|功能|任务)",
    r"根据.{0,20}(?:需求|要求|题意).{0,16}(?:编写|完成|设计|实现).{0,16}(?:代码|程序)",
    r"(?:编写|完成|设计|实现).{0,12}(?:下面|以下|一段)?.{0,12}(?:代码|程序)",
]
CODE_OPTION_STEM_MARKERS = ["哪段代码", "代码片段", "正确代码", "代码写法", "程序语句"]


def is_readable_python_code_option(option):
    """判断“代码选项”是否至少是可阅读的 Python 代码/片段，而非自然语言步骤。"""
    text = (option or "").strip()
    if not text:
        return False
    if re.search(r"\b(?:if|elif|else)\b", text):
        # 条件分支必须有合法的 Python 形式；“输出A，否则输出B”不属于代码。
        return bool(
            re.search(r"\b(?:if|elif)\b.+:\s*(?:print\(|[A-Za-z_]\w*\s*=|pass\b)", text)
            or re.search(r"\belse\s*:\s*(?:print\(|[A-Za-z_]\w*\s*=|pass\b)", text)
        )
    return bool(
        re.search(r"\b(?:print|input|int|float|str)\s*\(", text)
        or re.search(r"\b[A-Za-z_]\w*\s*=", text)
        or re.fullmatch(r"[A-Za-z_]\w*(?:\s*[+*/-]\s*(?:[A-Za-z_]\w*|\d+(?:\.\d+)?))+", text)
    )


def quiz_content_issues(message):
    """校验前测定位，阻止自主编程题和用自然语言冒充代码的选项。"""
    issues = []
    for block in split_quiz_blocks(message):
        title = block.splitlines()[0].strip()
        normalized = re.sub(r"\s+", "", block)
        if any(re.search(pattern, normalized) for pattern in INDEPENDENT_PROGRAMMING_QUESTION_PATTERNS):
            issues.append({"question": title, "requiresIndependentProgramming": True})
            continue
        if not contains_any(title, CODE_OPTION_STEM_MARKERS):
            continue
        options = re.findall(r"(?m)^\s*[A-D][\.．、\)）]\s*(.+)$", block)
        invalid_options = [option for option in options if not is_readable_python_code_option(option)]
        if invalid_options:
            issues.append({"question": title, "nonCodeOption": invalid_options})
    return issues


INPUT_OUTPUT_CONTEXT_KEYWORDS = [
    "输入输出",
    "输入和输出",
    "input",
    "print",
    "输出",
    "输入",
    "逗号",
    "字符串",
    "提示语",
    "显示",
]

INPUT_OUTPUT_QUIZ_MARKERS = [
    "input",
    "print",
    "输入",
    "输出",
    "逗号",
    "字符串",
    "键盘",
    "屏幕",
    "显示",
]


def quiz_context_text(state):
    return f"{state.get('current_topic') or ''} {state.get('exercise_prompt') or ''}"


def is_input_output_quiz_context(state):
    return contains_any(quiz_context_text(state), INPUT_OUTPUT_CONTEXT_KEYWORDS)


def quiz_matches_current_context(state, message):
    if not is_input_output_quiz_context(state):
        return True
    io_blocks = [
        block
        for block in split_quiz_blocks(message)
        if contains_any(block, INPUT_OUTPUT_QUIZ_MARKERS)
    ]
    return len(io_blocks) >= 3


def looks_like_llm_error(message):
    return contains_any(message or "", LLM_ERROR_MARKERS)


def quiz_rng_for_state(state):
    seed_text = "|".join(
        [
            state.get("student_session_id") or "",
            state.get("current_topic") or "",
            state.get("exercise_prompt") or "",
            state.get("quiz_variant_seed") or "",
        ]
    )
    return random.Random(seed_text or None)


def shuffle_options(options, rng):
    shuffled = list(options)
    rng.shuffle(shuffled)
    return shuffled


def render_single_choice(index, stem, options, rng):
    lines = [f"{index}. {stem}（）"]
    for label, option in zip("ABCD", shuffle_options(options, rng)):
        lines.extend(["", f"{label}. {option}"])
    return "\n".join(lines)


def render_true_false(index, statement):
    return f"{index}. {statement}\n\n（回答“对”或“错”）"


def quiz_item_pools(state):
    context = quiz_context_text(state)
    topic_items = []
    if is_input_output_quiz_context(state):
        topic_items.extend(
            [
                ("choice", "在 Python 中，print() 最主要的作用是", ["在屏幕上输出内容", "接收键盘输入", "自动判断条件", "删除变量"]),
                ("choice", "在 Python 中，input() 最主要的作用是", ["接收用户从键盘输入的内容", "把内容显示到屏幕上", "让程序自动结束", "改变代码执行顺序"]),
                ("tf", "print(2 + 3) 输出的是数字计算结果 5，而不是字符串“2+3”。"),
                ("choice", "在 print('圆周率取', 变量) 中，英文逗号的作用是", ["分隔要输出的多个内容", "接收用户输入", "表示加法运算", "让程序报错"]),
                ("tf", "input() 得到的内容通常先被当作字符串保存。"),
                ("choice", "如果要把用户输入的年龄变成整数，常用写法是", ["int(input())", "print(input())", "str(print())", "input(int)"]),
            ]
        )
    if contains_any(context, ["BMI", "bmi", "身高", "体重"]):
        topic_items.extend(
            [
                ("choice", "在计算 BMI 的程序中，input() 适合用来", ["接收身高、体重等输入", "自动计算 BMI", "结束程序", "删除变量"]),
                ("choice", "如果身高变量是 height，体重变量是 weight，计算 BMI 的表达式应是", ["weight / (height * height)", "height / (weight * weight)", "height + weight", "weight * height"]),
                ("tf", "float(input()) 可以把用户输入的内容转换成小数。"),
                ("choice", "BMI 程序中使用 float() 的原因通常是", ["身高、体重可能是小数", "让程序重复执行", "自动输出中文", "删除多余空格"]),
            ]
        )
    if contains_any(context, ["判断", "如果", "条件", "分支", "是否", "发烧", "及格", "等级"]):
        topic_items.extend(
            [
                ("choice", "Python 中用于条件判断的关键字是", ["if", "print", "input", "float"]),
                ("tf", "if 后面的条件成立时，才会执行它下面缩进的语句。"),
                ("choice", "判断温度是否发烧时，最需要先明确的是", ["判断条件和临界值", "变量颜色", "电脑型号", "代码文件名"]),
                ("choice", "if 语句行末通常需要写", ["英文冒号", "中文句号", "等号", "逗号"]),
            ]
        )
    if contains_any(context, ["面积", "周长", "半径", "圆", "月饼", "公式", "计算"]):
        topic_items.extend(
            [
                ("choice", "编写计算面积或周长的程序时，最关键的是先明确", ["输入数据、计算公式和输出结果", "窗口背景颜色", "文件保存位置", "电脑品牌"]),
                ("tf", "如果用户输入半径，程序通常需要先把输入内容转换成数字再计算。"),
                ("choice", "表达式 2 * 3.14 * r 更可能用来计算圆的", ["周长", "半径", "输入文字", "变量名"]),
                ("choice", "表达式 r * r * 3.14 更可能用来计算圆的", ["面积", "周长", "直径文字", "输出格式"]),
            ]
        )
    common_items = [
        ("choice", "程序顺序结构最主要的特点是", ["按照代码书写顺序，从上到下依次执行", "根据条件选择性运行代码", "重复执行一段代码", "代码执行顺序自动跳跃"]),
        ("choice", "在 Python 中，变量的主要作用是", ["保存数据", "改变电脑屏幕颜色", "自动生成图片", "删除程序"]),
        ("tf", "input() 通常用来接收用户输入。"),
        ("choice", "写程序前先做 IPO 分析，其中 P 通常表示", ["处理", "输入", "输出", "程序图标"]),
        ("tf", "变量名应该尽量表达数据含义，这样更容易检查程序。"),
    ]
    return topic_items, common_items


def fallback_quiz_intro(state):
    if is_input_output_quiz_context(state):
        return "我先给你一组围绕本节“输入输出”内容的基础知识前测。请按顺序作答，例如：1A 2B 3错 4C。"
    return "我先根据本节课学习内容生成一组基础知识前测。请按顺序作答，例如：1A 2B 3对 4C。"


def fallback_quiz_message(state):
    rng = quiz_rng_for_state(state)
    topic_items, common_items = quiz_item_pools(state)
    rng.shuffle(topic_items)
    rng.shuffle(common_items)
    topic_count = min(len(topic_items), 4)
    selected = topic_items[:topic_count]
    selected.extend(common_items[: max(0, 4 - len(selected))])
    rng.shuffle(selected)
    lines = [fallback_quiz_intro(state)]
    for index, item in enumerate(selected, start=1):
        if item[0] == "choice":
            lines.extend(["", render_single_choice(index, item[1], item[2], rng)])
        else:
            lines.extend(["", render_true_false(index, item[1])])
    return "\n".join(lines)


def quiz_regeneration_prompt(state, original_message):
    exercise = state.get("exercise_prompt") or "当前编程任务"
    topic = state.get("current_topic") or "当前学习主题"
    return (
        "刚才生成的基础知识测试题格式不完整，不能直接给学生作答。"
        f"请重新生成一组3-5道基础知识测试题，只输出题目，不要解释原因。当前学习主题是：{topic}；当前练习题干是：{exercise}。"
        "题目必须紧扣当前学习主题和练习题干，不要退回到通用的顺序结构题。"
        "如果主题或题干涉及输入输出、input()、print()、逗号分隔、字符串或输出显示，至少三道题必须直接考查输入输出。"
        "这是前测知识检测，不是自主练习：只能考语法、规范、概念、语句作用和简单代码阅读；不得要求学生编写、补全、设计或独立实现代码/程序。"
        "如果题干问“哪段代码”或“哪种代码写法”，A、B、C、D必须全部是可阅读的 Python 代码或代码片段，不能用自然语言步骤或伪代码充当选项。"
        "必须严格遵守：每道题用“1. 题干（）”这种数字编号开头；"
        "如果是单选题，必须有且只有A、B、C、D四个选项，并且每个选项独立成行；"
        "如果是判断题，题干下一行写“（回答“对”或“错”）”。"
        "判断题必须写成完整陈述句，并统一采用“对/错”作答；不要在题干中再问True还是False、真还是假。"
        "题目和每个选项之间都空一行，像教材练习题一样清楚。"
        "不要把题干和选项挤在同一行，不要缺少任何单选题选项。\n\n"
        f"原始不完整输出如下：\n{original_message}"
    )


def ensure_complete_quiz_message(state, agent, step, message):
    formatted = format_quiz_layout(message)
    if not should_format_quiz(agent, step):
        return formatted, {"quiz_layout_checked": False}
    if looks_like_llm_error(formatted):
        return formatted, {
            "quiz_layout_checked": True,
            "quiz_layout_complete": False,
            "quiz_llm_error": True,
        }
    issues = quiz_layout_issues(formatted) + quiz_content_issues(formatted)
    topic_mismatch = not issues and split_quiz_blocks(formatted) and not quiz_matches_current_context(state, formatted)
    if not issues and split_quiz_blocks(formatted) and not topic_mismatch:
        return formatted, {"quiz_layout_checked": True, "quiz_layout_complete": True}
    if topic_mismatch:
        issues = [{"topicMismatch": True}]
    retry = call_llm(state, agent, quiz_regeneration_prompt(state, formatted))
    retry = format_quiz_layout(clean_reply(retry))
    if looks_like_llm_error(retry):
        return retry, {
            "quiz_layout_checked": True,
            "quiz_layout_complete": False,
            "quiz_regenerated": True,
            "quiz_llm_error": True,
            "quiz_layout_issues": issues,
            "quiz_topic_mismatch": topic_mismatch,
        }
    retry_issues = quiz_layout_issues(retry) + quiz_content_issues(retry)
    retry_topic_mismatch = bool(split_quiz_blocks(retry)) and not quiz_matches_current_context(state, retry)
    if not retry_issues and split_quiz_blocks(retry) and not retry_topic_mismatch:
        return retry, {
            "quiz_layout_checked": True,
            "quiz_layout_complete": True,
            "quiz_regenerated": True,
            "quiz_layout_issues": issues,
            "quiz_topic_mismatch": topic_mismatch,
        }
    fallback = format_quiz_layout(fallback_quiz_message(state))
    return fallback, {
        "quiz_layout_checked": True,
        "quiz_layout_complete": True,
        "quiz_regenerated": True,
        "quiz_fallback_generated": True,
        "quiz_topic_mismatch": topic_mismatch or retry_topic_mismatch,
        "quiz_layout_issues": retry_issues or issues,
    }


def normalize_answer_token(value):
    text = re.sub(r"[\s\"'“”‘’。.,，、:：;；()（）]", "", str(value or "")).upper()
    if not text:
        return ""
    if text in {"TRUE", "T", "对", "正确", "是"}:
        return "对"
    if text in {"FALSE", "F", "错", "错误", "否"}:
        return "错"
    if text[0] in "ABCD":
        return text[0]
    if "TRUE" in text or "对" in text or "正确" in text:
        return "对"
    if "FALSE" in text or "错" in text or "错误" in text:
        return "错"
    return text


def parse_student_quiz_answers(message):
    text = message or ""
    answer_token = r"TRUE|FALSE|[A-D]|对|错|正确|错误|是|否"
    numbered = re.findall(
        rf"(?:^|\s)(?:第)?([1-9]\d*)\s*(?:题)?\s*[:：.、)]?\s*({answer_token})(?![A-Za-z])",
        text,
        flags=re.I,
    )
    if numbered:
        return {int(index): normalize_answer_token(answer) for index, answer in numbered}
    answers = [
        normalize_answer_token(answer)
        for answer in re.findall(r"(?<![A-Za-z])(?:TRUE|FALSE|[A-D])(?![A-Za-z])|对|错", text, flags=re.I)
    ]
    return {index + 1: answer for index, answer in enumerate(answers) if answer}


def split_quiz_grading_segments(message):
    pattern = re.compile(r"第\s*([1-9]\d*)\s*题\s*[:：]?(.*?)(?=第\s*[1-9]\d*\s*题|正确率|前测通过|$)", re.S)
    return [(int(index), body.strip()) for index, body in pattern.findall(message or "")]


def answer_key_from_segment(segment):
    match = re.search(
        r"正确答案\s*(?:是|为|[:：])?\s*(TRUE|FALSE|[A-D]|对|错|正确|错误)(?![A-Za-z])",
        segment or "",
        flags=re.I,
    )
    if match:
        return normalize_answer_token(match.group(1))
    return ""


def segment_marks_correct(segment):
    without_key = re.sub(
        r"正确答案\s*(?:是|为|[:：])?\s*(?:TRUE|FALSE|[A-D]|对|错|正确|错误)(?![A-Za-z])",
        "",
        segment or "",
        flags=re.I,
    )
    if re.search(r"不正确|答错|错了|错误", without_key):
        return False
    return bool(re.search(r"(^|[：:，,。；;\s])正确([。；;，,\s]|$)", without_key))


def replace_quiz_score(message, percent, passed):
    text = message or ""
    pass_text = "是" if passed else "否"
    if re.search(r"正确率\s*[:：]\s*\d{1,3}\s*%", text):
        text = re.sub(r"正确率\s*[:：]\s*\d{1,3}\s*%", f"正确率：{percent}%", text)
    else:
        text += f"\n\n正确率：{percent}%"
    if re.search(r"前测通过\s*[:：]\s*[是否]", text):
        text = re.sub(r"前测通过\s*[:：]\s*[是否]", f"前测通过：{pass_text}", text)
    else:
        text += f"\n前测通过：{pass_text}"
    return text


def normalize_quiz_grading(user_message, assistant_message):
    student_answers = parse_student_quiz_answers(user_message)
    segments = split_quiz_grading_segments(assistant_message)
    if not student_answers or not segments:
        return assistant_message, {"quiz_grading_checked": False}

    results = {}
    compared_with_answer_key = []
    for index, segment in segments:
        student_answer = student_answers.get(index)
        correct_answer = answer_key_from_segment(segment)
        if correct_answer and student_answer:
            results[index] = student_answer == correct_answer
            compared_with_answer_key.append(index)
        elif segment_marks_correct(segment):
            results[index] = True

    total = max(len(student_answers), max(results.keys(), default=0))
    if not total or len(results) < total:
        return assistant_message, {
            "quiz_grading_checked": True,
            "quiz_grading_complete": False,
            "quiz_grading_results": results,
        }

    correct_count = sum(1 for value in results.values() if value)
    percent = round(correct_count * 100 / total)
    passed = correct_count == total
    corrected = replace_quiz_score(assistant_message, percent, passed)
    metadata = {
        "quiz_grading_checked": True,
        "quiz_grading_complete": True,
        "quiz_grading_correct_count": correct_count,
        "quiz_grading_total": total,
        "quiz_grading_percent": percent,
        "quiz_grading_compared_with_answer_key": compared_with_answer_key,
    }
    if corrected != assistant_message:
        metadata["quiz_grading_corrected"] = True
    if compared_with_answer_key and passed and "正确率：100%" not in assistant_message:
        corrected += (
            "\n\n系统校验：你的作答与助教回复中给出的正确答案一致，"
            "因此本次前测按100%通过处理。"
        )
        metadata["quiz_grading_corrected"] = True
    return corrected, metadata


def parse_time_plan(message):
    text = message.strip()
    planned = {}
    for canonical, aliases in TASK_PATTERNS:
        alias_group = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
        patterns = [
            rf"({alias_group})\s*[：:、，,\s]*([1-9]\d*)\s*分钟",
            rf"([1-9]\d*)\s*分钟\s*(?:的)?\s*({alias_group})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            values = [group for group in match.groups() if group and group.isdigit()]
            if values:
                planned[canonical] = int(values[0])
                break
    return [{"name": name, "minutes": planned[name]} for name, _ in TASK_PATTERNS if name in planned]


def plan_total_minutes(plan):
    return sum(int(task.get("minutes", 0)) for task in (plan or []))


def merge_remaining_time_plan(existing_plan, new_remaining_plan, remaining_names):
    by_name = {task["name"]: int(task.get("minutes", 0)) for task in (new_remaining_plan or [])}
    remaining_names = list(remaining_names or by_name.keys())
    merged = []
    for canonical, _ in TASK_PATTERNS:
        existing = next((task for task in (existing_plan or []) if task.get("name") == canonical), None)
        if canonical in remaining_names:
            merged.append({"name": canonical, "minutes": by_name.get(canonical, 0)})
        elif existing:
            merged.append({"name": canonical, "minutes": int(existing.get("minutes", 0))})
    return merged


def validate_overtime_replan(state, planned_tasks):
    expected_total = state.get("overtime_remaining_minutes")
    remaining_names = state.get("overtime_remaining_task_names") or [task["name"] for task in planned_tasks]
    provided_names = {task["name"] for task in planned_tasks}
    missing_names = [name for name in remaining_names if name not in provided_names]
    total = plan_total_minutes(planned_tasks)
    if expected_total is None:
        return {"ok": True, "total": total, "expectedTotal": total, "missingNames": []}
    return {
        "ok": total == int(expected_total) and not missing_names,
        "total": total,
        "expectedTotal": int(expected_total),
        "missingNames": missing_names,
    }


def is_complete_initial_time_plan(plan):
    if len(plan) != len(TASK_NAMES):
        return False
    names = {task["name"] for task in plan}
    total_minutes = plan_total_minutes(plan)
    return names == set(TASK_NAMES) and total_minutes == 20

def looks_like_time_plan(message):
    parsed_tasks = parse_time_plan(message)
    if len(parsed_tasks) >= 2:
        return True
    task_words = ["分析", "算法", "编程", "优化", "分钟"]
    if not contains_any(message, task_words):
        return False
    if "20" in message or "总计" in message or "一共" in message:
        return True
    minutes = [int(value) for value in re.findall(r"(\d+)\s*分钟", message)]
    return len(minutes) >= 4 and sum(minutes[:4]) == 20

def looks_like_replan(message):
    return contains_any(message, REPLAN_WORDS) and bool(parse_time_plan(message))

def looks_like_debug_failure(message):
    text = message or ""
    compact = re.sub(r"\s+", "", text)
    hard_failure_words = [
        word for word in DEBUG_FAILURE_WORDS
        if word not in {"报错", "错误", "bug", "Bug", "BUG"}
    ]
    if contains_any(text, hard_failure_words):
        return True
    if contains_any(text, DEBUG_SUCCESS_WORDS):
        return False
    if contains_any(text, ["没有报错", "无报错"]):
        return False
    if contains_any(text, ["报错", "错误", "bug", "Bug", "BUG"]):
        return True
    return bool(
        re.search(
            r"(?:无法|不会|不能|没法|仍然不能|还是不能|还不能)(?:正常|成功)?(?:运行|执行|跑通)",
            compact,
        )
    )

def looks_like_debug_success(message):
    if looks_like_debug_failure(message):
        return False
    return contains_any(message or "", DEBUG_SUCCESS_WORDS)

def looks_like_code_help(message):
    text = message or ""
    lowered = text.lower()
    if looks_like_debug_failure(text) or contains_any(text, CODE_HELP_WORDS):
        return True
    if "```" in lowered or "traceback" in lowered or "syntaxerror" in lowered:
        return True
    if re.search(r"\b(?:print|input|float|int|str|if|elif|else|for|while|def)\s*\(", lowered):
        return True
    if re.search(r"(?m)^\s*[a-zA-Z_]\w*\s*=", text):
        return True
    return False


def looks_like_debug_attempt(message):
    text = message or ""
    lowered = text.lower()
    if looks_like_debug_success(text) or looks_like_debug_failure(text) or looks_like_code_help(text):
        return True
    if contains_any(text, ["运行结果", "测试结果", "输出结果", "执行结果", "修改后", "再运行", "重新运行"]):
        return True
    if re.search(r"\b(?:print|input|float|int|str|if|elif|else|for|while|def)\b", lowered):
        return True
    if re.search(r"(?m)^\s*[a-zA-Z_]\w*\s*=", text):
        return True
    return False


def assistant_reflection_start_message():
    return (
        "程序已经完成啦，接下来先不要急着结束学习。我们先看看这次编程任务完成得怎么样，"
        "再总结一下这次学习过程。\n\n"
        "第一步是学习成果评价。我们先按照任务要求检查程序，请你先完成自己的检查和自评，"
        "然后我再结合代码、运行结果和测试记录给出证据反馈。"
    )


def peer_debug_success_message():
    return (
        "太好了，你的代码已经成功运行了！这说明你完成了从分析、设计算法到编写调试的关键闭环，"
        "也能用运行结果验证自己的程序逻辑。\n\n"
        "我已经帮你暂停倒计时，并把任务完成率更新到100%。接下来由编程助教智能体带你进入学习成果评价，"
        "再继续完成学习反思和改进优化。"
    )

def assistant_confirms_quiz_pass(message):
    text = re.sub(r"\s+", "", message or "").replace("％", "%")
    if not text:
        return False
    negative_patterns = [
        r"前测通过[:：]?否",
        r"正确率[:：]?(?!100%)\d{1,2}%",
        r"未(?:达到|达)100%",
        r"没有(?:达到)?100%",
        r"还(?:没|未)有?全[部都]?答对",
        r"不能进入(?:任务拆解|时间分配|下一阶段)",
    ]
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return False
    pass_patterns = [
        r"前测通过[:：]?是",
        r"正确率[:：]?100%",
        r"得分[:：]?100%",
        r"全部答对",
        r"全都答对",
        r"可以进入(?:任务拆解|时间分配|下一阶段)",
    ]
    return any(re.search(pattern, text) for pattern in pass_patterns)

def mentor_quiz_explanation_trigger(state, user_message, assistant_message):
    exercise = state.get("exercise_prompt") or "当前编程练习题干"
    return (
        "学生完成基础知识前测后存在错误。助教智能体已经负责批改并公布正确答案，"
        "现在请你作为编程导师智能体进行知识讲解。\n\n"
        f"练习任务题干：{exercise}\n"
        f"学生前测作答：{user_message}\n"
        f"助教批改与正确答案：{assistant_message}\n\n"
        "请只讲解学生出错题目背后的基础知识点，不要重新出题，不要进入任务拆解或时间分配。"
        "讲解要适合初中生：优先用生活化类比；如果涉及变量、输入输出、表达式或条件判断，"
        "可以给一个短小的Python代码案例。最后询问学生是否掌握，并提醒学生回复“我已掌握”后，助教会再出检验题。"
    )


def normalize_quiz_pass_transition(message):
    if not assistant_confirms_quiz_pass(message):
        return message
    text = message or ""
    mentor_handoff_patterns = [
        r"(?:接下来|下一步|之后)[^。\n！？]*(?:编程导师智能体|导师智能体|导师)[^。\n！？]*(?:讲解|解释|知识点)[^。\n！？]*[。\n！？]?",
        r"(?:接下来|下一步|之后)[^。\n！？]*(?:讲解|解释)[^。\n！？]*(?:编程导师智能体|导师智能体|导师)[^。\n！？]*[。\n！？]?",
        r"如果后续在计划制定或作品引导方面有需要，我随时在[。\n！？]?",
    ]
    for pattern in mentor_handoff_patterns:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not contains_any(text, ["任务拆解", "时间分配", "分析问题", "设计算法", "编写程序", "代码优化"]):
        text += (
            "\n\n接下来进入任务拆解与时间分配。请你把本次编程练习拆解为："
            "分析问题、设计算法、编写程序、代码优化四项，并为每项分配时间，总计20分钟。"
        )
    return text


def prepare_step_for_prompt(state, user_message):
    step = state.get("learning_step", "topic_intro")
    text = user_message.strip()
    if step == "exercise_intake" and text:
        state["exercise_prompt"] = text[:500]
        state["quiz_variant_seed"] = datetime.now().isoformat(timespec="microseconds")
        state["ipo_coverage"] = {"input": False, "process": False, "output": False}
        state["reflection_current_step"] = ""
        state["debug_success_peer_acknowledged"] = False
        state["debug_peer_encouraged"] = False
        state["debug_count"] = 0
    if step == "quiz_explain_wait" and contains_any(text, ["掌握", "明白", "懂了", "会了"]):
        state["learning_phase"] = "掌握检验"
        state["learning_step"] = "quiz_review"

def update_learning_step(state, agent, user_message, assistant_message=""):
    step = state.get("learning_step", "topic_intro")
    phase = state.get("learning_phase", "主题作品体验")
    text = user_message.strip()
    metadata = {}

    if agent == "assistant" and step == "plan_allocation" and looks_like_time_plan(text):
        planned_tasks = parse_time_plan(text)
        if is_complete_initial_time_plan(planned_tasks):
            phase = "IPO问题分析"
            step = "ipo_analysis"
            state["plan_synced"] = True
            state["time_plan"] = planned_tasks
            metadata["start_timer"] = True
            metadata["plan_synced_to_peer"] = True
            metadata["time_plan"] = planned_tasks
            metadata["total_minutes"] = sum(task["minutes"] for task in planned_tasks)
        else:
            phase = "任务拆解与时间分配"
            step = "plan_allocation"
            metadata["time_plan_incomplete"] = True
            metadata["parsed_time_plan"] = planned_tasks
            metadata["total_minutes"] = sum(task["minutes"] for task in planned_tasks)
    elif agent == "peer" and (state.get("overtime_replan_pending") or looks_like_replan(text)) and looks_like_time_plan(text):
        planned_tasks = parse_time_plan(text)
        validation = validate_overtime_replan(state, planned_tasks)
        if validation["ok"]:
            remaining_names = state.get("overtime_remaining_task_names") or [task["name"] for task in planned_tasks]
            merged_plan = merge_remaining_time_plan(state.get("time_plan"), planned_tasks, remaining_names)
            if merged_plan:
                state["time_plan"] = merged_plan
            state["overtime_replan_pending"] = False
            metadata["reset_timer"] = True
            metadata["start_timer"] = True
            metadata["time_plan"] = merged_plan or planned_tasks
            metadata["total_minutes"] = validation["expectedTotal"]
            metadata["remaining_replan"] = True
            metadata["replan_current_index"] = int(state.get("overtime_current_index", 0))
            metadata["replan_completed_tasks"] = int(state.get("overtime_completed_tasks", metadata["replan_current_index"]))
        else:
            state["overtime_replan_pending"] = True
            metadata["replan_invalid"] = True
            metadata["replan_validation"] = validation
            metadata["parsed_time_plan"] = planned_tasks
    elif (
        agent == "peer"
        and step == "debugging"
        and looks_like_debug_success(text)
        and not state.get("debug_success_peer_acknowledged")
    ):
        phase = "学习成果评价"
        step = "self_evaluation"
        metadata["complete_timer"] = True
        metadata["pause_timer"] = True
        metadata["progress"] = 100
        metadata["peer_success_acknowledged"] = True
        state["debug_success_peer_acknowledged"] = True
        metadata["reflection_available"] = True
        metadata["assistant_started_reflection"] = True
    elif step == "topic_intro" and agent == "assistant":
        state["current_topic"] = text[:80]
        phase = "主题作品体验"
        step = "experience_feedback"
    elif step == "experience_feedback" and contains_any(text, ["我已完成体验", "完成体验", "已体验", "体验完成"]):
        phase = "生活迁移思考"
        step = "life_connection"
    elif step == "life_connection" and agent == "assistant":
        phase = "练习题干输入"
        step = "exercise_intake"
    elif step == "exercise_intake" and agent == "assistant":
        state["exercise_prompt"] = text[:500]
        phase = "前测"
        step = "quiz"
    elif step == "quiz" and agent == "assistant":
        if assistant_confirms_quiz_pass(assistant_message):
            phase = "任务拆解与时间分配"
            step = "plan_allocation"
            metadata["quiz_passed"] = True
        else:
            phase = "前测讲解"
            step = "quiz_explain_wait"
            metadata["quiz_passed"] = False
            metadata["quiz_needs_mentor_explanation"] = True
    elif step == "quiz_review" and agent == "assistant":
        phase = "掌握检验"
        step = "quiz"
    elif step == "quiz_explain_wait" and agent in {"assistant", "mentor"}:
        phase = "前测讲解"
        step = "quiz_explain_wait"
    elif (
        step == "ipo_analysis"
        and agent == "mentor"
        and ipo_analysis_is_acceptable(state, assistant_message)
    ):
        phase = "流程图完善"
        step = "flowchart"
    elif step == "flowchart" and looks_like_numbered_flowchart_answer(text) and mentor_claims_flowchart_complete(assistant_message):
        phase = "代码编写与调试"
        step = "debugging"
    elif looks_like_debug_failure(text) or contains_any(text, ["报错", "错误", "bug", "调试", "Traceback", "SyntaxError", "TypeError", "NameError"]):
        phase = "代码编写与调试"
        step = "debugging"
    elif contains_any(text, REFLECTION_WORDS):
        phase = "学习成果评价"
        step = "self_evaluation"
        metadata["reflection_available"] = True

    state["learning_phase"] = phase
    state["learning_step"] = step
    metadata["learning_step"] = step
    return phase, metadata

def decorate_message(state, agent, message, user_message):
    current_step = state.get("learning_step", "topic_intro")
    current_phase = state.get("learning_phase", "准备")
    phase = current_phase
    ipo_status = None
    if current_step == "ipo_analysis" and agent == "mentor":
        ipo_status, message = extract_ipo_status_marker(message)
        if ipo_status:
            update_ipo_coverage(state, ipo_status)
    message = clean_reply(message)
    if current_step == "debugging" and looks_like_debug_success(user_message):
        agent = "peer"
        message = peer_debug_success_message()
    message = guard_algorithm_design_flowchart_format(state, agent, message)
    message = guard_premature_flowchart_completion(state, agent, user_message, message)
    message = guard_programming_stage_overguidance(state, agent, user_message, message)
    message = guard_reflection_agent_echo(state, agent, message)
    message = guard_reflection_task_consistency(state, agent, message)
    quiz_metadata = {}
    if should_format_quiz(agent, current_step):
        message, quiz_metadata = ensure_complete_quiz_message(state, agent, current_step, message)
    if agent == "assistant" and current_step == "quiz":
        message, grading_metadata = normalize_quiz_grading(user_message, message)
        quiz_metadata.update(grading_metadata)
    next_phase, metadata = update_learning_step(state, agent, user_message, message)
    if current_step == "quiz" and metadata.get("quiz_passed"):
        message = normalize_quiz_pass_transition(message)
    if metadata.get("learning_step") != current_step:
        metadata["learning_step_changed"] = True
        metadata["previous_learning_step"] = current_step
    if agent == "mentor" and current_step == "ipo_analysis" and metadata.get("learning_step") == "flowchart":
        message = mentor_algorithm_design_start_message(state)
        metadata["mentor_started_algorithm_design"] = True
    metadata.update(quiz_metadata)
    if quiz_metadata.get("quiz_layout_complete") is False:
        phase = current_phase
        state["learning_phase"] = current_phase
        state["learning_step"] = current_step
        metadata["learning_step"] = current_step
    else:
        phase = next_phase
    should_count_debug_attempt = current_step == "debugging" and (
        (agent == "mentor" and looks_like_debug_attempt(user_message))
        or (agent == "peer" and looks_like_debug_success(user_message))
    )
    if should_count_debug_attempt:
        state["debug_count"] = int(state.get("debug_count", 0)) + 1
        metadata["debug_count"] = state["debug_count"]
        if state["debug_count"] >= 2 and not state.get("debug_peer_encouraged"):
            metadata["before_messages"] = (metadata.get("before_messages") or []) + [
                {
                    "agent": "peer",
                    "message": peer_debug_encouragement_message(),
                    "phase": "代码编写与调试",
                    "trigger": "学生代码调试次数大于等于2",
                }
            ]
            metadata["peer_encouraged_before_debug"] = True
            state["debug_peer_encouraged"] = True
    if metadata.get("quiz_needs_mentor_explanation"):
        mentor_message = mentor_quiz_explanation_trigger(state, user_message, message)
        mentor_response = call_llm(state, "mentor", mentor_message)
        metadata["after_messages"] = [
            {
                "agent": "mentor",
                "message": clean_reply(mentor_response),
                "phase": "前测讲解",
                "trigger": "基础知识前测存在错误",
            }
        ]
        metadata["mentor_explained_quiz_errors"] = True
    if metadata.get("replan_invalid"):
        validation = metadata.get("replan_validation", {})
        missing = validation.get("missingNames") or []
        missing_text = f"还缺少：{'、'.join(missing)}。" if missing else ""
        message += (
            "\n\n系统提醒：这次剩余时间安排还没有同步到右侧计时器。"
            f"当前填写总计{validation.get('total', 0)}分钟，但剩余总时间应为{validation.get('expectedTotal', 0)}分钟。"
            f"{missing_text}"
            "请重新分配当前未完成任务和后续任务的时间，并让总计等于剩余总时间。"
        )
    if metadata.get("time_plan_incomplete"):
        parsed_summary = "、".join(f"{task['name']}{task['minutes']}分钟" for task in metadata.get("parsed_time_plan", []))
        parsed_hint = f"当前我识别到：{parsed_summary}。" if parsed_summary else "当前我还没有识别到完整的时间分配。"
        message += (
            "\n\n系统提醒：这次时间计划还没有同步给同伴智能体和右侧计时器。"
            f"{parsed_hint}"
            "请按四项任务重新回复完整计划，并让总计等于20分钟："
            "分析问题x分钟，设计算法x分钟，编写程序x分钟，代码优化x分钟。"
            "如果你写“设计程序”，系统会按“设计算法”处理。"
        )
    if metadata.get("plan_synced_to_peer"):
        total_minutes = metadata.get("total_minutes") or 20
        message += (
            f"\n\n学习计划已同步给编程同伴智能体。右侧计时器将按你分配的{total_minutes}分钟自动开始；"
            "接下来由编程导师智能体引导你完成IPO分析。每完成一个任务，直接告诉我“已完成”即可，"
            "同伴智能体会自动进入下一任务；你也可以使用右侧“进入下一任务”按钮手动推进。"
        )
    if agent == "peer" and any(k in user_message for k in ["没完成", "未完成", "超时", "时间已到", "倒计时已结束"]):
        metadata["overtime"] = True
        state["overtime_replan_pending"] = True
        message += (
            "\n\n请先停一下，重新分析这项任务为什么超时：是任务拆得太大、分析卡住、还是时间估计偏短。"
            "请直接回复剩余任务的新时间安排，例如“设计算法3分钟，编写程序6分钟，代码优化6分钟”。"
            "我会把右侧倒计时重置为新的剩余计划，并从第一项剩余任务开始计时。"
        )
    if agent == "peer" and metadata.get("reset_timer"):
        total_minutes = metadata.get("total_minutes") or 0
        message += f"\n\n新的剩余时间计划已同步到右侧倒计时，总计{total_minutes}分钟，现在重新开始计时。"
    if agent == "peer" and metadata.get("complete_timer"):
        message += "\n\n我已经帮你暂停倒计时，并把任务完成率更新到100%。接下来由编程助教智能体带你先做学习成果评价。"
        metadata["after_messages"] = (metadata.get("after_messages") or []) + [
            {
                "agent": "assistant",
                "message": assistant_reflection_start_message(),
                "phase": "学习成果评价",
                "trigger": "学生反馈代码运行成功后自动进入反思阶段",
            }
        ]
        metadata["reflection_available"] = True
        metadata["assistant_started_reflection"] = True
    return clean_reply(message), phase, metadata

def maybe_append_auto_followup(state, agent, response, metadata):
    return clean_reply(response)
