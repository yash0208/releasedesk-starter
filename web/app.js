"use strict";

const state = {
  releases: [],
  selectedId: "REL-1042",
  snapshot: null,
  requests: [],
  busy: false,
};
const $ = (id) => document.getElementById(id);
const statusLabel = {
  pending: "Awaiting review",
  approved: "Approved",
  rejected: "Rejected",
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = `notice${error ? " error" : ""}`;
  $("notice").hidden = false;
}

async function api(path, body) {
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  return { status: response.status, ok: response.ok, data };
}

function renderQueue() {
  const query = $("search").value.trim().toLowerCase();
  const filter = $("status-filter").value;
  const visible = state.releases.filter(
    (release) =>
      `${release.service} ${release.id}`.toLowerCase().includes(query) &&
      (filter === "all" || release.status === filter),
  );
  $("queue-count").textContent = String(visible.length);
  $("queue").replaceChildren();
  for (const release of visible) {
    const button = element(
      "button",
      `queue-item${release.id === state.selectedId ? " selected" : ""}`,
    );
    button.type = "button";
    button.setAttribute(
      "aria-pressed",
      String(release.id === state.selectedId),
    );
    button.setAttribute(
      "aria-label",
      `${release.service}, ${release.id}, ${statusLabel[release.status]}`,
    );
    const top = element("span", "queue-top");
    top.append(
      element("span", "", release.id),
      element("span", "", release.version),
    );
    const bottom = element("span", "queue-bottom");
    bottom.append(
      element("span", "", release.environment),
      element("span", `status ${release.status}`, statusLabel[release.status]),
    );
    button.append(top, element("strong", "", release.service), bottom);
    button.addEventListener("click", async () => {
      if (state.busy) return;
      state.selectedId = release.id;
      $("race-result").hidden = true;
      await load();
    });
    $("queue").append(button);
  }
  if (!visible.length)
    $("queue").append(element("p", "empty", "No releases match this filter."));
}

function setBusy(busy) {
  state.busy = busy;
  const actionable = state.snapshot?.status === "pending";
  for (const id of ["approve", "reject", "run-race"])
    $(id).disabled = busy || !actionable;
  for (const id of ["refresh", "reset", "reload-snapshot", "reviewer", "note"])
    $(id).disabled = busy;
  $("decision-hint").textContent = busy
    ? "Saving review…"
    : actionable
      ? "Review the release evidence before submitting."
      : "This release already has a recorded decision.";
}

function renderRelease(release) {
  $("release-id").textContent = release.id;
  $("environment").textContent = release.environment;
  $("service").textContent = release.service;
  $("version").textContent = release.version;
  $("revision").textContent = `Revision ${release.revision}`;
  $("status").textContent = statusLabel[release.status];
  $("status").className = `status ${release.status}`;
  $("risk").textContent = `${release.risk} risk`;
  $("summary").textContent = release.summary;
  $("snapshot").textContent = `Snapshot revision ${release.revision}`;
  $("checks").replaceChildren();
  for (const check of release.checks) {
    const row = element("div", "check-row");
    row.append(
      element(
        "span",
        `check-icon ${check.result}`,
        check.result === "passed" ? "✓" : "!",
      ),
      element("span", "", check.name),
      element(
        "span",
        "check-result",
        check.result === "passed" ? "Passed" : "Needs review",
      ),
    );
    $("checks").append(row);
  }
  setBusy(state.busy);
}

function renderAudit(events) {
  $("audit-count").textContent =
    `${events.length} ${events.length === 1 ? "event" : "events"}`;
  $("audit").replaceChildren();
  for (const event of events) {
    const row = element("div", "audit-event");
    const body = element("div", "audit-body");
    const top = element("div", "audit-top");
    const time = element(
      "time",
      "",
      new Date(event.created_at).toLocaleTimeString("en-CA", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
    );
    time.dateTime = event.created_at;
    top.append(
      element("strong", "", event.reviewer),
      element("span", `status ${event.decision}`, statusLabel[event.decision]),
      time,
    );
    body.append(
      top,
      element("p", "audit-note", event.note),
      element(
        "p",
        "audit-revision",
        `Submitted revision ${event.submitted_revision ?? "none"} → saved revision ${event.resulting_revision}`,
      ),
    );
    row.append(element("span", "audit-avatar", event.reviewer.slice(-1)), body);
    $("audit").append(row);
  }
  if (!events.length)
    $("audit").append(
      element(
        "p",
        "empty",
        "No decisions recorded yet. The first review will appear here.",
      ),
    );
}

function renderRequests() {
  $("request-count").textContent = String(state.requests.length);
  $("requests").replaceChildren();
  for (const request of [...state.requests].reverse()) {
    const node = element("div", "request");
    const header = element("div", "request-header");
    header.append(
      element("span", "", `${request.body.reviewer} · POST review`),
      element(
        "span",
        `http-status${request.status >= 400 ? " error" : ""}`,
        `HTTP ${request.status}`,
      ),
    );
    node.append(
      header,
      element(
        "pre",
        "",
        JSON.stringify(
          { request: request.body, response: request.data },
          null,
          2,
        ),
      ),
    );
    $("requests").append(node);
  }
  if (!state.requests.length)
    $("requests").append(
      element(
        "p",
        "empty",
        "Review requests and their HTTP responses will appear here.",
      ),
    );
}

async function load() {
  const result = await api("/api/releases");
  if (!result.ok) throw new Error("Could not load releases.");
  state.releases = result.data.releases;
  state.snapshot =
    state.releases.find((release) => release.id === state.selectedId) ??
    state.releases[0];
  renderQueue();
  $("empty-selection").hidden = Boolean(state.snapshot);
  $("release-content").hidden = !state.snapshot;
  if (!state.snapshot) return;
  state.selectedId = state.snapshot.id;
  renderRelease(state.snapshot);
  const audit = await api(`/api/releases/${state.selectedId}/audit`);
  if (!audit.ok) throw new Error("Could not load decision history.");
  renderAudit(audit.data.events);
}

async function sendReview(releaseId, body) {
  const result = await api(`/api/releases/${releaseId}/review`, body);
  state.requests.push({ body, status: result.status, data: result.data });
  state.requests = state.requests.slice(-6);
  renderRequests();
  return result;
}

async function decide(decision) {
  if (state.busy || !state.snapshot) return;
  const snapshot = { ...state.snapshot };
  setBusy(true);
  try {
    const result = await sendReview(snapshot.id, {
      reviewer: $("reviewer").value,
      decision,
      note: $("note").value,
      expected_revision: snapshot.revision,
    });
    notice(
      result.ok
        ? `${snapshot.id}: ${statusLabel[decision].toLowerCase()} and saved.`
        : `HTTP ${result.status}: ${result.data.error?.message ?? "Review could not be saved."}`,
      !result.ok,
    );
    await load();
  } catch (error) {
    notice(`Connection error: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

async function runRace() {
  if (state.busy || state.snapshot?.status !== "pending") return;
  const snapshot = { ...state.snapshot };
  setBusy(true);
  $("race-result").hidden = true;
  try {
    const results = await Promise.all([
      sendReview(snapshot.id, {
        reviewer: "Reviewer A",
        decision: "approved",
        note: "Reviewer A confirms the staging evidence.",
        expected_revision: snapshot.revision,
      }),
      sendReview(snapshot.id, {
        reviewer: "Reviewer B",
        decision: "rejected",
        note: "Reviewer B requests another rollback review.",
        expected_revision: snapshot.revision,
      }),
    ]);
    const statuses = results
      .map((result) => result.status)
      .sort((a, b) => a - b);
    const protectedResult = statuses[0] === 200 && statuses[1] === 409;
    $("race-result").className =
      `race-result${protectedResult ? " protected" : ""}`;
    $("race-result").textContent = protectedResult
      ? "HTTP 200 + 409. One decision saved; the stale review was rejected. Check that only one audit event was added."
      : statuses.every((status) => status === 200)
        ? "HTTP 200 + 200. Both reviews were accepted against the same revision. Inspect the conflicting audit events below."
        : `Received HTTP ${statuses.join(" + ")}. Inspect the response bodies before drawing a conclusion.`;
    $("race-result").hidden = false;
    await load();
  } catch (error) {
    notice(`Concurrent review could not complete: ${error.message}`, true);
  } finally {
    setBusy(false);
  }
}

$("copy-summary").addEventListener("click", async () => {
  const release = state.snapshot;
  if (!release) return;

  const summary = [
    `Release: ${release.id} - ${release.service}`,
    `Version: ${release.version}`,
    `Environment: ${release.environment}`,
    `Status: ${statusLabel[release.status]}`,
    `Risk: ${release.risk}`,
    "",
    "Change summary:",
    release.summary,
    "",
    "Readiness checks:",
    ...release.checks.map(
      (check) =>
        `- ${check.name}: ${check.result === "passed" ? "Passed" : "Needs review"}`,
    ),
  ].join("\n");

  try {
    await navigator.clipboard.writeText(summary);
    notice(`Review summary copied for ${release.id}.`);
  } catch {
    notice("Could not copy the review summary. Try again or copy the details manually.", true);
  }
});

$("search").addEventListener("input", renderQueue);
$("status-filter").addEventListener("change", renderQueue);
$("approve").addEventListener("click", () => decide("approved"));
$("reject").addEventListener("click", () => decide("rejected"));
$("run-race").addEventListener("click", runRace);
for (const id of ["refresh", "reload-snapshot"])
  $(id).addEventListener("click", () =>
    load()
      .then(() => notice("Latest release records loaded."))
      .catch((error) => notice(error.message, true)),
  );
$("reset").addEventListener("click", async () => {
  if (
    !confirm(
      "Reset only this local synthetic workspace? Review decisions and audit events will be cleared.",
    )
  )
    return;
  setBusy(true);
  try {
    const result = await api("/api/demo/reset", {
      confirm: "reset-synthetic-data",
    });
    if (!result.ok)
      throw new Error(result.data.error?.message ?? "Reset failed.");
    state.requests = [];
    $("race-result").hidden = true;
    renderRequests();
    await load();
    notice("Synthetic release records restored.");
  } catch (error) {
    notice(error.message, true);
  } finally {
    setBusy(false);
  }
});
load().catch((error) => notice(error.message, true));
