// Beratungs-Chat (RAG-gestützt). Schickt die Nachricht an den Server, der
// Norm-Kontext holt, Ollama mit der Historie fragt und beides persistiert.
// Der Chat ist beratend und nie Quelle der Wahrheit (CLAUDE.md, Regel 3).
(function () {
  const history = document.getElementById("chat-history");
  const input = document.getElementById("chat-text");
  const sendBtn = document.getElementById("chat-send");
  if (!history || !input || !sendBtn) return;

  const sendUrl = history.dataset.sendUrl;
  const pollUrl = history.dataset.pollUrl;
  let lastId = parseInt(history.dataset.lastId || "0", 10) || 0;
  const seen = new Set();          // bereits gerenderte Server-Nachrichten-IDs (gegen Doppel)

  // Provider-Glyphen (Handle → {icon,color}) für die Absender-Icons.
  let GLYPHS = {};
  try { GLYPHS = JSON.parse(document.getElementById("participant-glyphs").textContent || "{}"); }
  catch (e) { GLYPHS = {}; }
  function glyphFor(sender) {
    var s = (sender || "").trim();
    if (GLYPHS[s]) return GLYPHS[s];                  // exakter Klarname (z. B. Wendelin)
    var m = s.match(/@([\wäöüÄÖÜß\-]+)/);
    if (m) return GLYPHS[m[1]] || GLYPHS[m[1].toLowerCase()] || null;
    return null;
  }
  // Provider-/Typ-spezifische Hintergrund-Tönung der Sprechblase. LLM/RAG → ihre
  // Provider-Farbe; Mensch → neutrales Grau. Sehr blasser Alpha-Anteil, damit der
  // Text lesbar bleibt; zusätzlich ein farbiger Akzent links als Typ-Marker.
  function tintBubble(bubble, sender, role) {
    var g = glyphFor(sender);
    var color = (g && g.color) ? g.color : (role === "user" ? "#6c757d" : null);
    if (!color) return;
    bubble.style.background = color + "14";           // ~8% Deckkraft über Weiß
    bubble.style.borderLeft = "3px solid " + color;
  }

  function getCookie(name) {
    const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? m.pop() : "";
  }

  // Eingabezeile wächst mit dem Inhalt (kein internes Scrolling).
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = input.scrollHeight + "px";
  }
  input.addEventListener("input", autoGrow);
  autoGrow();

  // ── @-Wake-Character: Mention-Autocomplete über ALLE Teilnehmer ──
  // Datenquelle sind die Teilnehmer-Chips (.chat-mention) im DOM.
  const mentionPop = document.getElementById("mention-pop");
  let mpItems = [], mpActive = -1;
  function mpParticipants() {
    return Array.from(document.querySelectorAll(".chat-participants .chat-mention"))
      .map(function (ch) {
        const ico = ch.querySelector("i");
        return { handle: ch.dataset.handle || "",
                 label: ((ch.getAttribute("title") || "").split(" · ")[0]) || "",
                 iconClass: ico ? ico.className.replace(/\bme-1\b/, "").trim() : "fas fa-user",
                 iconColor: ico ? ico.style.color : "" };
      }).filter(function (p) { return p.handle; });
  }
  function mpClose() { if (mentionPop) { mentionPop.classList.add("d-none"); mentionPop.innerHTML = ""; } mpItems = []; mpActive = -1; }
  function mpQueryAt() {                         // aktives @-Token direkt vor dem Cursor?
    const pos = input.selectionStart;
    const m = input.value.slice(0, pos).match(/(^|\s)@([\wäöüÄÖÜß\-]*)$/);
    return m ? { query: m[2], start: pos - m[2].length - 1 } : null;
  }
  function mpRender(q) {
    if (!mentionPop) return;
    const ql = q.toLowerCase();
    mpItems = mpParticipants().filter(function (p) {
      return p.handle.toLowerCase().indexOf(ql) >= 0 || p.label.toLowerCase().indexOf(ql) >= 0;
    });
    if (!mpItems.length) { mpClose(); return; }
    mpActive = 0;
    mentionPop.innerHTML = mpItems.map(function (p, i) {
      return '<div class="mention-opt' + (i === 0 ? ' active' : '') + '" data-i="' + i + '">'
        + '<i class="' + p.iconClass + ' me-2"' + (p.iconColor ? (' style="color:' + p.iconColor + '"') : '') + '></i>'
        + '<strong>@' + escapeHtml(p.handle) + '</strong>'
        + (p.label ? ' <span class="text-muted small ms-1">' + escapeHtml(p.label) + '</span>' : '')
        + '</div>';
    }).join("");
    mentionPop.classList.remove("d-none");
  }
  function mpMove(d) {
    if (!mpItems.length) return;
    mpActive = (mpActive + d + mpItems.length) % mpItems.length;
    Array.from(mentionPop.children).forEach(function (el, i) { el.classList.toggle("active", i === mpActive); });
    const act = mentionPop.children[mpActive]; if (act) act.scrollIntoView({ block: "nearest" });
  }
  function mpChoose(i) {
    const p = mpItems[i], ctx = mpQueryAt();
    if (!p || !ctx) { mpClose(); return; }
    const before = input.value.slice(0, ctx.start), after = input.value.slice(input.selectionStart);
    const ins = "@" + p.handle + " ";
    input.value = before + ins + after;
    const np = (before + ins).length;
    input.focus(); input.setSelectionRange(np, np);
    mpClose(); autoGrow();
  }
  if (mentionPop) {
    input.addEventListener("input", function () {
      const ctx = mpQueryAt();
      if (ctx) mpRender(ctx.query); else mpClose();
    });
    // VOR dem Senden-Handler registriert → fängt Enter/Pfeile ab, wenn die Liste offen ist.
    input.addEventListener("keydown", function (e) {
      if (mentionPop.classList.contains("d-none")) return;
      if (e.key === "ArrowDown") { e.preventDefault(); e.stopImmediatePropagation(); mpMove(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); e.stopImmediatePropagation(); mpMove(-1); }
      else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopImmediatePropagation(); mpChoose(mpActive); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); mpClose(); }
    });
    mentionPop.addEventListener("mousedown", function (e) {
      const opt = e.target.closest(".mention-opt");
      if (opt) { e.preventDefault(); mpChoose(parseInt(opt.dataset.i, 10)); }
    });
    input.addEventListener("blur", function () { setTimeout(mpClose, 150); });
  }

  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s || ""; return d.innerHTML; }
  function withMentions(s) { return escapeHtml(s).replace(/(@[\wäöüÄÖÜß\-]+)/g, '<span class="mention">$1</span>'); }

  function addMessage(role, content, sources, sender) {
    const wrap = document.createElement("div");
    wrap.className = "chat-msg " + role;
    if (sender) {
      const sd = document.createElement("div");
      sd.className = "sender small text-muted mb-1";
      const g = glyphFor(sender);
      const i = document.createElement("i");
      i.className = "fas " + (g ? g.icon : (role === "user" ? "fa-user" : "fa-robot")) + " me-1";
      if (g && g.color) i.style.color = g.color;
      sd.appendChild(i);
      sd.appendChild(document.createTextNode(sender));
      wrap.appendChild(sd);
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = withMentions(content);
    tintBubble(bubble, sender, role);
    wrap.appendChild(bubble);
    if (sources && sources.length) {
      const s = document.createElement("div");
      s.className = "sources";
      s.appendChild(document.createTextNode("Quellen: "));
      sources.forEach((x, i) => {
        const a = document.createElement("a");
        a.href = "/normen/download/?name=" + encodeURIComponent(x.quelle);
        a.className = "norm-cite";
        a.dataset.name = x.quelle;
        a.dataset.page = x.seite || 1;
        a.textContent = x.quelle + (x.seite ? " S." + x.seite : "");
        s.appendChild(a);
        if (i < sources.length - 1) s.appendChild(document.createTextNode(", "));
      });
      wrap.appendChild(s);
    }
    history.appendChild(wrap);
    history.scrollTop = history.scrollHeight;
    return wrap;
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    autoGrow();                          // Höhe nach dem Leeren zurücksetzen
    const userBubble = addMessage("user", text, null, history.dataset.me || "Ich");
    sendBtn.disabled = true;
    addMessage("assistant", "");
    const placeholder = history.lastChild;
    // Laufende Tipp-Welle, solange die Antwort aussteht (wie in Chats üblich).
    placeholder.querySelector(".bubble").innerHTML =
      '<span class="typing"><span></span><span></span><span></span></span>';
    try {
      const res = await fetch(sendUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ message: text }),
      });
      let data = null;
      try { data = await res.json(); } catch (pe) { data = null; }
      placeholder.remove();
      if (!data) {
        // Server hat geantwortet, aber nicht-JSON (Timeout/500). Die Nachricht ist
        // serverseitig schon gespeichert → optimistische Blase entfernen und alles
        // per Poll nachladen (sonst Echo der EIGENEN Nachricht).
        if (userBubble) userBubble.remove();
        poll();
      } else {
        if (data.user && data.user.id) {
          if (seen.has(data.user.id)) {
            // Hintergrund-Poll war schneller und hat meine Nachricht schon gerendert
            // → die optimistische Blase ist das Doppel und fliegt raus.
            if (userBubble) userBubble.remove();
          } else {
            seen.add(data.user.id);
            if (userBubble) userBubble.dataset.mid = data.user.id;
          }
          lastId = Math.max(lastId, data.user.id);
        }
        if (data.assistant) {
          const aw = addMessage("assistant", data.assistant.content, data.assistant.sources,
                                data.assistant.sender || "Assistent");
          if (data.assistant.id) { aw.dataset.mid = data.assistant.id; seen.add(data.assistant.id); }
          lastId = Math.max(lastId, data.assistant.id || 0);
        }
        // assistant === null → @-erwähnte Personas antworten asynchron (per Poll).
        if (!data.assistant) startWait();   // Wartemarke […], bis Antworten kommen
        poll();
      }
    } catch (e) {
      // Echter Netzwerkfehler (keine Server-Antwort) → Nachricht evtl. nicht
      // gespeichert → optimistische Blase behalten, Hinweis anzeigen.
      placeholder.querySelector(".bubble").textContent =
        "(Netzwerkfehler beim Senden: " + e + ")";
    } finally {
      sendBtn.disabled = false;
    }
  }

  // Wartemarke […] solange auf (asynchrone) Persona-Antworten gewartet wird.
  let waitBubble = null, waitUntil = 0;
  function makeWaitBubble() {
    const b = addMessage("assistant", "");
    b.querySelector(".bubble").innerHTML =
      '<span class="typing"><span></span><span></span><span></span></span>';
    return b;
  }
  function startWait() { waitUntil = Date.now() + 60000; if (!waitBubble) waitBubble = makeWaitBubble(); }
  function stopWait() { if (waitBubble) { waitBubble.remove(); waitBubble = null; } }

  // Live-Nachzug asynchroner Persona-/Inter-Persona-Antworten.
  async function poll() {
    if (!pollUrl) return;
    try {
      const res = await fetch(pollUrl + "?after=" + lastId);
      const data = await res.json();
      const msgs = data.messages || [];
      if (msgs.length) {
        stopWait();
        msgs.forEach(function (m) {
          lastId = Math.max(lastId, m.id || 0);
          if (m.id && seen.has(m.id)) return;          // schon gerendert (z. B. optimistisch)
          const w = addMessage(m.role, m.content, m.sources, m.sender);
          if (m.id) { w.dataset.mid = m.id; seen.add(m.id); }
        });
        if (Date.now() < waitUntil) waitBubble = makeWaitBubble();  // unten weiter warten
      }
      if (waitBubble && Date.now() >= waitUntil) stopWait();        // Timeout
    } catch (e) {}
  }
  setInterval(poll, 4000);

  // Server-gerenderte Nachrichten beim Laden mit Provider-Icons versehen.
  function applyProviderIcons() {
    history.querySelectorAll(".chat-msg").forEach(function (msg) {
      const s = msg.querySelector(".sender");
      const g = s ? glyphFor(s.textContent || "") : null;
      const i = s ? s.querySelector("i") : null;
      if (g && i) { i.className = "fas " + g.icon + " me-1"; if (g.color) i.style.color = g.color; }
      const bubble = msg.querySelector(".bubble");
      const role = msg.classList.contains("user") ? "user" : "assistant";
      if (bubble) tintBubble(bubble, s ? s.textContent : "", role);
    });
  }
  applyProviderIcons();

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  // ── Zitieren: Rechtsklick auf eine Nachricht → Antwort als Markdown-Zitat ins
  //    Eingabefeld, damit man inhaltlich Bezug nehmen kann (selbsttragend: der
  //    zitierte Text reist mit, jede Persona/jedes Tool sieht den Bezug). ──
  const msgCtx = document.getElementById("chat-msg-ctx");
  let citeTarget = null;
  function insertAtCursor(txt) {
    const s = input.selectionStart != null ? input.selectionStart : input.value.length;
    const en = input.selectionEnd != null ? input.selectionEnd : s;
    input.value = input.value.slice(0, s) + txt + input.value.slice(en);
    const np = s + txt.length;
    input.focus();
    input.setSelectionRange(np, np);
    autoGrow();
  }
  if (msgCtx) {
    history.addEventListener("contextmenu", function (e) {
      const msg = e.target.closest(".chat-msg");
      if (!msg || !history.contains(msg)) return;
      e.preventDefault();
      citeTarget = msg;
      msgCtx.style.left = Math.min(e.clientX, window.innerWidth - 200) + "px";
      msgCtx.style.top = Math.min(e.clientY, window.innerHeight - 60) + "px";
      msgCtx.classList.remove("d-none");
    });
    document.addEventListener("click", function (e) { if (!msgCtx.contains(e.target)) msgCtx.classList.add("d-none"); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") msgCtx.classList.add("d-none"); });
    msgCtx.querySelector('[data-act="cite"]').addEventListener("click", function (e) {
      e.preventDefault();
      msgCtx.classList.add("d-none");
      if (!citeTarget) return;
      const senderEl = citeTarget.querySelector(".sender");
      const bubbleEl = citeTarget.querySelector(".bubble");
      const who = senderEl ? (senderEl.textContent || "").trim() : "";
      const body = bubbleEl ? (bubbleEl.textContent || "").trim() : "";
      if (!body) return;
      // Markdown-Blockquote; mehrzeilig korrekt mit „> " je Zeile.
      const quoted = body.replace(/\n/g, "\n> ");
      const cite = (who ? "> **" + who + ":** " : "> ") + quoted + "\n\n";
      insertAtCursor(cite);
    });
  }

  // Persona/Teilnehmer-Chips: Klick fügt @handle an der Cursorposition ein
  // (Projekt-/allgemeiner Chat — wie im Item-Chat).
  document.addEventListener("click", (e) => {
    const chip = e.target.closest(".chat-mention");
    if (!chip || !input) return;
    e.preventDefault();
    insertAtCursor("@" + chip.dataset.handle + " ");
  });
})();
