// Beratungs-Chat (RAG-gestützt). Schickt die Nachricht an den Server, der
// Norm-Kontext holt, das lokale Modell (Eliezer/Ollama) mit der Historie fragt und beides persistiert.
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
  // @all richtet sich an alle Teilnehmer (Menschen und Personas).
  const ALL_ENTRY = { handle: "all", label: "alle Teilnehmer",
                      iconClass: "fas fa-users", iconColor: "" };
  function mpParticipants() {
    return [ALL_ENTRY].concat(Array.from(document.querySelectorAll(".chat-participants .chat-mention"))
      .map(function (ch) {
        const ico = ch.querySelector("i");
        return { handle: ch.dataset.handle || "",
                 label: ((ch.getAttribute("title") || "").split(" · ")[0]) || "",
                 iconClass: ico ? ico.className.replace(/\bme-1\b/, "").trim() : "fas fa-user",
                 iconColor: ico ? ico.style.color : "" };
      }).filter(function (p) { return p.handle; }));
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

  // ── Kopieren: Button an jeder Nachricht kopiert den ROH-Text (Markdown/Quelltext),
  //    nicht das gerenderte HTML. ──
  function ensureCopy(msg) {
    if (!msg || msg.querySelector(".chat-copy")) return;
    let sd = msg.querySelector(".sender");
    if (!sd) {
      sd = document.createElement("div");
      sd.className = "sender small text-muted mb-1";
      msg.insertBefore(sd, msg.firstChild);
    }
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chat-copy btn btn-sm btn-link p-0 ms-2 text-muted";
    b.title = (history.dataset.copyLabel || "Kopieren");
    b.innerHTML = '<i class="fas fa-copy"></i>';
    sd.appendChild(b);
  }
  // ── Einzelne Nachricht löschen: Button für eigene Nachrichten bzw. – mit Recht
  //    (data-can-delete-all) – für alle; der Server prüft das Recht erneut. ──
  function ensureDelete(msg) {
    if (!msg || msg.querySelector(".chat-del") || !msg.dataset.mid) return;
    if (!(history.dataset.canDeleteAll || msg.dataset.mine)) return;
    const sd = msg.querySelector(".sender");
    if (!sd) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chat-del btn btn-sm btn-link p-0 ms-2 text-danger";
    b.title = history.dataset.deleteLabel || "Löschen";
    b.innerHTML = '<i class="fas fa-trash-can"></i>';
    sd.appendChild(b);
  }
  history.addEventListener("click", async function (e) {
    const btn = e.target.closest(".chat-del");
    if (!btn) return;
    e.preventDefault();
    const msg = btn.closest(".chat-msg");
    if (!msg || !msg.dataset.mid) return;
    if (!window.confirm(history.dataset.deleteConfirm || "Diese Nachricht löschen?")) return;
    try {
      const res = await fetch(history.dataset.deleteUrl.replace("/0/", "/" + msg.dataset.mid + "/"),
                              { method: "POST", headers: { "X-CSRFToken": getCookie("elisa_csrftoken") } });
      if (res.ok) msg.remove();
    } catch (err) { /* Netzfehler: nichts ändern */ }
  });

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (e2) {}
      ta.remove(); return ok;
    }
  }
  history.addEventListener("click", async function (e) {
    const btn = e.target.closest(".chat-copy");
    if (!btn) return;
    e.preventDefault();
    const msg = btn.closest(".chat-msg");
    const raw = msg ? (msg.dataset.raw != null ? msg.dataset.raw
                       : (msg.querySelector(".bubble") || {}).innerText || "") : "";
    const ok = await copyText(raw);
    const ico = btn.querySelector("i");
    ico.className = ok ? "fas fa-check text-success" : "fas fa-triangle-exclamation text-danger";
    setTimeout(function () { ico.className = "fas fa-copy"; }, 1200);
  });

  function addMessage(role, content, sources, sender, html, reply) {
    const wrap = document.createElement("div");
    wrap.className = "chat-msg " + role;
    wrap.dataset.raw = content || "";
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
    if (reply && reply.text) {          // Bezug: worauf diese Nachricht antwortet
      const rr = document.createElement("div");
      rr.className = "reply-ref small text-muted";
      const ri = document.createElement("i");
      ri.className = "fas fa-reply me-1";
      rr.appendChild(ri);
      rr.appendChild(document.createTextNode(
        (history.dataset.replyLabel || "Antwort auf") + " " + (reply.sender || "") + ": „" + reply.text + "“"));
      wrap.appendChild(rr);
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = html || withMentions(content);   // html = serverseitig gerendertes Markdown
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
        a.target = "_blank"; a.rel = "noopener noreferrer";
        a.dataset.name = x.quelle;
        a.dataset.page = x.seite || 1;
        a.textContent = x.quelle + (x.seite ? " S." + x.seite : "");
        s.appendChild(a);
        if (i < sources.length - 1) s.appendChild(document.createTextNode(", "));
      });
      wrap.appendChild(s);
    }
    history.appendChild(wrap);
    if (content) ensureCopy(wrap);
    if (role === "user") { wrap.dataset.mine = "1"; ensureEdit(wrap); }   // optimistisch: meine eigene Nachricht
    history.scrollTop = history.scrollHeight;
    return wrap;
  }

  // ── Eingabe-Historie (wie in der Shell): ↑ = frühere eigene Nachricht, ↓ = spätere,
  //    ganz unten wieder der angefangene Entwurf. Quelle: meine Nachrichten dieser
  //    Session (serverseitig mit data-mine/data-raw markiert) + hier gesendete. ──
  const sentHistory = Array.from(history.querySelectorAll('.chat-msg[data-mine="1"]'))
    .map(function (el) { return el.dataset.raw || ""; }).filter(Boolean);
  let histPos = sentHistory.length, histDraft = "";
  function histSet(v) {
    input.value = v; autoGrow();
    input.setSelectionRange(v.length, v.length);
  }
  function remember(text) {
    if (text && sentHistory[sentHistory.length - 1] !== text) sentHistory.push(text);
    histPos = sentHistory.length; histDraft = "";
  }

  // ── Wer ist gemeint? Ohne @ geht eine Nachricht an die zuletzt angesprochene Persona
  //    (serverseitig dieselbe Regel); der Chip zeigt das aktuelle Ziel. ──
  const targetEl = document.getElementById("chat-target");
  function updateTarget(text) {
    if (!targetEl) return;
    const hits = [];
    (text.match(/@([\wäöüÄÖÜß\-]+)/g) || []).forEach(function (t) {
      const h = t.slice(1).toLowerCase();
      if (GLYPHS[h] && hits.indexOf(h) === -1) hits.push(h);
    });
    if (hits.length) targetEl.textContent = hits.map(function (h) { return "@" + h; }).join(", ");
  }

  // ── Bearbeiten: Text einer eigenen Nachricht ins Eingabefeld holen; Senden schickt
  //    sie NEU (die alte bleibt stehen und lässt sich mit dem Papierkorb entfernen). ──
  const editBanner = document.getElementById("chat-editing");
  function setEditing(on) { if (editBanner) editBanner.classList.toggle("d-none", !on); }
  function ensureEdit(msg) {
    if (!msg || msg.querySelector(".chat-edit") || !msg.dataset.mine) return;
    const sd = msg.querySelector(".sender");
    if (!sd) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chat-edit btn btn-sm btn-link p-0 ms-2 text-muted";
    b.title = history.dataset.editLabel || "Bearbeiten";
    b.innerHTML = '<i class="fas fa-pen"></i>';
    sd.appendChild(b);
  }
  history.addEventListener("click", function (e) {
    const btn = e.target.closest(".chat-edit");
    if (!btn) return;
    e.preventDefault();
    const msg = btn.closest(".chat-msg");
    if (!msg) return;
    histPos = sentHistory.length;
    histSet(msg.dataset.raw || "");
    setEditing(true);
    input.focus();
  });
  const editCancel = document.getElementById("chat-editing-cancel");
  if (editCancel) editCancel.addEventListener("click", function (e) {
    e.preventDefault(); input.value = ""; autoGrow(); setEditing(false);
  });

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    remember(text);
    updateTarget(text);
    setEditing(false);
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
          "X-CSRFToken": getCookie("elisa_csrftoken"),
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
            if (userBubble) {
              userBubble.dataset.mid = data.user.id; ensureDelete(userBubble);
              const ub = userBubble.querySelector(".bubble");       // Markdown wie auf dem Server
              if (ub && data.user.html) ub.innerHTML = data.user.html;
            }
          }
          lastId = Math.max(lastId, data.user.id);
        }
        if (data.assistant) {
          const aw = addMessage("assistant", data.assistant.content, data.assistant.sources,
                                data.assistant.sender || "Assistent", data.assistant.html);
          if (data.assistant.id) { aw.dataset.mid = data.assistant.id; seen.add(data.assistant.id); ensureDelete(aw); }
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
          const w = addMessage(m.role, m.content, m.sources, m.sender, m.html, m.reply);
          if (m.id) { w.dataset.mid = m.id; seen.add(m.id); ensureDelete(w); }
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
  history.querySelectorAll(".chat-msg").forEach(function (m) { ensureCopy(m); ensureEdit(m); ensureDelete(m); });

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  // NACH dem Mention-Handler registriert: ist die @-Liste offen, hat sie die Pfeile.
  input.addEventListener("keydown", (e) => {
    if ((e.key !== "ArrowUp" && e.key !== "ArrowDown") || e.shiftKey || e.altKey
        || e.ctrlKey || e.metaKey || !sentHistory.length) return;
    const before = input.value.slice(0, input.selectionStart);
    const after = input.value.slice(input.selectionEnd);
    if (e.key === "ArrowUp") {
      if (before.indexOf("\n") !== -1) return;          // nur in der ersten Zeile
      if (histPos === sentHistory.length) histDraft = input.value;
      if (histPos > 0) { e.preventDefault(); histPos--; histSet(sentHistory[histPos]); }
    } else {
      if (after.indexOf("\n") !== -1) return;           // nur in der letzten Zeile
      if (histPos < sentHistory.length) {
        e.preventDefault(); histPos++;
        histSet(histPos === sentHistory.length ? histDraft : sentHistory[histPos]);
      }
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
