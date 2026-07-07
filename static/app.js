// MedSentry dashboard client — no build step, no framework, talks to the
// FastAPI endpoints in app/web.py. Renders progressively as each fetch
// resolves rather than blocking on everything at once.

const $ = (sel) => document.querySelector(sel);

async function getJSON(url) {
  const res = await fetch(url);
  const body = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, body };
}

function severityRank(sev) {
  return { major: 0, moderate: 1, minor: 2 }[sev] ?? 3;
}

function renderMode(mode) {
  const pill = $("#mode-pill");
  const live = mode.live_mode_available;
  pill.textContent = live ? `LIVE · ${mode.model}` : "DEMO MODE (offline, deterministic)";
  pill.classList.toggle("live", live);
}

function renderTimeline(schedule) {
  const track = $("#timeline-track");
  track.innerHTML = "";
  if (!schedule.length) {
    track.innerHTML = `<p class="no-flags">No scheduled doses.</p>`;
    return;
  }
  schedule.forEach((slot, i) => {
    const stop = document.createElement("div");
    stop.className = "timeline-stop";
    stop.style.animationDelay = `${i * 0.08}s`;
    stop.innerHTML = `
      <div class="timeline-dot"></div>
      <div class="timeline-time">${slot.time}</div>
      <div class="timeline-items">${slot.items.join(", ")}</div>
    `;
    track.appendChild(stop);
  });
}

function renderSafety(flags, disclaimer) {
  const el = $("#safety-flags");
  el.innerHTML = "";
  if (!flags.length) {
    el.innerHTML = `<p class="no-flags">✓ No known interactions among today's medications.</p>`;
  } else {
    flags
      .slice()
      .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
      .forEach((f) => {
        const div = document.createElement("div");
        div.className = `flag ${f.severity}`;
        div.innerHTML = `
          <span class="flag-severity">${f.severity}</span> — ${f.a} + ${f.b}<br>
          ${f.risk}
          <div class="flag-action">→ ${f.action}</div>
        `;
        el.appendChild(div);
      });
  }
  $("#disclaimer").textContent = disclaimer;
}

function renderCircle(patientName, circle, consent) {
  const sharedScopes = Object.entries(consent).filter(([, v]) => v).map(([k]) => k);
  const withheldScopes = Object.entries(consent).filter(([, v]) => !v).map(([k]) => k);
  const n = circle.length;
  const cx = 110, cy = 100, r = 68;
  const nodeR = 22;

  let svg = `<svg viewBox="0 0 220 200" width="100%" height="200" role="img" aria-label="Circle of care diagram">`;
  circle.forEach((person, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    const inLoop = sharedScopes.length > 0;
    svg += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${inLoop ? '#2f5d53' : '#5b6b65'}" stroke-width="1.5" stroke-dasharray="${inLoop ? '0' : '4,3'}" />`;
  });
  circle.forEach((person, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    const initials = person.name.split(" ").map((p) => p[0]).slice(0, 2).join("");
    svg += `
      <circle cx="${x}" cy="${y}" r="${nodeR}" fill="#fbfaf5" stroke="#b8862b" stroke-width="1.5"/>
      <text x="${x}" y="${y + 4}" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="12" fill="#1c2b27">${initials}</text>
      <text x="${x}" y="${y + nodeR + 13}" text-anchor="middle" font-family="IBM Plex Sans, sans-serif" font-size="9" fill="#5b6b65">${person.relationship}</text>
    `;
  });
  const patientInitials = patientName.split(" ").map((p) => p[0]).slice(0, 2).join("");
  svg += `
    <circle cx="${cx}" cy="${cy}" r="26" fill="#2f5d53" />
    <text x="${cx}" y="${cy + 5}" text-anchor="middle" font-family="Fraunces, serif" font-size="15" fill="#fbfaf5">${patientInitials}</text>
  `;
  svg += `</svg>`;
  $("#circle-of-care").innerHTML = svg;
  $("#circle-caption").textContent =
    withheldScopes.length > 0
      ? `Sharing: ${sharedScopes.join(", ") || "none"}. Withheld (no consent): ${withheldScopes.join(", ")}.`
      : `Sharing: ${sharedScopes.join(", ")}.`;
}

async function renderAuditLog(role) {
  document.querySelectorAll(".role-btn").forEach((b) => b.classList.toggle("active", b.dataset.role === role));
  const box = $("#audit-ledger");
  const { ok, body } = await getJSON(`/api/audit-log?role=${encodeURIComponent(role)}`);
  box.innerHTML = "";
  if (!ok) {
    box.innerHTML = `<p style="color:var(--brick); font-size:0.85rem;">🔒 Access denied for role "${role}": ${body.detail || "not permitted"}. <em>This is RBAC working as designed — try "patient".</em></p>`;
    return;
  }
  body.events
    .slice()
    .reverse()
    .slice(0, 8)
    .forEach((e) => {
      const row = document.createElement("div");
      row.className = "ledger-row";
      row.innerHTML = `<span>${e.timestamp.replace("T", " ").slice(0, 19)} · ${e.action}</span><span class="ledger-outcome ${e.outcome}">${e.outcome}</span>`;
      box.appendChild(row);
    });
}

async function boot() {
  const [{ body: mode }, { body: summary }] = await Promise.all([
    getJSON("/api/mode"),
    getJSON("/api/summary"),
  ]);

  renderMode(mode);
  $("#patient-name").textContent = summary.patient_name;
  renderTimeline(summary.daily_schedule);
  renderSafety(summary.safety_flags, summary.disclaimer);
  renderCircle(summary.patient_name, summary.caregiver_circle, summary.consent);

  document.querySelectorAll(".role-btn").forEach((btn) => {
    btn.addEventListener("click", () => renderAuditLog(btn.dataset.role));
  });
  renderAuditLog("patient");
}

boot().catch((err) => {
  console.error(err);
  document.body.innerHTML = `<div class="app"><p style="color:#a13d2b">Could not reach the MedSentry API. Is the server running? Try: <code>python -m app.cli serve</code></p></div>`;
});
