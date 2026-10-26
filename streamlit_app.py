import csv
import html
import json
import os
import re
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components

from backend.agents.router_agent import AGENT_NAMES, agent_notice, manager_refusal, route_agent
from backend.services.knowledge_base import build_knowledge_summary, existing_upload_rows, extract_text
from backend.services.learning_flow import (
    assistant_reflection_start_message,
    clean_reply,
    decorate_message,
    looks_like_debug_success,
    maybe_append_auto_followup,
    prepare_step_for_prompt,
)
from backend.services.llm_client import call_llm
from backend.services.reflection_service import (
    get_reflection_session_payload,
    latest_reflection_report,
    save_final_report,
    save_reflection_step,
    student_id_from_state,
    validate_improvement_actions,
)
from backend.storage import db_rows, execute, init_storage, save_interaction
from backend.upload_store import choose_upload_dir, find_upload_file, iter_upload_files
from backend.utils import allowed_file, ensure_student_state, load_env_file, secure_name


st.set_page_config(
    page_title="编程自主学习伙伴",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_runtime_config():
    load_env_file()
    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_TIMEOUT",
        "TEACHER_USERNAME",
        "TEACHER_PASSWORD",
        "APP_DB_PATH",
        "APP_UPLOAD_DIR",
    ]:
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value and key not in os.environ:
            os.environ[key] = str(value)


@st.cache_resource
def initialize_app():
    load_runtime_config()
    init_storage()
    return True


def student_state():
    state = st.session_state.setdefault("student_state", {})
    ensure_student_state(state)
    return state


def agent_options():
    return {
        "编程自主学习管家": "auto",
        "助教智能体": "assistant",
        "导师智能体": "mentor",
        "同伴智能体": "peer",
    }


TASK_LABELS = {
    "分析问题": "分析",
    "设计算法": "算法",
    "编写程序": "编程",
    "代码优化": "优化",
}

DEFAULT_TIME_PLAN = [
    {"name": "分析问题", "label": "分析", "minutes": 5},
    {"name": "设计算法", "label": "算法", "minutes": 5},
    {"name": "编写程序", "label": "编程", "minutes": 7},
    {"name": "代码优化", "label": "优化", "minutes": 3},
]

TIME_PLAN_WIDGET_PREFIX = "time_plan_input"
PEER_MONITOR_TITLE = "同伴智能体监督区"
CHAT_AVATARS = {
    "user": "static/agent_avatars/user.svg",
    "manager": "static/agent_avatars/manager.svg",
    "assistant": "static/agent_avatars/assistant.svg",
    "mentor": "static/agent_avatars/mentor.svg",
    "peer": "static/agent_avatars/peer.svg",
}
COMPLETION_WORDS = [
    "已完成",
    "完成了",
    "做完了",
    "完成任务",
    "任务完成",
    "分析完成",
    "算法完成",
    "编写完成",
    "优化完成",
    "流程图完成",
    "流程图正确",
    "代码写完",
    "编写完代码",
    "IPO正确",
    "分析正确",
    "结束问题分析",
    "完全正确",
    "调试成功",
    "运行成功",
    "问题解决",
    "进入下一任务",
]
LEARNING_STEP_TASK_INDEX = {
    "ipo_analysis": 0,
    "flowchart": 1,
    "debugging": 2,
    "self_evaluation": 3,
}


def inject_student_page_styles():
    st.markdown(
        """
        <style>
        .peer-monitor-title {
            margin: 0 0 10px 0;
            color: #2f3340;
            font-size: 18px;
            font-weight: 800;
            line-height: 1.2;
            letter-spacing: 0;
            white-space: normal;
        }
        .peer-current-task {
            margin-top: 4px;
            color: #2f3340;
            font-size: 19px;
            font-weight: 800;
            line-height: 1.15;
            letter-spacing: 0;
        }
        .peer-timer-text {
            font-size: 36px;
            font-weight: 800;
            color: #f45f5f;
            line-height: 1;
            letter-spacing: 0;
        }
        .peer-card {
            border: 1px solid #d8dce3;
            border-radius: 8px;
            padding: 10px 14px;
            background: #ffffff;
        }
        .peer-card-label {
            color: #8b909b;
            font-size: 0.78rem;
            line-height: 1.1;
        }
        .peer-progress-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            color: #2f3340;
            font-size: 0.9rem;
            font-weight: 700;
        }
        .peer-progress-track {
            height: 7px;
            border-radius: 999px;
            background: #edf1f6;
            overflow: hidden;
            margin: 8px 0 4px 0;
        }
        .peer-progress-fill {
            height: 100%;
            border-radius: inherit;
            background: #2b7de9;
        }
        .st-key-peer_monitor_fixed,
       .st-key-peer_monitor_fixed {
            position: fixed;
            top: 84px;
            right: 24px;
            width: min(420px, 30vw);   /* 改为 min 保证最小宽度 */
            max-height: calc(100vh - 96px);
            overflow-y: auto;
            padding-bottom: 4px;
            z-index: 20;
            background: #ffffff;
            border-radius: 12px;        /* 增加圆角 */
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            padding: 16px 18px;         /* 统一内边距 */
        }
        .st-key-peer_monitor_fixed [data-testid="stVerticalBlock"] {
            gap: 0.3rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stCaptionContainer"] {
            font-size: 0.75rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stNumberInput"] label {
            font-size: 0.82rem;
            margin-bottom: 0.15rem;
        }
        .st-key-peer_monitor_fixed [data-testid="stNumberInput"] input {
            min-height: 32px;
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
            font-size: 0.85rem;
        }
        .st-key-peer_monitor_fixed button {
            min-height: 32px;
            padding-top: 0.25rem;
            padding-bottom: 0.25rem;
        }
        .peer-debug-row {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
            padding: 0;
        }
        .peer-debug-label {
            color: #8b909b;
            font-size: 0.78rem;
        }
        .peer-debug-value {
            color: #2f3340;
            font-size: 22px;
            font-weight: 800;
            line-height: 1;
        }
        .st-key-chat_scroll_area,
        .st-key-chat-scroll-area {
            height: calc(100vh - 220px);
            overflow-y: auto;
            padding-right: 0.65rem;
        }
        .st-key-chat_scroll_area [data-testid="stVerticalBlock"],
        .st-key-chat-scroll-area [data-testid="stVerticalBlock"] {
            gap: 0.85rem;
        }
        .flowchart-message {
            display: grid;
            gap: 0.75rem;
            margin-top: 0.25rem;
        }
        .flowchart-message p {
            margin: 0;
            color: #2f3340;
            line-height: 1.7;
            white-space: pre-wrap;
        }
        .flowchart-diagram {
            display: grid;
            justify-items: center;
            gap: 0;
            max-width: 100%;
            overflow-x: auto;
            padding: 16px 10px;
            background: #f8fbff;
            border: 1px solid #d8dce3;
            border-radius: 8px;
        }
        .flow-node {
            min-width: 190px;
            max-width: min(460px, 100%);
            min-height: 54px;
            display: grid;
            place-items: center;
            padding: 10px 20px;
            color: #2f3340;
            background: #e5f7ff;
            border: 2px solid #6ea3ff;
            text-align: center;
            line-height: 1.5;
            font-weight: 700;
            box-sizing: border-box;
        }
        .flow-node-terminal {
            min-width: 112px;
            border-radius: 999px;
        }
        .flow-node-process {
            min-width: 260px;
            border-radius: 2px;
        }
        .flow-node-merge {
            min-width: 170px;
            min-height: 42px;
            color: #405a83;
            background: #f1f6ff;
            border-style: dashed;
            border-radius: 999px;
            font-size: 15px;
        }
        .flow-node-io {
            min-width: 250px;
            transform: skewX(-18deg);
            border-radius: 2px;
        }
        .flow-node-io span {
            display: inline-block;
            transform: skewX(18deg);
        }
        .flow-node-decision {
            width: 150px;
            height: 150px;
            min-width: 150px;
            transform: rotate(45deg);
            margin: 16px 0;
        }
        .flow-node-decision span {
            display: inline-block;
            max-width: 110px;
            transform: rotate(-45deg);
        }
        .flow-arrow {
            color: #8a98a8;
            font-size: 32px;
            line-height: 1.1;
        }
        .flow-branches {
            width: min(560px, 100%);
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            align-items: start;
            margin: 4px 0 12px 0;
        }
        .flow-branch {
            display: grid;
            justify-items: center;
            gap: 6px;
        }
        .flow-branch-label {
            color: #5f6875;
            font-size: 14px;
            font-weight: 800;
            line-height: 1.2;
        }
        .flow-branches .flow-node {
            min-width: min(230px, 100%);
            width: 100%;
        }
        .flow-blank {
            display: inline-flex;
            min-width: 64px;
            margin: 0 3px;
            padding: 1px 6px;
            justify-content: center;
            color: #2b7de9;
            background: #ffffff;
            border: 1px dashed #2b7de9;
            border-radius: 4px;
        }
        .flowchart-answer-hint {
            padding: 10px 12px;
            color: #5f6875;
            background: #fff7db;
            border: 1px solid #f1d487;
            border-radius: 6px;
        }
        div[data-testid="column"]:has(.st-key-peer_monitor_fixed),
        div[data-testid="column"]:has(.st-key-peer-monitor-fixed) {
            min-height: calc(100vh - 120px);
        }
        @media (max-width: 1100px) {
            .peer-monitor-title {
                font-size: 17px;
            }
            .peer-current-task {
                font-size: 19px;
            }
            .peer-timer-text {
                font-size: 34px;
            }
        }
        @media (max-width: 900px) {
            .st-key-chat_scroll_area,
            .st-key-chat-scroll-area {
                height: auto;
                overflow-y: visible;
                padding-right: 0;
            }
            .st-key-peer_monitor_fixed,
            .st-key-peer-monitor-fixed {
                position: static;
                width: auto;
                max-height: none;
                overflow-y: visible;
                background: transparent;
            }
            div[data-testid="column"]:has(.st-key-peer_monitor_fixed),
            div[data-testid="column"]:has(.st-key-peer-monitor-fixed) {
                min-height: auto;
            }
            .flow-branches {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def timer_state():
    return st.session_state.setdefault(
        "timer_state",
        {
            "running": False,
            "started_at": None,
            "elapsed_before_pause": 0.0,
            "current_task_index": 0,
            "completed_tasks": 0,
        },
    )


def normalize_time_plan(source_plan):
    source_by_name = {
        task.get("name"): task
        for task in (source_plan or [])
        if task.get("name")
    }
    plan = []
    for default in DEFAULT_TIME_PLAN:
        task = source_by_name.get(default["name"], default)
        name = default["name"]
        plan.append(
            {
                "name": name,
                "label": TASK_LABELS.get(name, default["label"]),
                "minutes": int(task.get("minutes", default["minutes"])),
            }
        )
    return plan


def active_time_plan(state):
    source_plan = st.session_state.get("manual_time_plan") or state.get("time_plan") or DEFAULT_TIME_PLAN
    return normalize_time_plan(source_plan)


def has_estimated_time_plan(state):
    return bool(state.get("plan_synced") or st.session_state.get("time_plan_estimated"))


def same_minutes(left_plan, right_plan):
    left = normalize_time_plan(left_plan)
    right = normalize_time_plan(right_plan)
    return [task["minutes"] for task in left] == [task["minutes"] for task in right]


def set_active_time_plan(state, plan):
    normalized = normalize_time_plan(plan)
    state["time_plan"] = normalized
    st.session_state["manual_time_plan"] = normalized
    st.session_state["time_plan_estimated"] = True
    st.session_state["time_plan_version"] = int(st.session_state.get("time_plan_version", 0)) + 1
    return normalized


def total_plan_seconds(plan):
    return max(0, sum(task["minutes"] for task in plan) * 60)


def cumulative_task_seconds(plan, task_index):
    if not plan:
        return 0
    end_index = min(max(task_index, 0), len(plan) - 1) + 1
    return max(0, sum(task["minutes"] for task in plan[:end_index]) * 60)


def elapsed_timer_seconds(timer):
    elapsed = float(timer.get("elapsed_before_pause", 0.0))
    if timer.get("running") and timer.get("started_at"):
        elapsed += time.time() - float(timer["started_at"])
    return max(0, elapsed)


def remaining_timer_seconds(plan, timer):
    return max(0, int(total_plan_seconds(plan) - elapsed_timer_seconds(timer)))


def current_task_remaining_seconds(plan, timer):
    current_index = min(int(timer.get("current_task_index", 0)), max(len(plan) - 1, 0))
    return max(0, int(cumulative_task_seconds(plan, current_index) - elapsed_timer_seconds(timer)))


def format_seconds(seconds):
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


def render_browser_countdown(element_id, remaining_seconds, running):
    payload = json.dumps(
        {
            "elementId": element_id,
            "remainingSeconds": max(0, int(remaining_seconds)),
            "running": bool(running),
        },
        ensure_ascii=True,
    )
    components.html(
        f"""
        <script>
        (() => {{
          const config = {payload};
          const parentDoc = window.parent.document;
          const target = parentDoc.getElementById(config.elementId);
          if (!target) return;

          const format = (value) => {{
            const seconds = Math.max(0, Math.floor(value));
            const minutes = Math.floor(seconds / 60);
            const rest = seconds % 60;
            return `${{String(minutes).padStart(2, "0")}}:${{String(rest).padStart(2, "0")}}`;
          }};

          const timerKey = `codexCountdown_${{config.elementId}}`;
          if (parentDoc.defaultView[timerKey]) {{
            parentDoc.defaultView.clearInterval(parentDoc.defaultView[timerKey]);
            parentDoc.defaultView[timerKey] = null;
          }}

          let remaining = config.remainingSeconds;
          target.textContent = format(remaining);
          if (!config.running || remaining <= 0) return;

          const startedAt = Date.now();
          parentDoc.defaultView[timerKey] = parentDoc.defaultView.setInterval(() => {{
            const elapsed = Math.floor((Date.now() - startedAt) / 1000);
            const next = Math.max(0, remaining - elapsed);
            target.textContent = format(next);
            if (next <= 0) {{
              parentDoc.defaultView.clearInterval(parentDoc.defaultView[timerKey]);
              parentDoc.defaultView[timerKey] = null;
            }}
          }}, 1000);
        }})();
        </script>
        """,
        height=0,
    )


def distribute_remaining_minutes(tasks, total_minutes):
    tasks = list(tasks or [])
    total_minutes = max(0, int(total_minutes))
    if not tasks:
        return []
    if total_minutes <= 0:
        return [{**task, "minutes": 0} for task in tasks]
    original_total = sum(max(0, int(task.get("minutes", 0))) for task in tasks)
    if original_total <= 0:
        base, extra = divmod(total_minutes, len(tasks))
        return [{**task, "minutes": base + (1 if index < extra else 0)} for index, task in enumerate(tasks)]
    raw_values = [max(0, int(task.get("minutes", 0))) * total_minutes / original_total for task in tasks]
    minutes = [max(1, int(value)) for value in raw_values] if total_minutes >= len(tasks) else [0] * len(tasks)
    while sum(minutes) < total_minutes:
        index = max(range(len(tasks)), key=lambda i: raw_values[i] - minutes[i])
        minutes[index] += 1
    while sum(minutes) > total_minutes:
        candidates = [i for i, value in enumerate(minutes) if value > (1 if total_minutes >= len(tasks) else 0)]
        if not candidates:
            break
        index = max(candidates, key=lambda i: minutes[i] - raw_values[i])
        minutes[index] -= 1
    return [{**task, "minutes": minutes[index]} for index, task in enumerate(tasks)]


def start_timer():
    timer = timer_state()
    if not timer.get("running"):
        timer["running"] = True
        timer["started_at"] = time.time()


def pause_timer():
    timer = timer_state()
    if timer.get("running") and timer.get("started_at"):
        timer["elapsed_before_pause"] = elapsed_timer_seconds(timer)
    timer["running"] = False
    timer["started_at"] = None


def current_timer_task(plan, timer):
    if not plan:
        return 0, {"name": "分析问题", "label": "分析", "minutes": 0}
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1)
    return current_index, plan[current_index]


def advance_timer_task(state, reason="auto"):
    plan = active_time_plan(state)
    timer = timer_state()
    current_index, current_task = current_timer_task(plan, timer)
    if not plan:
        return None
    next_index = min(current_index + 1, len(plan) - 1)
    timer["completed_tasks"] = min(max(int(timer.get("completed_tasks", 0)), current_index + 1), len(plan))
    timer["current_task_index"] = next_index
    timer.pop("overtime_notice_key", None)
    if timer["completed_tasks"] >= len(plan):
        pause_timer()
    elif not timer.get("running"):
        start_timer()
    return {
        "completed_task": current_task["name"],
        "next_task": plan[next_index]["name"],
        "reason": reason,
        "all_done": timer["completed_tasks"] >= len(plan),
    }


def sync_timer_task_from_learning_step(state, metadata=None):
    if not has_estimated_time_plan(state):
        return None
    plan = active_time_plan(state)
    if not plan:
        return None
    step = state.get("learning_step")
    target_index = LEARNING_STEP_TASK_INDEX.get(step)
    if target_index is None:
        return None

    timer = timer_state()
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1)
    target_index = min(target_index, len(plan) - 1)
    if target_index <= current_index:
        return None

    timer["completed_tasks"] = max(int(timer.get("completed_tasks", 0)), target_index)
    timer["current_task_index"] = target_index
    timer.pop("overtime_notice_key", None)
    if metadata is not None:
        metadata["timer_synced_to_learning_step"] = step
        metadata["rerun_after_timer_update"] = True
    return {"from": current_index, "to": target_index, "step": step}


def reset_timer():
    st.session_state["timer_state"] = {
        "running": False,
        "started_at": None,
        "elapsed_before_pause": 0.0,
        "current_task_index": 0,
        "completed_tasks": 0,
    }


def reset_time_plan_session():
    st.session_state.pop("manual_time_plan", None)
    st.session_state.pop("time_plan_estimated", None)
    st.session_state["time_plan_version"] = int(st.session_state.get("time_plan_version", 0)) + 1
    for key in list(st.session_state.keys()):
        if str(key).startswith(f"{TIME_PLAN_WIDGET_PREFIX}_"):
            st.session_state.pop(key, None)


def sync_timer_from_metadata(metadata):
    if metadata.get("time_plan"):
        state = student_state()
        set_active_time_plan(state, metadata["time_plan"])
        reset_timer()
    if metadata.get("reset_timer"):
        reset_timer()
    if metadata.get("start_timer") and not metadata.get("delay_timer_start"):
        start_timer()
    if metadata.get("pause_timer") or metadata.get("complete_timer"):
        pause_timer()
    if metadata.get("complete_timer"):
        timer = timer_state()
        timer["completed_tasks"] = len(DEFAULT_TIME_PLAN)
    if metadata.get("remaining_replan"):
        state = student_state()
        plan = active_time_plan(state)
        timer = timer_state()
        current_index = min(int(metadata.get("replan_current_index", 0)), max(len(plan) - 1, 0))
        completed = min(int(metadata.get("replan_completed_tasks", current_index)), len(plan))
        timer["current_task_index"] = current_index
        timer["completed_tasks"] = completed
        timer["elapsed_before_pause"] = sum(task["minutes"] for task in plan[:current_index]) * 60
        timer["started_at"] = time.time() if timer.get("running") else None
        timer.pop("overtime_notice_key", None)


def sync_reflection_from_metadata(state, metadata):
    if state.get("learning_step") != "self_evaluation" and not metadata.get("reflection_available"):
        return
    try:
        metadata["reflection"] = get_reflection_session_payload(state)
        metadata["reflection_available"] = True
    except Exception as exc:
        metadata["reflection_available"] = False
        metadata["reflection_error"] = str(exc)


def update_manual_plan(state, plan):
    edited_plan = []
    cols = st.columns(2, gap="small")
    version = int(st.session_state.get("time_plan_version", 0))
    for idx, task in enumerate(plan):
        with cols[idx % 2]:
            minutes = st.number_input(
                task["label"],
                min_value=0,
                max_value=60,
                value=int(task["minutes"]),
                step=1,
                key=f"{TIME_PLAN_WIDGET_PREFIX}_{version}_{idx}_{task['label']}",
            )
        edited_plan.append({**task, "minutes": int(minutes)})
    st.session_state["manual_time_plan"] = edited_plan
    if not same_minutes(edited_plan, DEFAULT_TIME_PLAN):
        st.session_state["time_plan_estimated"] = True
        state["time_plan"] = edited_plan
    return edited_plan

def render_timer_panel(state):
    plan = active_time_plan(state)
    timer = timer_state()
    estimated_plan = has_estimated_time_plan(state)
    current_index = min(int(timer.get("current_task_index", 0)), len(plan) - 1) if plan else 0
    current_task = plan[current_index]["name"] if plan else "分析问题"
    remaining = current_task_remaining_seconds(plan, timer) if estimated_plan else remaining_timer_seconds(plan, timer)
    completed = min(int(timer.get("completed_tasks", 0)), len(plan)) if plan else 0
    progress = completed / len(plan) if plan else 0
    timer_mount_id = (
        "peer-timer-"
        f"{int(st.session_state.get('time_plan_version', 0))}-"
        f"{current_index}-"
        f"{int(timer.get('completed_tasks', 0))}"
    )

    # ---- 当前任务 ----
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:2px;">
            <span style="color:#8b909b; font-size:0.85rem;">当前任务</span>
            <span style="font-size:1.2rem; font-weight:700; color:#2f3340;">{current_task}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- 剩余时间 ----
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin:4px 0 10px 0;">
            <span style="color:#8b909b; font-size:0.85rem;">剩余时间</span>
            <span id="{timer_mount_id}" style="font-size:2.2rem; font-weight:800; color:#f45f5f; line-height:1.2;">{format_seconds(remaining)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_browser_countdown(timer_mount_id, remaining, bool(timer.get("running")))

    # ---- 任务时间输入（四列并排） ----
    labels = ["分析", "算法", "编程", "优化"]
    keys = ["分析问题", "设计算法", "编写程序", "代码优化"]
    current_minutes = [task["minutes"] for task in plan] if plan else [3, 3, 7, 7]

    cols = st.columns(4, gap="small")
    new_minutes = []
    for idx, (col, label, key) in enumerate(zip(cols, labels, keys)):
        with col:
            val = st.number_input(
                label,
                min_value=0,
                max_value=60,
                value=current_minutes[idx] if idx < len(current_minutes) else 3,
                step=1,
                key=f"time_plan_{key}_{st.session_state.get('time_plan_version', 0)}",
            )
            new_minutes.append(int(val))

    # 更新计划（如果发生变化则重置计时器）
    updated_plan = [
        {"name": keys[0], "label": labels[0], "minutes": new_minutes[0]},
        {"name": keys[1], "label": labels[1], "minutes": new_minutes[1]},
        {"name": keys[2], "label": labels[2], "minutes": new_minutes[2]},
        {"name": keys[3], "label": labels[3], "minutes": new_minutes[3]},
    ]
    if not same_minutes(updated_plan, plan):
        set_active_time_plan(state, updated_plan)
        reset_timer()  # 计划改变，重置计时器
        st.rerun()     # 立即刷新显示

    # ---- 总计提示 ----
    total = sum(new_minutes)
    remaining_total = sum(new_minutes[current_index:]) if current_index > 0 else total
    expected_remaining = state.get("overtime_remaining_minutes")
    if current_index > 0 and expected_remaining is not None:
        if remaining_total == int(expected_remaining):
            st.caption(f"剩余任务总计 {remaining_total} 分钟，同伴按新的剩余计划倒计时。")
        else:
            st.warning(f"剩余任务当前总计 {remaining_total} 分钟，应调整为 {expected_remaining} 分钟。")
    elif total == 20:
        st.caption("总计 20 分钟，同伴按计划倒计时。")
    else:
        st.warning(f"当前总计 {total} 分钟，建议调整为 20 分钟。")

    # ---- 任务完成率进度条 ----
    progress_percent = int(progress * 100)
    st.progress(progress, text=f"任务完成率 {progress_percent}%")

    # ---- 操作按钮 ----
    btn_cols = st.columns(2, gap="small")
    with btn_cols[0]:
        if timer.get("running"):
            if st.button("⏸️ 暂停计时", use_container_width=True):
                pause_timer()
                st.rerun()
        else:
            if st.button("▶️ 开始计时", use_container_width=True):
                start_timer()
                st.rerun()
    with btn_cols[1]:
        if st.button("⏩ 进入下一任务", type="primary", use_container_width=True):
            advance_timer_task(state, reason="manual")
            st.rerun()

    # ---- 调试次数显示（新增） ----
    st.metric("🐞 代码调试次数", int(state.get("debug_count", 0)))



def render_peer_monitor_area(state):
    with st.container(key="peer_monitor_fixed"):
        st.markdown(f"<div class='peer-monitor-title'>{PEER_MONITOR_TITLE}</div>", unsafe_allow_html=True)
        render_timer_panel(state)


@st.cache_data
def load_avatar_svg(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def chat_avatar(role, agent=None):
    path = CHAT_AVATARS["user"] if role == "user" else CHAT_AVATARS.get(agent)
    if path:
        svg = load_avatar_svg(path)
        if svg:
            return svg
    return ":material/smart_toy:"


def looks_like_inline_python_code(line):
    return (
        "print(" in line
        and line.count("print(") >= 2
        and ("input(" in line or " if " in line or " elif " in line or " else:" in line)
    )


def format_inline_python_code(line):
    normalized = re.sub(
        r"\s+(?=(?:print\(|[A-Za-z_]\w*\s*=\s*input\(|if\s+|elif\s+|else:|for\s+|while\s+))",
        "\n",
        line.strip(),
    )
    formatted_lines = []
    indent_next = 0
    for raw_line in normalized.splitlines():
        code_line = raw_line.strip()
        if not code_line:
            continue
        if re.match(r"^(elif\b|else:)", code_line):
            indent_next = 0
        formatted_lines.append(" " * indent_next + code_line)
        if re.match(r"^(if\b|elif\b|else:|for\b|while\b)", code_line) and code_line.endswith(":"):
            indent_next = 4
    return "```python\n" + "\n".join(formatted_lines) + "\n```"


def format_ai_message(message):
    if "```" in message:
        return message
    lines = []
    for line in (message or "").splitlines():
        if looks_like_inline_python_code(line):
            lines.append(format_inline_python_code(line))
        else:
            lines.append(line)
    return format_quiz_layout("\n".join(lines).strip())


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
        text = re.sub(r"\n{3,}", "\n\n", text)
        formatted_parts.append(text)
    formatted = "".join(formatted_parts).strip()
    formatted = re.sub(r"(?m)^\s*题目\s*(\d+)\s*[（(]\s*(?:单选|判断)\s*[）)]\s*", r"\1. ", formatted)
    formatted = re.sub(r"(?m)^(\d+\.\s*[^\n]+)\n(?=[A-D][.．、)）])", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^(\d+\.\s*[^\n]+)\n(?=（回答)", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^([A-D][.．、)）]\s*[^\n]+)\n(?=[A-D][.．、)）])", r"\1\n\n", formatted)
    formatted = re.sub(r"(?m)^([A-D][.．、)）]\s*[^\n]+)\n(?=\d+\.\s*)", r"\1\n\n", formatted)
    return re.sub(r"\n{4,}", "\n\n", formatted).strip()


def parse_flowchart_message(message):
    lines = [line.strip() for line in re.split(r"\n+", str(message or "")) if line.strip()]
    marker_index = next((index for index, line in enumerate(lines) if re.match(r"^挖空流程图[：:]", line)), -1)
    if marker_index < 0:
        return None

    nodes = []
    after_index = len(lines)
    for index in range(marker_index + 1, len(lines)):
        line = lines[index]
        if re.match(r"^[↓→-]+$", line):
            continue
        if re.match(r"^(请回答|请按|如果你|如果当前|学生回答)", line):
            after_index = index
            break
        branch_match = re.match(r"^[├└]─\s*([^→]+?)\s*→\s*（([^）]+)）\s*(.+)$", line)
        if branch_match:
            nodes.append(
                {
                    "type": "branch",
                    "label": branch_match.group(1).strip(),
                    "shape": branch_match.group(2),
                    "text": branch_match.group(3),
                }
            )
            continue
        match = re.match(r"^（([^）]+)）\s*(.+)$", line)
        if match:
            nodes.append({"type": "node", "shape": match.group(1), "text": match.group(2)})

    if len(nodes) < 2:
        return None
    return {
        "intro": "\n".join(lines[:marker_index]),
        "nodes": nodes,
        "after": "\n".join(lines[after_index:]),
    }


def flowchart_shape_class(node):
    declared_shape = node.get("shape", "")
    text = node.get("text", "")
    if re.search(r"各分支汇合|分支汇合", text):
        return "flow-node-merge"
    if re.search(r"平行四边形", declared_shape):
        return "flow-node-io"
    if re.search(r"圆角矩形", declared_shape):
        return "flow-node-terminal"
    if re.search(r"菱形", declared_shape):
        return "flow-node-decision"
    if re.search(r"矩形", declared_shape):
        return "flow-node-process"
    if re.search(r"输入|输出", text):
        return "flow-node-io"
    if re.search(r"开始|结束", text):
        return "flow-node-terminal"
    if re.search(r"判断", text):
        return "flow-node-decision"
    return "flow-node-process"


def flowchart_text_html(text):
    parts = re.split(r"(___\d+___)", str(text or ""))
    rendered = []
    for part in parts:
        if not part:
            continue
        escaped = html.escape(part)
        if re.match(r"^___\d+___$", part):
            rendered.append(f"<span class='flow-blank'>{escaped}</span>")
        else:
            rendered.append(escaped)
    return "".join(rendered)


def render_flowchart_html(message):
    flowchart = parse_flowchart_message(message)
    if not flowchart:
        return None

    parts = ["<div class='flowchart-message'>"]
    if flowchart["intro"]:
        parts.append(f"<p>{html.escape(flowchart['intro'])}</p>")
    parts.append("<div class='flowchart-diagram'>")
    index = 0
    while index < len(flowchart["nodes"]):
        node = flowchart["nodes"][index]
        if node.get("type") == "branch":
            branch_nodes = []
            while index < len(flowchart["nodes"]) and flowchart["nodes"][index].get("type") == "branch":
                branch_nodes.append(flowchart["nodes"][index])
                index += 1
            parts.append("<div class='flow-branches'>")
            for branch in branch_nodes:
                shape_class = flowchart_shape_class(branch)
                label = flowchart_text_html(branch.get("label", ""))
                text = flowchart_text_html(branch["text"])
                parts.append(
                    "<div class='flow-branch'>"
                    f"<div class='flow-branch-label'>{label}</div>"
                    f"<div class='flow-node {shape_class}'><span>{text}</span></div>"
                    "</div>"
                )
            parts.append("</div>")
            if index < len(flowchart["nodes"]):
                parts.append("<div class='flow-arrow'>↓</div>")
            continue
        shape_class = flowchart_shape_class(node)
        text = flowchart_text_html(node["text"])
        parts.append(f"<div class='flow-node {shape_class}'><span>{text}</span></div>")
        index += 1
        if index < len(flowchart["nodes"]):
            parts.append("<div class='flow-arrow'>↓</div>")
    parts.append("</div>")
    if flowchart["after"]:
        parts.append(f"<p class='flowchart-answer-hint'>{html.escape(flowchart['after'])}</p>")
    parts.append("</div>")
    return "".join(parts)


def render_chat_content(message):
    flowchart_html = render_flowchart_html(message)
    if flowchart_html:
        st.markdown(flowchart_html, unsafe_allow_html=True)
    else:
        st.markdown(message)



def plan_summary(plan):
    return "，".join(f"{task['name']}{task['minutes']}分钟" for task in plan)


def append_auto_agent_message(state, agent, trigger_message, phase):
    response = call_llm(state, agent, trigger_message)
    response = format_ai_message(clean_reply(response))
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    saved = save_interaction(
        state,
        agent,
        f"[系统自动调用] {trigger_message}",
        response,
        phase,
        {"auto_triggered": True, "trigger": trigger_message},
    )
    return {"agent": agent, "message": response, "saved": saved}


def append_fixed_agent_message(state, agent, response, phase, trigger):
    response = format_ai_message(clean_reply(response))
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    saved = save_interaction(
        state,
        agent,
        f"[系统自动提醒] {trigger}",
        response,
        phase,
        {"auto_triggered": True, "trigger": trigger},
    )
    return {"agent": agent, "message": response, "saved": saved}


def persist_auto_messages(state, metadata, position):
    key = f"{position}_messages"
    for item in metadata.get(key, []) or []:
        agent = item.get("agent", "assistant")
        message = format_ai_message(clean_reply(item.get("message", "")))
        phase = item.get("phase") or state.get("learning_phase", "")
        if not message:
            continue
        state["conversation"].append({"role": "assistant", "content": message, "agent": agent, "phase": phase})
        item["message"] = message
        item["saved"] = save_interaction(
            state,
            agent,
            f"[系统自动调用] {item.get('trigger', '智能体自动跟进')}",
            message,
            phase,
            {"auto_triggered": True, "trigger": item.get("trigger", "")},
        )


def auto_continue_after_plan_sync(state, metadata):
    if not metadata.get("plan_synced_to_peer"):
        return []

    plan = active_time_plan(state)
    summary = plan_summary(plan)
    total_minutes = sum(task["minutes"] for task in plan)
    phase = state.get("learning_phase", "IPO问题分析")

    peer_message = (
        f"助教已将学生的学习计划同步给你：{summary}，总计{total_minutes}分钟。"
        "请你作为编程同伴智能体，用两三句话确认会按这个计划监督倒计时和任务进度，"
        "不要进行IPO分析或代码指导。"
    )
    mentor_message = (
        f"学生已经完成时间分配：{summary}，总计{total_minutes}分钟。"
        "请你作为编程导师智能体，立即开始第一个任务“分析问题”，"
        "用IPO模式引导学生说出输入、处理、输出。先提问，不要直接给完整答案。"
    )

    auto_messages = [
        append_auto_agent_message(state, "peer", peer_message, phase),
        append_auto_agent_message(state, "mentor", mentor_message, phase),
    ]
    metadata["auto_messages"] = auto_messages
    metadata["mentor_auto_started"] = True
    metadata["rerun_after_plan_sync"] = True
    return auto_messages


def looks_like_task_completion(message):
    text = re.sub(r"\s+", "", message or "")
    if not text:
        return False
    if any(word in text for word in COMPLETION_WORDS):
        return True
    return bool(re.search(r"(第[一二三四1-4]个)?任务.*(完成|做完|结束)", text))


def auto_advance_after_completion(state, user_message, metadata):
    if not has_estimated_time_plan(state) or metadata.get("complete_timer"):
        return None
    if looks_like_debug_success(user_message):
        return None
    if metadata.get("learning_step_changed"):
        return None
    if not looks_like_task_completion(user_message):
        return None

    advanced = advance_timer_task(state, reason="student_completion")
    if not advanced:
        return None

    state["overtime_replan_pending"] = False
    phase = state.get("learning_phase", "任务执行")
    if advanced["all_done"]:
        state["learning_phase"] = "学习成果评价"
        state["learning_step"] = "self_evaluation"
        message = (
            f"我看到你已经完成“{advanced['completed_task']}”。四项任务都已完成，我已帮你暂停倒计时，"
            "接下来由编程助教智能体先带你进行学习成果评价。"
        )
        phase = "学习成果评价"
        metadata["complete_timer"] = True
        metadata["pause_timer"] = True
        metadata["progress"] = 100
        metadata["reflection_available"] = True
        metadata["assistant_started_reflection"] = True
        metadata["learning_step"] = "self_evaluation"
        peer_notice = append_fixed_agent_message(state, "peer", message, phase, "学生完成全部任务后自动进入反思")
        assistant_notice = append_fixed_agent_message(
            state,
            "assistant",
            assistant_reflection_start_message(),
            phase,
            "学生完成全部任务后助教发起学习评价",
        )
        metadata["auto_messages"] = [peer_notice, assistant_notice]
        metadata["timer_auto_advanced"] = True
        metadata["rerun_after_timer_update"] = True
        return assistant_notice
    else:
        message = (
            f"我看到你已经完成“{advanced['completed_task']}”，已自动帮你进入下一任务："
            f"“{advanced['next_task']}”。继续保持节奏，我会在右侧帮你看着时间。"
        )
    metadata["timer_auto_advanced"] = True
    metadata["rerun_after_timer_update"] = True
    return append_fixed_agent_message(state, "peer", message, phase, "学生完成任务后自动进入下一任务")


def maybe_prompt_overtime(state):
    plan = active_time_plan(state)
    timer = timer_state()
    if not has_estimated_time_plan(state) or not plan or not timer.get("running"):
        return None

    current_index, current_task = current_timer_task(plan, timer)
    completed = int(timer.get("completed_tasks", 0))
    if completed > current_index or current_task_remaining_seconds(plan, timer) > 0:
        return None

    notice_key = f"{int(st.session_state.get('time_plan_version', 0))}:{current_index}:{completed}"
    if timer.get("overtime_notice_key") == notice_key:
        return None

    pause_timer()
    timer = timer_state()
    timer["overtime_notice_key"] = notice_key
    state["overtime_replan_pending"] = True
    spent_tasks = plan[: current_index + 1]
    spent_minutes = sum(task["minutes"] for task in spent_tasks)
    remaining_budget = max(0, sum(task["minutes"] for task in plan) - spent_minutes)
    remaining_tasks = plan[current_index:]
    suggested_tasks = distribute_remaining_minutes(remaining_tasks, remaining_budget)
    remaining_summary = "，".join(f"{task['name']}{task['minutes']}分钟" for task in suggested_tasks)
    spent_summary = "，".join(f"{task['name']}{task['minutes']}分钟" for task in spent_tasks)
    state["overtime_current_index"] = current_index
    state["overtime_completed_tasks"] = current_index
    state["overtime_remaining_minutes"] = remaining_budget
    state["overtime_remaining_task_names"] = [task["name"] for task in remaining_tasks]
    message = (
        f"“{current_task['name']}”的预估时间已经用完了。你现在完成了吗？\n\n"
        "如果已经完成，请直接回复“已完成”，我会自动帮你进入下一任务。\n\n"
        f"如果还没有完成，需要重新分配剩余学习时间。当前已经用掉：{spent_summary}，"
        f"所以剩余总时间是{remaining_budget}分钟。"
        f"请只给“{current_task['name']}”和后续任务分配这{remaining_budget}分钟，例如：{remaining_summary}。"
    )
    return append_fixed_agent_message(state, "peer", message, state.get("learning_phase", "任务执行"), "当前任务超时")


def maybe_refresh_running_timer(state):
    plan = active_time_plan(state)
    timer = timer_state()
    if maybe_prompt_overtime(state):
        st.rerun()
    remaining = remaining_timer_seconds(plan, timer)
    if timer.get("running") and remaining <= 0:
        pause_timer()
        st.rerun()


def handle_chat(message, explicit_agent):
    state = student_state()
    prepare_step_for_prompt(state, message)
    agent = route_agent(message, state, explicit_agent)
    if agent == "manager":
        response = manager_refusal()
        phase = state.get("learning_phase", "准备")
        metadata = {"rejected_by_manager": True}
    else:
        response = call_llm(state, agent, message)
        response, phase, metadata = decorate_message(state, agent, response, message)
        response = maybe_append_auto_followup(state, agent, response, metadata)
        response = clean_reply(response)
        response = format_ai_message(response)
        metadata["routed_by_manager"] = True

    if metadata.get("plan_synced_to_peer") and metadata.get("start_timer"):
        metadata["delay_timer_start"] = True
    sync_timer_from_metadata(metadata)
    state["conversation"].append({"role": "user", "content": message})
    persist_auto_messages(state, metadata, "before")
    state["conversation"].append({"role": "assistant", "content": response, "agent": agent, "phase": phase})
    persist_auto_messages(state, metadata, "after")
    auto_continue_after_plan_sync(state, metadata)
    auto_advance_after_completion(state, message, metadata)
    sync_timer_task_from_learning_step(state, metadata)
    sync_reflection_from_metadata(state, metadata)
    if metadata.pop("delay_timer_start", False):
        start_timer()
    metadata["saved"] = save_interaction(state, agent, message, response, phase, metadata)
    return agent, response, phase, metadata


def render_streamlit_reflection_panel(state):
    if state.get("learning_step") != "self_evaluation" and not state.get("reflection_current_step"):
        return
    try:
        payload = get_reflection_session_payload(state)
    except Exception as exc:
        st.error(f"反思数据加载失败：{exc}")
        return

    current_step = payload["currentStep"]
    labels = payload["stepLabels"]
    draft = payload.get("draft", {})
    context = payload.get("context", {})
    steps = payload["steps"]
    progress = (steps.index(current_step) + 1) / len(steps) if current_step in steps else 0

    st.subheader("反思阶段")
    st.progress(progress, text=labels.get(current_step, current_step))

    if current_step == "OUTCOME_SELF_EVALUATION":
        st.caption("评价依据")
        st.write("学习目标：", context.get("learningGoal", {}))
        st.write("任务要求：", context.get("taskRequirement", {}))
        st.json(context.get("rubric", []), expanded=False)
        current = draft.get("OUTCOME_SELF_EVALUATION", {})
        task_completion = st.selectbox("你的程序实现了任务要求的功能吗？", ["", "已完成", "部分完成", "还没有完成"], index=["", "已完成", "部分完成", "还没有完成"].index(current.get("taskCompletion", "")) if current.get("taskCompletion", "") in ["", "已完成", "部分完成", "还没有完成"] else 0)
        tested = st.selectbox("你有没有使用不同的数据测试程序？", ["", "有", "没有"], index=["", "有", "没有"].index(current.get("testedDifferentData", "")) if current.get("testedDifferentData", "") in ["", "有", "没有"] else 0)
        runtime = st.selectbox("不同输入下运行结果符合预期吗？", ["", "符合", "不确定", "不符合"], index=["", "符合", "不确定", "不符合"].index(current.get("runtimeCorrectness", "")) if current.get("runtimeCorrectness", "") in ["", "符合", "不确定", "不符合"] else 0)
        logic = st.selectbox("检查过判断条件、冒号和缩进吗？", ["", "检查过", "还没有"], index=["", "检查过", "还没有"].index(current.get("programLogic", "")) if current.get("programLogic", "") in ["", "检查过", "还没有"] else 0)
        quality = st.selectbox("代码格式和变量命名基本清楚吗？", ["", "基本规范", "还需要整理"], index=["", "基本规范", "还需要整理"].index(current.get("codeQuality", "")) if current.get("codeQuality", "") in ["", "基本规范", "还需要整理"] else 0)
        if st.button("保存自评", key="reflection_outcome_self"):
            if not all([task_completion, tested, runtime, logic, quality]):
                st.warning("请先完成自评问题。")
            else:
                save_reflection_step(state, "OUTCOME_SELF_EVALUATION", {"taskCompletion": task_completion, "testedDifferentData": tested, "runtimeCorrectness": runtime, "programLogic": logic, "codeQuality": quality})
                st.rerun()
    elif current_step == "OUTCOME_AGENT_EVALUATION":
        st.caption("助教成果评价")
        st.json(context.get("outcomeEvaluation", {}), expanded=False)
        if st.button("保存助教评价并继续", key="reflection_outcome_agent"):
            save_reflection_step(state, "OUTCOME_AGENT_EVALUATION", {})
            st.rerun()
    elif current_step == "OUTCOME_CONFIRMATION":
        st.caption("学生确认成果评价记录")
        st.json(context.get("outcomeComparison", {}), expanded=False)
        final_eval = st.text_area("我的最终成果评价", value=draft.get("OUTCOME_CONFIRMATION", {}).get("studentFinalEvaluation", ""))
        next_action = st.selectbox("下一步", ["continue_reflection", "return_to_debug"])
        if st.button("保存成果记录", key="reflection_outcome_confirm"):
            result = save_reflection_step(state, "OUTCOME_CONFIRMATION", {"studentFinalEvaluation": final_eval, "nextAction": next_action})
            if result.get("returnedToDebug"):
                st.info(result["message"])
            st.rerun()
    elif current_step == "REFLECTION_PROCESS_REVIEW":
        st.caption("过程回顾")
        st.json(context.get("processSummary", {}), expanded=False)
        cues = context.get("problemCues", [])
        selected = st.selectbox("最值得反思的问题", [""] + [cue["description"] for cue in cues])
        extra = st.text_area("我补充的问题")
        if st.button("保存问题选择", key="reflection_process_review"):
            if not selected and not extra:
                st.warning("请选择或写下一个问题。")
            else:
                save_reflection_step(state, "REFLECTION_PROCESS_REVIEW", {"selectedProblem": selected, "extraProblem": extra})
                st.rerun()
    elif current_step == "REFLECTION_CAUSE_ANALYSIS":
        process = draft.get("REFLECTION_PROCESS_REVIEW", {})
        problem = process.get("selectedProblem") or process.get("extraProblem") or "主要问题"
        cause = st.selectbox("可能原因方向", ["知识掌握", "程序设计思路", "调试方法", "时间安排", "注意力或情绪", "其他"])
        evidence = st.text_area("具体表现或学习记录")
        confirmed = st.checkbox("我确认这是主要原因之一")
        if st.button("保存原因分析", key="reflection_cause"):
            if not confirmed or len(evidence.strip()) < 8:
                st.warning("请写一个具体表现，并确认这是主要原因之一。")
            else:
                save_reflection_step(state, "REFLECTION_CAUSE_ANALYSIS", {"studentSelectedCause": cause, "studentEvidence": evidence, "studentConfirmed": confirmed, "confirmedCauses": [{"problem": problem, "selectedCause": cause, "studentEvidence": evidence, "studentConfirmed": confirmed}]})
                st.rerun()
    elif current_step == "REFLECTION_EXPERIENCE_SUMMARY":
        strategies = st.multiselect("这次有效的方法", ["先做IPO分析再写代码", "先画流程图再写代码", "使用不同测试数据", "每次只修改一个错误", "根据时间提醒调整进度", "主动寻求帮助"])
        extra = st.text_area("我补充的有效方法")
        if st.button("保存有效经验", key="reflection_experience"):
            if extra:
                strategies.append(extra)
            if not strategies:
                st.warning("请至少确认一种有效方法。")
            else:
                save_reflection_step(state, "REFLECTION_EXPERIENCE_SUMMARY", {"effectiveStrategies": strategies, "extraStrategy": extra})
                st.rerun()
    elif current_step == "REFLECTION_IMPROVEMENT_PLAN":
        action = {}
        action["relatedProblem"] = st.text_input("针对的问题")
        action["relatedCause"] = st.text_input("相关原因")
        action["action"] = st.text_area("下一次具体行动")
        action["verification"] = st.text_area("如何判断有效")
        action["nextUseContext"] = st.text_input("准备在哪个环节使用")
        validation = validate_improvement_actions([action])
        if st.button("保存改进方案", key="reflection_improve"):
            if not validation["ok"]:
                st.warning("改进方案还不够具体，请补齐问题、行动、判断标准和使用场景。")
            else:
                save_reflection_step(state, "REFLECTION_IMPROVEMENT_PLAN", {"actions": [action]})
                st.rerun()
    elif current_step == "REFLECTION_COMPLETE":
        if payload.get("session", {}).get("status") == "completed":
            st.success("学习反思记录已经保存。")
            return
        st.caption("确认前预览")
        st.json(payload.get("draft", {}), expanded=False)
        confirmed = st.checkbox("我确认生成正式反思记录")
        if st.button("确认并保存反思", type="primary", key="reflection_report"):
            if not confirmed:
                st.warning("需要你主动确认后才能保存正式反思记录。")
            else:
                save_final_report(state, {"studentConfirmed": True})
                st.rerun()
    else:
        st.success("学习反思记录已经保存。下一轮计划时会读取这次的改进措施。")


def render_student_page():
    state = student_state()
    inject_student_page_styles()
    st.title("编程自主学习伙伴")

    with st.sidebar:
        st.subheader("学习状态")
        name = st.text_input("学生姓名", value=state.get("student_name", ""), max_chars=30)
        state["student_name"] = name.strip()
        st.metric("当前阶段", state.get("learning_phase", "主题作品体验"))
        selected_agent = st.selectbox("智能体", list(agent_options().keys()), index=0)
        if st.button("🔄重新开始学习", use_container_width=True):
            st.session_state.pop("student_state", None)
            reset_time_plan_session()
            reset_timer()
            st.rerun()

    if not os.getenv("DEEPSEEK_API_KEY"):
        st.warning("尚未配置 DeepSeek API Key。部署到 Streamlit 后，请在 App Secrets 中设置 DEEPSEEK_API_KEY。")

    chat_col, monitor_col = st.columns([2.2, 1.45], gap="large")

    prompt = st.chat_input("输入你的编程学习问题")
    if prompt:
        with chat_col:
            with st.spinner("智能体正在思考..."):
                _, _, _, metadata = handle_chat(prompt.strip(), agent_options()[selected_agent])
                if metadata.get("rerun_after_plan_sync") or metadata.get("rerun_after_timer_update"):
                    st.rerun()
        st.rerun()

    with chat_col:
        with st.container(key="chat_scroll_area"):
            for item in state.get("conversation", []):
                with st.chat_message(item["role"], avatar=chat_avatar(item["role"], item.get("agent"))):
                    if item["role"] == "assistant" and item.get("agent"):
                        st.caption(agent_notice(item["agent"]))
                    render_chat_content(item["content"])

    with monitor_col:
        render_peer_monitor_area(state)
        render_streamlit_reflection_panel(state)

    maybe_refresh_running_timer(state)


def save_uploaded_file(uploaded_file):
    if not uploaded_file:
        return False, "请选择要上传的资料。"
    if not allowed_file(uploaded_file.name):
        return False, "文件类型不支持，请上传 pdf、ppt、pptx、doc、docx、txt 或 md。"

    content = uploaded_file.getvalue()
    if not content:
        return False, "上传文件为空，请检查文件内容。"

    original = secure_name(uploaded_file.name)
    ext = original.rsplit(".", 1)[1].lower()
    saved = f"{int(time.time())}_{uuid4().hex}.{ext}"
    upload_dir = choose_upload_dir()
    saved_path = upload_dir / saved
    saved_path.write_bytes(content)

    try:
        knowledge_summary = build_knowledge_summary(extract_text(saved_path))
    except Exception as exc:
        knowledge_summary = f"暂未提取到可读文本，请根据文件名和学生题干判断知识点。提取错误：{exc}"

    execute(
        """
        INSERT INTO knowledge_files
        (original_name, saved_name, file_type, knowledge_summary, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (original, saved, ext, knowledge_summary, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    return True, f"已上传：{original}"


def interactions_as_json():
    rows = db_rows("SELECT * FROM interactions ORDER BY created_at ASC")
    return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")


def interactions_as_csv():
    rows = db_rows("SELECT * FROM interactions ORDER BY created_at ASC")
    output = StringIO()
    fieldnames = [
        "id",
        "session_id",
        "student_name",
        "agent",
        "user_message",
        "assistant_message",
        "phase",
        "metadata",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def render_login():
    st.subheader("教师登录")
    with st.form("teacher_login"):
        username = st.text_input("账号")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录", use_container_width=True)
    if submitted:
        expected_username = os.getenv("TEACHER_USERNAME", "teacher")
        expected_password = os.getenv("TEACHER_PASSWORD", "123456")
        if username == expected_username and password == expected_password:
            st.session_state["teacher_logged_in"] = True
            st.rerun()
        st.error("账号或密码不正确。")


def render_teacher_page():
    if not st.session_state.get("teacher_logged_in"):
        render_login()
        return

    st.title("教师端")
    if st.button("退出登录"):
        st.session_state["teacher_logged_in"] = False
        st.rerun()

    upload_col, data_col = st.columns([1, 1])
    with upload_col:
        st.subheader("知识库")
        uploaded_file = st.file_uploader("上传资料", type=["pdf", "ppt", "pptx", "doc", "docx", "txt", "md"])
        if st.button("保存到知识库", type="primary", use_container_width=True):
            try:
                ok, message = save_uploaded_file(uploaded_file)
                st.success(message) if ok else st.error(message)
            except Exception as exc:
                st.error(f"上传失败：{exc}")

        files = existing_upload_rows()
        if files:
            st.dataframe(
                [{k: row[k] for k in ["id", "original_name", "file_type", "uploaded_at"]} for row in files],
                use_container_width=True,
                hide_index=True,
            )
            file_id = st.selectbox("选择要删除的文件", [row["id"] for row in files], format_func=lambda value: next(row["original_name"] for row in files if row["id"] == value))
            if st.button("删除所选文件", use_container_width=True):
                delete_knowledge_file(file_id)
                st.rerun()
        else:
            st.info("暂无知识库文件。")

    with data_col:
        st.subheader("学习数据")
        rows = db_rows("SELECT * FROM interactions ORDER BY created_at DESC LIMIT 50")
        st.download_button("下载 CSV", interactions_as_csv(), file_name="interactions.csv", mime="text/csv", use_container_width=True)
        st.download_button("下载 JSON", interactions_as_json(), file_name="interactions.json", mime="application/json", use_container_width=True)
        if st.button("清空学习数据和知识库", use_container_width=True):
            clear_data()
            st.rerun()
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("暂无学习记录。")

def delete_knowledge_file(file_id):
    rows = db_rows("SELECT * FROM knowledge_files WHERE id = ?", (file_id,))
    if not rows:
        return
    row = rows[0]
    upload_path = find_upload_file(row["saved_name"])
    if upload_path:
        upload_path.unlink(missing_ok=True)
    execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))


def clear_data():
    execute("DELETE FROM interactions")
    execute("DELETE FROM knowledge_files")
    execute("DELETE FROM reflection_improvement_actions")
    execute("DELETE FROM reflection_reports")
    execute("DELETE FROM reflection_step_data")
    execute("DELETE FROM reflection_sessions")
    execute("DELETE FROM learning_runs")
    for path in iter_upload_files():
        try:
            path.unlink()
        except OSError:
            pass
    st.session_state.pop("student_state", None)


def main():
    initialize_app()
    page = st.sidebar.radio("页面", ["学生端", "教师端"], horizontal=True)
    if page == "学生端":
        render_student_page()
    else:
        render_teacher_page()


if __name__ == "__main__":
    main()
