/* mietly – kleine, abhängigkeitsfreie Oberflächenhelfer (plus htmx). */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // CSRF-Token für htmx-Anfragen
  document.addEventListener("htmx:configRequest", (e) => {
    const token = document.querySelector("meta[name=csrf-token]");
    if (token) e.detail.headers["X-CSRFToken"] = token.content;
  });

  // ---------- Theme ----------
  function currentTheme() {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr) return attr;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("mietly-theme", next); } catch (err) { /* ignorieren */ }
  });

  // ---------- Navigation (mobil) ----------
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-nav-toggle]")) {
      document.body.classList.toggle("nav-open");
    } else if (document.body.classList.contains("nav-open") && !e.target.closest(".sidebar")) {
      document.body.classList.remove("nav-open");
    }
  });

  const topbar = $(".topbar");
  if (topbar) {
    const onScroll = () => topbar.classList.toggle("scrolled", window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ---------- Meldungen ----------
  function dismiss(toast) {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 220);
  }
  function armToasts(root = document) {
    $$(".toast", root).forEach((t) => {
      if (t.dataset.armed) return;
      t.dataset.armed = "1";
      const ms = t.classList.contains("toast-error") ? 9000 : 5000;
      setTimeout(() => dismiss(t), ms);
    });
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-dismiss]");
    if (b) dismiss(b.closest(".toast"));
  });
  armToasts();
  document.addEventListener("htmx:afterSwap", () => armToasts());

  // ---------- Schrittleiste: gewählten Schritt auf schmalen Bildschirmen sichtbar machen ----------
  const selectedStep = $(".stepper li.selected");
  if (selectedStep) {
    const list = selectedStep.parentElement;
    if (list.scrollWidth > list.clientWidth) {
      list.scrollLeft = selectedStep.offsetLeft - list.clientWidth / 2 + selectedStep.clientWidth / 2;
    }
  }

  // ---------- Mengen-Stepper (− / +) für Touch-Bedienung ----------
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".num-stepper [data-step]");
    if (!btn) return;
    const input = btn.parentElement.querySelector("input");
    const min = input.min !== "" ? Number(input.min) : -Infinity;
    const max = input.max !== "" ? Number(input.max) : Infinity;
    const next = Math.min(max, Math.max(min, (Number(input.value) || 0) + Number(btn.dataset.step)));
    input.value = next;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // ---------- Tabellenzeilen als Link ----------
  document.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-href]");
    if (!row || e.target.closest("a, button, input, select, textarea, label")) return;
    if (e.metaKey || e.ctrlKey) window.open(row.dataset.href, "_blank");
    else window.location = row.dataset.href;
  });

  // Zeilen auch per Tastatur öffnen (Tab + Enter)
  $$("tr[data-href]").forEach((row) => { if (!row.hasAttribute("tabindex")) row.tabIndex = 0; });
  document.addEventListener("keydown", (e) => {
    const row = e.target.closest && e.target.closest("tr[data-href]");
    if (row && e.target === row && e.key === "Enter") window.location = row.dataset.href;
  });

  // ---------- Bestätigungen (eigener Dialog statt Browser-Popup) ----------
  let confirmDialog = null;
  function getConfirmDialog() {
    if (confirmDialog) return confirmDialog;
    confirmDialog = document.createElement("dialog");
    confirmDialog.className = "modal confirm-modal";
    confirmDialog.innerHTML =
      '<div class="modal-body"><h2 class="confirm-title">Sind Sie sicher?</h2><p class="confirm-text"></p></div>' +
      '<div class="modal-foot"><button class="btn" type="button" data-answer="no">Abbrechen</button>' +
      '<button class="btn btn-primary" type="button" data-answer="yes">Bestätigen</button></div>';
    document.body.appendChild(confirmDialog);
    return confirmDialog;
  }
  function askConfirm(message, { okLabel, danger }) {
    return new Promise((resolve) => {
      const dlg = getConfirmDialog();
      $(".confirm-text", dlg).textContent = message;
      const ok = $("[data-answer=yes]", dlg);
      ok.textContent = okLabel || "Bestätigen";
      ok.classList.toggle("btn-danger-solid", !!danger);
      const done = (answer) => {
        dlg.removeEventListener("click", onClick);
        dlg.removeEventListener("cancel", onCancel);
        if (dlg.open) dlg.close();
        resolve(answer);
      };
      const onClick = (e) => {
        const b = e.target.closest("[data-answer]");
        if (b) done(b.dataset.answer === "yes");
        else if (e.target === dlg) done(false);
      };
      const onCancel = (e) => { e.preventDefault(); done(false); };
      dlg.addEventListener("click", onClick);
      dlg.addEventListener("cancel", onCancel);
      dlg.showModal();
      ok.focus();
    });
  }
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const msg = form.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (!msg) return;
    if (form.dataset.confirmed) { delete form.dataset.confirmed; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    const submitter = e.submitter;
    const label = submitter ? submitter.textContent.trim() : "";
    const danger = !!(submitter && (submitter.classList.contains("btn-danger") || submitter.closest(".btn-danger"))) || /lösch|storn|entfern|anonymis/i.test(msg);
    askConfirm(msg, { okLabel: label.length && label.length < 40 ? label : "Bestätigen", danger }).then((yes) => {
      if (!yes) return;
      form.dataset.confirmed = "1";
      if (submitter) form.requestSubmit(submitter); else form.requestSubmit();
    });
  }, true);

  // Doppeltes Absenden verhindern
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (e.defaultPrevented || form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) return;
    if (form.dataset.submitting) { e.preventDefault(); return; }
    form.dataset.submitting = "1";
    setTimeout(() => delete form.dataset.submitting, 4000);
  });


  // ---------- Längere Vorgänge: Knopf zeigt, dass gearbeitet wird ----------
  document.addEventListener("submit", (e) => {
    const btn = e.submitter;
    if (e.defaultPrevented || !btn || !btn.dataset.busy) return;
    // Erst nach dem Absenden deaktivieren, damit name/value des Knopfs mitgeschickt wird
    setTimeout(() => {
      btn.disabled = true;
      btn.textContent = btn.dataset.busy;
    }, 0);
  });


  // ---------- Ladeanzeige ----------
  const progress = document.createElement("div");
  progress.className = "progress-bar";
  progress.setAttribute("aria-hidden", "true");
  document.body.appendChild(progress);
  let pending = 0;
  let progressTimer = null;
  function startProgress() {
    pending += 1;
    clearTimeout(progressTimer);
    // Erst nach kurzer Zeit zeigen, damit schnelle Aktionen nicht flackern
    progressTimer = setTimeout(() => progress.classList.add("active"), 150);
  }
  function stopProgress() {
    pending = Math.max(0, pending - 1);
    if (pending === 0) {
      clearTimeout(progressTimer);
      progress.classList.remove("active");
    }
  }
  document.addEventListener("htmx:beforeRequest", (e) => {
    // Suchfelder laden laufend nach – dafür keinen Balken zeigen
    if (e.detail.elt && e.detail.elt.matches && e.detail.elt.matches("input[type=search]")) return;
    e.detail.elt.dataset.progress = "1";
    startProgress();
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    if (e.detail.elt && e.detail.elt.dataset.progress) {
      delete e.detail.elt.dataset.progress;
      stopProgress();
    }
  });
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (e.defaultPrevented || form.hasAttribute("hx-post") || form.hasAttribute("hx-get") || form.target === "_blank") return;
    startProgress();
  });
  window.addEventListener("pageshow", () => { pending = 0; clearTimeout(progressTimer); progress.classList.remove("active"); });

  // ---------- Ungespeicherte Eingaben ----------
  let dirtyForm = null;
  document.addEventListener("input", (e) => {
    const form = e.target.closest && e.target.closest("form[data-guard]");
    if (form) dirtyForm = form;
  });
  document.addEventListener("change", (e) => {
    const form = e.target.closest && e.target.closest("form[data-guard]");
    if (form && e.target.type !== "file") dirtyForm = form;
  });
  // Nur das Absenden des geänderten Formulars selbst gibt frei – ein anderes Formular
  // (z. B. Foto-Upload) würde die Eingaben sonst unbemerkt verwerfen.
  document.addEventListener("submit", (e) => { if (e.target === dirtyForm) dirtyForm = null; }, true);
  window.addEventListener("beforeunload", (e) => {
    if (dirtyForm && document.body.contains(dirtyForm)) {
      e.preventDefault();
      e.returnValue = "";
    }
  });

  // ---------- Dialoge ----------
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-modal]");
    if (opener) {
      const dlg = document.getElementById(opener.dataset.openModal);
      if (dlg) {
        dlg.showModal();
        // Auf Touch-Geräten keinen Fokus setzen, sonst klappt sofort die Tastatur auf
        if (!window.matchMedia("(pointer: coarse)").matches) {
          const first = dlg.querySelector("input:not([type=hidden]), select, textarea");
          if (first) first.focus();
        } else {
          document.activeElement && document.activeElement.blur();
        }
      }
      return;
    }
    const closer = e.target.closest("[data-close-modal]");
    if (closer) closer.closest("dialog").close();
  });
  document.addEventListener("click", (e) => {
    if (e.target.tagName === "DIALOG" && e.target.classList.contains("modal")) e.target.close();
  });
  // Formulare in Dialogen, die per htmx senden: nach Erfolg schließen und leeren
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt.closest && e.detail.elt.closest("form");
    const dlg = form && form.closest("dialog");
    if (dlg && e.detail.successful) {
      form.reset();
      dlg.close();
    }
  });
  // Nach dem Hinzufügen einer Position: Suchfeld leeren und Trefferliste schließen
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target && e.detail.target.id === "items") {
      const results = document.getElementById("picker-results");
      if (results) results.innerHTML = "";
      const search = document.querySelector(".item-picker input[type=search]");
      if (search && e.detail.requestConfig && /positionen\/neu/.test(e.detail.requestConfig.path)) search.value = "";
    }
  });
  document.addEventListener("click", (e) => {
    const results = document.getElementById("picker-results");
    if (results && results.innerHTML && !e.target.closest(".item-picker")) results.innerHTML = "";
  });

  // ---------- Dateiauswahl: automatisch absenden ----------
  document.addEventListener("change", (e) => {
    const input = e.target.closest("input[type=file][data-autosubmit]");
    if (input && input.files.length) input.form.requestSubmit();
    const select = e.target.closest("select[data-autosubmit-select]");
    if (select) select.form.requestSubmit();
  });

  // ---------- Platzhalter in Vorlagen einfügen ----------
  document.addEventListener("click", (e) => {
    const code = e.target.closest("[data-insert]");
    if (!code) return;
    const target = document.getElementById(code.dataset.target || "id_body");
    if (!target) return;
    const text = code.dataset.insert;
    const start = target.selectionStart, end = target.selectionEnd;
    target.value = target.value.slice(0, start) + text + target.value.slice(end);
    target.focus();
    target.selectionStart = target.selectionEnd = start + text.length;
  });

  // ---------- Ein-/Ausblenden abhängiger Felder ----------
  function syncToggles(root = document) {
    $$("[data-show-when]", root).forEach((el) => {
      const [name, value] = el.dataset.showWhen.split("=");
      const checked = $(`[name="${name}"]:checked`) || $(`select[name="${name}"]`);
      const current = checked ? checked.value : "";
      el.classList.toggle("hidden", current !== value);
    });
  }
  document.addEventListener("change", () => syncToggles());
  syncToggles();


  // ---------- Eventformular: Termine aus dem Eventdatum vorschlagen ----------
  function pad(n) { return String(n).padStart(2, "0"); }
  function localValue(d, time) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${time}`; }
  document.addEventListener("change", (e) => {
    const dateInput = e.target.closest("input[name=event_date]");
    if (!dateInput || !dateInput.value) return;
    const form = dateInput.form;
    const handover = form.querySelector("input[name=handover_at]");
    const ret = form.querySelector("input[name=return_at]");
    const [y, m, d] = dateInput.value.split("-").map(Number);
    const before = new Date(y, m - 1, d - 1);
    const after = new Date(y, m - 1, d + 1);
    let changed = false;
    // Nur leere oder zuvor automatisch vorgeschlagene Felder überschreiben
    if (handover && (!handover.value || handover.dataset.suggested === handover.value)) {
      handover.value = handover.dataset.suggested = localValue(before, "14:00");
      changed = true;
    }
    if (ret && (!ret.value || ret.dataset.suggested === ret.value)) {
      ret.value = ret.dataset.suggested = localValue(after, "10:00");
      changed = true;
    }
    const hint = document.getElementById("date-suggest-hint");
    if (hint && changed) hint.classList.remove("hidden");
  });

  // ---------- Felder aus anderen Angaben übernehmen ----------
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-fill]");
    if (!btn) return;
    const target = document.getElementById(btn.dataset.fill);
    const source = btn.dataset.fillFrom ? document.getElementById(btn.dataset.fillFrom) : null;
    const value = source ? source.value.trim() : (btn.dataset.value || "");
    if (!target) return;
    if (!value) {
      if (source) source.focus();
      return;
    }
    target.value = value;
    target.focus();
  });
  // Bei Wahl von „Lieferung“ eine leere Lieferadresse mit der Kundenanschrift vorbelegen
  document.addEventListener("change", (e) => {
    const radio = e.target.closest("input[name=fulfillment]");
    if (!radio || radio.value !== "delivery") return;
    const target = document.getElementById("id_delivery_address");
    const btn = document.querySelector("[data-fill=id_delivery_address][data-value]");
    if (target && !target.value.trim() && btn) target.value = btn.dataset.value;
  });

  // ---------- Befehlspalette / Suche (Strg+K) ----------
  const palette = $("#palette");
  if (palette) {
    const input = $("input", palette);
    const results = $(".palette-results", palette);
    let timer = null;
    let sel = -1;

    const open = () => {
      palette.classList.add("open");
      input.value = "";
      results.innerHTML = "";
      input.focus();
      load("");
    };
    const close = () => palette.classList.remove("open");
    const items = () => $$(".palette-item", results);
    const highlight = (i) => {
      const list = items();
      list.forEach((el) => el.classList.remove("sel"));
      if (!list.length) return;
      sel = (i + list.length) % list.length;
      list[sel].classList.add("sel");
      list[sel].scrollIntoView({ block: "nearest" });
    };
    let requestNo = 0;
    function load(q) {
      const no = ++requestNo;
      fetch(`${palette.dataset.url}?q=${encodeURIComponent(q)}`, { headers: { "X-Requested-With": "fetch" } })
        .then((r) => r.text())
        .then((html) => {
          if (no !== requestNo) return; // veraltete Antwort ignorieren
          results.innerHTML = html; sel = -1; highlight(0);
        });
    }

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        palette.classList.contains("open") ? close() : open();
      } else if (e.key === "Escape" && palette.classList.contains("open")) {
        close();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.target.closest("[data-open-search]")) open();
      else if (e.target === palette) close();
    });
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => load(input.value.trim()), 140);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); highlight(sel + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); highlight(sel - 1); }
      else if (e.key === "Enter") {
        const target = items()[sel];
        if (target) { e.preventDefault(); window.location = target.href; }
      }
    });
  }

  // ---------- Unterschriftenfeld ----------
  function initSignaturePad(wrap) {
    const canvas = $("canvas", wrap);
    const field = document.getElementById(wrap.dataset.field);
    const clearBtn = document.querySelector(`[data-clear-signature="${wrap.id}"]`);
    const ctx = canvas.getContext("2d");
    let drawing = false, empty = true, last = null, lastWidth = 2.2;
    const strokes = [];

    function resize() {
      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * ratio;
      canvas.height = rect.height * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#1b2a4a";
      redraw();
    }
    function redraw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      strokes.forEach((s) => {
        for (let i = 1; i < s.length; i++) segment(s[i - 1], s[i], s[i].w);
      });
    }
    function point(e) {
      const r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now() };
    }
    function segment(a, b, w) {
      ctx.lineWidth = w;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    canvas.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      drawing = true;
      last = point(e);
      last.w = 2.2;
      strokes.push([last]);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!drawing) return;
      const p = point(e);
      const dist = Math.hypot(p.x - last.x, p.y - last.y);
      if (dist < 0.8) return;
      const speed = dist / Math.max(p.t - last.t, 1);
      const pressure = e.pressure && e.pointerType === "pen" ? e.pressure : 0.5;
      const target = Math.max(1.1, Math.min(3.4, 3.2 - speed * 1.1 + (pressure - 0.5)));
      p.w = lastWidth * 0.6 + target * 0.4;
      lastWidth = p.w;
      segment(last, p, p.w);
      strokes[strokes.length - 1].push(p);
      last = p;
      empty = false;
    });
    const end = () => {
      if (!drawing) return;
      drawing = false;
      if (!empty) field.value = canvas.toDataURL("image/png");
      wrap.dispatchEvent(new CustomEvent("signature-change", { bubbles: true }));
    };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", end);
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        strokes.length = 0;
        empty = true;
        field.value = "";
        redraw();
        wrap.dispatchEvent(new CustomEvent("signature-change", { bubbles: true }));
      });
    }
    window.addEventListener("resize", resize);
    resize();
  }
  $$("[data-signature-pad]").forEach(initSignaturePad);

  // Absenden erst mit Unterschrift, Name und Bestätigung
  $$("form[data-sign-form]").forEach((form) => {
    const submit = $("[type=submit]", form);
    const check = () => {
      const sig = $("input[name=signature]", form);
      const name = $("input[name=signer_name]", form);
      const consent = $("input[name=consent]", form);
      submit.disabled = !(sig.value && name.value.trim() && (!consent || consent.checked));
    };
    form.addEventListener("input", check);
    form.addEventListener("change", check);
    form.addEventListener("signature-change", check);
    check();
  });
})();
