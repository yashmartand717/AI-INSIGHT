/**
 * GyanBuddy AI Insight Engine - Clean, Minimalist Client Application
 */

document.addEventListener("DOMContentLoaded", () => {
  initSystem();
});

async function initSystem() {
  await fetchSystemStatus();
  await loadStudentsList();
  await loadTeacherGroups();
  await loadParentReport();
  recalcCost();
}

// ==========================================
// 1. Navigation & Tab Switching
// ==========================================
function switchTab(tabName) {
  document.querySelectorAll(".nav-link").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(panel => panel.classList.remove("active"));

  const targetBtn = document.getElementById(`nav-btn-${tabName}`);
  const targetPanel = document.getElementById(`tab-panel-${tabName}`);

  if (targetBtn && targetPanel) {
    targetBtn.classList.add("active");
    targetPanel.classList.add("active");
  }

  if (tabName === "teacher") {
    loadTeacherReport();
  } else if (tabName === "principal") {
    loadPrincipalReport();
  }
}

// ==========================================
// 2. System Status & Students Roster
// ==========================================
async function fetchSystemStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    const providerBadge = document.getElementById("provider-name-display");
    const statusDot = document.querySelector(".status-dot");
    if (providerBadge) {
      providerBadge.textContent = data.provider.active_provider === "SMART_MOCK"
        ? "Smart Engine (Offline)"
        : `${data.provider.active_provider} configured`;
      if (statusDot) statusDot.style.backgroundColor = "var(--success-text)";
    }
  } catch (err) {
    console.error("Failed to fetch system status:", err);
  }
}

async function loadStudentsList() {
  try {
    const res = await fetch("/api/students");
    const data = await res.json();
    const selector = document.getElementById("student-selector");
    if (!selector || !data.students) return;

    const previous = selector.value;
    selector.innerHTML = "";
    data.students.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.student_id;
      opt.textContent = `${s.student_name} (${s.class_name}-${s.section})`;
      selector.appendChild(opt);
    });
    if (data.students.some(s => s.student_id === previous)) selector.value = previous;
  } catch (err) {
    console.error("Failed to load students:", err);
  }
}

// ==========================================
// 3. Parent Report Generator
// ==========================================
async function loadParentReport(studentId) {
  if (!studentId) {
    const selector = document.getElementById("student-selector");
    studentId = selector ? selector.value : "";
  }

  const request = ++parentRequest;
  clearParentReport();
  const headlineEl = document.getElementById("parent-headline");
  const summaryEl = document.getElementById("parent-summary-text");
  if (!studentId) {
    if (summaryEl) summaryEl.textContent = "Upload test records to view a student report.";
    return;
  }
  document.getElementById("student-selector").value = studentId;
  if (summaryEl) summaryEl.textContent = "Generating learning report...";

  try {
    const res = await fetch(`/api/reports/parent/${encodeURIComponent(studentId)}`);
    const data = await res.json();

    if (request !== parentRequest) return;
    if (!res.ok) throw new Error(data.detail || "Unable to load student report.");
    const metrics = data.metrics;
    const ai = data.ai_insight;

    // Headline and Summary
    if (headlineEl) headlineEl.textContent = ai.headline || `${metrics.student_name}'s Learning Pulse`;
    if (summaryEl) summaryEl.textContent = ai.overall_summary;

    // Pills
    const classPill = document.getElementById("parent-class-pill");
    const accPill = document.getElementById("parent-accuracy-pill");
    if (classPill) classPill.textContent = `${metrics.class_name}-${metrics.section}${metrics.roll_no ? ` • Roll ${metrics.roll_no}` : ""}`;
    if (accPill) {
      accPill.textContent = `Accuracy: ${metrics.overall_accuracy_pct}%`;
      accPill.className = metrics.overall_accuracy_pct >= 70 ? "pill pill-success" : (metrics.overall_accuracy_pct >= 40 ? "pill pill-warning" : "pill pill-danger");
    }

    // Weakness / Critical Gap Box
    const focusBox = document.getElementById("parent-focus-box");
    const focusTitle = document.getElementById("parent-focus-title");
    const focusScore = document.getElementById("parent-focus-score");
    const focusDesc = document.getElementById("parent-focus-desc");

    const focus = [...(metrics.critical_gaps || []), ...(metrics.needs_revision || [])];
    if (focus.length > 0) {
      const topGap = focus[0];
      focusBox.style.display = "block";
      focusTitle.textContent = `⚠️ Needs Attention: ${topGap.chapter} (${topGap.subject})`;
      focusScore.textContent = `${topGap.correct}/${topGap.total_questions} Correct (${topGap.score_pct}%)`;
      focusDesc.textContent = ai.focus_area_explanation;
    } else {
      focusBox.style.display = "none";
    }

    // Celebrated Strength
    const strengthEl = document.getElementById("parent-strength-text");
    if (strengthEl) {
      strengthEl.textContent = ai.strength_highlight;
    }

    // Action Plan List
    const actionList = document.getElementById("parent-action-list");
    if (actionList) {
      actionList.innerHTML = "";
      if (ai.action_plan_for_home) {
        ai.action_plan_for_home.forEach(step => {
          const li = document.createElement("li");
          li.textContent = step;
          actionList.appendChild(li);
        });
      }
    }

    // Recent Test Table
    const tbody = document.getElementById("parent-test-table-body");
    if (tbody) {
      tbody.innerHTML = "";
      metrics.chapter_diagnostics.forEach(test => {
        const tr = document.createElement("tr");
        let statusBadge = `<span class="pill pill-success">Mastered (${test.score_pct}%)</span>`;
        if (test.mastery_status === "CRITICAL_GAP") {
          statusBadge = `<span class="pill pill-danger">Needs Practice (${test.score_pct}%)</span>`;
        } else if (test.mastery_status === "NEEDS_REVISION") {
          statusBadge = `<span class="pill pill-warning">Revise (${test.score_pct}%)</span>`;
        }

        tr.innerHTML = `
          <td><strong>${escapeHTML(test.subject)}</strong></td>
          <td>${escapeHTML(test.chapter)}</td>
          <td><strong>${test.correct} / ${test.total_questions}</strong></td>
          <td>${statusBadge}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    // WhatsApp Message
    const whatsappEl = document.getElementById("whatsapp-message-bubble");
    if (whatsappEl) whatsappEl.textContent = ai.whatsapp_message;

  } catch (err) {
    if (request === parentRequest && summaryEl) summaryEl.textContent = err.message;
  }
}

function copyWhatsAppMessage() {
  const whatsappEl = document.getElementById("whatsapp-message-bubble");
  if (!whatsappEl) return;

  navigator.clipboard.writeText(whatsappEl.textContent).then(() => {
    const copyBtn = document.getElementById("btn-copy-whatsapp");
    const origText = copyBtn.innerHTML;
    copyBtn.innerHTML = "✅ Copied to Clipboard!";
    setTimeout(() => {
      copyBtn.innerHTML = origText;
    }, 2000);
  });
}

// ==========================================
// 4. File Upload (CSV / Excel)
// ==========================================
function handleFileUpload(event) {
  const file = event.target.files[0];
  if (file) {
    uploadFile(file);
  }
}

async function uploadFile(file) {
  const toast = document.getElementById("upload-toast");
  toast.style.display = "block";
  toast.style.color = "";
  toast.textContent = `Loading test records from ${file.name}...`;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-csv", {
      method: "POST",
      body: formData
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      throw new Error(data.detail || data.error || "Upload failed");
    }

    toast.textContent = `Loaded ${data.total_records} test rows for ${data.total_students} students. ${(data.warnings || []).join(" ")}`;
    ++parentRequest;
    ++teacherRequest;
    ++principalRequest;
    clearParentReport();
    clearTeacherReport();
    clearPrincipalReport();

    await fetchSystemStatus();
    await loadStudentsList();
    await loadTeacherGroups();
    if (data.first_student_id) {
      await loadParentReport(data.first_student_id);
    }
    if (document.getElementById("tab-panel-teacher").classList.contains("active")) await loadTeacherReport();
    if (document.getElementById("tab-panel-principal").classList.contains("active")) await loadPrincipalReport();
    recalcCost();

    setTimeout(() => {
      if (!(data.warnings || []).length) toast.style.display = "none";
    }, 6000);

  } catch (err) {
    toast.style.color = "var(--danger-text)";
    toast.textContent = `❌ ${err.message}`;
  }
}

// ==========================================
// 5. Teacher View
// ==========================================
let teacherGroups = [];
let parentRequest = 0;
let teacherRequest = 0;
let principalRequest = 0;

function escapeHTML(value) {
  const span = document.createElement("span");
  span.textContent = String(value ?? "");
  return span.innerHTML;
}

function clearParentReport() {
  ["parent-headline", "parent-class-pill", "parent-accuracy-pill", "parent-strength-text", "parent-action-list", "parent-test-table-body", "whatsapp-message-bubble"].forEach(id => document.getElementById(id).textContent = "");
  document.getElementById("parent-focus-box").style.display = "none";
}

function clearTeacherReport() {
  ["teacher-avg-badge", "teacher-gap-text", "teacher-student-tags", "teacher-intervention-text", "teacher-homework-text", "teacher-peer-text", "teacher-cluster-description"].forEach(id => document.getElementById(id).textContent = "");
  document.getElementById("teacher-overview-text").textContent = "Choose a class to view its report.";
}

function clearPrincipalReport() {
  ["principal-score-badge", "principal-bottleneck-body", "principal-teacher-support"].forEach(id => document.getElementById(id).textContent = "");
  document.getElementById("principal-exec-summary").textContent = "Open this view to generate a briefing.";
}

async function loadTeacherGroups() {
  const selector = document.getElementById("teacher-group-selector");
  const previous = selector.value;
  selector.replaceChildren();
  teacherGroups = [];
  try {
    const res = await fetch("/api/report-groups");
    if (!res.ok) throw new Error("Unable to load classes.");
    teacherGroups = (await res.json()).groups;
    teacherGroups.forEach(group => {
      const option = document.createElement("option");
      option.value = JSON.stringify(group);
      option.textContent = `${group.class_name}-${group.section} · ${group.subject}`;
      selector.appendChild(option);
    });
    if ([...selector.options].some(option => option.value === previous)) selector.value = previous;
  } catch (err) {
    document.getElementById("teacher-overview-text").textContent = err.message;
  }
}

async function loadTeacherReport() {
  const request = ++teacherRequest;
  clearTeacherReport();
  const overviewEl = document.getElementById("teacher-overview-text");
  const value = document.getElementById("teacher-group-selector").value;
  if (!value) {
    overviewEl.textContent = "Upload test records to view class reports.";
    return;
  }
  const group = JSON.parse(value);
  document.getElementById("teacher-heading").textContent = `${group.class_name}-${group.section} ${group.subject} Diagnostic`;
  overviewEl.textContent = "Analyzing recorded results...";
  try {
    const route = [group.class_name, group.section, group.subject].map(encodeURIComponent).join("/");
    const res = await fetch(`/api/reports/teacher/${route}`);
    const data = await res.json();
    if (request !== teacherRequest) return;
    if (!res.ok) throw new Error(data.detail || "Unable to load class report.");
    const metrics = data.metrics;
    const ai = data.ai_insight;
    document.getElementById("teacher-avg-badge").textContent = `Class Average: ${metrics.class_average_pct}%`;
    overviewEl.textContent = ai.subject_class_overview;
    document.getElementById("teacher-gap-text").textContent = ai.critical_learning_gap;
    const cluster = metrics.remedial_clusters[0];
    document.getElementById("teacher-cluster-description").textContent = cluster
      ? `First remedial group: ${cluster.chapter}` : "No recorded scores are below 50%.";
    if (cluster) {
      const tagContainer = document.getElementById("teacher-student-tags");
      cluster.students.forEach(student => {
        const span = document.createElement("span");
        span.className = "student-chip";
        span.textContent = `${student.student_name} (${student.score_pct}%)`;
        tagContainer.appendChild(span);
      });
    }
    document.getElementById("teacher-intervention-text").textContent = ai.remedial_group_strategy?.targeted_intervention || "";
    document.getElementById("teacher-homework-text").textContent = ai.remedial_group_strategy?.recommended_homework || "";
    document.getElementById("teacher-peer-text").textContent = ai.peer_learning_pairing || "";
  } catch (err) {
    if (request === teacherRequest) overviewEl.textContent = err.message;
  }
}

async function loadPrincipalReport() {
  const request = ++principalRequest;
  clearPrincipalReport();
  const summaryEl = document.getElementById("principal-exec-summary");
  summaryEl.textContent = "Compiling school briefing...";
  try {
    const res = await fetch("/api/reports/principal");
    const data = await res.json();
    if (request !== principalRequest) return;
    if (!res.ok) throw new Error(data.detail || "Unable to load school report.");
    const metrics = data.metrics;
    const ai = data.ai_insight;
    document.getElementById("principal-score-badge").textContent = `Overall Score: ${metrics.school_overall_average_pct}%`;
    summaryEl.textContent = ai.executive_summary;
    const tbody = document.getElementById("principal-bottleneck-body");
    metrics.curriculum_bottlenecks.forEach(item => {
      const advice = (ai.top_bottlenecks || []).find(b => b.subject === item.subject && b.chapter === item.chapter);
      const tr = document.createElement("tr");
      [item.subject, item.chapter, `${item.average_pct}%`, advice?.suggested_administrative_action || "Review these results with the subject teacher."].forEach(value => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    if (!metrics.curriculum_bottlenecks.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.textContent = "No chapter averages below 50% in the uploaded records.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    document.getElementById("principal-teacher-support").textContent = ai.teacher_support_recommendations;
  } catch (err) {
    if (request === principalRequest) summaryEl.textContent = err.message;
  }
}

// ==========================================
// 7. Cost Calculator & Batch
// ==========================================
async function recalcCost() {
  const studentCount = parseInt(document.getElementById("sim-student-count").value) || 1500;
  const frequency = document.getElementById("sim-frequency").value;

  try {
    const res = await fetch(`/api/cost-calculator?students=${studentCount}&frequency=${frequency}`);
    const data = await res.json();

    document.getElementById("calc-cost-usd").textContent = `$${data.gemini_total_usd} USD`;
    document.getElementById("calc-cost-inr").textContent = `₹ ${data.gemini_total_inr} / month`;
    document.getElementById("calc-per-student").textContent = `₹ ${data.cost_per_student_per_month_inr} INR`;
  } catch (err) {
    console.error("Failed to calculate cost:", err);
  }
}

async function runSimulatedBatch() {
  const btn = document.getElementById("btn-run-batch");
  const progEl = document.getElementById("batch-progress-text");
  btn.disabled = true;
  btn.textContent = "Processing async batch...";

  try {
    await fetch("/api/batch/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ concurrency: 5, stagger_delay_ms: 50 })
    });

    const timer = setInterval(async () => {
      const pollRes = await fetch("/api/batch/progress");
      const prog = await pollRes.json();
      progEl.textContent = `Completed ${prog.processed} / ${prog.total} students (${prog.percent}%) in ${prog.elapsed_seconds}s - Server CPU < 1%`;

      if (prog.status === "completed" || prog.processed >= prog.total) {
        clearInterval(timer);
        btn.disabled = false;
        btn.textContent = "🚀 Test Background Batch Runner";
      }
    }, 200);
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "🚀 Test Background Batch Runner";
  }
}
