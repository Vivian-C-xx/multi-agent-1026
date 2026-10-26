const chatLog = document.querySelector("#chatLog");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const chips = document.querySelectorAll(".agent-chip");
const studentName = document.querySelector("#studentName");
const activeAgentName = document.querySelector("#activeAgentName");
const timerTask = document.querySelector("#timerTask");
const timerClock = document.querySelector("#timerClock");
const debugCount = document.querySelector("#debugCount");
const progressText = document.querySelector("#progressText");
const progressBar = document.querySelector("#progressBar");
const pauseTimerButton = document.querySelector("#pauseTimer");
const nextTaskButton = document.querySelector("#nextTask");
const timePlanHint = document.querySelector("#timePlanHint");
const reflectionPanel = document.querySelector("#reflectionPanel");
const reflectionBody = document.querySelector("#reflectionBody");
const reflectionStepText = document.querySelector("#reflectionStepText");
const reflectionProgressText = document.querySelector("#reflectionProgressText");
const reflectionProgressBar = document.querySelector("#reflectionProgressBar");
const reflectionError = document.querySelector("#reflectionError");
const reflectionBackButton = document.querySelector("#reflectionBack");
const reflectionSaveButton = document.querySelector("#reflectionSave");

let timer = null;
let timerStarted = false;
let taskIndex = 0;
const TOTAL_SECONDS = 20 * 60;
let secondsLeft = TOTAL_SECONDS;
let tasks = readTasks();
let activeTasks = null;
let reflectionState = null;
let reflectionSaving = false;

const agentLabels = [
  "编程自主学习管家",
  "编程助教智能体",
  "编程导师智能体",
  "编程同伴智能体",
];

function readTasks() {
  return [...document.querySelectorAll(".time-inputs input")].map((input) => ({
    name: input.dataset.task,
    minutes: Math.max(1, Number(input.value || 1)),
  }));
}

function totalPlannedMinutes() {
  return (activeTasks || readTasks()).reduce((sum, task) => sum + task.minutes, 0);
}

function renderTimePlanHint() {
  const total = totalPlannedMinutes();
  if (!timePlanHint) return;
  timePlanHint.textContent = `当前总计 ${total} 分钟，同伴会按这个计划倒计时。`;
  timePlanHint.classList.toggle("warning", total !== 20);
}

function setActiveAgent(agent) {
  chips.forEach((chip) => chip.classList.toggle("active", chip.dataset.agent === agent));
}

function addMessage(role, text, agent = "") {
  const node = document.createElement("div");
  node.className = `message ${role} ${agent}`;
  if (role === "user") {
    node.textContent = text;
  } else {
    const title = document.createElement("strong");
    title.textContent = agentName(agent);
    const body = renderBotMessageBody(stripAgentLabels(text));
    node.append(title, body);
  }
  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function normalizeQuizText(text) {
  return String(text || "")
    .replace(/(^|\n)\s*题目\s*(\d+)\s*[（(]\s*(?:单选|判断)\s*[）)]\s*/g, "$1$2. ")
    .replace(/\s+([A-D][.．、)）])\s*/g, "\n$1 ")
    .replace(/(（回答[“"']?对[”"']?或[“"']?错[”"']?）)/g, "\n$1")
    .replace(/(^|\n)(\d+\.\s*[^\n]+)\n(?=[A-D][.．、)）])/g, "$1$2\n\n")
    .replace(/(^|\n)(\d+\.\s*[^\n]+)\n(?=（回答)/g, "$1$2\n\n")
    .replace(/(^|\n)([A-D][.．、)）]\s*[^\n]+)\n(?=[A-D][.．、)）])/g, "$1$2\n\n")
    .replace(/(^|\n)([A-D][.．、)）]\s*[^\n]+)\n(?=\d+\.\s*)/g, "$1$2\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const reportSectionConfig = [
  { label: "完成目标", aliases: ["完成目标", "目标完成", "学习目标"], icon: "目" },
  { label: "自评分数", aliases: ["自评分数", "自评得分", "自我评价"], icon: "分" },
  { label: "主要问题", aliases: ["主要问题", "主要困难", "需要改进"], icon: "问" },
  { label: "改进计划", aliases: ["改进计划", "改进方案", "下一次行动"], icon: "改" },
  { label: "老师建议", aliases: ["老师建议", "助教建议", "学习建议"], icon: "建" },
  { label: "请你确认", aliases: ["请你确认", "确认方式", "确认"], icon: "认" },
];

function reportLabelPattern() {
  return reportSectionConfig
    .flatMap((section) => section.aliases)
    .map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
}

function extractReportSections(text) {
  const normalized = String(text || "")
    .replace(new RegExp(`\\s*(${reportLabelPattern()})\\s*[：:]`, "g"), "\n$1：")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  if (!/学习报告|报告摘要|个人报告/.test(normalized)) return null;
  const labelRegex = new RegExp(`(${reportLabelPattern()})\\s*[：:]`, "g");
  const matches = [...normalized.matchAll(labelRegex)];
  if (matches.length < 2) return null;
  const intro = normalized.slice(0, matches[0].index).trim();
  const sections = matches.map((match, index) => {
    const rawLabel = match[1];
    const start = match.index + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : normalized.length;
    const config = reportSectionConfig.find((item) => item.aliases.includes(rawLabel)) || reportSectionConfig[0];
    return {
      label: config.label,
      icon: config.icon,
      content: normalized.slice(start, end).trim(),
    };
  }).filter((section) => section.content);
  return sections.length ? { intro, sections } : null;
}

function renderLearningReport(text) {
  const report = extractReportSections(text);
  if (!report) return null;
  const wrapper = document.createElement("div");
  wrapper.className = "learning-report";
  if (report.intro) {
    const intro = document.createElement("p");
    intro.className = "report-intro";
    intro.textContent = report.intro;
    wrapper.appendChild(intro);
  }
  report.sections.forEach((section) => {
    const item = document.createElement("div");
    item.className = "report-section";
    const icon = document.createElement("span");
    icon.className = "report-icon";
    icon.textContent = section.icon;
    const content = document.createElement("div");
    content.className = "report-content";
    const title = document.createElement("strong");
    title.textContent = section.label;
    const body = document.createElement("p");
    body.textContent = section.content;
    content.append(title, body);
    item.append(icon, content);
    wrapper.appendChild(item);
  });
  return wrapper;
}

function parseFlowchartMessage(text) {
  const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const markerIndex = lines.findIndex((line) => /^挖空流程图[：:]/.test(line));
  if (markerIndex < 0) return null;
  const nodes = [];
  let afterIndex = lines.length;
  for (let index = markerIndex + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^[↓→-]+$/.test(line)) continue;
    if (/^(请回答|请按|如果你|如果当前|学生回答)/.test(line)) {
      afterIndex = index;
      break;
    }
    const branchMatch = line.match(/^[├└]─\s*([^→]+?)\s*→\s*（([^）]+)）\s*(.+)$/);
    if (branchMatch) {
      nodes.push({
        type: "branch",
        label: branchMatch[1].trim(),
        shape: branchMatch[2],
        text: branchMatch[3],
      });
      continue;
    }
    const match = line.match(/^（([^）]+)）\s*(.+)$/);
    if (match) {
      nodes.push({ type: "node", shape: match[1], text: match[2] });
    }
  }
  if (nodes.length < 2) return null;
  return {
    intro: lines.slice(0, markerIndex).join("\n"),
    nodes,
    after: lines.slice(afterIndex).join("\n"),
  };
}

function flowchartShapeClass(node) {
  const declaredShape = node.shape || "";
  const text = node.text || "";
  if (/各分支汇合|分支汇合/.test(text)) return "flow-node-merge";
  if (/平行四边形/.test(declaredShape)) return "flow-node-io";
  if (/圆角矩形/.test(declaredShape)) return "flow-node-terminal";
  if (/菱形/.test(declaredShape)) return "flow-node-decision";
  if (/矩形/.test(declaredShape)) return "flow-node-process";
  if (/输入|输出/.test(text)) return "flow-node-io";
  if (/开始|结束/.test(text)) return "flow-node-terminal";
  if (/判断/.test(text)) return "flow-node-decision";
  return "flow-node-process";
}

function appendFlowchartText(target, text) {
  String(text || "").split(/(___\d+___)/g).forEach((part) => {
    if (!part) return;
    const node = document.createElement("span");
    node.textContent = part;
    if (/^___\d+___$/.test(part)) node.className = "flow-blank";
    target.appendChild(node);
  });
}

function renderFlowchartMessage(text) {
  const flowchart = parseFlowchartMessage(text);
  if (!flowchart) return null;
  const wrapper = document.createElement("div");
  wrapper.className = "flowchart-message";
  if (flowchart.intro) {
    const intro = document.createElement("p");
    intro.textContent = flowchart.intro;
    wrapper.appendChild(intro);
  }
  const diagram = document.createElement("div");
  diagram.className = "flowchart-diagram";
  for (let index = 0; index < flowchart.nodes.length;) {
    const node = flowchart.nodes[index];
    if (node.type === "branch") {
      const branches = [];
      while (index < flowchart.nodes.length && flowchart.nodes[index].type === "branch") {
        branches.push(flowchart.nodes[index]);
        index += 1;
      }
      const branchRow = document.createElement("div");
      branchRow.className = "flow-branches";
      branches.forEach((branch) => {
        const branchItem = document.createElement("div");
        branchItem.className = "flow-branch";
        const label = document.createElement("div");
        label.className = "flow-branch-label";
        appendFlowchartText(label, branch.label);
        const item = document.createElement("div");
        item.className = `flow-node ${flowchartShapeClass(branch)}`;
        appendFlowchartText(item, branch.text);
        branchItem.append(label, item);
        branchRow.appendChild(branchItem);
      });
      diagram.appendChild(branchRow);
      if (index < flowchart.nodes.length) {
        const arrow = document.createElement("div");
        arrow.className = "flow-arrow";
        arrow.textContent = "↓";
        diagram.appendChild(arrow);
      }
      continue;
    }
    const item = document.createElement("div");
    item.className = `flow-node ${flowchartShapeClass(node)}`;
    appendFlowchartText(item, node.text);
    diagram.appendChild(item);
    index += 1;
    if (index < flowchart.nodes.length) {
      const arrow = document.createElement("div");
      arrow.className = "flow-arrow";
      arrow.textContent = "↓";
      diagram.appendChild(arrow);
    }
  }
  wrapper.appendChild(diagram);
  if (flowchart.after) {
    const after = document.createElement("p");
    after.className = "flowchart-answer-hint";
    after.textContent = flowchart.after;
    wrapper.appendChild(after);
  }
  return wrapper;
}

function renderBotMessageBody(text) {
  const normalized = normalizeQuizText(text);
  const report = renderLearningReport(normalized);
  if (report) return report;
  const flowchart = renderFlowchartMessage(normalized);
  if (flowchart) return flowchart;
  const body = document.createElement("p");
  body.textContent = normalized;
  return body;
}

function stripAgentLabels(text) {
  const labelPattern = agentLabels.join("|");
  const bracketed = new RegExp(`[【\\[]\\s*(?:${labelPattern})\\s*[】\\]]\\s*[:：]?\\s*`, "g");
  const bare = new RegExp(`(?:^|\\n)\\s*(?:${labelPattern})\\s*[:：]\\s*`, "g");
  return String(text || "")
    .replace(bracketed, "")
    .replace(bare, "\n")
    .trim();
}

function agentName(agent) {
  return {
    manager: "编程自主学习管家",
    assistant: "编程助教智能体",
    mentor: "编程导师智能体",
    peer: "编程同伴智能体",
  }[agent] || "智能体";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusText(item) {
  if (!item) return "暂无记录";
  if (item.available === false) return item.reason || "暂无记录";
  if (item.available === true) return JSON.stringify(item.value);
  return String(item);
}

function compactList(items, fallback = "暂无记录") {
  const values = (Array.isArray(items) ? items : [items])
    .map((item) => {
      if (item && typeof item === "object") {
        return item.action || item.selectedCause || item.studentEvidence || item.name || "";
      }
      return String(item || "");
    })
    .map((item) => item.trim())
    .filter(Boolean);
  return values.length ? values.join("；") : fallback;
}

function buildManagerLearningRecordMessage(report) {
  const summary = report?.studentLearningRecordSummary || {};
  const taskCompletion = summary.taskCompletion || {};
  const outcome = summary.outcome || {};
  const evidence = summary.processEvidence || {};
  const completed = taskCompletion.completedTasks || [];
  const planned = taskCompletion.plannedTasks || [];
  const completedText = completed.length && planned.length
    ? `${completed.length}/${planned.length}项（${completed.join("、")}）`
    : compactList(completed, "暂无完整任务记录");
  const actionText = compactList((summary.improvementActions || []).map((item) => item.action), "暂无改进措施");
  return [
    "学习记录汇总",
    `完成任务：${completedText}`,
    `成果记录：${compactList(outcome.strengths, outcome.studentFinalEvaluation || "暂无记录")}`,
    `待改进点：${compactList(outcome.problems, summary.reflectionFocus || "暂无明确问题")}`,
    `原因记录：${compactList(summary.causeAnalysis, "暂无原因记录")}`,
    `有效方法：${compactList(summary.effectiveStrategies, "暂无方法记录")}`,
    `下次行动：${actionText}`,
    `过程证据：调试 ${evidence.debugCount ?? 0} 次，测试证据 ${evidence.testEvidenceCount ?? 0} 条。`,
  ].join("\n");
}

async function sendMessage(message, agent = "auto") {
  addMessage("user", message);
  messageInput.value = "";
  messageInput.disabled = true;
  const waiting = document.createElement("div");
  waiting.className = "message bot";
  waiting.textContent = "正在思考...";
  chatLog.appendChild(waiting);
  chatLog.scrollTop = chatLog.scrollHeight;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, agent }),
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    waiting.remove();
    if (!res.ok) {
      addMessage("bot", data.error || "发送失败，请稍后重试。", "assistant");
      return;
    }
    setActiveAgent(data.agent);
    if (activeAgentName) {
      activeAgentName.textContent = data.agent_name || agentName(data.agent);
    }
    if (debugCount) {
      debugCount.textContent = data.debug_count || 0;
    }
    const metadata = data.metadata || {};
    if (Array.isArray(metadata.before_messages)) {
      metadata.before_messages.forEach((item) => {
        addMessage("bot", item.message || "", item.agent || "assistant");
      });
    }
    addMessage("bot", data.message || "智能体暂时没有返回内容，请再试一次。", data.agent);
    if (Array.isArray(metadata.after_messages)) {
      metadata.after_messages.forEach((item) => {
        addMessage("bot", item.message || "", item.agent || "assistant");
      });
      const lastMessage = metadata.after_messages[metadata.after_messages.length - 1];
      if (lastMessage?.agent) {
        setActiveAgent(lastMessage.agent);
        if (activeAgentName) {
          activeAgentName.textContent = agentName(lastMessage.agent);
        }
      }
    }
    if (metadata.start_timer) {
      applyTimePlan(metadata.time_plan, {
        replace: Boolean(metadata.reset_timer),
        currentIndex: metadata.remaining_replan ? Number(metadata.replan_current_index || 0) : 0,
        totalSeconds: metadata.remaining_replan ? Number(metadata.total_minutes || 0) * 60 : null,
      });
      startTimer();
    }
    if (metadata.complete_timer) {
      completeTimer();
    }
    if (metadata.reflection_available || metadata.reflection_step) {
      initReflection();
    }
  } catch (error) {
    waiting.remove();
    addMessage("bot", `请求失败：${error.message || "请检查后端服务是否正常运行。"}`, "assistant");
  } finally {
    messageInput.disabled = false;
    messageInput.focus();
  }
}

async function reflectionRequest(path, payload = null) {
  const options = payload
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    : { method: "GET" };
  const res = await fetch(path, options);
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok || data.ok === false) {
    const error = new Error(data.error || data.validation?.message || "反思数据保存失败，请稍后重试。");
    error.data = data;
    throw error;
  }
  return data;
}

async function initReflection() {
  if (!reflectionPanel) return;
  try {
    const data = await reflectionRequest("/api/reflection/init", {});
    reflectionState = data;
    renderReflection();
  } catch (error) {
    showReflectionError(error.message);
  }
}

function showReflectionError(message) {
  if (!reflectionError) return;
  reflectionError.textContent = message || "";
  reflectionError.classList.toggle("hidden", !message);
}

function currentReflectionStep() {
  return reflectionState?.currentStep || "OUTCOME_SELF_EVALUATION";
}

function reflectionDraft(step = currentReflectionStep()) {
  return reflectionState?.draft?.[step] || {};
}

function renderReflection() {
  if (!reflectionPanel || !reflectionState) return;
  const step = currentReflectionStep();
  const steps = reflectionState.steps || [];
  const index = Math.max(0, steps.indexOf(step));
  const progress = Math.round(((index + 1) / steps.length) * 100);
  reflectionPanel.classList.remove("hidden");
  reflectionStepText.textContent = reflectionState.stepLabels?.[step] || step;
  reflectionProgressText.textContent = `${progress}%`;
  reflectionProgressBar.style.width = `${progress}%`;
  reflectionBackButton.disabled = index <= 0 || step === "REFLECTION_COMPLETE";
  reflectionSaveButton.disabled = step === "RETURN_TO_DEBUG";
  reflectionSaveButton.textContent = step === "REFLECTION_COMPLETE" ? "确认并保存反思" : "保存并继续";
  showReflectionError("");

  const renderers = {
    OUTCOME_SELF_EVALUATION: renderOutcomeSelfEvaluation,
    OUTCOME_AGENT_EVALUATION: renderOutcomeAgentEvaluation,
    OUTCOME_CONFIRMATION: renderOutcomeConfirmation,
    REFLECTION_PROCESS_REVIEW: renderReflectionProcessReview,
    REFLECTION_CAUSE_ANALYSIS: renderReflectionCauseAnalysis,
    REFLECTION_EXPERIENCE_SUMMARY: renderReflectionExperienceSummary,
    REFLECTION_IMPROVEMENT_PLAN: renderReflectionImprovementPlan,
    REFLECTION_COMPLETE: renderReflectionComplete,
    RETURN_TO_DEBUG: renderReturnToDebug,
  };
  reflectionBody.innerHTML = (renderers[step] || renderOutcomeSelfEvaluation)();
}

function optionTags(options, selected = "") {
  return options.map((item) => `<option ${selected === item ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
}

function renderOutcomeSelfEvaluation() {
  const context = reflectionState.context || {};
  const draft = reflectionDraft("OUTCOME_SELF_EVALUATION");
  const rubric = context.rubric || [];
  const items = rubric.map((item) => `<li>${escapeHtml(item.dimension)}：${escapeHtml(item.criteria)}</li>`).join("");
  return `
    <div class="reflection-card">
      <span class="reflection-tag">评价依据</span>
      <h3>我们先按照任务要求检查程序</h3>
      <p>学习目标：${escapeHtml(statusText(context.learningGoal))}</p>
      <p>任务要求：${escapeHtml(statusText(context.taskRequirement))}</p>
      <ul>${items}</ul>
    </div>
    <div class="reflection-card">
      <span class="reflection-tag">学生先评价</span>
      <h3>先自己检查一下你的程序吧</h3>
      <label>1. 你的程序实现了任务要求的功能吗？
        <select data-reflection-field="taskCompletion">${optionTags(["", "已完成", "部分完成", "还没有完成"], draft.taskCompletion)}</select>
      </label>
      <label>2. 你有没有使用不同的数据测试程序？
        <select data-reflection-field="testedDifferentData">${optionTags(["", "有", "没有"], draft.testedDifferentData)}</select>
      </label>
      <label>3. 你认为不同输入情况下程序的运行结果都符合预期吗？
        <select data-reflection-field="runtimeCorrectness">${optionTags(["", "符合", "不确定", "不符合"], draft.runtimeCorrectness)}</select>
      </label>
      <label>4. 你检查过判断条件、冒号和缩进吗？
        <select data-reflection-field="programLogic">${optionTags(["", "检查过", "还没有"], draft.programLogic)}</select>
      </label>
      <label>5. 你觉得代码格式和变量命名基本清楚吗？
        <select data-reflection-field="codeQuality">${optionTags(["", "基本规范", "还需要整理"], draft.codeQuality)}</select>
      </label>
    </div>`;
}

function dimensionRows(evaluation = {}) {
  return ["taskCompletion", "runtimeCorrectness", "programLogic", "codeQuality"].map((key) => {
    const item = evaluation[key] || {};
    return `
      <tr>
        <td>${escapeHtml(item.label || key)}</td>
        <td>${escapeHtml(item.status || "证据不足")}</td>
        <td>${escapeHtml(item.evidence || "当前记录无法判断。")}</td>
      </tr>`;
  }).join("");
}

function renderOutcomeAgentEvaluation() {
  const outcome = reflectionState.context?.outcomeEvaluation || {};
  const strengths = (outcome.strengths || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const problems = (outcome.problems || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `
    <div class="reflection-card">
      <span class="reflection-tag">助教评价</span>
      <h3>我根据现有证据检查了四个方面</h3>
      <table class="reflection-table">
        <thead><tr><th>维度</th><th>判断</th><th>证据</th></tr></thead>
        <tbody>${dimensionRows(outcome.agentEvaluation)}</tbody>
      </table>
    </div>
    <div class="reflection-card">
      <span class="reflection-tag">成果记录</span>
      <h3>已完成和仍需检查的地方</h3>
      <p>已经完成或表现较好的内容：</p>
      <ul>${strengths || "<li>当前记录中还没有足够证据。</li>"}</ul>
      <p>仍然存在的问题：</p>
      <ul>${problems || "<li>当前记录中没有发现明确问题。</li>"}</ul>
    </div>`;
}

function renderOutcomeConfirmation() {
  const outcome = reflectionState.context?.outcomeEvaluation || {};
  const comparison = reflectionState.context?.outcomeComparison || {};
  const draft = reflectionDraft("OUTCOME_CONFIRMATION");
  const diff = (comparison.differences || []).map((item) => `<li>${escapeHtml(item.dimension)}：你选“${item.self}”，证据显示“${item.agent}”。</li>`).join("");
  const tests = (outcome.recommendedTestInputs || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const nextDefault = draft.nextAction || (outcome.coreFunctionIncomplete ? "return_to_debug" : "continue_reflection");
  return `
    <div class="reflection-card">
      <span class="reflection-tag">对照确认</span>
      <h3>${comparison.isMostlyAligned ? "你的自评和程序证据基本一致" : "有一处需要重新看看"}</h3>
      <p>${comparison.isMostlyAligned ? "说明你已经能够比较准确地评价自己的程序。" : "先别急着否定自己，我们用证据再检查一次。"}</p>
      ${diff ? `<ul>${diff}</ul>` : ""}
      <p>程序能够运行是第一步，还需要用不同数据看看结果是否都符合预期。</p>
      <ul>${tests}</ul>
    </div>
    <div class="reflection-card">
      <span class="reflection-tag">我的确认</span>
      <h3>确认学习成果评价记录</h3>
      <textarea data-reflection-field="studentFinalEvaluation" rows="4" placeholder="例如：我完成了主要功能，但还需要补充边界数据测试。">${escapeHtml(draft.studentFinalEvaluation || "")}</textarea>
      <label>下一步
        <select data-reflection-field="nextAction">
          ${optionTags(["continue_reflection", "return_to_debug"], nextDefault)}
        </select>
      </label>
      <p>选择 continue_reflection 会进入学习反思优化；选择 return_to_debug 会返回调试阶段继续完善。</p>
    </div>`;
}

function renderReflectionProcessReview() {
  const context = reflectionState.context || {};
  const draft = reflectionDraft("REFLECTION_PROCESS_REVIEW");
  const summary = context.processSummary || {};
  const problems = context.problemCues || [];
  const selected = draft.selectedProblem || problems[0]?.description || "";
  const options = ["", ...problems.map((cue) => cue.description)];
  return `
    <div class="reflection-card">
      <span class="reflection-tag">过程回顾</span>
      <h3>这次学习中</h3>
      <p>完成记录：${escapeHtml((summary.taskCompletion || []).filter((item) => item.completed).map((item) => item.name).join("、") || "暂无完整记录")}</p>
      <p>调试次数：${escapeHtml(summary.debugCount ?? 0)}</p>
      <p>学习成果评价发现：${escapeHtml((context.outcomeEvaluation?.problems || []).join("；") || "暂无明确问题")}</p>
    </div>
    <div class="reflection-card">
      <span class="reflection-tag">学生选择</span>
      <h3>你觉得最值得进一步想一想的问题是什么？</h3>
      <select data-reflection-field="selectedProblem">${optionTags(options, selected)}</select>
      <textarea data-reflection-field="extraProblem" rows="3" placeholder="如果上面没有合适的问题，可以自己写一个。">${escapeHtml(draft.extraProblem || "")}</textarea>
    </div>`;
}

function renderReflectionCauseAnalysis() {
  const draft = reflectionDraft("REFLECTION_CAUSE_ANALYSIS");
  const processDraft = reflectionDraft("REFLECTION_PROCESS_REVIEW");
  const problem = processDraft.selectedProblem || processDraft.extraProblem || "刚才选择的问题";
  return `
    <div class="reflection-card">
      <span class="reflection-tag">原因分析</span>
      <h3>先分析一个问题：${escapeHtml(problem)}</h3>
      <p>你觉得它主要可能和哪方面有关？</p>
      <select data-reflection-field="studentSelectedCause">
        ${optionTags(["知识掌握", "程序设计思路", "调试方法", "时间安排", "注意力或情绪", "其他"], draft.studentSelectedCause)}
      </select>
      <textarea data-reflection-field="studentEvidence" rows="4" placeholder="回想一下，当时主要表现是什么？例如：不确定判断条件，还是不知道怎样定位错误。">${escapeHtml(draft.studentEvidence || "")}</textarea>
      <label><input type="checkbox" data-reflection-field="studentConfirmed" ${draft.studentConfirmed ? "checked" : ""}> 我确认这是本次主要原因之一</label>
    </div>`;
}

function renderReflectionExperienceSummary() {
  const draft = reflectionDraft("REFLECTION_EXPERIENCE_SUMMARY");
  const selected = new Set(draft.effectiveStrategies || []);
  const strategies = [
    "先做IPO分析再写代码",
    "先画流程图再写代码",
    "使用不同测试数据",
    "每次只修改一个错误",
    "根据时间提醒调整进度",
    "主动寻求帮助",
  ];
  const options = strategies.map((item, index) => `
    <label>
      <input type="checkbox" data-strategy-index="${index}" ${selected.has(item) ? "checked" : ""}>
      <span>${escapeHtml(item)}</span>
    </label>`).join("");
  return `
    <div class="reflection-card">
      <span class="reflection-tag">有效经验</span>
      <h3>这次学习中，哪种方法对你特别有帮助？</h3>
      <div class="reflection-options">${options}</div>
      <textarea data-reflection-field="extraStrategy" rows="3" placeholder="也可以写一个自己的有效方法。">${escapeHtml(draft.extraStrategy || "")}</textarea>
    </div>`;
}

function renderReflectionImprovementPlan() {
  const draft = reflectionDraft("REFLECTION_IMPROVEMENT_PLAN");
  const causeDraft = reflectionDraft("REFLECTION_CAUSE_ANALYSIS");
  const processDraft = reflectionDraft("REFLECTION_PROCESS_REVIEW");
  const action = (draft.actions || [{}])[0];
  return `
    <div class="reflection-card">
      <span class="reflection-tag">改进措施</span>
      <h3>把改进写成下一次能做到的行动</h3>
      <input data-action-field="relatedProblem" placeholder="针对的问题" value="${escapeHtml(action.relatedProblem || processDraft.selectedProblem || processDraft.extraProblem || "")}">
      <input data-action-field="relatedCause" placeholder="相关原因" value="${escapeHtml(action.relatedCause || causeDraft.studentSelectedCause || "")}">
      <textarea data-action-field="action" rows="3" placeholder="例如：至少使用两组不同数据和一个边界数据测试程序。">${escapeHtml(action.action || "")}</textarea>
      <textarea data-action-field="verification" rows="3" placeholder="如何判断措施有效？例如：能说出每组输入的预期结果并和运行结果对比。">${escapeHtml(action.verification || "")}</textarea>
      <input data-action-field="nextUseContext" placeholder="准备在哪个任务或环节使用" value="${escapeHtml(action.nextUseContext || "")}">
    </div>`;
}

function renderReflectionComplete() {
  const draft = reflectionState.draft || {};
  const outcome = reflectionState.context?.outcomeEvaluation || {};
  const process = draft.REFLECTION_PROCESS_REVIEW || {};
  const causes = draft.REFLECTION_CAUSE_ANALYSIS?.confirmedCauses || [];
  const strategies = draft.REFLECTION_EXPERIENCE_SUMMARY?.effectiveStrategies || [];
  const actions = draft.REFLECTION_IMPROVEMENT_PLAN?.actions || [];
  if (reflectionState.session?.status === "completed" || reflectionState.report) {
    return renderReportSaved();
  }
  return `
    <div class="reflection-card">
      <span class="reflection-tag">我的本次学习反思</span>
      <h3>确认后保存</h3>
      <p>我的学习成果：${escapeHtml((outcome.strengths || []).join("；") || "暂无记录")}</p>
      <p>我发现的问题：${escapeHtml((outcome.problems || []).join("；") || "暂无记录")}</p>
      <p>我认为的原因：${escapeHtml(causes.map((item) => `${item.selectedCause}：${item.studentEvidence}`).join("；") || "未填写")}</p>
      <p>这次有效的方法：${escapeHtml(strategies.join("；") || "未填写")}</p>
      <p>下次我准备：${escapeHtml(actions.map((item) => item.action).join("；") || "未填写")}</p>
      <label><input type="checkbox" data-reflection-field="studentConfirmed"> 我确认以上内容可以生成正式反思记录</label>
    </div>`;
}

function renderReturnToDebug() {
  return `
    <div class="reflection-card">
      <span class="reflection-tag">返回调试</span>
      <h3>先继续完善程序</h3>
      <p>修改程序并再次确认运行成功后，系统会重新进入学习成果评价。</p>
    </div>`;
}

function renderReportSaved() {
  const actions = reflectionState?.report?.studentLearningRecordSummary?.improvementActions
    || reflectionState?.report?.improvementActions
    || [];
  return `
    <div class="reflection-card">
      <span class="reflection-tag">反思已保存</span>
      <h3>学习反思记录已经保存</h3>
      <p>编程自主学习管家已在聊天区汇总本次学习记录。</p>
      <p>下次行动：${escapeHtml(compactList(actions.map((item) => item.action), "暂无改进措施"))}</p>
    </div>`;
}

function collectReflectionPayload(step) {
  const payload = {};
  reflectionBody.querySelectorAll("[data-reflection-field]").forEach((field) => {
    const key = field.dataset.reflectionField;
    payload[key] = field.type === "checkbox" ? field.checked : field.value.trim();
  });
  if (step === "PROCESS_REVIEW") {
    payload.learningStrengths = String(payload.learningStrengths || "").split(/\n+/).map((item) => item.trim()).filter(Boolean);
    payload.effectiveExperiences = String(payload.effectiveExperiences || "").split(/\n+/).map((item) => item.trim()).filter(Boolean);
  }
  if (step === "PROBLEM_IDENTIFICATION") {
    const cues = reflectionState.context?.problemCues || [];
    payload.confirmedProblems = [...reflectionBody.querySelectorAll("[data-problem-index]:checked")]
      .map((item) => cues[Number(item.dataset.problemIndex)]?.description)
      .filter(Boolean);
    if (payload.extraProblem) payload.confirmedProblems.push(payload.extraProblem);
  }
  if (step === "REFLECTION_EXPERIENCE_SUMMARY") {
    const strategies = [
      "先做IPO分析再写代码",
      "先画流程图再写代码",
      "使用不同测试数据",
      "每次只修改一个错误",
      "根据时间提醒调整进度",
      "主动寻求帮助",
    ];
    payload.effectiveStrategies = [...reflectionBody.querySelectorAll("[data-strategy-index]:checked")]
      .map((item) => strategies[Number(item.dataset.strategyIndex)])
      .filter(Boolean);
    if (payload.extraStrategy) payload.effectiveStrategies.push(payload.extraStrategy);
  }
  if (step === "CAUSE_ANALYSIS" || step === "REFLECTION_CAUSE_ANALYSIS") {
    const problemDraft = reflectionDraft("PROBLEM_IDENTIFICATION");
    const processDraft = reflectionDraft("REFLECTION_PROCESS_REVIEW");
    const problem = processDraft.selectedProblem || processDraft.extraProblem || (problemDraft.confirmedProblems || [problemDraft.extraProblem || "主要问题"])[0];
    payload.confirmedCauses = [
      {
        problem,
        selectedCause: payload.studentSelectedCause,
        studentEvidence: payload.studentEvidence,
        studentConfirmed: Boolean(payload.studentConfirmed),
      },
    ];
  }
  if (step === "IMPROVEMENT_PLAN" || step === "REFLECTION_IMPROVEMENT_PLAN") {
    const action = {};
    reflectionBody.querySelectorAll("[data-action-field]").forEach((field) => {
      action[field.dataset.actionField] = field.value.trim();
    });
    payload.actions = [action];
  }
  return payload;
}

async function saveReflectionStep() {
  if (!reflectionState || reflectionSaving) return;
  const step = currentReflectionStep();
  const payload = collectReflectionPayload(step);
  if (step === "OUTCOME_SELF_EVALUATION" && (!payload.taskCompletion || !payload.testedDifferentData || !payload.runtimeCorrectness || !payload.programLogic || !payload.codeQuality)) {
    showReflectionError("请先完成自评问题，再查看助教评价。");
    return;
  }
  if (step === "REFLECTION_PROCESS_REVIEW" && !payload.selectedProblem && !payload.extraProblem) {
    showReflectionError("请选择或写下一个最值得反思的问题。");
    return;
  }
  if (step === "REFLECTION_CAUSE_ANALYSIS") {
    const evidence = payload.studentEvidence || "";
    if (!payload.studentConfirmed || evidence.length < 8 || /粗心|不认真|没认真|不会|不熟|忘了|没学好/.test(evidence)) {
      showReflectionError("请补充一个具体表现或学习记录，并确认这是主要原因之一。");
      return;
    }
  }
  if (step === "REFLECTION_EXPERIENCE_SUMMARY" && !(payload.effectiveStrategies || []).length) {
    showReflectionError("请至少确认一种这次有效的方法。");
    return;
  }
  if (step === "REFLECTION_COMPLETE") {
    if (!payload.studentConfirmed) {
      showReflectionError("需要你主动勾选确认后，系统才会保存正式反思记录。");
      return;
    }
    return saveReflectionReport(payload);
  }
  reflectionSaving = true;
  reflectionSaveButton.disabled = true;
  try {
    const nextState = await reflectionRequest("/api/reflection/save", { step, payload });
    if (nextState.returnedToDebug) {
      reflectionPanel.classList.add("hidden");
      reflectionState = null;
      addMessage("bot", nextState.message || "已经返回调试阶段。", "assistant");
      return;
    }
    reflectionState = nextState;
    renderReflection();
  } catch (error) {
    showReflectionError(error.message);
  } finally {
    reflectionSaving = false;
    reflectionSaveButton.disabled = false;
  }
}

async function saveReflectionReport(payload) {
  reflectionSaving = true;
  reflectionSaveButton.disabled = true;
  try {
    const data = await reflectionRequest("/api/reflection/report", {
      studentConfirmed: true,
      ...payload,
    });
    reflectionState.currentStep = "REFLECTION_COMPLETE";
    if (reflectionState.session) reflectionState.session.status = "completed";
    reflectionState.report = data.report;
    renderReflection();
    addMessage("bot", buildManagerLearningRecordMessage(data.report), "manager");
    setActiveAgent("manager");
    if (activeAgentName) activeAgentName.textContent = agentName("manager");
  } catch (error) {
    showReflectionError(error.message);
  } finally {
    reflectionSaving = false;
    reflectionSaveButton.disabled = false;
  }
}

async function backReflectionStep() {
  if (!reflectionState || reflectionSaving) return;
  try {
    reflectionState = await reflectionRequest("/api/reflection/back", {});
    renderReflection();
  } catch (error) {
    showReflectionError(error.message);
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (message) sendMessage(message);
});

function normalizeTimePlan(timePlan) {
  return (Array.isArray(timePlan) ? timePlan : [])
    .map((task) => ({
      name: task.name,
      minutes: Math.max(1, Number(task.minutes || 1)),
    }))
    .filter((task) => task.name && task.minutes > 0);
}

function applyTimePlan(timePlan, options = {}) {
  const normalized = normalizeTimePlan(timePlan);
  if (normalized.length === 0) return;
  const inputs = [...document.querySelectorAll(".time-inputs input")];
  normalized.forEach((task) => {
    const input = inputs.find((item) => item.dataset.task === task.name);
    if (input) input.value = task.minutes;
  });
  clearInterval(timer);
  timer = null;
  timerStarted = false;
  activeTasks = options.replace ? normalized : null;
  taskIndex = Math.min(Math.max(0, Number(options.currentIndex || 0)), normalized.length - 1);
  tasks = activeTasks || readTasks();
  secondsLeft = Number(options.totalSeconds || 0) > 0 ? Number(options.totalSeconds) : TOTAL_SECONDS;
  renderTimePlanHint();
  renderTimer();
}

chips.forEach((chip) => {
  chip.type = "button";
});

studentName.addEventListener("change", async () => {
  await fetch("/api/student-name", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: studentName.value.trim() }),
  });
});

document.querySelectorAll(".time-inputs input").forEach((input) => {
  input.addEventListener("change", () => {
    input.value = clampTaskMinutes(input.value, input.min, input.max);
    activeTasks = null;
    tasks = readTasks();
    renderTimePlanHint();
    if (!timerStarted) {
      taskIndex = 0;
      secondsLeft = TOTAL_SECONDS;
      renderTimer();
    }
  });
});

document.querySelectorAll("[data-time-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.closest(".time-stepper")?.querySelector("input");
    if (!input) return;
    const direction = button.dataset.timeAction === "increment" ? 1 : -1;
    input.value = clampTaskMinutes(Number(input.value || 0) + direction, input.min, input.max);
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
});

function clampTaskMinutes(value, min, max) {
  const lower = Number(min || 1);
  const upper = Number(max || 20);
  const nextValue = Math.round(Number(value || lower));
  return Math.min(upper, Math.max(lower, nextValue));
}

function completedPlannedMinutes() {
  return tasks
    .slice(0, taskIndex)
    .reduce((sum, task) => sum + task.minutes, 0);
}

function renderTimer() {
  const task = tasks[taskIndex] || { name: "学习完成", minutes: 0 };
  timerTask.textContent = taskIndex < tasks.length ? `当前任务：${task.name}` : "全部任务已结束";
  const minutes = String(Math.floor(secondsLeft / 60)).padStart(2, "0");
  const seconds = String(secondsLeft % 60).padStart(2, "0");
  timerClock.textContent = `${minutes}:${seconds}`;
  const total = tasks.reduce((sum, item) => sum + item.minutes, 0);
  const progress = total ? Math.min(100, Math.round((completedPlannedMinutes() / total) * 100)) : 0;
  if (progressText) progressText.textContent = `${progress}%`;
  if (progressBar) progressBar.style.width = `${progress}%`;
  renderTimerButton();
  renderNextTaskButton();
}

function renderTimerButton() {
  if (!pauseTimerButton) return;
  const finished = taskIndex >= tasks.length || secondsLeft <= 0;
  pauseTimerButton.disabled = finished;
  if (!timerStarted) {
    pauseTimerButton.textContent = "开始计时";
  } else {
    pauseTimerButton.textContent = timer ? "暂停计时" : "继续计时";
  }
}

function renderNextTaskButton() {
  if (!nextTaskButton) return;
  const lastTask = taskIndex >= Math.max(0, tasks.length - 1);
  nextTaskButton.textContent = lastTask ? "程序完成/进入反思" : "进入下一任务";
}

function startTimer() {
  tasks = activeTasks || readTasks();
  if (!tasks.length) return;
  if (taskIndex >= tasks.length) taskIndex = 0;
  if (!secondsLeft || secondsLeft <= 0) secondsLeft = TOTAL_SECONDS;
  timerStarted = true;
  renderTimePlanHint();
  renderTimer();
  clearInterval(timer);
  timer = setInterval(() => {
    secondsLeft -= 1;
    renderTimer();
    if (secondsLeft <= 0) {
      clearInterval(timer);
      timer = null;
      renderTimerButton();
      sendMessage(
        `当前任务“${tasks[taskIndex].name}”倒计时已结束，我还没有确认完成，属于超时未完成。请编程同伴智能体监督我重新分析任务时间，并帮我调整接下来的学习节奏。`,
        "peer"
      );
    }
  }, 1000);
  renderTimerButton();
}

function completeTimer() {
  clearInterval(timer);
  timer = null;
  timerStarted = false;
  tasks = activeTasks || readTasks();
  taskIndex = tasks.length;
  secondsLeft = 0;
  renderTimer();
}

function toggleTimerPause() {
  if (timer) {
    clearInterval(timer);
    timer = null;
    renderTimerButton();
    return;
  }
  startTimer();
}

function nextTask() {
  clearInterval(timer);
  timer = null;
  const shouldResume = timerStarted && secondsLeft > 0;
  taskIndex += 1;
  if (taskIndex < tasks.length) {
    renderTimer();
    if (shouldResume) startTimer();
    if (tasks[taskIndex].name === "设计算法") {
      sendMessage("我已经结束问题分析任务，请导师根据我的 IPO 总结生成流程图框架。");
    }
  } else {
    secondsLeft = 0;
    renderTimer();
    sendMessage("我的程序已经成功运行，代码完成了，请进入反思阶段。");
  }
}

pauseTimerButton.addEventListener("click", toggleTimerPause);
nextTaskButton.addEventListener("click", nextTask);
if (reflectionSaveButton) reflectionSaveButton.addEventListener("click", saveReflectionStep);
if (reflectionBackButton) reflectionBackButton.addEventListener("click", backReflectionStep);
renderTimePlanHint();
renderTimer();
