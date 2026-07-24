const exam = window.MOCK_EXAM || { deck_id: null, questions: [] };
const questions = (exam.questions || []).map((question) => ({
  ...question,
  options: JSON.parse(question.options_json || "[]"),
}));
let index = 0;
const answers = new Map();
const evaluations = new Map();

const number = document.querySelector("#examNumber");
const progress = document.querySelector("#examProgressBar");
const questionNode = document.querySelector("#examQuestion");
const choices = document.querySelector("#examChoices");
const feedback = document.querySelector("#examFeedback");
const previous = document.querySelector("#previousQuestion");
const next = document.querySelector("#nextQuestion");
const submit = document.querySelector("#submitExam");
const form = document.querySelector("#examForm");
const results = document.querySelector("#examResults");

function render() {
  const question = questions[index];
  if (!question) {
    questionNode.textContent = "This test has no questions.";
    next.disabled = true;
    submit.disabled = true;
    return;
  }
  const evaluation = evaluations.get(index);
  number.textContent = String(index + 1);
  progress.style.width = `${((index + 1) / questions.length) * 100}%`;
  questionNode.textContent = question.front;
  questionNode.className = evaluation ? `is-${evaluation.correct ? "correct" : "wrong"}` : "";
  feedback.className = `exam-feedback${evaluation ? ` is-${evaluation.correct ? "correct" : "wrong"}` : ""}`;
  feedback.textContent = evaluation
    ? evaluation.correct ? "Correct." : `Incorrect. Correct answer: ${evaluation.correct_answer}`
    : "";
  choices.replaceChildren();
  question.options.forEach((option, optionIndex) => {
    const label = document.createElement("label");
    label.className = `exam-choice${evaluation && option === evaluation.correct_answer ? " is-correct" : ""}${evaluation && answers.get(index) === optionIndex && !evaluation.correct ? " is-selected-wrong" : ""}`;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = String(optionIndex);
    input.checked = answers.get(index) === optionIndex;
    input.disabled = Boolean(evaluation);
    input.addEventListener("change", () => gradeAnswer(question, optionIndex));
    const text = document.createElement("span");
    text.textContent = option;
    label.append(input, text);
    choices.append(label);
  });
  previous.disabled = index === 0;
  next.disabled = false;
  next.hidden = false;
  next.textContent = index === questions.length - 1 ? "Finish test" : "Next";
  submit.hidden = true;
}

async function gradeAnswer(question, optionIndex) {
  const questionIndex = index;
  if (evaluations.has(questionIndex)) return;
  answers.set(questionIndex, optionIndex);
  choices.querySelectorAll("input").forEach((input) => { input.disabled = true; });
  previous.disabled = true;
  next.disabled = true;
  try {
    const response = await fetch(`/api/decks/${exam.deck_id}/exam-answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: question.id, option_index: optionIndex }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "Could not check the answer.");
    evaluations.set(questionIndex, payload.result);
    render();
  } catch (error) {
    answers.delete(questionIndex);
    render();
    window.alert(error.message);
  }
}

previous.addEventListener("click", () => {
  index = Math.max(0, index - 1);
  render();
});
next.addEventListener("click", () => {
  if (index >= questions.length - 1) {
    form.requestSubmit();
    return;
  }
  index += 1;
  render();
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const review = document.createElement("ol");
  questions.forEach((question, questionIndex) => {
    const result = evaluations.get(questionIndex);
    const item = document.createElement("li");
    item.className = result?.correct ? "is-correct" : "is-wrong";
    item.textContent = result
      ? `${question.front} — ${result.correct ? "Correct" : `Correct answer: ${result.correct_answer}`}`
      : `${question.front} — Not answered`;
    review.append(item);
  });
  form.hidden = true;
  results.hidden = false;
  results.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = `Score: ${[...evaluations.values()].filter((result) => result.correct).length} / ${questions.length}`;
  results.append(heading, review);
});

render();
