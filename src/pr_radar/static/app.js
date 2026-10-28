"use strict";

const REFRESH_MS = 20000;
const ACTION_HEADERS = { "X-PR-Radar": "1" };

const CHECK_CHIPS = {
  SUCCESS: ["green", "✅ Checks pass"],
  FAILURE: ["red", "❌ Checks fail"],
  ERROR: ["red", "❌ Checks error"],
  PENDING: ["amber", "⏳ Checks running"],
  EXPECTED: ["amber", "⏳ Checks waiting"],
};
const REVIEW_CHIPS = {
  APPROVED: ["green", "👍 Approved"],
  CHANGES_REQUESTED: ["red", "✏️ Changes requested"],
  REVIEW_REQUIRED: ["", "👀 Needs review"],
};
const EVENT_ICONS = {
  new_comment: "💬",
  changes_requested: "✏️",
  ci_failed: "❌",
  merge_conflict: "⚔️",
  ready_to_merge: "🚀",
  review_requested: "👀",
  stale: "💤",
};
const SUMMARY_CHIPS = [
  ["to_reply", "red", "💬 to reply"],
  ["to_review", "red", "👀 to review"],
  ["to_fix", "red", "🛠️ to fix"],
  ["ready_to_merge", "green", "🚀 ready to merge"],
  ["waiting", "", "⏳ waiting"],
  ["stale", "amber", "💤 gone quiet"],
];

let seenEventIds = null;
let latestDashboard = null;

function el(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") node.textContent = value;
    else if (name === "className") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value);
  }
  for (const child of [].concat(children)) {
    if (child) node.append(child);
  }
  return node;
}

function externalLink(url, children, className = "") {
  return el("a", { href: url, target: "_blank", rel: "noopener noreferrer", className }, children);
}

function chip(colour, text, url) {
  const className = `chip ${colour}`.trim();
  return url ? externalLink(url, text, className) : el("span", { className, text });
}

function timeAgo(isoText) {
  const minutes = Math.round((Date.now() - new Date(isoText).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function clockTime(isoText) {
  return new Date(isoText).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function api(path, method = "GET") {
  const response = await fetch(path, { method, headers: method === "GET" ? {} : ACTION_HEADERS });
  if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status}`);
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response.text();
}

function minutesUntilTomorrowMorning() {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(9, 0, 0, 0);
  return Math.round((tomorrow - Date.now()) / 60000);
}

const SNOOZE_CHOICES = [
  ["1 hour", () => 60],
  ["4 hours", () => 240],
  ["Until tomorrow 9:00", minutesUntilTomorrowMorning],
  ["1 week", () => 60 * 24 * 7],
];

function snoozeMenu(view) {
  const wrapper = el("div", { className: "snooze-menu" });
  const options = el("div", { hidden: "" });
  for (const [label, minutes] of SNOOZE_CHOICES) {
    options.append(
      el("button", {
        className: "link-button",
        type: "button",
        text: label,
        onclick: async () => {
          await api(`/api/snooze/${encodeURIComponent(view.id)}?minutes=${minutes()}`, "POST");
          await refreshView();
        },
      }),
    );
  }
  const toggle = el("button", {
    className: "button small",
    type: "button",
    text: "😴 Snooze",
    onclick: () => options.toggleAttribute("hidden"),
  });
  wrapper.append(toggle, options);
  return wrapper;
}

function cardChips(view) {
  const chips = [chip("", `${view.repo.split("/").pop()} #${view.number}`)];
  if (view.role === "review") chips.push(chip("blue", `👤 by ${view.author}`));
  if (view.is_draft) chips.push(chip("", "📝 Draft"));
  if (view.check_state && CHECK_CHIPS[view.check_state]) chips.push(chip(...CHECK_CHIPS[view.check_state]));
  if (view.role === "mine" && view.review_decision && REVIEW_CHIPS[view.review_decision]) {
    chips.push(chip(...REVIEW_CHIPS[view.review_decision]));
  }
  if (view.mergeable === "CONFLICTING") chips.push(chip("red", "⚔️ Conflict"));
  const idleText = view.days_idle === 0 ? "🕒 Active today" : `🕒 Quiet ${view.days_idle} day(s)`;
  chips.push(chip(view.is_stale ? "amber" : "", idleText));
  for (const issue of view.jira) chips.push(chip("blue", `🎫 ${issue.key}: ${issue.status}`, issue.url));
  return chips;
}

function plainText(markdown) {
  return markdown.replace(/[*`#>]+/g, "").replace(/\s+/g, " ").trim();
}

function waitingComments(view) {
  if (!view.waiting_comments.length) return null;
  const items = view.waiting_comments.slice(-3).map((comment) =>
    el("li", {}, externalLink(comment.url, [el("strong", { text: comment.author }), plainText(comment.body).slice(0, 160)])),
  );
  return el("ul", { className: "comments" }, items);
}

function card(view, snoozedUntil) {
  const buttons = [externalLink(view.url, "Open PR ↗", "button small primary")];
  if (snoozedUntil) {
    buttons.push(el("span", { className: "muted", text: `Snoozed until ${new Date(snoozedUntil).toLocaleString()}` }));
    buttons.push(
      el("button", {
        className: "button small",
        type: "button",
        text: "Wake up",
        onclick: async () => {
          await api(`/api/snooze/${encodeURIComponent(view.id)}`, "DELETE");
          await refreshView();
        },
      }),
    );
  } else if (view.bucket === "needs_you") {
    buttons.push(snoozeMenu(view));
  }
  return el("article", { className: `card ${view.bucket}` }, [
    el("div", { className: "action", text: view.next_action }),
    el("div", { className: "title" }, externalLink(view.url, view.title)),
    el("div", { className: "meta" }, cardChips(view)),
    waitingComments(view),
    el("div", { className: "buttons" }, buttons),
  ]);
}

function renderNextUp(views, snoozed, hasChecked) {
  const box = document.getElementById("next-up");
  if (!hasChecked) {
    box.replaceChildren(el("div", { className: "action", text: "📡 Checking GitHub…" }));
    return;
  }
  const active = views.filter((view) => !snoozed[view.id]);
  const next = active.find((view) => view.bucket === "needs_you") || active.find((view) => view.bucket === "easy_win");
  box.replaceChildren();
  box.classList.toggle("done", !next);
  if (!next) {
    box.append(
      el("div", { className: "label", text: "Do this next" }),
      el("div", { className: "action", text: "🎉 Nothing needs you right now" }),
      el("div", { className: "pr-title", text: "Good time for deep work. I will tell you when something changes." }),
    );
    return;
  }
  box.append(
    el("div", { className: "label", text: "Do this next" }),
    el("div", { className: "action", text: next.next_action }),
    el("div", { className: "pr-title", text: `${next.title} · ${next.repo.split("/").pop()} #${next.number}` }),
    externalLink(next.url, "Open PR ↗", "button primary"),
  );
}

function renderSummary(summary) {
  const chips = [];
  for (const [field, colour, label] of SUMMARY_CHIPS) {
    if (summary[field]) chips.push(chip(colour, `${summary[field]} ${label}`));
  }
  document.getElementById("summary").replaceChildren(...chips);
}

function renderBuckets(views, snoozed) {
  const buckets = { needs_you: [], easy_win: [], waiting: [], snoozed: [] };
  for (const view of views) {
    const key = snoozed[view.id] ? "snoozed" : view.bucket;
    buckets[key].push(card(view, snoozed[view.id]));
  }
  for (const [key, cards] of Object.entries(buckets)) {
    const container = document.getElementById(`bucket-${key}`);
    container.replaceChildren(...(cards.length ? cards : [el("div", { className: "empty", text: "Nothing here 👌" })]));
  }
  document.getElementById("snoozed-group").hidden = buckets.snoozed.length === 0;
  document.getElementById("waiting-count").textContent = `(${buckets.waiting.length})`;
}

function renderStatus(dashboard) {
  const parts = [];
  if (dashboard.login) parts.push(`@${dashboard.login}`);
  if (dashboard.checked_at) parts.push(`synced ${clockTime(dashboard.checked_at)}`);
  parts.push(`every ${dashboard.light_check_seconds_now} s`);
  if (dashboard.light_check_seconds_now > dashboard.sync.light_check_seconds) parts.push("slowed down: GitHub points are low");
  if (!dashboard.is_work_time) parts.push("outside work hours: Mac alerts are off");
  document.getElementById("status").textContent = parts.join(" · ");

  const errorBanner = document.getElementById("error-banner");
  errorBanner.hidden = !dashboard.error;
  errorBanner.textContent = dashboard.error ? `⚠️ Could not check GitHub: ${dashboard.error}` : "";

  const focusBanner = document.getElementById("focus-banner");
  focusBanner.hidden = !dashboard.focus_until;
  focusBanner.replaceChildren();
  if (dashboard.focus_until) {
    focusBanner.append(
      `🎯 Focus mode until ${clockTime(dashboard.focus_until)}. Mac alerts are on hold.`,
      el("button", { className: "button small", type: "button", text: "End focus", onclick: endFocus }),
    );
  }

  const unread = document.getElementById("unread");
  unread.hidden = dashboard.unread === 0;
  unread.textContent = String(dashboard.unread);
  const needsYou = dashboard.summary.to_reply + dashboard.summary.to_review + dashboard.summary.to_fix;
  document.title = needsYou ? `(${needsYou}) PR Radar` : "PR Radar";
}

async function openEvent(event) {
  window.open(event.url, "_blank", "noopener");
  await api(`/api/events/${encodeURIComponent(event.id)}/read`, "POST");
  await refreshView();
}

function eventContent(event) {
  return [
    el("span", { className: "what", text: `${EVENT_ICONS[event.kind] || "•"} ${event.pr_title}` }),
    el("span", { text: event.message }),
    el("div", { className: "when", text: `${event.repo.split("/").pop()} · ${timeAgo(event.created_at)}` }),
  ];
}

function renderFeed(events) {
  const items = events.map((event) =>
    el("li", { className: event.read ? "" : "unread" }, [
      el("a", { href: event.url, onclick: (click) => { click.preventDefault(); openEvent(event); } }, eventContent(event)),
    ]),
  );
  document.getElementById("feed-list").replaceChildren(...(items.length ? items : [el("li", { className: "empty", text: "No updates yet." })]));
}

function showToasts(events) {
  if (seenEventIds === null) {
    seenEventIds = new Set(events.map((event) => event.id));
    return;
  }
  const container = document.getElementById("toasts");
  for (const event of events) {
    if (seenEventIds.has(event.id)) continue;
    seenEventIds.add(event.id);
    if (event.read) continue;
    const toast = el("div", { className: "toast" });
    toast.append(
      el("a", { href: event.url, onclick: (click) => { click.preventDefault(); toast.remove(); openEvent(event); } }, eventContent(event)),
      el("button", { className: "icon-button", type: "button", "aria-label": "Close", text: "✕", onclick: () => toast.remove() }),
    );
    container.prepend(toast);
  }
}

function render(dashboard) {
  latestDashboard = dashboard;
  renderStatus(dashboard);
  renderNextUp(dashboard.views, dashboard.snoozed_until, Boolean(dashboard.checked_at));
  renderSummary(dashboard.summary);
  renderBuckets(dashboard.views, dashboard.snoozed_until);
  renderFeed(dashboard.events);
  showToasts(dashboard.events);
}

async function refreshView() {
  try {
    render(await api("/api/dashboard"));
  } catch (error) {
    document.getElementById("status").textContent = "⚠️ PR Radar is not running";
  }
}

async function endFocus() {
  await api("/api/focus", "DELETE");
  await refreshView();
}

function wireDialogs() {
  for (const dialog of document.querySelectorAll("dialog")) {
    for (const closer of dialog.querySelectorAll("[data-close]")) closer.addEventListener("click", () => dialog.close());
  }
  const focusDialog = document.getElementById("focus-dialog");
  document.getElementById("focus-button").addEventListener("click", () => focusDialog.showModal());
  for (const button of focusDialog.querySelectorAll("[data-minutes]")) {
    button.addEventListener("click", async () => {
      await api(`/api/focus?minutes=${button.dataset.minutes}`, "POST");
      focusDialog.close();
      await refreshView();
    });
  }
  const reportDialog = document.getElementById("report-dialog");
  const reportText = document.getElementById("report-text");
  document.getElementById("report-button").addEventListener("click", async () => {
    reportText.textContent = "Loading…";
    reportDialog.showModal();
    try {
      reportText.textContent = await api("/api/report/weekly");
    } catch (error) {
      reportText.textContent = `Could not build the report: ${error.message}`;
    }
  });
  document.getElementById("copy-report").addEventListener("click", async (click) => {
    await navigator.clipboard.writeText(reportText.textContent);
    click.target.textContent = "Copied ✓";
    setTimeout(() => { click.target.textContent = "Copy"; }, 2000);
  });
}

function pointsEstimate(lightSeconds, fullMinutes, budget) {
  return Math.round((3600 / lightSeconds) * budget.light_cost + (60 / fullMinutes) * budget.full_cost);
}

function showEstimate() {
  const lightSeconds = Number(document.getElementById("light-seconds").value);
  const fullMinutes = Number(document.getElementById("full-minutes").value);
  const box = document.getElementById("settings-estimate");
  if (!lightSeconds || !fullMinutes || !latestDashboard) return;
  const limit = latestDashboard.rate_limit ? latestDashboard.rate_limit.limit : 5000;
  const estimate = pointsEstimate(lightSeconds, fullMinutes, latestDashboard.budget);
  const share = Math.round((estimate / limit) * 100);
  box.className = `estimate${share > 60 ? " danger" : share > 30 ? " warn" : ""}`;
  const advice = share > 60 ? " Too fast: GitHub may block your account for the rest of the hour." : "";
  box.textContent = `About ${estimate.toLocaleString()} of ${limit.toLocaleString()} GitHub points per hour (${share}%), plus a full check for each change.${advice}`;
}

function wireSettings() {
  const dialog = document.getElementById("settings-dialog");
  const lightInput = document.getElementById("light-seconds");
  const fullInput = document.getElementById("full-minutes");
  document.getElementById("settings-button").addEventListener("click", () => {
    lightInput.value = latestDashboard.sync.light_check_seconds;
    fullInput.value = latestDashboard.sync.full_check_minutes;
    const rate = latestDashboard.rate_limit;
    document.getElementById("settings-points").textContent = rate
      ? `GitHub points left now: ${rate.remaining.toLocaleString()} of ${rate.limit.toLocaleString()}. More come at ${clockTime(rate.reset_at)}.`
      : "";
    showEstimate();
    dialog.showModal();
  });
  lightInput.addEventListener("input", showEstimate);
  fullInput.addEventListener("input", showEstimate);
  document.getElementById("settings-form").addEventListener("submit", async (submit) => {
    submit.preventDefault();
    await api(`/api/settings/sync?light_check_seconds=${lightInput.value}&full_check_minutes=${fullInput.value}`, "POST");
    dialog.close();
    await refreshView();
  });
}

function wireButtons() {
  const feed = document.getElementById("feed");
  document.getElementById("feed-button").addEventListener("click", () => feed.toggleAttribute("hidden"));
  document.getElementById("feed-close").addEventListener("click", () => feed.setAttribute("hidden", ""));
  document.getElementById("read-all-button").addEventListener("click", async () => {
    await api("/api/events/read", "POST");
    await refreshView();
  });
  document.getElementById("refresh-button").addEventListener("click", async (click) => {
    click.target.disabled = true;
    try {
      render(await api("/api/refresh", "POST"));
    } finally {
      click.target.disabled = false;
    }
  });
  document.getElementById("test-alert-button").addEventListener("click", () => api("/api/test-alert", "POST"));
}

wireDialogs();
wireButtons();
wireSettings();
refreshView();
setInterval(refreshView, REFRESH_MS);
