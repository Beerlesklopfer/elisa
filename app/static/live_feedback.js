// Live-Lektor: schickt den getippten Text debounced an den Feedback-Endpoint
// und zeigt die Antwort als nicht-blockierende, interaktive Toasts
// (notice | checkbox | radio | form).
//
// Der Text wird hier NICHT gespeichert -- das uebernimmt das normale
// Speichern des Formulars, mit dem Menschen als Autor. Referenz- oder
// Form-Vorschlaege wirken erst durch einen bewussten Klick.

const FEEDBACK_ENDPOINT = "/api/writing-feedback/";
const POLL_ENDPOINT = "/api/feedback-poll/";   // async: wartet aufs MCP-Team
const ACTION_ENDPOINT = "/api/toast-action/"; // menschlich angestossen
const DEBOUNCE_MS = 800;

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function getCookie(name) {
  const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
  return m ? m.pop() : "";
}

async function postJSON(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCookie("elisa_csrftoken"),
    },
    body: JSON.stringify(data),
  });
  return res.json();
}

function itemId() {
  return document.getElementById("item-body").dataset.itemId;
}

// Verzweigt ueber den Toast-Typ und baut das passende Steuerelement.
function renderToast(toast) {
  const el = document.createElement("div");
  el.className = `toast toast-${toast.severity || "info"}`;
  el.append(Object.assign(document.createElement("span"), { textContent: toast.message }));

  if (toast.type === "radio" || toast.type === "checkbox") {
    (toast.options || []).forEach((opt) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = toast.type;
      input.name = `t-${toast.action}`;
      input.value = opt;
      label.append(input, document.createTextNode(" " + opt));
      el.append(label);
    });
  } else if (toast.type === "form") {
    (toast.fields || []).forEach((f) => {
      const input = document.createElement("input");
      input.name = f.name;
      input.placeholder = f.label;
      el.append(input);
    });
  }

  // notice ohne action verfaellt von selbst; alles Interaktive braucht Bestaetigung.
  if (toast.action) {
    const btn = document.createElement("button");
    btn.textContent = "Übernehmen";
    btn.onclick = () => submitToast(toast, el);
    el.append(btn);
  } else {
    setTimeout(() => el.remove(), 8000);
  }

  document.getElementById("toast-container").append(el);
}

// Sammelt die menschliche Auswahl/Eingabe und ruft den Aktions-Endpoint.
async function submitToast(toast, el) {
  const values = {};
  el.querySelectorAll("input").forEach((i) => {
    if (i.type === "checkbox" || i.type === "radio") {
      if (i.checked) (values[i.name] ||= []).push(i.value);
    } else {
      values[i.name] = i.value; // vom Menschen getippter Inhalt
    }
  });
  await postJSON(ACTION_ENDPOINT, { item: itemId(), action: toast.action, values });
  el.remove();
}

async function requestFeedback(draft, neighbours) {
  if (!draft.trim()) return;
  const data = await postJSON(FEEDBACK_ENDPOINT, { draft, neighbours, item: itemId() });
  if (data.toasts && data.toasts.length) data.toasts.forEach(renderToast);
  // Team-Antwort ist asynchron -> pollen, bis sie da ist.
  if (data.pending && data.request_id) pollFeedback(data.request_id, 0);
}

async function pollFeedback(id, tries) {
  if (tries > 30) return; // ~60s Geduld, dann gibt der Server eh Ollama frei
  try {
    const res = await fetch(POLL_ENDPOINT + "?id=" + encodeURIComponent(id));
    const d = await res.json();
    if (d.ready) {
      (d.toasts || []).forEach(renderToast);
      return;
    }
  } catch (e) { /* weiter versuchen */ }
  setTimeout(() => pollFeedback(id, tries + 1), 2000);
}

const editor = document.getElementById("item-body");
const neighbours = JSON.parse(
  document.getElementById("neighbours-data")?.textContent || "[]"
);

editor.addEventListener(
  "input",
  debounce(() => requestFeedback(editor.value, neighbours), DEBOUNCE_MS)
);
