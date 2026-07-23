const form = document.querySelector("#pdfUploadForm");
const startButton = document.querySelector("#startPdfImport");
const statusPanel = document.querySelector("#pdfStatus");
const statusLabel = document.querySelector("#pdfStatusLabel");
const statusMessage = document.querySelector("#pdfStatusMessage");
const progressText = document.querySelector("#pdfProgressText");
const progressBar = document.querySelector("#pdfProgressBar");
const cancelButton = document.querySelector("#cancelPdfImport");
const review = document.querySelector("#draftReview");
const draftList = document.querySelector("#draftList");
const warningList = document.querySelector("#draftWarnings");
const deckName = document.querySelector("#pdfDeckName");
const saveButton = document.querySelector("#saveApprovedDrafts");

let currentJobId = null;
let pollTimer = null;

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({ error: "The server returned an invalid response." }));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed with status ${response.status}.`);
  }
  return payload;
}

function showError(message) {
  statusPanel.hidden = false;
  statusLabel.textContent = "Error";
  statusMessage.textContent = message;
  progressBar.style.width = "100%";
  progressBar.classList.add("is-error");
  cancelButton.hidden = true;
  startButton.disabled = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  review.hidden = true;
  statusPanel.hidden = false;
  cancelButton.hidden = false;
  progressBar.classList.remove("is-error");
  statusLabel.textContent = "Uploading";
  statusMessage.textContent = "The PDF will remain in temporary storage only while it is processed.";
  progressText.textContent = "0%";
  progressBar.style.width = "0%";
  startButton.disabled = true;
  try {
    const payload = await api("/api/pdf-imports", { method: "POST", body: new FormData(form) });
    currentJobId = payload.job_id;
    schedulePoll(100);
  } catch (error) {
    showError(error.message);
  }
});

function schedulePoll(delay = 1200) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(pollJob, delay);
}

async function pollJob() {
  if (!currentJobId) return;
  try {
    const { job } = await api(`/api/pdf-imports/${currentJobId}`);
    const readableStatus = job.status.replaceAll("_", " ");
    statusLabel.textContent = readableStatus.charAt(0).toUpperCase() + readableStatus.slice(1);
    progressText.textContent = `${job.progress}%`;
    progressBar.style.width = `${job.progress}%`;
    statusMessage.textContent = job.total_chunks
      ? `${job.processed_chunks} of ${job.total_chunks} source chunks processed.`
      : "Preparing the document…";
    if (["completed", "partially_completed"].includes(job.status)) {
      cancelButton.hidden = true;
      startButton.disabled = false;
      await loadDrafts();
    } else if (job.status === "failed") {
      showError(job.error_message || "PDF processing failed.");
    } else if (job.status === "cancelled") {
      showError("PDF processing was cancelled.");
    } else {
      schedulePoll();
    }
  } catch (error) {
    showError(error.message);
  }
}

cancelButton.addEventListener("click", async () => {
  if (!currentJobId) return;
  cancelButton.disabled = true;
  try {
    await api(`/api/pdf-imports/${currentJobId}/cancel`, { method: "POST" });
    statusMessage.textContent = "Cancellation requested. The current parser or model call may need to finish first.";
    schedulePoll(250);
  } catch (error) {
    showError(error.message);
  } finally {
    cancelButton.disabled = false;
  }
});

async function loadDrafts() {
  const { job, drafts } = await api(`/api/pdf-imports/${currentJobId}/drafts`);
  review.hidden = false;
  review.dataset.kind = job.kind;
  draftList.replaceChildren();
  warningList.replaceChildren();
  deckName.value = job.document_title || (job.kind === "mock_exam" ? "PDF mock exam" : "PDF flashcards");
  for (const warning of job.warnings) {
    const notice = document.createElement("p");
    notice.className = "notice warning";
    notice.textContent = warning;
    warningList.append(notice);
  }
  if (!drafts.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No questions were found. Try generation mode or a document with explicit question formatting.";
    draftList.append(empty);
  }
  drafts.forEach(renderDraft);
}

function labeledField(labelText, element) {
  const label = document.createElement("label");
  const title = document.createElement("span");
  title.textContent = labelText;
  label.append(title, element);
  return label;
}

function renderDraft(draft) {
  const card = document.createElement("article");
  card.className = "draft-card";
  card.dataset.draftId = draft.id;

  const top = document.createElement("div");
  top.className = "draft-card-top";
  const accepted = document.createElement("input");
  accepted.type = "checkbox";
  accepted.checked = draft.accepted;
  accepted.className = "draft-accepted";
  const acceptedLabel = labeledField("Include", accepted);
  acceptedLabel.className = "accept-control";
  const confidence = document.createElement("span");
  confidence.className = `confidence confidence-${draft.confidence >= 0.8 ? "high" : draft.confidence >= 0.6 ? "medium" : "low"}`;
  confidence.textContent = `${Math.round(draft.confidence * 100)}% confidence`;
  top.append(acceptedLabel, confidence);

  const question = document.createElement("textarea");
  question.value = draft.question;
  question.maxLength = 500;
  question.rows = 2;
  const answer = document.createElement("textarea");
  answer.value = draft.answer;
  answer.maxLength = 1500;
  answer.rows = 3;
  answer.placeholder = draft.requires_input ? "Answer required before saving" : "Answer";

  const choices = document.createElement("div");
  choices.className = "draft-choices";
  if (jobKind() === "mock_exam") {
    const heading = document.createElement("strong");
    heading.textContent = "Answer choices from the PDF";
    choices.append(heading);
    const list = document.createElement("ol");
    (JSON.parse(draft.options_json || "[]")).forEach((option) => {
      const item = document.createElement("li");
      item.textContent = option;
      list.append(item);
    });
    choices.append(list);
  }

  const source = document.createElement("div");
  source.className = "draft-source";
  const sourceMeta = document.createElement("strong");
  sourceMeta.textContent = [draft.section_title, draft.page_number ? `page ${draft.page_number}` : ""]
    .filter(Boolean).join(" · ") || "Source";
  const evidence = document.createElement("blockquote");
  evidence.textContent = draft.evidence;
  source.append(sourceMeta, evidence);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "secondary remove-draft";
  remove.textContent = "Reject and remove";

  accepted.addEventListener("change", () => updateDraft(draft.id, { accepted: accepted.checked }));
  question.addEventListener("change", () => updateDraft(draft.id, { question: question.value }));
  answer.addEventListener("change", () => updateDraft(draft.id, { answer: answer.value }));
  remove.addEventListener("click", async () => {
    try {
      await api(`/api/pdf-imports/${currentJobId}/drafts/${draft.id}`, { method: "DELETE" });
      card.remove();
    } catch (error) {
      showError(error.message);
    }
  });

  card.append(top, labeledField("Question", question), labeledField("Correct answer", answer), choices, source, remove);
  draftList.append(card);
}

function jobKind() {
  return review.dataset.kind || "flashcards";
}

async function updateDraft(draftId, values) {
  try {
    await api(`/api/pdf-imports/${currentJobId}/drafts/${draftId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
  } catch (error) {
    showError(error.message);
  }
}

async function setAllDrafts(accepted) {
  const controls = [...document.querySelectorAll(".draft-accepted")];
  await Promise.all(controls.map((control) => {
    control.checked = accepted;
    return updateDraft(Number(control.closest(".draft-card").dataset.draftId), { accepted });
  }));
}

document.querySelector("#selectAllDrafts").addEventListener("click", () => setAllDrafts(true));
document.querySelector("#deselectAllDrafts").addEventListener("click", () => setAllDrafts(false));

saveButton.addEventListener("click", async () => {
  saveButton.disabled = true;
  try {
    const payload = await api(`/api/pdf-imports/${currentJobId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deck_name: deckName.value }),
    });
    window.location.assign(`/deck/${payload.deck_id}`);
  } catch (error) {
    showError(error.message);
    saveButton.disabled = false;
  }
});
