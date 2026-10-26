import json
import re
from datetime import datetime

from backend.storage import db_rows, execute
from backend.utils import contains_any


REFLECTION_STEPS = [
    "OUTCOME_SELF_EVALUATION",
    "OUTCOME_AGENT_EVALUATION",
    "OUTCOME_CONFIRMATION",
    "REFLECTION_PROCESS_REVIEW",
    "REFLECTION_CAUSE_ANALYSIS",
    "REFLECTION_EXPERIENCE_SUMMARY",
    "REFLECTION_IMPROVEMENT_PLAN",
    "REFLECTION_COMPLETE",
]

STEP_LABELS = {
    "OUTCOME_SELF_EVALUATION": "学习成果自评",
    "OUTCOME_AGENT_EVALUATION": "助教成果评价",
    "OUTCOME_CONFIRMATION": "确认成果记录",
    "REFLECTION_PROCESS_REVIEW": "回顾学习过程",
    "REFLECTION_CAUSE_ANALYSIS": "分析问题原因",
    "REFLECTION_EXPERIENCE_SUMMARY": "总结有效经验",
    "REFLECTION_IMPROVEMENT_PLAN": "制定改进措施",
    "REFLECTION_COMPLETE": "确认学习反思",
    "RETURN_TO_DEBUG": "返回调试完善",
}

DEFAULT_RUBRIC = [
    {"key": "taskCompletion", "dimension": "任务完成情况", "criteria": "是否实现了题目要求的功能。"},
    {"key": "runtimeCorrectness", "dimension": "运行正确性", "criteria": "程序能否正常运行，不同合理输入下结果是否符合预期。"},
    {"key": "programLogic", "dimension": "程序逻辑", "criteria": "判断条件和程序执行逻辑是否合理。"},
    {"key": "codeQuality", "dimension": "代码规范", "criteria": "代码格式、缩进、变量命名等是否基本规范。"},
]

VAGUE_ACTION_WORDS = ["认真一点", "多练习", "多检查", "仔细一点", "努力一点", "好好学"]
VAGUE_CAUSE_WORDS = ["粗心", "不认真", "没认真", "不会", "不熟", "忘了", "没学好"]
CAUSE_OPTIONS = ["知识掌握", "任务理解", "程序设计思路", "调试方法", "时间安排", "注意力或情绪", "其他"]


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def unavailable(reason="当前记录中暂时没有这项数据。"):
    return {"available": False, "reason": reason}


def available(value):
    return {"available": True, "value": value}


def safe_json_loads(value, default=None):
    if default is None:
        default = {}
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def student_id_from_state(state):
    return state.setdefault("student_session_id", "")


def ensure_learning_run(state):
    session_id = student_id_from_state(state)
    run_id = state.get("learning_run_id")
    if run_id:
        rows = db_rows("SELECT * FROM learning_runs WHERE id = ? AND session_id = ?", (run_id, session_id))
        if rows and rows[0].get("status") == "active":
            update_learning_run_from_state(rows[0]["id"], state)
            return rows[0]

    rows = db_rows(
        """
        SELECT * FROM learning_runs
        WHERE session_id = ? AND status = 'active'
        ORDER BY id DESC LIMIT 1
        """,
        (session_id,),
    )
    if rows:
        state["learning_run_id"] = rows[0]["id"]
        update_learning_run_from_state(rows[0]["id"], state)
        return rows[0]

    timestamp = now_text()
    previous_report = latest_reflection_report(session_id)
    if previous_report:
        state["previous_improvement_actions"] = previous_report.get("improvementActions", [])
    execute(
        """
        INSERT INTO learning_runs
        (session_id, student_name, topic, exercise_prompt, status, current_phase,
         previous_reflection_report_id, started_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            state.get("student_name", ""),
            state.get("current_topic", ""),
            state.get("exercise_prompt", ""),
            state.get("learning_phase", ""),
            previous_report.get("id") if previous_report else None,
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    row = db_rows(
        "SELECT * FROM learning_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    )[0]
    state["learning_run_id"] = row["id"]
    return row


def update_learning_run_from_state(run_id, state):
    execute(
        """
        UPDATE learning_runs
        SET student_name = ?, topic = ?, exercise_prompt = ?, current_phase = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            state.get("student_name", ""),
            state.get("current_topic", ""),
            state.get("exercise_prompt", ""),
            state.get("learning_phase", ""),
            now_text(),
            run_id,
        ),
    )


def latest_reflection_report(student_id):
    rows = db_rows(
        """
        SELECT * FROM reflection_reports
        WHERE student_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (student_id,),
    )
    if not rows:
        return None
    row = rows[0]
    row["report"] = safe_json_loads(row.get("report_json"), {})
    row["improvementActions"] = safe_json_loads(row.get("improvement_actions"), [])
    return row


def task_completion_index(step):
    mapping = {
        "topic_intro": 0,
        "experience_feedback": 0,
        "life_connection": 0,
        "exercise_intake": 0,
        "quiz": 0,
        "quiz_review": 0,
        "plan_allocation": 0,
        "ipo_analysis": 0,
        "flowchart": 1,
        "debugging": 2,
        "self_evaluation": 4,
        "outcome_evaluation": 4,
        "reflection_optimization": 4,
    }
    return mapping.get(step, 0)


def task_reviews_from_plan(plan, step, progress=None):
    planned = plan or []
    completed_count = task_completion_index(step)
    if progress == 100:
        completed_count = len(planned)
    reviews = []
    for index, task in enumerate(planned):
        reviews.append(
            {
                "name": task.get("name", ""),
                "plannedMinutes": int(task.get("minutes", 0) or 0),
                "completed": index < completed_count,
                "actualMinutes": None,
                "timeDeviationMinutes": None,
                "actualStatus": unavailable("当前版本只记录了计划时间，未记录每项任务的真实耗时。"),
            }
        )
    return reviews


def extract_submitted_code(interactions):
    code_blocks = []
    for row in interactions:
        text = row.get("user_message", "")
        blocks = re.findall(r"```(?:python)?\s*(.*?)```", text, flags=re.S | re.I)
        code_blocks.extend(block.strip() for block in blocks if block.strip())
        if not blocks and any(token in text for token in ["print(", "input(", "def ", "for ", "if "]):
            code_blocks.append(text.strip())
    if not code_blocks:
        return unavailable("当前聊天记录中没有发现学生提交的完整代码。")
    return available(code_blocks[-1])


def infer_run_results(interactions):
    success_words = ["运行成功", "调试成功", "没有报错", "无报错", "问题解决"]
    error_words = ["Traceback", "SyntaxError", "TypeError", "NameError", "报错", "运行错误"]
    for row in reversed(interactions):
        text = row.get("user_message", "")
        if any(word in text for word in success_words):
            return available({"status": "success", "source": "student_message", "message": text[:300]})
        if any(word in text for word in error_words):
            return available({"status": "error", "source": "student_message", "message": text[:300]})
    return unavailable("当前记录中没有结构化程序运行结果。")


def extract_test_evidence(interactions):
    evidence = []
    test_words = ["测试", "输入", "输出", "结果", "运行"]
    for row in interactions:
        text = row.get("user_message", "")
        if any(word in text for word in test_words) and any(word in text for word in ["输入", "输出", "结果"]):
            evidence.append(
                {
                    "source": "student_message",
                    "message": text[:300],
                    "createdAt": row.get("created_at"),
                }
            )
    return available(evidence[-5:]) if evidence else unavailable("当前记录中还没有发现多组测试数据。")


def _first_number_from_text(text):
    match = re.search(r"(-?\d+(?:\.\d+)?)", text or "")
    return float(match.group(1)) if match else None


def recommend_test_inputs(task_text, submitted_code):
    source = f"{task_text or ''}\n{submitted_code.get('value', '') if submitted_code.get('available') else ''}"
    number = _first_number_from_text(source)
    if number is None:
        return [
            "一组应该满足条件的数据",
            "一组应该不满足条件的数据",
            "一组接近判断变化位置的数据",
        ]
    step = 1 if number == int(number) else 0.1
    lower = number - step
    upper = number + step
    return [
        f"比 {number:g} 大一点的数据，例如 {upper:g}",
        f"比 {number:g} 小一点的数据，例如 {lower:g}",
        f"刚好等于 {number:g} 的边界数据",
    ]


def static_code_checks(submitted_code):
    if not submitted_code.get("available"):
        return unavailable("没有可检查的代码。")
    code = submitted_code["value"]
    checks = []
    checks.append({"name": "包含输出语句", "passed": "print(" in code})
    checks.append({"name": "包含输入语句", "passed": "input(" in code})
    checks.append({"name": "缩进看起来完整", "passed": "\t" not in code})
    checks.append({"name": "代码不为空", "passed": bool(code.strip())})
    return available(checks)


def count_debug_interactions(interactions, state):
    count = int(state.get("debug_count", 0) or 0)
    if count:
        return count
    debug_words = [
        "调试", "报错", "错误", "bug", "Traceback", "SyntaxError", "TypeError", "NameError",
        "运行结果", "测试结果", "输出结果", "执行结果", "修改后", "再运行", "重新运行",
    ]
    code_pattern = re.compile(
        r"\b(?:print|input|float|int|str|if|elif|else|for|while|def)\b|^\s*[a-zA-Z_]\w*\s*=",
        re.MULTILINE,
    )
    return sum(
        1
        for row in interactions
        if row.get("agent") == "mentor"
        and (
            any(word in row.get("user_message", "") for word in debug_words)
            or bool(code_pattern.search(row.get("user_message", "")))
        )
    )


def interactions_by_agent(interactions, agent):
    return [
        {
            "createdAt": row.get("created_at"),
            "phase": row.get("phase"),
            "studentMessage": row.get("user_message", "")[:300],
            "agentMessage": row.get("assistant_message", "")[:300],
        }
        for row in interactions
        if row.get("agent") == agent
    ]


def assemble_reflection_context(state, learning_session_id=None):
    run = ensure_learning_run(state)
    session_id = learning_session_id or student_id_from_state(state)
    if session_id != student_id_from_state(state):
        raise PermissionError("不能读取其他学习会话的反思数据。")

    interactions = db_rows(
        "SELECT * FROM interactions WHERE session_id = ? ORDER BY created_at ASC, id ASC",
        (session_id,),
    )
    plan = state.get("time_plan") or []
    debug_count = count_debug_interactions(interactions, state)
    submitted_code = extract_submitted_code(interactions)
    run_results = infer_run_results(interactions)
    test_results = extract_test_evidence(interactions)
    code_checks = static_code_checks(submitted_code)
    previous = latest_reflection_report(student_id_from_state(state))
    task_text = state.get("exercise_prompt") or state.get("current_topic") or ""

    context = {
        "learningRunId": run["id"],
        "learningSessionId": session_id,
        "studentId": student_id_from_state(state),
        "learningGoal": available(task_text) if task_text else unavailable("学生还没有形成明确的练习题干。"),
        "taskRequirement": available(state.get("exercise_prompt")) if state.get("exercise_prompt") else unavailable("当前记录中没有单独的编程任务要求。"),
        "plannedTasks": available(task_reviews_from_plan(plan, state.get("learning_step", ""), state.get("progress"))) if plan else unavailable("当前记录中没有完整学习计划。"),
        "plannedDurations": available(plan) if plan else unavailable("当前记录中没有计划时间。"),
        "actualTaskRecords": unavailable("当前版本没有逐项任务完成时间的结构化记录。"),
        "actualDurations": unavailable("当前版本没有真实耗时的结构化记录。"),
        "submittedCode": submitted_code,
        "codeVersions": unavailable("当前版本没有程序版本历史。"),
        "runResults": run_results,
        "testResults": test_results,
        "staticCodeChecks": code_checks,
        "recommendedTestInputs": recommend_test_inputs(task_text, submitted_code),
        "debugCount": available(debug_count),
        "mentorInteractions": interactions_by_agent(interactions, "mentor"),
        "peerInteractions": interactions_by_agent(interactions, "peer"),
        "assistantInteractions": interactions_by_agent(interactions, "assistant"),
        "progressEvents": progress_events_from_interactions(interactions),
        "previousReflection": previous["report"] if previous else unavailable("还没有上一轮正式反思报告。"),
        "rubric": DEFAULT_RUBRIC,
    }
    context["taskReview"] = build_task_review(context)
    context["workEvidence"] = build_work_evidence(context)
    context["processSummary"] = build_process_summary(context)
    context["problemCues"] = build_problem_cues(context)
    return context


def progress_events_from_interactions(interactions):
    events = []
    for row in interactions:
        metadata = safe_json_loads(row.get("metadata"), {})
        if metadata.get("learning_step") or metadata.get("start_timer") or metadata.get("complete_timer") or metadata.get("overtime"):
            events.append(
                {
                    "createdAt": row.get("created_at"),
                    "phase": row.get("phase"),
                    "agent": row.get("agent"),
                    "event": metadata,
                }
            )
    return events


def build_task_review(context):
    planned = context.get("plannedTasks", {})
    items = planned.get("value", []) if planned.get("available") else []
    total_planned = sum(item.get("plannedMinutes", 0) for item in items)
    completed = [item for item in items if item.get("completed")]
    return {
        "plannedTasks": items,
        "completedTasks": completed,
        "plannedDuration": total_planned if items else None,
        "actualDuration": None,
        "timeDeviations": [
            {
                "taskName": item.get("name"),
                "plannedMinutes": item.get("plannedMinutes"),
                "actualMinutes": item.get("actualMinutes"),
                "deviationMinutes": item.get("timeDeviationMinutes"),
                "status": "实际耗时暂无记录",
            }
            for item in items
        ],
        "studentGoalJudgement": None,
    }


def build_work_evidence(context):
    return {
        "rubric": DEFAULT_RUBRIC,
        "objectiveEvidence": {
            "runResults": context.get("runResults"),
            "testResults": context.get("testResults"),
            "staticCodeChecks": context.get("staticCodeChecks"),
        },
        "agentExplanation": "当前只展示可查到的客观证据。没有运行结果或测试用例时，系统不会猜测程序是否正确。",
    }


def _dimension_result(label, status, evidence):
    return {"label": label, "status": status, "evidence": evidence}


def _status_text(value):
    return "已完成" if value is True else "需要完善" if value is False else "证据不足"


def build_agent_outcome_evaluation(context, self_evaluation=None):
    self_evaluation = self_evaluation or {}
    submitted_code = context.get("submittedCode", {})
    run_results = context.get("runResults", {})
    test_results = context.get("testResults", {})
    code_checks = context.get("staticCodeChecks", {})
    task_text = context.get("taskRequirement", {}).get("value") or context.get("learningGoal", {}).get("value") or "当前任务"
    code = submitted_code.get("value", "") if submitted_code.get("available") else ""
    checks = code_checks.get("value", []) if code_checks.get("available") else []
    passed_checks = [item for item in checks if item.get("passed")]
    failed_checks = [item for item in checks if not item.get("passed")]

    strengths = []
    problems = []

    has_code = bool(code.strip())
    run_success = run_results.get("available") and run_results.get("value", {}).get("status") == "success"
    has_test_evidence = test_results.get("available") and bool(test_results.get("value"))
    needs_condition_logic = any(word in task_text for word in ["判断", "是否", "如果", "条件", "分支"]) or "if " in code
    has_condition_logic = bool(re.search(r"\bif\b", code))

    if has_code:
        strengths.append("已经提交了可以检查的程序代码。")
    else:
        problems.append("当前记录中没有发现完整代码。")

    if run_success:
        strengths.append("学生记录显示程序已经能够运行。")
    elif run_results.get("available"):
        problems.append("当前运行记录中仍有错误或异常。")
    else:
        problems.append("缺少明确的程序运行结果。")

    if has_test_evidence:
        strengths.append("已经记录了至少一组运行或测试结果。")
    else:
        problems.append("测试数据较少，还不能只凭“能运行”判断程序完全正确。")

    if needs_condition_logic and not has_condition_logic:
        problems.append("任务需要判断逻辑，但当前代码中没有发现 if 判断。")
    elif has_condition_logic:
        strengths.append("代码中已经使用了判断结构来处理条件。")

    if failed_checks:
        problems.extend(f"{item['name']}还需要检查。" for item in failed_checks)
    if passed_checks:
        strengths.append("基础代码检查中有项目通过，例如：" + "、".join(item["name"] for item in passed_checks[:2]) + "。")

    agent_evaluation = {
        "taskCompletion": _dimension_result(
            "任务完成情况",
            _status_text(has_code and (run_success or has_condition_logic)),
            "根据任务要求和当前提交代码判断；系统不会替学生补写代码。",
        ),
        "runtimeCorrectness": _dimension_result(
            "运行正确性",
            "基本运行" if run_success and has_test_evidence else "需要更多测试" if run_success else "证据不足",
            "运行成功只是第一步，还需要不同数据下的结果证据。",
        ),
        "programLogic": _dimension_result(
            "程序逻辑",
            _status_text((not needs_condition_logic) or has_condition_logic),
            "根据题干是否需要条件判断，以及代码中是否出现相应判断结构来检查。",
        ),
        "codeQuality": _dimension_result(
            "代码规范",
            "基本规范" if code_checks.get("available") and not failed_checks else "需要检查",
            "根据缩进、输入输出语句和代码是否为空等基础规则检查。",
        ),
    }

    return {
        "taskId": task_text[:80],
        "studentId": context.get("studentId"),
        "selfEvaluation": {
            "taskCompletion": self_evaluation.get("taskCompletion"),
            "runtimeCorrectness": self_evaluation.get("runtimeCorrectness") or self_evaluation.get("testConfidence"),
            "programLogic": self_evaluation.get("programLogic"),
            "codeQuality": self_evaluation.get("codeQuality"),
        },
        "agentEvaluation": agent_evaluation,
        "strengths": list(dict.fromkeys(strengths)),
        "problems": list(dict.fromkeys(problems)),
        "testEvidence": test_results.get("value", []) if test_results.get("available") else [],
        "recommendedTestInputs": context.get("recommendedTestInputs", []),
        "coreFunctionIncomplete": not has_code or (needs_condition_logic and not has_condition_logic),
        "timestamp": now_text(),
    }


def format_outcome_evaluation_feedback(context, outcome_record):
    task_text = context.get("taskRequirement", {}).get("value") or context.get("learningGoal", {}).get("value") or "当前任务"
    agent_eval = outcome_record.get("agentEvaluation", {})
    lines = [
        "那我们继续。刚才你完成了自评，现在我结合当前任务和已有程序记录，从四个维度给你反馈。",
        "",
        f"当前任务：{task_text}",
        "",
    ]
    for key in ["taskCompletion", "runtimeCorrectness", "programLogic", "codeQuality"]:
        item = agent_eval.get(key) or {}
        label = item.get("label") or key
        status = item.get("status") or "证据不足"
        evidence = item.get("evidence") or "当前记录不足。"
        lines.append(f"{label}：{status}。{evidence}")
    strengths = "；".join(outcome_record.get("strengths") or []) or "当前记录中还没有足够证据。"
    problems = "；".join(outcome_record.get("problems") or []) or "当前记录中没有发现明确问题。"
    lines.extend(
        [
            "",
            f"已经看到的表现：{strengths}",
            f"还需要继续确认的地方：{problems}",
            "",
            "你觉得这四个维度里，哪个方面最想继续保持，或者哪个方面还想改进？",
        ]
    )
    return "\n".join(lines)


def reply_conflicts_with_current_task(state, message):
    exercise = state.get("exercise_prompt") or ""
    if not exercise or contains_any(exercise, ["BMI", "bmi", "身高", "体重"]):
        return False
    return contains_any(message or "", ["BMI", "bmi", "身高", "体重", "height", "weight"])


def compare_self_and_agent(outcome_record):
    self_eval = outcome_record.get("selfEvaluation", {})
    agent_eval = outcome_record.get("agentEvaluation", {})
    differences = []
    aligned = []
    positive_self_values = {"已完成", "符合", "检查过", "基本规范", "有"}
    caution_agent_values = {"需要完善", "证据不足", "需要更多测试", "需要检查"}
    for key, self_value in self_eval.items():
        agent_status = (agent_eval.get(key) or {}).get("status", "")
        if self_value in positive_self_values and agent_status in caution_agent_values:
            differences.append({"dimension": (agent_eval.get(key) or {}).get("label", key), "self": self_value, "agent": agent_status})
        elif self_value:
            aligned.append({"dimension": (agent_eval.get(key) or {}).get("label", key), "self": self_value, "agent": agent_status})
    return {
        "isMostlyAligned": not differences,
        "aligned": aligned,
        "differences": differences,
    }


def build_process_summary(context):
    task_review = context.get("taskReview", {})
    return {
        "taskCompletion": task_review.get("plannedTasks", []),
        "timeUse": "计划时间已记录；真实耗时暂无结构化记录。",
        "debugCount": context.get("debugCount", {}).get("value", 0),
        "keyHelpRecords": {
            "mentor": context.get("mentorInteractions", [])[-3:],
            "peer": context.get("peerInteractions", [])[-3:],
            "assistant": context.get("assistantInteractions", [])[-3:],
        },
        "importantEvents": context.get("progressEvents", [])[-8:],
    }


def build_problem_cues(context):
    cues = []
    for problem in (context.get("outcomeEvaluation", {}) or {}).get("problems", []):
        cues.append(
            {
                "description": problem,
                "evidence": "来自学习成果评价记录。",
                "source": "成果评价",
                "studentConfirmed": False,
            }
        )
    task_review = context.get("taskReview", {})
    planned_tasks = task_review.get("plannedTasks", [])
    if planned_tasks and len(task_review.get("completedTasks", [])) < len(planned_tasks):
        cues.append(
            {
                "description": "有计划任务可能还没有全部完成。",
                "evidence": "任务完成记录显示还有未完成项。",
                "source": "系统数据",
                "studentConfirmed": False,
            }
        )
    if context.get("debugCount", {}).get("value", 0) >= 2:
        cues.append(
            {
                "description": "调试次数较多，可能需要回顾调试方法。",
                "evidence": f"本轮记录到 {context['debugCount']['value']} 次调试相关求助。",
                "source": "系统数据",
                "studentConfirmed": False,
            }
        )
    if not context.get("runResults", {}).get("available"):
        cues.append(
            {
                "description": "程序运行结果没有被完整记录。",
                "evidence": context.get("runResults", {}).get("reason", "缺少运行结果。"),
                "source": "系统数据",
                "studentConfirmed": False,
            }
        )
    if not cues:
        cues.append(
            {
                "description": "当前记录没有发现明显异常，可以请你自己补充一个最想改进的地方。",
                "evidence": "系统没有检测到超时、反复调试或未完成等明确现象。",
                "source": "系统数据",
                "studentConfirmed": False,
            }
        )
    return cues


def get_or_create_reflection_session(state):
    run = ensure_learning_run(state)
    student_id = student_id_from_state(state)
    rows = db_rows(
        """
        SELECT * FROM reflection_sessions
        WHERE learning_session_id = ? AND status NOT IN ('completed', 'returned_to_debug')
        ORDER BY id DESC LIMIT 1
        """,
        (student_id,),
    )
    if rows:
        return rows[0], False
    timestamp = now_text()
    execute(
        """
        INSERT INTO reflection_sessions
        (student_id, learning_session_id, learning_run_id, task_id, current_step, status,
         started_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
        """,
        (
            student_id,
            student_id,
            run["id"],
            state.get("exercise_prompt", "")[:80],
            "OUTCOME_SELF_EVALUATION",
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    session = db_rows(
        "SELECT * FROM reflection_sessions WHERE learning_session_id = ? ORDER BY id DESC LIMIT 1",
        (student_id,),
    )[0]
    return session, True


def reflection_step_payload(reflection_session_id, step):
    rows = db_rows(
        "SELECT payload FROM reflection_step_data WHERE reflection_session_id = ? AND step = ?",
        (reflection_session_id, step),
    )
    if not rows:
        return {}
    return safe_json_loads(rows[0].get("payload"), {})


def all_reflection_step_data(reflection_session_id):
    rows = db_rows(
        "SELECT step, payload FROM reflection_step_data WHERE reflection_session_id = ?",
        (reflection_session_id,),
    )
    return {row["step"]: safe_json_loads(row.get("payload"), {}) for row in rows}


def mark_return_to_debug(state, session_id):
    timestamp = now_text()
    execute(
        """
        UPDATE reflection_sessions
        SET current_step = 'RETURN_TO_DEBUG', status = 'returned_to_debug', updated_at = ?
        WHERE id = ?
        """,
        (timestamp, session_id),
    )
    state["learning_phase"] = "代码编写与调试"
    state["learning_step"] = "debugging"
    state["reflection_current_step"] = ""
    state["debug_success_peer_acknowledged"] = False
    return {
        "ok": True,
        "returnedToDebug": True,
        "message": "成果评价发现程序还需要完善。已经返回代码编写与调试阶段，修改并再次确认运行成功后，会重新进入学习成果评价。",
    }


def save_reflection_step(state, step, payload, next_step=None):
    if step not in REFLECTION_STEPS:
        raise ValueError("未知的反思步骤。")
    session, _ = get_or_create_reflection_session(state)
    draft = all_reflection_step_data(session["id"])
    if step == "OUTCOME_AGENT_EVALUATION":
        context = assemble_reflection_context(state, session["learning_session_id"])
        payload = build_agent_outcome_evaluation(context, draft.get("OUTCOME_SELF_EVALUATION", {}))
    if step == "OUTCOME_CONFIRMATION" and (payload or {}).get("nextAction") == "return_to_debug":
        return mark_return_to_debug(state, session["id"])
    if step in {"OUTCOME_SELF_EVALUATION", "OUTCOME_AGENT_EVALUATION", "OUTCOME_CONFIRMATION"}:
        state["learning_phase"] = "学习成果评价"
    if step == "OUTCOME_CONFIRMATION" and (payload or {}).get("nextAction", "continue_reflection") == "continue_reflection":
        state["learning_phase"] = "学习反思优化"
    if step.startswith("REFLECTION_"):
        state["learning_phase"] = "学习反思优化"
    timestamp = now_text()
    execute(
        """
        INSERT INTO reflection_step_data
        (reflection_session_id, step, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(reflection_session_id, step)
        DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (
            session["id"],
            step,
            json.dumps(payload or {}, ensure_ascii=False),
            timestamp,
            timestamp,
        ),
    )
    target_step = next_step or next_reflection_step(step)
    if target_step:
        set_reflection_step(session["id"], target_step)
    return get_reflection_session_payload(state)


def next_reflection_step(step):
    try:
        index = REFLECTION_STEPS.index(step)
    except ValueError:
        return None
    if index + 1 >= len(REFLECTION_STEPS):
        return step
    return REFLECTION_STEPS[index + 1]


def previous_reflection_step(step):
    try:
        index = REFLECTION_STEPS.index(step)
    except ValueError:
        return None
    return REFLECTION_STEPS[max(0, index - 1)]


def set_reflection_step(reflection_session_id, step):
    execute(
        "UPDATE reflection_sessions SET current_step = ?, updated_at = ? WHERE id = ?",
        (step, now_text(), reflection_session_id),
    )


def get_reflection_session_payload(state):
    session, created = get_or_create_reflection_session(state)
    context = assemble_reflection_context(state, session["learning_session_id"])
    state["reflection_current_step"] = session["current_step"]
    draft = all_reflection_step_data(session["id"])
    outcome_record = draft.get("OUTCOME_AGENT_EVALUATION") or build_agent_outcome_evaluation(
        context,
        draft.get("OUTCOME_SELF_EVALUATION", {}),
    )
    context["outcomeEvaluation"] = outcome_record
    context["outcomeComparison"] = compare_self_and_agent(outcome_record)
    context["problemCues"] = build_problem_cues(context)
    return {
        "session": session,
        "created": created,
        "steps": REFLECTION_STEPS,
        "stepLabels": STEP_LABELS,
        "currentStep": session["current_step"],
        "context": context,
        "draft": draft,
    }


def validate_improvement_action(action):
    missing = []
    for field in ["relatedProblem", "action", "verification", "nextUseContext"]:
        if not str(action.get(field, "")).strip():
            missing.append(field)
    text = str(action.get("action", "")).strip()
    vague = any(word in text for word in VAGUE_ACTION_WORDS) or len(text) < 8
    return {
        "ok": not missing and not vague,
        "missingFields": missing,
        "needsDetail": vague,
        "message": "请把改进措施写得更具体。" if vague else "",
    }


def validate_cause_analysis(payload):
    evidence = str((payload or {}).get("studentEvidence", "")).strip()
    vague = any(word in evidence for word in VAGUE_CAUSE_WORDS) or len(evidence) < 8
    return {
        "ok": not vague,
        "needsDetail": vague,
        "message": "请补充一个具体表现或学习记录，不要只写“粗心”“不认真”这类笼统原因。",
    }


def validate_improvement_actions(actions):
    results = [validate_improvement_action(action) for action in (actions or [])]
    return {"ok": bool(results) and all(item["ok"] for item in results), "items": results}


def first_available_text(item, fallback="暂无记录"):
    if isinstance(item, dict):
        if item.get("available"):
            return str(item.get("value") or "").strip() or fallback
        return item.get("reason") or fallback
    return str(item or "").strip() or fallback


def build_student_learning_record_summary(context, outcome, confirmation, process_review, causes, experiences, improvements):
    task_review = context.get("taskReview") or {}
    planned_tasks = task_review.get("plannedTasks") or []
    completed_tasks = task_review.get("completedTasks") or []
    planned_names = [item.get("name") for item in planned_tasks if item.get("name")]
    completed_names = [item.get("name") for item in completed_tasks if item.get("name")]
    debug_count = (context.get("debugCount") or {}).get("value", 0)
    selected_problem = process_review.get("selectedProblem") or process_review.get("extraProblem") or ""
    confirmed_causes = causes.get("confirmedCauses") or []
    effective_strategies = experiences.get("effectiveStrategies") or []
    actions = improvements.get("actions") or []
    return {
        "learningGoal": first_available_text(context.get("learningGoal")),
        "taskCompletion": {
            "plannedTasks": planned_names,
            "completedTasks": completed_names,
            "plannedDuration": task_review.get("plannedDuration"),
        },
        "outcome": {
            "studentFinalEvaluation": confirmation.get("studentFinalEvaluation", ""),
            "strengths": outcome.get("strengths", []),
            "problems": outcome.get("problems", []),
        },
        "reflectionFocus": selected_problem,
        "causeAnalysis": confirmed_causes,
        "effectiveStrategies": effective_strategies,
        "improvementActions": actions,
        "processEvidence": {
            "debugCount": debug_count,
            "testEvidenceCount": len(outcome.get("testEvidence", []) or []),
        },
    }


def build_report_from_draft(state):
    session, _ = get_or_create_reflection_session(state)
    draft = all_reflection_step_data(session["id"])
    context = assemble_reflection_context(state, session["learning_session_id"])
    outcome = draft.get("OUTCOME_AGENT_EVALUATION") or build_agent_outcome_evaluation(
        context,
        draft.get("OUTCOME_SELF_EVALUATION", {}),
    )
    confirmation = draft.get("OUTCOME_CONFIRMATION", {})
    process_review = draft.get("REFLECTION_PROCESS_REVIEW", {})
    causes = draft.get("REFLECTION_CAUSE_ANALYSIS", {})
    experiences = draft.get("REFLECTION_EXPERIENCE_SUMMARY", {})
    improvements = draft.get("REFLECTION_IMPROVEMENT_PLAN", {})
    return {
        "outcomeSummary": {
            "strengths": outcome.get("strengths", []),
            "problems": outcome.get("problems", []),
            "studentFinalEvaluation": confirmation.get("studentFinalEvaluation", ""),
        },
        "outcomeEvaluation": {
            "rubric": DEFAULT_RUBRIC,
            "selfEvaluation": outcome.get("selfEvaluation", {}),
            "agentEvaluation": outcome.get("agentEvaluation", {}),
            "comparison": compare_self_and_agent(outcome),
            "testEvidence": outcome.get("testEvidence", []),
            "recommendedTestInputs": outcome.get("recommendedTestInputs", []),
        },
        "reflection": {
            "selectedProblem": process_review.get("selectedProblem") or process_review.get("extraProblem"),
            "causeAnalysis": causes.get("confirmedCauses", []),
            "effectiveStrategies": experiences.get("effectiveStrategies", []),
            "improvementActions": improvements.get("actions", []),
        },
        "learningStrengths": outcome.get("strengths", []),
        "mainProblems": outcome.get("problems", []),
        "causeAnalysis": causes.get("confirmedCauses", []),
        "effectiveExperiences": experiences.get("effectiveStrategies", []),
        "improvementActions": improvements.get("actions", []),
        "systemData": {
            "taskReview": context.get("taskReview"),
            "processSummary": context.get("processSummary"),
            "outcomeEvaluation": outcome,
        },
        "agentSuggestions": {
            "problemCues": context.get("problemCues"),
            "workEvidence": context.get("workEvidence"),
        },
        "studentLearningRecordSummary": build_student_learning_record_summary(
            context,
            outcome,
            confirmation,
            process_review,
            causes,
            experiences,
            improvements,
        ),
    }


def save_final_report(state, confirmation_payload):
    session, _ = get_or_create_reflection_session(state)
    report = build_report_from_draft(state)
    report["studentConfirmation"] = confirmation_payload or {}
    report["studentConfirmedAt"] = now_text()
    improvements = report.get("improvementActions") or []
    validation = validate_improvement_actions(improvements)
    if not validation["ok"]:
        raise ValueError("改进措施还不够完整，请先补充具体行动和判断标准。")
    timestamp = now_text()
    execute(
        """
        INSERT INTO reflection_reports
        (reflection_session_id, student_id, learning_session_id, learning_run_id, objective_data,
         agent_suggestions, student_confirmed_content, improvement_actions, report_json,
         student_confirmed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["id"],
            student_id_from_state(state),
            session["learning_session_id"],
            session.get("learning_run_id"),
            json.dumps(report.get("systemData", {}), ensure_ascii=False),
            json.dumps(report.get("agentSuggestions", {}), ensure_ascii=False),
            json.dumps(confirmation_payload or {}, ensure_ascii=False),
            json.dumps(improvements, ensure_ascii=False),
            json.dumps(report, ensure_ascii=False),
            report["studentConfirmedAt"],
            timestamp,
        ),
    )
    report_id = db_rows(
        "SELECT id FROM reflection_reports WHERE reflection_session_id = ? ORDER BY id DESC LIMIT 1",
        (session["id"],),
    )[0]["id"]
    for action in improvements:
        execute(
            """
            INSERT INTO reflection_improvement_actions
            (reflection_report_id, student_id, related_problem, related_cause, action,
             verification, next_use_context, student_confirmed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                report_id,
                student_id_from_state(state),
                action.get("relatedProblem", ""),
                action.get("relatedCause", ""),
                action.get("action", ""),
                action.get("verification", ""),
                action.get("nextUseContext", ""),
                timestamp,
            ),
        )
    execute(
        """
        UPDATE reflection_sessions
        SET current_step = 'REFLECTION_COMPLETE', status = 'completed', completed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (timestamp, timestamp, session["id"]),
    )
    execute(
        "UPDATE learning_runs SET status = 'reflected', completed_at = ?, updated_at = ? WHERE id = ?",
        (timestamp, timestamp, session.get("learning_run_id")),
    )
    state["last_reflection_report_id"] = report_id
    state["previous_improvement_actions"] = improvements
    state["reflection_current_step"] = "REFLECTION_COMPLETE"
    state["learning_run_id"] = None
    return {"reportId": report_id, "report": report}
