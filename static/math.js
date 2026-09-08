const TEX_SYMBOLS = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", theta: "θ",
  lambda: "λ", mu: "μ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ", phi: "φ",
  omega: "ω", Delta: "Δ", Gamma: "Γ", Lambda: "Λ", Omega: "Ω", Sigma: "Σ",
  times: "×", cdot: "·", pm: "±", le: "≤", ge: "≥", ne: "≠", degree: "°",
};

function texGroup(expression, start) {
  if (expression[start] !== "{") return { value: expression[start] || "", next: start + 1 };
  let depth = 1;
  for (let index = start + 1; index < expression.length; index += 1) {
    if (expression[index] === "{") depth += 1;
    if (expression[index] === "}") depth -= 1;
    if (depth === 0) return { value: expression.slice(start + 1, index), next: index + 1 };
  }
  return { value: expression.slice(start + 1), next: expression.length };
}

function texNodes(expression) {
  const fragment = document.createDocumentFragment();
  let text = "";
  const flush = () => {
    if (text) fragment.appendChild(document.createTextNode(text));
    text = "";
  };

  for (let index = 0; index < expression.length;) {
    const character = expression[index];
    if (character === "^" || character === "_") {
      flush();
      const group = texGroup(expression, index + 1);
      const element = document.createElement(character === "^" ? "sup" : "sub");
      element.appendChild(texNodes(group.value));
      fragment.appendChild(element);
      index = group.next;
      continue;
    }
    if (character === "\\") {
      const match = expression.slice(index + 1).match(/^[A-Za-z]+/);
      if (!match) {
        text += expression[index + 1] || "";
        index += 2;
        continue;
      }
      flush();
      const command = match[0];
      index += command.length + 1;
      if (["mathrm", "textrm", "text"].includes(command) && expression[index] === "{") {
        const group = texGroup(expression, index);
        const roman = document.createElement("span");
        roman.className = "math-roman";
        roman.appendChild(texNodes(group.value));
        fragment.appendChild(roman);
        index = group.next;
      } else {
        fragment.appendChild(document.createTextNode(TEX_SYMBOLS[command] || command));
      }
      continue;
    }
    if (character !== "{" && character !== "}") text += character;
    index += 1;
  }
  flush();
  return fragment;
}

function renderMathIn(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);
  const pattern = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]|\[latex\]([\s\S]+?)\[\/latex\]/g;

  textNodes.forEach((node) => {
    const source = node.nodeValue || "";
    pattern.lastIndex = 0;
    if (!pattern.test(source)) return;
    pattern.lastIndex = 0;
    const replacement = document.createDocumentFragment();
    let lastIndex = 0;
    let match;
    while ((match = pattern.exec(source)) !== null) {
      replacement.appendChild(document.createTextNode(source.slice(lastIndex, match.index)));
      const math = document.createElement("span");
      math.className = match[2] ? "card-math display-math" : "card-math";
      math.setAttribute("role", "math");
      math.appendChild(texNodes(match[1] || match[2] || match[3] || ""));
      replacement.appendChild(math);
      lastIndex = pattern.lastIndex;
    }
    replacement.appendChild(document.createTextNode(source.slice(lastIndex)));
    node.parentNode.replaceChild(replacement, node);
  });
}

window.renderCardMath = renderMathIn;
