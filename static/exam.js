const exam = window.MOCK_EXAM || { deck_id: null, questions: [] };
const questions = (exam.questions || []).map((question) => ({
  ...question,
  options: JSON.parse(question.options_json || "[]"),
}));
let index = 0;
const answers = new Map();

const number = document.querySelector("#examNumber");
const progress = document.querySelector("#examProgressBar");
const questionNode = document.querySelector("#examQuestion");
const choices = document.querySelector("#examChoices");
const previous = document.querySelector("#previousQuestion");
const next = document.querySelector("#nextQuestion");
const submit = document.querySelector("#submitExam");
const form = document.querySelector("#examForm");
const results = document.querySelector("#examResults");

function render() {
  const question = questions[index];
  if (!question) {
    questionNode.textContent = "This test has no questions.";
    submit.disabled = true;
    return;
  }
  number.textContent = String(index + 1);
  progress.style.width = `${((index + 1) / questions.length) * 100}%`;
  questionNode.textContent = question.front;
  choices.replaceChildren();
  question.options.forEach((option, optionIndex) => {
    const label = document.createElement("label");
    label.className = "exam-choice";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = String(optionIndex);
    input.checked = answers.get(index) === optionIndex;
    input.addEventListener("change", () => answers.set(index, optionIndex));
    const text = document.createElement("span");
    text.textContent = option;
    label.append(input, text);
    choices.append(label);
  });
  previous.disabled = index === 0;
  next.hidden = index === questions.length - 1;
  submit.hidden = index !== questions.length - 1;
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
  submit.disabled = true;
  try {
    const response = await fetch(`/api/decks/${exam.deck_id}/exam-submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: Object.fromEntries([...answers].map(([questionIndex, selected]) => [questions[questionIndex].id, selected])) }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "Could not submit the test.");
    const review = document.createElement("ol");
    payload.results.forEach((result) => {
    const item = document.createElement("li");
    item.className = result.correct ? "is-correct" : "is-wrong";
    item.textContent = `${result.question} — ${result.correct ? "Correct" : `Correct answer: ${result.correct_answer}`}`;
    review.append(item);
    });
    form.hidden = true;
    results.hidden = false;
    results.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = `Score: ${payload.score} / ${questions.length}`;
    results.append(heading, review);
  } catch (error) {
    submit.disabled = false;
    window.alert(error.message);
  }
});

render();
