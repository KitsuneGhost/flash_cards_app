const cards = window.FLASHCARDS || [];

let index = 0;
let showingBack = false;

const cardNumber = document.querySelector("#cardNumber");
const progressBar = document.querySelector("#progressBar");
const studyCard = document.querySelector("#studyCard");
const sideLabel = document.querySelector("#sideLabel");
const cardContent = document.querySelector("#cardContent");
const flipButton = document.querySelector("#flipButton");
const wrongButton = document.querySelector("#wrongButton");
const rightButton = document.querySelector("#rightButton");

function currentCard() {
  return cards[index];
}

function updateButtons() {
  const disabled = cards.length === 0;
  flipButton.disabled = disabled;
  wrongButton.disabled = disabled || !showingBack;
  rightButton.disabled = disabled || !showingBack;
}

function renderCard() {
  if (cards.length === 0) {
    sideLabel.textContent = "Done";
    cardContent.innerHTML = "<p>No cards are available in this deck.</p>";
    cardNumber.textContent = "0";
    progressBar.style.width = "100%";
    updateButtons();
    return;
  }

  const card = currentCard();
  sideLabel.textContent = showingBack ? "Back" : "Front";
  cardContent.innerHTML = showingBack ? card.back : card.front;
  cardNumber.textContent = String(index + 1);
  progressBar.style.width = `${((index + 1) / cards.length) * 100}%`;
  studyCard.classList.toggle("is-back", showingBack);
  updateButtons();
}

function flipCard() {
  showingBack = !showingBack;
  renderCard();
}

async function record(result) {
  const card = currentCard();
  if (!card) return;

  try {
    await fetch("/api/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: card.id, result }),
    });
  } catch {
    // The local UI should keep moving even if a progress write fails.
  }

  index = (index + 1) % cards.length;
  showingBack = false;
  renderCard();
}

flipButton.addEventListener("click", flipCard);
studyCard.addEventListener("click", flipCard);
wrongButton.addEventListener("click", () => record("wrong"));
rightButton.addEventListener("click", () => record("correct"));

window.addEventListener("keydown", (event) => {
  if (event.key === " ") {
    event.preventDefault();
    flipCard();
  }
  if (event.key === "ArrowLeft" && showingBack) {
    record("wrong");
  }
  if (event.key === "ArrowRight" && showingBack) {
    record("correct");
  }
});

renderCard();
